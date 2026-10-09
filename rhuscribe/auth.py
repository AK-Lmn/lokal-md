"""Users, authentication (= unwrapping the data key), roles and permissions."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from . import audit, config, crypto
from .timeutil import now_iso

PERMISSIONS: dict[str, set[str]] = {
    "encounter.create": {"clinician", "staff"},
    "encounter.edit": {"clinician", "staff"},
    "encounter.view": {"clinician", "staff", "pharmacist"},
    "encounter.list_meta": {"clinician", "staff", "pharmacist", "admin"},
    "encounter.delete": {"clinician", "admin"},
    "encounter.archive": {"clinician", "admin"},
    "transcript.edit": {"clinician", "staff"},
    "note.edit": {"clinician", "staff"},
    "note.approve": {"clinician"},
    "medreview.run": {"clinician", "staff", "pharmacist"},
    "medreview.ack": {"clinician"},
    "export.pdf": {"clinician", "staff", "pharmacist"},
    "refdata.import": {"admin", "pharmacist"},
    "refdata.approve": {"pharmacist", "clinician"},
    "refdata.view": {"admin", "clinician", "staff", "pharmacist"},
    "settings.edit": {"admin"},
    "users.manage": {"admin"},
    "backup.manage": {"admin"},
    "audit.view": {"admin"},
    "retention.manage": {"admin"},
    "history.view": {"clinician", "staff", "pharmacist"},
}

ROLE_LABELS = {
    "admin": "System administrator",
    "clinician": "Clinician (can approve notes)",
    "staff": "Health worker / encoder (cannot approve)",
    "pharmacist": "Pharmacist / reviewer (read + reference data)",
}


def can(user: dict | None, perm: str) -> bool:
    return bool(user) and user["role"] in PERMISSIONS.get(perm, set())


class AuthError(Exception):
    pass


def _validate_password(pw: str) -> None:
    if len(pw) < config.MIN_PASSWORD_LEN:
        raise AuthError(f"Password must be at least {config.MIN_PASSWORD_LEN} characters.")
    if pw.lower() == pw or not any(c.isdigit() for c in pw):
        raise AuthError("Password needs upper- and lower-case letters and at least one digit.")


def _validate_username(u: str) -> str:
    u = u.strip()
    if not (3 <= len(u) <= 32) or not all(c.isalnum() or c in "._-" for c in u):
        raise AuthError("Username: 3-32 characters, letters/digits/._- only.")
    return u


def is_setup_done(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM key_store").fetchone() is not None


def first_run_setup(
    conn: sqlite3.Connection, username: str, display_name: str, password: str, credentials: str = "", license_no: str = ""
) -> tuple[dict, str, crypto.Vault]:
    """Create the data key, the first (admin) user and a recovery key. Returns (user, recovery_key, vault)."""
    if is_setup_done(conn):
        raise AuthError("Setup has already been completed.")
    username = _validate_username(username)
    _validate_password(password)
    if not display_name.strip():
        raise AuthError("Display name is required.")
    dek = crypto.new_dek()
    recovery = crypto.new_recovery_key()
    uid = str(uuid.uuid4())
    now = now_iso()
    conn.execute(
        "INSERT INTO key_store(id, recovery_wrap, created_at) VALUES (1,?,?)",
        (crypto.wrap_dek(dek, crypto.normalize_recovery_key(recovery)), now),
    )
    conn.execute(
        "INSERT INTO users(id,username,display_name,credentials,license_no,role,wrapped_dek,created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (uid, username, display_name.strip(), credentials.strip(), license_no.strip(), "admin", crypto.wrap_dek(dek, password), now),
    )
    conn.commit()
    user = get_user(conn, uid)
    audit.record(conn, user, "setup.completed", "user", uid)
    return user, recovery, crypto.Vault(dek)


def get_user(conn: sqlite3.Connection, user_id: str) -> dict | None:
    r = conn.execute(
        "SELECT id,username,display_name,credentials,license_no,role,active,created_at,last_login_at FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    return dict(r) if r else None


def list_users(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id,username,display_name,credentials,license_no,role,active,created_at,last_login_at,locked_until FROM users ORDER BY username"
        )
    ]


def login(conn: sqlite3.Connection, username: str, password: str) -> tuple[dict, crypto.Vault]:
    r = conn.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    generic = AuthError("Incorrect username or password.")
    if not r or not r["active"]:
        audit.record(conn, None, "login.failed", "user", None, {"reason": "unknown_or_inactive"})
        raise generic
    now = datetime.now(timezone.utc)
    if r["locked_until"] and datetime.fromisoformat(r["locked_until"]) > now:
        mins = int((datetime.fromisoformat(r["locked_until"]) - now).total_seconds() // 60) + 1
        raise AuthError(f"Account temporarily locked after repeated failed sign-ins. Try again in about {mins} min.")
    try:
        dek = crypto.unwrap_dek(r["wrapped_dek"], password)
    except crypto.WrongPassword:
        attempts = r["failed_attempts"] + 1
        locked = None
        if attempts >= config.MAX_FAILED_LOGINS:
            locked = (now + timedelta(minutes=config.LOCKOUT_MINUTES)).isoformat(timespec="seconds")
            attempts = 0
        conn.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?", (attempts, locked, r["id"]))
        conn.commit()
        audit.record(conn, get_user(conn, r["id"]), "login.failed", "user", r["id"], {"locked": bool(locked)})
        raise generic
    conn.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login_at=? WHERE id=?", (now_iso(), r["id"]))
    conn.commit()
    user = get_user(conn, r["id"])
    audit.record(conn, user, "login.success", "user", r["id"])
    return user, crypto.Vault(dek)


def create_user(
    conn: sqlite3.Connection, actor: dict, vault_dek: bytes, username: str, display_name: str, role: str,
    password: str, credentials: str = "", license_no: str = "",
) -> dict:
    if not can(actor, "users.manage"):
        raise AuthError("Not permitted.")
    if role not in config.ROLES:
        raise AuthError("Unknown role.")
    username = _validate_username(username)
    _validate_password(password)
    if not display_name.strip():
        raise AuthError("Display name is required.")
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise AuthError("That username already exists.")
    uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users(id,username,display_name,credentials,license_no,role,wrapped_dek,created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (uid, username, display_name.strip(), credentials.strip(), license_no.strip(), role, crypto.wrap_dek(vault_dek, password), now_iso()),
    )
    conn.commit()
    audit.record(conn, actor, "user.created", "user", uid, {"role": role})
    return get_user(conn, uid)  # type: ignore[return-value]


def update_user_profile(conn, actor: dict, user_id: str, display_name: str, credentials: str, license_no: str, role: str | None = None, active: bool | None = None) -> None:
    if actor["id"] != user_id and not can(actor, "users.manage"):
        raise AuthError("Not permitted.")
    if role is not None or active is not None:
        if not can(actor, "users.manage"):
            raise AuthError("Not permitted.")
        target = get_user(conn, user_id)
        admins = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (user_id,)).fetchone()[0]
        if target and target["role"] == "admin" and admins == 0 and ((role and role != "admin") or active is False):
            raise AuthError("At least one active administrator must remain.")
    fields = {"display_name": display_name.strip(), "credentials": credentials.strip(), "license_no": license_no.strip()}
    if role is not None:
        fields["role"] = role
    if active is not None:
        fields["active"] = int(active)
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), user_id))
    conn.commit()
    audit.record(conn, actor, "user.updated", "user", user_id, {"role": role, "active": active})


def change_password(conn, user: dict, old_password: str, new_password: str) -> None:
    r = conn.execute("SELECT wrapped_dek FROM users WHERE id=?", (user["id"],)).fetchone()
    try:
        dek = crypto.unwrap_dek(r["wrapped_dek"], old_password)
    except crypto.WrongPassword:
        raise AuthError("Current password is incorrect.")
    _validate_password(new_password)
    conn.execute("UPDATE users SET wrapped_dek=? WHERE id=?", (crypto.wrap_dek(dek, new_password), user["id"]))
    conn.commit()
    audit.record(conn, user, "password.changed", "user", user["id"])


def admin_reset_password(conn, actor: dict, dek: bytes, user_id: str, new_password: str) -> None:
    if not can(actor, "users.manage"):
        raise AuthError("Not permitted.")
    _validate_password(new_password)
    conn.execute(
        "UPDATE users SET wrapped_dek=?, failed_attempts=0, locked_until=NULL WHERE id=?",
        (crypto.wrap_dek(dek, new_password), user_id),
    )
    conn.commit()
    audit.record(conn, actor, "password.reset_by_admin", "user", user_id)


def reset_with_recovery_key(conn, username: str, recovery_key: str, new_password: str) -> None:
    """Lost-password path: needs the recovery key shown once at setup."""
    _validate_password(new_password)
    ks = conn.execute("SELECT recovery_wrap FROM key_store WHERE id=1").fetchone()
    u = conn.execute("SELECT id FROM users WHERE username=? AND active=1", (username.strip(),)).fetchone()
    if not ks or not u:
        raise AuthError("Recovery failed.")
    try:
        dek = crypto.unwrap_dek(ks["recovery_wrap"], crypto.normalize_recovery_key(recovery_key))
    except crypto.CryptoError:
        audit.record(conn, None, "recovery.failed", "user", u["id"])
        raise AuthError("Recovery failed.")
    conn.execute(
        "UPDATE users SET wrapped_dek=?, failed_attempts=0, locked_until=NULL WHERE id=?",
        (crypto.wrap_dek(dek, new_password), u["id"]),
    )
    conn.commit()
    audit.record(conn, get_user(conn, u["id"]), "recovery.password_reset", "user", u["id"])
