"""Pydantic models for encounter data, medication orders and SOAP notes."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

NOT_DOCUMENTED = "Not documented"

Sex = Literal["female", "male", "other", "unknown"]
Pregnancy = Literal["yes", "no", "unknown", "not_applicable"]
ListStatus = Literal["unknown", "none_known", "listed"]


def _clean_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [x for x in v.replace(";", "\n").splitlines()]
    return [str(x).strip() for x in v if str(x).strip()]


class Vitals(BaseModel):
    bp_systolic: int | None = Field(None, ge=40, le=300)
    bp_diastolic: int | None = Field(None, ge=20, le=200)
    heart_rate: int | None = Field(None, ge=20, le=300)
    resp_rate: int | None = Field(None, ge=4, le=80)
    temp_c: float | None = Field(None, ge=30, le=45)
    spo2: int | None = Field(None, ge=50, le=100)
    weight_kg: float | None = Field(None, gt=0, le=400)
    height_cm: float | None = Field(None, gt=20, le=260)

    def lines(self) -> list[str]:
        out = []
        if self.bp_systolic and self.bp_diastolic:
            out.append(f"BP {self.bp_systolic}/{self.bp_diastolic} mmHg")
        if self.heart_rate:
            out.append(f"HR {self.heart_rate} bpm")
        if self.resp_rate:
            out.append(f"RR {self.resp_rate} /min")
        if self.temp_c:
            out.append(f"Temp {self.temp_c:g} °C")
        if self.spo2:
            out.append(f"SpO2 {self.spo2}%")
        if self.weight_kg:
            out.append(f"Weight {self.weight_kg:g} kg")
        if self.height_cm:
            out.append(f"Height {self.height_cm:g} cm")
        return out


class PatientProfile(BaseModel):
    display_name: str = ""  # optional; leave blank to use pseudonymous reference only
    age_value: float | None = Field(None, ge=0, le=130)
    age_unit: Literal["years", "months", "days"] = "years"
    sex: Sex = "unknown"
    pregnancy_status: Pregnancy = "unknown"
    allergies_status: ListStatus = "unknown"
    allergies: list[str] = []
    conditions_status: ListStatus = "unknown"
    conditions: list[str] = []
    current_medications: list[str] = []
    history_notes: str = ""

    chk_l = field_validator("allergies", "conditions", "current_medications", mode="before")(_clean_list)

    @property
    def age_years(self) -> float | None:
        if self.age_value is None:
            return None
        return {"years": self.age_value, "months": self.age_value / 12, "days": self.age_value / 365.25}[self.age_unit]

    def age_text(self) -> str:
        if self.age_value is None:
            return NOT_DOCUMENTED
        v = f"{self.age_value:g}"
        return f"{v} {self.age_unit if self.age_value != 1 else self.age_unit.rstrip('s')}"


class ClinicalInputs(BaseModel):
    """Items typed by the clinician. They take precedence over anything AI-extracted."""
    chief_complaint: str = ""
    exam_findings: str = ""
    working_diagnosis: str = ""
    treatment_plan: str = ""
    investigations: str = ""
    referrals: str = ""
    follow_up: str = ""


class EncounterData(BaseModel):
    patient_ref: str = ""  # pseudonymous reference (e.g. clinic-assigned code). Avoid names here.
    profile: PatientProfile = PatientProfile()
    vitals: Vitals = Vitals()
    inputs: ClinicalInputs = ClinicalInputs()
    consult_type: str = "General consultation"
    location: str = ""


class MedicationOrder(BaseModel):
    """A medication order *entered by a clinician*. The software never creates these."""
    id: str = ""
    drug_name: str = Field("", max_length=200)
    strength: str = ""  # e.g. "500 mg" or "125 mg/5 mL"
    dose_amount: float | None = Field(None, gt=0, le=100000)
    dose_unit: str = ""  # mg | g | mcg | mL | tablet | capsule | ...
    route: str = ""
    frequency: str = ""
    duration_days: int | None = Field(None, gt=0, le=3650)
    instructions: str = ""
    indication: str = ""

    def summary(self) -> str:
        dose = f"{self.dose_amount:g} {self.dose_unit}".strip() if self.dose_amount else ""
        parts = [self.drug_name, self.strength, dose, self.route, self.frequency]
        s = " ".join(p for p in parts if p).strip()
        if self.duration_days:
            s += f" x {self.duration_days} day(s)"
        return s or "(blank order)"


# --------------------------------------------------------------------------- SOAP note
class Subjective(BaseModel):
    chief_complaint: str = ""
    hpi: str = ""
    relevant_history: str = ""
    current_medications: list[str] = []
    allergies: list[str] = []
    allergies_status: ListStatus = "unknown"
    symptoms: list[str] = []

    chk_l = field_validator("current_medications", "allergies", "symptoms", mode="before")(_clean_list)


class Objective(BaseModel):
    vitals: list[str] = []
    exam_findings: list[str] = []
    other_findings: list[str] = []

    chk_l = field_validator("vitals", "exam_findings", "other_findings", mode="before")(_clean_list)


class Assessment(BaseModel):
    working_diagnosis: str = ""
    supporting_findings: list[str] = []
    uncertainties: list[str] = []
    missing_information: list[str] = []

    chk_l = field_validator("supporting_findings", "uncertainties", "missing_information", mode="before")(_clean_list)


class Plan(BaseModel):
    treatment_plan: str = ""
    medication_orders: list[str] = []  # rendered from entered orders only
    investigations: list[str] = []
    referrals: list[str] = []
    follow_up: str = ""

    chk_l = field_validator("medication_orders", "investigations", "referrals", mode="before")(_clean_list)


class SOAPNote(BaseModel):
    subjective: Subjective = Subjective()
    objective: Objective = Objective()
    assessment: Assessment = Assessment()
    plan: Plan = Plan()
    # field path -> clinician_input | structured | ai_extracted | transcript_text
    provenance: dict[str, str] = {}
    # AI output that failed grounding checks; shown for review, never part of the note
    flagged_items: list[str] = []
    generation_warnings: list[str] = []

    def to_text(self) -> str:
        def lst(xs):
            return "; ".join(xs) if xs else NOT_DOCUMENTED
        s, o, a, p = self.subjective, self.objective, self.assessment, self.plan
        return "\n".join(
            [
                "SUBJECTIVE", f"CC: {s.chief_complaint or NOT_DOCUMENTED}", f"HPI: {s.hpi or NOT_DOCUMENTED}",
                f"History: {s.relevant_history or NOT_DOCUMENTED}", f"Meds: {lst(s.current_medications)}",
                f"Allergies: {lst(s.allergies)}", f"Symptoms: {lst(s.symptoms)}",
                "OBJECTIVE", f"Vitals: {lst(o.vitals)}", f"Exam: {lst(o.exam_findings)}", f"Other: {lst(o.other_findings)}",
                "ASSESSMENT", f"Dx: {a.working_diagnosis or NOT_DOCUMENTED}", f"Support: {lst(a.supporting_findings)}",
                f"Uncertainties: {lst(a.uncertainties)}", f"Missing: {lst(a.missing_information)}",
                "PLAN", f"Tx: {p.treatment_plan or NOT_DOCUMENTED}", f"Orders: {lst(p.medication_orders)}",
                f"Investigations: {lst(p.investigations)}", f"Referrals: {lst(p.referrals)}", f"Follow-up: {p.follow_up or NOT_DOCUMENTED}",
            ]
        )
