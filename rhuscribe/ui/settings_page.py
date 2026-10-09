"""Settings: models, privacy/retention, users, medication reference, backup, audit, data deletion."""
from __future__ import annotations

import json

import streamlit as st
from pydantic import ValidationError

from .. import APP_NAME, __version__, audit, auth, backup, config, crypto, llm, retention, settings_store, transcription
from ..auth import ROLE_LABELS, can
from ..safety import refdata
from ..safety.demo_data import demo_bundle_dict
from ..timeutil import local_display
from . import common as C
from . import wsstate as W


def render() -> None:
    st.title("Settings")
    C.show_flash()
    user = C.user()
    tabs = st.tabs(["Models", "Privacy & retention", "Medication reference", "My account", "Users", "Backup & restore", "Audit log", "Data deletion", "About"])
    with tabs[0]:
        _models()
    with tabs[1]:
        _privacy()
    with tabs[2]:
        _reference()
    with tabs[3]:
        _account()
    with tabs[4]:
        _users()
    with tabs[5]:
        _backup()
    with tabs[6]:
        _audit()
    with tabs[7]:
        _deletion()
    with tabs[8]:
        _about()


def _need(perm: str, msg: str = "Only an administrator can change these settings.") -> bool:
    if can(C.user(), perm):
        return True
    st.info(msg)
    return False


# ---------------------------------------------------------------------------- models
def _models():
    s = C.settings()
    edit = can(C.user(), "settings.edit")
    st.markdown("##### Speech recognition (faster-whisper)")
    asr = transcription.status(s["whisper_model"])
    st.markdown(C.chip("ready" if asr["ready"] else "unavailable", "ok" if asr["ready"] else "warn") + C.chip("installed: " + (", ".join(asr["installed"]) or "none"), "neutral"), unsafe_allow_html=True)
    if not asr["ready"]:
        st.caption(asr["message"])
    c1, c2, c3, c4 = st.columns(4)
    wm = c1.selectbox("Model size", config.WHISPER_SIZES, index=config.WHISPER_SIZES.index(s["whisper_model"]) if s["whisper_model"] in config.WHISPER_SIZES else 2, disabled=not edit, help="Larger = more accurate but slower. 'small' is a practical laptop default.")
    wl = c2.selectbox("Language", ["auto", "en", "tl"], index=["auto", "en", "tl"].index(s["whisper_language"]), format_func={"auto": "Auto-detect (Taglish)", "en": "English", "tl": "Tagalog"}.get, disabled=not edit)
    wd = c3.selectbox("Device", ["cpu", "cuda", "auto"], index=["cpu", "cuda", "auto"].index(s["whisper_device"]), disabled=not edit, help="'cuda' needs NVIDIA CUDA 12 libraries installed.")
    wc = c4.selectbox("Precision", ["int8", "int8_float16", "float16", "float32"], index=["int8", "int8_float16", "float16", "float32"].index(s["whisper_compute_type"]), disabled=not edit)

    st.markdown("##### Local language model (Ollama)")
    lm = llm.status(s["ollama_model"])
    st.markdown(C.chip("server running" if lm["running"] else "server not reachable", "ok" if lm["running"] else "warn")
                + C.chip("model ready" if lm["ready"] else "model missing", "ok" if lm["ready"] else "warn"), unsafe_allow_html=True)
    if not lm["ready"]:
        st.caption(lm["message"])
    d1, d2 = st.columns([2, 1])
    opts = lm["models"] or []
    om = d1.text_input("Model name", value=s["ollama_model"], disabled=not edit, help="Suggested: llama3.2:3b (Llama 3.2 Community License) or phi3.5 (MIT). Installed: " + (", ".join(opts) or "none detected"))
    to = d2.number_input("Generation timeout (s)", 30, 1800, int(s["ollama_timeout_s"]), 30, disabled=not edit)
    if edit and st.button("Save model settings", type="primary"):
        settings_store.set_many(C.conn(), {"whisper_model": wm, "whisper_language": wl, "whisper_device": wd, "whisper_compute_type": wc, "ollama_model": om.strip(), "ollama_timeout_s": int(to)}, C.user()["id"])
        audit.record(C.conn(), C.user(), "settings.models_changed", "settings")
        C.flash("Model settings saved.")
        st.rerun()
    with st.expander("How to install models (do this while online)"):
        st.code("python scripts/prepare_models.py                 # whisper small + llama3.2:3b\npython scripts/prepare_models.py --whisper base   # smaller speech model\npython scripts/prepare_models.py --llm phi3.5", language="bash")
        st.caption("The running application never downloads models. Language support: Whisper handles English and Tagalog; Taglish (mixed) accuracy varies. "
                   "Llama 3.2 / Phi-3.5 are not officially tuned for Tagalog, so notes from Taglish speech need extra careful review.")


