"""PDF export of a clinical note and patient prescription with ReportLab (fully local).

* Designed for both clinical records and patient-understandable instructions (Tagalog / English).
* Drafts are watermarked and headed "DRAFT - NOT APPROVED".
* Approval details are copied from the stored approval record exactly as entered; blank
  credentials/licence numbers are printed as "not recorded". Nothing is invented.
* Includes clear patient medication guide (℞ Reseta), frequency in layman terms,
  and high-visibility safety/allergy warning callouts.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import APP_NAME, __version__
from .safety.engine import CATEGORY_LABELS, OVERALL_LABELS
from .schemas import NOT_DOCUMENTED, SOAPNote
from .timeutil import local_display, now_iso

TEAL = colors.HexColor("#0b6e75")
DARK_TEAL = colors.HexColor("#07494e")
LIGHT_TEAL = colors.HexColor("#f0f7f8")
CARD_BORDER = colors.HexColor("#b8d9dc")
INK = colors.HexColor("#14262e")
MUTED = colors.HexColor("#5a6b73")
LINE = colors.HexColor("#cbd7dc")
RED = colors.HexColor("#b3261e")
SOFT_RED = colors.HexColor("#fef2f2")
RED_BORDER = colors.HexColor("#f5c2c2")
AMBER = colors.HexColor("#8a5a00")
SOFT_AMBER = colors.HexColor("#fffbeb")
AMBER_BORDER = colors.HexColor("#f9e09d")
GREEN = colors.HexColor("#1b6b3a")
SOFT_GREEN = colors.HexColor("#f0fdf4")
GREEN_BORDER = colors.HexColor("#bbf7d0")

FREQ_MAP = {
    "TID": "3x a day (every 8 hrs / tuwing 8 oras)",
    "BID": "2x a day (every 12 hrs / tuwing 12 oras)",
    "QID": "4x a day (every 6 hrs / tuwing 6 oras)",
    "OD": "Once daily (isang beses sa isang araw)",
    "PRN": "As needed (kung kinakailangan)",
    "Q8H": "Every 8 hours (tuwing 8 oras)",
    "Q12H": "Every 12 hours (tuwing 12 oras)",
    "Q4H": "Every 4 hours (tuwing 4 oras)",
    "Q6H": "Every 6 hours (tuwing 6 oras)",
    "ONCE": "Single dose (isang beses lamang)",
    "STAT": "Immediately (ngayon na agad)",
}


def _t(s) -> str:
    """Make text safe for the built-in Helvetica font (WinAnsi) and for Paragraph markup."""
    s = str(s if s is not None else "")
    for a, b in (("≈", "~"), ("‹", "<"), ("›", ">"), ("≥", ">="), ("≤", "<="), ("→", "->"), ("•", "-"), ("·", "-"), ("℞", "Rx")):
        s = s.replace(a, b)
    s = s.encode("cp1252", "replace").decode("cp1252")
    return escape(s)


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=12.2, textColor=INK)
    return {
        "base": base,
        "base_bold": ParagraphStyle("base_bold", parent=base, fontName="Helvetica-Bold"),
        "small": ParagraphStyle("small", parent=base, fontSize=7.6, leading=9.8, textColor=MUTED),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=TEAL),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=13.5, textColor=DARK_TEAL, spaceBefore=8, spaceAfter=3),
        "rx_title": ParagraphStyle("rx_title", parent=base, fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=TEAL),
        "label": ParagraphStyle("label", parent=base, fontName="Helvetica-Bold", fontSize=8.2, textColor=MUTED, spaceBefore=3),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=10, bulletIndent=1),
        "banner": ParagraphStyle("banner", parent=base, fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=colors.white, alignment=1),
        "th": ParagraphStyle("th", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white),
        "td": ParagraphStyle("td", parent=base, fontSize=8, leading=10.5, textColor=INK),
        "td_bold": ParagraphStyle("td_bold", parent=base, fontName="Helvetica-Bold", fontSize=8.2, leading=10.5, textColor=DARK_TEAL),
        "alert": ParagraphStyle("alert", parent=base, fontSize=8.2, leading=11, textColor=INK),
    }


def _banner(text: str, color) -> Table:
    t = Table([[Paragraph(_t(text), _styles()["banner"])]], colWidths=[174 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def build_pdf(
    *, encounter: dict, note_rec: dict, orders: list, review: dict | None, review_current: bool, settings: dict,
    author_name: str = "", exported_by: str = "", demo_mode: bool = True,
) -> bytes:
    st = _styles()
    note: SOAPNote = note_rec["note"]
    approved = note_rec["status"] == "approved"
    d = encounter["data"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=f"Clinical note {encounter['id']}", author=APP_NAME, subject="Clinical consultation note & prescription",
    )
    S: list = []

    # 1. Facility Header & Document Title
    facility = settings.get("facility_name") or ""
    fac_text = f"<b>{_t(facility.upper())}</b> - " if facility else ""
    S.append(Paragraph(f"{fac_text}{APP_NAME} CLINICAL INTELLIGENCE - RURAL HEALTH OUTPOST", st["small"]))
    S.append(Paragraph("Patient Consultation &amp; Prescription Summary", st["h1"]))
    S.append(Paragraph("Buod ng Konsultasyon, Reseta at Gabay sa Paggaling - Clinical Consultation Note (SOAP)", st["small"]))
    S.append(Spacer(1, 2))

    if approved:
        S.append(_banner(f"APPROVED NOTE - version {note_rec['version']}", GREEN))
    else:
        S.append(_banner("DRAFT - NOT REVIEWED OR APPROVED BY A CLINICIAN. NOT A FINAL MEDICAL RECORD.", RED))
    S.append(Spacer(1, 4))

    # 2. Patient & Encounter Details Card
    def kv(rows):
        return Table([[Paragraph(f"<b>{_t(k)}</b>", st["base"]), Paragraph(_t(v), st["base"])] for k, v in rows], colWidths=[33 * mm, 52 * mm])

    left = kv([
        ("Encounter ID", encounter["id"]),
        ("Patient ref.", d.patient_ref),
        ("Age", d.profile.age_text()),
        ("Sex", d.profile.sex.capitalize()),
    ])
    right = kv([
        ("Encounter date", local_display(encounter["created_at"])),
        ("Consult type", d.consult_type),
        ("Note status", note_rec["status"].capitalize()),
        ("Prepared by", author_name or "not recorded"),
    ])
    info = Table([[left, right]], colWidths=[87 * mm, 87 * mm])
    info.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, CARD_BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_TEAL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    S.append(info)
    if d.profile.display_name:
        S.append(Paragraph(f"Patient name (as entered): {_t(d.profile.display_name)}", st["small"]))
    S.append(Spacer(1, 4))

    # 3. Patient Diagnosis & Health Highlights
    dx = note.assessment.working_diagnosis or d.inputs.working_diagnosis
    dx_text = dx if dx else NOT_DOCUMENTED
    dx_box = Table([[
        Paragraph("<b>Primary Working Diagnosis (Karamdaman):</b>", st["td_bold"]),
        Paragraph(f"<b>{_t(dx_text)}</b>", st["base"])
    ]], colWidths=[65 * mm, 109 * mm])
    dx_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, TEAL),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_TEAL),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    S.append(dx_box)
    S.append(Spacer(1, 3))

    # 4. Official ℞ Prescription & Patient Medication Schedule
    S.append(Paragraph("<b>℞ PRESCRIPTION & MEDICATION GUIDE</b> (Reseta at Gabay sa Pag-inom)", st["rx_title"]))
    if orders:
        rx_rows = [[
            Paragraph("Gamot / Medicine", st["th"]),
            Paragraph("Dose & Frequency (Gaano Kadalas)", st["th"]),
            Paragraph("Tagal (Duration)", st["th"]),
            Paragraph("Tagubilin (Instructions)", st["th"]),
        ]]
        for o in orders:
            freq_raw = o.frequency.upper().strip() if o.frequency else ""
            freq_desc = FREQ_MAP.get(freq_raw, o.frequency or "")
            amt = f"{o.dose_amount:g} {o.dose_unit}" if o.dose_amount else ""
            dose_freq = f"<b>{_t(amt)}</b><br/>{_t(freq_desc)}" if amt and freq_desc else _t(amt or freq_desc or "As instructed")
            dur = f"{o.duration_days} day(s) / araw" if o.duration_days else "As directed"
            instr = o.instructions or ("Take with water after meals" if "oral" in (o.route or "").lower() else "Follow physician guidance")

            drug_label = f"<b>{_t(o.drug_name)}</b>"
            if o.strength:
                drug_label += f"<br/><font color='#5a6b73'>{_t(o.strength)}</font>"

            rx_rows.append([
                Paragraph(drug_label, st["td_bold"]),
                Paragraph(dose_freq, st["td"]),
                Paragraph(_t(dur), st["td"]),
                Paragraph(_t(instr), st["td"]),
            ])

        rx_table = Table(rx_rows, colWidths=[48 * mm, 46 * mm, 26 * mm, 54 * mm])
        rx_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TEAL),
            ("BOX", (0, 0), (-1, -1), 0.8, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        S.append(rx_table)
    else:
        S.append(Paragraph("<i>No prescription medications ordered for this visit.</i>", st["base"]))
    S.append(Spacer(1, 4))

    # 5. Patient Safety & Allergy Alerts Callout
    alerts = []
    # Allergy alert
    s_alg = note.subjective.allergies or d.profile.allergies
    if s_alg:
        alg_str = ", ".join(s_alg)
        warn_note = ""
        if any("penicillin" in x.lower() for x in s_alg):
            warn_note = " <i>(Huwag uminom ng Amoxicillin, Augmentin, o kahit anong penicillin-based antibiotics).</i>"
        alerts.append(f"<b>⚠️ ALLERGY WARNING:</b> Patient is allergic to <b>{_t(alg_str)}</b>.{warn_note}")

    # Drug interaction / duplicate alert from review
    if review and review.get("result", {}).get("findings"):
        for f in review["result"]["findings"]:
            if f.get("category") == "detected_concern" and f.get("severity") in ("major", "contraindicated"):
                alerts.append(f"<b>🚨 SAFETY WARNING:</b> {_t(f['title'])}. {_t(f.get('explanation', ''))}")
            elif f.get("check_type") == "duplicates" and f.get("category") == "detected_concern":
                alerts.append(f"<b>⚠️ MEDICATION PRECAUTION:</b> {_t(f['title'])}. If you are taking over-the-counter medicine (such as Biogesic), stop it while taking this prescription to avoid overdose.")

    if alerts:
        alert_content = "<br/>".join(alerts)
        alert_box = Table([[Paragraph(alert_content, st["alert"])]], colWidths=[174 * mm])
        alert_box.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, AMBER_BORDER),
            ("BACKGROUND", (0, 0), (-1, -1), SOFT_AMBER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        S.append(alert_box)
        S.append(Spacer(1, 4))

    # 6. Patient Instructions: Care Plan & Follow-Up
    care_items = []
    tx = note.plan.treatment_plan or d.inputs.treatment_plan
    if tx:
        care_items.append(("Home Care Plan (Tagubilin sa Bahay)", tx))
    fu = note.plan.follow_up or d.inputs.follow_up
    if fu:
        care_items.append(("Follow-Up / Kailan Babalik", fu))

    if care_items:
        care_rows = []
        for title, desc in care_items:
            care_rows.append([Paragraph(f"<b>{_t(title)}:</b>", st["td_bold"]), Paragraph(_t(desc), st["base"])])
        care_table = Table(care_rows, colWidths=[52 * mm, 122 * mm])
        care_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, LINE),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfd")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        S.append(care_table)
        S.append(Spacer(1, 5))

    # 7. Clinician Approval Card (Official Doctor Sign-off)
    S.append(Paragraph("<b>Clinician Sign-Off &amp; Approval</b>", st["h2"]))
    if approved and note_rec.get("approver"):
        ap = note_rec["approver"]
        rows = [
            ("Approved by", ap.get("name") or "not recorded"),
            ("Credentials", ap.get("credentials") or "not recorded"),
            ("Licence no.", ap.get("license_no") or "not recorded"),
            ("Approved at", local_display(note_rec["approved_at"])),
            ("Method", "Electronic approval within Lokal.MD (account sign-in). Not a handwritten or digital signature."),
        ]
        t = Table([[Paragraph(f"<b>{_t(k)}</b>", st["base"]), Paragraph(_t(v), st["base"])] for k, v in rows], colWidths=[33 * mm, 141 * mm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, GREEN_BORDER),
            ("BACKGROUND", (0, 0), (-1, -1), SOFT_GREEN),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        S.append(t)
        if ap.get("attestation"):
            S.append(Paragraph("Attestation recorded: " + _t(ap["attestation"]), st["small"]))
        if note_rec.get("content_hash"):
            S.append(Paragraph(f"Content hash (SHA-256): {note_rec['content_hash']}", st["small"]))
    else:
        S.append(Paragraph("<b>Not approved.</b> No clinician has reviewed or approved this note. It must not be treated as part of the final medical record.", st["base"]))
    S.append(Spacer(1, 6))

    # 8. Detailed Clinical EHR Record (SOAP Format & Audit Trail)
    S.append(Paragraph("Clinical Consultation Note (SOAP)", st["h1"]))
    S.append(Paragraph("Complete EHR Clinical Record & Medical Reference", st["small"]))
    S.append(Spacer(1, 2))

    def para(label, text):
        return [Paragraph(_t(label), st["label"]), Paragraph(_t(text) if text else f"<i>{NOT_DOCUMENTED}</i>", st["base"])]

    def bullets(label, items):
        out = [Paragraph(_t(label), st["label"])]
        if not items:
            out.append(Paragraph(f"<i>{NOT_DOCUMENTED}</i>", st["base"]))
        for it in items:
            out.append(Paragraph(_t(it), st["bullet"], bulletText="-"))
        return out

    s, o, a, p = note.subjective, note.objective, note.assessment, note.plan
    S.append(Paragraph("S - Subjective", st["h2"]))
    S += para("Chief complaint", s.chief_complaint) + para("History of present illness", s.hpi) + para("Relevant history", s.relevant_history)
    S += bullets("Symptoms reported", s.symptoms) + bullets("Current medications", s.current_medications)
    alg = s.allergies if s.allergies else ([] if s.allergies_status == "unknown" else ["No known allergies (as recorded)"])
    S += bullets("Allergies" + (" - status not recorded" if s.allergies_status == "unknown" else ""), alg)

    S.append(Paragraph("O - Objective", st["h2"]))
    S += bullets("Vital signs", o.vitals) + bullets("Examination findings", o.exam_findings) + bullets("Other documented findings", o.other_findings)

    S.append(Paragraph("A - Assessment", st["h2"]))
    S += para("Working diagnosis (clinician-provided)", a.working_diagnosis) + bullets("Supporting findings", a.supporting_findings)
    S += bullets("Uncertainties", a.uncertainties) + bullets("Missing information", a.missing_information)

    S.append(Paragraph("P - Plan", st["h2"]))
    S += para("Treatment plan", p.treatment_plan) + bullets("Medication orders (entered by clinician)", p.medication_orders)
    S += bullets("Investigations", p.investigations) + bullets("Referrals", p.referrals) + para("Follow-up", p.follow_up)

    # 9. Medication Safety Engine Audit Review
    S.append(Paragraph("Medication safety review", st["h2"]))
    if not review:
        S.append(Paragraph("<b>No medication-safety check was run for this note.</b> Medication safety has not been reviewed by the software.", st["base"]))
    else:
        res = review["result"]
        ds = res.get("dataset", {})
        S.append(Paragraph(
            f"Run {_t(local_display(review['run_at']))} against reference dataset <b>{_t(ds.get('name', '?'))}</b> v{_t(ds.get('version', '?'))} "
            f"({'sample reference set - not clinically validated' if res.get('synthetic') else ('professionally approved' if res.get('approved_for_clinical') else 'imported, NOT yet approved')}).",
            st["small"]))
        if not review_current:
            S.append(Paragraph("<b>This check is OUT OF DATE: medications or patient data changed after it was run.</b>", st["base"]))
        S.append(Paragraph(f"Overall: <b>{_t(OVERALL_LABELS.get(res['overall'], res['overall']))}</b>", st["base"]))
        shown = [f for f in res["findings"] if f["category"] != "no_rules_triggered"]
        for f in shown:
            ack = review["acks"].get(f["key"])
            block = [
                Paragraph(f"<b>[{_t(CATEGORY_LABELS.get(f['category'], f['category']))} | {_t(f['severity'])}]</b> {_t(f['title'])}", st["base"]),
                Paragraph(_t(f["explanation"]), st["small"]),
                Paragraph(f"Next step: {_t(f['next_step'])}", st["small"]),
            ]
            if f.get("evidence"):
                block.append(Paragraph("Source: " + _t("; ".join(f"{e['rule']} - {e['source']}" for e in f["evidence"])), st["small"]))
            if ack:
                block.append(Paragraph(f"Acknowledged by clinician - reason: {_t(ack['reason'])}", st["small"]))
            S.append(KeepTogether(block + [Spacer(1, 3)]))
        if not shown:
            S.append(Paragraph("No findings were raised by the installed rules.", st["base"]))
        S.append(Paragraph(_t(res["disclaimer"]), st["small"]))

    if note.generation_warnings or note.flagged_items:
        S.append(Paragraph("Generation notes", st["h2"]))
        for w in note.generation_warnings:
            S.append(Paragraph(_t(w), st["bullet"], bulletText="-"))

    exported = f"Exported {local_display(now_iso())}" + (f" by {exported_by}" if exported_by else "")

    def decorate(canvas, doc_):
        canvas.saveState()
        w, h = A4
        if not approved:
            canvas.setFont("Helvetica-Bold", 64)
            canvas.setFillColor(colors.Color(0.7, 0.1, 0.1, alpha=0.07))
            canvas.translate(w / 2, h / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "DRAFT")
            canvas.restoreState()
            canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 8 * mm, f"{APP_NAME} v{__version__} - {encounter['id']} - {note_rec['status'].upper()} v{note_rec['version']} - {exported}")
        canvas.drawRightString(w - 18 * mm, 8 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(S, onFirstPage=decorate, onLaterPages=decorate)
    return buf.getvalue()
