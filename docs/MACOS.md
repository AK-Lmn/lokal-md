# Running RHU Scribe on macOS

> **Untested.** RHU Scribe was built and tested on Windows 11 only. The steps below should work on macOS
> (Python, Streamlit, SQLite, faster-whisper and Ollama all support it) but have not been verified on a Mac.
> The `setup.bat` / `run.bat` launchers are Windows-only; use the commands here instead.

## Requirements

- macOS 12 or newer. Apple Silicon (M1 or later) is recommended; Intel Macs work but are slower.
- 8 GB RAM minimum, 16 GB comfortable. About 5 GB free disk (Python packages ~1 GB, Whisper "small" ~0.5 GB, `llama3.2:3b` ~2 GB).
- Internet is needed **once**, for installation. Afterwards the app runs offline.

## 1. Install the prerequisites (needs internet)

1. **Python 3.11 or newer.** Check with `python3 --version`. If needed, install from https://www.python.org/downloads/ or `brew install python@3.12`.
2. **Ollama** (runs the local language model). Download from https://ollama.com/download, or `brew install ollama`.

## 2. Install the app (needs internet)

Open Terminal in the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Download the AI models (needs internet)

Start Ollama (the desktop app, or `ollama serve` in a second Terminal window), then:

```bash
python scripts/prepare_models.py
```

This downloads Whisper "small" into `models/whisper/` and pulls `llama3.2:3b`.
On a Mac, `prepare_models.py` cannot install Ollama for you (step 1 does that); it only pulls the model.
Smaller/faster speech model: `python scripts/prepare_models.py --whisper base`.

## 4. Run the app (works offline)

```bash
source .venv/bin/activate
ollama serve &              # skip if the Ollama app is already running
streamlit run app.py
```

Open http://127.0.0.1:8501 in Safari, Chrome or Edge. The first launch asks you to create the administrator account and
shows a one-time recovery key. Then follow the normal flow described in the README (create a clinician account, etc.).

## 5. Verify offline use

Turn Wi-Fi off, then run:

```bash
python scripts/check_offline.py
```

Every line should say `PASS` (speech and LLM checks say `SKIPPED` if those models are not installed).

## Things to watch for on a Mac

- **Microphone:** the browser asks for permission the first time you record. If it is blocked, allow it in
  System Settings → Privacy & Security → Microphone, and in the browser's site settings. Safari is stricter than Chrome/Edge;
  if recording fails, upload an audio file instead (this always works).
- **Speed:** transcription runs on the CPU (`int8`). A 1-minute recording may take a minute or more on older machines.
  Note generation uses Ollama, which uses the Apple GPU automatically on Apple Silicon.
- **Package install errors:** if `pip install` fails on `av`, `ctranslate2` or `onnxruntime`, update pip
  (`pip install --upgrade pip`) and retry; make sure you are on a 64-bit Python (arm64 on Apple Silicon).
- **Firewall prompt:** macOS may ask whether Python may accept incoming connections. The app only listens on 127.0.0.1;
  you can answer "Deny" safely.
- **After code changes** restart `streamlit run app.py` (file watching is disabled on purpose).

## Optional launcher script

Save as `run.sh` in the project folder, then `chmod +x run.sh` and `./run.sh`:

```bash
#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
pgrep -x ollama >/dev/null || (ollama serve >/dev/null 2>&1 &)
open http://127.0.0.1:8501
streamlit run app.py
```

If something fails, copy the full error text into an issue or message so it can be fixed; macOS support is not yet confirmed.
