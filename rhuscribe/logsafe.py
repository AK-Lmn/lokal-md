"""Logging that is safe by construction: only event names and opaque IDs are logged.

A redaction filter is added as a second line of defence. Callers must never pass patient
names, transcript text, note text or medication details to the logger.
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from . import config

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b(?:\+?63|0)9\d{9}\b"), "[phone]"),
    (re.compile(r"\b\d{4}-\d{4}-\d{4}\b"), "[id]"),
    (re.compile(r"(?i)(password|passphrase|key|token)\s*[=:]\s*\S+"), r"\1=[redacted]"),
]


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pat, repl in _PATTERNS:
            msg = pat.sub(repl, msg)
        record.msg, record.args = msg, ()
        if record.exc_info:
            # Tracebacks can embed values; keep type + location only.
            et, ev, tb = record.exc_info
            record.exc_text = f"{et.__name__ if et else 'Error'} (details withheld)"
            record.exc_info = None
        return True


def get_logger(name: str = "rhuscribe") -> logging.Logger:
    logger = logging.getLogger(name)
    if getattr(logger, "_rhu_configured", False):
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        fh = RotatingFileHandler(config.log_dir() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(RedactFilter())
        logger.addHandler(fh)
    except OSError:
        pass
    logger._rhu_configured = True  # type: ignore[attr-defined]
    return logger