# ---------------------------------------------------------------------------- privacy
def _privacy():
    s = C.settings()
    edit = _need("settings.edit")
    st.markdown("##### Raw audio")
    mode = st.radio("After transcription, raw audio is…", ["delete", "keep_days"], index=0 if s["audio_retention"] == "delete" else 1,
                    format_func={"delete": "Deleted immediately (default, recommended)", "keep_days": "Kept encrypted for a limited time (needs an approved clinic policy)"}.get, disabled=not edit)
    days, pol = s["audio_retention_days"], s["audio_retention_policy_ref"]
    if mode == "keep_days":
        days = st.number_input("Keep for (days)", 1, 3650, max(1, int(s["audio_retention_days"] or 7)), disabled=not edit)
        pol = st.text_input("Approved policy reference (required)", value=s["audio_retention_policy_ref"], disabled=not edit, placeholder="e.g. RHU Records Policy 2026-03, section 4")
        st.caption("Retained audio is encrypted with the same key as other records and purged automatically after expiry.")
    st.markdown("##### Transcript & records")
    tr = st.radio("Transcript after a note is approved", ["keep", "delete_after_approval"], index=0 if s["transcript_retention"] == "keep" else 1,
                  format_func={"keep": "Keep with the record", "delete_after_approval": "Delete after approval (the approved note remains)"}.get, disabled=not edit)
    yrs = st.number_input("Flag approved records for retention review after (years, 0 = off)", 0, 60, int(s["record_retention_years"]), disabled=not edit,
                          help="Only produces a review list under Data deletion. Nothing is deleted automatically.")
    st.markdown("##### Access")
    idle = st.number_input("Lock the session after inactivity (minutes)", 1, 240, int(s["inactivity_lock_minutes"]), disabled=not edit)
    purpose = st.checkbox("Require a stated purpose when opening past records", value=bool(s["require_access_purpose"]), disabled=not edit)
    fac = st.text_input("Facility name (printed on PDFs)", value=s["facility_name"], disabled=not edit)
    if edit and st.button("Save privacy settings", type="primary"):
        if mode == "keep_days" and not pol.strip():
            st.error("An approved policy reference is required to keep raw audio.")
        else:
            settings_store.set_many(C.conn(), {"audio_retention": mode, "audio_retention_days": int(days), "audio_retention_policy_ref": pol.strip(), "transcript_retention": tr,
                                               "record_retention_years": int(yrs), "inactivity_lock_minutes": int(idle), "require_access_purpose": purpose, "facility_name": fac.strip()}, C.user()["id"])
            audit.record(C.conn(), C.user(), "settings.privacy_changed", "settings", None, {"audio": mode})
            C.flash("Privacy settings saved.")
            st.rerun()
    with st.expander("What is protected, and what is not"):
        st.markdown(
            "- **Encrypted (AES-256-GCM, per field):** patient details, transcripts, notes, medication orders, review results, acknowledgements, retained audio.\n"
            "- **Not encrypted (visible to anyone with file access):** encounter IDs, timestamps, record status, user names/roles, audit event names, settings, reference data.\n"
            "- **Keys:** a random data key is wrapped by each user's password (scrypt + AES-GCM); it is held in memory only while signed in. Losing every password *and* the recovery key makes the data unrecoverable.\n"
            "- **Not covered:** an attacker who controls the running computer, malware, shoulder-surfing, or copies of exported PDFs. Use full-disk encryption (e.g. BitLocker) and a locked-down workstation.\n"
            "- Local storage alone does not make a deployment compliant with the Data Privacy Act of 2012; your organisation still needs its own privacy impact assessment, policies and DPO review.")


