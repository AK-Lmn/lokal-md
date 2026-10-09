"""Dashboard (Figma "Lokal.MD clinical dashboard"): workload KPIs, recent patient queue, quick actions and local readiness."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from .. import llm, netguard, transcription
from ..auth import can
from ..safety import refdata
from . import common as C
from .encounters import open_encounter

def render() -> None:
    store = C.store()
    user = C.user()
    s = C.settings()
    C.page_header("Clinical dashboard", "A clear view of your clinic. Every patient, every note, securely local.", [("Private by design", "shield-check", "")])
    C.show_flash()
    if can(user, "encounter.list_meta"):
        cnt = store.counts()
        checks = C.conn().execute("SELECT COUNT(*) FROM audit_log WHERE action='medreview.run'").fetchone()[0]
        last = s.get("last_backup_at")
        k = st.container(key="dash_kpis").columns(4)
        C.kpi(k[0], "Today's Consultations", "stethoscope", cnt["today"], "Patients", f"{cnt['open']} open · {cnt['total']} total encounters")
        C.kpi(k[1], "Pending SOAP Approvals", "clipboard-list", cnt["drafts"], "Notes", "Ready for clinician review" if cnt["drafts"] else "Nothing waiting for sign-off", "warm")
        C.kpi(k[2], "Medication Safety Checks", "shield-check", checks, "Checked", "Medication rules verified locally")
        C.kpi(k[3], "Offline Vault Status", "database", "Local Vault Secured", foot=f"Last backup {last[:10]}" if last else "All records saved on this device",
              text=True, accent="(AES-256-GCM)")
    left, right = st.container(key="dash_main").columns([2.1, 1], gap="medium")
    with left:
        _queue(store, user)
    with right:
        with st.container(border=True):
            st.markdown('<div class="rs-tblhead" style="padding:0"><div class="t">Quick Actions</div></div>', unsafe_allow_html=True)
            if st.button("Start New Consultation", key="qa_new", type="primary", width="stretch"):
                st.session_state["page"] = "new"
                st.rerun()
            if st.button("Browse Patient Encounters", key="qa_enc", width="stretch"):
                st.session_state["page"] = "encounters"
                st.rerun()
            if st.button("Encounter History & Audit", key="qa_hist", width="stretch"):
                st.session_state["page"] = "history"
                st.rerun()
        with st.container(border=True):
            st.markdown(f'<div class="rs-tblhead" style="padding:0"><div class="t">System Diagnostic Card</div><span style="color:var(--accent)">{C.icon_html("activity", 18)}</span></div>',
                        unsafe_allow_html=True)
            _readiness(s)
    st.markdown(f'<div class="rs-foot"><span>{C.icon_html("lock", 13)} Patient records stay on this device. No cloud processing.</span>'
                f'<span>Last refreshed {datetime.now().strftime("%H:%M")}</span></div>', unsafe_allow_html=True)


def _queue(store, user) -> None:
    with st.container(border=True, key="tbl_dash"):
        h1, h2 = st.columns([3, 1.1], vertical_alignment="center")
        h1.markdown('<div class="rs-tblhead" style="padding:4px 0"><div><div class="t">Recent Patient Queue</div>'
                    '<div class="s">Recent encounters, from intake to signed note.</div></div></div>', unsafe_allow_html=True)
        status = h2.selectbox("Status filter", ["All", "open", "note_draft", "approved", "archived"], label_visibility="collapsed", key="dash_status",
                              format_func=lambda x: "All statuses" if x == "All" else C.STATUS_CHIP[x][0])
        if not can(user, "encounter.list_meta"):
            C.empty_state("No access", "Your role cannot list encounters.")
            return
        rows = store.list_encounters(status=None if status == "All" else status, limit=6)
        w = [1.3, 0.8, 2.2, 1.2, 1.5]
        C.th(st.columns(w, vertical_alignment="center"), ["Patient Ref", "Age/Sex", "Chief Complaint", "Status", "Workspace"])
        if not rows:
            r = st.columns([1])[0]
            r.markdown('<div class="rs-tfoot" style="padding:18px 0;text-align:center">No encounters yet. Start with New Consultation.</div>', unsafe_allow_html=True)
        for i, r in enumerate(rows):
            c = st.columns(w, vertical_alignment="center")
            d, t = C.split_ts(r["updated_at"])
            C.td(c[0], f'<b>{C.esc(r["patient_ref"])}</b><span class="m">{C.esc(t)} · {C.esc(d[5:])}</span>')
            C.td(c[1], C.age_sex(r))
            C.td(c[2], C.esc(r["chief_complaint"] or "—"))
            C.td(c[3], C.status_chip(r["status"]))
            if c[4].button("Open Workspace", key=f"dq_{r['id']}", type="primary" if r["status"] in ("open", "note_draft") and i == 0 else "secondary",
                           disabled=not can(user, "encounter.view"), icon=":material/north_east:"):
                open_encounter(r["id"], tab="approve" if r["status"] == "note_draft" else "intake")
        f1, f2 = st.columns([3, 1.2], vertical_alignment="center")
        total = store.counts()["total"]
        f1.markdown(f'<div class="rs-tfoot">Showing {len(rows)} of {total} encounters · Pseudonymised references</div>', unsafe_allow_html=True)
        if f2.button("View all encounters →", key="dash_all", type="tertiary"):
            st.session_state["page"] = "encounters"
            st.rerun()


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
        ("mic", "Local Whisper audio engine", f"{s['whisper_model']} ready" if asr["ready"] else "Model not installed", "ok" if asr["ready"] else "warn"),
        ("cpu", "LLM inference", f"{s['ollama_model']} ready" if lm["ready"] else "Not reachable", "ok" if lm["ready"] else "warn"),
        ("lock", "Data encryption", "AES-256-GCM", "ok"),
        ("shield-check", "Network guard", "Outbound blocked" if netguard.is_installed() else "NOT active", "ok" if netguard.is_installed() else "danger"),
        ("pill", "Medication data", ("Loaded (sample)" if ix.is_synthetic else ("Approved" if ix.is_approved_for_clinical else "Imported, unapproved")) if ix else "None active",
         ("warn" if (not ix or ix.is_synthetic or not ix.is_approved_for_clinical) else "ok")),
        ("mic", "Raw audio", "Deleted after use" if s["audio_retention"] == "delete" else f"Kept {s['audio_retention_days']} days", "ok" if s["audio_retention"] == "delete" else "warn"),
        ("hard-drive", "Last backup", "never" if age_days is None else f"{age_days} day(s) ago", "warn" if age_days is None or age_days > s["backup_reminder_days"] else "ok"),
    ]
    st.markdown("".join(f'<div class="rs-diag"><span>{C.icon_html(i, 15, "var(--muted)")}&nbsp; {C.esc(a)}</span>{C.chip(b, k)}</div>' for i, a, b, k in rows), unsafe_allow_html=True)
    st.caption("Unavailable AI features do not stop manual transcripts, note editing, medication-rule checks or PDF export.")
