"""Dashboard: workload overview, drafts awaiting review, activity and local readiness."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from .. import audit, llm, netguard, transcription
from ..auth import can
from ..safety import refdata
from ..timeutil import local_display
from . import common as C
from .encounters import _table, open_encounter

ACTION_TEXT = {
    "encounter.created": "Encounter created", "encounter.updated": "Encounter updated", "note.draft_saved": "Note draft saved", "note.approved": "Note approved",
    "medreview.run": "Medication check run", "transcript.saved": "Transcript saved", "export.pdf": "PDF exported", "login.success": "Signed in",
    "encounter.deleted": "Encounter deleted", "backup.created": "Backup created", "note.amendment_started": "Amendment started", "medreview.acknowledged": "Finding acknowledged",
}


def render() -> None:
    store = C.store()
    user = C.user()
    s = C.settings()
    st.title("Dashboard")
    C.show_flash()
    st.caption(f"Signed in as {user['display_name']} · {user['role']}")
    if can(user, "encounter.list_meta"):
        cnt = store.counts()
        cols = st.columns(4)
        C.metric("Encounters today", cnt["today"], cols[0])
        C.metric("Open", cnt["open"], cols[1])
        C.metric("Drafts awaiting review", cnt["drafts"], cols[2])
        C.metric("Approved", cnt["approved"], cols[3])
    st.write("")
    left, right = st.columns([1.5, 1], gap="large")
    with left:
        st.markdown("#### Drafts awaiting review")
        drafts = store.list_encounters(status="note_draft", limit=20)
        if drafts:
            sel = _table(drafts, "dash_drafts", compact=True)
            if sel and can(user, "encounter.view") and st.button("Open selected draft", type="primary"):
                open_encounter(sel["id"], tab="approve")
        else:
            C.empty_state("No drafts waiting", "Notes you generate or save appear here until approved.")
        st.markdown("#### Recent encounters")
        recent = store.list_encounters(limit=8)
        if recent:
            sel2 = _table(recent, "dash_recent", compact=True)
            if sel2 and can(user, "encounter.view") and st.button("Open selected encounter"):
                open_encounter(sel2["id"])
        else:
            C.empty_state("No encounters yet", "Start with New Consultation.")
            if st.button("Start a consultation", type="primary"):
                st.session_state["page"] = "new"
                st.rerun()
    with right:
        st.markdown("#### Local system readiness")
        _readiness(s)
        st.markdown("#### Recent activity")
        rows = audit.recent(C.conn(), 40)
        if not can(user, "audit.view"):
            rows = [r for r in rows if r["user_id"] == user["id"]]
        rows = rows[:8]
        if not rows:
            st.caption("No activity yet.")
        for r in rows:
            st.markdown(f'<div class="rs-small">{C.esc(local_display(r["ts"]))} · {C.esc(ACTION_TEXT.get(r["action"], r["action"].replace(".", " ").replace("_", " ").capitalize()))}'
                        f'{" · " + C.esc(r["target_id"]) if r["target_type"] == "encounter" else ""}</div>', unsafe_allow_html=True)


def _readiness(s: dict) -> None:
    asr = transcription.status(s["whisper_model"])
    lm = llm.status(s["ollama_model"])
    ix = refdata.load_active_index(C.conn())
    last = s.get("last_backup_at")
    age_days = None
    if last:
        try:
            age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days
        except ValueError:
            pass
    rows = [
        ("Data encryption", "AES-256-GCM", "ok"),
        ("Network guard", "Outbound blocked" if netguard.is_installed() else "NOT active", "ok" if netguard.is_installed() else "danger"),
        ("Speech recognition", f"{s['whisper_model']} ready" if asr["ready"] else asr["message"], "ok" if asr["ready"] else "warn"),
        ("Local language model", f"{s['ollama_model']} ready" if lm["ready"] else lm["message"], "ok" if lm["ready"] else "warn"),
        ("Medication data", ("SYNTHETIC DEMO" if ix.is_synthetic else ("Approved" if ix.is_approved_for_clinical else "Imported, unapproved")) if ix else "None active", ("warn" if (not ix or ix.is_synthetic or not ix.is_approved_for_clinical) else "ok")),
        ("Raw audio", "Deleted after use" if s["audio_retention"] == "delete" else f"Kept {s['audio_retention_days']} days", "ok" if s["audio_retention"] == "delete" else "warn"),
        ("Last backup", "never" if age_days is None else f"{age_days} day(s) ago", "warn" if age_days is None or age_days > s["backup_reminder_days"] else "ok"),
    ]
    html = "".join(f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #e3e9ec;font-size:.9rem"><span>{C.esc(a)}</span><span>{C.chip(b, k)}</span></div>' for a, b, k in rows)
    st.markdown(f'<div class="rs-card">{html}</div>', unsafe_allow_html=True)
    st.caption("Features marked unavailable do not stop manual transcripts, note editing, medication-rule checks or PDF export.")
