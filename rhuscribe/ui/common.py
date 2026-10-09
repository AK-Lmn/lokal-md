"""Shared UI helpers: session access, design system (CSS), small HTML components."""
from __future__ import annotations

import base64
import html
import re
import time
from pathlib import Path

import streamlit as st

from .. import APP_NAME, bootstrap, db, settings_store
from ..repo import Store

# --------------------------------------------------------------------------- session access
IDLE_KEYS = ("last_active",)


def conn():
    c = st.session_state.get("_conn")
    if c is None:
        c = db.connect()
        bootstrap.init(c)
        st.session_state["_conn"] = c
    return c


def user() -> dict | None:
    return st.session_state.get("user")


def vault():
    return st.session_state.get("vault")


def store() -> Store:
    return Store(conn(), vault(), user())


def settings() -> dict:
    return settings_store.get_all(conn())


def touch() -> None:
    st.session_state["last_active"] = time.time()


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def flash(msg: str, kind: str = "success") -> None:
    st.session_state.setdefault("_flash", []).append((kind, msg))


def show_flash() -> None:
    for kind, msg in st.session_state.pop("_flash", []):
        {"success": st.success, "error": st.error, "warning": st.warning, "info": st.info}.get(kind, st.info)(msg)


# --------------------------------------------------------------------------- design system
CSS = """
<style>
/* Design tokens: Figma "Lokal.MD clinical workspace" (static/figma/tokens.json).
   Streamlit cannot reproduce the Figma frame pixel-for-pixel. Known gaps:
   - Layout: Streamlit's grid, column gutters and widget vertical rhythm are fixed; Figma auto-layout gaps are approximated.
   - Sidebar: the collapse header, resize handle and scroll container are Streamlit-owned; the account block cannot be pinned
     to the bottom of the sidebar.
   - Widgets: BaseWeb inputs/selects/number steppers keep their internal structure (stepper buttons, clear icons, dropdowns).
   - Step tabs are a styled st.segmented_control: no per-tab icons; numbers come from CSS counters.
   - Section cards: Streamlit has no wrapper per section, so Figma's white section cards (01-05) become headings with
     step markers, and only st.container(border=True) blocks get the card treatment.
   - Waveform, avatars and per-badge icons from the design are not drawn; badges use a colour dot instead of an icon.
   - Text rendering differs slightly from Figma (browser hinting, Inter variable font vs. static instances). */
:root{
  --ink:#14262e; --ink2:#34454d; --muted:#52656f; --line:#dce5e9; --line2:#e8eef1; --bg:#f8fafc; --card:#ffffff; --subtle:#f1f5f7;
  --accent:#0b6e75; --accent-dark:#07494e; --accent-soft:#edf8f6; --mint:#2dd4bf; --warm:#95520b; --warm-soft:#fff4e3;
  --blue:#2f6fb5; --green:#1b6b3a; --navy:#07494e;
  --ok:#0b6e75; --warn:#95520b; --danger:#a3241d; --info:#1f5a94;
  --r-sm:2px; --r:12px; --r-pill:100px;
  --s-1:4px; --s-2:6px; --s-3:8px; --s-4:10px; --s-5:12px; --s-6:16px; --s-7:20px; --s-8:24px; --s-9:32px;
}
html, body, .stApp, [class*="css"] { font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif; color: var(--ink); }
.stApp { background: var(--bg); }
.block-container { padding-top: 2.6rem; padding-bottom: 4rem; padding-left: var(--s-9); padding-right: var(--s-9); max-width: 1352px; }
h1, h2, h3, h4, h5 { color: var(--ink); letter-spacing: -0.01em; }
h1 { font-size: 27px !important; line-height: 33px !important; font-weight: 700 !important; margin-bottom: .25rem; }
h2 { font-size: 1.25rem !important; font-weight: 700 !important; }
h3 { font-size: 17px !important; font-weight: 600 !important; }
h4, h5 { font-size: 17px !important; font-weight: 500 !important; text-transform: none; }
p, li, label, span { color: inherit; }

/* ---------- sidebar (Figma "Clinic navigation": 248px, white, 20px gutters) ---------- */
section[data-testid="stSidebar"] { background: var(--card); border-right: 1px solid var(--line); width: 248px !important; min-width: 248px !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding: 0; }
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] { padding: var(--s-5) var(--s-7) 0; margin-bottom: 0; height: auto; min-height: 2.25rem; }
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: 0 var(--s-7) var(--s-8); }
section[data-testid="stSidebar"] .stButton > button::before { opacity: .9; }
section[data-testid="stSidebar"] .stButton > button[kind="primary"]::before { opacity: 1; }
.rs-brandrow { display:flex; align-items:center; gap: var(--s-4); padding: 0 0 var(--s-6); margin-bottom: var(--s-3); border-bottom: 1px solid var(--line); }
.rs-logo { width: 38px; height: 38px; flex:none; line-height:0; }
.rs-hero { background: linear-gradient(160deg,#0b6e75 0%,#042f2e 100%); color:#fff; border-radius: 16px; padding: 42px 38px; min-height: 440px; border-bottom: 5px solid var(--mint); }
.rs-hero h2 { border: 0 !important; padding: 0 !important; margin: 22px 0 12px !important; color:#fff !important; font-size: 1.7rem !important; margin: 18px 0 8px; }
.rs-hero p { color: #d7ecee; font-size: .95rem; line-height: 1.55; }
.rs-tagline { color:#fff; font-size: 1.35rem; font-weight: 650; line-height: 1.35; margin: 0 0 8px; }
.rs-tagsub { color:#a9d3d7; font-size: .82rem; letter-spacing: .02em; margin-bottom: 4px; }
.rs-hero li { color:#eaf6f7; margin: 10px 0; font-size:.93rem; list-style:none; }
.rs-hero ul { padding: 0; margin: 22px 0 0; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: var(--s-3); }
section[data-testid="stSidebar"] .stButton > button { width: 100%; justify-content: flex-start; text-align: left; border: 0; border-radius: var(--r);
  background: transparent; color: var(--ink); padding: 0 var(--s-5); font-weight: 500; font-size: 13px; min-height: 46px; box-shadow: none; }
section[data-testid="stSidebar"] .stButton > button::before { width: 18px !important; height: 18px !important; margin-right: var(--s-4) !important; }
section[data-testid="stSidebar"] :is(.st-key-btn_lock, .st-key-btn_signout) button { padding: 0 var(--s-2); }
section[data-testid="stSidebar"] :is(.st-key-btn_lock, .st-key-btn_signout) button::before { margin-right: var(--s-2) !important; }
section[data-testid="stSidebar"] .stButton > button:hover { background: var(--bg); color: var(--ink); }
section[data-testid="stSidebar"] .stButton > button[kind="primary"] { background: var(--accent-soft); color: var(--accent); font-weight: 500; box-shadow: none; }
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover { background: var(--accent-soft); color: var(--accent-dark); }
.rs-brand { font-weight: 400; font-size: 23px; color: var(--ink); padding: 0; line-height: 28px; letter-spacing: -0.01em; }
.rs-brand small { display:block; font-weight: 400; font-size: 12px; line-height: 19px; letter-spacing: 0; color: var(--muted); margin-top: var(--s-1); }
.rs-navlabel { text-transform: uppercase; font-size: 10px; letter-spacing: .06em; color: var(--muted); padding: var(--s-6) 0 var(--s-1); font-weight: 700; line-height: 12px; margin: 0; }

/* ---------- offline vault card ---------- */
.rs-vault-card { background: var(--bg); border: 1px solid var(--line); border-radius: var(--r); padding: 14px; margin: var(--s-7) 0 var(--s-3); }
.rs-vault-badge { display:inline-flex; align-items:center; gap: var(--s-2); background: var(--accent-soft); color: var(--accent); font-size: 12px; font-weight: 600; line-height: 15px; padding: var(--s-2) var(--s-4); border-radius: var(--r-pill); margin-bottom: var(--s-4); }
.rs-vault-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
.rs-vault-desc { font-size: 12px; color: var(--muted); line-height: 19px; margin-bottom: var(--s-4); }
.rs-vault-foot { font-size: 11px; color: var(--accent); font-weight: 500; display:flex; align-items:center; gap: var(--s-2); }

/* ---------- clinician account ---------- */
.rs-account { display:flex; align-items:center; gap: var(--s-4); padding-top: 14px; margin-top: var(--s-3); border-top: 1px solid var(--line); }
.rs-avatar { width: 34px; height: 34px; flex: none; border-radius: var(--r-pill); background: var(--subtle); color: var(--accent); font-size: 12px; font-weight: 700; display:flex; align-items:center; justify-content:center; }
.rs-account .n { font-size: 12px; line-height: 15px; color: var(--ink); }
.rs-account .r { font-size: 10px; line-height: 12px; color: var(--muted); margin-top: var(--s-1); text-transform: capitalize; }

/* ---------- section headings: Figma step marker + 17px title ---------- */
.block-container h4, .block-container h5 { display:flex; align-items:center; gap: var(--s-5); margin: var(--s-7) 0 var(--s-6); padding: 0; border: 0; line-height: 21px !important; }
.block-container h4::before, .block-container h5::before { content:""; flex:none; width: 30px; height: 30px; border-radius: var(--r);
  background: radial-gradient(circle, var(--accent) 0 3.5px, transparent 4px), var(--accent-soft); }
.block-container h1 { margin-bottom: var(--s-3); }

/* ---------- segmented controls / Figma five-step navigation ---------- */
[data-testid="stButtonGroup"] button[role="radio"] { background: var(--card); color: var(--muted); border: 1px solid var(--line); font-size: 12px; font-weight: 500; }
[data-testid="stButtonGroup"] button[role="radio"]:hover { background: var(--accent-soft); color: var(--accent); }
[data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"] { background: var(--accent-soft) !important; border-color: var(--accent) !important; }
[data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"], [data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"] * { color: var(--accent) !important; }
.st-key-ws_tab_ctl, .st-key-ws_tab_ctl [data-testid="stButtonGroup"] { width: 100%; counter-reset: step; }
.st-key-ws_tab_ctl [data-testid="stButtonGroup"] > div { display:flex; flex-wrap: nowrap; gap: var(--s-3); width: 100%; }
.st-key-ws_tab_ctl [data-testid="stButtonGroup"] button[role="radio"] { flex: 1 1 0; min-height: 54px; justify-content: flex-start; gap: var(--s-3); padding: 0 var(--s-4);
  border: 0 !important; border-bottom: 1px solid var(--line) !important; border-radius: 0 !important; background: var(--card) !important; }
.st-key-ws_tab_ctl [data-testid="stButtonGroup"] button[role="radio"] > * { flex: 1 1 auto; justify-content: flex-start; text-align: left; }
.st-key-ws_tab_ctl [data-testid="stButtonGroup"] button[role="radio"]::before { counter-increment: step; content: counter(step); flex: none; width: 23px; height: 23px;
  border-radius: var(--r-pill); background: var(--subtle); color: var(--muted); font-size: 11px; font-weight: 700; display:inline-flex; align-items:center; justify-content:center; }
.st-key-ws_tab_ctl [data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"] { background: var(--accent-soft) !important; border-bottom: 2px solid var(--accent) !important; font-weight: 500; }
.st-key-ws_tab_ctl [data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"]::before { background: var(--accent); color: #fff; }

/* ---------- inputs: white, 1px #dce5e9, 12px radius ---------- */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] * { color: var(--ink) !important; opacity: 1 !important; font-size: 12px; font-weight: 500; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div, [data-testid="stNumberInputContainer"] { background: #fff !important; border: 1px solid var(--line) !important; border-radius: var(--r) !important; }
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea, [data-baseweb="select"] * { color: var(--ink) !important; font-size: 13px !important; }
[data-baseweb="textarea"] textarea { line-height: 20.8px !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"] > div:focus-within { border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(11,110,117,.15) !important; }
[data-baseweb="base-input"], [data-baseweb="base-input"] input, textarea { background: #fff !important; }
[data-baseweb="base-input"]:has(input:disabled), textarea:disabled { background: var(--subtle) !important; }
::placeholder { color: #6b7d86 !important; opacity: 1 !important; }
input:disabled, textarea:disabled, [aria-disabled="true"], [data-disabled="true"] { opacity: 1 !important; -webkit-text-fill-color: #2c3c44 !important; color: #2c3c44 !important; cursor: not-allowed; }
[data-baseweb="input"]:has(input:disabled), [data-baseweb="textarea"]:has(textarea:disabled), [data-baseweb="select"] > div[aria-disabled="true"] { background: var(--subtle) !important; border-color: var(--line) !important; }
.stCheckbox label, .stRadio label { color: var(--ink) !important; }

/* ---------- spacing (Figma auto-layout: 16 / 20 px) ---------- */
[data-testid="stVerticalBlock"] { gap: var(--s-6); }
[data-testid="stHorizontalBlock"] { gap: var(--s-6); }
[data-testid="stExpander"] { margin-bottom: var(--s-3); }
[data-testid="stCheckbox"] { margin: var(--s-1) 0; }
.stButton { margin: 2px 0; }
section[data-testid="stSidebar"] .stButton { margin: 0; }
/* ---------- buttons: 42px, 12px radius, 13px/600 ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button { min-height: 42px; padding: 0 var(--s-6); border-radius: var(--r); font-weight: 600; font-size: 13px; border: 1px solid var(--line); background: #fff; color: var(--ink); box-shadow: none; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--accent); color: var(--accent); background: var(--bg); }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"], .stFormSubmitButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primaryFormSubmit"]:hover { background: var(--accent-dark); border-color: var(--accent-dark); color: #fff; }
.stButton > button:disabled, .stDownloadButton > button:disabled, .stFormSubmitButton > button:disabled {
  background: var(--subtle) !important; color: #55656d !important; border: 1px solid var(--line) !important; opacity: 1 !important; cursor: not-allowed; }
.stButton > button[kind="tertiary"] { border: 0; background: transparent; color: var(--accent); text-decoration: underline; min-height: 0; }
section[data-testid="stSidebar"] .stButton > button:disabled { background: transparent !important; border: 0 !important; }
button[role="tab"] { color: var(--muted) !important; font-weight: 500; }
button[role="tab"][aria-selected="true"] { color: var(--accent) !important; font-weight: 600; }
details, [data-testid="stExpander"] { background: #fff; border: 1px solid var(--line) !important; border-radius: var(--r); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *, .stCaption { color: var(--muted) !important; opacity: 1 !important; font-size: 12px; }
[data-baseweb="input"] > div, [data-baseweb="select"] > div > div { background: #fff !important; }
[data-baseweb="input"]:has(input:disabled) > div, [data-baseweb="select"] > div[aria-disabled="true"] > div { background: var(--subtle) !important; }
[data-testid="stAlert"] > div { border-radius: var(--r); }

/* ---------- surfaces: white cards, 1px #dce5e9, 12px radius, 16-20px padding ---------- */
[data-testid="stVerticalBlock"][class*="stVerticalBlockBorderWrapper"], [data-testid="stVerticalBlockBorderWrapper"] { background: var(--card); border-color: var(--line) !important; border-radius: var(--r) !important; }
.rs-card { background: var(--card); border: 1px solid var(--line); border-radius: var(--r); padding: var(--s-6) var(--s-7); margin-bottom: var(--s-5); }
.rs-metric { background: var(--card); border: 1px solid var(--line); border-radius: var(--r); padding: var(--s-6); }
.rs-metric .v { font-size: 28px; font-weight: 400; line-height: 34px; color: var(--ink); font-variant-numeric: tabular-nums; }
.rs-metric .l { font-size: 12px; font-weight: 500; color: var(--muted); margin-top: var(--s-2); }
.rs-metric::before { content:""; display:block; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); margin-bottom: var(--s-4); }
.rs-metric.t-blue::before { background: var(--blue); } .rs-metric.t-warm::before { background: var(--warm); } .rs-metric.t-green::before { background: var(--mint); }

/* status badges: Figma pills (6x10 padding, 12px/600, tinted fill) */
.rs-chip { display:inline-flex; align-items:center; gap: var(--s-2); padding: var(--s-2) var(--s-4); border-radius: var(--r-pill); font-size: 12px; line-height: 15px; font-weight: 600; margin: 0 var(--s-2) var(--s-4) 0; border: 0; background: var(--subtle); color: var(--muted); max-width: 100%; }
.rs-chip::before { content:""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.rs-chip.ok { background: var(--accent-soft); color: var(--accent); } .rs-chip.warn { background: var(--warm-soft); color: var(--warm); }
.rs-chip.danger { background: #fdecea; color: var(--danger); } .rs-chip.info { background: #eaf2fb; color: var(--info); }
.rs-chip.neutral { background: var(--subtle); color: var(--muted); }

/* banners: Figma "Sample notice" - tinted strip, 12px radius */
.rs-banner { border: 1px solid var(--line); border-radius: var(--r); padding: var(--s-5) var(--s-6); margin: 0 0 var(--s-6) 0; font-size: 12px; line-height: 18px; background: var(--bg); color: var(--ink); }
.rs-banner.demo { border-color: #f3dfbf; background: var(--warm-soft); color: var(--warm); font-weight: 600; padding: var(--s-3) var(--s-5); }
.rs-banner.danger { border-color: #f3c9c5; background: #fdf3f2; } .rs-banner.ok { border-color: #cfe9e4; background: var(--accent-soft); }
.rs-banner.info { border-color: var(--line); background: var(--bg); color: var(--muted); } .rs-banner.warn { border-color: #f3dfbf; background: var(--warm-soft); }

/* Figma "Patient toolbar" */
.rs-enchead { background: var(--card); border: 1px solid var(--line); border-radius: var(--r); padding: var(--s-6) var(--s-7); margin-bottom: var(--s-5); }
.rs-enchead .who { display:flex; align-items:center; gap: 14px; }
.rs-enchead .pav { width: 44px; height: 44px; flex:none; border-radius: var(--r); background: var(--subtle); color: var(--muted); display:flex; align-items:center; justify-content:center; }
.rs-enchead .ref { font-size: 17px; line-height: 21px; font-weight: 700; color: var(--ink); margin-right: var(--s-3); }
.rs-enchead .rs-chip { margin-bottom: 0; }
.rs-enchead .id { font-weight: 500; font-size: 13px; }
.rs-enchead .meta { color: var(--muted); font-size: 12px; margin-top: var(--s-2); }
.rs-pill { display:inline-flex; align-items:center; gap: var(--s-2); color: var(--accent); font-size: 12px; font-weight: 600; white-space: nowrap; }
.rs-pill::before { content:""; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
.rs-wshead { display:flex; justify-content:space-between; align-items:flex-end; gap: var(--s-6); margin: var(--s-3) 0 var(--s-5); }
.rs-wshead h2 { margin: 0 !important; padding: 0 !important; font-size: 27px !important; line-height: 33px !important; font-weight: 700 !important; color: var(--ink); }
.rs-wshead .d { color: var(--muted); font-size: 13px; margin-top: var(--s-3); }
.rs-finding { border: 1px solid var(--line); border-left-width: 4px; border-radius: var(--r); padding: var(--s-5) var(--s-6); margin-bottom: var(--s-5); background:#fff; }
.rs-finding.detected_concern { border-left-color: var(--danger); } .rs-finding.potential_concern { border-left-color: var(--warm); }
.rs-finding.incomplete_check, .rs-finding.cannot_check { border-left-color: var(--info); }
.rs-finding.unknown_or_unavailable { border-left-color: #7a5c9e; } .rs-finding.no_rules_triggered { border-left-color: var(--accent); }
.rs-finding .t { font-weight: 600; font-size: 13px; color: var(--ink); } .rs-finding .x { color: var(--ink2); font-size: 13px; margin-top: 3px; } .rs-finding .n { color: var(--muted); font-size: 12px; margin-top: var(--s-1); }
.rs-small { color: var(--muted); font-size: 12px; }
.rs-empty { text-align:center; color: var(--muted); padding: var(--s-8) var(--s-4); margin-bottom: var(--s-6); border: 1px dashed var(--line); border-radius: var(--r); background: #fff; }
.rs-check { display:flex; gap: var(--s-5); padding: var(--s-4) 0; border-bottom: 1px solid var(--line); font-size: 13px; }
.rs-check .s { font-weight: 700; min-width: 74px; } .rs-check .s.block { color: var(--danger); } .rs-check .s.note { color: var(--warn); } .rs-check .s.pass { color: var(--ok); }
.rs-check .s { text-transform: uppercase; font-size: 11px; letter-spacing: .05em; padding-top: 2px; }
:focus-visible { outline: 3px solid #1f8fff !important; outline-offset: 2px; }
@media (max-width: 800px){ .block-container{ padding-left: .8rem; padding-right: .8rem; } .st-key-ws_tab_ctl [data-testid="stButtonGroup"] > div { flex-wrap: wrap; } }
</style>
"""


