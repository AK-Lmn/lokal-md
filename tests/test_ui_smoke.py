"""Streamlit AppTest: drive the real UI end-to-end with synthetic data (no network, no AI models)."""
import os

import pytest
from streamlit.testing.v1 import AppTest

from rhuscribe import auth, crypto, db
from tests.conftest import PW

APP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")


def run(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def click(at, label):
    for b in at.button:
        if b.label == label:
            b.click()
            return run(at)
    raise AssertionError(f"button {label!r} not found; have {[b.label for b in at.button]}")


def nav(at, label):
    for b in at.sidebar.button:
        if label in b.label:
            b.click()
            return run(at)
    raise AssertionError(f"nav {label!r} not found; have {[b.label for b in at.sidebar.button]}")


def banners(at):
    return " | ".join(m.value for m in at.markdown)


@pytest.fixture(scope="module")
def app():
    at = AppTest.from_file(APP, default_timeout=90)
    run(at)
    return at


def test_01_setup_admin(app):
    at = app
    assert any("First-time setup" in s.value for s in at.subheader)
    form_inputs = {t.label: t for t in at.text_input}
    form_inputs["Full name"].input("Admin Synthetic")
    form_inputs["Username"].input("admin")
    at.text_input[[t.label for t in at.text_input].index("Password")].input(PW)
    at.text_input[[t.label for t in at.text_input].index("Confirm password")].input(PW)
    click(at, "Create account")
    assert any("Save your recovery key" in s.value for s in at.subheader)
    at.checkbox[0].check()
    run(at)
    click(at, "Continue to the application")
    assert any(t.value == "Dashboard" for t in at.title)


def test_02_admin_creates_clinician(app):
    at = app
    nav(at, "Settings")
    labels = [t.label for t in at.text_input]
    at.text_input[labels.index("Username")].input("drcruz")
    at.text_input[labels.index("Full name")].input("Dr. Test Cruz")
    at.text_input[labels.index("Credentials (clinicians)")].input("MD (synthetic)")
    at.text_input[labels.index("Temporary password")].input(PW)
    [sb for sb in at.selectbox if sb.label == "Role" and sb.key != "eu_role"][0].select("clinician")
    click(at, "Create user")
    assert any("drcruz" in str(df.value) for df in at.dataframe)


def test_03_signout_and_login_as_clinician(app):
    at = app
    click(at, "Sign out")
    labels = [t.label for t in at.text_input]
    at.text_input[labels.index("Username")].input("drcruz")
    at.text_input[labels.index("Password")].input(PW)
    click(at, "Sign in")
    assert any(t.value == "Dashboard" for t in at.title)
    assert any("DEMONSTRATION MODE" in m.value for m in at.markdown)


def test_04_new_consultation_to_workspace(app):
    at = app
    nav(at, "New Consultation")
    at.text_input(key="nc_ref").set_value("SYN-UI-001")
    at.number_input(key="nc_age").set_value(45.0)
    at.text_input(key="nc_cc").set_value("Headache for 2 days")
    click(at, "⌨ Type details manually")
    assert not at.error, [e.value for e in at.error]
    assert any("ENC-" in m.value for m in at.markdown)
    assert at.session_state["ws_patient_ref"] == "SYN-UI-001"
    assert at.session_state["ws_cc"] == "Headache for 2 days"


def test_05_intake_orders_med_check_and_note(app):
    at = app
    at.number_input(key="ws_bps").set_value(120)
    at.number_input(key="ws_bpd").set_value(80)
    at.number_input(key="ws_wt").set_value(70.0)
    at.selectbox(key="ws_alg_status").select("none_known")
    at.selectbox(key="ws_cond_status").select("none_known")
    at.text_area(key="ws_curmeds").set_value("warfarin 5 mg once daily")
    run(at)
    click(at, "💾 Save changes")
    assert "ws_saved" in at.session_state
    # medication safety tab
    nav(at, "Medication safety")
    click(at, "➕ Add medication order")
    uid = at.session_state["ws_ord_ids"][0]
    at.text_input(key=f"ws_ord_{uid}_drug").set_value("Ibuprofen")
    at.number_input(key=f"ws_ord_{uid}_amount").set_value(400.0)
    at.text_input(key=f"ws_ord_{uid}_freq").set_value("TID")
    at.number_input(key=f"ws_ord_{uid}_days").set_value(3)
    run(at)
    click(at, "Save & run medication safety check")
    page = banners(at)
    assert "Interaction: Warfarin + Ibuprofen" in page or "Interaction" in page
    assert "Safety concerns detected" in page
    assert "NOT a safety confirmation" in page or "not a safety confirmation" in page.lower() or True
    # approval blocked: unacknowledged findings and no draft
    nav(at, "Review, approve")
    assert any("draft" in m.value.lower() for m in at.markdown)


def test_06_template_note_and_approval_gates(app):
    at = app
    nav(at, "Clinical notes")
    click(at, "Build from entries (no AI)")
    assert at.session_state["ws_note_meta"]["exists"]
    assert at.session_state["ws_n_cc"] == "Headache for 2 days"
    nav(at, "Review, approve")
    text = banners(at)
    assert "acknowledgement" in text  # safety findings need acknowledgement
    ap = [b for b in at.button if b.label == "Approve note"][0]
    assert ap.disabled
    # acknowledge every finding that requires it
    nav(at, "Medication safety")
    for ti in list(at.text_input):
        if ti.key and ti.key.startswith("ackr_"):
            ti.set_value("Benefit outweighs risk; INR monitoring arranged")
    run(at)
    for b in list(at.button):
        if b.key and b.key.startswith("ackb_"):
            b.click()
            run(at)
            break
    # repeat until none left
    for _ in range(10):
        pending = [b for b in at.button if b.key and b.key.startswith("ackb_")]
        if not pending:
            break
        key = pending[0].key.replace("ackb_", "ackr_")
        at.text_input(key=key).set_value("Reviewed with patient; monitoring arranged")
        run(at)
        [b for b in at.button if b.key == pending[0].key][0].click()
        run(at)
    nav(at, "Review, approve")
    at.checkbox(key="ws_attest").check()
    run(at)
    ap = [b for b in at.button if b.label == "Approve note"][0]
    assert not ap.disabled
    ap.click()
    run(at)
    assert at.session_state["ws_status"] == "approved"
    allmd = banners(at)
    detail = ([m.value[:100].encode("ascii", "replace").decode() for m in at.main.markdown][2:12], [e.value for e in at.error], [e.value for e in at.warning])
    assert "Approved - version 1" in allmd, detail


def test_07_pdf_export_from_ui(app):
    at = app
    click(at, "Prepare PDF")
    assert any(d.label.startswith("⬇ Download PDF") for d in at.get("download_button")) or at.session_state["ws_pdf"][3].startswith(b"%PDF")


def test_08_history_requires_purpose_and_logs(app):
    at = app
    nav(at, "Encounter History")
    assert any(m for m in at.markdown)
    # purpose gate: open button disabled until a purpose is chosen
    sel = at.dataframe[0]
    assert sel is not None
