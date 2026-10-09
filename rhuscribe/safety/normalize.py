"""Deterministic parsing of medication names, strengths, units and frequencies."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import get_close_matches

NOISE_WORDS = {
    "tablet", "tablets", "tab", "tabs", "capsule", "capsules", "cap", "caps", "syrup", "suspension", "susp",
    "drops", "drop", "ampule", "amp", "vial", "injection", "inj", "cream", "ointment", "sachet", "oral", "film",
    "once", "daily", "twice", "thrice", "day", "days", "times", "time", "every", "hours", "hour", "hrs", "morning", "night", "bedtime", "weekly",
    "week", "needed", "as", "at", "x", "bid", "tid", "qid", "od", "qd", "prn", "hs", "after", "before", "meals", "food", "continue", "continued",
    "coated", "forte", "plus", "and", "with", "sr", "xr", "er", "mr", "po", "iv", "im", "per", "the", "of", "for",
    "mg", "g", "mcg", "ml", "iu", "unit", "units", "pcs", "pc", "generic", "brand", "tabs.", "solution", "sol",
}

_STRENGTH_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:mg|g|mcg|µg|ug|ml|iu|%|units?)(?:\s*/\s*\d*(?:[.,]\d+)?\s*(?:ml|g|mg|tab|tablet|cap|capsule|l))?",
    re.I,
)


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9+\- ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_strength(s: str) -> str:
    return _STRENGTH_RE.sub(" ", s or "")


def name_tokens(raw: str) -> list[str]:
    cleaned = norm_text(strip_strength(raw))
    return [t for t in cleaned.split() if t]


# --------------------------------------------------------------------- name resolution
@dataclass
class Resolution:
    raw: str
    status: str  # resolved | partial | unknown | empty
    ingredients: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    leftover: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def resolve_name(raw: str, alias_map: dict[str, list[str]], max_ngram: int = 4) -> Resolution:
    """Greedy longest-match of alias n-grams. `alias_map`: normalised alias -> ingredient keys.
    Fuzzy matches are only ever offered as suggestions, never applied automatically."""
    toks = name_tokens(raw)
    if not toks:
        return Resolution(raw, "empty")
    used = [False] * len(toks)
    found: list[str] = []
    matched: list[str] = []
    i = 0
    while i < len(toks):
        hit = False
        for n in range(min(max_ngram, len(toks) - i), 0, -1):
            if any(used[i : i + n]):
                continue
            phrase = " ".join(toks[i : i + n])
            if phrase in alias_map:
                for k in alias_map[phrase]:
                    if k not in found:
                        found.append(k)
                matched.append(phrase)
                for j in range(i, i + n):
                    used[j] = True
                i += n
                hit = True
                break
        if not hit:
            i += 1
    leftover = [t for t, u in zip(toks, used) if not u and t not in NOISE_WORDS and not t.isdigit() and len(t) > 2]
    if found and not leftover:
        return Resolution(raw, "resolved", found, matched)
    if found:
        return Resolution(raw, "partial", found, matched, leftover)
    sugg: list[str] = []
    singles = [a for a in alias_map if " " not in a]
    for t in (leftover or toks):
        sugg += get_close_matches(t, singles, n=2, cutoff=0.78)
    sugg += get_close_matches(" ".join(toks), list(alias_map), n=2, cutoff=0.8)
    seen, out = set(), []
    for s in sugg:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return Resolution(raw, "unknown", [], [], leftover or toks, out[:3])


# --------------------------------------------------------------------- strength / units
UNIT_ALIASES = {
    "mg": "mg", "milligram": "mg", "milligrams": "mg", "g": "g", "gram": "g", "grams": "g", "gm": "g",
    "mcg": "mcg", "µg": "mcg", "ug": "mcg", "microgram": "mcg", "micrograms": "mcg",
    "ml": "ml", "cc": "ml", "milliliter": "ml", "millilitre": "ml",
    "tab": "tablet", "tabs": "tablet", "tablet": "tablet", "tablets": "tablet",
    "cap": "capsule", "caps": "capsule", "capsule": "capsule", "capsules": "capsule",
    "drop": "drop", "drops": "drop", "puff": "puff", "puffs": "puff", "sachet": "sachet", "sachets": "sachet",
    "iu": "iu", "unit": "unit", "units": "unit", "ampule": "ampule", "amp": "ampule", "vial": "vial",
}
MASS_TO_MG = {"mg": 1.0, "g": 1000.0, "mcg": 0.001}
COUNT_UNITS = {"tablet", "capsule", "sachet", "ampule", "vial"}


def canon_unit(u: str) -> str:
    return UNIT_ALIASES.get((u or "").strip().lower().rstrip("."), (u or "").strip().lower())


@dataclass
class Strength:
    mg_per_unit: float | None = None  # per tablet/capsule
    mg_per_ml: float | None = None
    ambiguous: bool = False
    text: str = ""


_MASS = r"(mg|g|mcg|µg|ug)"
_NUM = r"(\d+(?:[.,]\d+)?)"


def parse_strength(*texts: str) -> Strength:
    for t in texts:
        if not t:
            continue
        s = t.lower()
        m = re.search(_NUM + r"\s*" + _MASS + r"\s*/\s*" + _NUM + r"?\s*(ml)\b", s)
        if m:
            amt = float(m.group(1).replace(",", ".")) * MASS_TO_MG[canon_unit(m.group(2))]
            den = float(m.group(3).replace(",", ".")) if m.group(3) else 1.0
            return Strength(mg_per_ml=amt / den, text=t)
        if re.search(_NUM + r"\s*(?:" + _MASS + r")?\s*/\s*" + _NUM + r"\s*" + _MASS, s):
            return Strength(ambiguous=True, text=t)  # e.g. 500/125 mg combination strengths
        ms = re.findall(_NUM + r"\s*" + _MASS + r"\b", s)
        if len(ms) == 1:
            amt = float(ms[0][0].replace(",", ".")) * MASS_TO_MG[canon_unit(ms[0][1])]
            return Strength(mg_per_unit=amt, text=t)
        if len(ms) > 1:
            return Strength(ambiguous=True, text=t)
    return Strength()


# --------------------------------------------------------------------- frequency
@dataclass
class Freq:
    ok: bool
    per_day: float | None = None
    prn: bool = False
    single: bool = False
    label: str = ""


def parse_frequency(text: str) -> Freq:
    s = (text or "").lower().strip()
    if not s:
        return Freq(False)
    prn = bool(re.search(r"\bprn\b|as needed|if needed|kung kailangan|when needed", s))
    s2 = re.sub(r"\bprn\b|as needed|if needed|when needed|kung kailangan", " ", s).strip(" ,;")
    if re.search(r"\b(stat|once only|single dose|one time|one-time|x ?1 dose|now)\b", s2):
        return Freq(True, 1.0, prn, True, "single dose")
    m = re.search(r"\bq\s*(\d+)(?:\s*-\s*(\d+))?\s*(?:h|hr|hrs|hours?)\b", s2) or re.search(
        r"every\s+(\d+)(?:\s*(?:-|to)\s*(\d+))?\s*(?:h|hr|hrs|hours?)\b", s2
    )
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else lo
        interval = min(lo, hi)
        if interval > 0:
            return Freq(True, 24.0 / interval, prn, False, f"every {m.group(1)}h")
    pats = [
        (r"\b(qid|four times|4 times|4x|qds)\b", 4), (r"\b(tid|tds|three times|3 times|3x)\b", 3),
        (r"\b(bid|bd|twice|2 times|2x)\b", 2), (r"\b(qhs|hs|at bedtime|nightly|at night|bedtime)\b", 1),
        (r"\b(qod|every other day|alternate day)\b", 0.5), (r"\b(weekly|once a week|once weekly)\b", 1 / 7),
        (r"\b(qd|od|once|daily|every day|1 time|1x|isang beses)\b", 1),
    ]
    for pat, n in pats:
        if re.search(pat, s2):
            return Freq(True, float(n), prn, False, pat.split("|")[0].strip(r"\b("))
    m = re.search(r"(\d+)\s*(?:times|x)\s*(?:a|per|/)?\s*(?:day|daily)", s2)
    if m:
        return Freq(True, float(m.group(1)), prn, False, m.group(0))
    return Freq(False, None, prn, False, s)
