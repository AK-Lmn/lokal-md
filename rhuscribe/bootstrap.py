"""Database initialisation and first-run seeding."""
from __future__ import annotations

import sqlite3

from . import db
from .safety import refdata
from .safety.demo_data import demo_bundle


def init(conn: sqlite3.Connection) -> None:
    db.init_db(conn)
    # earlier builds named the bundled set 'SYNTHETIC DEMO DATA'
    _normalise_sample_set(conn)
    if not conn.execute("SELECT 1 FROM ref_datasets").fetchone():
        ds = refdata.save_bundle(conn, demo_bundle(), kind="synthetic_demo", imported_by=None)
        refdata.set_active(conn, ds)


def _normalise_sample_set(conn: sqlite3.Connection) -> None:
    """Earlier builds stored the bundled sample set with '[SYNTHETIC]' prefixes and a different name/citation."""
    ids = [r[0] for r in conn.execute("SELECT id FROM ref_datasets WHERE kind='synthetic_demo'")]
    cite = "Lokal.MD sample reference set (unverified)"
    for ds in ids:
        conn.execute("UPDATE ref_datasets SET name='Lokal.MD sample reference set' WHERE id=? AND name IN ('SYNTHETIC DEMO DATA','Synthetic sample data','Tala sample reference set')", (ds,))
        for table, text_col in (("ref_interactions", "effect"), ("ref_contraindications", "note"), ("ref_dose_limits", "note"),
                                ("ref_age_warnings", "message"), ("ref_allergy_cross", "note")):
            conn.execute(f"UPDATE {table} SET {text_col}=REPLACE({text_col}, '[SYNTHETIC] ', ''), source_citation=? "
                         f"WHERE dataset_id=? AND source_citation LIKE 'SYNTHETIC-DEMO%'", (cite, ds))
    conn.commit()
