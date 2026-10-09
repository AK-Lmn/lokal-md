"""Paths and static configuration. Runtime-changeable options live in settings_store."""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    d = Path(os.environ.get("RHUSCRIBE_DATA_DIR", ROOT_DIR / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    return Path(os.environ.get("RHUSCRIBE_MODELS_DIR", ROOT_DIR / "models"))


def db_path() -> Path:
    return data_dir() / "rhuscribe.db"


def log_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tmp_dir() -> Path:
    d = data_dir() / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_dir() -> Path:
    d = data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


WHISPER_SIZES = ["tiny", "base", "small", "medium"]
DEFAULT_WHISPER = "small"
DEFAULT_LLM = "llama3.2:3b"
OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434

MIN_PASSWORD_LEN = 10
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 5

ENCOUNTER_STATUSES = ("open", "note_draft", "approved", "archived")
ROLES = ("admin", "clinician", "staff", "pharmacist")
