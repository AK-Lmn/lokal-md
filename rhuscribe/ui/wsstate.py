"""Session-state model of the consultation workspace.

All editable values live under `ws_*` keys so that (a) unsaved changes survive tab switches,
(b) dirty-state can be computed without rendering the widgets, and (c) a session lock can
auto-save or wipe them.
"""
from __future__ import annotations

import hashlib
import json
import uuid

import streamlit as st
from pydantic import ValidationError

from ..repo import Conflict, Store
from ..schemas import (
    Assessment, ClinicalInputs, EncounterData, MedicationOrder, Objective, PatientProfile, Plan, SOAPNote, Subjective, Vitals,
)
from ..soap import NoteSource, refresh_missing

INTAKE_DEFAULTS = {
    "ws_patient_ref": "", "ws_name": "", "ws_consult_type": "General consultation",
    "ws_age_value": None, "ws_age_unit": "years", "ws_sex": "unknown", "ws_preg": "unknown",
    "ws_alg_status": "unknown", "ws_allergies": "", "ws_cond_status": "unknown", "ws_conditions": "", "ws_curmeds": "", "ws_history": "",
    "ws_cc": "", "ws_exam": "", "ws_dx": "", "ws_plan": "", "ws_inv": "", "ws_ref": "", "ws_fu": "",
    "ws_bps": None, "ws_bpd": None, "ws_hr": None, "ws_rr": None, "ws_temp": None, "ws_spo2": None, "ws_wt": None, "ws_ht": None,
}
NOTE_FIELDS = {  # key -> (section, attr, is_list)
    "ws_n_cc": ("subjective", "chief_complaint", False), "ws_n_hpi": ("subjective", "hpi", False), "ws_n_hist": ("subjective", "relevant_history", False),
    "ws_n_symptoms": ("subjective", "symptoms", True), "ws_n_exam": ("objective", "exam_findings", True), "ws_n_other": ("objective", "other_findings", True),
    "ws_n_dx": ("assessment", "working_diagnosis", False), "ws_n_support": ("assessment", "supporting_findings", True),
    "ws_n_uncert": ("assessment", "uncertainties", True), "ws_n_tx": ("plan", "treatment_plan", False),
    "ws_n_inv": ("plan", "investigations", True), "ws_n_ref": ("plan", "referrals", True), "ws_n_fu": ("plan", "follow_up", False),
}
ORDER_FIELDS = ("drug", "strength", "amount", "unit", "route", "freq", "days", "indication", "instr")
ORDER_DEFAULTS = {"drug": "", "strength": "", "amount": None, "unit": "mg", "route": "oral", "freq": "", "days": None, "indication": "", "instr": ""}


