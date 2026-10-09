import pytest

from rhuscribe.safety.engine import run_checks
from rhuscribe.safety.normalize import parse_frequency, parse_strength, resolve_name
from rhuscribe.schemas import MedicationOrder, PatientProfile


def order(name, amt=500, unit="mg", route="oral", freq="TID", days=5, strength=""):
    return MedicationOrder(drug_name=name, dose_amount=amt, dose_unit=unit, route=route, frequency=freq, duration_days=days, strength=strength)


def profile(**kw):
    base = dict(age_value=35, age_unit="years", sex="male", allergies_status="none_known", conditions_status="none_known")
    base.update(kw)
    return PatientProfile(**base)


def cats(res, cat):
    return [f for f in res.findings if f.category == cat]


def types(res, cat):
    return {f.check_type for f in cats(res, cat)}


def test_brand_resolves_to_generic(ix):
    res = resolve_name("Biogesic 500 mg tab", ix.drug_alias)
    assert res.status == "resolved" and res.ingredients == ["paracetamol"]


def test_combination_product_expands(ix):
    res = resolve_name("Augmentin 625", ix.drug_alias)
    assert set(res.ingredients) == {"amoxicillin", "clavulanic_acid"}


def test_unknown_medication_never_autocorrected(ix):
    res = resolve_name("paracetmol", ix.drug_alias)
    assert res.status == "unknown" and res.ingredients == []
    assert "paracetamol" in res.suggestions


def test_interaction_detected_class_level(ix):
    r = run_checks(profile(), 70, [order("Warfarin", 5, "mg", freq="OD"), order("Ibuprofen", 400)], ix)
    inter = [f for f in cats(r, "detected_concern") if f.check_type == "interactions"]
    assert inter and inter[0].severity == "major"
    assert inter[0].evidence[0]["source"].startswith("SYNTHETIC-DEMO")
    assert r.overall == "concerns_detected"
    assert r.synthetic is True


def test_duplicate_brand_and_generic(ix):
    r = run_checks(profile(), 70, [order("Biogesic", 500), order("Paracetamol", 500)], ix)
    dups = [f for f in r.findings if f.check_type == "duplicates" and f.category == "detected_concern"]
    assert dups and "Paracetamol" in dups[0].title


def test_allergy_class_conflict(ix):
    r = run_checks(profile(allergies_status="listed", allergies=["penicillin"]), 70, [order("Amoxicillin", 500)], ix)
    assert any(f.check_type == "allergies" and f.category == "detected_concern" and f.severity == "contraindicated" for f in r.findings)


def test_allergy_cross_reactivity_is_potential(ix):
    r = run_checks(profile(allergies_status="listed", allergies=["Penicillin"]), 70, [order("Cefalexin", 500)], ix)
    assert any(f.check_type == "allergies" and f.category == "potential_concern" for f in r.findings)
    assert not any(f.check_type == "allergies" and f.category == "detected_concern" for f in r.findings)


def test_allergy_unknown_status_cannot_check(ix):
    r = run_checks(profile(allergies_status="unknown"), 70, [order("Amoxicillin", 500)], ix)
    assert "allergies" in types(r, "cannot_check")
    # must NOT claim a completed allergy check
    assert not any(f.check_type == "allergies" and f.category == "no_rules_triggered" for f in r.findings)


def test_age_warning_and_missing_age(ix):
    r = run_checks(profile(age_value=8), 25, [order("Aspirin", 300)], ix)
    assert any(f.check_type == "age" and f.category == "detected_concern" for f in r.findings)
    r2 = run_checks(profile(age_value=None), 25, [order("Aspirin", 300)], ix)
    assert "age" in types(r2, "cannot_check")


def test_contraindication_from_condition(ix):
    r = run_checks(profile(conditions_status="listed", conditions=["Chronic kidney disease stage 3"]), 70, [order("Ibuprofen", 400)], ix)
    assert any(f.check_type == "contraindications" and f.category == "detected_concern" for f in r.findings)


def test_pregnancy_unknown_flags_cannot_check(ix):
    r = run_checks(profile(sex="female", age_value=28, pregnancy_status="unknown"), 60, [order("Losartan", 50, freq="OD")], ix)
    assert any(f.category == "cannot_check" and f.check_type == "contraindications" for f in r.findings)
    r2 = run_checks(profile(sex="female", age_value=28, pregnancy_status="yes"), 60, [order("Losartan", 50, freq="OD")], ix)
    assert any(f.check_type == "contraindications" and f.severity == "contraindicated" for f in r2.findings)


def test_conditions_unknown_cannot_check(ix):
    r = run_checks(profile(conditions_status="unknown"), 70, [order("Ibuprofen", 400)], ix)
    assert any(f.check_type == "contraindications" and f.category == "cannot_check" for f in r.findings)


