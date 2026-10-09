"""Assemble an import bundle for RHU Scribe from public sources.

    python scripts/build_reference/build_bundle.py --pnf pnf.json --ddinter ddinter_dir --fda fda_cache --out bundle.json

Sources (all cited per record in the output):
  * DOH Philippine National Formulary - EML (ingredient names, combination-product aliases)
  * DDInter 2.0 downloadable CSVs (drug-drug interaction pairs + severity level only). CC BY-NC-SA 4.0
  * openFDA drug-label excerpts (contraindications, paediatric statements, US brand names). US FDA labelling.
NOTHING here is clinically validated. Content extracted from label prose is automatic and must be
verified by a pharmacist; the app imports the bundle as "awaiting review" and will not use it in
clinical mode until a second qualified person approves it.
Not covered (no open source found): dose limits, allergy class cross-reactivity, drug classes.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

LEVELS = {"major": 3, "moderate": 2, "minor": 1}
INV = {3: "major", 2: "moderate", 1: "minor"}
VARIANTS = {
    "paracetamol": "acetaminophen", "aciclovir": "acyclovir", "adrenaline": "epinephrine", "salbutamol": "albuterol",
    "ciclosporin": "cyclosporine", "cefalexin": "cephalexin", "ceftaxidime": "ceftazidime", "anastrazole": "anastrozole",
    "chlorphenamine": "chlorpheniramine", "clomifene": "clomiphene", "noradrenaline": "norepinephrine", "pethidine": "meperidine",
    "rifampicin": "rifampin", "glibenclamide": "glyburide", "frusemide": "furosemide", "glycerol": "glycerin",
}
CONTRA_TERMS = {
    "pregnancy": (r"\bpregnan(?:t|cy)\b", ["pregnancy", "pregnant"]),
    "breastfeeding": (r"\b(?:breast[- ]?feeding|lactation|nursing (?:mothers|women))\b", ["breastfeeding", "lactation"]),
    "renal impairment": (r"\b(?:severe |significant )?(?:renal|kidney) (?:impairment|failure|disease|dysfunction|insufficiency)\b", ["renal impairment", "kidney disease", "renal failure", "kidney failure", "ckd", "chronic kidney disease"]),
    "hepatic impairment": (r"\b(?:severe |significant |active )?(?:hepatic|liver) (?:impairment|failure|disease|dysfunction|insufficiency)\b", ["hepatic impairment", "liver disease", "liver failure", "cirrhosis"]),
    "peptic ulcer": (r"\b(?:peptic|gastric|duodenal) ulcers?\b", ["peptic ulcer", "gastric ulcer", "duodenal ulcer"]),
    "gastrointestinal bleeding": (r"\b(?:gastrointestinal|GI) (?:bleeding|hemorrhage)\b", ["gastrointestinal bleeding", "gi bleeding"]),
    "asthma": (r"\basthma\b", ["asthma"]),
    "glaucoma": (r"\bglaucoma\b", ["glaucoma"]),
    "heart failure": (r"\b(?:congestive |decompensated )?heart failure\b", ["heart failure", "congestive heart failure"]),
    "g6pd deficiency": (r"\bG6PD\b|glucose-6-phosphate", ["g6pd deficiency"]),
    "myasthenia gravis": (r"\bmyasthenia gravis\b", ["myasthenia gravis"]),
    "qt prolongation": (r"\b(?:long|prolonged) QT\b|QT (?:interval )?prolongation", ["qt prolongation", "long qt"]),
    "bleeding disorder": (r"\bbleeding (?:disorders?|diathesis)\b|hemophilia", ["bleeding disorder", "hemophilia"]),
    "porphyria": (r"\bporphyria\b", ["porphyria"]),
}
NEG = re.compile(r"\b(?:no known|not contraindicated|no contraindications?|none)\b", re.I)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]


def sentences(t: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.;:])\s+", re.sub(r"\s+", " ", t)) if x.strip()]


def extract_contra(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for sent in sentences(text):
        if NEG.search(sent):
            continue
        for term, (pat, _) in CONTRA_TERMS.items():
            if term not in out and re.search(pat, sent, re.I):
                out[term] = sent[:350]
    return out


def extract_age(text: str) -> list[tuple[float, str, str]]:
    """-> [(max_age_years_exclusive, severity, sentence)]"""
    res = []
    for sent in sentences(text):
        low = sent.lower()
        m = re.search(r"(?:under|below|younger than|less than|<)\s*(?:the age of\s*)?(\d+)\s*(years?|yrs?|months?|weeks?)", low)
        if m and re.search(r"not been established|not recommended|contraindicated|should not|not approved|not indicated|not be used", low):
            n = float(m.group(1))
            unit = m.group(2)
            yrs = n if unit.startswith(("y",)) else (n / 12 if unit.startswith("mo") else n / 52)
            if 0 < yrs <= 18:
                res.append((round(yrs, 3), "major" if "contraindicated" in low else "moderate", sent[:350]))
        elif re.search(r"(?:safety and (?:effectiveness|efficacy)).{0,80}(?:pediatric|children).{0,40}(?:have|has) not been (?:established|evaluated)|not (?:been )?established in pediatric", low):
            res.append((18.0, "minor", sent[:350]))
    return res[:2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pnf", required=True)
    ap.add_argument("--ddinter", required=True)
    ap.add_argument("--fda", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scope", choices=["all", "pnf"], default="all", help="'pnf' keeps only interaction pairs with a formulary drug")
    a = ap.parse_args()

    pnf = json.load(open(a.pnf, encoding="utf-8"))
    dd_files = sorted(Path(a.ddinter).glob("*.csv"))
    names: dict[str, str] = {}  # key -> display name
    pairs: dict[frozenset, tuple[int, str, str]] = {}
    for f in dd_files:
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            lv = LEVELS.get(r["Level"].strip().lower())
            ka, kb = slug(r["Drug_A"]), slug(r["Drug_B"])
            if not ka or not kb or ka == kb:
                continue
            names.setdefault(ka, r["Drug_A"].strip())
            names.setdefault(kb, r["Drug_B"].strip())
            if lv is None:
                continue  # 'Unknown' level: not imported
            k = frozenset((ka, kb))
            if k not in pairs or pairs[k][0] < lv:
                pairs[k] = (lv, r["DDInterID_A"], r["DDInterID_B"])

    # ---- map PNF ingredients onto DDInter keys (exact name or known INN/USAN variant); otherwise new ingredient
    ing_alias: dict[str, set[str]] = {}
    pnf_key: dict[str, str] = {}
    product_names = {"cotrimoxazole", "co_trimoxazole", "co_amoxiclav"}
    for p in pnf["ingredients"]:
        base = p["name"]
        if slug(base) in product_names:
            continue  # combination products are added explicitly below
        k = slug(base)
        var = VARIANTS.get(base.lower())
        if k not in names and var and slug(var) in names:
            k = slug(var)
        if k not in names:
            names[k] = base
        pnf_key[base.lower()] = k
        al = ing_alias.setdefault(k, set())
        al.add(base)
        if var:
            al.add(var)
        for x in p["aliases"]:
            al.add(x)
    for ref in pnf["cross_refs"]:  # e.g. Adrenaline -> Epinephrine
        tgt = pnf_key.get(ref["see"].lower()) or (slug(ref["see"]) if slug(ref["see"]) in names else None)
        if tgt and "+" not in ref["name"]:
            ing_alias.setdefault(tgt, set()).add(ref["name"])

    products = []
    def pk(n):
        for cand in (slug(n), slug(VARIANTS.get(n, n))):
            if cand in names:
                return cand
        return next((k for k in names if k.startswith(slug(n)[:8])), None)
    for nm, brands, parts in [("Co-amoxiclav", ["Amoxicillin + Potassium Clavulanate", "Amoxicillin clavulanate"], ["amoxicillin", "clavulanic acid"]),
                              ("Cotrimoxazole", ["Co-trimoxazole", "Sulfamethoxazole + Trimethoprim", "Sulfamethoxazole-trimethoprim"], ["sulfamethoxazole", "trimethoprim"])]:
        keys = [pk(x) for x in parts]
        if all(keys):
            products.append({"name": nm, "brands": brands, "ingredients": keys})

    pnf_keys = set(pnf_key.values())
    # ---- FDA label extraction
    contra, age, brand_owner = [], [], {}
    cite_tpl = "openFDA drug label (US FDA labelling), set_id {sid}, effective {eff}; text extracted automatically - verify"
    cache = Path(a.fda)
    fda_used = 0
    for base, k in pnf_key.items():
        f = cache / (re.sub(r"[^a-z0-9]+", "_", next((p["name"] for p in pnf["ingredients"] if p["name"].lower() == base), base).lower()) + ".json")
        if not f.exists():
            continue
        labels = json.load(open(f, encoding="utf-8"))["labels"]
        single = [l for l in labels if len(l["generic_name"]) == 1 and slug(l["generic_name"][0]).split("_")[0] in {slug(base).split("_")[0], slug(VARIANTS.get(base, base)).split("_")[0]}]
        rx = [l for l in single if "PRESCRIPTION" in " ".join(l["product_type"]).upper() and l["contraindications"]] or [l for l in single if l["contraindications"]]
        if rx:
            fda_used += 1
            l = rx[0]
            cite = cite_tpl.format(sid=l["set_id"], eff=l["effective_time"])
            for term, sent in extract_contra(l["contraindications"]).items():
                contra.append({"subject": k, "condition_terms": CONTRA_TERMS[term][1], "severity": "contraindicated",
                               "note": f"[Auto-extracted, verify] US label contraindication mentioning {term}: \"{sent}\"",
                               "management": "Clinician review; consider an alternative. Check the full product label.", "source_citation": cite})
            for yrs, sev, sent in extract_age(l["pediatric_use"] + " " + l["contraindications"]):
                age.append({"subject": k, "max_age_years": yrs, "severity": sev, "message": f"[Auto-extracted, verify] \"{sent}\"",
                            "management": "Clinician review of paediatric use; check local guidelines.", "source_citation": cite})

    ingredients = []
    for k, display in names.items():
        brands: list[str] = []  # no reliable open source of Philippine brand names was found
        ingredients.append({"key": k, "name": display, "aliases": sorted(ing_alias.get(k, set()) - {display}), "brands": brands[:6]})

    keep_pair = lambda ka, kb: a.scope == "all" or ka in pnf_keys or kb in pnf_keys
    interactions = []
    for fs, (lv, ia, ib) in pairs.items():
        ka, kb = sorted(fs)
        if not keep_pair(ka, kb):
            continue
        interactions.append({"a": ka, "b": kb, "severity": INV[lv],
                             "effect": f"DDInter 2.0 severity level: {INV[lv].capitalize()}. The downloadable data give a severity level only (no mechanism text).",
                             "management": "Check a drug-information reference or ask a pharmacist for mechanism and management before prescribing.",
                             "source_citation": f"DDInter 2.0 (Xiong et al., Nucleic Acids Res 2022; ddinter2.scbdd.com), CC BY-NC-SA 4.0, records {ia}/{ib}"})

    used = {i["a"] for i in interactions} | {i["b"] for i in interactions} | pnf_keys
    ingredients = [i for i in ingredients if i["key"] in used]
    bundle = {
        "meta": {"name": "PH starter set (PNF + DDInter + openFDA labels) - UNVERIFIED", "version": f"build-{date.today().isoformat()}-{a.scope}",
                 "source_description": ("Names: DOH Philippine National Formulary EML 8th ed. (as of 2 Nov 2022). Interactions: DDInter 2.0 (CC BY-NC-SA 4.0, non-commercial/share-alike; "
                                        "8 downloadable ATC files only; 'Unknown' levels excluded). Contraindications/age statements: openFDA US drug labels, auto-extracted. No brand names. "
                                        "No dose limits, no allergy cross-reactivity, no drug classes. NOT clinically validated.")},
        "classes": [], "ingredients": ingredients, "products": products, "interactions": interactions,
        "contraindications": contra, "dose_limits": [], "age_warnings": age, "allergy_cross": [],
    }
    Path(a.out).write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    print(f"ingredients {len(ingredients)} | interactions {len(interactions)} | contraindications {len(contra)} (from {fda_used} labels) | age warnings {len(age)} | products {len(products)}")
    print("PNF ingredients without any DDInter interaction record:", sum(1 for k in pnf_keys if not any(k in fs for fs in pairs)))


if __name__ == "__main__":
    main()
