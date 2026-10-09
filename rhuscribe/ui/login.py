"""First-run setup, sign-in, lock screen and recovery."""
from __future__ import annotations

import time

import streamlit as st

from .. import APP_NAME, auth, config
from . import common as C


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
    st.markdown(f'<div class="rs-offstrip">{C.icon_html("shield-check", 14)} 100% Offline Vault &bull; Zero Cloud Dependency</div>', unsafe_allow_html=True)
    if locked_user:
        C.banner("Session locked. Sign in again to continue; unsaved work was kept as a draft where possible.", "info", "")
    st.subheader("Welcome to your clinical vault")
    st.markdown('<div class="rs-sub" style="margin:0">Sign in securely on this workstation.</div>', unsafe_allow_html=True)
    with st.form("signin", border=False):
        un = st.text_input("Username", value=locked_user, placeholder="e.g. dr.reyes")
        pw = st.text_input("Password", type="password", placeholder="Enter your password")
        st.markdown(f'<div class="rs-keynote">{C.icon_html("lock", 13)} Your password unlocks the AES-256-GCM vault key on this device only</div>', unsafe_allow_html=True)
        go = st.form_submit_button("Unlock Clinical Vault", type="primary", width="stretch", icon=":material/lock_open:")
    if go:
        try:
            user, vault = auth.login(conn, un, pw)
        except auth.AuthError as e:
            st.error(str(e))
            st.caption("Forgot your password? Use the recovery link below.")
        else:
            st.session_state.update(user=user, vault=vault)
            st.session_state.pop("locked_username", None)
            C.touch()
            st.rerun()
    if st.button("Forgot password / Emergency account recovery", key="forgot_pw", type="tertiary"):
        st.session_state["_recovery_mode"] = True
        st.rerun()


def _recovery(conn):
    st.markdown(f'<div class="rs-rechead"><div class="ic">{C.icon_html("shield-check", 22)}</div><div><div class="t">Emergency Vault Recovery &amp; Reset</div>'
                '<div class="s">Securely restore your clinician access to this clinic&#39;s offline vault.</div></div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="rs-banner teal"><span>{C.icon_html("info", 16)}</span><span>Because {APP_NAME} runs 100% offline with zero cloud servers, passwords '
                'cannot be recovered via email. Use the recovery key that was shown when your account was created.</span></div>', unsafe_allow_html=True)
    with st.form("recovery", border=False):
        un = st.text_input("Username", placeholder="Enter your username")
        rk = st.text_area("Recovery key", placeholder="Enter your recovery key exactly as it was saved", height=96)
        st.caption("Verified on this device only. Find it in your clinic's secure recovery kit.")
        a, b = st.columns(2)
        pw = a.text_input("New password", type="password", placeholder="Create a strong password")
        pw2 = b.text_input("Confirm new password", type="password", placeholder="Re-enter your password")
        st.caption(f"Use at least {config.MIN_PASSWORD_LEN} characters with upper and lower case letters and a digit.")
        go = st.form_submit_button("Verify Key & Restore Access", type="primary", width="stretch", icon=":material/verified_user:")
    if go:
        if pw != pw2:
            st.error("Passwords do not match.")
        else:
            try:
                auth.reset_with_recovery_key(conn, un, rk.strip(), pw)
                st.session_state["_recovery_mode"] = False
                C.flash("Password reset. You can now sign in.")
                st.rerun()
            except auth.AuthError as e:
                st.error(str(e))
    if st.button("Back to Clinician Login", key="rec_back", type="tertiary"):
        st.session_state["_recovery_mode"] = False
        st.rerun()


def render():
    conn = C.conn()
    st.markdown("<style>.block-container{padding-top:7vh !important}</style>", unsafe_allow_html=True)
    C.show_flash()
    setup = st.session_state.get("_setup_recovery") or not auth.is_setup_done(conn)
    recovery = not setup and st.session_state.get("_recovery_mode")
    _, mid, _ = st.columns([1, 1.6, 1] if (setup or recovery) else [1, 1.2, 1])
    with mid:
        st.markdown(f'<div class="rs-login-brand"><div class="rs-logo" style="width:40px;height:40px">{C.logo_svg(40)}</div>{APP_NAME}</div>'
                    '<div class="rs-login-tag">Local intelligence for local clinics.</div>', unsafe_allow_html=True)
        with st.container(key="login_card"):
            if setup:
                _setup(conn)
            elif recovery:
                _recovery(conn)
            else:
                _signin(conn)
    st.markdown(f'<div class="rs-login-foot">{C.icon_html("monitor", 14)} Rural Health Unit workstation mode &bull; Records never leave this computer &bull; '
                'Not a certified medical device</div>', unsafe_allow_html=True)
