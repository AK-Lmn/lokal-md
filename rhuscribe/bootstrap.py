"""Database initialisation and first-run seeding."""
from __future__ import annotations

import sqlite3

from . import db
from .safety import refdata
from .safety.demo_data import demo_bundle


def init(conn: sqlite3.Connection) -> None:
    db.init_db(conn)
    if not conn.execute("SELECT 1 FROM ref_datasets").fetchone():
        ds = refdata.save_bundle(conn, demo_bundle(), kind="synthetic_demo", imported_by=None)
        refdata.set_active(conn, ds)
