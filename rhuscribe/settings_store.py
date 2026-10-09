"""Application settings (non-PHI) persisted in the app_settings table."""
from __future__ import annotations

import json
import sqlite3

from . import config
from .timeutil import now_iso

DEFAULTS: dict = {
    # operating mode: 'demo' (synthetic data only) or 'clinical' (requires approved reference data)
    "operating_mode": "demo",
    # models
    "whisper_model": config.DEFAULT_WHISPER,
    "whisper_device": "cpu",
    "whisper_compute_type": "int8",
    "whisper_language": "auto",  # auto | en | tl
    "ollama_model": config.DEFAULT_LLM,
    "ollama_timeout_s": 300,
    # privacy / retention
    "audio_retention": "delete",  # delete | keep_days
    "audio_retention_days": 0,
    "audio_retention_policy_ref": "",
    "transcript_retention": "keep",  # keep | delete_after_approval
    "record_retention_years": 0,  # 0 = no automatic eligibility; informational review list only
    "inactivity_lock_minutes": 10,
    "require_access_purpose": True,
    # preferences
    "facility_name": "",
    "backup_reminder_days": 7,
    "last_backup_at": "",
}


def get_all(conn: sqlite3.Connection) -> dict:
    out = dict(DEFAULTS)
    for r in conn.execute("SELECT key, value FROM app_settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except ValueError:
            pass
    return out


def get(conn: sqlite3.Connection, key: str):
    r = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    if r:
        try:
            return json.loads(r["value"])
        except ValueError:
            pass
    return DEFAULTS.get(key)


def set_many(conn: sqlite3.Connection, values: dict, user_id: str | None = None) -> None:
    ts = now_iso()
    for k, v in values.items():
        if k not in DEFAULTS:
            raise KeyError(f"Unknown setting: {k}")
        conn.execute(
            "INSERT INTO app_settings(key,value,updated_at,updated_by) VALUES (?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (k, json.dumps(v), ts, user_id),
        )
    conn.commit()
