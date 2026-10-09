"""The consultation workspace: intake, transcript, SOAP note, medication safety, approval."""
from __future__ import annotations

import time

import streamlit as st
from pydantic import ValidationError

from .. import llm, pdf_export, retention, services, soap, transcription, audit
from ..auth import can
from ..repo import Conflict, PermissionDenied
from ..safety import refdata
from ..safety.engine import OVERALL_LABELS
from ..schemas import NOT_DOCUMENTED
from ..timeutil import local_display
from . import common as C
from . import medview, wsstate as W

TABS = [
    ("intake", "1 · Patient Intake & Vitals"),
    ("transcript", "2 · Audio Transcription"),
    ("note", "3 · Clinical SOAP Note"),
    ("meds", "4 · Medication Orders"),
    ("approve", "5 · Review & Approval"),
]
TAB_LABEL = dict(TABS)
LIST_STATUS = {"unknown": "Not asked / unknown", "none_known": "None known", "listed": "Yes - list below"}
SEX = {"unknown": "Not recorded", "female": "Female", "male": "Male", "other": "Other"}
PREG = {"unknown": "Unknown", "no": "Not pregnant", "yes": "Pregnant", "not_applicable": "Not applicable"}
PROV_BADGE = {"clinician_input": ":green-badge[clinician]", "ai_extracted": ":orange-badge[AI-extracted · verify]", "mixed": ":orange-badge[clinician + AI]", "ai_unverified": ":red-badge[AI · unverified translation]",
              "structured": ":blue-badge[from intake]", "clinician_entered_orders": ":blue-badge[from orders]"}


def _err_text(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in x['loc'])}: {x['msg']}" for x in e.errors()[:5])


