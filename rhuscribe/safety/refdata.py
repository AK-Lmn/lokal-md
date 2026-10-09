"""Medication reference data: validated bundle format, SQLite persistence, import/review.

The software ships ONLY clearly-labelled synthetic sample data (demo_data.py).
Verified pharmaceutical content must be imported by authorised staff and approved by a
second professional before it can back real patient-care workflows.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .. import audit
from ..auth import can
from ..timeutil import now_iso
from .normalize import norm_text

Severity = Literal["contraindicated", "major", "moderate", "minor"]
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,60}$")


class RefError(Exception):
    pass


def _key(v: str) -> str:
    v = (v or "").strip().lower().replace(" ", "_")
    if not KEY_RE.match(v):
        raise ValueError(f"invalid key '{v}' (use lowercase letters, digits, _ or -)")
    return v


def _subject(v: str) -> str:
    """'class:nsaid' or an ingredient key."""
    v = (v or "").strip().lower()
    if v.startswith("class:"):
        return "class:" + _key(v[6:])
    return _key(v.removeprefix("ingredient:"))


def split_subject(s: str) -> tuple[str, str]:
    return ("class", s[6:]) if s.startswith("class:") else ("ingredient", s)


def _cite(v: str) -> str:
    if not v or not v.strip():
        raise ValueError("source_citation is required for every record")
    return v.strip()


class ClassDef(BaseModel):
    key: str
    name: str
    aliases: list[str] = []
    chk_k = field_validator("key")(_key)


class IngredientDef(BaseModel):
    key: str
    name: str
    classes: list[str] = []
    aliases: list[str] = []
    brands: list[str] = []
    chk_k = field_validator("key")(_key)


class ProductDef(BaseModel):
    """Combination product: one name that expands to several ingredients."""
    name: str
    brands: list[str] = []
    ingredients: list[str]
    @field_validator("ingredients")
    @classmethod
    def _ing(cls, v):
        if len(v) < 2:
            raise ValueError("a product needs at least two ingredients")
        return [_key(x) for x in v]


class InteractionDef(BaseModel):
    a: str
    b: str
    severity: Severity
    effect: str
    management: str
    source_citation: str
    chk_a = field_validator("a", "b")(_subject)
    chk_c = field_validator("source_citation")(_cite)


class ContraDef(BaseModel):
    subject: str
    condition_terms: list[str]
    severity: Severity
    note: str
    management: str = ""
    source_citation: str
    chk_s = field_validator("subject")(_subject)
    chk_c = field_validator("source_citation")(_cite)

    @field_validator("condition_terms")
    @classmethod
    def _t(cls, v):
        v = [norm_text(x) for x in v if norm_text(x)]
        if not v:
            raise ValueError("condition_terms must not be empty")
        return v


class DoseLimitDef(BaseModel):
    ingredient: str
    route: str = ""
    min_age_years: float | None = None
    max_age_years: float | None = None
    max_single: float | None = None
    max_daily: float | None = None
    unit: str = "mg"
    per_kg: bool = False
    note: str = ""
    source_citation: str
    chk_i = field_validator("ingredient")(_key)
    chk_c = field_validator("source_citation")(_cite)

    @model_validator(mode="after")
    def _chk(self):
        if self.max_single is None and self.max_daily is None:
            raise ValueError("dose limit needs max_single and/or max_daily")
        if self.unit not in ("mg", "g", "mcg"):
            raise ValueError("unit must be mg, g or mcg (per-kg limits: set per_kg true)")
        return self


class AgeWarningDef(BaseModel):
    subject: str
    min_age_years: float | None = None
    max_age_years: float | None = None
    severity: Severity
    message: str
    management: str = ""
    source_citation: str
    chk_s = field_validator("subject")(_subject)
    chk_c = field_validator("source_citation")(_cite)


class AllergyCrossDef(BaseModel):
    allergen: str
    drug: str
    severity: Severity = "moderate"
    note: str
    source_citation: str
    chk_s = field_validator("allergen", "drug")(_subject)
    chk_c = field_validator("source_citation")(_cite)


class Meta(BaseModel):
    name: str
    version: str
    source_description: str = Field(min_length=3)


class Bundle(BaseModel):
    meta: Meta
    classes: list[ClassDef] = []
    ingredients: list[IngredientDef] = []
    products: list[ProductDef] = []
    interactions: list[InteractionDef] = []
    contraindications: list[ContraDef] = []
    dose_limits: list[DoseLimitDef] = []
    age_warnings: list[AgeWarningDef] = []
    allergy_cross: list[AllergyCrossDef] = []

    @model_validator(mode="after")
    def _refs(self):
        ing = {i.key for i in self.ingredients}
        cls = {c.key for c in self.classes}
        if not ing:
            raise ValueError("bundle contains no ingredients")
        problems = []
        for i in self.ingredients:
            for c in i.classes:
                if c not in cls:
                    problems.append(f"ingredient {i.key}: unknown class '{c}'")
        for p in self.products:
            for k in p.ingredients:
                if k not in ing:
                    problems.append(f"product {p.name}: unknown ingredient '{k}'")

        def chk(s: str, where: str):
            t, k = split_subject(s)
            if (t == "class" and k not in cls) or (t == "ingredient" and k not in ing):
                problems.append(f"{where}: unknown {t} '{k}'")

        for x in self.interactions:
            chk(x.a, "interaction"); chk(x.b, "interaction")
        for x in self.contraindications:
            chk(x.subject, "contraindication")
        for x in self.age_warnings:
            chk(x.subject, "age_warning")
        for x in self.allergy_cross:
            chk(x.allergen, "allergy_cross"); chk(x.drug, "allergy_cross")
        for x in self.dose_limits:
            if x.ingredient not in ing:
                problems.append(f"dose_limit: unknown ingredient '{x.ingredient}'")
        if problems:
            raise ValueError("; ".join(problems[:20]) + (" ..." if len(problems) > 20 else ""))
        return self


def parse_bundle_json(text: str) -> Bundle:
    try:
        return Bundle.model_validate_json(text)
    except ValidationError as e:
        msgs = []
        for err in e.errors()[:15]:
            loc = ".".join(str(p) for p in err["loc"])
            msgs.append(f"{loc}: {err['msg']}")
        raise RefError("Invalid reference bundle:\n" + "\n".join(msgs)) from e


# ---------------------------------------------------------------------------- CSV import
CSV_SECTIONS = {
    "ingredients": {"key", "name", "classes", "aliases", "brands"},
    "classes": {"key", "name", "aliases"},
    "interactions": {"a", "b", "severity", "effect", "management", "source_citation"},
    "contraindications": {"subject", "condition_terms", "severity", "note", "management", "source_citation"},
    "dose_limits": {"ingredient", "max_single", "max_daily", "unit", "source_citation"},
    "age_warnings": {"subject", "severity", "message", "source_citation"},
    "allergy_cross": {"allergen", "drug", "note", "source_citation"},
}
_LIST_FIELDS = {"classes", "aliases", "brands", "condition_terms"}
_NUM_FIELDS = {"min_age_years", "max_age_years", "max_single", "max_daily"}


def bundle_from_csvs(meta: dict, files: dict[str, str]) -> Bundle:
    """`files`: section name -> CSV text. List cells use '|' as separator."""
    data: dict = {"meta": meta}
    for section, text in files.items():
        if section not in CSV_SECTIONS:
            raise RefError(f"Unknown CSV section '{section}'")
        rdr = csv.DictReader(io.StringIO(text))
        missing = CSV_SECTIONS[section] - set(rdr.fieldnames or [])
        if missing:
            raise RefError(f"{section}.csv is missing columns: {', '.join(sorted(missing))}")
        rows = []
        for r in rdr:
            row = {}
            for k, v in r.items():
                if k is None or v is None:
                    continue
                v = v.strip()
                if k in _LIST_FIELDS:
                    row[k] = [x.strip() for x in v.split("|") if x.strip()]
                elif k in _NUM_FIELDS:
                    if v:
                        row[k] = float(v)
                elif k == "per_kg":
                    row[k] = v.lower() in ("1", "true", "yes", "y")
                else:
                    row[k] = v
            rows.append(row)
        data[section] = rows
    try:
        return Bundle.model_validate(data)
    except ValidationError as e:
        raise RefError("Invalid CSV content:\n" + "\n".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:15])) from e


# ---------------------------------------------------------------------------- in-memory index
@dataclass
class RefIndex:
    dataset: dict
    ingredients: dict[str, str] = field(default_factory=dict)
    classes: dict[str, str] = field(default_factory=dict)
    ing_classes: dict[str, set] = field(default_factory=dict)
    drug_alias: dict[str, list[str]] = field(default_factory=dict)  # alias -> ingredient keys
    any_alias: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # alias -> (type,key)
    interactions: list[dict] = field(default_factory=list)
    contraindications: list[dict] = field(default_factory=list)
    dose_limits: list[dict] = field(default_factory=list)
    age_warnings: list[dict] = field(default_factory=list)
    allergy_cross: list[dict] = field(default_factory=list)

    @property
    def rule_count(self) -> int:
        return len(self.interactions) + len(self.contraindications) + len(self.dose_limits) + len(self.age_warnings) + len(self.allergy_cross)

    @property
    def is_synthetic(self) -> bool:
        return self.dataset.get("kind") == "synthetic_demo"

    @property
    def is_approved_for_clinical(self) -> bool:
        return self.dataset.get("kind") == "imported" and self.dataset.get("status") == "approved"

    def classes_of(self, ing: str) -> set:
        return self.ing_classes.get(ing, set())

    def matches(self, subject_type: str, subject_key: str, ing: str) -> bool:
        return ing == subject_key if subject_type == "ingredient" else subject_key in self.classes_of(ing)


def _rows_from_bundle(b: Bundle) -> dict[str, list[dict]]:
    aliases: list[dict] = []

    def add(alias, ttype, tkey, kind):
        n = norm_text(alias)
        if n:
            aliases.append({"alias_norm": n, "target_type": ttype, "target_key": tkey, "alias_kind": kind})

    for c in b.classes:
        add(c.name, "class", c.key, "generic"); add(c.key.replace("_", " "), "class", c.key, "generic")
        for a in c.aliases:
            add(a, "class", c.key, "generic")
    for i in b.ingredients:
        add(i.name, "ingredient", i.key, "generic"); add(i.key.replace("_", " "), "ingredient", i.key, "generic")
        for a in i.aliases:
            add(a, "ingredient", i.key, "generic")
        for a in i.brands:
            add(a, "ingredient", i.key, "brand")
    for p in b.products:
        for nm, kind in [(p.name, "generic")] + [(x, "brand") for x in p.brands]:
            for k in p.ingredients:
                add(nm, "ingredient", k, kind)
    return {
        "classes": [{"key": c.key, "name": c.name} for c in b.classes],
        "ingredients": [{"key": i.key, "name": i.name} for i in b.ingredients],
        "ingredient_classes": [{"ingredient_key": i.key, "class_key": c} for i in b.ingredients for c in i.classes],
        "aliases": aliases,
        "interactions": [x.model_dump() for x in b.interactions],
        "contraindications": [x.model_dump() for x in b.contraindications],
        "dose_limits": [x.model_dump() for x in b.dose_limits],
        "age_warnings": [x.model_dump() for x in b.age_warnings],
        "allergy_cross": [x.model_dump() for x in b.allergy_cross],
    }


def _index_from_rows(dataset: dict, rows: dict[str, list[dict]]) -> RefIndex:
    ix = RefIndex(dataset=dataset)
    ix.classes = {r["key"]: r["name"] for r in rows["classes"]}
    ix.ingredients = {r["key"]: r["name"] for r in rows["ingredients"]}
    for r in rows["ingredient_classes"]:
        ix.ing_classes.setdefault(r["ingredient_key"], set()).add(r["class_key"])
    for r in rows["aliases"]:
        lst = ix.any_alias.setdefault(r["alias_norm"], [])
        if (r["target_type"], r["target_key"]) not in lst:
            lst.append((r["target_type"], r["target_key"]))
        if r["target_type"] == "ingredient":
            d = ix.drug_alias.setdefault(r["alias_norm"], [])
            if r["target_key"] not in d:
                d.append(r["target_key"])
    for i, r in enumerate(rows["interactions"]):
        ix.interactions.append({**r, "id": r.get("id", i + 1), "a_t": split_subject(r["a"]), "b_t": split_subject(r["b"])})
    for i, r in enumerate(rows["contraindications"]):
        ix.contraindications.append({**r, "id": r.get("id", i + 1), "s_t": split_subject(r["subject"])})
    for i, r in enumerate(rows["dose_limits"]):
        ix.dose_limits.append({**r, "id": r.get("id", i + 1)})
    for i, r in enumerate(rows["age_warnings"]):
        ix.age_warnings.append({**r, "id": r.get("id", i + 1), "s_t": split_subject(r["subject"])})
    for i, r in enumerate(rows["allergy_cross"]):
        ix.allergy_cross.append({**r, "id": r.get("id", i + 1), "al_t": split_subject(r["allergen"]), "dr_t": split_subject(r["drug"])})
    return ix


def index_from_bundle(b: Bundle, kind: str = "imported", status: str = "pending_review") -> RefIndex:
    ds = {"id": "mem", "name": b.meta.name, "version": b.meta.version, "kind": kind, "status": status,
          "source_description": b.meta.source_description}
    return _index_from_rows(ds, _rows_from_bundle(b))


# ---------------------------------------------------------------------------- persistence
def _checksum(b: Bundle) -> str:
    return hashlib.sha256(json.dumps(b.model_dump(), sort_keys=True).encode()).hexdigest()


def save_bundle(conn: sqlite3.Connection, b: Bundle, *, kind: str, imported_by: str | None, activate: bool = False) -> str:
    ds_id = uuid.uuid4().hex[:12]
    rows = _rows_from_bundle(b)
    cs = _checksum(b)
    if conn.execute("SELECT 1 FROM ref_datasets WHERE checksum=? AND status<>'retired'", (cs,)).fetchone():
        raise RefError("An identical dataset has already been imported.")
    conn.execute(
        "INSERT INTO ref_datasets(id,name,version,kind,source_description,status,active,checksum,imported_at,imported_by)"
        " VALUES (?,?,?,?,?,?,0,?,?,?)",
        (ds_id, b.meta.name, b.meta.version, kind, b.meta.source_description, "pending_review", cs, now_iso(), imported_by),
    )
    ins = lambda sql, seq: conn.executemany(sql, seq)  # noqa: E731
    ins("INSERT INTO ref_classes VALUES (?,?,?)", [(ds_id, r["key"], r["name"]) for r in rows["classes"]])
    ins("INSERT INTO ref_ingredients VALUES (?,?,?)", [(ds_id, r["key"], r["name"]) for r in rows["ingredients"]])
    ins("INSERT INTO ref_ingredient_classes VALUES (?,?,?)", [(ds_id, r["ingredient_key"], r["class_key"]) for r in rows["ingredient_classes"]])
    ins("INSERT OR IGNORE INTO ref_aliases VALUES (?,?,?,?,?)", [(ds_id, r["alias_norm"], r["target_type"], r["target_key"], r["alias_kind"]) for r in rows["aliases"]])
    ins("INSERT INTO ref_interactions(dataset_id,a_type,a_key,b_type,b_key,severity,effect,management,source_citation) VALUES (?,?,?,?,?,?,?,?,?)",
        [(ds_id, *split_subject(r["a"]), *split_subject(r["b"]), r["severity"], r["effect"], r["management"], r["source_citation"]) for r in rows["interactions"]])
    ins("INSERT INTO ref_contraindications(dataset_id,subject_type,subject_key,condition_terms,severity,note,management,source_citation) VALUES (?,?,?,?,?,?,?,?)",
        [(ds_id, *split_subject(r["subject"]), json.dumps(r["condition_terms"]), r["severity"], r["note"], r["management"], r["source_citation"]) for r in rows["contraindications"]])
    ins("INSERT INTO ref_dose_limits(dataset_id,ingredient_key,route,min_age_years,max_age_years,max_single,max_daily,unit,per_kg,note,source_citation) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(ds_id, r["ingredient"], r["route"] or None, r["min_age_years"], r["max_age_years"], r["max_single"], r["max_daily"], r["unit"], int(r["per_kg"]), r["note"], r["source_citation"]) for r in rows["dose_limits"]])
    ins("INSERT INTO ref_age_warnings(dataset_id,subject_type,subject_key,min_age_years,max_age_years,severity,message,management,source_citation) VALUES (?,?,?,?,?,?,?,?,?)",
        [(ds_id, *split_subject(r["subject"]), r["min_age_years"], r["max_age_years"], r["severity"], r["message"], r["management"], r["source_citation"]) for r in rows["age_warnings"]])
    ins("INSERT INTO ref_allergy_cross(dataset_id,allergen_type,allergen_key,drug_type,drug_key,severity,note,source_citation) VALUES (?,?,?,?,?,?,?,?)",
        [(ds_id, *split_subject(r["allergen"]), *split_subject(r["drug"]), r["severity"], r["note"], r["source_citation"]) for r in rows["allergy_cross"]])
    conn.commit()
    if activate:
        set_active(conn, ds_id)
    return ds_id


def list_datasets(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM ref_datasets ORDER BY imported_at DESC"):
        d = dict(r)
        d["counts"] = {
            t: conn.execute(f"SELECT COUNT(*) FROM ref_{t} WHERE dataset_id=?", (r["id"],)).fetchone()[0]
            for t in ("ingredients", "interactions", "contraindications", "dose_limits", "age_warnings", "allergy_cross")
        }
        out.append(d)
    return out


def get_dataset(conn, ds_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM ref_datasets WHERE id=?", (ds_id,)).fetchone()
    return dict(r) if r else None


def load_index(conn: sqlite3.Connection, ds_id: str) -> RefIndex:
    ds = get_dataset(conn, ds_id)
    if not ds:
        raise RefError("Dataset not found")

    def q(sql):
        return [dict(r) for r in conn.execute(sql, (ds_id,))]

    ia = []
    for r in q("SELECT * FROM ref_interactions WHERE dataset_id=?"):
        ia.append({"id": r["id"], "a": ("class:" if r["a_type"] == "class" else "") + r["a_key"], "b": ("class:" if r["b_type"] == "class" else "") + r["b_key"],
                   "severity": r["severity"], "effect": r["effect"], "management": r["management"], "source_citation": r["source_citation"]})
    sub = lambda t, k: ("class:" if t == "class" else "") + k  # noqa: E731
    rows = {
        "classes": q("SELECT key,name FROM ref_classes WHERE dataset_id=?"),
        "ingredients": q("SELECT key,name FROM ref_ingredients WHERE dataset_id=?"),
        "ingredient_classes": q("SELECT ingredient_key,class_key FROM ref_ingredient_classes WHERE dataset_id=?"),
        "aliases": q("SELECT alias_norm,target_type,target_key,alias_kind FROM ref_aliases WHERE dataset_id=?"),
        "interactions": ia,
        "contraindications": [
            {"id": r["id"], "subject": sub(r["subject_type"], r["subject_key"]), "condition_terms": json.loads(r["condition_terms"]), "severity": r["severity"],
             "note": r["note"], "management": r["management"], "source_citation": r["source_citation"]}
            for r in q("SELECT * FROM ref_contraindications WHERE dataset_id=?")],
        "dose_limits": [
            {"id": r["id"], "ingredient": r["ingredient_key"], "route": r["route"] or "", "min_age_years": r["min_age_years"], "max_age_years": r["max_age_years"],
             "max_single": r["max_single"], "max_daily": r["max_daily"], "unit": r["unit"], "per_kg": bool(r["per_kg"]), "note": r["note"], "source_citation": r["source_citation"]}
            for r in q("SELECT * FROM ref_dose_limits WHERE dataset_id=?")],
        "age_warnings": [
            {"id": r["id"], "subject": sub(r["subject_type"], r["subject_key"]), "min_age_years": r["min_age_years"], "max_age_years": r["max_age_years"],
             "severity": r["severity"], "message": r["message"], "management": r["management"], "source_citation": r["source_citation"]}
            for r in q("SELECT * FROM ref_age_warnings WHERE dataset_id=?")],
        "allergy_cross": [
            {"id": r["id"], "allergen": sub(r["allergen_type"], r["allergen_key"]), "drug": sub(r["drug_type"], r["drug_key"]), "severity": r["severity"],
             "note": r["note"], "source_citation": r["source_citation"]}
            for r in q("SELECT * FROM ref_allergy_cross WHERE dataset_id=?")],
    }
    return _index_from_rows(ds, rows)


def active_dataset_id(conn) -> str | None:
    r = conn.execute("SELECT id FROM ref_datasets WHERE active=1 LIMIT 1").fetchone()
    return r["id"] if r else None


def load_active_index(conn) -> RefIndex | None:
    ds = active_dataset_id(conn)
    return load_index(conn, ds) if ds else None


def set_active(conn, ds_id: str, actor: dict | None = None, clinical_mode: bool = False) -> None:
    ds = get_dataset(conn, ds_id)
    if not ds:
        raise RefError("Dataset not found")
    if ds["status"] in ("retired", "rejected"):
        raise RefError("A retired or rejected dataset cannot be activated.")
    if clinical_mode and not (ds["kind"] == "imported" and ds["status"] == "approved"):
        raise RefError("Strict mode requires an imported dataset that has been professionally reviewed and approved.")
    conn.execute("UPDATE ref_datasets SET active=0")
    conn.execute("UPDATE ref_datasets SET active=1 WHERE id=?", (ds_id,))
    conn.commit()
    if actor:
        audit.record(conn, actor, "refdata.activated", "refdata", ds_id, {"name": ds["name"], "kind": ds["kind"]})


def review_dataset(conn, actor: dict, ds_id: str, approve: bool, notes: str, attestation: bool) -> None:
    if not can(actor, "refdata.approve"):
        raise RefError("Your role cannot review reference data.")
    ds = get_dataset(conn, ds_id)
    if not ds:
        raise RefError("Dataset not found")
    if ds["kind"] == "synthetic_demo":
        raise RefError("Synthetic sample data cannot be approved for clinical use.")
    if ds["imported_by"] == actor["id"]:
        raise RefError("The reviewer must be a different person from the importer.")
    if approve and not attestation:
        raise RefError("Approval requires the reviewer's attestation.")
    if len(notes.strip()) < 10:
        raise RefError("Please record review notes (what was checked against which source).")
    conn.execute(
        "UPDATE ref_datasets SET status=?, reviewed_at=?, reviewed_by=?, review_notes=? WHERE id=?",
        ("approved" if approve else "rejected", now_iso(), actor["id"], notes.strip(), ds_id),
    )
    if not approve:
        conn.execute("UPDATE ref_datasets SET active=0 WHERE id=?", (ds_id,))
    conn.commit()
    audit.record(conn, actor, "refdata.approved" if approve else "refdata.rejected", "refdata", ds_id, {"name": ds["name"]})


def retire_dataset(conn, actor: dict, ds_id: str) -> None:
    conn.execute("UPDATE ref_datasets SET status='retired', active=0 WHERE id=?", (ds_id,))
    conn.commit()
    audit.record(conn, actor, "refdata.retired", "refdata", ds_id)
