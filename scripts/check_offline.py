"""Offline self-test. Run it with the network DISCONNECTED (Wi-Fi off / cable out) to verify that
every operational feature works without internet:

    python scripts/check_offline.py

It uses a throw-away data directory and synthetic data only. Exit code 0 = all checks passed.
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["RHUSCRIBE_DATA_DIR"] = tempfile.mkdtemp(prefix="rhu_offline_")

from rhuscribe import netguard  # noqa: E402

netguard.install()

from rhuscribe import auth, bootstrap, crypto, db, llm, pdf_export, services, settings_store, soap, transcription  # noqa: E402
from rhuscribe.repo import Store  # noqa: E402
from rhuscribe.safety import refdata  # noqa: E402
from rhuscribe.schemas import ClinicalInputs, EncounterData, MedicationOrder, PatientProfile  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        msg = fn() or ""
        results.append((name, True, msg))
    except Exception as e:  # noqa: BLE001
        results.append((name, False, f"{type(e).__name__}: {e}"))


ctx: dict = {}


def t_db():
    crypto.set_kdf_cost(2**12)
    ctx["conn"] = db.connect()
    bootstrap.init(ctx["conn"])
    user, rec, vault = auth.first_run_setup(ctx["conn"], "admin", "Offline Admin", "Offline-Test-Pass9")
    dek = vault.export_dek()
    auth.create_user(ctx["conn"], user, dek, "clin", "Offline Clinician", "clinician", "Offline-Test-Pass9", "MD (synthetic)")
    u, v = auth.login(ctx["conn"], "clin", "Offline-Test-Pass9")
    ctx["store"] = Store(ctx["conn"], v, u)
    return "encrypted DB, users, login"


def t_encounter():
    st = ctx["store"]
    eid = st.create_encounter(EncounterData(patient_ref="SYN-OFFLINE", profile=PatientProfile(age_value=40, sex="male", allergies_status="none_known", conditions_status="none_known"),
                                            inputs=ClinicalInputs(chief_complaint="Headache")))
    st.save_transcript(eid, "Patient has a headache for two days.", source="manual", reviewed=True)
    st.save_orders(eid, [MedicationOrder(drug_name="Paracetamol", dose_amount=500, dose_unit="mg", route="oral", frequency="q6h", duration_days=3)])
    ctx["eid"] = eid
    return eid


def t_review():
    st = ctx["store"]
    ix = refdata.load_active_index(st.conn)
    r = services.run_med_review(st, ctx["eid"], ix)
    return f"rules engine: {r['overall']}"


def t_note_pdf():
    st = ctx["store"]
    enc = st.get_encounter(ctx["eid"])
    n = soap.build_note(soap.NoteSource(enc["data"], st.get_transcript_text(ctx["eid"]), st.get_orders(ctx["eid"])), None)
    st.save_draft(ctx["eid"], n, method="template")
    pdf = pdf_export.build_pdf(encounter=st.get_encounter(ctx["eid"]), note_rec=st.get_draft(ctx["eid"]), orders=[], review=st.latest_review(ctx["eid"]),
                               review_current=True, settings=settings_store.get_all(st.conn))
    assert pdf.startswith(b"%PDF")
    return f"PDF {len(pdf) // 1024} KB"


def t_asr():
    s = settings_store.get_all(ctx["conn"])
    st = transcription.status(s["whisper_model"])
    if not st["ready"]:
        return "SKIPPED (model not installed: " + st["message"] + ")"
    transcription._load(s["whisper_model"], s["whisper_device"], s["whisper_compute_type"])
    return f"whisper '{s['whisper_model']}' loads from local files"


def t_llm():
    s = settings_store.get_all(ctx["conn"])
    st = llm.status(s["ollama_model"])
    if not st["ready"]:
        return "SKIPPED (" + st["message"] + ")"
    out = llm.chat_json(s["ollama_model"], "Reply with JSON.", 'Return {"ok": true}', None, timeout=120)
    return "local LLM answered: " + out.strip()[:40]


def t_guard():
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("8.8.8.8", 53))
    except netguard.OfflineViolation:
        return "outbound connection to 8.8.8.8 refused by guard"
    finally:
        s.close()
    raise AssertionError("guard did not block")


for name, fn in [("database & encryption", t_db), ("encounter storage", t_encounter), ("medication rules", t_review), ("note + PDF export", t_note_pdf),
                 ("speech model (local files)", t_asr), ("local LLM (Ollama on localhost)", t_llm), ("network guard", t_guard)]:
    check(name, fn)

ok = True
for name, passed, msg in results:
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {msg}")
    ok &= passed
print("\nBlocked outbound attempts during test:", netguard.BLOCKED_LOG or "none (besides the deliberate guard probe)")
print("RESULT:", "all checks passed" if ok else "FAILURES - see above")
sys.exit(0 if ok else 1)
