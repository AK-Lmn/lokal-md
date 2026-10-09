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
  --ink:#14262e; --ink2:#34454d; --muted:#52656f; --line:#dce5e9; --line2:#e8eef1; --bg:#f8fafc; --card:#ffffff;
  --accent:#0b6e75; --accent-dark:#07494e; --accent-soft:#edf8f6; --mint:#2dd4bf; --warm:#e0803a; --blue:#2f6fb5; --green:#1b6b3a; --navy:#07494e;
  --ok:#1b6b3a; --warn:#95520b; --danger:#a3241d; --info:#1f5a94;
}
html, body, .stApp, [class*="css"] { font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif; color: var(--ink); }
.stApp { background: var(--bg); }
.block-container { padding-top: 3.8rem; padding-bottom: 4rem; max-width: 1240px; }
h1, h2, h3, h4, h5 { color: var(--ink); letter-spacing: -0.01em; }
h1 { font-size: 1.6rem !important; font-weight: 700 !important; margin-bottom: .25rem; }
h2 { font-size: 1.25rem !important; font-weight: 700 !important; }
h3 { font-size: 1.05rem !important; font-weight: 650 !important; }
h4, h5 { font-size: .95rem !important; font-weight: 650 !important; text-transform: none; }
p, li, label, span { color: inherit; }

