"""Database initialisation and first-run seeding."""
from __future__ import annotations

import sqlite3

from . import db
from .safety import refdata
from .safety.demo_data import demo_bundle


def init(conn: sqlite3.Connection) -> None:
    db.init_db(conn)
    # earlier builds named the bundled set 'SYNTHETIC DEMO DATA'
    conn.execute("UPDATE ref_datasets SET name='Synthetic sample data' WHERE kind='synthetic_demo' AND name='SYNTHETIC DEMO DATA'")
    conn.commit()
    if not conn.execute("SELECT 1 FROM ref_datasets").fetchone():
        ds = refdata.save_bundle(conn, demo_bundle(), kind="synthetic_demo", imported_by=None)
        refdata.set_active(conn, ds)