# ---------------------------------------------------------------------------- reference data
def _reference():
    conn = C.conn()
    user = C.user()
    s = C.settings()
    st.markdown("##### Operating mode")
    ix = refdata.load_active_index(conn)
    mode = s["operating_mode"]
    st.markdown(C.chip("DEMONSTRATION mode" if mode != "clinical" else "CLINICAL mode", "warn" if mode != "clinical" else "ok"), unsafe_allow_html=True)
    st.caption("Demonstration mode is for testing with synthetic patients. Clinical mode is only allowed when an imported dataset has been professionally reviewed and approved and is active; otherwise medication checks fail closed.")
    if can(user, "settings.edit"):
        if mode != "clinical":
            ok = bool(ix and ix.is_approved_for_clinical)
            typed = st.text_input("To enable clinical mode type: ENABLE CLINICAL MODE", key="clin_confirm", disabled=not ok)
            if st.button("Switch to clinical mode", disabled=not ok or typed.strip() != "ENABLE CLINICAL MODE"):
                settings_store.set_many(conn, {"operating_mode": "clinical"}, user["id"])
                audit.record(conn, user, "settings.mode_clinical", "settings", None, {"dataset": ix.dataset["name"]})
                st.rerun()
            if not ok:
                st.caption("Not available: no approved imported dataset is active.")
        elif st.button("Return to demonstration mode"):
            settings_store.set_many(conn, {"operating_mode": "demo"}, user["id"])
            audit.record(conn, user, "settings.mode_demo", "settings")
            st.rerun()

    st.markdown("##### Datasets")
    dss = refdata.list_datasets(conn)
    for d in dss:
        with st.container(border=True):
            kind = "SYNTHETIC DEMO" if d["kind"] == "synthetic_demo" else "Imported"
            stat = {"pending_review": ("Awaiting review", "warn"), "approved": ("Approved", "ok"), "rejected": ("Rejected", "danger"), "retired": ("Retired", "neutral")}[d["status"]]
            st.markdown(f"**{C.esc(d['name'])}** v{C.esc(d['version'])} " + C.chip(kind, "warn" if d["kind"] == "synthetic_demo" else "info") + C.chip(*stat) + (C.chip("ACTIVE", "ok") if d["active"] else ""), unsafe_allow_html=True)
            st.caption(f"{d['source_description']}  ·  imported {local_display(d['imported_at'])}")
            st.caption(" · ".join(f"{k.replace('_', ' ')}: {v}" for k, v in d["counts"].items()))
            if d["reviewed_at"]:
                st.caption(f"Reviewed {local_display(d['reviewed_at'])}: {d['review_notes']}")
            b = st.columns(4)
            if can(user, "settings.edit") and not d["active"] and d["status"] not in ("retired", "rejected"):
                if b[0].button("Activate", key=f"act_{d['id']}"):
                    try:
                        refdata.set_active(conn, d["id"], user, clinical_mode=mode == "clinical")
                        st.rerun()
                    except refdata.RefError as e:
                        st.error(str(e))
            if d["status"] == "pending_review" and d["kind"] == "imported" and can(user, "refdata.approve"):
                with st.expander("Professional review"):
                    notes = st.text_area("Review notes (what was verified, against which source)", key=f"rn_{d['id']}")
                    att = st.checkbox("I am qualified to review this content and have verified it against authoritative sources.", key=f"ra_{d['id']}")
                    x, y = st.columns(2)
                    if x.button("Approve for clinical use", key=f"ap_{d['id']}", type="primary", disabled=not att):
                        try:
                            refdata.review_dataset(conn, user, d["id"], True, notes, att)
                            st.rerun()
                        except refdata.RefError as e:
                            st.error(str(e))
                    if y.button("Reject", key=f"rj_{d['id']}"):
                        try:
                            refdata.review_dataset(conn, user, d["id"], False, notes, att)
                            st.rerun()
                        except refdata.RefError as e:
                            st.error(str(e))
            if can(user, "settings.edit") and not d["active"] and d["status"] != "retired" and d["kind"] != "synthetic_demo":
                if b[1].button("Retire", key=f"rt_{d['id']}"):
                    refdata.retire_dataset(conn, user, d["id"])
                    st.rerun()

    st.markdown("##### Import verified reference data")
    if not can(user, "refdata.import"):
        st.info("Only a pharmacist or administrator can import reference data.")
        return
    st.caption("Imported data starts as 'awaiting review' and cannot back clinical mode until a DIFFERENT qualified person approves it. Every record must carry a source citation.")
    t1, t2 = st.tabs(["JSON bundle", "CSV files"])
    with t1:
        st.download_button("Download format example (synthetic demo bundle)", json.dumps(demo_bundle_dict(), indent=1), file_name="reference_bundle_example.json", mime="application/json")
        up = st.file_uploader("Reference bundle (.json)", type=["json"], key="ref_json")
        if up and st.button("Validate & import", key="imp_json"):
            _do_import(lambda: refdata.parse_bundle_json(up.getvalue().decode("utf-8", "replace")))
    with t2:
        st.caption("Upload one CSV per section (ingredients, classes, interactions, contraindications, dose_limits, age_warnings, allergy_cross). List cells use | as separator.")
        m1, m2 = st.columns(2)
        nm = m1.text_input("Dataset name", key="csv_name")
        vr = m2.text_input("Version", key="csv_ver")
        src = st.text_input("Source description (publisher, edition, date)", key="csv_src")
        files = st.file_uploader("CSV files (name each file after its section, e.g. interactions.csv)", type=["csv"], accept_multiple_files=True, key="ref_csv")
        if files and st.button("Validate & import", key="imp_csv"):
            def build():
                secs = {f.name.rsplit(".", 1)[0].lower(): f.getvalue().decode("utf-8-sig", "replace") for f in files}
                return refdata.bundle_from_csvs({"name": nm, "version": vr, "source_description": src}, secs)
            _do_import(build)


