"""Session lifecycle: inactivity lock and sign-out. Clearing the session drops the data key."""
from __future__ import annotations

import time

import streamlit as st

from .. import audit
from . import common as C
from . import wsstate as W


def idle_seconds() -> float:
    return time.time() - st.session_state.get("last_active", time.time())


def idle_exceeded() -> bool:
    minutes = C.settings().get("inactivity_lock_minutes", 10)
    return idle_seconds() > minutes * 60


def _wipe(keep_username: str | None, flash_msg: str | None) -> None:
    for k in list(st.session_state.keys()):
        if k in ("_conn",):
            continue
        del st.session_state[k]
    if keep_username:
        st.session_state["locked_username"] = keep_username
    if flash_msg:
        C.flash(flash_msg, "info")


def lock(reason: str = "inactivity") -> None:
    """Auto-save unsaved work (best effort), then drop the user, key and every workspace value."""
    user = C.user()
    if not user:
        return
    try:
        from . import workspace
        workspace.autosave_on_lock()
    except Exception:
        pass
    try:
        audit.record(C.conn(), user, "session.locked", "user", user["id"], {"reason": reason})
    except Exception:
        pass
    _wipe(user["username"], None)


def logout(msg: str | None = None) -> None:
    user = C.user()
    if user:
        try:
            workspace_save()
            audit.record(C.conn(), user, "logout", "user", user["id"])
        except Exception:
            pass
    _wipe(None, msg)


def workspace_save() -> None:
    from . import workspace
    workspace.autosave_on_lock()
