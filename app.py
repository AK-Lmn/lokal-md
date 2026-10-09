"""Lokal.MD - offline clinical consultation & prescription-review assistant.

Run:  streamlit run app.py        (binds to 127.0.0.1 only; see .streamlit/config.toml)
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

from rhuscribe import netguard  # noqa: E402

netguard.install()  # refuse any non-loopback outbound connection from this process

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Lokal.MD", page_icon=str(Path(__file__).parent / "static" / "favicon.png"), layout="wide", initial_sidebar_state="expanded")

from rhuscribe import APP_NAME  # noqa: E402
from rhuscribe.auth import can  # noqa: E402
from rhuscribe.ui import common as C  # noqa: E402
from rhuscribe.ui import dashboard, encounters, login, new_consult, session, settings_page, workspace  # noqa: E402
from rhuscribe.ui import wsstate as W  # noqa: E402

NAV = [("dashboard", "Dashboard"), ("encounters", "Patient Encounters"), ("new", "New Consultation")]
WS_NAV = [("intake", "Intake & vitals"), ("transcript", "Transcription workspace"), ("note", "Clinical notes (SOAP)"), ("meds", "Medication safety"), ("approve", "Review, approve & export")]
NAV2 = [("history", "Encounter History"), ("settings", "Settings")]


def request_nav(target: str) -> None:
    st.session_state["_nav_req"] = target


def apply_nav(req: str) -> None:
    ss = st.session_state
    if req.startswith("ws:"):
        ss["page"] = "workspace"
        ss["ws_tab_ctl"] = req[3:]
    else:
        ss["page"] = req


def process_nav() -> None:
    ss = st.session_state
    req = ss.pop("_nav_req", None)
    if not req:
        return
    target_is_ws = req.startswith("ws:")
    if ss.get("page") == "workspace" and not target_is_ws and W.is_dirty():
        ss["_nav_pending"] = req  # ask before leaving with unsaved changes
        return
    apply_nav(req)


def unsaved_guard() -> bool:
    ss = st.session_state
    req = ss.get("_nav_pending")
    if not req:
        return False
    secs = ", ".join(W.dirty_sections())
    st.warning(f"**Unsaved changes** in encounter {W.active_id()} ({secs}). What would you like to do?")
    a, b, c = st.columns(3)
    if a.button("Save and leave", type="primary"):
        if workspace.save(C.store()):
            apply_nav(ss.pop("_nav_pending"))
        st.rerun()
    if b.button("Discard and leave"):
        W.load(C.store(), W.active_id(), audit_view=False)  # reload saved state
        apply_nav(ss.pop("_nav_pending"))
        st.rerun()
    if c.button("Stay here"):
        ss.pop("_nav_pending")
        st.rerun()
    return True


def sidebar() -> None:
    ss = st.session_state
    user = C.user()
    page = ss.get("page", "dashboard")
    with st.sidebar:
        st.markdown(
            f'<div class="rs-brandrow">'
            f'<div class="rs-logo">{C.logo_svg(38)}</div>'
            f'<div class="rs-brand">{APP_NAME}<small>Local intelligence for local clinics.</small></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="rs-navlabel">WORKSPACE</div>', unsafe_allow_html=True)
        for key, label in NAV:
            st.button(label, key=f"nav_{key}", type="primary" if page == key else "secondary", on_click=request_nav, args=(key,))
        if W.active_id():
            st.markdown(f'<div class="rs-navlabel">OPEN: {C.esc(W.active_id())}</div>', unsafe_allow_html=True)
            for key, label in WS_NAV:
                active = page == "workspace" and ss.get("ws_tab_ctl", "intake") == key
                st.button(label, key=f"nav_ws_{key}", type="primary" if active else "secondary", on_click=request_nav, args=(f"ws:{key}",))
            if W.is_dirty():
                st.markdown(C.chip("Unsaved changes", "danger"), unsafe_allow_html=True)
        st.markdown('<div class="rs-navlabel">SETTINGS &amp; RECORDS</div>', unsafe_allow_html=True)
        for key, label in NAV2:
            st.button(label, key=f"nav_{key}", type="primary" if page == key else "secondary", on_click=request_nav, args=(key,))
        st.markdown(
            '<div class="rs-vault-card">'
            '<div class="rs-vault-badge"><span class="dot"></span> Offline vault active</div>'
            '<div class="rs-vault-desc">Records stay on this device. No internet connection required.</div>'
            '<div class="rs-vault-foot">🔒 Encrypted local storage</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div style="margin-top:auto; padding-top:1.5rem; border-top:1px solid var(--line2);"></div>', unsafe_allow_html=True)
        initials = "".join([part[0].upper() for part in (user["display_name"] or "DR").split()[:2]]) or "MD"
        role_label = "Rural health physician" if "clinician" in user.get("role", "").lower() else user.get("role", "")
        st.markdown(
            f'<div class="rs-usercard">'
            f'<div class="rs-avatar">{initials}</div>'
            f'<div><div class="rs-username">{C.esc(user["display_name"])}</div>'
            f'<div class="rs-userrole">{C.esc(role_label)}</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        if c1.button("Lock", key="btn_lock"):
            session.lock("manual")
            st.rerun()
        if c2.button("Sign out", key="btn_signout"):
            session.logout("Signed out.")
            st.rerun()


@st.fragment(run_every="20s")
def idle_watch() -> None:
    """Locks the session after inactivity even if the user is not touching the page."""
    if C.user() and session.idle_exceeded():
        session.lock("inactivity")
        st.rerun()


def main() -> None:
    C.inject_css()
    if not C.user() or st.session_state.get("_setup_recovery"):
        login.render()
        return
    if session.idle_exceeded():
        session.lock("inactivity")
        st.rerun()
    C.touch()
    W.keep_state()
    process_nav()
    sidebar()
    if unsaved_guard():
        idle_watch()
        return
    page = st.session_state.get("page", "dashboard")
    {
        "dashboard": dashboard.render, "encounters": encounters.render_list, "new": new_consult.render,
        "workspace": lambda: (C.show_flash(), workspace.render()), "history": encounters.render_history, "settings": settings_page.render,
    }.get(page, dashboard.render)()
    idle_watch()


main()