def _do_import(builder):
    try:
        b = builder()
        ds = refdata.save_bundle(C.conn(), b, kind="imported", imported_by=C.user()["id"])
        audit.record(C.conn(), C.user(), "refdata.imported", "refdata", ds, {"name": b.meta.name})
        C.flash(f"Imported '{b.meta.name}'. It is awaiting professional review and is not active.")
        st.rerun()
    except refdata.RefError as e:
        st.error(str(e))
    except (ValidationError, ValueError) as e:
        st.error(f"Invalid data: {e}")


# ---------------------------------------------------------------------------- account & users
def _account():
    conn, user = C.conn(), C.user()
    st.markdown(f"**{C.esc(user['display_name'])}** · {C.esc(user['username'])} · {C.esc(ROLE_LABELS[user['role']])}")
    with st.form("profile"):
        dn = st.text_input("Display name", user["display_name"])
        cr = st.text_input("Credentials (printed on notes you approve)", user["credentials"], placeholder="Leave blank if none - nothing is invented")
        lic = st.text_input("Licence / PRC number (optional)", user["license_no"])
        if st.form_submit_button("Save profile"):
            auth.update_user_profile(conn, user, user["id"], dn, cr, lic)
            st.session_state["user"] = auth.get_user(conn, user["id"])
            C.flash("Profile saved.")
            st.rerun()
    with st.form("pw"):
        old = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password")
        if st.form_submit_button("Change password"):
            try:
                auth.change_password(conn, user, old, new)
                C.flash("Password changed.")
                st.rerun()
            except auth.AuthError as e:
                st.error(str(e))