def test_daily_dose_exceeded(ix):
    r = run_checks(profile(), 70, [order("Paracetamol", 1000, freq="QID"), order("Paracetamol", 500, freq="BID")], ix)
    assert any(f.check_type == "dose" and "Daily dose above limit" in f.title for f in r.findings)


def test_daily_dose_within_limit_no_dose_alert(ix):
    r = run_checks(profile(), 70, [order("Paracetamol", 500, freq="q6h")], ix)
    assert not [f for f in r.findings if f.check_type == "dose" and f.category in ("detected_concern", "potential_concern")]


def test_tablet_dose_uses_strength(ix):
    r = run_checks(profile(), 70, [order("Paracetamol 500 mg", 3, "tablet", freq="QID")], ix)  # 6 g/day
    assert any(f.check_type == "dose" and f.category == "detected_concern" for f in r.findings)


def test_tablets_without_strength_is_incomplete_not_safe(ix):
    r = run_checks(profile(), 70, [order("Paracetamol", 2, "tablet", freq="QID")], ix)
    assert any(f.check_type == "dose" and f.category == "incomplete_check" for f in r.findings)
    assert r.overall != "no_rules_triggered"


def test_pediatric_per_kg_needs_weight(ix):
    r = run_checks(profile(age_value=5), None, [order("Paracetamol", 250, freq="QID")], ix)
    assert any(f.check_type == "dose" and f.category == "cannot_check" for f in r.findings)
    r2 = run_checks(profile(age_value=5), 18, [order("Paracetamol", 500, freq="QID")], ix)  # 2000mg/18kg = 111 mg/kg/day
    assert any(f.check_type == "dose" and f.category == "detected_concern" for f in r2.findings)


def test_syrup_mg_per_ml_conversion(ix):
    r = run_checks(profile(age_value=5), 18, [order("Paracetamol", 5, "mL", freq="QID", strength="120 mg/5 mL")], ix)  # 120mg*4=480mg/18kg=26.7 mg/kg/day OK
    assert not [f for f in r.findings if f.check_type == "dose" and f.category == "detected_concern"]


def test_unknown_drug_reported_and_not_safe(ix):
    r = run_checks(profile(), 70, [order("Zorblaxine", 10)], ix)
    assert cats(r, "unknown_or_unavailable")
    assert r.overall in ("incomplete",)
    assert "not evidence" in r.disclaimer.lower()


def test_missing_order_fields_incomplete(ix):
    o = MedicationOrder(drug_name="Amoxicillin")
    r = run_checks(profile(), 70, [o], ix)
    f = [x for x in r.findings if x.check_type == "order_completeness"]
    assert f and "dose amount" in f[0].explanation and "frequency" in f[0].explanation


def test_clean_case_is_never_called_safe(ix):
    r = run_checks(profile(), 70, [order("Paracetamol", 500, freq="q6h", days=3)], ix)
    assert r.overall in ("no_rules_triggered", "incomplete")
    assert all("not a safety confirmation" in f.explanation for f in cats(r, "no_rules_triggered"))
    text = " ".join(f.title + f.explanation for f in r.findings).lower().replace("not a safety confirmation", "")
    assert " safe" not in text
    assert all(f.severity == "info" for f in cats(r, "no_rules_triggered"))


def test_no_dataset_fails_closed():
    r = run_checks(profile(), 70, [order("Paracetamol")], None)
    assert r.overall == "no_reference" and r.findings[0].category == "unknown_or_unavailable"


def test_nothing_to_check(ix):
    assert run_checks(profile(), 70, [], ix).overall == "nothing_to_check"


def test_current_med_interaction_is_reported(ix):
    r = run_checks(profile(current_medications=["Warfarin 5 mg OD"]), 70, [order("Ibuprofen", 400)], ix)
    assert any(f.check_type == "interactions" for f in cats(r, "detected_concern"))


def test_input_hash_changes_with_inputs(ix):
    a = run_checks(profile(), 70, [order("Paracetamol", 500)], ix).input_hash
    b = run_checks(profile(), 70, [order("Paracetamol", 600)], ix).input_hash
    assert a != b


@pytest.mark.parametrize("text,per_day,prn", [
    ("TID", 3, False), ("twice daily", 2, False), ("q6h", 4, False), ("every 8 hours", 3, False),
    ("QID PRN", 4, True), ("once daily", 1, False), ("at bedtime", 1, False), ("2 times a day", 2, False),
])
def test_frequency_parser(text, per_day, prn):
    f = parse_frequency(text)
    assert f.ok and f.per_day == per_day and f.prn == prn


def test_frequency_garbage_not_ok():
    assert not parse_frequency("sometimes maybe").ok
    assert not parse_frequency("").ok


def test_strength_parser():
    assert parse_strength("500 mg").mg_per_unit == 500
    assert parse_strength("1 g").mg_per_unit == 1000
    assert parse_strength("125 mg/5 mL").mg_per_ml == 25
    assert parse_strength("500/125 mg").ambiguous
