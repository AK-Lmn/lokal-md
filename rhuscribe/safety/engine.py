"""Deterministic, explainable medication-safety rules engine.

No language model is involved. Every finding names the rule, the data that triggered it and
the citation recorded in the reference dataset. The engine never states that a prescription
is "safe": the strongest positive result is "no rules triggered in the installed reference
data", which is explicitly not a safety conclusion.

Finding categories (mirrors the product requirements):
  detected_concern    a rule matched using documented patient/order data
  potential_concern   a match that relies on inference or an uncertain input - needs review
  no_rules_triggered  a check completed and no rule matched (NOT proof of safety)
  incomplete_check    the check ran but inputs were ambiguous/incomplete
  unknown_or_unavailable  unknown medication name, or no reference data for it
  cannot_check        required patient information is missing so the check could not run
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

from ..schemas import MedicationOrder, PatientProfile
from .normalize import (
    COUNT_UNITS, MASS_TO_MG, Resolution, canon_unit, norm_text, parse_frequency, parse_strength, resolve_name,
)
from .refdata import RefIndex

CATEGORIES = [
    "detected_concern", "potential_concern", "incomplete_check", "unknown_or_unavailable", "cannot_check", "no_rules_triggered",
]
CATEGORY_LABELS = {
    "detected_concern": "Detected safety concern",
    "potential_concern": "Potential concern - review required",
    "no_rules_triggered": "Check completed - no rules triggered",
    "incomplete_check": "Incomplete check",
    "unknown_or_unavailable": "Unknown medication / reference unavailable",
    "cannot_check": "Cannot be checked - information missing",
}
SEV_RANK = {"contraindicated": 4, "major": 3, "moderate": 2, "minor": 1, "info": 0}
CHECK_LABELS = {
    "medication_names": "Medication identification",
    "order_completeness": "Order completeness",
    "duplicates": "Duplicate ingredients",
    "interactions": "Drug-drug interactions",
    "allergies": "Allergy conflicts",
    "age": "Age-specific warnings",
    "contraindications": "Contraindications",
    "dose": "Dose limits",
}
NO_SAFETY_STATEMENT = (
    "Absence of alerts is not evidence that a prescription is safe. This tool only evaluates the rules present in the "
    "installed reference dataset and the information entered for this encounter. The prescriber remains responsible."
)


@dataclass
class Finding:
    key: str
    check_type: str
    category: str
    severity: str
    title: str
    explanation: str
    involved: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    next_step: str = ""


@dataclass
class MedItem:
    source: str  # order | current
    display: str
    res: Resolution
    order: MedicationOrder | None = None


@dataclass
class ReviewResult:
    overall: str
    findings: list[Finding]
    checks: list[dict]
    meds: list[dict]
    dataset: dict
    input_hash: str
    rule_count: int
    synthetic: bool
    approved_for_clinical: bool
    disclaimer: str = NO_SAFETY_STATEMENT

    def to_dict(self) -> dict:
        return {
            "overall": self.overall, "findings": [asdict(f) for f in self.findings], "checks": self.checks, "meds": self.meds,
            "dataset": self.dataset, "input_hash": self.input_hash, "rule_count": self.rule_count,
            "synthetic": self.synthetic, "approved_for_clinical": self.approved_for_clinical, "disclaimer": self.disclaimer,
        }

    def by_category(self, cat: str) -> list[Finding]:
        return [f for f in self.findings if f.category == cat]


OVERALL_LABELS = {
    "concerns_detected": "Safety concerns detected - clinician review required",
    "review_required": "Potential concerns - clinician review required",
    "incomplete": "Check incomplete - see items below",
    "no_rules_triggered": "No rules triggered in installed reference data (this is NOT a safety confirmation)",
    "nothing_to_check": "No medications entered - nothing to check",
    "no_reference": "No medication reference data is active - no checks could be performed",
}


def compute_input_hash(profile: PatientProfile, weight_kg: float | None, orders: list[MedicationOrder], dataset_id: str) -> str:
    payload = {
        "p": profile.model_dump(), "w": weight_kg, "ds": dataset_id,
        "o": [o.model_dump(exclude={"id"}) for o in orders],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


def _fkey(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _ev(ix: RefIndex, rule: str, citation: str) -> dict:
    return {"rule": rule, "source": citation, "dataset": f"{ix.dataset.get('name')} v{ix.dataset.get('version')}"}


def _cond_match(terms: list[str], profile: PatientProfile) -> str | None:
    for c in profile.conditions:
        cn = norm_text(c)
        for t in terms:
            if t and (re.search(rf"\b{re.escape(t)}\b", cn) or re.search(rf"\b{re.escape(cn)}\b", t)):
                return c
    if profile.pregnancy_status == "yes" and any(t.startswith("pregnan") for t in terms):
        return "pregnancy (recorded)"
    return None


def _could_be_pregnant(p: PatientProfile) -> bool:
    return p.sex == "female" and p.pregnancy_status == "unknown" and (p.age_years is None or 10 <= p.age_years <= 55)


def run_checks(
    profile: PatientProfile, weight_kg: float | None, orders: list[MedicationOrder], ix: RefIndex | None
) -> ReviewResult:
    if ix is None:
        return ReviewResult("no_reference", [Finding("noref", "medication_names", "unknown_or_unavailable", "info",
                            "No medication reference data is active",
                            "No dataset is loaded, so no interaction, allergy, contraindication, age or dose checks were performed.",
                            next_step="Ask an administrator to activate a reference dataset (Settings > Medication reference).")],
                            [], [], {}, "none", 0, False, False)
    orders = [o for o in orders if o.drug_name.strip()]
    ds_id = ix.dataset.get("id", "")
    ihash = compute_input_hash(profile, weight_kg, orders, ds_id)
    findings: list[Finding] = []
    checks: dict[str, dict] = {k: {"check_type": k, "label": v, "status": "not_run", "detail": "", "matches": 0} for k, v in CHECK_LABELS.items()}

    def add(f: Finding):
        findings.append(f)

    def mark(check, status, detail=""):
        c = checks[check]
        c["status"], c["detail"] = status, detail

    # ---- resolve every medication ------------------------------------------------
    items: list[MedItem] = [MedItem("order", o.summary(), resolve_name(o.drug_name, ix.drug_alias), o) for o in orders]
    for m in profile.current_medications:
        items.append(MedItem("current", m, resolve_name(m, ix.drug_alias)))

    if not items:
        return ReviewResult("nothing_to_check", [], list(checks.values()), [], _ds_meta(ix), ihash, ix.rule_count, ix.is_synthetic, ix.is_approved_for_clinical)

    meds_out = []
    unresolved_orders = 0
    for it in items:
        r = it.res
        meds_out.append({"source": it.source, "entered": it.display, "status": r.status,
                         "ingredients": [ix.ingredients.get(k, k) for k in r.ingredients], "suggestions": r.suggestions})
        label = "ordered medication" if it.source == "order" else "current medication"
        if r.status in ("unknown", "empty"):
            if it.source == "order":
                unresolved_orders += 1
            sug = f" Possible matches (not applied automatically): {', '.join(r.suggestions)}." if r.suggestions else ""
            add(Finding(_fkey("unk", it.source, it.display), "medication_names", "unknown_or_unavailable", "moderate",
                        f"Unknown {label}: \"{it.display}\"",
                        f"The name was not found in the installed reference data, so no interaction, allergy, age, contraindication or dose "
                        f"rule could be evaluated for it.{sug}", [it.display],
                        next_step="Check the spelling or use the generic name; verify manually against an authoritative reference."))
        elif r.status == "partial":
            add(Finding(_fkey("part", it.source, it.display), "medication_names", "incomplete_check", "minor",
                        f"Name only partly recognised: \"{it.display}\"",
                        f"Recognised: {', '.join(ix.ingredients.get(k, k) for k in r.ingredients)}. Not recognised: {', '.join(r.leftover)}. "
                        f"Another ingredient may be present and unchecked.", [it.display],
                        next_step="Confirm the full product composition and re-enter using generic names."))
    n_unres = sum(1 for i in items if i.res.status in ("unknown", "empty"))
    mark("medication_names", "partial" if n_unres else "ran_no_match",
         f"{len(items) - n_unres} of {len(items)} medication entries identified in the reference data")

    # ---- ingredient pool -----------------------------------------------------------
    pool: dict[str, list[MedItem]] = {}
    for it in items:
        for k in it.res.ingredients:
            pool.setdefault(k, []).append(it)

    def nm(k):
        return ix.ingredients.get(k, k)

    # ---- order completeness ----------------------------------------------------------
    gaps = 0
    for it in items:
        if it.source != "order" or it.order is None:
            continue
        o = it.order
        missing = []
        if not o.dose_amount:
            missing.append("dose amount")
        if not o.dose_unit.strip():
            missing.append("dose unit")
        elif canon_unit(o.dose_unit) not in {"mg", "g", "mcg", "ml", "tablet", "capsule", "drop", "puff", "sachet", "iu", "unit", "ampule", "vial"}:
            missing.append(f"recognisable dose unit (\"{o.dose_unit}\")")
        if not o.route.strip():
            missing.append("route")
        fr = parse_frequency(o.frequency)
        if not o.frequency.strip():
            missing.append("frequency")
        elif not fr.ok:
            missing.append(f"interpretable frequency (\"{o.frequency}\")")
        if not o.duration_days:
            missing.append("duration")
        if missing:
            gaps += 1
            add(Finding(_fkey("cmp", o.id or o.drug_name), "order_completeness", "incomplete_check", "moderate",
                        f"Incomplete order: {o.drug_name}", f"Missing or ambiguous: {', '.join(missing)}. Dose and frequency checks depend on these.",
                        [o.drug_name], next_step="Complete the order fields before relying on the dose checks."))
    n_orders = sum(1 for i in items if i.source == "order")
    if n_orders:
        mark("order_completeness", "partial" if gaps else "ran_no_match", f"{n_orders - gaps} of {n_orders} orders fully specified")
    else:
        mark("order_completeness", "not_run", "No orders entered")

    # ---- duplicates --------------------------------------------------------------------
    dup_found = 0
    for k, its in pool.items():
        # brand+generic aliases of the same ingredient entered twice are caught here
        if len(its) > 1:
            dup_found += 1
            orders_n = sum(1 for i in its if i.source == "order")
            cat = "detected_concern" if orders_n >= 2 else "potential_concern"
            add(Finding(_fkey("dup", k), "duplicates", cat, "moderate" if orders_n >= 2 else "minor",
                        f"Duplicate active ingredient: {nm(k)}",
                        f"{nm(k)} appears in more than one entry: " + "; ".join(f"{i.display} ({'new order' if i.source == 'order' else 'current medication'})" for i in its)
                        + ". Brand and generic names that map to the same ingredient are treated as duplicates."
                        + ("" if orders_n >= 2 else " A new order duplicating a current medication may be an intended continuation."),
                        [i.display for i in its], [_ev(ix, "ingredient-match", "Alias table of active dataset")],
                        "Confirm whether both entries are intended; remove or reconcile any unintended duplicate."))
    mark("duplicates", "ran_match" if dup_found else ("partial" if n_unres else "ran_no_match"),
         f"{dup_found} duplicate ingredient group(s)")
    checks["duplicates"]["matches"] = dup_found

    # ---- interactions --------------------------------------------------------------------
    keys = list(pool)
    seen_pairs = set()
    inter_found = 0
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            for rule in ix.interaction_rules(a, b):
                pk = (frozenset((a, b)), rule["id"])
                if pk in seen_pairs:
                    continue
                seen_pairs.add(pk)
                inter_found += 1
                ia, ib = pool[a][0], pool[b][0]
                both_orders = ia.source == "order" and ib.source == "order"
                inferential = rule["severity"] == "minor"
                cat = "potential_concern" if inferential else "detected_concern"
                add(Finding(_fkey("int", rule["id"], a, b), "interactions", cat, rule["severity"],
                            f"Interaction: {nm(a)} + {nm(b)}", f"{rule['effect']} ({'both new orders' if both_orders else 'involves a current medication whose dose/adherence is not verified'}).",
                            [ia.display, ib.display], [_ev(ix, f"interaction#{rule['id']}", rule["source_citation"])], rule["management"]))
    unresolved_any = n_unres > 0 or any(i.res.status == "partial" for i in items)
    if len(keys) < 2 and not inter_found:
        mark("interactions", "not_run" if not unresolved_any else "partial", "Fewer than two identified ingredients to compare")
    else:
        mark("interactions", "ran_match" if inter_found else ("partial" if unresolved_any else "ran_no_match"),
             f"{len(keys)} identified ingredients compared against {len(ix.interactions)} interaction rules")
    checks["interactions"]["matches"] = inter_found

    # ---- allergies ---------------------------------------------------------------------------
    allergy_matches = 0
    if profile.allergies_status == "unknown":
        add(Finding("allergy-unknown", "allergies", "cannot_check", "moderate", "Allergy status not recorded",
                    "Allergies were not asked/recorded, so allergy conflicts cannot be checked.", [],
                    next_step="Ask about drug allergies and record them (or record 'no known allergies')."))
        mark("allergies", "cannot_run", "Allergy history not recorded")
    elif profile.allergies_status == "none_known":
        mark("allergies", "ran_no_match", "No known allergies recorded - nothing to compare")
    else:
        if not profile.allergies:
            add(Finding("allergy-empty", "allergies", "cannot_check", "moderate", "Allergies marked as present but none listed",
                        "The record says the patient has allergies but no allergen is listed.", [], next_step="List the allergens."))
            mark("allergies", "cannot_run", "No allergen listed")
        else:
            unmapped = 0
            for al in profile.allergies:
                targets: list[tuple[str, str]] = []
                an = norm_text(al)
                for phrase in [an] + [t for t in an.split()]:
                    for t in ix.any_alias.get(phrase, []):
                        if t not in targets:
                            targets.append(t)
                if not targets:
                    unmapped += 1
                    add(Finding(_fkey("alg-unm", al), "allergies", "incomplete_check", "minor", f"Allergen not mapped: \"{al}\"",
                                "This allergen is not a drug or drug class in the reference data (it may be a food, latex or another non-drug allergen), "
                                "so no automated comparison was possible.", [al], next_step="Review manually against the planned medications and excipients."))
                    continue
                for ing in keys:
                    for (tt, tk) in targets:
                        direct = ix.matches(tt, tk, ing)
                        same_class = tt == "ingredient" and (ix.classes_of(tk) & ix.classes_of(ing)) and tk != ing
                        if direct:
                            allergy_matches += 1
                            add(Finding(_fkey("alg", al, ing), "allergies", "detected_concern", "contraindicated",
                                        f"Allergy conflict: {nm(ing)} vs recorded allergy \"{al}\"",
                                        f"The recorded allergy \"{al}\" matches {nm(ing)} ({'same drug' if tt == 'ingredient' else 'drug class ' + ix.classes.get(tk, tk)}).",
                                        [pool[ing][0].display, al], [_ev(ix, "allergen-match", "Alias/class table of active dataset")],
                                        "Do not give without clinician review of the allergy history and reaction type."))
                        elif same_class:
                            allergy_matches += 1
                            shared = ", ".join(ix.classes.get(c, c) for c in ix.classes_of(tk) & ix.classes_of(ing))
                            add(Finding(_fkey("alg-cls", al, ing), "allergies", "potential_concern", "moderate",
                                        f"Possible same-class allergy: {nm(ing)} vs \"{al}\"",
                                        f"{nm(ing)} shares a drug class ({shared}) with the allergen \"{al}\". Cross-sensitivity is possible but not established by this rule.",
                                        [pool[ing][0].display, al], [_ev(ix, "shared-class", "Class membership in active dataset")],
                                        "Review the allergy history before prescribing."))
                    for rule in ix.allergy_cross:
                        if _allergen_hits(ix, targets, rule["al_t"]) and ix.matches(rule["dr_t"][0], rule["dr_t"][1], ing):
                            allergy_matches += 1
                            add(Finding(_fkey("alg-x", rule["id"], al, ing), "allergies", "potential_concern", rule["severity"],
                                        f"Cross-reactivity: {nm(ing)} vs allergy \"{al}\"", rule["note"], [pool[ing][0].display, al],
                                        [_ev(ix, f"allergy_cross#{rule['id']}", rule["source_citation"])], "Review the allergy history and reaction type before prescribing."))
            mark("allergies", "ran_match" if allergy_matches else ("partial" if (unmapped or unresolved_any) else "ran_no_match"),
                 f"{len(profile.allergies)} recorded allergen(s) compared with {len(keys)} ingredient(s)")
    checks["allergies"]["matches"] = allergy_matches

    # ---- age -------------------------------------------------------------------------------------
    age = profile.age_years
    age_found = 0
    relevant_age_rules = {k for k in keys for r in ix.age_warnings if ix.matches(r["s_t"][0], r["s_t"][1], k)}
    if age is None:
        if keys:
            if relevant_age_rules:
                add(Finding("age-unknown", "age", "cannot_check", "moderate", "Patient age not recorded",
                            f"Age-specific warnings exist for {', '.join(nm(k) for k in sorted(relevant_age_rules))} but cannot be evaluated without the patient's age.",
                            [], next_step="Record the patient's age."))
            else:
                add(Finding("age-unknown", "age", "cannot_check", "minor", "Patient age not recorded",
                            "Age-specific checks were not performed because the age is missing.", [], next_step="Record the patient's age."))
            mark("age", "cannot_run", "Age not recorded")
    else:
        for k in keys:
            for r in ix.age_warnings:
                if not ix.matches(r["s_t"][0], r["s_t"][1], k):
                    continue
                lo, hi = r.get("min_age_years"), r.get("max_age_years")
                if (lo is None or age >= lo) and (hi is None or age < hi):
                    age_found += 1
                    add(Finding(_fkey("age", r["id"], k), "age", "detected_concern", r["severity"], f"Age warning: {nm(k)}",
                                f"{r['message']} Patient age recorded as {profile.age_text()}.", [pool[k][0].display],
                                [_ev(ix, f"age_warning#{r['id']}", r["source_citation"])], r["management"] or "Clinician review."))
        if keys:
            mark("age", "ran_match" if age_found else ("partial" if unresolved_any else "ran_no_match"), f"Patient age {profile.age_text()}")
    checks["age"]["matches"] = age_found

    # ---- contraindications ---------------------------------------------------------------------------
    contra_found = 0
    rel_contra = {(k, r["id"]) for k in keys for r in ix.contraindications if ix.matches(r["s_t"][0], r["s_t"][1], k)}
    if rel_contra and profile.conditions_status == "unknown":
        ks = sorted({k for k, _ in rel_contra})
        add(Finding("cond-unknown", "contraindications", "cannot_check", "moderate", "Medical conditions not recorded",
                    f"Contraindication rules exist for {', '.join(nm(k) for k in ks)}, but the patient's conditions were not recorded, so they cannot be evaluated.",
                    [], next_step="Record relevant conditions (or record 'none known')."))
    for k in keys:
        for r in ix.contraindications:
            if not ix.matches(r["s_t"][0], r["s_t"][1], k):
                continue
            hit = _cond_match(r["condition_terms"], profile)
            if hit:
                contra_found += 1
                add(Finding(_fkey("ci", r["id"], k), "contraindications", "detected_concern", r["severity"], f"Contraindication/caution: {nm(k)} with {hit}",
                            f"{r['note']} Matched against recorded: {hit}.", [pool[k][0].display, hit], [_ev(ix, f"contraindication#{r['id']}", r["source_citation"])],
                            r["management"] or "Clinician review."))
            elif any(t.startswith("pregnan") for t in r["condition_terms"]) and _could_be_pregnant(profile):
                add(Finding(_fkey("ci-preg", r["id"], k), "contraindications", "cannot_check", "moderate", f"Pregnancy status unknown: {nm(k)}",
                            f"A pregnancy-related rule exists for {nm(k)} but pregnancy status was not recorded for this patient.", [pool[k][0].display],
                            [_ev(ix, f"contraindication#{r['id']}", r["source_citation"])], "Record pregnancy status before prescribing."))
    if keys:
        pend = bool(rel_contra and profile.conditions_status == "unknown") or any(f.key.startswith("ci-preg") for f in findings)
        mark("contraindications", "ran_match" if contra_found else ("partial" if (pend or unresolved_any) else "ran_no_match"),
             f"{len(keys)} ingredient(s) compared with {len(ix.contraindications)} contraindication rules")
    checks["contraindications"]["matches"] = contra_found

    # ---- dose limits ----------------------------------------------------------------------------------------
    dose_found = 0
    dose_checked = 0
    dose_unavailable = []
    by_ing_orders: dict[str, list[MedItem]] = {}
    for it in items:
        if it.source == "order":
            for k in it.res.ingredients:
                by_ing_orders.setdefault(k, []).append(it)
    for k, its in by_ing_orders.items():
        limits = [r for r in ix.dose_limits if r["ingredient"] == k]
        if not limits:
            dose_unavailable.append(k)
            continue
        if age is None and any(r["min_age_years"] is not None or r["max_age_years"] is not None for r in limits):
            add(Finding(_fkey("dose-age", k), "dose", "cannot_check", "moderate", f"Dose limit for {nm(k)} needs the patient's age",
                        "Dose limits differ by age band, and age is not recorded.", [its[0].display], next_step="Record the patient's age."))
            continue
        applicable = [r for r in limits if age is None or ((r["min_age_years"] is None or age >= r["min_age_years"]) and (r["max_age_years"] is None or age < r["max_age_years"]))]
        if not applicable:
            dose_unavailable.append(k)
            continue
        total_mg, total_ok, prn_any = 0.0, True, False
        for it in its:
            o = it.order
            assert o is not None
            multi = len(it.res.ingredients) > 1
            st = parse_strength(o.strength, o.drug_name)
            fr = parse_frequency(o.frequency)
            mg = _dose_mg(o, st)
            if multi:
                add(Finding(_fkey("dose-combo", o.id, k), "dose", "incomplete_check", "minor", f"Dose not computed for combination product: {o.drug_name}",
                            f"Per-ingredient amounts for {nm(k)} in a combination product cannot be derived from the entered information.", [o.drug_name],
                            next_step="Verify the ingredient-level dose manually."))
                total_ok = False
                continue
            if mg is None:
                add(Finding(_fkey("dose-unk", o.id, k), "dose", "incomplete_check", "moderate", f"Dose of {o.drug_name} could not be converted to mg",
                            "The dose amount/unit and strength do not allow a numeric daily-dose calculation (e.g. tablets without a strength, or a missing dose).", [o.drug_name],
                            next_step="Enter the strength and dose amount/unit, then re-run the check."))
                total_ok = False
                continue
            dose_checked += 1
            for lim in applicable:
                if lim["route"] and o.route.strip() and norm_text(o.route) != norm_text(lim["route"]):
                    continue
                single_mg = mg
                if lim["per_kg"]:
                    if not weight_kg:
                        add(Finding(_fkey("dose-wt", lim["id"], k), "dose", "cannot_check", "moderate", f"Weight needed for per-kg dose check: {nm(k)}",
                                    "The applicable limit is expressed per kg body weight, and the patient's weight is not recorded.", [o.drug_name], next_step="Record the patient's weight."))
                        total_ok = False
                        break
                    single_mg = mg / weight_kg
                f = MASS_TO_MG.get(lim["unit"], 1.0)
                unit_lbl = f"{lim['unit']}/kg" if lim["per_kg"] else lim["unit"]
                if lim["max_single"] is not None and single_mg > lim["max_single"] * f + 1e-9:
                    dose_found += 1
                    add(Finding(_fkey("dose-s", lim["id"], o.id), "dose", "detected_concern", "major", f"Single dose above limit: {o.drug_name}",
                                f"Entered single dose ≈ {single_mg / f:.4g} {unit_lbl}; reference limit {lim['max_single']:g} {unit_lbl}. {lim['note']}",
                                [o.drug_name], [_ev(ix, f"dose_limit#{lim['id']}", lim["source_citation"])], "Re-check the dose and units with the prescriber/pharmacist."))
            if fr.ok and fr.per_day:
                total_mg += mg * fr.per_day
                prn_any = prn_any or fr.prn
            else:
                total_ok = False
        if total_ok and total_mg > 0:
            for lim in applicable:
                if lim["max_daily"] is None:
                    continue
                f = MASS_TO_MG.get(lim["unit"], 1.0)
                daily = total_mg / weight_kg if lim["per_kg"] and weight_kg else total_mg
                if lim["per_kg"] and not weight_kg:
                    continue
                if daily > lim["max_daily"] * f + 1e-9:
                    dose_found += 1
                    cat = "potential_concern" if prn_any else "detected_concern"
                    unit_lbl = f"{lim['unit']}/kg" if lim["per_kg"] else lim["unit"]
                    add(Finding(_fkey("dose-d", lim["id"], k), "dose", cat, "major", f"Daily dose above limit: {nm(k)}",
                                f"Calculated total ≈ {daily / f:.4g} {unit_lbl}/day{' (PRN: assumes the maximum number of doses)' if prn_any else ''}; reference limit {lim['max_daily']:g} {unit_lbl}/day. {lim['note']}",
                                [i.display for i in its], [_ev(ix, f"dose_limit#{lim['id']}", lim["source_citation"])], "Re-check dose, frequency and units; adjust if unintended."))
    for k in dose_unavailable:
        add(Finding(_fkey("dose-na", k), "dose", "unknown_or_unavailable", "minor", f"No applicable dose limit in reference data: {nm(k)}",
                    f"The dataset has no dose limit for {nm(k)} for this patient's age/route, so the dose was not verified.", [by_ing_orders[k][0].display],
                    next_step="Verify the dose against an authoritative reference."))
    if by_ing_orders:
        dose_partial = bool(dose_unavailable) or n_unres or any(f.check_type == "dose" and f.category in ("incomplete_check", "cannot_check") for f in findings)
        mark("dose", "ran_match" if dose_found else ("partial" if dose_partial else "ran_no_match"),
             f"{dose_checked} order(s) converted to mg and compared; {len(dose_unavailable)} ingredient(s) without a limit in the dataset")
    checks["dose"]["matches"] = dose_found

    # ---- no-rules-triggered summaries (never "safe") --------------------------------------------------------------
    for ck in ("duplicates", "interactions", "allergies", "age", "contraindications", "dose"):
        c = checks[ck]
        if c["status"] == "ran_no_match":
            add(Finding(f"none-{ck}", ck, "no_rules_triggered", "info", f"{CHECK_LABELS[ck]}: no rules triggered",
                        f"{c['detail']}. No matching rule was found in the installed reference data. This is not a safety confirmation.", [],
                        next_step="Continue normal clinical judgement."))

    findings.sort(key=lambda f: (CATEGORIES.index(f.category), -SEV_RANK.get(f.severity, 0)))
    if any(f.category == "detected_concern" for f in findings):
        overall = "concerns_detected"
    elif any(f.category == "potential_concern" for f in findings):
        overall = "review_required"
    elif any(f.category in ("incomplete_check", "unknown_or_unavailable", "cannot_check") for f in findings) or any(c["status"] in ("partial", "cannot_run") for c in checks.values()):
        overall = "incomplete"
    elif not n_orders and not profile.current_medications:
        overall = "nothing_to_check"
    else:
        overall = "no_rules_triggered"
    return ReviewResult(overall, findings, list(checks.values()), meds_out, _ds_meta(ix), ihash, ix.rule_count, ix.is_synthetic, ix.is_approved_for_clinical)


def _allergen_hits(ix: RefIndex, targets: list[tuple[str, str]], rule_al: tuple[str, str]) -> bool:
    for tt, tk in targets:
        if rule_al == (tt, tk):
            return True
        if rule_al[0] == "class" and tt == "ingredient" and rule_al[1] in ix.classes_of(tk):
            return True
    return False


def _ds_meta(ix: RefIndex) -> dict:
    d = ix.dataset
    return {k: d.get(k) for k in ("id", "name", "version", "kind", "status", "source_description")}


def _dose_mg(o: MedicationOrder, st) -> float | None:
    if not o.dose_amount:
        return None
    u = canon_unit(o.dose_unit)
    if u in MASS_TO_MG:
        return o.dose_amount * MASS_TO_MG[u]
    if u in COUNT_UNITS:
        if st.mg_per_unit:
            return o.dose_amount * st.mg_per_unit
        return None
    if u == "ml":
        if st.mg_per_ml:
            return o.dose_amount * st.mg_per_ml
        return None
    return None
