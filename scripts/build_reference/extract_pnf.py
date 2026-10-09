"""Extract active ingredients (and combinations) from the DOH Philippine National Formulary
Essential Medicines List PDF (PNF-EML, 8th ed. Vol. I, as of 2 Nov 2022).

    python scripts/build_reference/extract_pnf.py <pnf.pdf> <out.json>

Output: {"ingredients": [{"name","aliases","routes","forms":[...strength lines]}], "products": [...], "cross_refs": [...]}
Only names/forms/strengths are extracted - the PNF contains no interaction or dose-limit data.
Uncertain parses are listed under "review" for a pharmacist to check.
"""
from __future__ import annotations

import json
import re
import sys

import pypdf

ROUTE_RE = re.compile(r"(?<![A-Za-z])(Oral|Inj\.?|Inhalation|Topical|Rectal|Vaginal|Ophthalmic|Nasal|Otic|Solution|Sublingual|Intravitreal|Transdermal|Dental|Intrapleural|Intrathecal|Implant|Intradermal|Cream|Ointment|Lotion|Gel|Eye drops[A-Za-z ]*|Ear drops|Drops|Powder|Shampoo|Suspension|Resp\. Soln\.|MDI|DPI|Spray|Suppository|Syrup|Emulsion|Paste|Patch|Sachet|Tincture|Strips|Granules|Oral gel|Vaginal suppository|Concentrate)\s*:")
HEADER_RE = re.compile(r"^\s*(Active Ingredient\s+Route|Pharmaceutical Forms and Strengths|\d+\s*$|[A-Z]\s*$)")
FOOTNOTE_RE = re.compile(r"\((?:[A-Z]|\d+(?:\s*,\s*\d+)*|[A-Z]\s*,\s*\d+(?:\s*,\s*\d+)*)\)")


def clean_dash(s: str) -> str:
    return s.replace("‐", "-").replace("‑", "-").replace("–", "-").replace("’", "'")


def read_lines(pdf: str) -> list[str]:
    r = pypdf.PdfReader(pdf)
    out: list[str] = []
    for p in r.pages[13:]:
        for ln in clean_dash(p.extract_text() or "").splitlines():
            out.append(ln.rstrip())
    return out


SKIP_RE = re.compile(r"^\s*(Composition:|Concentration:|N\.B\.|Na\+|K\+|Ca\+\+|Mg\+\+|Cl-|Acetate\s)")


def records(lines: list[str]) -> list[dict]:
    recs: list[dict] = []
    cur: dict | None = None
    for i, ln in enumerate(lines):  # start at the first real entry, skipping the abbreviations page
        if ln.startswith("Abacavir"):
            lines = lines[i:]
            break

    def new():
        nonlocal cur
        cur = {"name_lines": [], "body": [], "has_route": False}
        recs.append(cur)

    for ln in lines:
        if not ln.strip() or HEADER_RE.match(ln):
            continue
        indented = ln.startswith(" ")
        m = ROUTE_RE.search(ln)
        if SKIP_RE.match(ln) or (not indented and len(ln.strip()) < 4):
            continue
        if cur is None:
            new()
        if indented:
            cur["body"].append(ln.strip())
            continue
        if m and m.start() == 0:  # route-start line continues the current record
            cur["has_route"] = True
            cur["body"].append(ln.strip())
            continue
        if cur["has_route"] or cur.get("closed"):
            new()
        if re.search(r"\((?:see|See) ", ln) and not m:
            cur["name_lines"].append(ln.strip())
            cur["closed"] = True
            continue
        if m:
            cur["name_lines"].append(ln[: m.start()].strip())
            cur["has_route"] = True
            cur["body"].append(ln[m.start():].strip())
        else:
            cur["name_lines"].append(ln.strip())
    return recs


def split_name(raw: str) -> tuple[str, list[str], str | None, list[str]]:
    """-> (clean name, aliases, see_target, notes)"""
    s = re.sub(r"\s+", " ", raw).strip()
    notes: list[str] = []
    s = re.sub(r"\*\s*Reserve Antimicrobial", "", s)
    s = FOOTNOTE_RE.sub("", s)
    see = None
    m = re.search(r"\((?:see|See)\s+([^)]+)\)", s)
    if m:
        see = m.group(1).strip()
        s = (s[: m.start()] + s[m.end():]).strip()
    aliases: list[str] = []
    for par in re.findall(r"\(([^)]*)\)", s):
        p = par.strip()
        if re.match(r"(as|equivalent|expressed|in the form)\b", p, re.I) or not p:
            continue
        if len(p) <= 40 and not re.search(r"\d", p):
            aliases.append(p)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\(.*$", "", s)  # unbalanced remainder
    s = re.sub(r"\s+", " ", s).strip(" ,;*-")
    return s, aliases, see, notes


def parse(pdf: str) -> dict:
    ingredients, products, cross, review = [], [], [], []
    seen = set()
    for r in records(read_lines(pdf)):
        raw = " ".join(r["name_lines"])
        name, aliases, see, _ = split_name(raw)
        body = [b for b in r["body"]]
        if not name or len(name) < 3:
            continue
        if see and not r["has_route"]:
            cross.append({"name": name, "see": see})
            continue
        if not r["has_route"]:
            review.append({"raw": raw, "why": "no route/strength found"})
            continue
        routes = sorted({clean_dash(m.group(1)).rstrip(".") for b in body for m in [ROUTE_RE.match(b)] if m})
        forms = [re.sub(r"^(Oral|Inj\.?|Inhalation|Topical|Rectal|Vaginal|Ophthalmic|Nasal|Otic|Solution|Sublingual)\s*:\s*", "", b) for b in body]
        if ":" in name or len(name) > 70 or re.search(r"mmol|Composition", name):
            review.append({"raw": raw, "why": "not an ingredient entry (table/composition)"})
            continue
        base = re.sub(r"\s+(calcium|sodium|potassium|hydrochloride|sulfate|sulphate|fumarate|maleate|mesylate|tartrate|acetate|phosphate|succinate|citrate|bromide|besilate|hydrobromide|magnesium|trihydrate)$", "", name, flags=re.I)
        if base.lower() != name.lower():
            aliases = aliases + [name]
            name = base
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        entry = {"name": name, "aliases": aliases, "routes": routes, "forms": forms[:12]}
        if "+" in name:
            parts = [p.strip() for p in name.split("+") if p.strip()]
            products.append({**entry, "ingredients": parts})
        else:
            ingredients.append(entry)
        if len(name) > 60:
            review.append({"raw": raw, "why": "long name - check parse"})
    return {"source": "DOH Philippine National Formulary - Essential Medicines List, Vol. I, 8th ed. (2019), as of 2 Nov 2022",
            "ingredients": ingredients, "products": products, "cross_refs": cross, "review": review}


if __name__ == "__main__":
    data = parse(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print(f"{len(data['ingredients'])} ingredients, {len(data['products'])} combinations, {len(data['cross_refs'])} cross-refs, {len(data['review'])} to review")