ICON_MAP = {
    "nav_dashboard": "layout-dashboard", "nav_encounters": "users", "nav_new": "square-pen", "nav_history": "history", "nav_settings": "settings",
    "nav_ws_intake": "file-text", "nav_ws_transcript": "mic", "nav_ws_note": "file-text", "nav_ws_meds": "pill", "nav_ws_approve": "shield-check",
    "btn_lock": "lock", "btn_signout": "log-out",
}
_ICON_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "icons"
_FIGMA_ICON_DIR = _ICON_DIR.parent / "figma" / "icons"


def icon_uri(name: str) -> str:
    """Lucide icon (ISC licence) as a CSS data URI - bundled locally, no network. Figma exports win over the stock set."""
    for d in (_FIGMA_ICON_DIR, _ICON_DIR):
        try:
            svg = (d / f"{name}.svg").read_text(encoding="utf-8")
            break
        except OSError:
            continue
    else:
        return ""
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = re.sub(r'\s+class="[^"]*"', "", svg)
    return "url(data:image/svg+xml;base64," + base64.b64encode(svg.strip().encode()).decode() + ")"


def logo_svg(size: int = 34) -> str:
    try:
        svg = (_ICON_DIR.parent / "logo.svg").read_text(encoding="utf-8")
    except OSError:
        return ""
    return svg.replace("<svg ", f'<svg width="{size}" height="{size}" style="display:block" ', 1)


