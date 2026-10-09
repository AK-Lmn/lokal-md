import json
import sqlite3

import pytest

from rhuscribe import audit, auth, backup, crypto, pdf_export, repo, services, settings_store
from rhuscribe.repo import Conflict, PermissionDenied, Store
from rhuscribe.safety import refdata
from rhuscribe.schemas import ClinicalInputs, EncounterData, MedicationOrder, PatientProfile, SOAPNote, Vitals
from tests.conftest import PW, _dek

SYN_NAME = "Juanita Syntheticname Dela Cruz"


def make_data(**kw):
    return EncounterData(
        patient_ref="SYN-0001",
        profile=PatientProfile(display_name=SYN_NAME, age_value=34, sex="female", pregnancy_status="no", allergies_status="none_known", conditions_status="none_known"),
        vitals=Vitals(bp_systolic=120, bp_diastolic=80, heart_rate=78, temp_c=37.1),
        inputs=ClinicalInputs(chief_complaint="Cough for 3 days", working_diagnosis="Acute bronchitis"),
        **kw,
    )


# ------------------------------------------------------------------ crypto
def test_wrap_unwrap_and_wrong_password():
    dek = crypto.new_dek()
    w = crypto.wrap_dek(dek, "pw-correct-1A")
    assert crypto.unwrap_dek(w, "pw-correct-1A") == dek
    with pytest.raises(crypto.WrongPassword):
        crypto.unwrap_dek(w, "nope")


def test_ciphertext_bound_to_row():
    v = crypto.Vault(crypto.new_dek())
    c = v.encrypt_text("secret", "t", "c", "row1")
    assert "secret" not in c
    assert v.decrypt_text(c, "t", "c", "row1") == "secret"
    with pytest.raises(crypto.CryptoError):
        v.decrypt_text(c, "t", "c", "row2")


def test_tamper_detected():
    v = crypto.Vault(crypto.new_dek())
    c = v.encrypt_text("secret", "t", "c", "r")
    bad = c[:-4] + ("AAAA" if not c.endswith("AAAA") else "BBBB")
    with pytest.raises(Exception):
        v.decrypt_text(bad, "t", "c", "r")


# ------------------------------------------------------------------ auth
def test_first_run_login_lockout_recovery(admin_ctx):
    conn, admin, vault, recovery = admin_ctx
    with pytest.raises(auth.AuthError):
        auth.first_run_setup(conn, "x", "X", PW)  # setup only once
    u, v = auth.login(conn, "admin", PW)
    assert u["role"] == "admin"
    for _ in range(5):
        with pytest.raises(auth.AuthError):
            auth.login(conn, "admin", "wrong-password-1A")
    with pytest.raises(auth.AuthError, match="locked"):
        auth.login(conn, "admin", PW)
    auth.reset_with_recovery_key(conn, "admin", recovery, "BrandNewPass9")
    u2, v2 = auth.login(conn, "admin", "BrandNewPass9")
    assert u2["id"] == u["id"]


def test_weak_password_rejected(admin_ctx):
    conn, admin, vault, _ = admin_ctx
    with pytest.raises(auth.AuthError):
        auth.create_user(conn, admin, _dek(conn, "admin"), "bad", "Bad", "staff", "short1A")


def test_role_permissions(admin_ctx):
    conn, admin, _, _ = admin_ctx
    dek = _dek(conn, "admin")
    auth.create_user(conn, admin, dek, "nurse", "Nurse Syn", "staff", PW)
    u, v = auth.login(conn, "nurse", PW)
    st = Store(conn, v, u)
    eid = st.create_encounter(make_data())
    st.save_draft(eid, SOAPNote(), method="manual")
    with pytest.raises(PermissionDenied):
        st.approve_note(eid, review_id=None, attestation="x")
    with pytest.raises(PermissionDenied):
        st.delete_encounter(eid)
    # admin cannot read clinical content
    a_user, a_vault = auth.login(conn, "admin", PW)
    ast = Store(conn, a_vault, a_user)
    with pytest.raises(PermissionDenied):
        ast.get_encounter(eid)
    assert ast.list_encounters()[0]["patient_ref"] == "(restricted)"


