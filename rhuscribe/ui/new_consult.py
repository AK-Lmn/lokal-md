"""New consultation: create an encounter and start capturing."""
from __future__ import annotations

import secrets

import streamlit as st
from pydantic import ValidationError

from ..repo import PermissionDenied
from ..schemas import ClinicalInputs, EncounterData, PatientProfile
from . import common as C
from .encounters import open_encounter

_ALPHA = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def render() -> None:
    st.title("New Consultation")
    C.show_flash()
    st.write("Create the encounter now and add details as the consultation proceeds. You need only a pseudonymous patient reference to begin.")
    if "nc_ref" not in st.session_state:
        st.session_state["nc_ref"] = "PT-" + "".join(secrets.choice(_ALPHA) for _ in range(6))
    c1, c2 = st.columns([1, 1], gap="large")
    with c1:
        st.text_input("Patient reference *", key="nc_ref", help="A clinic-assigned code. Avoid names or ID numbers. A random one is suggested.")
        a, b = st.columns([2, 1.3])
        age = a.number_input("Age", min_value=0.0, max_value=120.0, value=None, step=1.0, key="nc_age", format="%g")
        unit = b.selectbox("Unit", ["years", "months", "days"], key="nc_unit")
        sex = st.selectbox("Sex", ["unknown", "female", "male", "other"], format_func=lambda s: {"unknown": "Not recorded"}.get(s, s.capitalize()), key="nc_sex")
    with c2:
        ctype = st.selectbox("Consultation type", ["General consultation", "Follow-up", "Maternal / child health", "Chronic disease review", "Disaster / outreach", "Other"], key="nc_type")
        cc = st.text_input("Chief complaint (optional)", key="nc_cc")
        st.caption("Everything else - vitals, allergies, medicines, transcript - is added inside the workspace.")

    st.markdown("##### How will you document this consultation?")
    b1, b2, b3 = st.columns(3)
    start = None
    if b1.button("🎙 Record audio", type="primary", width="stretch"):
        start = "transcript"
    if b2.button("📁 Upload a recording", width="stretch"):
        start = "transcript"
    if b3.button("⌨ Type details manually", width="stretch"):
        start = "intake"
    if start:
        try:
            data = EncounterData(patient_ref=st.session_state["nc_ref"].strip(), consult_type=ctype,
                                 profile=PatientProfile(age_value=age, age_unit=unit, sex=sex), inputs=ClinicalInputs(chief_complaint=cc.strip()))
            eid = C.store().create_encounter(data)
        except ValidationError as e:
            st.error("Please correct the form: " + "; ".join(x["msg"] for x in e.errors()[:3]))
            return
        except (ValueError, PermissionDenied) as e:
            st.error(str(e))
            return
        st.session_state.pop("nc_ref", None)
        C.flash(f"Encounter {eid} created.")
        open_encounter(eid, tab=start)
