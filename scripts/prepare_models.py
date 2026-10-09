"""Provision local AI models. RUN THIS WHILE ONLINE, BEFORE CLINICAL USE.

    python scripts/prepare_models.py                       # whisper "small" + llama3.2:3b
    python scripts/prepare_models.py --whisper base        # smaller/faster speech model
    python scripts/prepare_models.py --llm phi3.5          # alternative LLM
    python scripts/prepare_models.py --skip-llm

The operational app never downloads anything; it only reads what this script installs.

Model notes (verify licences for your deployment):
  * faster-whisper models (Systran/faster-whisper-*): MIT-licensed conversions of OpenAI Whisper (MIT).
  * llama3.2:3b (Llama 3.2 Community License) ~2 GB; phi3.5 (MIT) ~2.2 GB.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["RHUSCRIBE_ALLOW_NETWORK"] = "1"
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)


def whisper(size: str) -> bool:
    from huggingface_hub import snapshot_download

    dest = ROOT / "models" / "whisper" / size
    print(f"[whisper] downloading Systran/faster-whisper-{size} -> {dest}")
    snapshot_download(repo_id=f"Systran/faster-whisper-{size}", local_dir=str(dest))
    ok = (dest / "model.bin").exists()
    print("[whisper] OK" if ok else "[whisper] FAILED: model.bin missing")
    return ok


def find_ollama() -> str | None:
    p = shutil.which("ollama")
    if p:
        return p
    for cand in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe", Path("/usr/local/bin/ollama")):
        if cand.exists():
            return str(cand)
    return None


def llm(model: str, install: bool) -> bool:
    exe = find_ollama()
    if not exe and install and sys.platform == "win32":
        print("[llm] installing Ollama with winget ...")
        subprocess.run(["winget", "install", "-e", "--id", "Ollama.Ollama", "--accept-package-agreements", "--accept-source-agreements"], check=False)
        exe = find_ollama()
    if not exe:
        print("[llm] Ollama is not installed. Install from https://ollama.com/download (or re-run with --install-ollama on Windows).")
        return False
    print(f"[llm] pulling {model} with {exe}")
    r = subprocess.run([exe, "pull", model])
    print("[llm] OK" if r.returncode == 0 else "[llm] FAILED (is the Ollama service running? try `ollama serve`)")
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", default="small", choices=["tiny", "base", "small", "medium"])
    ap.add_argument("--llm", default="llama3.2:3b")
    ap.add_argument("--skip-whisper", action="store_true")
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--install-ollama", action="store_true", help="try to install Ollama via winget (Windows)")
    a = ap.parse_args()
    ok = True
    if not a.skip_whisper:
        ok &= whisper(a.whisper)
    if not a.skip_llm:
        ok &= llm(a.llm, a.install_ollama)
    print("\nDone." if ok else "\nFinished with problems - see messages above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