# =============================================================================== entry point
def render() -> None:
    enc_id = W.active_id()
    if not enc_id:
        C.empty_state("No encounter open", "Open one from Patient Encounters, or start a New Consultation.")
        return
    store = C.store()
    user = C.user()
    settings = C.settings()
    ix = services.get_reference_index(C.conn(), settings)
    locked = W.locked_for_edit()
    can_edit = can(user, "encounter.edit") and not locked

    _header(store, enc_id, locked)
    st.markdown(
        '<div class="rs-wshead"><div><h2>Clinical workspace</h2>'
        '<div class="d">One encounter. From patient intake to clinician approval.</div></div>'
        '<span class="rs-pill">On-device intelligence</span></div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("ws_tab_ctl") not in TAB_LABEL:
        st.session_state["ws_tab_ctl"] = "intake"
    tab = st.segmented_control("Workspace section", [k for k, _ in TABS], format_func=lambda k: TAB_LABEL[k].split(" · ", 1)[-1], key="ws_tab_ctl", required=True, label_visibility="collapsed", width="stretch") or "intake"
    if locked:
        C.banner("This encounter is approved/archived and read-only. Clinicians can start an amendment from 'Review & approve'.", "info", "")

    {"intake": _intake, "transcript": _transcript, "note": _note, "meds": _meds, "approve": _approve}[tab](store, can_edit, ix, settings)


# =============================================================================== header
def _header(store, enc_id: str, locked: bool) -> None:
    d = None
    try:
        d = W.collect_encounter()
    except ValidationError:
        pass
    dirty = W.dirty_sections()
    status = st.session_state.get("ws_status", "open")
    c1, c2 = st.columns([5, 1.4], vertical_alignment="center")
    with c1:
        age = d.profile.age_text() if d else "?"
        sex = SEX.get(d.profile.sex, "") if d else ""
        pref = st.session_state.get("ws_patient_ref", "")
        ctype = d.consult_type if d else "Outpatient consultation"
        st.markdown(
            f'<div class="rs-enchead"><div class="who"><div class="pav">{C.icon_html("user-round", 23)}</div><div>'
            f'<span class="ref">Patient Ref {C.esc(pref or enc_id)}</span>{C.status_chip(status)}'
            + (C.chip("Unsaved changes", "danger") if dirty else C.chip("All changes saved", "ok") if not locked else "")
            + f'<div class="meta">{C.esc(age)} · {C.esc(sex)} · {C.esc(ctype)} · Encounter <code>{C.esc(enc_id)}</code></div>'
            f'</div></div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        if st.button("Save changes", type="primary", disabled=locked or not dirty, width="stretch"):
            save(store)
            st.rerun()


def save(store, quiet: bool = False) -> bool:
    try:
        msgs = W.save_all(store)
    except ValidationError as e:
        C.flash("Cannot save - please correct: " + _err_text(e), "error")
        return False
    except (Conflict, PermissionDenied, ValueError) as e:
        C.flash(str(e), "error")
        return False
    if msgs and not quiet:
        C.flash("; ".join(msgs) + ".")
    return True


def autosave_on_lock() -> None:
    """Best-effort save of unsaved work when the session locks."""
    try:
        if W.active_id() and W.is_dirty() and not W.locked_for_edit():
            W.save_all(C.store())
    except Exception:
        pass


# =============================================================================== 1. intake
def _num(label, key, lo, hi, step, dis, fmt=None, help=None):
    return st.number_input(label, min_value=lo, max_value=hi, value=None, step=step, key=key, disabled=dis, format=fmt, help=help)


def _intake(store, can_edit, ix, settings):
    dis = not can_edit
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.markdown("##### Patient")
        st.text_input("Patient reference *", key="ws_patient_ref", disabled=dis, help="Use the clinic's pseudonymous code (e.g. PT-00123). Avoid names, addresses or ID numbers.")
        st.text_input("Patient name (optional)", key="ws_name", disabled=dis, help="Collect a name only if your clinic procedure requires it. Leave blank to keep the record pseudonymous.")
        a, b = st.columns([2, 1.4])
        with a:
            _num("Age", "ws_age_value", 0.0, 120.0, 1.0, dis, "%g")
        b.selectbox("Unit", ["years", "months", "days"], key="ws_age_unit", disabled=dis)
        s1, s2 = st.columns(2)
        s1.selectbox("Sex", list(SEX), format_func=SEX.get, key="ws_sex", disabled=dis)
        s2.selectbox("Pregnancy", list(PREG), format_func=PREG.get, key="ws_preg", disabled=dis or st.session_state.get("ws_sex") == "male")
        st.selectbox("Consultation type", ["General consultation", "Follow-up", "Maternal / child health", "Chronic disease review", "Disaster / outreach", "Other"], key="ws_consult_type", disabled=dis)
        st.markdown("##### Safety-relevant history")
        st.selectbox("Drug allergies", list(LIST_STATUS), format_func=LIST_STATUS.get, key="ws_alg_status", disabled=dis)
        if st.session_state.get("ws_alg_status") == "listed":
            st.text_area("Allergens (one per line)", key="ws_allergies", height=80, disabled=dis, placeholder="penicillin\nsulfa drugs")
        st.selectbox("Medical conditions", list(LIST_STATUS), format_func=LIST_STATUS.get, key="ws_cond_status", disabled=dis)
        if st.session_state.get("ws_cond_status") == "listed":
            st.text_area("Conditions (one per line)", key="ws_conditions", height=80, disabled=dis, placeholder="hypertension\nchronic kidney disease")
        st.text_area("Current medications (one per line)", key="ws_curmeds", height=90, disabled=dis, placeholder="losartan 50 mg once daily")
        st.text_area("Other relevant history", key="ws_history", height=70, disabled=dis)
    with right:
        st.markdown("##### Vital signs")
        v1, v2, v3 = st.columns(3)
        with v1:
            _num("BP systolic (mmHg)", "ws_bps", 40, 300, 1, dis)
            _num("Heart rate (/min)", "ws_hr", 20, 300, 1, dis)
            _num("Weight (kg)", "ws_wt", 0.5, 400.0, 0.5, dis, "%g")
        with v2:
            _num("BP diastolic (mmHg)", "ws_bpd", 20, 200, 1, dis)
            _num("Resp. rate (/min)", "ws_rr", 4, 80, 1, dis)
            _num("Height (cm)", "ws_ht", 20.0, 260.0, 1.0, dis, "%g")
        with v3:
            _num("Temp (°C)", "ws_temp", 30.0, 45.0, 0.1, dis, "%.1f")
            _num("SpO2 (%)", "ws_spo2", 50, 100, 1, dis)
        st.markdown("##### Clinician entries")
        st.caption("What you type here is authoritative: it is used verbatim in the note and always overrides anything the AI extracts.")
        st.text_input("Chief complaint", key="ws_cc", disabled=dis)
        st.text_area("Examination findings (one per line)", key="ws_exam", height=90, disabled=dis, placeholder="Only findings you actually observed or measured")
        st.text_input("Working diagnosis", key="ws_dx", disabled=dis)
        st.text_area("Treatment plan", key="ws_plan", height=80, disabled=dis, help="Describe the plan in words. Medicines are entered as orders in 'Medication safety' so they can be checked.")
        r1, r2 = st.columns(2)
        r1.text_area("Investigations (one per line)", key="ws_inv", height=70, disabled=dis)
        r2.text_area("Referrals (one per line)", key="ws_ref", height=70, disabled=dis)
        st.text_input("Follow-up", key="ws_fu", disabled=dis)


# =============================================================================== 2. transcript
def _asr_status_chips(settings):
    asr = transcription.status(settings["whisper_model"])
    st.markdown(C.chip("Speech recognition: ready" if asr["ready"] else "Speech recognition: unavailable", "ok" if asr["ready"] else "warn")
                + C.chip(f"model {settings['whisper_model']} · {settings['whisper_language']}", "neutral"), unsafe_allow_html=True)
    if not asr["ready"]:
        st.caption(f"{asr['message']}. You can still type or paste the transcript manually.")
    return asr


def _transcript(store, can_edit, ix, settings):
    ss = st.session_state
    enc_id = W.active_id()
    meta = ss.get("ws_tr_meta", {})
    dis = not can_edit or not can(C.user(), "transcript.edit")
    asr = _asr_status_chips(settings)

    if not dis:
        st.markdown("##### Capture or import audio")
        n = ss.setdefault("ws_aud_n", 0)
        src_pick = st.radio("Audio source", ["record", "upload"], format_func={"record": "Record with microphone", "upload": "Upload a file"}.get,
                            horizontal=True, key="ws_aud_src", label_visibility="collapsed")
        audio = None
        if src_pick == "record":
            rec = st.audio_input("Record the consultation (microphone)", key=f"aud_rec_{n}", disabled=not asr["ready"])
            st.caption("Recording runs in your browser; nothing is sent anywhere. If the recording is interrupted, nothing is kept - record again or type the transcript.")
            if rec is not None and st.button("Transcribe recording", type="primary", key="go_rec", disabled=not asr["ready"]):
                audio = (rec.getvalue(), ".wav", "audio/wav")
        else:
            up = st.file_uploader("Upload an audio recording (WAV, MP3, M4A, OGG, FLAC)", type=["wav", "mp3", "m4a", "ogg", "flac"], key=f"aud_up_{n}", disabled=not asr["ready"])
            if up is not None and st.button("Transcribe file", type="primary", key="go_up", disabled=not asr["ready"]):
                suffix = "." + up.name.rsplit(".", 1)[-1] if "." in up.name else ".wav"
                audio = (up.getvalue(), suffix, up.type or "audio/wav")
        if audio:
            _run_asr(store, enc_id, audio, settings)
        if ss.get("ws_asr_pending"):
            _asr_pending_panel()

    st.markdown("##### Transcript")
    status_chip = {"none": ("No transcript yet", "neutral"), "unreviewed": ("Not yet reviewed", "warn"), "reviewed": ("Reviewed", "ok")}[meta.get("status", "none")]
    n_unc = transcription.count_uncertain(ss.get("ws_transcript", ""))
    st.markdown(C.chip(*status_chip) + C.chip(f"source: {meta.get('source', 'manual')}", "neutral")
                + (C.chip(f"language: {meta['language']}", "neutral") if meta.get("language") else "")
                + (C.chip(f"{n_unc} low-confidence line(s)", "danger") if n_unc else ""), unsafe_allow_html=True)
    st.text_area("Edit the transcript - correct drug names, doses and numbers especially", key="ws_transcript", height=340, disabled=dis,
                 placeholder="Type or paste the consultation here if audio is unavailable. One statement per line works well.")
    st.caption("Lines starting with [?] were recognised with low confidence. Check each against the audio or the patient, fix the text, and remove the [?]. "
               "Recognition of Tagalog/Taglish and medical terms is imperfect - always review.")
    hints = soap.transcript_drug_hints(ss.get("ws_transcript", ""), ix)
    if hints:
        C.banner("Possible mis-heard drug names (check against the recording): " + "; ".join(f"'{h}' (possibly {d})" for h, d in hints), "warn", "")
    if dis:
        return
    c1, c2, c3 = st.columns([1.4, 1.6, 2])
    txt = ss.get("ws_transcript", "")
    if c1.button("Mark as reviewed", type="primary", disabled=not txt.strip() or n_unc > 0, help="Disabled while [?] lines remain"):
        try:
            store.save_transcript(W.active_id(), txt, source=meta.get("source", "manual"), language=meta.get("language"), asr_model=meta.get("model"), reviewed=True)
            ss["ws_tr_meta"] = {**meta, "status": "reviewed"}
            ss["ws_saved"] = {**ss["ws_saved"], "transcript": W.snap("transcript")}
            C.flash("Transcript marked as reviewed.")
            st.rerun()
        except Exception as e:
            st.error(str(e))
    if n_unc:
        ok = c2.checkbox("I checked every [?] line", key="ws_confirm_unc")
        if c3.button("Clear [?] markers", disabled=not ok):
            ss["ws_transcript"] = transcription.clear_uncertain_markers(txt)
            ss["ws_confirm_unc"] = False
            st.rerun()
    if c3.button("Clear transcript", type="tertiary") if not n_unc else False:
        ss["ws_transcript"] = ""
        ss["ws_tr_meta"] = {"source": "manual", "status": "none", "language": None, "model": None}
        st.rerun()


def _run_asr(store, enc_id, audio, settings):
    data, suffix, mime = audio
    bar = st.progress(0.0, text="Transcribing locally ...")
    t0 = time.time()
    try:
        res = transcription.transcribe_bytes(data, suffix, settings, progress=lambda f: bar.progress(f, text=f"Transcribing locally ... {int(f * 100)}%"))
    except transcription.TranscriptionUnavailable as e:
        bar.empty()
        st.error(f"Transcription failed: {e} Your audio is still loaded above - you can retry, or type the transcript manually.")
        return
    except Exception as e:  # unexpected decoder/runtime failure
        bar.empty()
        st.error(f"Transcription failed ({type(e).__name__}). You can retry or type the transcript manually.")
        return
    bar.empty()
    retained = retention.maybe_retain_audio(store, enc_id, data, mime, settings)
    ss = st.session_state
    ss["ws_asr_pending"] = {"text": res.text, "language": res.language, "model": res.model, "n_unc": res.n_uncertain, "duration": res.duration_s, "secs": time.time() - t0, "retained": retained}
    ss["ws_aud_n"] = ss.get("ws_aud_n", 0) + 1  # drops the audio widgets (and their in-memory audio)
    if not ss.get("ws_transcript", "").strip():
        _apply_pending()
    st.rerun()


def _apply_pending():
    ss = st.session_state
    p = ss.pop("ws_asr_pending")
    ss["ws_transcript"] = p["text"]
    ss["ws_tr_meta"] = {"source": "audio", "status": "unreviewed", "language": p["language"], "model": p["model"]}
    C.flash(f"Transcript created ({p['duration']:.0f}s audio, {p['secs']:.0f}s). Review it before generating a note."
            + (f" {p['n_unc']} low-confidence line(s) are marked [?]." if p["n_unc"] else "")
            + (" Audio retained per clinic policy." if p["retained"] else " The audio was not kept."))


def _asr_pending_panel():
    p = st.session_state["ws_asr_pending"]
    with st.container(border=True):
        st.markdown(f"**New transcription ready** ({p['duration']:.0f}s audio · {p['language']} · {p['n_unc']} uncertain line(s))")
        st.text_area("Preview", p["text"], height=140, disabled=True, key="ws_pending_preview")
        a, b = st.columns(2)
        if a.button("Replace current transcript with this", type="primary"):
            _apply_pending()
            st.rerun()
        if b.button("Discard"):
            st.session_state.pop("ws_asr_pending")
            st.rerun()


# =============================================================================== 3. SOAP note
def _note(store, can_edit, ix, settings):
    ss = st.session_state
    enc_id = W.active_id()
    meta = ss.get("ws_note_meta", {})
    dis = not can_edit or not can(C.user(), "note.edit")
    tr = ss.get("ws_tr_meta", {})
    lm = llm.status(settings["ollama_model"])
    st.markdown(
        C.chip("DRAFT - not approved" if meta.get("status") != "approved" else "Approved", "warn" if meta.get("status") != "approved" else "ok")
        + C.chip("Local AI ready: " + settings["ollama_model"] if lm["ready"] else "Local AI unavailable", "ok" if lm["ready"] else "warn")
        + (C.chip(f"generated by {meta['method']}", "neutral") if meta.get("method") else ""), unsafe_allow_html=True)
    if not lm["ready"]:
        st.caption(f"{lm['message']}. You can still build a draft from your entries, or write the note manually.")

    if not dis:
        with st.container(border=True):
            st.markdown("**Generate draft**")
            has_text = bool(ss.get("ws_transcript", "").strip())
            tr_ok = (not has_text) or tr.get("status") == "reviewed"
            n_unc = transcription.count_uncertain(ss.get("ws_transcript", ""))
            if has_text and not tr_ok:
                C.banner("Review the transcript first (Transcript tab, Mark as reviewed). Notes are generated from the reviewed transcript only.", "warn")
            existing = any(ss.get(k) for k in W.NOTE_FIELDS)
            replace_ok = True
            if existing:
                rv = ss.setdefault("ws_rep_v", 0)
                replace_ok = st.checkbox("Replace the current draft text (your edits will be lost)", key=f"ws_replace_ok_{rv}")
            g1, g2 = st.columns(2)
            with g1:
                go_ai = st.button("Generate with local AI", type="primary", disabled=not (lm["ready"] and has_text and tr_ok and replace_ok and n_unc == 0), width="stretch")
            with g2:
                go_tpl = st.button("Build from entries (no AI)", disabled=not replace_ok, width="stretch")
            if go_ai or go_tpl:
                _generate(store, enc_id, settings, use_llm=go_ai)

    if meta.get("warnings"):
        for w in meta["warnings"]:
            C.banner(w, "warn")
    if meta.get("flagged"):
        with st.expander(f"Withheld AI output ({len(meta['flagged'])}) - not part of the note", expanded=False):
            st.caption("The model produced these items but they were not supported by the transcript or your entries, so they were NOT added to the note.")
            for f in meta["flagged"]:
                st.markdown(f"- {f}")

    prov = meta.get("provenance", {})
    badge = lambda k: " " + PROV_BADGE.get(prov.get(k, ""), "")  # noqa: E731
    live = W.collect_note()
    st.markdown("#### S - Subjective")
    st.text_input("Chief complaint" + badge("chief_complaint"), key="ws_n_cc", disabled=dis)
    st.text_area("History of present illness" + badge("hpi"), key="ws_n_hpi", height=110, disabled=dis)
    c1, c2 = st.columns(2)
    c1.text_area("Relevant history" + badge("relevant_history"), key="ws_n_hist", height=80, disabled=dis)
    c2.text_area("Symptoms reported (one per line)" + badge("symptoms"), key="ws_n_symptoms", height=80, disabled=dis)
    _readonly_list("Current medications", live.subjective.current_medications, "from Intake")
    alg = live.subjective.allergies or ([] if live.subjective.allergies_status == "unknown" else ["No known allergies (as recorded)"])
    _readonly_list("Allergies" + (" - status NOT recorded" if live.subjective.allergies_status == "unknown" else ""), alg, "from Intake")
    st.markdown("#### O - Objective")
    _readonly_list("Vital signs", live.objective.vitals, "from Intake")
    c1, c2 = st.columns(2)
    c1.text_area("Examination findings (one per line)" + badge("exam_findings"), key="ws_n_exam", height=90, disabled=dis)
    c2.text_area("Other documented findings" + badge("other_findings"), key="ws_n_other", height=90, disabled=dis)
    st.markdown("#### A - Assessment")
    st.text_input("Working diagnosis (clinician-provided)" + badge("working_diagnosis"), key="ws_n_dx", disabled=dis)
    c1, c2 = st.columns(2)
    c1.text_area("Supporting findings" + badge("supporting_findings"), key="ws_n_support", height=80, disabled=dis)
    c2.text_area("Uncertainties", key="ws_n_uncert", height=80, disabled=dis)
    if live.assessment.missing_information:
        st.markdown("**Missing information** (calculated by the app - not guessed)")
        st.markdown("\n".join(f"- {m}" for m in live.assessment.missing_information))
    st.markdown("#### P - Plan")
    st.text_area("Treatment plan" + badge("treatment_plan"), key="ws_n_tx", height=80, disabled=dis)
    _readonly_list("Medication orders (entered in 'Medication safety')", live.plan.medication_orders, "from orders")
    c1, c2 = st.columns(2)
    c1.text_area("Investigations" + badge("investigations"), key="ws_n_inv", height=70, disabled=dis)
    c2.text_area("Referrals" + badge("referrals"), key="ws_n_ref", height=70, disabled=dis)
    st.text_input("Follow-up" + badge("follow_up"), key="ws_n_fu", disabled=dis)
    mentions = soap.unchecked_drug_mentions([ss.get("ws_n_tx", ""), ss.get("ws_transcript", "")], W.collect_orders(), W.lines(ss.get("ws_curmeds", "")), services.get_reference_index(C.conn(), settings))
    if mentions:
        C.banner("Mentioned in the plan/transcript but NOT entered as a medication order (so not safety-checked): " + ", ".join(mentions), "warn", "")


def _readonly_list(label, items, src):
    st.markdown(f"**{label}** :blue-badge[{src}]")
    st.markdown("\n".join(f"- {x}" for x in items) if items else f"_{NOT_DOCUMENTED}_")


def _generate(store, enc_id, settings, use_llm: bool):
    ss = st.session_state
    if not save(store, quiet=True):
        return
    try:
        data = W.collect_encounter()
    except ValidationError as e:
        st.error(_err_text(e))
        return
    src = soap.NoteSource(data, ss.get("ws_transcript", ""), W.collect_orders())
    with st.spinner("Generating note locally - this can take a minute on a laptop ..." if use_llm else "Building draft ..."):
        gen = soap.generate_note(src, use_llm=use_llm, model=settings["ollama_model"], timeout=settings["ollama_timeout_s"], ix=services.get_reference_index(C.conn(), settings))
    n = gen.note
    for key, (sec, attr, is_list) in W.NOTE_FIELDS.items():
        v = getattr(getattr(n, sec), attr)
        ss[key] = "\n".join(v) if is_list else v
    ss["ws_note_meta"] = {"exists": True, "status": "draft", "version": None, "method": gen.method, "model": gen.model, "provenance": n.provenance,
                          "flagged": n.flagged_items, "warnings": n.generation_warnings}
    store.save_draft(enc_id, n, method=gen.method, model=gen.model)
    ss["ws_status"] = "note_draft"
    ss["ws_saved"] = {**ss["ws_saved"], "note": W.snap("note")}
    ss["ws_rep_v"] = ss.get("ws_rep_v", 0) + 1
    C.flash("Draft note generated. It is a DRAFT - review and edit every section." if gen.method == "llm" else "Draft built from your entries without AI. Complete the narrative sections.", "success" if gen.method == "llm" else "warning")
    st.rerun()


# =============================================================================== 4. medication safety
def _meds(store, can_edit, ix, settings):
    ss = st.session_state
    enc_id = W.active_id()
    dis = not can_edit
    if ix is None:
        C.banner("No usable medication reference dataset is active - checks cannot run. See Settings, Medication reference.", "danger")
    else:
        medview.dataset_line({"dataset": ix.dataset, "synthetic": ix.is_synthetic, "approved_for_clinical": ix.is_approved_for_clinical, "rule_count": ix.rule_count})

    st.markdown("##### Medication orders")
    st.caption("Enter the medicines the clinician has decided to prescribe. The software never prescribes or approves anything - it only checks what you enter.")
    ids = ss.get("ws_ord_ids", [])
    if not ids:
        C.empty_state("No medication orders", "Add an order if a medicine is being prescribed.")
    for i, uid in enumerate(list(ids)):
        k = lambda f: f"ws_ord_{uid}_{f}"  # noqa: E731
        with st.container(border=True):
            a, b, c, d = st.columns([2.2, 1.4, 1, 1])
            a.text_input(f"Medicine #{i + 1} (generic or brand)", key=k("drug"), disabled=dis, placeholder="e.g. amoxicillin")
            b.text_input("Strength", key=k("strength"), disabled=dis, placeholder="500 mg  or  125 mg/5 mL")
            c.number_input("Dose", min_value=0.0, max_value=100000.0, value=None, step=0.5, key=k("amount"), disabled=dis, format="%g")
            d.selectbox("Unit", ["mg", "g", "mcg", "mL", "tablet", "capsule", "sachet", "drop", "puff", "IU", "other"], key=k("unit"), disabled=dis)
            e, f, g, h = st.columns([1, 1.6, 1, 0.8])
            e.selectbox("Route", ["oral", "IV", "IM", "SC", "topical", "inhaled", "rectal", "ophthalmic", "other", ""], key=k("route"), disabled=dis)
            f.text_input("Frequency", key=k("freq"), disabled=dis, placeholder="TID, q8h, twice daily ...")
            g.number_input("Days", min_value=1, max_value=3650, value=None, step=1, key=k("days"), disabled=dis)
            if not dis and h.button("Remove", key=f"rm_{uid}"):
                W.remove_order(uid)
                st.rerun()
            x, y = st.columns(2)
            x.text_input("Indication (optional)", key=k("indication"), disabled=dis)
            y.text_input("Instructions (optional)", key=k("instr"), disabled=dis)
    if not dis and st.button("Add medication order"):
        W.add_order()
        st.rerun()

    st.markdown("##### Safety check")
    d = None
    try:
        d = W.collect_encounter()
    except ValidationError as e:
        st.error("Fix the Intake data first: " + _err_text(e))
    if d:
        p = d.profile
        gaps = []
        if p.age_value is None:
            gaps.append("age")
        if p.allergies_status == "unknown":
            gaps.append("allergy status")
        if p.conditions_status == "unknown":
            gaps.append("medical conditions")
        if not d.vitals.weight_kg:
            gaps.append("weight (needed for per-kg dosing)")
        if p.sex == "female" and p.pregnancy_status == "unknown":
            gaps.append("pregnancy status")
        if gaps:
            C.banner("Missing patient information limits the check: " + ", ".join(gaps) + ". Complete it in Intake.", "warn", "")
    run = st.button("Save & run medication safety check", type="primary", disabled=not can(C.user(), "medreview.run") or ix is None or locked_view())
    if run:
        if not locked_view() and not save(store, quiet=True):
            return
        services.run_med_review(store, enc_id, ix)
        C.flash("Medication safety check completed.")
        st.rerun()
    review = store.latest_review(enc_id)
    if review:
        stale = not services.review_is_current(store, enc_id, review, ix) or W.is_dirty()
        medview.render(review, store=store, stale=stale)
    else:
        C.empty_state("No safety check yet", "Run the check after entering orders and completing the patient information.")


def locked_view() -> bool:
    return W.locked_for_edit()


# =============================================================================== 5. approve & export
def _approve(store, can_edit, ix, settings):
    ss = st.session_state
    enc_id = W.active_id()
    user = C.user()
    status = ss.get("ws_status")
    if status in ("approved", "archived"):
        rec = store.get_approved(enc_id)
        if rec:
            ap = rec["approver"] or {}
            C.banner(f"Approved - version {rec['version']} on {local_display(rec['approved_at'])}", "ok", "")
            st.markdown(f"**Approved by:** {C.esc(ap.get('name', ''))} · **Credentials:** {C.esc(ap.get('credentials') or 'not recorded')} · **Licence:** {C.esc(ap.get('license_no') or 'not recorded')}")
            st.caption("Electronic approval by an authenticated account. This is not a handwritten or digital signature.")
        if can(user, "note.approve") and status == "approved":
            if st.button("Start amendment (creates a new draft version)"):
                store.start_amendment(enc_id)
                W.load(store, enc_id, audit_view=False)
                ss["ws_tab_ctl"] = "note"
                C.flash("Amendment draft created. The approved version stays unchanged until you approve the new one.")
                st.rerun()
    else:
        dirty = W.dirty_sections()
        ready = services.approval_readiness(store, enc_id, ix, settings) if ss.get("ws_note_meta", {}).get("exists") else None
        st.markdown("##### Checklist before approval")
        if dirty:
            C.banner("You have unsaved changes. Save them before approving.", "danger")
            if st.button("Save now", type="primary"):
                save(store)
                st.rerun()
        if ready is None:
            C.banner("No draft note yet. Generate or write the SOAP note first.", "warn")
        else:
            rows = [("block", "Blocked", x) for x in ready.blockers] + [("note", "Check", w) for w in ready.warnings]
            if ready.ok and not dirty:
                rows.append(("pass", "Ready", "All required checks are satisfied. Approval is the clinician's decision."))
            C.check_rows(rows)
        if not can(user, "note.approve"):
            C.banner("Only a clinician account can approve notes. A draft stays a draft until then.", "info", "")
        else:
            att = st.checkbox("I have personally reviewed this note, the transcript and every medication-safety finding, and I take responsibility for its content.", key="ws_attest")
            if st.button("Approve note", type="primary", disabled=not (att and ready and ready.ok and not dirty)):
                try:
                    services.approve(store, enc_id, ix, settings, "Clinician attested review of note, transcript and medication-safety findings.")
                    W.load(store, enc_id, audit_view=False)
                    C.flash("Note approved.")
                    st.rerun()
                except (ValueError, Conflict, PermissionDenied) as e:
                    st.error(str(e))

    st.markdown("##### Export")
    _export(store, enc_id, ix, settings)


def _export(store, enc_id, ix, settings):
    ss = st.session_state
    if not can(C.user(), "export.pdf"):
        st.caption("Your role cannot export.")
        return
    rec = store.get_draft(enc_id) or store.get_approved(enc_id)
    if not rec:
        st.caption("Nothing to export yet - save a note draft first.")
        return
    if rec["status"] != "approved":
        st.caption("This will export a clearly marked DRAFT. Unsaved edits are not included - save first.")
    if st.button("Prepare PDF"):
        try:
            import importlib
            from .. import pdf_export
            importlib.reload(pdf_export)
            review = store.latest_review(enc_id)
            cur = bool(review) and services.review_is_current(store, enc_id, review, ix)
            creator = C.conn().execute("SELECT display_name FROM users WHERE id=?", (rec.get("approved_by") or store.get_encounter(enc_id)["created_by"],)).fetchone()
            pdf = pdf_export.build_pdf(encounter=store.get_encounter(enc_id), note_rec=rec, orders=store.get_orders(enc_id), review=review, review_current=cur,
                                       settings=settings, author_name=creator["display_name"] if creator else "", exported_by=C.user()["display_name"],
                                       demo_mode=False)
            ss["ws_pdf"] = (enc_id, rec["status"], rec["version"], pdf)
            audit.record(C.conn(), C.user(), "export.pdf", "encounter", enc_id, {"status": rec["status"], "version": rec["version"]})
            C.flash("Fresh PDF prepared. Click Download below.")
            st.rerun()
        except Exception as e:
            ss.pop("ws_pdf", None)
            st.error(f"PDF export failed ({type(e).__name__}). Nothing was saved or sent anywhere.")
    pdf = ss.get("ws_pdf")
    if pdf and pdf[0] == enc_id:
        with st.container(border=True):
            st.markdown(f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
                        f'<span style="font-size:20px;">📄</span>'
                        f'<div><b>Clinical PDF Document Ready</b> &nbsp; {C.chip(f"{pdf[1].upper()} v{pdf[2]}", "ok" if pdf[1] == "approved" else "warn")}'
                        f'<div style="font-size:12px;color:var(--muted)">Size: {len(pdf[3]) / 1024:.1f} KB &bull; Compliant with DOH AO 2020-0047 standard</div>'
                        f'</div></div>', unsafe_allow_html=True)
            st.download_button(f"Download PDF ({pdf[1]}, v{pdf[2]})", pdf[3], file_name=f"{enc_id}_{pdf[1]}_v{pdf[2]}.pdf", mime="application/pdf", type="primary")
            st.caption("The PDF contains patient information. Store and share it according to your facility's privacy policy; this app keeps no copy.")
