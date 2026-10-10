# Lokal.MD — Local Intelligence for Local Clinics

<p align="center">
  <img src="static/logo.svg" width="96" alt="Lokal.MD Logo" /><br />
  <b>"Local intelligence for local clinics."</b><br />
  <i>Offline clinical consultation, Taglish speech transcription & medication safety-review assistant.</i>
</p>

---

> **AppBuildersPH Hackathon 2026 Submission** · **Theme: Local AI (On-Device Inference)**  
> *"An AI healthcare product that remains genuinely useful when the cloud disappears."*

A local-first, air-gapped clinical documentation and medication safety workstation designed for Rural Health Units (RHUs), barangay health stations, and disaster-response medical missions across the Philippines. Runs entirely on an ordinary laptop or workstation; **no cloud AI, no telemetry, no subscription bills**. All patient health records are encrypted at rest with AES-256-GCM.

### Why Local AI is Fundamental
Under the **Philippine Data Privacy Act of 2012 (DPA)**, transmitting patient consultations and identifiable medical records to third-party cloud servers creates severe compliance, ethical, and privacy risks. Furthermore, during typhoons, natural disasters, or in remote island/mountain RHUs with zero connectivity, cloud healthcare tools fail completely. Lokal.MD runs 100% on-device: patient data never leaves the hardware, operations never stop during blackouts, and public health units incur ₱0 in subscription fees.

### AI Disclosures
- **Speech-to-Text**: `faster-whisper` (Systran/faster-whisper-base/small) running locally via CTranslate2.
- **Clinical Structuring (SOAP Notes)**: `llama3.2:3b` running on-device via local Ollama.
- **Safety Engine**: Deterministic offline SQLite rules engine checking contraindications, allergies, and dosage limits against the Philippine National Formulary (PNF) standards.
- **AI Development Tools**: Built using **Devin** (Cognition) + Antigravity.

> **Status: functional MVP.** Ships with a *synthetic sample* medication reference set (labelled as such on every result and PDF). It is not a certified medical device and has not been assessed for Data Privacy Act or regulatory compliance. See "Limitations".

---

## ⚡ Quick Start

### Windows
```cmd
setup.bat      # once, with internet: creates venv, downloads dependencies, Whisper & Ollama
run.bat        # daily use, 100% offline; opens http://127.0.0.1:8501
```

### macOS & Linux
```bash
# 1. Setup virtual environment and dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Prepare local models (one-time while online)
python scripts/prepare_models.py

# 3. Launch application (100% offline)
streamlit run app.py
```

- First launch prompts you to create the clinic administrator account and securely presents a one-time **master recovery key**.
- Run automated tests: `pytest` (94 passing tests).
- Offline air-gap self-test: `python scripts/check_offline.py`.

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
