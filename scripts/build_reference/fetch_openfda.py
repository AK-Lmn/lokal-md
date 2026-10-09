"""Fetch US FDA drug-label excerpts from openFDA for every ingredient in a PNF extract.

    python scripts/build_reference/fetch_openfda.py pnf.json cache_dir

Needs internet (build time only). openFDA data are public; limits: ~240 requests/min and 1000/day
without an API key (set OPENFDA_API_KEY to raise them). Responses are cached per ingredient, so reruns
resume. Only the fields we use are kept: ids, contraindications, pediatric use, brand names.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# INN/USAN spelling variants (the same molecule); US labels use the right-hand names
VARIANTS = {
    "paracetamol": "acetaminophen", "aciclovir": "acyclovir", "adrenaline": "epinephrine", "salbutamol": "albuterol",
    "ciclosporin": "cyclosporine", "cefalexin": "cephalexin", "glycerin": "glycerin", "ceftaxidime": "ceftazidime",
    "anastrazole": "anastrozole", "lumefantrin": "lumefantrine", "polymixin b": "polymyxin b", "clomifene": "clomiphene",
    "chlorphenamine": "chlorpheniramine", "furosemide": "furosemide", "retinol": "vitamin a", "lidocaine": "lidocaine",
    "noradrenaline": "norepinephrine", "pethidine": "meperidine", "thyroxine": "levothyroxine", "rifampicin": "rifampin",
    "isoprenaline": "isoproterenol", "glibenclamide": "glyburide", "amoxycillin": "amoxicillin", "benzylpenicillin": "penicillin g",
    "ethinylestradiol": "ethinyl estradiol", "hyoscine": "scopolamine", "frusemide": "furosemide", "cyproterone": "cyproterone",
}


def label_query(name: str) -> str:
    n = VARIANTS.get(name.lower(), name.lower())
    n = re.sub(r"[^a-z0-9 \-]", " ", n).strip()
    return f'openfda.generic_name:"{n}"+OR+openfda.substance_name:"{n}"'


def fetch(name: str, key: str | None) -> list[dict]:
    url = "https://api.fda.gov/drug/label.json?search=" + label_query(name).replace(" ", "+") + "&limit=8"
    if key:
        url += "&api_key=" + key
    req = urllib.request.Request(url, headers={"User-Agent": "rhu-scribe-reference-builder"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    keep = []
    for res in data.get("results", []):
        of = res.get("openfda", {})
        keep.append({
            "set_id": res.get("set_id"), "effective_time": res.get("effective_time"),
            "generic_name": of.get("generic_name", []), "substance_name": of.get("substance_name", []),
            "brand_name": of.get("brand_name", []), "product_type": of.get("product_type", []),
            "contraindications": (res.get("contraindications") or [""])[0][:6000],
            "pediatric_use": (res.get("pediatric_use") or [""])[0][:3000],
            "pregnancy": (res.get("pregnancy") or [""])[0][:1500],
        })
    return keep


def main(pnf_json: str, cache_dir: str) -> None:
    key = os.environ.get("OPENFDA_API_KEY")
    names = [i["name"] for i in json.load(open(pnf_json, encoding="utf-8"))["ingredients"]]
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    done = miss = 0
    for n in names:
        f = cache / (re.sub(r"[^a-z0-9]+", "_", n.lower()) + ".json")
        if f.exists():
            continue
        try:
            res = fetch(n, key)
        except Exception as e:  # network / rate limit: stop and let the user resume
            print(f"stopped at {n!r}: {type(e).__name__} {e}")
            break
        f.write_text(json.dumps({"query": n, "labels": res}, ensure_ascii=False), encoding="utf-8")
        done += 1
        miss += not res
        time.sleep(0.35)
    print(f"fetched {done} (no label found for {miss}); cache has {len(list(cache.glob('*.json')))} of {len(names)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
