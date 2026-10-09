"""Rendering of medication-safety review results."""
from __future__ import annotations

import streamlit as st

from ..auth import can
from ..safety.engine import CATEGORIES, CATEGORY_LABELS, OVERALL_LABELS
from ..timeutil import local_display
from . import common as C

CHECK_STATUS_TEXT = {
    "ran_no_match": ("Completed - no rules triggered", "neutral"), "ran_match": ("Completed - findings raised", "danger"),
    "partial": ("Partially completed", "info"), "cannot_run": ("Cannot be performed - information missing", "info"), "not_run": ("Not run", "neutral"),
}
SEV_KIND = {"contraindicated": "danger", "major": "danger", "moderate": "warn", "minor": "info", "info": "neutral"}


def overall_banner(res: dict, stale: bool) -> None:
    kind = {"concerns_detected": "danger", "review_required": "warn", "incomplete": "info", "no_rules_triggered": "info",
            "nothing_to_check": "info", "no_reference": "danger"}.get(res["overall"], "info")
    C.banner(OVERALL_LABELS.get(res["overall"], res["overall"]), kind)
    if stale:
        C.banner("This result is OUT OF DATE - medications or patient data changed since it was run. Re-run the check.", "danger", "⟳")


def dataset_line(res: dict) -> None:
    ds = res.get("dataset") or {}
    if not ds:
        return
    kind = "Reference set not clinically validated" if res.get("synthetic") else ("Professionally approved dataset" if res.get("approved_for_clinical") else "Imported, NOT yet approved")
    k = "warn" if res.get("synthetic") or not res.get("approved_for_clinical") else "ok"
    st.markdown(C.chip(kind, k) + C.chip(f"{ds.get('name')} v{ds.get('version')}", "neutral") + C.chip(f"{res.get('rule_count', 0)} rules", "neutral"), unsafe_allow_html=True)


def render(review: dict, *, store=None, stale: bool = False, allow_ack: bool = True) -> None:
    res = review["result"]
    overall_banner(res, stale)
    dataset_line(res)
    st.caption(f"Run {local_display(review['run_at'])}. {res['disclaimer']}")
    if res.get("checks"):
        with st.expander("What was checked", expanded=False):
            rows = []
            for c in res["checks"]:
                t, _ = CHECK_STATUS_TEXT.get(c["status"], (c["status"], "neutral"))
                rows.append({"Check": c["label"], "Result": t, "Detail": c["detail"]})
            st.dataframe(rows, hide_index=True, width="stretch")
    if res.get("meds"):
        with st.expander("How medication names were interpreted", expanded=False):
            st.dataframe([{"Entered": m["entered"], "From": "New order" if m["source"] == "order" else "Current medication",
                           "Identified as": ", ".join(m["ingredients"]) or "—", "Status": m["status"], "Suggestions (not applied)": ", ".join(m["suggestions"])}
                          for m in res["meds"]], hide_index=True, width="stretch")
    findings = res["findings"]
    if not findings:
        C.empty_state("No findings", "Nothing was raised. This is not a safety confirmation.")
    user = st.session_state.get("user")
    for cat in CATEGORIES:
        group = [f for f in findings if f["category"] == cat]
        if not group:
            continue
        st.markdown(f"**{CATEGORY_LABELS[cat]}** ({len(group)})")
        for f in group:
            ev = "".join(f'<div class="n">Source: {C.esc(e["rule"])} - {C.esc(e["source"])} <i>({C.esc(e["dataset"])})</i></div>' for e in f.get("evidence", []))
            st.markdown(
                f'<div class="rs-finding {C.esc(f["category"])}"><div class="t">{C.chip(f["severity"], SEV_KIND.get(f["severity"], "neutral"))} {C.esc(f["title"])}</div>'
                f'<div class="x">{C.esc(f["explanation"])}</div>{ev}'
                + (f'<div class="n"><b>Next step:</b> {C.esc(f["next_step"])}</div>' if f.get("next_step") else "") + "</div>",
                unsafe_allow_html=True,
            )
            if cat in ("detected_concern", "potential_concern"):
                ack = review["acks"].get(f["key"])
                if ack:
                    st.markdown(C.chip("Acknowledged", "ok") + f' <span class="rs-small">{C.esc(ack["reason"])} ({C.esc(local_display(ack["at"]))})</span>', unsafe_allow_html=True)
                elif allow_ack and store and can(user, "medreview.ack") and not stale:
                    c1, c2 = st.columns([4, 1])
                    reason = c1.text_input("Reason for proceeding (clinician acknowledgement)", key=f"ackr_{f['key']}", placeholder="e.g. benefit outweighs risk; monitoring arranged", label_visibility="collapsed")
                    if c2.button("Acknowledge", key=f"ackb_{f['key']}"):
                        try:
                            store.acknowledge_finding(review["id"], f["key"], reason)
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                elif not can(user, "medreview.ack"):
                    st.caption("Only a clinician can acknowledge safety findings.")