def icon_html(name: str, size: int = 16, color: str = "currentColor") -> str:
    u = icon_uri(name)
    return f'<span style="display:inline-block;width:{size}px;height:{size}px;background:{color};-webkit-mask:{u} center/contain no-repeat;mask:{u} center/contain no-repeat;vertical-align:-3px"></span>' if u else ""


def _icon_css() -> str:
    out = []
    for key, icon in ICON_MAP.items():
        u = icon_uri(icon)
        if u:
            out.append(f'.st-key-{key} button::before{{content:"";flex:none;width:16px;height:16px;margin-right:9px;background:currentColor;-webkit-mask:{u} center/contain no-repeat;mask:{u} center/contain no-repeat;}}')
    return "<style>" + "\n".join(out) + "</style>"


FONT_CSS = """<style>
@font-face { font-family: "Inter"; src: url("app/static/fonts/inter-latin.woff2") format("woff2"); font-weight: 100 900; font-style: normal; font-display: swap; }
@font-face { font-family: "IBM Plex Mono"; src: url("app/static/fonts/ibm-plex-mono-latin-400.woff2") format("woff2"); font-weight: 400; font-style: normal; font-display: swap; }
@font-face { font-family: "IBM Plex Mono"; src: url("app/static/fonts/ibm-plex-mono-latin-500.woff2") format("woff2"); font-weight: 500; font-style: normal; font-display: swap; }
html, body, .stApp, [class*="css"], button, input, textarea, select { font-family: "Inter", "Segoe UI", system-ui, sans-serif !important; font-feature-settings: "cv11", "ss03"; }
code, pre, .rs-enchead .id { font-family: "IBM Plex Mono", Consolas, "Cascadia Mono", monospace !important; }
</style>"""


