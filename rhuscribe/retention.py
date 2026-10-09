"""Retention behaviour. Defaults are privacy-protective: raw audio is never kept."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .repo import Store


def maybe_retain_audio(store: Store, enc_id: str, data: bytes, mime: str, settings: dict) -> bool:
    """Retain audio ONLY if an administrator enabled it and recorded an approved-policy reference."""
    if settings.get("audio_retention") != "keep_days":
        return False
    days = int(settings.get("audio_retention_days") or 0)
    ref = (settings.get("audio_retention_policy_ref") or "").strip()
    if days <= 0 or not ref:
        return False
    store.store_audio(enc_id, data, mime, days, ref)
    return True


def after_approval(store: Store, enc_id: str, settings: dict) -> list[str]:
    done = []
    if settings.get("transcript_retention") == "delete_after_approval":
        store.delete_transcript(enc_id)
        done.append("transcript deleted per retention policy")
    return done


def records_due_for_review(store: Store, years: int) -> list[dict]:
    """Approved encounters older than `years`. Listing only - deletion is always an explicit action."""
    if years <= 0:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365 * years)).isoformat(timespec="seconds")
    rows = store.conn.execute(
        "SELECT id, updated_at FROM encounters WHERE status IN ('approved','archived') AND updated_at < ? ORDER BY updated_at", (cutoff,)
    ).fetchall()
    return [dict(r) for r in rows]
