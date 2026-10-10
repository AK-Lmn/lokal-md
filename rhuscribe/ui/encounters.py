"""Encounter list, history (with access purpose), and opening an encounter into the workspace."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from .. import audit
from ..auth import can
from ..repo import PermissionDenied
from ..timeutil import local_display
from . import common as C
from . import wsstate as W

PURPOSES = ["Continuity of care / treatment", "Referral or follow-up consultation", "Medication reconciliation", "Clinical audit / quality review (authorised)", "Patient request for own record", "Other (state in note)"]


def open_encounter(enc_id: str, tab: str = "intake", purpose: str | None = None) -> None:
    store = C.store()
    W.load(store, enc_id)
    if purpose:
        audit.record(C.conn(), C.user(), "history.accessed", "encounter", enc_id, {"purpose": purpose})
    st.session_state["ws_tab_ctl"] = tab
    st.session_state["page"] = "workspace"
    st.rerun()


def _table(rows: list[dict], key: str, compact: bool = False):
    data = [{"Encounter": r["id"], "Patient ref": r["patient_ref"], **({} if compact else {"Chief complaint": r["chief_complaint"]}),
             "Status": C.STATUS_CHIP.get(r["status"], (r["status"],))[0], "Updated": local_display(r["updated_at"])} for r in rows]
    ev = st.dataframe(data, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=key)
    sel = ev.selection.rows if ev and ev.selection else []
    return rows[sel[0]] if sel else None


PAGE = 12
HIST_PAGE = 8


def _pager(key: str, n: int, size: int, cols) -> tuple[int, int]:
    pages = max(1, -(-n // size))
    pg = min(max(1, st.session_state.get(key, 1)), pages)
    if cols[1].button("‹ Previous", key=f"{key}_prev", disabled=pg <= 1, width="stretch"):
        st.session_state[key] = pg - 1
        st.rerun()
    cols[2].markdown(f'<div class="rs-tfoot" style="text-align:center">Page {pg:02d} / {pages:02d}</div>', unsafe_allow_html=True)
    if cols[3].button("Next ›", key=f"{key}_next", disabled=pg >= pages, width="stretch"):
        st.session_state[key] = pg + 1
        st.rerun()
    return (pg - 1) * size, min(pg * size, n)


@st.dialog("Patient Encounter Quick-Peek", width="large")
def _quick_peek_dialog(enc_id: str) -> None:
    store = C.store()
    user = C.user()
    try:
        enc = store.get_encounter(enc_id)
        draft = store.get_draft(enc_id)
        appr = store.get_approved(enc_id)
        note_rec = appr or draft
        orders = store.get_orders(enc_id)
        review = store.latest_review(enc_id)
    except Exception as e:
        st.error(f"Cannot load encounter preview: {e}")
        return

    data = enc.get("data")
    p = data.profile if data else None
    v = data.vitals if data else None
    inp = data.inputs if data else None

    sex_label = C.SEX.get(p.sex, p.sex) if (p and hasattr(C, 'SEX')) else (p.sex if p else "")
    status_label = C.STATUS_CHIP.get(enc.get("status", ""), (enc.get("status", ""),))[0]
    c1.markdown(f'<div style="font-size:1.2rem;font-weight:700;color:var(--ink)">Patient Ref {C.esc(data.patient_ref if data else enc_id)}</div>'
                f'<div style="color:var(--muted);font-size:0.85rem">{C.esc(p.age_text() if p else "?")} · {C.esc(sex_label)} · {C.esc(status_label)}</div>', unsafe_allow_html=True)
    c2.markdown(C.status_chip(enc.get("status", "open")), unsafe_allow_html=True)
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Recorded Vitals**")
        if v and any([v.bp_systolic, v.heart_rate, v.temp_c, v.spo2, v.weight_kg]):
            v_lines = v.lines()
            for line in v_lines:
                st.markdown(f"- {C.esc(line)}")
        else:
            st.caption("No vitals recorded.")
        st.markdown("**Chief Complaint & Diagnosis**")
        st.write(inp.chief_complaint if (inp and inp.chief_complaint) else "_No chief complaint recorded._")
        if inp and inp.working_diagnosis:
            st.caption(f"Working Diagnosis: {inp.working_diagnosis}")

    with col2:
        st.markdown("**Medications & Safety Review**")
        if orders:
            for o in orders:
                st.markdown(f"- **{C.esc(o.drug_name)}** {C.esc(o.strength or '')} — {C.esc(o.frequency or '')}")
        else:
            st.caption("No medication orders recorded.")
        if review and "result" in review:
            r_res = review["result"]
            r_overall = r_res.get("overall", "unknown")
            r_findings = r_res.get("findings", [])
            st.markdown(f"Safety Engine: `{r_overall}` ({len(r_findings)} findings checked)")
        else:
            st.caption("No safety review run yet.")

    st.markdown("---")
    b1, b2 = st.columns([2, 1])
    if b1.button("Open Full Clinical Workspace →", type="primary", width="stretch", disabled=not can(user, "encounter.view")):
        open_encounter(enc_id)
    if b2.button("Close", width="stretch"):
        st.rerun()


def render_list() -> None:
    store = C.store()
    user = C.user()
    right = C.page_header("Patient Encounters", "Browse, filter, and audit local pseudonymised clinical consultations", ratio=(3, 1))
    with right:
        st.markdown('<div style="display:flex;justify-content:flex-end">', unsafe_allow_html=True)
        if st.button("New Consultation", key="enc_new", type="primary"):
            st.session_state["page"] = "new"
            st.rerun()
    C.show_flash()
    q = st.text_input("Search", placeholder="Search by patient reference (e.g. PT-PQCTPD), encounter ID, chief complaint or diagnosis ... [Ctrl+K]",
                      label_visibility="collapsed", key="enc_q")
    c1, c2, c3 = st.columns([1.2, 1.9, 2.4], vertical_alignment="center")
    status = c1.selectbox("Status", ["All", "open", "note_draft", "approved", "archived"], label_visibility="collapsed", key="enc_status",
                          format_func=lambda s: "Status: All" if s == "All" else f"Status: {C.STATUS_CHIP[s][0]}")
    deep = c2.checkbox("Also search transcripts & notes", help="Slower: decrypts and searches every record.")
    cnt = store.counts()
    archived = cnt["total"] - cnt["open"] - cnt["drafts"] - cnt["approved"]
    c3.markdown(f'<div class="rs-counts" style="justify-content:flex-end"><span>All<b>{cnt["total"]}</b></span><span class="open">Open<b>{cnt["open"]}</b></span>'
                f'<span class="draft">Draft note<b>{cnt["drafts"]}</b></span><span class="appr">Approved<b>{cnt["approved"]}</b></span><span>Archived<b>{archived}</b></span></div>',
                unsafe_allow_html=True)
    rows = store.list_encounters(status=None if status == "All" else status, query=q, deep=deep)
    if not rows:
        C.empty_state("No encounters found", "Create one with New Consultation." if not q else "Try a different search.")
        return
    with st.container(border=True, key="tbl_enc"):
        w = [1.3, 0.75, 1.15, 2.1, 1.05, 1.9]
        C.th(st.columns(w, vertical_alignment="center"), ["Patient Reference", "Age/Sex", "Date & Time", "Consultation", "Note Status", "Actions"])
        foot = st.container()
        f = st.columns([3.2, 0.9, 0.8, 0.9], vertical_alignment="center")
        lo, hi = _pager("enc_page", len(rows), PAGE, f)
        f[0].markdown(f'<div class="rs-tfoot">Showing {lo + 1}-{hi} of {len(rows)} local encounters · Pseudonymised records only</div>', unsafe_allow_html=True)
        with foot:
            for r in rows[lo:hi]:
                c = st.columns(w, vertical_alignment="center")
                d, t = C.split_ts(r["created_at"])
                C.td(c[0], f'<span class="rs-ref">{C.esc(r["patient_ref"])}</span><span class="m rs-mono" style="font-size:10px;margin-top:6px">{C.esc(r["id"])}</span>')
                C.td(c[1], C.age_sex(r))
                C.td(c[2], f'{C.esc(d)}<span class="m">{C.esc(t)} · Local time</span>')
                C.td(c[3], f'{C.esc(r["chief_complaint"] or "No chief complaint recorded")}<span class="m">{C.esc(r.get("consult_type", ""))}</span>')
                C.td(c[4], C.status_chip(r["status"]))
                a1, a2 = c[5].columns([1, 1.2], gap="small")
                if a1.button("Peek", key=f"peek_{r['id']}", icon=":material/visibility:", disabled=not can(user, "encounter.view")):
                    _quick_peek_dialog(r["id"])
                if a2.button("Open", key=f"eo_{r['id']}", icon=":material/north_east:", disabled=not can(user, "encounter.view"),
                               help=None if can(user, "encounter.view") else "Your role cannot open clinical content."):
                    open_encounter(r["id"])


def render_history() -> None:
    store = C.store()
    s = C.settings()
    user = C.user()
    conn = C.conn()
    C.page_header("Encounter History & Audit Trail", "Cryptographically verified, tamper-evident consultation archives stored locally",
                  [("Immutable · Read-only", "lock", "soft")])
    C.show_flash()
    if not can(user, "history.view"):
        C.banner("Your role can see record metadata only, not clinical content.", "info")
    cnt = store.counts()
    ok, n_checked, bad = audit.verify_chain(conn)
    b1, b2 = st.columns([5, 1.25], vertical_alignment="center")
    b1.markdown(f'<div class="rs-hashbar{"" if ok else " bad"}">{C.icon_html("shield-check", 20)} {cnt["total"]} Encounters Recorded &bull; {cnt["approved"]} Approved '
                f'&bull; 100% Encrypted At Rest<span class="tag">{"HASH CHAIN INTACT" if ok else f"HASH CHAIN BROKEN AT #{bad}"}</span></div>', unsafe_allow_html=True)
    if b2.button("Verify archive integrity", key="hist_verify", width="stretch"):
        audit.record(conn, user, "audit.verified", None, None, {"ok": ok, "rows": n_checked})
        C.flash(f"Audit chain verified: {n_checked} entries intact." if ok else f"Audit chain broken at entry #{bad}. Contact the administrator.", "success" if ok else "error")
        st.rerun()
    encs = {r["id"]: r for r in store.list_encounters(limit=500)}
    logs = audit.recent(conn, 2000)
    if not can(user, "audit.view"):
        logs = [r for r in logs if r["user_id"] == user["id"]]
    with st.container(border=True, key="tbl_hist"):
        h1, h2 = st.columns([3, 1.4])
        h1.markdown(f'<div class="rs-tblhead" style="padding:4px 0 0"><div><div class="t">Consultation audit log {C.chip("Append-only ledger", "neutral")}</div>'
                    '<div class="s">Every clinical event preserved in order. Original records cannot be altered or removed.</div></div></div>', unsafe_allow_html=True)
        h2.markdown(f'<div style="text-align:right;padding-top:6px"><span class="rs-ok">{C.icon_html("shield-check", 13)} '
                    f'{"All displayed records verified" if ok else "Chain broken - see banner"}</span><div class="rs-mono" style="font-size:10px;color:var(--muted);margin-top:4px">'
                    f'LAST CHECK {C.esc(datetime.now().strftime("%Y-%m-%d %H:%M"))}</div></div>', unsafe_allow_html=True)
        f = st.columns([1.4, 1.3, 1.3, 1.6], vertical_alignment="bottom")
        ev = f[0].selectbox("Event type", ["All"] + sorted({r["action"] for r in logs}), key="hist_ev",
                            format_func=lambda a: "All event types" if a == "All" else C.action_text(a))
        pref = f[1].text_input("Patient code", placeholder="Search patient code", key="hist_pref")
        eid = f[2].text_input("Encounter ID", placeholder="ENC-...", key="hist_eid")
        rows = [r for r in logs if ev == "All" or r["action"] == ev]
        if pref.strip():
            ids = set(store.encounters_for_patient(pref.strip())) if can(user, "encounter.view") else set()
            rows = [r for r in rows if r["target_id"] in ids]
        if eid.strip():
            rows = [r for r in rows if eid.strip().upper() in (r["target_id"] or "").upper()]
        f[3].markdown(f'<div class="rs-tfoot" style="text-align:right;padding-bottom:10px">{len(rows)} events shown / <b style="color:var(--ink)">Newest first</b></div>',
                      unsafe_allow_html=True)
        w = [1.25, 1.15, 0.95, 1.65, 1.15, 1.35, 1.2]
        C.th(st.columns(w, vertical_alignment="center"), ["Timestamp", "Encounter ID", "Patient Ref", "Action", "Performed By", "Signature / Hash", "Archive access"])
        body = st.container()
        pf = st.columns([3.2, 0.9, 0.8, 0.9], vertical_alignment="center")
        lo, hi = _pager("hist_page", len(rows), HIST_PAGE, pf)
        pf[0].markdown(f'<div class="rs-tfoot">Showing {lo + 1 if rows else 0}-{hi} of {len(rows)} audit events across {len(encs)} encounters</div>', unsafe_allow_html=True)
        with body:
            if not rows:
                C.empty_state("No matching events")
            for r in rows[lo:hi]:
                c = st.columns(w, vertical_alignment="center")
                d, t = C.split_ts(r["ts"])
                enc = encs.get(r["target_id"]) if r["target_type"] == "encounter" else None
                C.td(c[0], f'<span class="rs-mono">{C.esc(d)}T{C.esc(t)}</span><span class="m">Local time</span>')
                C.td(c[1], f'<b class="rs-mono">{C.esc(r["target_id"])}</b>' if r["target_type"] == "encounter" else f'<span class="m">{C.esc(r["target_type"] or "system")}</span>')
                C.td(c[2], f'<span class="rs-mono" style="color:var(--muted)">{C.esc(enc["patient_ref"]) if enc else "—"}</span>')
                kind = "ok" if r["action"] in ("note.approved", "export.pdf", "medreview.run") else "neutral"
                C.td(c[3], C.chip(C.action_text(r["action"]), kind))
                C.td(c[4], f'<b>{C.esc(r["username"] or "system")}</b><span class="m">Authenticated user</span>')
                good = ok or r["id"] < bad
                C.td(c[5], f'<span class="rs-mono">{C.esc(r["hash"][:8])}...{C.esc(r["hash"][-6:])}</span>'
                           + ('<span class="m rs-ok">&#10003; Integrity verified</span>' if good else '<span class="m" style="color:var(--danger)">Unverified</span>'))
                if enc and c[6].button("View record", key=f"hv_{r['id']}", icon=":material/visibility:"):
                    st.session_state["hist_sel"] = enc["id"]
                    st.rerun()
    sel = encs.get(st.session_state.get("hist_sel"))
    if sel:
        with st.container(border=True):
            _record_panel(store, s, user, sel)
    st.markdown(f'<div class="rs-feats"><div><span class="ic">{C.icon_html("hard-drive", 18)}</span><span><b>Stored on this device</b>Encrypted local vault · No external data transfer</span></div>'
                f'<div><span class="ic">{C.icon_html("link", 18)}</span><span><b>Cryptographically linked</b>SHA-256 hashes preserve a tamper-evident event chain</span></div>'
                f'<div><span class="ic">{C.icon_html("lock", 18)}</span><span><b>Immutable clinical record</b>Approved versions are read-only. Amendments create new versions.</span></div></div>',
                unsafe_allow_html=True)


def _record_panel(store, s, user, sel) -> None:
    C.card_head("file-text", f"{sel['id']} · {sel['patient_ref']}", sel.get("chief_complaint") or "", C.STATUS_CHIP.get(sel["status"], (sel["status"], "neutral")))
    st.caption("Opening a record is access to personal health information and is logged with its purpose.")
    if can(user, "encounter.view"):
        v = store.list_versions(sel["id"])
        if v:
            st.markdown("**Note versions:** " + " · ".join(f"v{x['version']} ({x['status']}{', ' + local_display(x['approved_at']) if x['approved_at'] else ''})" for x in v))
        if can(user, "history.view"):
            purpose = None
            if s.get("require_access_purpose"):
                purpose = st.selectbox("Purpose of access (required)", ["— choose —"] + PURPOSES, key="hist_purpose")
                ok = purpose != "— choose —"
            else:
                ok = True
            if st.button("Open record", type="primary", disabled=not ok):
                open_encounter(sel["id"], tab="note" if v else "intake", purpose=purpose if s.get("require_access_purpose") else "not required")
    if user["role"] in ("clinician", "admin"):
        with st.expander("Activity log for this record"):
            rows_a = audit.recent(C.conn(), 100, sel["id"])
            st.dataframe([{"When": local_display(r["ts"]), "User": r["username"], "Action": C.action_text(r["action"]), "Detail": r["detail"]} for r in rows_a],
                         hide_index=True, width="stretch")
    _manage(store, sel)


def _manage(store, sel):
    user = C.user()
    if can(user, "encounter.archive") and sel["status"] == "approved":
        if st.button("Archive record (locks it permanently)"):
            store.archive_encounter(sel["id"])
            C.flash("Record archived.")
            st.rerun()
    if can(user, "encounter.delete"):
        with st.expander("Delete permanently"):
            st.warning("Deletes this encounter, transcript, notes, medication reviews and retained audio from this computer. This cannot be undone. Backups made earlier will still contain it. An audit entry (without clinical content) remains.")
            typed = st.text_input("Type the encounter ID to confirm", key=f"del_{sel['id']}")
            if st.button("Delete permanently", type="primary", disabled=typed.strip() != sel["id"]):
                try:
                    store.delete_encounter(sel["id"])
                    if W.active_id() == sel["id"]:
                        W.clear()
                    C.flash(f"{sel['id']} deleted.")
                    st.rerun()
                except PermissionDenied as e:
                    st.error(str(e))