/* ---------- sidebar: clean, crisp, matching Figma design ---------- */
section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] .stButton > button::before { opacity: .85; }
section[data-testid="stSidebar"] .stButton > button[kind="primary"]::before { opacity: 1; }
.rs-brandrow { display:flex; align-items:center; gap:12px; padding: .6rem .6rem .8rem; margin-bottom: .8rem; border-bottom: 1px solid var(--line2); }
.rs-logo { width: 38px; height: 38px; flex:none; line-height:0; }
.rs-hero { background: linear-gradient(160deg,#0b6e75 0%,#042f2e 100%); color:#fff; border-radius: 16px; padding: 42px 38px; min-height: 440px; border-bottom: 5px solid var(--mint); }
.rs-hero h2 { border: 0 !important; padding: 0 !important; margin: 22px 0 12px !important; color:#fff !important; font-size: 1.7rem !important; margin: 18px 0 8px; }
.rs-hero p { color: #d7ecee; font-size: .95rem; line-height: 1.55; }
.rs-tagline { color:#fff; font-size: 1.35rem; font-weight: 650; line-height: 1.35; margin: 0 0 8px; }
.rs-tagsub { color:#a9d3d7; font-size: .82rem; letter-spacing: .02em; margin-bottom: 4px; }
.rs-hero li { color:#eaf6f7; margin: 10px 0; font-size:.93rem; list-style:none; }
.rs-hero ul { padding: 0; margin: 22px 0 0; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .35rem; }
section[data-testid="stSidebar"] .stButton > button { width: 100%; justify-content: flex-start; text-align: left; border: 0; border-radius: 10px;
  background: transparent; color: var(--ink); padding: .62rem .9rem; font-weight: 500; font-size: .92rem; min-height: 42px; }
section[data-testid="stSidebar"] .stButton > button:hover { background: var(--accent-soft); color: var(--accent-dark); }
section[data-testid="stSidebar"] .stButton > button[kind="primary"] { background: var(--accent); color: #fff; font-weight: 600; box-shadow: 0 1px 2px rgba(11,110,117,.25); }
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover { background: var(--accent-dark); color: #fff; }
.rs-brand { font-weight: 700; font-size: 1.15rem; color: var(--ink); padding: .1rem .2rem 0; line-height: 1.25; }
.rs-brand small { display:block; font-weight: 400; font-size: .75rem; color: var(--muted); margin-top: 2px; }
.rs-navlabel { text-transform: uppercase; font-size: .68rem; letter-spacing: .08em; color: var(--muted); padding: 1.1rem 0 .5rem .75rem; font-weight: 700; line-height: 1.3; margin: 0; }

/* ---------- offline vault card (Figma spec) ---------- */
.rs-vault-card { background: #f8fafc; border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; margin: 10px 0; }
.rs-vault-badge { display:inline-flex; align-items:center; gap:6px; background: #edf8f6; color: #0b6e75; font-size: .75rem; font-weight: 650; padding: 3px 8px; border-radius: 100px; margin-bottom: 6px; }
.rs-vault-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: #0b6e75; }
.rs-vault-desc { font-size: .75rem; color: var(--muted); line-height: 1.45; margin-bottom: 6px; }
.rs-vault-foot { font-size: .72rem; color: #0b6e75; font-weight: 600; }

/* ---------- user card & avatar (Figma spec) ---------- */
.rs-usercard { display: flex; align-items: center; gap: 10px; padding: 6px 4px 12px; margin-top: 4px; }
.rs-avatar { width: 34px; height: 34px; border-radius: 50%; background: #e0f2fe; color: #0369a1; font-weight: 700; font-size: .8rem; display: flex; align-items: center; justify-content: center; flex: none; }
.rs-username { font-weight: 650; font-size: .88rem; color: var(--ink); line-height: 1.2; }
.rs-userrole { font-size: .75rem; color: var(--muted); margin-top: 2px; }

.block-container h5 { border-left: 4px solid var(--warm); padding-left: .6rem; margin: .9rem 0 .9rem; }
.block-container h4 { border-left: 4px solid var(--accent); padding-left: .6rem; margin: 1.2rem 0 .9rem; }
.block-container h1 { margin-bottom: .6rem; }
/* ---------- segmented control tabs (Figma modern pill & active state) ---------- */
[data-testid="stSegmentedControl"] { background: #f1f5f9; padding: 4px; border-radius: 12px; border: 1px solid var(--line); }
[data-testid="stSegmentedControl"] [data-testid="stButtonGroup"] { gap: 4px; }
[data-testid="stSegmentedControl"] [data-testid="stButtonGroup"] button[role="radio"] {
  background: transparent; border: 0 !important; color: var(--muted) !important; font-weight: 500; font-size: .88rem;
  border-radius: 8px !important; padding: .45rem 1rem !important; transition: all .15s ease-in-out;
}
[data-testid="stSegmentedControl"] [data-testid="stButtonGroup"] button[role="radio"]:hover {
  background: rgba(255, 255, 255, 0.6) !important; color: var(--ink) !important;
}
[data-testid="stSegmentedControl"] [data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"] {
  background: #ffffff !important; color: #0b6e75 !important; font-weight: 650 !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04) !important;
}
[data-testid="stSegmentedControl"] [data-testid="stButtonGroup"] button[role="radio"][aria-checked="true"] * {
  color: #0b6e75 !important;
}

/* ---------- inputs: Figma clean white cards & subtle borders ---------- */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] * { color: var(--ink) !important; opacity: 1 !important; font-size: .85rem; font-weight: 600; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div, [data-testid="stNumberInputContainer"] {
  background: #fff !important; border: 1px solid var(--line) !important; border-radius: 8px !important; box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
}
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea, [data-baseweb="select"] * { color: var(--ink) !important; font-size: .92rem !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"] > div:focus-within {
  border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(11,110,117,.12) !important;
}
[data-baseweb="base-input"], [data-baseweb="base-input"] input, textarea { background: #fff !important; }
[data-baseweb="base-input"]:has(input:disabled), textarea:disabled { background: #f8fafc !important; }
::placeholder { color: #94a3b8 !important; opacity: 1 !important; }
input:disabled, textarea:disabled, [aria-disabled="true"], [data-disabled="true"] { opacity: 1 !important; -webkit-text-fill-color: #475569 !important; color: #475569 !important; cursor: not-allowed; }
[data-baseweb="input"]:has(input:disabled), [data-baseweb="textarea"]:has(textarea:disabled), [data-baseweb="select"] > div[aria-disabled="true"] { background: #f8fafc !important; border-color: #e2e8f0 !important; }
.stCheckbox label, .stRadio label { color: var(--ink) !important; font-size: .88rem; }

/* ---------- spacing ---------- */
[data-testid="stVerticalBlock"] { gap: 1rem; }
[data-testid="stHorizontalBlock"] { gap: 1rem; }
[data-testid="stExpander"] { margin-bottom: .5rem; }
[data-testid="stCheckbox"] { margin: .25rem 0; }
.stButton { margin: .15rem 0; }
section[data-testid="stSidebar"] .stButton { margin: 0; }
/* ---------- buttons: crisp Figma corners and shadows ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 8px; font-weight: 600; font-size: .88rem; border: 1px solid var(--line); background: #fff; color: var(--ink); box-shadow: 0 1px 2px rgba(0,0,0,0.03); transition: all .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover { border-color: #cbd5e1; color: var(--accent-dark); background: #f8fafc; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"], .stFormSubmitButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: var(--accent); border-color: var(--accent); color: #fff; box-shadow: 0 1px 3px rgba(11,110,117,0.25);
}
.stButton > button[kind="primary"]:hover { background: var(--accent-dark); border-color: var(--accent-dark); color: #fff; }
.stButton > button:disabled, .stDownloadButton > button:disabled, .stFormSubmitButton > button:disabled {
  background: #f1f5f9 !important; color: #94a3b8 !important; border: 1px solid #e2e8f0 !important; opacity: 1 !important; cursor: not-allowed; box-shadow: none !important;
}
.stButton > button[kind="tertiary"] { border: 0; background: transparent; color: var(--accent-dark); text-decoration: underline; box-shadow: none; }
section[data-testid="stSidebar"] .stButton > button:disabled { background: transparent !important; border: 0 !important; }
button[role="tab"] { color: var(--muted) !important; font-weight: 500; }
button[role="tab"][aria-selected="true"] { color: var(--accent) !important; font-weight: 650; }
details, [data-testid="stExpander"] { background: #fff; border: 1px solid var(--line) !important; border-radius: 8px; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *, .stCaption { color: #4a5b63 !important; opacity: 1 !important; }
[data-baseweb="input"] > div, [data-baseweb="select"] > div > div { background: #fff !important; }
[data-baseweb="input"]:has(input:disabled) > div, [data-baseweb="select"] > div[aria-disabled="true"] > div { background: #eef1f3 !important; }

/* ---------- surfaces ---------- */
.rs-card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(22,37,44,.05); }
.rs-metric { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 18px; box-shadow: 0 1px 2px rgba(22,37,44,.05); border-top: 3px solid var(--accent); }
.rs-metric.t-blue { border-top-color: var(--blue); } .rs-metric.t-warm { border-top-color: var(--warm); } .rs-metric.t-green { border-top-color: var(--green); }
.rs-metric .v { font-size: 2rem; font-weight: 650; line-height: 1.1; color: var(--ink); font-variant-numeric: tabular-nums; }
.rs-metric .l { font-size: .78rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }

/* status chips: outlined, dark text, small colour dot */
.rs-chip { display:inline-flex; align-items:center; gap:6px; padding: 2px 9px; border-radius: 4px; font-size: .78rem; font-weight: 600; margin: 0 6px 10px 0; border: 1px solid var(--line); background:#fff; color: var(--ink2); white-space: nowrap; }
.rs-chip::before { content:""; width:7px; height:7px; border-radius:50%; background:#8a99a1; }
.rs-chip.ok::before { background: var(--ok); } .rs-chip.warn::before { background:#c98a00; }
.rs-chip.danger::before { background: var(--danger); } .rs-chip.info::before { background: var(--info); }
.rs-chip.neutral::before { background:#8a99a1; }

/* banners: plain, left rule, dark text */
.rs-banner { border: 1px solid var(--line); border-left-width: 4px; border-radius: 6px; padding: 9px 14px; margin: 0 0 14px 0; font-size: .9rem; background:#fff; color: var(--ink); }
.rs-banner.demo { border-left-color:#c98a00; background:#fffaf0; font-weight: 600; font-size: .85rem; padding: 6px 12px; }
.rs-banner.danger { border-left-color: var(--danger); background:#fdf3f2; } .rs-banner.ok { border-left-color: var(--ok); background:#f2faf5; }
.rs-banner.info { border-left-color: var(--info); background:#f3f7fc; } .rs-banner.warn { border-left-color:#c98a00; background:#fffaf0; }

.rs-enchead { background: #fff; border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(22,37,44,.05); }
.rs-enchead .id { font-family: Consolas, "Courier New", monospace; font-weight: 700; font-size: 1rem; }
.rs-enchead .meta { color: var(--muted); font-size: .85rem; margin-top: 2px; }
.rs-finding { border: 1px solid var(--line); border-left-width: 4px; border-radius: 6px; padding: 10px 14px; margin-bottom: 12px; background:#fff; }
.rs-finding.detected_concern { border-left-color: var(--danger); } .rs-finding.potential_concern { border-left-color: #c98a00; }
.rs-finding.incomplete_check, .rs-finding.cannot_check { border-left-color: var(--info); }
.rs-finding.unknown_or_unavailable { border-left-color: #7a5c9e; } .rs-finding.no_rules_triggered { border-left-color: #9aa8af; }
.rs-finding .t { font-weight: 650; color: var(--ink); } .rs-finding .x { color: var(--ink2); font-size: .9rem; margin-top: 3px; } .rs-finding .n { color: var(--muted); font-size: .84rem; margin-top: 4px; }
.rs-small { color: var(--muted); font-size: .82rem; }
.rs-empty { text-align:center; color: var(--muted); padding: 22px 10px; margin-bottom: 1rem; border: 1px dashed #b4c1c8; border-radius: 8px; background: #fff; }
.rs-check { display:flex; gap:12px; padding: 9px 0; border-bottom: 1px solid var(--line2); font-size:.92rem; }
.rs-check .s { font-weight: 700; min-width: 74px; } .rs-check .s.block { color: var(--danger); } .rs-check .s.note { color: var(--warn); } .rs-check .s.pass { color: var(--ok); }
.rs-check .s { text-transform: uppercase; font-size: .72rem; letter-spacing: .05em; padding-top: 2px; }
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

