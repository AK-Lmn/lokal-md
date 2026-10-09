"""Encryption of stored clinical data.

Design
------
* A random 256-bit data-encryption key (DEK) is generated once at first-run setup.
* The DEK is never stored in clear. For every user it is wrapped (AES-256-GCM) with a
  key-encryption key derived from that user's password using scrypt. A one-time recovery
  key wraps a further copy. Logging in = successfully unwrapping the DEK.
* Sensitive columns are encrypted individually with AES-256-GCM. The associated data binds
  each ciphertext to its table/column/row, so values cannot be swapped between rows.
* The DEK lives only in server process memory for the lifetime of a logged-in session.

SQLite itself provides no encryption; unencrypted metadata (IDs, timestamps, status,
user names, audit event names) remain visible to anyone with file access. Full-disk
encryption (e.g. BitLocker) is still recommended for the workstation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

PREFIX = "enc1:"
DEFAULT_SCRYPT_N = 2**15  # ~100 ms on a laptop; tests may lower via set_kdf_cost()
_scrypt_n = DEFAULT_SCRYPT_N


class CryptoError(Exception):
    pass


class WrongPassword(CryptoError):
    pass


def set_kdf_cost(n: int) -> None:
    global _scrypt_n
    _scrypt_n = n


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _derive(secret: str, salt: bytes, n: int, r: int = 8, p: int = 1) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(secret.encode("utf-8"))


def new_dek() -> bytes:
    return secrets.token_bytes(32)


def wrap_dek(dek: bytes, secret: str) -> str:
    """Wrap the DEK with a key derived from `secret` (password or recovery key)."""
    salt, nonce = os.urandom(16), os.urandom(12)
    n = _scrypt_n
    kek = _derive(secret, salt, n)
    ct = AESGCM(kek).encrypt(nonce, dek, b"rhuscribe-dek-wrap")
    return json.dumps({"v": 1, "n": n, "r": 8, "p": 1, "salt": _b64(salt), "nonce": _b64(nonce), "ct": _b64(ct)})


def unwrap_dek(wrapped: str, secret: str) -> bytes:
    try:
        d = json.loads(wrapped)
        kek = _derive(secret, _unb64(d["salt"]), d["n"], d.get("r", 8), d.get("p", 1))
        return AESGCM(kek).decrypt(_unb64(d["nonce"]), _unb64(d["ct"]), b"rhuscribe-dek-wrap")
    except InvalidTag as e:
        raise WrongPassword("Incorrect password or key") from e
    except (KeyError, ValueError) as e:
        raise CryptoError("Malformed key record") from e


def new_recovery_key() -> str:
    raw = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def normalize_recovery_key(s: str) -> str:
    return s.strip().upper().replace(" ", "")


class Vault:
    """Holds the DEK in memory and encrypts/decrypts field values."""

    def __init__(self, dek: bytes):
        if len(dek) != 32:
            raise CryptoError("Bad key length")
        self._dek = dek
        self._aes = AESGCM(dek)
        self._index_key = hmac.new(dek, b"rhuscribe-blind-index", hashlib.sha256).digest()

    def export_dek(self) -> bytes:
        """Only for wrapping the key for a new/reset user account."""
        return self._dek

    @staticmethod
    def aad(table: str, column: str, row_id: str) -> bytes:
        return f"{table}|{column}|{row_id}".encode("utf-8")

    def encrypt_bytes(self, data: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aes.encrypt(nonce, data, aad)

    def decrypt_bytes(self, blob: bytes, aad: bytes) -> bytes:
        try:
            return self._aes.decrypt(blob[:12], blob[12:], aad)
        except InvalidTag as e:
            raise CryptoError("Stored value failed integrity check") from e

    def encrypt_text(self, text: str | None, table: str, column: str, row_id: str) -> str | None:
        if text is None:
            return None
        return PREFIX + _b64(self.encrypt_bytes(text.encode("utf-8"), self.aad(table, column, row_id)))

    def decrypt_text(self, value: str | None, table: str, column: str, row_id: str) -> str | None:
        if value is None:
            return None
        if not value.startswith(PREFIX):
            raise CryptoError("Value is not encrypted")
        return self.decrypt_bytes(_unb64(value[len(PREFIX):]), self.aad(table, column, row_id)).decode("utf-8")

    def encrypt_json(self, obj, table: str, column: str, row_id: str) -> str:
        return self.encrypt_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), table, column, row_id)  # type: ignore[return-value]

    def decrypt_json(self, value: str | None, table: str, column: str, row_id: str):
        t = self.decrypt_text(value, table, column, row_id)
        return None if t is None else json.loads(t)

    def blind_index(self, value: str) -> str:
        """Deterministic keyed hash for exact-match lookups without storing plaintext."""
        norm = " ".join(value.strip().lower().split())
        return hmac.new(self._index_key, norm.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def encrypt_file_with_passphrase(data: bytes, passphrase: str, magic: bytes = b"RHUBAK1\n") -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    n = _scrypt_n
    key = _derive(passphrase, salt, n)
    header = magic + n.to_bytes(4, "big") + salt + nonce
    return header + AESGCM(key).encrypt(nonce, data, header)


def decrypt_file_with_passphrase(blob: bytes, passphrase: str, magic: bytes = b"RHUBAK1\n") -> bytes:
    if not blob.startswith(magic):
        raise CryptoError("Not a recognised backup file")
    off = len(magic)
    n = int.from_bytes(blob[off : off + 4], "big")
    if n > 2**20 or n < 2**4:
        raise CryptoError("Unsupported KDF parameter")
    salt = blob[off + 4 : off + 20]
    nonce = blob[off + 20 : off + 32]
    header = blob[: off + 32]
    key = _derive(passphrase, salt, n)
    try:
        return AESGCM(key).decrypt(nonce, blob[off + 32 :], header)
    except InvalidTag as e:
        raise WrongPassword("Wrong passphrase or damaged backup") from e
