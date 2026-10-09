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
:root{
  --ink:#16252c; --ink2:#34454d; --muted:#586971; --line:#cfd8dd; --line2:#e3e9ec; --bg:#f6f7f8; --card:#ffffff;
  --accent:#0d6b73; --accent-dark:#09535a; --accent-soft:#e6f1f2;
  --ok:#1d6b3f; --warn:#8a5a00; --danger:#a3241d; --info:#1f5a94;
}
html, body, .stApp, [class*="css"] { font-family: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; color: var(--ink); }
.stApp { background: var(--bg); }
.block-container { padding-top: 1rem; padding-bottom: 3rem; max-width: 1200px; }
h1, h2, h3, h4, h5 { color: var(--ink); letter-spacing: 0; }
h1 { font-size: 1.5rem !important; font-weight: 650 !important; margin-bottom: .2rem; }
h2 { font-size: 1.2rem !important; font-weight: 650 !important; }
h3 { font-size: 1.05rem !important; font-weight: 650 !important; }
h4, h5 { font-size: .95rem !important; font-weight: 650 !important; text-transform: none; }
p, li, label, span { color: inherit; }

/* ---------- sidebar: light, quiet ---------- */
section[data-testid="stSidebar"] { background: #eef2f3; border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] .stButton > button::before { opacity: .85; }
.rs-brandrow { display:flex; align-items:center; gap:10px; padding: .4rem .5rem .6rem; margin-bottom: .9rem; }
.rs-logo { width: 38px; height: 38px; flex:none; line-height:0; }
.rs-hero { background: #0d6b73; color:#fff; border-radius: 14px; padding: 40px 36px; min-height: 440px; }
.rs-hero h2 { color:#fff !important; font-size: 1.6rem !important; margin: 18px 0 8px; }
.rs-hero p { color: #d7ecee; font-size: .95rem; line-height: 1.55; }
.rs-hero li { color:#eaf6f7; margin: 10px 0; font-size:.93rem; list-style:none; }
.rs-hero ul { padding: 0; margin: 22px 0 0; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .3rem; }
section[data-testid="stSidebar"] .stButton > button { width: 100%; justify-content: flex-start; text-align: left; border: 0; border-radius: 6px;
  background: transparent; color: var(--ink2); padding: .6rem .85rem; font-weight: 500; font-size: .92rem; min-height: 0; }
section[data-testid="stSidebar"] .stButton > button:hover { background: #dfe5e8; color: var(--ink); }
section[data-testid="stSidebar"] .stButton > button[kind="primary"] { background: #fff; color: var(--accent-dark); font-weight: 650; box-shadow: inset 3px 0 0 var(--accent); }
.rs-brand { font-weight: 700; font-size: 1.1rem; color: var(--ink); padding: .2rem .3rem 0; }
.rs-brand small { display:block; font-weight: 400; font-size: .76rem; color: var(--muted); }
.rs-navlabel { text-transform: uppercase; font-size: .68rem; letter-spacing: .07em; color: var(--muted); padding: 1.2rem 0 1rem .85rem; font-weight: 600; line-height: 1.3; margin: 0; }

/* ---------- inputs: white, bordered, always readable ---------- */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] * { color: var(--ink) !important; opacity: 1 !important; font-size: .88rem; font-weight: 500; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div, [data-testid="stNumberInputContainer"] { background: #fff !important; border: 1px solid #b4c1c8 !important; border-radius: 6px !important; }
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea, [data-baseweb="select"] * { color: var(--ink) !important; font-size: .94rem !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"] > div:focus-within { border-color: var(--accent) !important; box-shadow: 0 0 0 2px rgba(13,107,115,.2) !important; }
[data-baseweb="base-input"], [data-baseweb="base-input"] input, textarea { background: #fff !important; }
[data-baseweb="base-input"]:has(input:disabled), textarea:disabled { background: #eef1f3 !important; }
::placeholder { color: #66767e !important; opacity: 1 !important; }
input:disabled, textarea:disabled, [aria-disabled="true"], [data-disabled="true"] { opacity: 1 !important; -webkit-text-fill-color: #2c3c44 !important; color: #2c3c44 !important; cursor: not-allowed; }
[data-baseweb="input"]:has(input:disabled), [data-baseweb="textarea"]:has(textarea:disabled), [data-baseweb="select"] > div[aria-disabled="true"] { background: #eef1f3 !important; border-color: #d3dce0 !important; }
.stCheckbox label, .stRadio label { color: var(--ink) !important; }

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button { border-radius: 6px; font-weight: 600; font-size: .92rem; border: 1px solid #aebbc2; background: #fff; color: var(--ink); box-shadow: none; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--accent); color: var(--accent-dark); background: #f4fafa; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"], .stFormSubmitButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.stButton > button[kind="primary"]:hover { background: var(--accent-dark); border-color: var(--accent-dark); color: #fff; }
.stButton > button:disabled, .stDownloadButton > button:disabled, .stFormSubmitButton > button:disabled {
  background: #e9edef !important; color: #55656d !important; border: 1px solid #cdd6da !important; opacity: 1 !important; cursor: not-allowed; }
.stButton > button[kind="tertiary"] { border: 0; background: transparent; color: var(--accent-dark); text-decoration: underline; }
section[data-testid="stSidebar"] .stButton > button:disabled { background: transparent !important; border: 0 !important; }
[data-testid="stSegmentedControl"] button { font-size: .9rem; }
button[role="tab"] { color: var(--ink2) !important; font-weight: 500; }
button[role="tab"][aria-selected="true"] { color: var(--accent-dark) !important; font-weight: 650; }
details, [data-testid="stExpander"] { background: #fff; border: 1px solid var(--line) !important; border-radius: 8px; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *, .stCaption { color: #4a5b63 !important; opacity: 1 !important; }
[data-baseweb="input"] > div, [data-baseweb="select"] > div > div { background: #fff !important; }
[data-baseweb="input"]:has(input:disabled) > div, [data-baseweb="select"] > div[aria-disabled="true"] > div { background: #eef1f3 !important; }

/* ---------- surfaces ---------- */
.rs-card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(22,37,44,.05); }
.rs-metric { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 18px; box-shadow: 0 1px 2px rgba(22,37,44,.05); border-top: 3px solid var(--accent); }
.rs-metric .v { font-size: 2rem; font-weight: 650; line-height: 1.1; color: var(--ink); font-variant-numeric: tabular-nums; }
.rs-metric .l { font-size: .78rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }

/* status chips: outlined, dark text, small colour dot */
.rs-chip { display:inline-flex; align-items:center; gap:6px; padding: 1px 9px; border-radius: 4px; font-size: .78rem; font-weight: 600; margin: 0 5px 4px 0; border: 1px solid var(--line); background:#fff; color: var(--ink2); white-space: nowrap; }
.rs-chip::before { content:""; width:7px; height:7px; border-radius:50%; background:#8a99a1; }
.rs-chip.ok::before { background: var(--ok); } .rs-chip.warn::before { background:#c98a00; }
.rs-chip.danger::before { background: var(--danger); } .rs-chip.info::before { background: var(--info); }
.rs-chip.neutral::before { background:#8a99a1; }

/* banners: plain, left rule, dark text */
.rs-banner { border: 1px solid var(--line); border-left-width: 4px; border-radius: 6px; padding: 8px 12px; margin: 0 0 8px 0; font-size: .9rem; background:#fff; color: var(--ink); }
.rs-banner.demo { border-left-color:#c98a00; background:#fffaf0; font-weight: 600; font-size: .85rem; padding: 6px 12px; }
.rs-banner.danger { border-left-color: var(--danger); } .rs-banner.ok { border-left-color: var(--ok); }
.rs-banner.info { border-left-color: var(--info); } .rs-banner.warn { border-left-color:#c98a00; }

.rs-enchead { background: #fff; border: 1px solid var(--line); border-radius: 10px; padding: 10px 16px; margin-bottom: 10px; box-shadow: 0 1px 2px rgba(22,37,44,.05); }
.rs-enchead .id { font-family: Consolas, "Courier New", monospace; font-weight: 700; font-size: 1rem; }
.rs-enchead .meta { color: var(--muted); font-size: .85rem; margin-top: 2px; }
.rs-finding { border: 1px solid var(--line); border-left-width: 4px; border-radius: 6px; padding: 9px 12px; margin-bottom: 7px; background:#fff; }
.rs-finding.detected_concern { border-left-color: var(--danger); } .rs-finding.potential_concern { border-left-color: #c98a00; }
.rs-finding.incomplete_check, .rs-finding.cannot_check { border-left-color: var(--info); }
.rs-finding.unknown_or_unavailable { border-left-color: #7a5c9e; } .rs-finding.no_rules_triggered { border-left-color: #9aa8af; }
.rs-finding .t { font-weight: 650; color: var(--ink); } .rs-finding .x { color: var(--ink2); font-size: .9rem; margin-top: 3px; } .rs-finding .n { color: var(--muted); font-size: .84rem; margin-top: 4px; }
.rs-small { color: var(--muted); font-size: .82rem; }
.rs-empty { text-align:center; color: var(--muted); padding: 22px 10px; border: 1px dashed #b4c1c8; border-radius: 8px; background: #fff; }
.rs-check { display:flex; gap:10px; padding: 7px 0; border-bottom: 1px solid var(--line2); font-size:.92rem; }
.rs-check .s { font-weight: 700; min-width: 74px; } .rs-check .s.block { color: var(--danger); } .rs-check .s.note { color: var(--warn); } .rs-check .s.pass { color: var(--ok); }
:focus-visible { outline: 3px solid #1f8fff !important; outline-offset: 2px; }
@media (max-width: 800px){ .block-container{ padding-left: .8rem; padding-right: .8rem; } }
</style>
"""


ICON_MAP = {
    "nav_dashboard": "layout-dashboard", "nav_encounters": "clipboard-list", "nav_new": "circle-plus", "nav_history": "history", "nav_settings": "settings",
    "nav_ws_intake": "file-text", "nav_ws_transcript": "mic", "nav_ws_note": "file-text", "nav_ws_meds": "pill", "nav_ws_approve": "shield-check",
    "btn_lock": "lock", "btn_signout": "log-out",
}
_ICON_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "icons"


def icon_uri(name: str) -> str:
    """Lucide icon (ISC licence) as a CSS data URI - bundled locally, no network."""
    try:
        svg = (_ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
    except OSError:
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
html, body, .stApp, [class*="css"], button, input, textarea, select { font-family: "Inter", "Segoe UI", system-ui, sans-serif !important; font-feature-settings: "cv11", "ss03"; }
code, pre, .rs-enchead .id { font-family: Consolas, "Cascadia Mono", monospace !important; }
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


def metric(label: str, value, col=None) -> None:
    (col or st).markdown(f'<div class="rs-metric"><div class="v">{esc(value)}</div><div class="l">{esc(label)}</div></div>', unsafe_allow_html=True)


def empty_state(title: str, hint: str = "") -> None:
    st.markdown(f'<div class="rs-empty"><b>{esc(title)}</b><br><span class="rs-small">{esc(hint)}</span></div>', unsafe_allow_html=True)


STATUS_CHIP = {
    "open": ("Open", "info"), "note_draft": ("Draft note", "warn"), "approved": ("Approved", "ok"), "archived": ("Archived", "neutral"),
    "draft": ("Draft", "warn"), "superseded": ("Superseded", "neutral"),
}


def status_chip(status: str) -> str:
    label, kind = STATUS_CHIP.get(status, (status, "neutral"))
    return chip(label, kind)