def lines(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").splitlines() if x.strip()]


def active_id() -> str | None:
    return st.session_state.get("ws_enc_id")


def keep_state() -> None:
    """Streamlit drops widget state for widgets not rendered in a run; re-assigning keeps it."""
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("ws_"):
            st.session_state[k] = st.session_state[k]


def clear() -> None:
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("ws_"):
            del st.session_state[k]


# ----------------------------------------------------------------------------- load
def load(store: Store, enc_id: str, *, audit_view: bool = True) -> None:
    tab = st.session_state.get("ws_tab_ctl")
    clear()
    if tab:
        st.session_state["ws_tab_ctl"] = tab
    enc = store.get_encounter(enc_id, audit_view=audit_view)
    d: EncounterData = enc["data"]
    p, v, i = d.profile, d.vitals, d.inputs
    ss = st.session_state
    ss.update(
        ws_enc_id=enc_id, ws_status=enc["status"],
        ws_patient_ref=d.patient_ref, ws_name=p.display_name, ws_consult_type=d.consult_type,
        ws_age_value=p.age_value, ws_age_unit=p.age_unit, ws_sex=p.sex, ws_preg=p.pregnancy_status,
        ws_alg_status=p.allergies_status, ws_allergies="\n".join(p.allergies), ws_cond_status=p.conditions_status,
        ws_conditions="\n".join(p.conditions), ws_curmeds="\n".join(p.current_medications), ws_history=p.history_notes,
        ws_cc=i.chief_complaint, ws_exam=i.exam_findings, ws_dx=i.working_diagnosis, ws_plan=i.treatment_plan, ws_inv=i.investigations,
        ws_ref=i.referrals, ws_fu=i.follow_up,
        ws_bps=v.bp_systolic, ws_bpd=v.bp_diastolic, ws_hr=v.heart_rate, ws_rr=v.resp_rate, ws_temp=v.temp_c, ws_spo2=v.spo2, ws_wt=v.weight_kg, ws_ht=v.height_cm,
    )
    # orders
    ids = []
    for o in store.get_orders(enc_id):
        ids.append(o.id)
        for f, val in zip(ORDER_FIELDS, (o.drug_name, o.strength, o.dose_amount, o.dose_unit, o.route, o.frequency, o.duration_days, o.indication, o.instructions)):
            ss[f"ws_ord_{o.id}_{f}"] = val
    ss["ws_ord_ids"] = ids
    # transcript
    t = store.get_transcript(enc_id)
    ss["ws_transcript"] = t["text"] if t else ""
    ss["ws_tr_meta"] = {"source": t["source"], "status": t["status"], "language": t["language"], "model": t["asr_model"]} if t else {"source": "manual", "status": "none", "language": None, "model": None}
    # note
    load_note(store, enc_id)
    ss["ws_saved"] = {"intake": snap("intake"), "orders": snap("orders"), "transcript": snap("transcript"), "note": snap("note")}
    ss["ws_loaded_at_status"] = enc["status"]


def load_note(store: Store, enc_id: str) -> None:
    ss = st.session_state
    rec = store.get_draft(enc_id) or store.get_approved(enc_id)
    note: SOAPNote = rec["note"] if rec else SOAPNote()
    for key, (sec, attr, is_list) in NOTE_FIELDS.items():
        val = getattr(getattr(note, sec), attr)
        ss[key] = "\n".join(val) if is_list else val
    ss["ws_note_meta"] = {
        "exists": bool(rec), "status": rec["status"] if rec else None, "version": rec["version"] if rec else None, "method": rec["method"] if rec else None,
        "provenance": note.provenance, "flagged": note.flagged_items, "warnings": note.generation_warnings, "model": rec["model"] if rec else None,
    }


# ----------------------------------------------------------------------------- collect
def _g(k):
    return st.session_state.get(k, INTAKE_DEFAULTS.get(k))


def collect_encounter() -> EncounterData:
    return EncounterData(
        patient_ref=(_g("ws_patient_ref") or "").strip(), consult_type=_g("ws_consult_type") or "General consultation",
        profile=PatientProfile(
            display_name=(_g("ws_name") or "").strip(), age_value=_g("ws_age_value"), age_unit=_g("ws_age_unit"), sex=_g("ws_sex"),
            pregnancy_status=_g("ws_preg"), allergies_status=_g("ws_alg_status"), allergies=lines(_g("ws_allergies")),
            conditions_status=_g("ws_cond_status"), conditions=lines(_g("ws_conditions")), current_medications=lines(_g("ws_curmeds")),
            history_notes=_g("ws_history") or "",
        ),
        vitals=Vitals(bp_systolic=_g("ws_bps"), bp_diastolic=_g("ws_bpd"), heart_rate=_g("ws_hr"), resp_rate=_g("ws_rr"), temp_c=_g("ws_temp"),
                      spo2=_g("ws_spo2"), weight_kg=_g("ws_wt"), height_cm=_g("ws_ht")),
        inputs=ClinicalInputs(chief_complaint=_g("ws_cc") or "", exam_findings=_g("ws_exam") or "", working_diagnosis=_g("ws_dx") or "",
                              treatment_plan=_g("ws_plan") or "", investigations=_g("ws_inv") or "", referrals=_g("ws_ref") or "", follow_up=_g("ws_fu") or ""),
    )


def collect_orders() -> list[MedicationOrder]:
    out = []
    for uid in st.session_state.get("ws_ord_ids", []):
        g = lambda f: st.session_state.get(f"ws_ord_{uid}_{f}", ORDER_DEFAULTS[f])  # noqa: E731
        if not (g("drug") or "").strip():
            continue
        out.append(MedicationOrder(
            id=uid, drug_name=g("drug").strip(), strength=(g("strength") or "").strip(), dose_amount=g("amount") or None, dose_unit=(g("unit") or "").strip(),
            route=(g("route") or "").strip(), frequency=(g("freq") or "").strip(), duration_days=int(g("days")) if g("days") else None,
            indication=(g("indication") or "").strip(), instructions=(g("instr") or "").strip(),
        ))
    return out


def order_line(o: MedicationOrder) -> str:
    s = o.summary()
    if o.indication:
        s += f" - for {o.indication}"
    if o.instructions:
        s += f" ({o.instructions})"
    return s


def collect_note(data: EncounterData | None = None, orders: list[MedicationOrder] | None = None) -> SOAPNote:
    """Editable narrative from widgets + structured facts re-derived from the current intake/orders."""
    ss = st.session_state
    try:
        data = data or collect_encounter()
    except ValidationError:
        data = EncounterData()
    orders = orders if orders is not None else collect_orders()
    meta = ss.get("ws_note_meta", {})
    vals: dict[str, dict] = {"subjective": {}, "objective": {}, "assessment": {}, "plan": {}}
    for key, (sec, attr, is_list) in NOTE_FIELDS.items():
        raw = ss.get(key, "")
        vals[sec][attr] = lines(raw) if is_list else (raw or "").strip()
    p = data.profile
    note = SOAPNote(
        subjective=Subjective(**vals["subjective"], current_medications=p.current_medications, allergies=p.allergies, allergies_status=p.allergies_status),
        objective=Objective(**vals["objective"], vitals=data.vitals.lines()),
        assessment=Assessment(**vals["assessment"]),
        plan=Plan(**vals["plan"], medication_orders=[order_line(o) for o in orders]),
        provenance=meta.get("provenance", {}), flagged_items=meta.get("flagged", []), generation_warnings=meta.get("warnings", []),
    )
    return refresh_missing(note, NoteSource(data, ss.get("ws_transcript", ""), orders))


# ----------------------------------------------------------------------------- dirty tracking
def _h(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def snap(section: str) -> str:
    ss = st.session_state
    if section == "intake":
        return _h({k: ss.get(k) for k in INTAKE_DEFAULTS})
    if section == "orders":
        return _h([[uid] + [ss.get(f"ws_ord_{uid}_{f}") for f in ORDER_FIELDS] for uid in ss.get("ws_ord_ids", [])])
    if section == "transcript":
        return _h(ss.get("ws_transcript", ""))
    if section == "note":
        return _h({k: ss.get(k) for k in NOTE_FIELDS})
    raise KeyError(section)


def dirty_sections() -> list[str]:
    saved = st.session_state.get("ws_saved")
    if not saved or not active_id():
        return []
    return [s for s in saved if snap(s) != saved[s]]


def is_dirty() -> bool:
    return bool(dirty_sections())


def locked_for_edit() -> bool:
    return st.session_state.get("ws_status") in ("approved", "archived")


# ----------------------------------------------------------------------------- save
def save_all(store: Store, *, only: list[str] | None = None) -> list[str]:
    """Persist dirty sections. Returns human-readable messages. Raises on validation/permission errors."""
    enc_id = active_id()
    if not enc_id or locked_for_edit():
        return []
    ss = st.session_state
    sections = only or dirty_sections()
    msgs = []
    data = None
    if "intake" in sections or "note" in sections or "orders" in sections:
        data = collect_encounter()  # may raise ValidationError - caller shows it
    if "intake" in sections:
        store.update_encounter(enc_id, data)
        msgs.append("Intake saved")
    if "orders" in sections:
        store.save_orders(enc_id, collect_orders())
        msgs.append("Medication orders saved")
    if "transcript" in sections:
        text = ss.get("ws_transcript", "")
        meta = ss.get("ws_tr_meta", {})
        if text.strip():
            same = meta.get("status") == "reviewed" and ss["ws_saved"]["transcript"] == snap("transcript")
            reviewed = same or meta.get("source") == "manual"
            store.save_transcript(enc_id, text, source=meta.get("source", "manual"), language=meta.get("language"), asr_model=meta.get("model"), reviewed=reviewed)
            ss["ws_tr_meta"] = {**meta, "status": "reviewed" if reviewed else "unreviewed", "source": meta.get("source", "manual")}
            msgs.append("Transcript saved")
        else:
            store.delete_transcript(enc_id)
            ss["ws_tr_meta"] = {"source": "manual", "status": "none", "language": None, "model": None}
    meta = ss.get("ws_note_meta", {})
    if "note" in sections or (meta.get("exists") and ("intake" in sections or "orders" in sections)):
        note = collect_note(data)
        store.save_draft(enc_id, note, method=meta.get("method") or "manual", model=meta.get("model"))
        ss["ws_note_meta"] = {**meta, "exists": True, "status": "draft", "provenance": note.provenance}
        ss["ws_status"] = store.get_encounter(enc_id)["status"]
        msgs.append("Note draft saved")
    ss["ws_saved"] = {"intake": snap("intake"), "orders": snap("orders"), "transcript": snap("transcript"), "note": snap("note")}
    return msgs


def add_order() -> None:
    uid = str(uuid.uuid4())
    for f, val in ORDER_DEFAULTS.items():
        st.session_state[f"ws_ord_{uid}_{f}"] = val
    st.session_state.setdefault("ws_ord_ids", []).append(uid)


def remove_order(uid: str) -> None:
    st.session_state["ws_ord_ids"] = [u for u in st.session_state.get("ws_ord_ids", []) if u != uid]
    for f in ORDER_FIELDS:
        st.session_state.pop(f"ws_ord_{uid}_{f}", None)
