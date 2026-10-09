"""Persistence layer: encounters, transcripts, orders, notes, reviews, audio.

All clinical content is encrypted per-field via the Vault; relationships are enforced by
foreign keys; every state-changing/sensitive operation writes an audit event whose detail
contains only IDs and statuses.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from . import audit
from .auth import can
from .crypto import Vault
from .schemas import EncounterData, MedicationOrder, SOAPNote
from .timeutil import now_iso

_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class PermissionDenied(Exception):
    pass


class Conflict(Exception):
    pass


def new_encounter_id() -> str:
    suffix = "".join(secrets.choice(_ID_ALPHABET) for _ in range(5))
    return f"ENC-{datetime.now().strftime('%Y%m%d')}-{suffix}"


def content_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class Store:
    def __init__(self, conn: sqlite3.Connection, vault: Vault, user: dict):
        self.conn, self.v, self.user = conn, vault, user

    # ----------------------------------------------------------------- helpers
    def _need(self, perm: str) -> None:
        if not can(self.user, perm):
            raise PermissionDenied(f"Your role cannot perform this action ({perm}).")

    def _audit(self, action, target_type=None, target_id=None, detail=None):
        audit.record(self.conn, self.user, action, target_type, target_id, detail)

    def _load_enc_row(self, enc_id: str) -> sqlite3.Row:
        r = self.conn.execute("SELECT * FROM encounters WHERE id=?", (enc_id,)).fetchone()
        if not r:
            raise KeyError(f"Encounter {enc_id} not found")
        return r

    def _decode_enc(self, r: sqlite3.Row) -> dict:
        data = EncounterData.model_validate(self.v.decrypt_json(r["data_enc"], "encounters", "data", r["id"]))
        return {
            "id": r["id"], "status": r["status"], "data": data, "patient_ref": data.patient_ref,
            "created_at": r["created_at"], "updated_at": r["updated_at"],
            "created_by": r["created_by"], "updated_by": r["updated_by"],
        }

    # ----------------------------------------------------------------- encounters
    def create_encounter(self, data: EncounterData) -> str:
        self._need("encounter.create")
        if not data.patient_ref.strip():
            raise ValueError("A patient reference is required (use a pseudonymous code, not a name).")
        now = now_iso()
        for _ in range(5):
            eid = new_encounter_id()
            if not self.conn.execute("SELECT 1 FROM encounters WHERE id=?", (eid,)).fetchone():
                break
        self.conn.execute(
            "INSERT INTO encounters(id,patient_idx,status,data_enc,created_at,updated_at,created_by,updated_by)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (eid, self.v.blind_index(data.patient_ref), "open", self.v.encrypt_json(data.model_dump(), "encounters", "data", eid),
             now, now, self.user["id"], self.user["id"]),
        )
        self.conn.commit()
        self._audit("encounter.created", "encounter", eid)
        return eid

    def get_encounter(self, enc_id: str, *, audit_view: bool = False) -> dict:
        self._need("encounter.view")
        d = self._decode_enc(self._load_enc_row(enc_id))
        if audit_view:
            self._audit("encounter.viewed", "encounter", enc_id)
        return d

    def update_encounter(self, enc_id: str, data: EncounterData) -> None:
        self._need("encounter.edit")
        r = self._load_enc_row(enc_id)
        if r["status"] in ("approved", "archived"):
            raise Conflict("This encounter is approved/archived and locked. Start an amendment to change it.")
        if not data.patient_ref.strip():
            raise ValueError("A patient reference is required.")
        self.conn.execute(
            "UPDATE encounters SET patient_idx=?, data_enc=?, updated_at=?, updated_by=? WHERE id=?",
            (self.v.blind_index(data.patient_ref), self.v.encrypt_json(data.model_dump(), "encounters", "data", enc_id),
             now_iso(), self.user["id"], enc_id),
        )
        self.conn.commit()
        self._audit("encounter.updated", "encounter", enc_id)

    def set_status(self, enc_id: str, status: str) -> None:
        self.conn.execute("UPDATE encounters SET status=?, updated_at=?, updated_by=? WHERE id=?", (status, now_iso(), self.user["id"], enc_id))
        self.conn.commit()

    def list_encounters(self, *, status: str | None = None, query: str = "", limit: int = 500, deep: bool = False) -> list[dict]:
        self._need("encounter.list_meta")
        sql, args = "SELECT * FROM encounters", []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit * 4 if query else limit)
        rows = self.conn.execute(sql, args).fetchall()
        phi_ok = can(self.user, "encounter.view")
        out = []
        q = query.strip().lower()
        for r in rows:
            item = {"id": r["id"], "status": r["status"], "created_at": r["created_at"], "updated_at": r["updated_at"], "patient_ref": "(restricted)", "chief_complaint": "", "diagnosis": ""}
            if phi_ok:
                d = self._decode_enc(r)["data"]
                item.update(patient_ref=d.patient_ref, chief_complaint=d.inputs.chief_complaint, diagnosis=d.inputs.working_diagnosis, name=d.profile.display_name)
                hay = " ".join([r["id"], d.patient_ref, d.profile.display_name, d.inputs.chief_complaint, d.inputs.working_diagnosis]).lower()
                if deep:
                    hay += " " + (self.get_transcript_text(r["id"]) or "").lower()
                    n = self.get_draft_or_latest_note(r["id"])
                    if n:
                        hay += " " + n["note"].to_text().lower()
            else:
                hay = r["id"].lower()
            if not q or q in hay:
                out.append(item)
            if len(out) >= limit:
                break
        return out

    def encounters_for_patient(self, patient_ref: str) -> list[str]:
        idx = self.v.blind_index(patient_ref)
        return [r["id"] for r in self.conn.execute("SELECT id FROM encounters WHERE patient_idx=? ORDER BY created_at DESC", (idx,))]

    def delete_encounter(self, enc_id: str) -> None:
        self._need("encounter.delete")
        self._load_enc_row(enc_id)
        self.conn.execute("DELETE FROM encounters WHERE id=?", (enc_id,))  # cascades to children
        self.conn.commit()
        self._audit("encounter.deleted", "encounter", enc_id)

    def archive_encounter(self, enc_id: str) -> None:
        self._need("encounter.archive")
        self.set_status(enc_id, "archived")
        self._audit("encounter.archived", "encounter", enc_id)

    # ----------------------------------------------------------------- transcript
    def get_transcript(self, enc_id: str) -> dict | None:
        self._need("encounter.view")
        r = self.conn.execute("SELECT * FROM transcripts WHERE encounter_id=?", (enc_id,)).fetchone()
        if not r:
            return None
        return {
            "text": self.v.decrypt_text(r["text_enc"], "transcripts", "text", enc_id) or "",
            "source": r["source"], "status": r["status"], "language": r["language"], "asr_model": r["asr_model"],
            "updated_at": r["updated_at"], "reviewed_by": r["reviewed_by"], "reviewed_at": r["reviewed_at"],
        }

    def get_transcript_text(self, enc_id: str) -> str:
        t = self.get_transcript(enc_id)
        return t["text"] if t else ""

    def save_transcript(self, enc_id: str, text: str, *, source: str, language: str | None = None, asr_model: str | None = None, reviewed: bool = False) -> None:
        """Saving edited text always resets review status unless explicitly marked reviewed."""
        self._need("transcript.edit")
        r = self._load_enc_row(enc_id)
        if r["status"] in ("approved", "archived"):
            raise Conflict("Encounter is locked.")
        status = "reviewed" if reviewed else "unreviewed"
        now = now_iso()
        enc = self.v.encrypt_text(text, "transcripts", "text", enc_id)
        self.conn.execute(
            "INSERT INTO transcripts(encounter_id,text_enc,source,status,language,asr_model,updated_at,reviewed_by,reviewed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(encounter_id) DO UPDATE SET text_enc=excluded.text_enc,"
            " source=excluded.source, status=excluded.status, language=excluded.language, asr_model=excluded.asr_model,"
            " updated_at=excluded.updated_at, reviewed_by=excluded.reviewed_by, reviewed_at=excluded.reviewed_at",
            (enc_id, enc, source, status, language, asr_model, now, self.user["id"] if reviewed else None, now if reviewed else None),
        )
        self.conn.commit()
        self._audit("transcript.saved", "encounter", enc_id, {"source": source, "status": status})

    def delete_transcript(self, enc_id: str) -> None:
        self.conn.execute("DELETE FROM transcripts WHERE encounter_id=?", (enc_id,))
        self.conn.commit()
        self._audit("transcript.deleted", "encounter", enc_id)

    # ----------------------------------------------------------------- orders
    def get_orders(self, enc_id: str) -> list[MedicationOrder]:
        self._need("encounter.view")
        out = []
        for r in self.conn.execute("SELECT * FROM medication_orders WHERE encounter_id=? ORDER BY seq", (enc_id,)):
            o = MedicationOrder.model_validate(self.v.decrypt_json(r["data_enc"], "medication_orders", "data", r["id"]))
            o.id = r["id"]
            out.append(o)
        return out

    def save_orders(self, enc_id: str, orders: list[MedicationOrder]) -> list[MedicationOrder]:
        """Replace the encounter's orders with the clinician-entered list."""
        self._need("encounter.edit")
        r = self._load_enc_row(enc_id)
        if r["status"] in ("approved", "archived"):
            raise Conflict("Encounter is locked.")
        now = now_iso()
        existing = {x["id"] for x in self.conn.execute("SELECT id FROM medication_orders WHERE encounter_id=?", (enc_id,))}
        keep = set()
        saved = []
        for i, o in enumerate(orders):
            if not o.drug_name.strip():
                continue
            oid = o.id if o.id in existing else str(uuid.uuid4())
            o = o.model_copy(update={"id": oid})
            payload = self.v.encrypt_json(o.model_dump(exclude={"id"}), "medication_orders", "data", oid)
            if oid in existing:
                self.conn.execute("UPDATE medication_orders SET seq=?, data_enc=?, updated_at=? WHERE id=?", (i, payload, now, oid))
            else:
                self.conn.execute(
                    "INSERT INTO medication_orders(id,encounter_id,seq,data_enc,entered_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (oid, enc_id, i, payload, self.user["id"], now, now),
                )
            keep.add(oid)
            saved.append(o)
        for gone in existing - keep:
            self.conn.execute("DELETE FROM medication_orders WHERE id=?", (gone,))
        self.conn.commit()
        self._audit("orders.saved", "encounter", enc_id, {"count": len(saved)})
        return saved

    # ----------------------------------------------------------------- notes
    def _note_from_row(self, r: sqlite3.Row) -> dict:
        note = SOAPNote.model_validate(self.v.decrypt_json(r["content_enc"], "note_versions", "content", r["id"]))
        snap = self.v.decrypt_json(r["approver_snapshot_enc"], "note_versions", "approver", r["id"]) if r["approver_snapshot_enc"] else None
        return {
            "id": r["id"], "encounter_id": r["encounter_id"], "version": r["version"], "status": r["status"], "note": note,
            "method": r["generation_method"], "model": r["model"], "created_at": r["created_at"], "updated_at": r["updated_at"],
            "approved_at": r["approved_at"], "approved_by": r["approved_by"], "approver": snap, "content_hash": r["content_hash"],
        }

    def get_draft(self, enc_id: str) -> dict | None:
        self._need("encounter.view")
        r = self.conn.execute("SELECT * FROM note_versions WHERE encounter_id=? AND status='draft'", (enc_id,)).fetchone()
        return self._note_from_row(r) if r else None

    def get_approved(self, enc_id: str) -> dict | None:
        self._need("encounter.view")
        r = self.conn.execute(
            "SELECT * FROM note_versions WHERE encounter_id=? AND status='approved' ORDER BY version DESC LIMIT 1", (enc_id,)
        ).fetchone()
        return self._note_from_row(r) if r else None

    def get_draft_or_latest_note(self, enc_id: str) -> dict | None:
        return self.get_draft(enc_id) or self.get_approved(enc_id)

    def list_versions(self, enc_id: str) -> list[dict]:
        self._need("encounter.view")
        return [
            {"version": r["version"], "status": r["status"], "created_at": r["created_at"], "approved_at": r["approved_at"], "id": r["id"]}
            for r in self.conn.execute("SELECT * FROM note_versions WHERE encounter_id=? ORDER BY version DESC", (enc_id,))
        ]

    def get_version(self, note_id: str) -> dict:
        self._need("encounter.view")
        r = self.conn.execute("SELECT * FROM note_versions WHERE id=?", (note_id,)).fetchone()
        if not r:
            raise KeyError(note_id)
        return self._note_from_row(r)

    def save_draft(self, enc_id: str, note: SOAPNote, *, method: str, model: str | None = None) -> str:
        """Create or overwrite the single editable draft. Approved text is never modified."""
        self._need("note.edit")
        r = self._load_enc_row(enc_id)
        if r["status"] == "archived":
            raise Conflict("Encounter is archived.")
        if r["status"] == "approved":
            raise Conflict("Encounter is approved. Start an amendment to edit.")
        now = now_iso()
        cur = self.conn.execute("SELECT id FROM note_versions WHERE encounter_id=? AND status='draft'", (enc_id,)).fetchone()
        if cur:
            nid = cur["id"]
            self.conn.execute(
                "UPDATE note_versions SET content_enc=?, generation_method=?, model=?, updated_at=? WHERE id=?",
                (self.v.encrypt_json(note.model_dump(), "note_versions", "content", nid), method, model, now, nid),
            )
        else:
            nid = str(uuid.uuid4())
            ver = (self.conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM note_versions WHERE encounter_id=?", (enc_id,)).fetchone()[0])
            self.conn.execute(
                "INSERT INTO note_versions(id,encounter_id,version,status,content_enc,generation_method,model,created_by,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (nid, enc_id, ver, "draft", self.v.encrypt_json(note.model_dump(), "note_versions", "content", nid), method, model, self.user["id"], now, now),
            )
        self.conn.commit()
        if r["status"] == "open":
            self.set_status(enc_id, "note_draft")
        self._audit("note.draft_saved", "encounter", enc_id, {"method": method})
        return nid

    def approve_note(self, enc_id: str, *, review_id: str | None, attestation: str) -> dict:
        """Approve the current draft. The approver snapshot is taken from the user record as
        entered; nothing is invented (blank credentials stay blank)."""
        self._need("note.approve")
        draft = self.get_draft(enc_id)
        if not draft:
            raise Conflict("There is no draft note to approve.")
        now = now_iso()
        snapshot = {
            "name": self.user["display_name"], "username": self.user["username"],
            "credentials": self.user.get("credentials", ""), "license_no": self.user.get("license_no", ""),
            "attestation": attestation, "review_id": review_id,
        }
        h = content_hash({"note": draft["note"].model_dump(), "review": review_id, "orders": [o.model_dump(exclude={"id"}) for o in self.get_orders(enc_id)]})
        self.conn.execute("UPDATE note_versions SET status='superseded' WHERE encounter_id=? AND status='approved'", (enc_id,))
        self.conn.execute(
            "UPDATE note_versions SET status='approved', approved_by=?, approved_at=?, approver_snapshot_enc=?, content_hash=?, updated_at=? WHERE id=?",
            (self.user["id"], now, self.v.encrypt_json(snapshot, "note_versions", "approver", draft["id"]), h, now, draft["id"]),
        )
        self.conn.commit()
        self.set_status(enc_id, "approved")
        self._audit("note.approved", "encounter", enc_id, {"version": draft["version"], "review_id": review_id})
        return self.get_approved(enc_id)  # type: ignore[return-value]

    def start_amendment(self, enc_id: str) -> None:
        """Re-open an approved encounter: copies the approved note into a new draft version."""
        self._need("note.approve")
        appr = self.get_approved(enc_id)
        if not appr:
            raise Conflict("No approved note to amend.")
        if self.get_draft(enc_id):
            return
        r = self._load_enc_row(enc_id)
        if r["status"] == "archived":
            raise Conflict("Encounter is archived.")
        self.set_status(enc_id, "open")
        self.save_draft(enc_id, appr["note"], method="manual")
        self._audit("note.amendment_started", "encounter", enc_id, {"from_version": appr["version"]})

    def discard_draft(self, enc_id: str) -> None:
        self._need("note.edit")
        self.conn.execute("DELETE FROM note_versions WHERE encounter_id=? AND status='draft'", (enc_id,))
        self.conn.commit()
        has_appr = self.conn.execute("SELECT 1 FROM note_versions WHERE encounter_id=? AND status='approved'", (enc_id,)).fetchone()
        self.set_status(enc_id, "approved" if has_appr else "open")
        self._audit("note.draft_discarded", "encounter", enc_id)

    # ----------------------------------------------------------------- medication reviews
    def save_review(self, enc_id: str, result: dict, input_hash: str, dataset_id: str | None, overall: str) -> str:
        self._need("medreview.run")
        rid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO med_reviews(id,encounter_id,input_hash,dataset_id,overall,result_enc,run_at,run_by) VALUES (?,?,?,?,?,?,?,?)",
            (rid, enc_id, input_hash, dataset_id, overall, self.v.encrypt_json(result, "med_reviews", "result", rid), now_iso(), self.user["id"]),
        )
        self.conn.commit()
        self._audit("medreview.run", "encounter", enc_id, {"overall": overall, "review_id": rid})
        return rid

    def latest_review(self, enc_id: str) -> dict | None:
        self._need("encounter.view")
        r = self.conn.execute("SELECT * FROM med_reviews WHERE encounter_id=? ORDER BY run_at DESC, rowid DESC LIMIT 1", (enc_id,)).fetchone()
        if not r:
            return None
        return self._review_from_row(r)

    def get_review(self, review_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM med_reviews WHERE id=?", (review_id,)).fetchone()
        return self._review_from_row(r) if r else None

    def _review_from_row(self, r) -> dict:
        res = self.v.decrypt_json(r["result_enc"], "med_reviews", "result", r["id"])
        acks = {}
        for a in self.conn.execute("SELECT * FROM review_acks WHERE review_id=?", (r["id"],)):
            acks[a["finding_key"]] = {
                "reason": self.v.decrypt_text(a["reason_enc"], "review_acks", "reason", a["id"]),
                "user_id": a["user_id"], "at": a["created_at"],
            }
        return {"id": r["id"], "encounter_id": r["encounter_id"], "input_hash": r["input_hash"], "dataset_id": r["dataset_id"],
                "overall": r["overall"], "result": res, "run_at": r["run_at"], "run_by": r["run_by"], "acks": acks}

    def acknowledge_finding(self, review_id: str, finding_key: str, reason: str) -> None:
        self._need("medreview.ack")
        if len(reason.strip()) < 5:
            raise ValueError("A short reason is required to acknowledge a safety finding.")
        aid = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO review_acks(id,review_id,finding_key,user_id,reason_enc,created_at) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(review_id,finding_key) DO UPDATE SET reason_enc=excluded.reason_enc, user_id=excluded.user_id, created_at=excluded.created_at",
            (aid, review_id, finding_key, self.user["id"], self.v.encrypt_text(reason.strip(), "review_acks", "reason", aid), now_iso()),
        )
        # on conflict the row keeps its original id, so re-encrypt with that id's AAD
        row = self.conn.execute("SELECT id FROM review_acks WHERE review_id=? AND finding_key=?", (review_id, finding_key)).fetchone()
        if row["id"] != aid:
            self.conn.execute("UPDATE review_acks SET reason_enc=? WHERE id=?", (self.v.encrypt_text(reason.strip(), "review_acks", "reason", row["id"]), row["id"]))
        self.conn.commit()
        self._audit("medreview.acknowledged", "review", review_id, {"finding": finding_key[:40]})

    # ----------------------------------------------------------------- audio (only if policy allows)
    def store_audio(self, enc_id: str, data: bytes, mime: str, days: int, policy_ref: str) -> str:
        aid = str(uuid.uuid4())
        exp = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
        blob = self.v.encrypt_bytes(data, self.v.aad("audio_files", "blob", aid))
        self.conn.execute(
            "INSERT INTO audio_files(id,encounter_id,blob_enc,mime,size,policy_ref,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (aid, enc_id, blob, mime, len(data), policy_ref, now_iso(), exp),
        )
        self.conn.commit()
        self._audit("audio.retained", "encounter", enc_id, {"days": days, "policy": policy_ref[:60]})
        return aid

    def list_audio(self, enc_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT id,mime,size,created_at,expires_at,policy_ref FROM audio_files WHERE encounter_id=?", (enc_id,))]

    def get_audio(self, audio_id: str) -> bytes:
        self._need("encounter.view")
        r = self.conn.execute("SELECT blob_enc FROM audio_files WHERE id=?", (audio_id,)).fetchone()
        self._audit("audio.accessed", "audio", audio_id)
        return self.v.decrypt_bytes(bytes(r["blob_enc"]), self.v.aad("audio_files", "blob", audio_id))

    def purge_expired_audio(self) -> int:
        cur = self.conn.execute("DELETE FROM audio_files WHERE expires_at IS NOT NULL AND expires_at < ?", (now_iso(),))
        self.conn.commit()
        if cur.rowcount:
            self._audit("audio.purged_expired", None, None, {"count": cur.rowcount})
        return cur.rowcount

    def delete_audio_for(self, enc_id: str) -> int:
        cur = self.conn.execute("DELETE FROM audio_files WHERE encounter_id=?", (enc_id,))
        self.conn.commit()
        if cur.rowcount:
            self._audit("audio.deleted", "encounter", enc_id, {"count": cur.rowcount})
        return cur.rowcount

    # ----------------------------------------------------------------- dashboard
    def counts(self) -> dict:
        c = self.conn
        q = lambda s, *a: c.execute(s, a).fetchone()[0]  # noqa: E731
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "total": q("SELECT COUNT(*) FROM encounters"),
            "open": q("SELECT COUNT(*) FROM encounters WHERE status='open'"),
            "drafts": q("SELECT COUNT(*) FROM encounters WHERE status='note_draft'"),
            "approved": q("SELECT COUNT(*) FROM encounters WHERE status='approved'"),
            "today": q("SELECT COUNT(*) FROM encounters WHERE date(created_at, 'localtime')=?", today),
        }