def _users():
    if not _need("users.manage"):
        return
    conn, user = C.conn(), C.user()
    users = auth.list_users(conn)
    st.dataframe([{"User": u["username"], "Name": u["display_name"], "Role": u["role"], "Active": bool(u["active"]), "Last sign-in": local_display(u["last_login_at"])} for u in users], hide_index=True, width="stretch")
    st.markdown("##### Add user")
    with st.form("newuser", clear_on_submit=True):
        c1, c2 = st.columns(2)
        un = c1.text_input("Username")
        dn = c2.text_input("Full name")
        role = c1.selectbox("Role", list(ROLE_LABELS), format_func=ROLE_LABELS.get)
        cr = c2.text_input("Credentials (clinicians)")
        lic = c1.text_input("Licence no. (optional)")
        pw = c2.text_input("Temporary password", type="password")
        if st.form_submit_button("Create user", type="primary"):
            try:
                auth.create_user(conn, user, st.session_state["vault"].export_dek(), un, dn, role, pw, cr, lic)
                C.flash(f"User {un} created.")
                st.rerun()
            except auth.AuthError as e:
                st.error(str(e))
    st.markdown("##### Edit user")
    pick = st.selectbox("User", [u["username"] for u in users], key="edit_user")
    u = next(x for x in users if x["username"] == pick)
    c1, c2, c3 = st.columns(3)
    nrole = c1.selectbox("Role", list(ROLE_LABELS), index=list(ROLE_LABELS).index(u["role"]), format_func=ROLE_LABELS.get, key="eu_role")
    nact = c2.checkbox("Active", bool(u["active"]), key="eu_act")
    newpw = c3.text_input("Reset password to", type="password", key="eu_pw")
    if st.button("Apply changes"):
        try:
            auth.update_user_profile(conn, user, u["id"], u["display_name"], u["credentials"], u["license_no"], role=nrole, active=nact)
            if newpw:
                auth.admin_reset_password(conn, user, st.session_state["vault"].export_dek(), u["id"], newpw)
            C.flash("User updated.")
            st.rerun()
        except auth.AuthError as e:
            st.error(str(e))


# ---------------------------------------------------------------------------- backup
def _backup():
    if not _need("backup.manage"):
        return
    conn, user = C.conn(), C.user()
    s = C.settings()
    st.caption(f"Last backup: {local_display(s.get('last_backup_at')) if s.get('last_backup_at') else 'never'}")
    st.markdown("##### Create encrypted backup")
    pw = st.text_input("Backup passphrase (min 12 characters - needed to restore)", type="password", key="bk_pw")
    if st.button("Create backup", type="primary"):
        try:
            path, blob = backup.create_backup(conn, user, pw)
            st.session_state["_bk"] = (path.name, blob)
        except backup.BackupError as e:
            st.error(str(e))
    if st.session_state.get("_bk"):
        name, blob = st.session_state["_bk"]
        st.success(f"Backup saved to data/backups/{name}")
        st.download_button("Download backup file", blob, file_name=name, mime="application/octet-stream")
        st.caption("Copy the file to removable media kept in a secure place. Without the passphrase it cannot be opened.")
    for b in backup.list_local_backups()[:5]:
        st.caption(f"{b['name']} · {b['size'] // 1024} KB · {b['modified']}")
    st.markdown("##### Restore from backup")
    st.warning("Restoring REPLACES all current data, users and keys with the backup's. A safety copy of the current data is made first. You will be signed out.")
    up = st.file_uploader("Backup file (.rhubak)", type=["rhubak"], key="bk_up")
    rp = st.text_input("Passphrase of that backup", type="password", key="bk_rp")
    typed = st.text_input("Type RESTORE to confirm", key="bk_conf")
    if up and st.button("Restore", disabled=typed.strip() != "RESTORE"):
        try:
            backup.restore_backup(conn, user, up.getvalue(), rp)
        except backup.BackupError as e:
            st.error(str(e))
        else:
            from . import session
            session.logout("Backup restored. Sign in with an account from the backup.")
            st.rerun()


