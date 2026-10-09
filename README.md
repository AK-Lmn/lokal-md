# RHU Scribe — offline clinical consultation & prescription-review assistant

A local-first documentation aid for Rural Health Units, barangay health centres and disaster-response teams in the
Philippines. Runs on one ordinary laptop; **no cloud AI, no telemetry**. Records are encrypted at rest.

> **Status: functional MVP / demonstration.** Ships with *synthetic* medication reference data. It is not a certified
> medical device and has not been assessed for Data Privacy Act or regulatory compliance. See "Limitations".

## Quick start (Windows)
```
setup.bat      # once, with internet: venv, dependencies, Whisper "small", Ollama + llama3.2:3b
run.bat        # daily use, offline; opens http://127.0.0.1:8501
```
Manual: `pip install -r requirements.txt`, `python scripts/prepare_models.py`, `streamlit run app.py`.
First launch asks you to create the administrator account and shows a one-time **recovery key**.
Tests: `python -m pytest`. Offline self-test (run with the network unplugged): `python scripts/check_offline.py`.

## What it does
| Area | Implementation |
|---|---|
| Workspace | Intake → Transcript → SOAP note → Medication safety → Review & approve, one encounter view with unsaved-change tracking |
| Speech | faster-whisper from local files (`models/whisper/<size>`); WAV/MP3/M4A/OGG/FLAC upload or browser microphone; low-confidence lines marked `[?]` and must be cleared by a human; raw audio deleted after processing unless an admin enables retention with a policy reference |
| Notes | Ollama (default `llama3.2:3b`) constrained to a JSON schema; vitals, allergies, medicines and orders are copied by code, clinician entries override the AI, every AI item is grounding-checked (numbers + wording, Tagalog glossary) and unsupported items are withheld; malformed output → retry → template fallback; notes stay **drafts** until a clinician approves |
| Medication safety | SQLite-backed deterministic rules engine (`rhuscribe/safety`), six result categories, evidence + next step per finding, clinician acknowledgement required before approval |
| Storage | SQLite + per-field AES-256-GCM, scrypt-wrapped data key per user, recovery key, hash-chained audit log, encrypted backups, restore, retention, hard delete |
| Access | Roles: admin, clinician (only role that can approve), staff, pharmacist; purpose-of-access for history; inactivity lock (auto-saves drafts, wipes session) |
| Export | ReportLab PDF with DRAFT/APPROVED banners, medication findings and approval record exactly as stored (no invented signatures) |

## Data sources
The repository contains **no third-party medication data**; only clearly-labelled synthetic demo records. A starter dataset can be
built locally from public sources (details, licences and gaps in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md)):

| Content | Source | Licence |
|---|---|---|
| Ingredient names / combination aliases | DOH Philippine National Formulary – Essential Medicines List (8th ed., as of 2 Nov 2022) | Government publication (reuse terms not stated) |
| Drug–drug interaction pairs + severity | [DDInter 2.0](https://ddinter2.scbdd.com/download/) (Xiong et al., *Nucleic Acids Res.* 2022) | **CC BY-NC-SA 4.0 – non-commercial** |
| Contraindications, paediatric age statements | [openFDA](https://open.fda.gov/) US drug labels (auto-extracted, verify) | openFDA terms |
| Dose limits, allergy cross-reactivity, drug classes, Philippine brand names | **none found – not imported** | – |

Build with `scripts/build_reference/*`, import with `python scripts/import_reference.py bundle.json`. Imported data is
"awaiting review" until a second qualified person approves it; the app stays in demonstration mode until then.
Non-commercial DDInter data must be replaced or licensed before commercial deployment.

## Design notes
* **Offline by construction:** Streamlit binds to 127.0.0.1; telemetry off; no external assets; a process-level socket guard
  refuses any non-loopback connection; models load with `local_files_only`; the Ollama client ignores proxies.
* **Encryption is not SQLite's:** SQLite is unencrypted; clinical columns are encrypted by the app. Encounter IDs, timestamps,
  status, user names, audit event names and settings remain visible to anyone with file access. Use BitLocker too.
* **Lost credentials:** if every password *and* the recovery key are lost, data cannot be recovered.

## Limitations (please read)
* Whisper/LLM make mistakes, especially with Tagalog/Taglish, accents, noise and drug names (observed in testing: "amoxicillin" heard as "a Moxicillin"). The app flags likely mis-heard drug names but cannot guarantee correctness.
* Llama 3.2 / Phi-3.5 are not officially tuned for Tagalog; Taglish notes carry an explicit "unverified translation" marker.
* Medication data are synthetic until you import and approve verified content (`docs/REFERENCE_DATA.md`).
* Single workstation, no TLS, no multi-site sync. Not tested on macOS/Linux. No speaker diarisation.
* Compliance with the Data Privacy Act of 2012 requires your own privacy impact assessment, policies, DPO review and security hardening.
