"""Tamper-evident audit trail.

Each row stores the SHA-256 of its content chained to the previous row's hash. This
detects edits/deletions of past rows by anyone who does not recompute the whole chain; it
is not a substitute for write-once media or off-device log shipping.

Audit `detail` must never contain patient-identifying or clinical free text. `record()`
only keeps short scalar values and drops everything else.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from .timeutil import now_iso

GENESIS = "GENESIS"


def _clean_detail(detail: dict | None) -> str:
    out = {}
    for k, v in (detail or {}).items():
        if isinstance(v, (bool, int, float)) or v is None:
            out[str(k)] = v
        elif isinstance(v, str):
            out[str(k)] = v[:120]
    return json.dumps(out, sort_keys=True, ensure_ascii=False)


def _hash(prev: str, ts: str, user_id, username, action, target_type, target_id, detail: str) -> str:
    payload = json.dumps([prev, ts, user_id, username, action, target_type, target_id, detail], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record(
    conn: sqlite3.Connection,
    user: dict | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    ts = now_iso()
    uid = user["id"] if user else None
    uname = user["username"] if user else None
    det = _clean_detail(detail)
    conn.execute("BEGIN IMMEDIATE") if not conn.in_transaction else None
    row = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev = row["hash"] if row else GENESIS
    h = _hash(prev, ts, uid, uname, action, target_type, target_id, det)
    conn.execute(
        "INSERT INTO audit_log(ts,user_id,username,action,target_type,target_id,detail,prev_hash,hash)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, uid, uname, action, target_type, target_id, det, prev, h),
    )
    conn.commit()


def verify_chain(conn: sqlite3.Connection) -> tuple[bool, int, int | None]:
    """Returns (ok, rows_checked, first_bad_id)."""
    prev = GENESIS
    n = 0
    for r in conn.execute("SELECT * FROM audit_log ORDER BY id"):
        n += 1
        expect = _hash(prev, r["ts"], r["user_id"], r["username"], r["action"], r["target_type"], r["target_id"], r["detail"])
        if r["prev_hash"] != prev or r["hash"] != expect:
            return False, n, r["id"]
        prev = r["hash"]
    return True, n, None


def recent(conn: sqlite3.Connection, limit: int = 50, target_id: str | None = None) -> list[sqlite3.Row]:
    if target_id:
        return conn.execute(
            "SELECT * FROM audit_log WHERE target_id=? ORDER BY id DESC LIMIT ?", (target_id, limit)
        ).fetchall()
    return conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