# ---------------------------------------------------------------------------- audit
def _audit():
    if not _need("audit.view", "Only an administrator can view the audit log."):
        return
    conn = C.conn()
    ok, n, bad = audit.verify_chain(conn)
    st.markdown(C.chip(f"Chain intact ({n} entries)" if ok else f"CHAIN BROKEN at entry {bad}", "ok" if ok else "danger"), unsafe_allow_html=True)
    st.caption("Entries record who did what and when, never clinical content. The hash chain makes after-the-fact edits detectable; it does not stop someone with full file access from rebuilding it.")
    rows = audit.recent(conn, 300)
    st.dataframe([{"#": r["id"], "When": local_display(r["ts"]), "User": r["username"], "Action": r["action"], "Target": f"{r['target_type'] or ''} {r['target_id'] or ''}".strip(), "Detail": r["detail"]} for r in rows], hide_index=True, width="stretch")


# ---------------------------------------------------------------------------- deletion
def _deletion():
    conn, user, s = C.conn(), C.user(), C.settings()
    store = C.store()
    if not (can(user, "retention.manage") or can(user, "encounter.delete")):
        st.info("Only an administrator or clinician can manage deletion.")
        return
    st.markdown("##### Retained audio")
    n = conn.execute("SELECT COUNT(*) FROM audio_files").fetchone()[0]
    st.caption(f"{n} retained recording(s).")
    if can(user, "retention.manage"):
        c1, c2 = st.columns(2)
        if c1.button("Purge expired recordings now"):
            C.flash(f"{store.purge_expired_audio()} expired recording(s) deleted.")
            st.rerun()
        if n and c2.button("Delete ALL retained recordings"):
            conn.execute("DELETE FROM audio_files")
            conn.commit()
            audit.record(conn, user, "audio.purged_all", "audio")
            st.rerun()
        st.markdown("##### Retention review")
        due = retention.records_due_for_review(store, int(s["record_retention_years"]))
        if not s["record_retention_years"]:
            st.caption("Retention review is off. Set a period under Privacy & retention.")
        elif not due:
            st.caption("No records are past the retention review period.")
        else:
            st.warning(f"{len(due)} record(s) are past {s['record_retention_years']} year(s). Review against your records policy; deletion is always manual (History → Delete permanently).")
            st.dataframe([{"Encounter": d["id"], "Last updated": local_display(d["updated_at"])} for d in due], hide_index=True)
    st.markdown("##### Delete an encounter")
    eid = st.text_input("Encounter ID", key="del_id_settings")
    if eid and can(user, "encounter.delete"):
        if st.checkbox("I understand this permanently removes the record from this computer"):
            if st.button("Delete permanently", type="primary", disabled=conn.execute("SELECT 1 FROM encounters WHERE id=?", (eid.strip(),)).fetchone() is None):
                store.delete_encounter(eid.strip())
                if W.active_id() == eid.strip():
                    W.clear()
                C.flash(f"{eid.strip()} deleted.")
                st.rerun()


# ---------------------------------------------------------------------------- about
def _about():
    st.markdown(f"**{APP_NAME}** v{__version__}")
    st.markdown(
        "**Intended use:** documentation aid and rule-based medication-review aid for qualified health workers. It does not diagnose, prescribe or approve anything.\n\n"
        "**Limitations**\n"
        "- Speech recognition and the language model make mistakes, especially with Tagalog/Taglish, accents, noise and drug names. Every transcript and note must be reviewed.\n"
        "- Medication checks use only the installed reference dataset. The bundled dataset is **synthetic demonstration data**. No alert does not mean safe.\n"
        "- Not a certified medical device. Not evaluated for regulatory or Data Privacy Act compliance. Deployment requires institutional clinical-safety, privacy and security review.\n"
        "- Single-workstation design; no TLS or multi-site sync. Keep the server bound to this computer.")
    st.caption("Network behaviour: the app only talks to localhost (Streamlit UI and the local Ollama server). A process-level guard blocks other outbound connections.")
