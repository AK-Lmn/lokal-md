"""Encrypted backup and restore.

A backup is a consistent SQLite snapshot (online backup API) encrypted as a whole with
AES-256-GCM under a key derived (scrypt) from a backup passphrase chosen by the
administrator. The snapshot's clinical fields are additionally field-encrypted. Restore
verifies the authentication tag, SQLite integrity and schema version before touching the
live database, and writes a pre-restore backup first.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from . import audit, config, crypto, db, settings_store
from .transcription import secure_delete


class BackupError(Exception):
    pass


MIN_PASSPHRASE = 12


def _snapshot_bytes(conn: sqlite3.Connection) -> bytes:
    tmp = config.tmp_dir() / f"snap_{os.urandom(6).hex()}.db"
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            conn.backup(dst)
        finally:
            dst.close()
        return tmp.read_bytes()
    finally:
        secure_delete(tmp)
        for ext in ("-wal", "-shm"):
            Path(str(tmp) + ext).unlink(missing_ok=True)


def create_backup(conn: sqlite3.Connection, actor: dict, passphrase: str, label: str = "") -> tuple[Path, bytes]:
    if len(passphrase) < MIN_PASSPHRASE:
        raise BackupError(f"Backup passphrase must be at least {MIN_PASSPHRASE} characters.")
    blob = crypto.encrypt_file_with_passphrase(_snapshot_bytes(conn), passphrase)
    name = f"{label + '-' if label else ''}rhu-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.rhubak"
    path = config.backup_dir() / name
    path.write_bytes(blob)
    settings_store.set_many(conn, {"last_backup_at": datetime.now().astimezone().isoformat(timespec="seconds")}, actor["id"])
    audit.record(conn, actor, "backup.created", "backup", name, {"bytes": len(blob)})
    return path, blob


def restore_backup(conn: sqlite3.Connection, actor: dict, blob: bytes, passphrase: str) -> None:
    try:
        raw = crypto.decrypt_file_with_passphrase(blob, passphrase)
    except crypto.CryptoError as e:
        raise BackupError(str(e)) from e
    if not raw.startswith(b"SQLite format 3"):
        raise BackupError("Backup content is not a SQLite database.")
    tmp = config.tmp_dir() / f"restore_{os.urandom(6).hex()}.db"
    try:
        tmp.write_bytes(raw)
        src = sqlite3.connect(str(tmp))
        try:
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("Backup failed the SQLite integrity check.")
            ver = src.execute("PRAGMA user_version").fetchone()[0]
            if ver > len(db.MIGRATIONS):
                raise BackupError(f"Backup schema v{ver} is newer than this application (v{len(db.MIGRATIONS)}).")
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"users", "encounters", "key_store"} <= tables:
                raise BackupError("Backup is missing required tables.")
            create_backup_safe = _try_pre_restore(conn, actor, passphrase)
            src.backup(conn)  # replaces live content page by page
        finally:
            src.close()
        conn.commit()
        db.init_db(conn)  # upgrade older backups
        audit.record(conn, None, "backup.restored", "backup", None, {"pre_restore_saved": create_backup_safe})
    finally:
        secure_delete(tmp)


def _try_pre_restore(conn, actor, passphrase) -> bool:
    try:
        create_backup(conn, actor, passphrase, label="pre-restore")
        return True
    except Exception:
        return False


def list_local_backups() -> list[dict]:
    out = []
    for p in sorted(config.backup_dir().glob("*.rhubak"), reverse=True):
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size, "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out