def inject_css() -> None:
    st.markdown(CSS + FONT_CSS + _icon_css(), unsafe_allow_html=True)


def chip(text: str, kind: str = "neutral") -> str:
    return f'<span class="rs-chip {kind}">{esc(text)}</span>'


def chips(items: list[tuple[str, str]]) -> None:
    st.markdown("".join(chip(t, k) for t, k in items), unsafe_allow_html=True)


def banner(text: str, kind: str = "info", icon: str = "") -> None:
    st.markdown(f'<div class="rs-banner {kind}">{esc(text)}</div>', unsafe_allow_html=True)


def check_rows(rows: list[tuple[str, str, str]]) -> None:
    """rows: (kind block|note|pass, label, text)"""
    st.markdown("".join(f'<div class="rs-check"><span class="s {k}">{esc(l)}</span><span>{esc(x)}</span></div>' for k, l, x in rows), unsafe_allow_html=True)


def metric(label: str, value, col=None, tone: str = "") -> None:
    (col or st).markdown(f'<div class="rs-metric {"t-" + tone if tone else ""}"><div class="v">{esc(value)}</div><div class="l">{esc(label)}</div></div>', unsafe_allow_html=True)


def empty_state(title: str, hint: str = "") -> None:
    st.markdown(f'<div class="rs-empty"><b>{esc(title)}</b><br><span class="rs-small">{esc(hint)}</span></div>', unsafe_allow_html=True)


STATUS_CHIP = {
    "open": ("Open", "info"), "note_draft": ("Draft note", "warn"), "approved": ("Approved", "ok"), "archived": ("Archived", "neutral"),
    "draft": ("Draft", "warn"), "superseded": ("Superseded", "neutral"),
}


def status_chip(status: str) -> str:
    label, kind = STATUS_CHIP.get(status, (status, "neutral"))
    return chip(label, kind)

