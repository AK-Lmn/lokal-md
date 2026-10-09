"""Fetch a Figma node, export it (PNG/SVG + icons) into static/figma/ and extract design tokens.

Developer tool only - needs internet and a Figma personal access token; the app itself never calls Figma.

    FIGMA_TOKEN=figd_... python scripts/figma_tokens.py [FILE_KEY] [NODE_ID]

Writes static/figma/{design.png,design.svg,tokens.json} and static/figma/icons/*.svg.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

API = "https://api.figma.com/v1"
OUT = Path(__file__).resolve().parent.parent / "static" / "figma"
ICON_MAX = 24  # frames named like lucide icons ("shield-check") at or below this size are exported as icons


def _get(url: str, token: str | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"X-Figma-Token": token} if token else {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _api(path: str, token: str, **params) -> dict:
    data = json.loads(_get(f"{API}{path}?{urllib.parse.urlencode(params)}", token))
    if data.get("err"):
        raise SystemExit(f"Figma API error: {data['err']}")
    return data


def _hex(c: dict, opacity: float = 1.0) -> str:
    h = "#%02x%02x%02x" % tuple(round(c[k] * 255) for k in "rgb")
    a = c.get("a", 1) * opacity
    return h if a >= 0.999 else f"{h}{round(a * 255):02x}"


def _walk(n: dict):
    yield n
    for c in n.get("children", []):
        yield from _walk(c)


def extract_tokens(root: dict) -> dict:
    fills, text, strokes = Counter(), Counter(), Counter()
    fonts, sizes, radii, spacing, gaps, effects = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    for n in _walk(root):
        for f in n.get("fills", []):
            if f.get("visible", True) and f["type"] == "SOLID":
                (text if n["type"] == "TEXT" else fills)[_hex(f["color"], f.get("opacity", 1))] += 1
        for s in n.get("strokes", []):
            if s.get("visible", True) and s["type"] == "SOLID":
                strokes[_hex(s["color"], s.get("opacity", 1))] += 1
        if n["type"] == "TEXT":
            st = n["style"]
            fonts[(st["fontFamily"], st["fontWeight"])] += 1
            sizes[(st["fontSize"], round(st.get("lineHeightPx", 0), 1), st["fontWeight"])] += 1
        if n.get("cornerRadius"):
            radii[n["cornerRadius"]] += 1
        for k in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft"):
            if n.get(k):
                spacing[n[k]] += 1
        if n.get("itemSpacing"):
            gaps[n["itemSpacing"]] += 1
        for e in n.get("effects", []):
            if e.get("visible", True):
                effects[json.dumps({k: e.get(k) for k in ("type", "color", "offset", "radius", "spread")}, sort_keys=True)] += 1
    by_family: dict[str, list[int]] = {}
    for (fam, w), _ in fonts.items():
        by_family.setdefault(fam, []).append(int(w))
    return {
        "colors": {
            "fill": dict(fills.most_common()),
            "text": dict(text.most_common()),
            "stroke": dict(strokes.most_common()),
        },
        "fonts": {fam: sorted(ws) for fam, ws in by_family.items()},
        "fontSizes": [{"size": s, "lineHeight": lh, "weight": int(w), "count": c} for (s, lh, w), c in sorted(sizes.items())],
        "spacing": {"padding": dict(sorted(spacing.items())), "gap": dict(sorted(gaps.items()))},
        "radii": dict(sorted(radii.items())),
        "effects": [json.loads(k) | {"count": c} for k, c in effects.items()],
    }


def main() -> None:
    token = os.environ.get("FIGMA_TOKEN") or sys.exit("Set FIGMA_TOKEN (Figma personal access token).")
    file_key = sys.argv[1] if len(sys.argv) > 1 else "uyPjPK9blJ48icnWrjNEfz"
    node_id = (sys.argv[2] if len(sys.argv) > 2 else "3:9").replace("-", ":")
    doc = _api(f"/files/{file_key}/nodes", token, ids=node_id)["nodes"][node_id]["document"]
    # Pages (CANVAS) cannot be rendered by /images; export their first top-level frame instead.
    frame = next((c for c in doc.get("children", []) if c["type"] == "FRAME"), doc) if doc["type"] == "CANVAS" else doc
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icons").mkdir(exist_ok=True)
    for stale in (OUT / "icons").glob("*.svg"):  # icons removed in Figma must not shadow stock Lucide ones
        stale.unlink()

    for fmt, extra in (("png", {"scale": 1}), ("svg", {"svg_include_id": "false", "svg_outline_text": "false"})):
        url = _api(f"/images/{file_key}", token, ids=frame["id"], format=fmt, **extra)["images"][frame["id"]]
        (OUT / f"design.{fmt}").write_bytes(_get(url))

    icons: dict[str, str] = {}
    for n in _walk(frame):
        bb = n.get("absoluteBoundingBox") or {}
        if n["type"] == "FRAME" and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", n["name"]) and bb.get("width", 99) <= ICON_MAX:
            icons.setdefault(n["name"], n["id"])
    if icons:
        urls = _api(f"/images/{file_key}", token, ids=",".join(icons.values()), format="svg", svg_include_id="false")["images"]
        for name, nid in icons.items():
            if urls.get(nid):
                (OUT / "icons" / f"{name}.svg").write_bytes(_get(urls[nid]))

    tokens = {"source": {"file": file_key, "node": node_id, "frame": frame["id"], "name": frame["name"],
                         "size": [frame["absoluteBoundingBox"]["width"], frame["absoluteBoundingBox"]["height"]]},
              **extract_tokens(frame)}
    (OUT / "tokens.json").write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {frame['name']} ({frame['id']}), {len(icons)} icons, tokens -> {OUT / 'tokens.json'}")


if __name__ == "__main__":
    main()
