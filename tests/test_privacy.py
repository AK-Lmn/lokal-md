"""Privacy / offline guarantees."""
import logging
import socket

import pytest

from rhuscribe import config, logsafe, netguard
from rhuscribe.schemas import ClinicalInputs, EncounterData, PatientProfile
from tests.test_core import SYN_NAME, make_data


def test_logs_never_contain_patient_data(clinician_store):
    st = clinician_store
    eid = st.create_encounter(make_data())
    st.save_transcript(eid, "Patient Juanita says she has chest pain", source="manual", reviewed=True)
    log = logsafe.get_logger()
    log.warning("unexpected failure for %s contact 09171234567 mail a@b.com password=hunter2", eid)
    try:
        raise ValueError(f"bad value {SYN_NAME}")
    except ValueError:
        log.exception("boom")
    for h in log.handlers:
        h.flush()
    text = (config.log_dir() / "app.log").read_text(encoding="utf-8")
    assert SYN_NAME not in text and "09171234567" not in text and "a@b.com" not in text and "hunter2" not in text
    assert "chest pain" not in text
    # audit rows only hold ids/status
    rows = " ".join(str(dict(r)) for r in st.conn.execute("SELECT * FROM audit_log"))
    assert SYN_NAME not in rows and "chest pain" not in rows and "SYN-0001" not in rows


def test_netguard_blocks_external_hosts_but_allows_loopback():
    netguard.install()
    s = socket.socket()
    s.settimeout(0.5)
    with pytest.raises(netguard.OfflineViolation):
        s.connect(("93.184.216.34", 80))
    with pytest.raises(netguard.OfflineViolation):
        s.connect_ex(("example.com", 443))
    s.close()
    assert "93.184.216.34" in netguard.BLOCKED_LOG
    s2 = socket.socket()
    s2.settimeout(0.5)
    assert s2.connect_ex(("127.0.0.1", 9)) != 0  # refused/timeout, but NOT blocked by the guard
    s2.close()


def test_llm_client_never_uses_proxy_or_remote_host(monkeypatch):
    from rhuscribe import llm
    monkeypatch.setenv("HTTP_PROXY", "http://evil.example:8080")
    assert llm.BASE.startswith("http://127.0.0.1:")


def test_transcription_never_downloads(monkeypatch, tmp_path):
    from rhuscribe import transcription
    monkeypatch.setenv("RHUSCRIBE_MODELS_DIR", str(tmp_path))
    st = transcription.status("small")
    assert not st["ready"] and "prepare_models" in st["message"]
    with pytest.raises(transcription.TranscriptionUnavailable):
        transcription.transcribe_bytes(b"RIFF....", ".wav", {"whisper_model": "small"})
    assert not list(tmp_path.rglob("*"))  # nothing was fetched or written


def test_source_has_no_remote_urls_or_telemetry():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parent.parent
    bad = []
    for f in list((root / "rhuscribe").rglob("*.py")) + [root / "app.py"]:
        for ln, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.findall(r"https?://[^\s\"')>]+", line):
                if not re.match(r"https?://(127\.0\.0\.1|localhost)", m) and "{" not in m:
                    bad.append((f.name, ln, m))
    allowed = {"ollama.com"}  # only appears in user-facing help text
    assert [b for b in bad if not any(a in b[2] for a in allowed)] == []