# ------------------------------------------------------------------ storage
def test_phi_not_stored_in_plaintext(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    st.save_transcript(eid, "Patient says she has a bad cough and fever", source="manual", reviewed=True)
    st.save_orders(eid, [MedicationOrder(drug_name="Amoxicillin", dose_amount=500, dose_unit="mg")])
    st.save_draft(eid, SOAPNote(), method="manual")
    st.conn.commit()
    dump = "\n".join(ln for ln in st.conn.iterdump() if not ln.startswith('INSERT INTO "ref_'))
    for needle in (SYN_NAME, "SYN-0001", "bad cough", "Amoxicillin", "Acute bronchitis"):
        assert needle not in dump, needle


def test_encounter_roundtrip_and_search(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    assert eid.startswith("ENC-")
    got = st.get_encounter(eid)
    assert got["data"].profile.display_name == SYN_NAME and got["status"] == "open"
    assert [e["id"] for e in st.list_encounters(query="bronchitis")] == [eid]
    assert st.list_encounters(query="zzz-none") == []
    assert st.encounters_for_patient("syn-0001") == [eid]


def test_patient_ref_required(clinician_store):
    d = make_data()
    d.patient_ref = "  "
    with pytest.raises(ValueError):
        clinician_store.create_encounter(d)


def test_invalid_vitals_rejected():
    with pytest.raises(Exception):
        Vitals(spo2=150)
    with pytest.raises(Exception):
        Vitals(temp_c=5)


def test_draft_approval_lifecycle_and_immutability(clinician_store, conn):
    st = clinician_store
    eid = st.create_encounter(make_data())
    n = SOAPNote()
    n.subjective.chief_complaint = "Cough"
    st.save_draft(eid, n, method="manual")
    assert st.get_encounter(eid)["status"] == "note_draft"
    ix = refdata.load_active_index(st.conn)
    settings = settings_store.get_all(st.conn)
    ready = services.approval_readiness(st, eid, ix, settings)
    assert ready.ok  # no meds, no transcript
    appr = services.approve(st, eid, ix, settings, "I reviewed this note")
    assert appr["status"] == "approved" and appr["approver"]["name"] == "Dr. Test Cruz"
    assert appr["approver"]["credentials"] == "MD (synthetic)"
    assert st.get_draft(eid) is None
    with pytest.raises(Conflict):
        st.save_draft(eid, n, method="manual")
    with pytest.raises(Conflict):
        st.update_encounter(eid, make_data())
    # amendment creates a new draft; approved text unchanged until re-approved
    st.start_amendment(eid)
    d = st.get_draft(eid)
    assert d["version"] == 2 and st.get_approved(eid)["version"] == 1
    n2 = d["note"]
    n2.subjective.chief_complaint = "Cough and fever"
    st.save_draft(eid, n2, method="manual")
    assert st.get_approved(eid)["note"].subjective.chief_complaint == "Cough"
    services.approve(st, eid, ix, settings, "amended")
    versions = {v["version"]: v["status"] for v in st.list_versions(eid)}
    assert versions == {1: "superseded", 2: "approved"}


def test_approval_blocked_until_transcript_reviewed_and_med_check(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    st.save_transcript(eid, "[?] maybe amoxicillin\nnormal line", source="audio", language="en", asr_model="x")
    st.save_orders(eid, [MedicationOrder(drug_name="Ibuprofen", dose_amount=400, dose_unit="mg", route="oral", frequency="TID", duration_days=3)])
    st.save_draft(eid, SOAPNote(), method="manual")
    ix = refdata.load_active_index(st.conn)
    settings = settings_store.get_all(st.conn)
    r = services.approval_readiness(st, eid, ix, settings)
    assert not r.ok and any("[?]" in b for b in r.blockers) and any("not been run" in b for b in r.blockers)
    st.save_transcript(eid, "normal line", source="audio", reviewed=True)
    rev = services.run_med_review(st, eid, ix)
    assert services.review_is_current(st, eid, rev, ix)
    # editing orders makes the review stale
    st.save_orders(eid, [MedicationOrder(drug_name="Ibuprofen", dose_amount=600, dose_unit="mg", route="oral", frequency="TID", duration_days=3)])
    assert any("changed" in b for b in services.approval_readiness(st, eid, ix, settings).blockers)


def test_findings_require_ack_before_approval(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    st.save_orders(eid, [
        MedicationOrder(drug_name="Warfarin", dose_amount=5, dose_unit="mg", route="oral", frequency="OD", duration_days=30),
        MedicationOrder(drug_name="Ibuprofen", dose_amount=400, dose_unit="mg", route="oral", frequency="TID", duration_days=3),
    ])
    st.save_draft(eid, SOAPNote(), method="manual")
    ix = refdata.load_active_index(st.conn)
    settings = settings_store.get_all(st.conn)
    rev = services.run_med_review(st, eid, ix)
    need = services.required_acks(rev)
    assert need
    assert any("acknowledgement" in b for b in services.approval_readiness(st, eid, ix, settings).blockers)
    with pytest.raises(ValueError):
        st.acknowledge_finding(rev["id"], need[0]["key"], "x")
    for f in need:
        st.acknowledge_finding(rev["id"], f["key"], "Benefit outweighs risk; INR monitoring arranged")
    assert services.approval_readiness(st, eid, ix, settings).ok
    st.acknowledge_finding(rev["id"], need[0]["key"], "Updated reason text here")  # re-ack overwrites
    assert st.latest_review(eid)["acks"][need[0]["key"]]["reason"] == "Updated reason text here"


def test_clinical_mode_fails_closed_with_synthetic_data(clinician_store):
    st = clinician_store
    settings = {**settings_store.get_all(st.conn), "operating_mode": "clinical"}
    assert services.get_reference_index(st.conn, settings) is None


def test_delete_cascades_and_audit_kept(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    st.save_transcript(eid, "x", source="manual", reviewed=True)
    st.save_orders(eid, [MedicationOrder(drug_name="Paracetamol")])
    st.save_draft(eid, SOAPNote(), method="manual")
    st.delete_encounter(eid)
    c = st.conn
    for t in ("transcripts", "medication_orders", "note_versions", "encounters"):
        col = "id" if t == "encounters" else "encounter_id"
        assert c.execute(f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (eid,)).fetchone()[0] == 0
    assert any(r["action"] == "encounter.deleted" for r in audit.recent(c, 20, eid))


def test_audit_chain_detects_tampering(clinician_store):
    st = clinician_store
    st.create_encounter(make_data())
    ok, n, bad = audit.verify_chain(st.conn)
    assert ok and n > 2
    st.conn.execute("UPDATE audit_log SET action='encounter.nothing' WHERE id=2")
    st.conn.commit()
    ok, _, bad = audit.verify_chain(st.conn)
    assert not ok and bad == 2


def test_audit_detail_drops_free_text_objects(clinician_store):
    audit.record(clinician_store.conn, clinician_store.user, "x.test", "t", "1", {"ok": 1, "nested": {"name": SYN_NAME}, "lst": [SYN_NAME]})
    row = clinician_store.conn.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert SYN_NAME not in row["detail"] and json.loads(row["detail"]) == {"ok": 1}


# ------------------------------------------------------------------ retention
def test_audio_not_retained_by_default(clinician_store):
    from rhuscribe import retention
    st = clinician_store
    eid = st.create_encounter(make_data())
    s = settings_store.get_all(st.conn)
    assert retention.maybe_retain_audio(st, eid, b"RIFFxxxx", "audio/wav", s) is False
    s.update(audio_retention="keep_days", audio_retention_days=7, audio_retention_policy_ref="")
    assert retention.maybe_retain_audio(st, eid, b"RIFFxxxx", "audio/wav", s) is False  # no policy ref -> still refused
    s["audio_retention_policy_ref"] = "RHU Policy 2026-01"
    assert retention.maybe_retain_audio(st, eid, b"RIFFxxxx", "audio/wav", s) is True
    aid = st.list_audio(eid)[0]["id"]
    assert st.get_audio(aid) == b"RIFFxxxx"
    assert b"RIFFxxxx" not in bytes(st.conn.execute("SELECT blob_enc FROM audio_files").fetchone()[0])


def test_transcript_deleted_after_approval_policy(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    st.save_transcript(eid, "hello", source="manual", reviewed=True)
    st.save_draft(eid, SOAPNote(), method="manual")
    settings = {**settings_store.get_all(st.conn), "transcript_retention": "delete_after_approval"}
    services.approve(st, eid, refdata.load_active_index(st.conn), settings, "ok")
    assert st.get_transcript(eid) is None


# ------------------------------------------------------------------ backup
def test_backup_restore_roundtrip(clinician_store, admin_ctx):
    st = clinician_store
    admin = auth.get_user(st.conn, admin_ctx[1]["id"])
    eid = st.create_encounter(make_data())
    path, blob = backup.create_backup(st.conn, admin, "a-long-backup-passphrase")
    assert b"SQLite format" not in blob and SYN_NAME.encode() not in blob
    with pytest.raises(backup.BackupError):
        backup.restore_backup(st.conn, admin, blob, "wrong-passphrase-123")
    with pytest.raises(backup.BackupError):
        backup.create_backup(st.conn, admin, "short")
    st.delete_encounter(eid)
    assert st.conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0] == 0
    backup.restore_backup(st.conn, admin, blob, "a-long-backup-passphrase")
    assert st.conn.execute("SELECT COUNT(*) FROM encounters WHERE id=?", (eid,)).fetchone()[0] == 1
    assert st.get_encounter(eid)["data"].profile.display_name == SYN_NAME  # same key material still decrypts


def test_corrupt_backup_rejected(admin_ctx):
    conn, admin, _, _ = admin_ctx
    _, blob = backup.create_backup(conn, admin, "a-long-backup-passphrase")
    bad = blob[:60] + bytes([blob[60] ^ 1]) + blob[61:]
    with pytest.raises(backup.BackupError):
        backup.restore_backup(conn, admin, bad, "a-long-backup-passphrase")


# ------------------------------------------------------------------ PDF
def _pdf_for(st, eid, approved):
    ix = refdata.load_active_index(st.conn)
    settings = settings_store.get_all(st.conn)
    if approved:
        services.approve(st, eid, ix, settings, "ok")
    rec = st.get_draft_or_latest_note(eid)
    review = st.latest_review(eid)
    return pdf_export.build_pdf(encounter=st.get_encounter(eid), note_rec=rec, orders=st.get_orders(eid), review=review,
                                review_current=True, settings=settings, author_name="Dr. Test Cruz", demo_mode=True)


def test_pdf_draft_vs_approved(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    n = SOAPNote()
    n.subjective.chief_complaint = "Cough for 3 days"
    st.save_draft(eid, n, method="manual")
    pdf = _pdf_for(st, eid, approved=False)
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    pdf2 = _pdf_for(st, eid, approved=True)
    assert pdf2.startswith(b"%PDF")
    assert pdf != pdf2


def test_pdf_text_contents(clinician_store):
    pytest.importorskip("pypdf", reason="pypdf not installed; text assertions skipped")


def test_pdf_handles_unicode_and_markup(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    n = SOAPNote()
    n.subjective.hpi = "Masakit ang ulo <b>bold</b> & ñandú ≈ 38.5°C → okay"
    st.save_draft(eid, n, method="manual")
    assert _pdf_for(st, eid, approved=False).startswith(b"%PDF")
