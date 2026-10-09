# Lokal.MD — offline clinical consultation & prescription-review assistant

> **AppBuildersPH Hackathon 2026 Submission** · **Theme: Local AI (On-Device Inference)**  
> *"An AI product that remains genuinely useful when the cloud disappears."*

A local-first, air-gapped documentation aid for Rural Health Units (RHUs), barangay health stations, and disaster-response teams in the Philippines. Runs on one ordinary laptop; **no cloud AI, no telemetry, no API bills**. Patient health records are encrypted at rest with AES-256-GCM.

### Why Local AI is Fundamental
Under the **Philippine Data Privacy Act of 2012**, transmitting patient consultations and identifiable medical records to third-party cloud servers creates severe compliance, ethical, and security risks. Furthermore, during typhoons, natural disasters, or in remote island/mountain RHUs with zero connectivity, cloud healthcare tools fail completely. Lokal.MD runs 100% on-device: patient data never leaves the hardware, operations never stop during blackouts, and public health units incur ₱0 in subscription fees.

### AI Disclosures
- **Speech-to-Text**: `faster-whisper` (Systran/faster-whisper-base/small) running locally via CTranslate2.
- **Clinical Structuring (SOAP Notes)**: `llama3.2:3b` running on-device via local Ollama.
- **Safety Engine**: Deterministic offline SQLite rules engine checking contraindications, allergies, and dosage limits.
- **AI Development Tools**: Built using **Devin** (Cognition) + Antigravity.

> **Status: functional MVP.** Ships with a *synthetic sample* medication reference set (labelled as such on every result and PDF). It is not a certified
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
