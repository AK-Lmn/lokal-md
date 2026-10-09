"""Shared UI helpers: session access, design system (CSS), small HTML components."""
from __future__ import annotations

import html
import time

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
  --teal:#0b6e75; --teal-dark:#084f55; --teal-soft:#e2f1f2; --ink:#14262e; --muted:#5a6b73; --line:#d5e0e5;
  --bg:#f4f7f9; --card:#ffffff; --ok:#1b6b3a; --ok-bg:#e3f4e8; --warn:#8a5a00; --warn-bg:#fff2d1;
  --danger:#a8201a; --danger-bg:#fde8e6; --info:#1f5c99; --info-bg:#e5eefb; --neutral-bg:#eaeff2;
}
html, body, [class*="css"], .stApp { font-family: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; color: var(--ink); }
.block-container { padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1240px; }
h1, h2, h3 { letter-spacing: -0.01em; color: var(--ink); }
h1 { font-size: 1.65rem !important; font-weight: 700 !important; }
h2 { font-size: 1.25rem !important; } h3 { font-size: 1.05rem !important; }
section[data-testid="stSidebar"] { background: #0e2a33; }
section[data-testid="stSidebar"] * { color: #e8f1f3; }
section[data-testid="stSidebar"] .stButton > button { width: 100%; justify-content: flex-start; text-align: left; border: 0; background: transparent; color: #dbe9ec; padding: .5rem .75rem; border-radius: 8px; font-weight: 500; }
section[data-testid="stSidebar"] .stButton > button:hover { background: rgba(255,255,255,.09); color: #fff; }
section[data-testid="stSidebar"] .stButton > button[kind="primary"] { background: var(--teal); color: #fff; font-weight: 600; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.15); }
.rs-brand { font-weight: 700; font-size: 1.15rem; letter-spacing: .01em; }
.rs-brand small { display:block; font-weight: 400; font-size: .72rem; opacity: .75; letter-spacing: 0; }
.rs-navlabel { text-transform: uppercase; font-size: .68rem; letter-spacing: .08em; opacity: .6; margin: .9rem 0 .2rem .4rem; }
.rs-card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; margin-bottom: 12px; }
.rs-card h4 { margin: 0 0 6px 0; font-size: .95rem; }
.rs-metric { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 16px; }
.rs-metric .v { font-size: 1.9rem; font-weight: 700; line-height: 1.1; color: var(--teal-dark); }
.rs-metric .l { font-size: .8rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
.rs-chip { display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .76rem; font-weight: 600; margin: 0 4px 4px 0; border: 1px solid transparent; white-space: nowrap; }
.rs-chip.ok { background: var(--ok-bg); color: var(--ok); } .rs-chip.warn { background: var(--warn-bg); color: var(--warn); }
.rs-chip.danger { background: var(--danger-bg); color: var(--danger); } .rs-chip.info { background: var(--info-bg); color: var(--info); }
.rs-chip.neutral { background: var(--neutral-bg); color: var(--muted); }
.rs-banner { border-radius: 10px; padding: 9px 14px; margin: 0 0 10px 0; font-size: .9rem; border: 1px solid transparent; }
.rs-banner.demo { background: var(--warn-bg); color: var(--warn); border-color: #ecd391; font-weight: 600; }
.rs-banner.danger { background: var(--danger-bg); color: var(--danger); border-color: #f0b8b3; }
.rs-banner.ok { background: var(--ok-bg); color: var(--ok); border-color: #b7dcc4; }
.rs-banner.info { background: var(--info-bg); color: var(--info); border-color: #bcd2ee; }
.rs-banner.warn { background: var(--warn-bg); color: var(--warn); border-color: #ecd391; }
.rs-enchead { background: var(--card); border: 1px solid var(--line); border-left: 5px solid var(--teal); border-radius: 12px; padding: 10px 16px; margin-bottom: 10px; }
.rs-enchead .id { font-family: Consolas, monospace; font-weight: 700; font-size: 1.05rem; }
.rs-enchead .meta { color: var(--muted); font-size: .85rem; }
.rs-finding { border: 1px solid var(--line); border-left-width: 6px; border-radius: 10px; padding: 10px 14px; margin-bottom: 8px; background: #fff; }
.rs-finding.detected_concern { border-left-color: var(--danger); } .rs-finding.potential_concern { border-left-color: #d98a00; }
.rs-finding.incomplete_check, .rs-finding.cannot_check { border-left-color: var(--info); }
.rs-finding.unknown_or_unavailable { border-left-color: #7b5ea7; } .rs-finding.no_rules_triggered { border-left-color: #8fa3ad; }
.rs-finding .t { font-weight: 650; } .rs-finding .x { color: #2d3f47; font-size: .9rem; margin-top: 3px; } .rs-finding .n { color: var(--muted); font-size: .84rem; margin-top: 4px; }
.rs-small { color: var(--muted); font-size: .82rem; }
.rs-empty { text-align:center; color: var(--muted); padding: 28px 10px; border: 1px dashed var(--line); border-radius: 12px; background: #fbfdfe; }
.stButton > button[kind="primary"] { background: var(--teal); border-color: var(--teal); }
.stButton > button[kind="primary"]:hover { background: var(--teal-dark); border-color: var(--teal-dark); }
:focus-visible { outline: 3px solid #1f8fff !important; outline-offset: 2px; }
textarea, input { font-size: .95rem !important; }
@media (max-width: 800px){ .block-container{ padding-left: .8rem; padding-right: .8rem; } }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def chip(text: str, kind: str = "neutral") -> str:
    return f'<span class="rs-chip {kind}">{esc(text)}</span>'


def chips(items: list[tuple[str, str]]) -> None:
    st.markdown("".join(chip(t, k) for t, k in items), unsafe_allow_html=True)


def banner(text: str, kind: str = "info", icon: str = "") -> None:
    st.markdown(f'<div class="rs-banner {kind}">{icon + " " if icon else ""}{esc(text)}</div>', unsafe_allow_html=True)


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


def demo_banner() -> None:
    s = settings()
    if s.get("operating_mode") != "clinical":
        banner("DEMONSTRATION MODE - synthetic reference data. Use synthetic patients only. Not validated for patient care.", "demo", "⚠")
