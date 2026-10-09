import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "build_reference"))
import build_bundle as bb  # noqa: E402
import extract_pnf as ep  # noqa: E402

from rhuscribe.safety import refdata  # noqa: E402
from rhuscribe.safety.engine import run_checks  # noqa: E402
from rhuscribe.schemas import MedicationOrder, PatientProfile  # noqa: E402


def test_contraindication_extraction_and_negation():
    t = "Known or suspected pregnancy. Severe renal impairment (CrCl <30). There are no known contraindications in asthma."
    got = bb.extract_contra(t)
    assert set(got) == {"pregnancy", "renal impairment"}


def test_age_extraction():
    r = bb.extract_age("Safety and effectiveness in pediatric patients below the age of 3 years has not been established.")
    assert r and r[0][0] == 3.0 and r[0][1] == "moderate"
    r2 = bb.extract_age("Safety and effectiveness in pediatric patients have not been established.")
    assert r2 and r2[0][0] == 18.0 and r2[0][1] == "minor"
    assert bb.extract_age("Use in adults is well tolerated.") == []


def test_pnf_name_cleaning():
    n, al, see, _ = ep.split_name("Epinephrine (adrenaline) (1, 2)")
    assert n == "Epinephrine" and al == ["adrenaline"]
    n, al, see, _ = ep.split_name("Adrenaline (see Epinephrine)")
    assert see == "Epinephrine"
    n, *_ = ep.split_name("Amlodipine (as besilate/camsylate)")
    assert n == "Amlodipine"


def test_large_style_bundle_imports_and_checks(conn):
    """A DDInter-style bundle (severity level only, auto-extracted label rules) must import as
    'awaiting review', work in demo mode, and be refused for clinical mode."""
    cite = "DDInter 2.0, CC BY-NC-SA 4.0"
    b = refdata.Bundle.model_validate({
        "meta": {"name": "mini", "version": "1", "source_description": "test bundle"},
        "ingredients": [{"key": "warfarin", "name": "Warfarin"}, {"key": "ibuprofen", "name": "Ibuprofen"},
                        {"key": "acetaminophen", "name": "Acetaminophen", "aliases": ["Paracetamol"]}],
        "interactions": [{"a": "warfarin", "b": "ibuprofen", "severity": "major", "effect": "level only", "management": "ask a pharmacist", "source_citation": cite}],
        "contraindications": [{"subject": "ibuprofen", "condition_terms": ["pregnancy"], "severity": "contraindicated", "note": "[Auto-extracted, verify]", "source_citation": cite}],
    })
    ds = refdata.save_bundle(conn, b, kind="imported", imported_by=None)
    ix = refdata.load_index(conn, ds)
    assert ix.dataset["status"] == "pending_review" and not ix.is_approved_for_clinical
    o = lambda n: MedicationOrder(drug_name=n, dose_amount=1, dose_unit="g", route="oral", frequency="OD", duration_days=1)  # noqa: E731
    r = run_checks(PatientProfile(age_value=30, sex="male", allergies_status="none_known", conditions_status="none_known"), 70, [o("warfarin"), o("Ibuprofen")], ix)
    assert any(f.check_type == "interactions" and f.severity == "major" for f in r.findings)
    assert r.approved_for_clinical is False
    import pytest
    with pytest.raises(refdata.RefError):
        refdata.set_active(conn, ds, clinical_mode=True)
    # dose checks for an ingredient with no limits are reported as unavailable, never as passed
    assert any(f.check_type == "dose" and f.category == "unknown_or_unavailable" for f in r.findings)
