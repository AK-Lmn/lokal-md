"""PDF export of a clinical note with ReportLab (fully local).

* Drafts are watermarked and headed "DRAFT - NOT APPROVED".
* Approval details are copied from the stored approval record exactly as entered; blank
  credentials/licence numbers are printed as "not recorded". Nothing is invented.
* The medication section states whether the reference data are a synthetic sample set.
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
INK = colors.HexColor("#14262e")
MUTED = colors.HexColor("#5a6b73")
LINE = colors.HexColor("#c9d6dc")
RED = colors.HexColor("#b3261e")
AMBER = colors.HexColor("#8a5a00")
GREEN = colors.HexColor("#1b6b3a")


def _t(s) -> str:
    """Make text safe for the built-in Helvetica font (WinAnsi) and for Paragraph markup."""
    s = str(s if s is not None else "")
    for a, b in (("≈", "~"), ("‹", "<"), ("›", ">"), ("≥", ">="), ("≤", "<="), ("→", "->"), ("•", "-")):
        s = s.replace(a, b)
    s = s.encode("cp1252", "replace").decode("cp1252")
    return escape(s)


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9.2, leading=12.6, textColor=INK)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.8, leading=10, textColor=MUTED),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=TEAL),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=TEAL, spaceBefore=9, spaceAfter=3),
        "label": ParagraphStyle("label", parent=base, fontName="Helvetica-Bold", fontSize=8.4, textColor=MUTED, spaceBefore=4),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=10, bulletIndent=1),
        "banner": ParagraphStyle("banner", parent=base, fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.white, alignment=1),
    }


def _banner(text: str, color) -> Table:
    t = Table([[Paragraph(_t(text), _styles()["banner"])]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
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
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f"Clinical note {encounter['id']}", author=APP_NAME, subject="Clinical consultation note")
    S: list = []

    facility = settings.get("facility_name") or ""
    S.append(Paragraph(_t(facility) if facility else "Clinical Consultation Note", st["small"]))
    S.append(Paragraph("Clinical Consultation Note (SOAP)", st["h1"]))
    S.append(Spacer(1, 3))
    if approved:
        S.append(_banner(f"APPROVED NOTE - version {note_rec['version']}", GREEN))
    else:
        S.append(_banner("DRAFT - NOT REVIEWED OR APPROVED BY A CLINICIAN. NOT A FINAL MEDICAL RECORD.", RED))
    S.append(Spacer(1, 6))

    def kv(rows):
        t = Table([[Paragraph(f"<b>{_t(k)}</b>", st["base"]), Paragraph(_t(v), st["base"])] for k, v in rows], colWidths=[34 * mm, 53 * mm])
        return t

    left = kv([("Encounter ID", encounter["id"]), ("Patient ref.", d.patient_ref), ("Age", d.profile.age_text()), ("Sex", d.profile.sex.capitalize())])
    right = kv([("Encounter date", local_display(encounter["created_at"])), ("Consult type", d.consult_type), ("Note status", note_rec["status"].capitalize()),
                ("Prepared by", author_name or "not recorded")])
    info = Table([[left, right]], colWidths=[87 * mm, 87 * mm])
    info.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    S.append(info)
    if d.profile.display_name:
        S.append(Paragraph(f"Patient name (as entered): {_t(d.profile.display_name)}", st["small"]))

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

    # ---- medication safety
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

    # ---- approval
    S.append(Paragraph("Approval", st["h2"]))
    if approved and note_rec.get("approver"):
        ap = note_rec["approver"]
        rows = [("Approved by", ap.get("name") or "not recorded"), ("Credentials", ap.get("credentials") or "not recorded"),
                ("Licence no.", ap.get("license_no") or "not recorded"), ("Approved at", local_display(note_rec["approved_at"])),
                ("Method", "Electronic approval within Tala (account sign-in). Not a handwritten or digital signature.")]
        t = Table([[Paragraph(f"<b>{_t(k)}</b>", st["base"]), Paragraph(_t(v), st["base"])] for k, v in rows], colWidths=[34 * mm, 140 * mm])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE)]))
        S.append(t)
        if ap.get("attestation"):
            S.append(Paragraph("Attestation recorded: " + _t(ap["attestation"]), st["small"]))
        if note_rec.get("content_hash"):
            S.append(Paragraph(f"Content hash (SHA-256): {note_rec['content_hash']}", st["small"]))
    else:
        S.append(Paragraph("<b>Not approved.</b> No clinician has reviewed or approved this note. It must not be treated as part of the final medical record.", st["base"]))

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
        canvas.drawString(18 * mm, 10 * mm, f"{APP_NAME} v{__version__} - {encounter['id']} - {note_rec['status'].upper()} v{note_rec['version']} - {exported}")
        canvas.drawRightString(w - 18 * mm, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(S, onFirstPage=decorate, onLaterPages=decorate)
    return buf.getvalue()
