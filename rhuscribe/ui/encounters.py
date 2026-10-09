"""Encounter list, history (with access purpose), and opening an encounter into the workspace."""
from __future__ import annotations

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


def _table(rows: list[dict], key: str):
    data = [{"Encounter": r["id"], "Patient ref": r["patient_ref"], "Chief complaint": r["chief_complaint"], "Status": C.STATUS_CHIP.get(r["status"], (r["status"],))[0],
             "Updated": local_display(r["updated_at"])} for r in rows]
    ev = st.dataframe(data, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=key)
    sel = ev.selection.rows if ev and ev.selection else []
    return rows[sel[0]] if sel else None


def render_list() -> None:
    store = C.store()
    st.title("Patient Encounters")
    C.show_flash()
    c1, c2, c3, c4 = st.columns([2.6, 1.5, 1.5, 1.4], vertical_alignment="bottom")
    q = c1.text_input("Search", placeholder="Encounter ID, patient reference, chief complaint, diagnosis ...")
    status = c2.selectbox("Status", ["All", "open", "note_draft", "approved", "archived"], format_func=lambda s: "All statuses" if s == "All" else C.STATUS_CHIP[s][0])
    deep = c3.checkbox("Also search transcripts & notes", help="Slower: decrypts and searches every record.")
    if c4.button("New encounter", type="primary", width="stretch"):
        st.session_state["page"] = "new"
        st.rerun()
    rows = store.list_encounters(status=None if status == "All" else status, query=q, deep=deep)
    if not rows:
        C.empty_state("No encounters found", "Create one with New consultation." if not q else "Try a different search.")
        return
    st.caption(f"{len(rows)} record(s). Select a row to open it.")
    sel = _table(rows, "enc_tbl")
    if sel:
        a, b = st.columns([1, 5])
        if a.button("Open encounter", type="primary"):
            if not can(C.user(), "encounter.view"):
                st.error("Your role cannot open clinical content.")
            else:
                open_encounter(sel["id"])


def render_history() -> None:
    store = C.store()
    s = C.settings()
    user = C.user()
    st.title("Encounter History")
    st.caption("Retrieve earlier records. Opening a record is access to personal health information and is logged with its purpose.")
    C.show_flash()
    if not can(user, "history.view"):
        C.banner("Your role can see record metadata only, not clinical content.", "info")
    c1, c2, c3 = st.columns([2.4, 2, 1.6], vertical_alignment="bottom")
    pref = c1.text_input("Patient reference (all visits of one patient)", placeholder="e.g. PT-00123")
    q = c2.text_input("Text search", placeholder="complaint, diagnosis ...")
    scope = c3.selectbox("Show", ["Approved & archived", "All records"])
    rows = store.list_encounters(query=q, limit=500)
    if scope == "Approved & archived":
        rows = [r for r in rows if r["status"] in ("approved", "archived")]
    if pref.strip():
        ids = set(store.encounters_for_patient(pref.strip())) if can(user, "encounter.view") else set()
        rows = [r for r in rows if r["id"] in ids]
    if not rows:
        C.empty_state("No matching records")
        return
    sel = _table(rows, "hist_tbl")
    if not sel:
        st.caption("Select a record to see its versions, activity and options.")
        return
    st.markdown(f"#### {C.esc(sel['id'])}")
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
            st.dataframe([{"When": local_display(r["ts"]), "User": r["username"], "Action": r["action"], "Detail": r["detail"]} for r in rows_a], hide_index=True, width="stretch")
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
