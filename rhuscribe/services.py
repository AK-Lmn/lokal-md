"""Workflow services that combine storage, the rules engine and approval gating."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import retention
from .repo import Store
from .safety import refdata
from .safety.engine import ReviewResult, compute_input_hash, run_checks
from .safety.refdata import RefIndex
from .soap import unchecked_drug_mentions
from .transcription import has_uncertain


def get_reference_index(conn: sqlite3.Connection, settings: dict) -> RefIndex | None:
    """Active dataset index. In strict mode, fails closed unless the dataset is approved."""
    ix = refdata.load_active_index(conn)
    if ix and settings.get("operating_mode") == "clinical" and not ix.is_approved_for_clinical:
        return None
    return ix


def run_med_review(store: Store, enc_id: str, ix: RefIndex | None) -> dict:
    enc = store.get_encounter(enc_id)
    orders = store.get_orders(enc_id)
    d = enc["data"]
    res: ReviewResult = run_checks(d.profile, d.vitals.weight_kg, orders, ix)
    rid = store.save_review(enc_id, res.to_dict(), res.input_hash, (ix.dataset.get("id") if ix else None), res.overall)
    return store.get_review(rid)  # type: ignore[return-value]


def current_input_hash(store: Store, enc_id: str, ix: RefIndex | None) -> str:
    d = store.get_encounter(enc_id)["data"]
    return compute_input_hash(d.profile, d.vitals.weight_kg, store.get_orders(enc_id), ix.dataset.get("id", "") if ix else "none")


def review_is_current(store: Store, enc_id: str, review: dict | None, ix: RefIndex | None) -> bool:
    return bool(review) and review["input_hash"] == current_input_hash(store, enc_id, ix)  # type: ignore[index]


def required_acks(review: dict) -> list[dict]:
    """Findings that need a recorded clinician acknowledgement before approval."""
    return [f for f in review["result"]["findings"] if f["category"] in ("detected_concern", "potential_concern")]


@dataclass
class Readiness:
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers


def approval_readiness(store: Store, enc_id: str, ix: RefIndex | None, settings: dict) -> Readiness:
    r = Readiness()
    enc = store.get_encounter(enc_id)
    draft = store.get_draft(enc_id)
    if not draft:
        r.blockers.append("There is no draft note to approve. Generate or write a note first.")
        return r
    tr = store.get_transcript(enc_id)
    if tr:
        if has_uncertain(tr["text"]):
            r.blockers.append("The transcript still contains low-confidence [?] lines. Review them and remove the markers.")
        elif tr["status"] != "reviewed":
            r.blockers.append("The transcript has not been marked as reviewed.")
    orders = store.get_orders(enc_id)
    review = store.latest_review(enc_id)
    if settings.get("operating_mode") == "clinical" and ix is None:
        r.blockers.append("Strict mode requires an active, professionally approved medication reference dataset.")
    if orders or enc["data"].profile.current_medications:
        if not review:
            r.blockers.append("Medication safety check has not been run.")
        elif not review_is_current(store, enc_id, review, ix):
            r.blockers.append("Medication data changed after the last safety check. Re-run the check.")
        else:
            missing = [f for f in required_acks(review) if f["key"] not in review["acks"]]
            if missing:
                r.blockers.append(f"{len(missing)} safety finding(s) need a recorded clinician acknowledgement (with reason).")
            if review["result"]["overall"] in ("incomplete", "no_reference"):
                r.warnings.append("The medication check was incomplete or unavailable. Verify medications manually.")
    note = draft["note"]
    if note.flagged_items:
        r.warnings.append(f"{len(note.flagged_items)} AI-extracted item(s) were withheld as unsupported - confirm nothing important is missing.")
    if note.assessment.missing_information:
        r.warnings.append(f"{len(note.assessment.missing_information)} item(s) of missing information are listed in the note.")
    mentions = unchecked_drug_mentions([note.plan.treatment_plan, store.get_transcript_text(enc_id)], orders, enc["data"].profile.current_medications, ix)
    if mentions:
        r.warnings.append("Medicines mentioned but not entered as orders (so not safety-checked): " + ", ".join(mentions))
    return r


def approve(store: Store, enc_id: str, ix: RefIndex | None, settings: dict, attestation: str) -> dict:
    ready = approval_readiness(store, enc_id, ix, settings)
    if not ready.ok:
        raise ValueError("Cannot approve: " + " ".join(ready.blockers))
    review = store.latest_review(enc_id)
    out = store.approve_note(enc_id, review_id=review["id"] if review else None, attestation=attestation)
    retention.after_approval(store, enc_id, settings)
    return out
