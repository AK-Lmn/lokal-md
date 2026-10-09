"""First-run setup, sign-in, lock screen and recovery."""
from __future__ import annotations

import time

import streamlit as st

from .. import APP_NAME, auth, config
from . import common as C


def _brand():
    st.markdown(
        f'<div style="text-align:center;margin:1.2rem 0 .8rem">'
        f'<div style="font-size:1.7rem;font-weight:750;color:#0b6e75">{APP_NAME}</div>'
        f'<div class="rs-small">Offline clinical consultation &amp; prescription-review assistant</div></div>',
        unsafe_allow_html=True,
    )


def render():
    conn = C.conn()
    st.markdown("<style>.block-container{padding-top:11vh !important}</style>", unsafe_allow_html=True)
    C.show_flash()
    _, mid, _ = st.columns([0.35, 6, 0.35])
    with mid:
        left, right = st.columns([1.05, 1], gap="large", vertical_alignment="center")
        with left:
            st.markdown(
                f'<div class="rs-hero"><div class="rs-logo" style="width:46px;height:46px">{C.logo_svg(46)}</div>'
                f'<h2>{APP_NAME}</h2><p><b>Tala</b> is Tagalog for <i>star</i>, a light to steer by when the power goes out, and the root of <i>talaan</i>, a record. '
                f'Consultation notes and prescription review for rural health units and disaster-response teams.</p>'
                f'<ul><li>{C.icon_html("shield-check", 16, "#bfe3e6")}&nbsp; Runs entirely on this computer. No patient data leaves it.</li>'
                f'<li>{C.icon_html("lock", 16, "#bfe3e6")}&nbsp; Records are encrypted; sessions lock when idle.</li>'
                f'<li>{C.icon_html("mic", 16, "#bfe3e6")}&nbsp; Speech and note drafting use local AI models, no internet needed.</li>'
                f'<li>{C.icon_html("file-text", 16, "#bfe3e6")}&nbsp; Every note stays a draft until a clinician approves it.</li></ul></div>',
                unsafe_allow_html=True)
        with right:
            if st.session_state.get("_setup_recovery") or not auth.is_setup_done(conn):
                _setup(conn)
            elif st.session_state.get("_recovery_mode"):
                _recovery(conn)
            else:
                _signin(conn)
            st.markdown('<div class="rs-small" style="margin-top:1rem">Not a certified medical device. Clinical decisions remain with the clinician.</div>', unsafe_allow_html=True)


def _setup(conn):
    if st.session_state.get("_setup_recovery"):
        st.subheader("Save your recovery key")
        C.banner("Shown once. Without your password OR this key, encrypted records cannot be recovered by anyone.", "warn", "")
        st.code(st.session_state["_setup_recovery"], language=None)
        st.download_button("Download recovery key (.txt)", f"{APP_NAME} recovery key\n{st.session_state['_setup_recovery']}\n\nStore offline, separate from this computer.\n",
                           file_name="rhu-scribe-recovery-key.txt")
        ok = st.checkbox("I have stored the recovery key somewhere safe and separate from this computer.")
        if st.button("Continue to the application", type="primary", disabled=not ok):
            st.session_state.pop("_setup_recovery")
            C.touch()
            st.rerun()
        return
    st.subheader("First-time setup")
    st.write("Create the administrator account. Your password protects the encryption key that locks all patient data on this computer.")
    with st.form("setup"):
        dn = st.text_input("Full name")
        cred = st.text_input("Professional credentials (optional)", placeholder="e.g. RN, RMT, MD - printed on approved notes only if you are a clinician")
        un = st.text_input("Username")
        pw = st.text_input("Password", type="password", help=f"At least {config.MIN_PASSWORD_LEN} characters with upper/lower case and a digit.")
        pw2 = st.text_input("Confirm password", type="password")
        go = st.form_submit_button("Create account", type="primary")
    if go:
        if pw != pw2:
            st.error("Passwords do not match.")
            return
        try:
            user, recovery, vault = auth.first_run_setup(conn, un, dn, pw, cred)
        except auth.AuthError as e:
            st.error(str(e))
            return
        st.session_state.update(user=user, vault=vault, _setup_recovery=recovery)
        st.rerun()


def _signin(conn):
    locked_user = st.session_state.get("locked_username", "")
    if locked_user:
        C.banner("Session locked. Sign in again to continue; unsaved work was kept as a draft where possible.", "info", "")
    h1, h2 = st.columns([1, 1.25], vertical_alignment="center")
    h1.subheader("Sign in")
    if h2.button("Forgot password?", key="forgot_pw", width="stretch"):
        st.session_state["_recovery_mode"] = True
        st.rerun()
    with st.form("signin"):
        un = st.text_input("Username", value=locked_user)
        pw = st.text_input("Password", type="password")
        go = st.form_submit_button("Sign in", type="primary")
    if go:
        try:
            user, vault = auth.login(conn, un, pw)
        except auth.AuthError as e:
            st.error(str(e))
            st.caption("Forgot your password? Use the button above the form.")
        else:
            st.session_state.update(user=user, vault=vault)
            st.session_state.pop("locked_username", None)
            C.touch()
            st.rerun()


def _recovery(conn):
    st.subheader("Reset password with recovery key")
    with st.form("recovery"):
        un = st.text_input("Username")
        rk = st.text_input("Recovery key")
        pw = st.text_input("New password", type="password")
        go = st.form_submit_button("Reset password", type="primary")
    if go:
        try:
            auth.reset_with_recovery_key(conn, un, rk, pw)
            st.session_state["_recovery_mode"] = False
            C.flash("Password reset. You can now sign in.")
            st.rerun()
        except auth.AuthError as e:
            st.error(str(e))
    if st.button("Back to sign in", type="tertiary"):
        st.session_state["_recovery_mode"] = False
        st.rerun()
