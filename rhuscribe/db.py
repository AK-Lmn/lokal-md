"""SQLite access and versioned schema migrations (PRAGMA user_version)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

MIGRATIONS: list[str] = [
    # ---- v1 -------------------------------------------------------------------------
    """
    CREATE TABLE app_settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT
    );
    CREATE TABLE key_store(
        id INTEGER PRIMARY KEY CHECK (id = 1),
        recovery_wrap TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE users(
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL,
        credentials TEXT NOT NULL DEFAULT '',
        license_no TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL CHECK (role IN ('admin','clinician','staff','pharmacist')),
        wrapped_dek TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    );
    CREATE TABLE encounters(
        id TEXT PRIMARY KEY,
        patient_idx TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','note_draft','approved','archived')),
        data_enc TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by TEXT REFERENCES users(id),
        updated_by TEXT REFERENCES users(id)
    );
    CREATE INDEX idx_enc_patient ON encounters(patient_idx);
    CREATE INDEX idx_enc_status ON encounters(status, updated_at);
    CREATE TABLE transcripts(
        encounter_id TEXT PRIMARY KEY REFERENCES encounters(id) ON DELETE CASCADE,
        text_enc TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('manual','audio')),
        status TEXT NOT NULL CHECK (status IN ('unreviewed','reviewed')),
        language TEXT,
        asr_model TEXT,
        updated_at TEXT NOT NULL,
        reviewed_by TEXT REFERENCES users(id),
        reviewed_at TEXT
    );
    CREATE TABLE medication_orders(
        id TEXT PRIMARY KEY,
        encounter_id TEXT NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        data_enc TEXT NOT NULL,
        entered_by TEXT REFERENCES users(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_orders_enc ON medication_orders(encounter_id, seq);
    CREATE TABLE note_versions(
        id TEXT PRIMARY KEY,
        encounter_id TEXT NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
        version INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','approved','superseded')),
        content_enc TEXT NOT NULL,
        generation_method TEXT NOT NULL CHECK (generation_method IN ('llm','template','manual')),
        model TEXT,
        content_hash TEXT,
        created_by TEXT REFERENCES users(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        approved_by TEXT REFERENCES users(id),
        approved_at TEXT,
        approver_snapshot_enc TEXT,
        UNIQUE (encounter_id, version)
    );
    CREATE UNIQUE INDEX idx_one_draft ON note_versions(encounter_id) WHERE status = 'draft';
    CREATE TABLE med_reviews(
        id TEXT PRIMARY KEY,
        encounter_id TEXT NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
        input_hash TEXT NOT NULL,
        dataset_id TEXT,
        overall TEXT NOT NULL,
        result_enc TEXT NOT NULL,
        run_at TEXT NOT NULL,
        run_by TEXT REFERENCES users(id)
    );
    CREATE INDEX idx_reviews_enc ON med_reviews(encounter_id, run_at);
    CREATE TABLE review_acks(
        id TEXT PRIMARY KEY,
        review_id TEXT NOT NULL REFERENCES med_reviews(id) ON DELETE CASCADE,
        finding_key TEXT NOT NULL,
        user_id TEXT REFERENCES users(id),
        reason_enc TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (review_id, finding_key)
    );
    CREATE TABLE audio_files(
        id TEXT PRIMARY KEY,
        encounter_id TEXT NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
        blob_enc BLOB NOT NULL,
        mime TEXT,
        size INTEGER NOT NULL,
        policy_ref TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT
    );
    CREATE TABLE audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        user_id TEXT,
        username TEXT,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id TEXT,
        detail TEXT,
        prev_hash TEXT NOT NULL,
        hash TEXT NOT NULL
    );
    CREATE INDEX idx_audit_target ON audit_log(target_type, target_id);

    CREATE TABLE ref_datasets(
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        version TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('synthetic_demo','imported')),
        source_description TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending_review','approved','retired','rejected')),
        active INTEGER NOT NULL DEFAULT 0,
        checksum TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        imported_by TEXT,
        reviewed_at TEXT,
        reviewed_by TEXT,
        review_notes TEXT
    );
    CREATE TABLE ref_classes(
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        key TEXT NOT NULL, name TEXT NOT NULL,
        PRIMARY KEY (dataset_id, key)
    );
    CREATE TABLE ref_ingredients(
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        key TEXT NOT NULL, name TEXT NOT NULL,
        PRIMARY KEY (dataset_id, key)
    );
    CREATE TABLE ref_ingredient_classes(
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        ingredient_key TEXT NOT NULL, class_key TEXT NOT NULL,
        PRIMARY KEY (dataset_id, ingredient_key, class_key)
    );
    CREATE TABLE ref_aliases(
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        alias_norm TEXT NOT NULL,
        target_type TEXT NOT NULL CHECK (target_type IN ('ingredient','class')),
        target_key TEXT NOT NULL,
        alias_kind TEXT NOT NULL DEFAULT 'generic',
        PRIMARY KEY (dataset_id, alias_norm, target_type, target_key)
    );
    CREATE TABLE ref_interactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        a_type TEXT NOT NULL, a_key TEXT NOT NULL,
        b_type TEXT NOT NULL, b_key TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('contraindicated','major','moderate','minor')),
        effect TEXT NOT NULL, management TEXT NOT NULL, source_citation TEXT NOT NULL
    );
    CREATE TABLE ref_contraindications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        subject_type TEXT NOT NULL, subject_key TEXT NOT NULL,
        condition_terms TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('contraindicated','major','moderate','minor')),
        note TEXT NOT NULL, management TEXT NOT NULL, source_citation TEXT NOT NULL
    );
    CREATE TABLE ref_dose_limits(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        ingredient_key TEXT NOT NULL, route TEXT,
        min_age_years REAL, max_age_years REAL,
        max_single REAL, max_daily REAL,
        unit TEXT NOT NULL, per_kg INTEGER NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '', source_citation TEXT NOT NULL
    );
    CREATE TABLE ref_age_warnings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        subject_type TEXT NOT NULL, subject_key TEXT NOT NULL,
        min_age_years REAL, max_age_years REAL,
        severity TEXT NOT NULL CHECK (severity IN ('contraindicated','major','moderate','minor')),
        message TEXT NOT NULL, management TEXT NOT NULL DEFAULT '', source_citation TEXT NOT NULL
    );
    CREATE TABLE ref_allergy_cross(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id TEXT NOT NULL REFERENCES ref_datasets(id) ON DELETE CASCADE,
        allergen_type TEXT NOT NULL, allergen_key TEXT NOT NULL,
        drug_type TEXT NOT NULL, drug_key TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('contraindicated','major','moderate','minor')),
        note TEXT NOT NULL, source_citation TEXT NOT NULL
    );
    """,
]


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.db_path()), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA secure_delete = ON")  # overwrite deleted content
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def init_db(conn: sqlite3.Connection) -> int:
    """Create or upgrade the schema. Each migration runs inside one transaction."""
    current = schema_version(conn)
    if current > len(MIGRATIONS):
        raise RuntimeError(
            f"Database schema v{current} is newer than this application supports (v{len(MIGRATIONS)})."
        )
    for i in range(current, len(MIGRATIONS)):
        try:
            conn.executescript("BEGIN;\n" + MIGRATIONS[i] + f"\nPRAGMA user_version = {i + 1};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return schema_version(conn)


@contextmanager
def tx(conn: sqlite3.Connection):
    """Explicit transaction helper: commit on success, rollback on error."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
