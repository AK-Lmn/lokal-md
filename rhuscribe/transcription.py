"""Local speech recognition with faster-whisper.

Models are loaded from a local directory only (models/whisper/<size>); nothing is downloaded
at runtime. Provision models with `python scripts/prepare_models.py` while online.

Low-confidence segments are prefixed with "[?] " in the transcript text so that uncertain
transcription stays visibly uncertain until a human reviews and removes the marker.
Accuracy for Tagalog/Taglish and medical terminology is limited - review every transcript.
"""
from __future__ import annotations

import importlib.util
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .logsafe import get_logger

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

log = get_logger()
UNCERTAIN_MARK = "[?] "
SUPPORTED_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".mp4", ".aac"}

_models: dict[tuple, object] = {}
_lock = threading.Lock()


class TranscriptionUnavailable(Exception):
    pass


@dataclass
class TranscriptResult:
    text: str
    language: str | None
    language_probability: float | None
    duration_s: float
    model: str
    n_uncertain: int = 0
    segments: list[dict] = field(default_factory=list)


def model_dir(size: str) -> Path:
    return config.models_dir() / "whisper" / size


def installed_models() -> list[str]:
    out = []
    for s in config.WHISPER_SIZES:
        d = model_dir(s)
        if (d / "model.bin").exists() and (d / "config.json").exists():
            out.append(s)
    return out


def status(size: str) -> dict:
    lib = importlib.util.find_spec("faster_whisper") is not None
    have = size in installed_models()
    msg = "Ready" if lib and have else (
        "faster-whisper is not installed" if not lib else f"Model '{size}' not found in models/whisper - run scripts/prepare_models.py while online"
    )
    return {"library": lib, "model_present": have, "ready": lib and have, "message": msg, "installed": installed_models()}


def has_uncertain(text: str) -> bool:
    return any(line.startswith(UNCERTAIN_MARK.strip()) for line in text.splitlines())


def count_uncertain(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith(UNCERTAIN_MARK.strip()))


def clear_uncertain_markers(text: str) -> str:
    return "\n".join(line[len(UNCERTAIN_MARK.strip()):].lstrip() if line.startswith(UNCERTAIN_MARK.strip()) else line for line in text.splitlines())


def _load(size: str, device: str, compute_type: str):
    key = (size, device, compute_type)
    with _lock:
        if key not in _models:
            st = status(size)
            if not st["ready"]:
                raise TranscriptionUnavailable(st["message"])
            from faster_whisper import WhisperModel  # imported lazily: heavy

            _models[key] = WhisperModel(str(model_dir(size)), device=device, compute_type=compute_type, local_files_only=True)
        return _models[key]


def secure_delete(path: Path) -> None:
    try:
        n = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(b"\x00" * n)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass


def transcribe_bytes(data: bytes, suffix: str, settings: dict, progress=None) -> TranscriptResult:
    """Transcribe audio held in memory. The temp file is overwritten and removed afterwards."""
    suffix = suffix.lower() if suffix.lower() in SUPPORTED_SUFFIXES else ".wav"
    tmp = config.tmp_dir() / f"aud_{os.urandom(8).hex()}{suffix}"
    try:
        tmp.write_bytes(data)
        return transcribe_file(tmp, settings, progress)
    finally:
        secure_delete(tmp)


def transcribe_file(path: Path, settings: dict, progress=None) -> TranscriptResult:
    size = settings.get("whisper_model", config.DEFAULT_WHISPER)
    model = _load(size, settings.get("whisper_device", "cpu"), settings.get("whisper_compute_type", "int8"))
    lang = settings.get("whisper_language", "auto")
    try:
        segments, info = model.transcribe(  # type: ignore[attr-defined]
            str(path), language=None if lang == "auto" else lang, beam_size=5, vad_filter=True, condition_on_previous_text=False,
        )
        lines, segs, n_unc = [], [], 0
        for s in segments:
            txt = s.text.strip()
            if not txt:
                continue
            uncertain = s.avg_logprob < -1.0 or s.no_speech_prob > 0.6 or s.compression_ratio > 2.4
            n_unc += uncertain
            lines.append((UNCERTAIN_MARK if uncertain else "") + txt)
            segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "uncertain": bool(uncertain)})
            if progress and info.duration:
                progress(min(1.0, s.end / info.duration))
    except TranscriptionUnavailable:
        raise
    except Exception as e:  # decoder errors, corrupt audio, etc.
        log.warning("transcription failed: %s", type(e).__name__)
        raise TranscriptionUnavailable(f"Audio could not be processed ({type(e).__name__}). The file may be corrupt or in an unsupported format.") from e
    if not lines:
        raise TranscriptionUnavailable("No speech was detected in the audio.")
    return TranscriptResult("\n".join(lines), info.language, float(info.language_probability), float(info.duration), f"faster-whisper/{size}", n_unc, segs)
