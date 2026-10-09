"""Candidate lattice: every value the converter may output must be one of these spans (or null).

Dates (DE/FR/IT): numeric d.m.yyyy / d/m/yyyy / ISO yyyy-mm-dd, and day + month name (full or abbreviated) + year, including
"1er", "1°", "1º" and weekday-free forms. Every candidate carries page (1-based), char_start/char_end into that page's text,
the raw span, ISO value, ±12-token context and the line it sits on. Invalid calendar dates and years outside 1848..2100
are dropped.

Affair numbers: generic shapes (BE 2024.RRGR.91, CHE 23.4086, ZH 123/2024, GE M 2345, ...) kept only if the normalised string
EXISTS in OPD for the given body (data/convert/affair_numbers.json.gz, built from the affairs export). The model can never
point at an affair number OPD does not know.

Enum labels: government recommendation, per language.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import re
from functools import lru_cache

from ..paths import DATA, OPD_RAW

K_CTX = 12

MONTHS = {
    # DE
    "januar": 1,
    "jänner": 1,
    "jan": 1,
    "februar": 2,
    "feb": 2,
    "febr": 2,
    "märz": 3,
    "maerz": 3,
    "mär": 3,
    "mrz": 3,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "juni": 6,
    "jun": 6,
    "juli": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "oktober": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "dezember": 12,
    "dez": 12,
    # FR
    "janvier": 1,
    "janv": 1,
    "février": 2,
    "fevrier": 2,
    "févr": 2,
    "fevr": 2,
    "fév": 2,
    "mars": 3,
    "avril": 4,
    "avr": 4,
    "juin": 6,
    "juillet": 7,
    "juil": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "oct": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
    "déc": 12,
    "dec": 12,
    # IT
    "gennaio": 1,
    "genn": 1,
    "gen": 1,
    "febbraio": 2,
    "febbr": 2,
    "marzo": 3,
    "mar": 3,
    "aprile": 4,
    "maggio": 5,
    "magg": 5,
    "giugno": 6,
    "giu": 6,
    "luglio": 7,
    "lug": 7,
    "agosto": 8,
    "ago": 8,
    "settembre": 9,
    "sett": 9,
    "set": 9,
    "ottobre": 10,
    "ott": 10,
    "dicembre": 12,
    "dic": 12,
}
_MON_ALT = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
DATE_RE = re.compile(
    r"(?<![\d.])(?P<d>[0-3]?\d)\s?\.\s?(?P<m>[01]?\d)\s?\.\s?(?P<y>(?:18|19|20)\d\d)(?!\d)"  # 28.08.2024 / 28. 8. 2024
    r"|(?<![\d/])(?P<d2>[0-3]?\d)/(?P<m2>[01]?\d)/(?P<y2>(?:18|19|20)\d\d)(?!\d)"  # 28/08/2024
    r"|(?<!\d)(?P<y3>(?:18|19|20)\d\d)-(?P<m3>[01]\d)-(?P<d3>[0-3]\d)(?!\d)"  # 2024-08-28
    r"|(?<![\w])(?P<d4>[0-3]?\d)(?:\s?\.|er|°|º|o)?\s*(?P<mon>" + _MON_ALT + r")\.?,?\s*(?P<y4>(?:18|19|20)\d\d)(?!\d)",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _iso(m: re.Match) -> str | None:
    g = m.groupdict()
    if g["d"]:
        d, mo, y = g["d"], g["m"], g["y"]
    elif g["d2"]:
        d, mo, y = g["d2"], g["m2"], g["y2"]
    elif g["y3"]:
        d, mo, y = g["d3"], g["m3"], g["y3"]
    else:
        d, y = g["d4"], g["y4"]
        mo = MONTHS.get(g["mon"].lower().rstrip("."))
        if mo is None:
            return None
    try:
        dt = _dt.date(int(y), int(mo), int(d))
    except ValueError:
        return None
    if not 1848 <= dt.year <= 2100:
        return None
    return dt.isoformat()


def _ctx(text: str, s: int, e: int, k: int = K_CTX) -> str:
    left = [t.group(0) for t in TOKEN_RE.finditer(text[max(0, s - 400) : s])][-k:]
    right = [t.group(0) for t in TOKEN_RE.finditer(text[e : e + 400])][:k]
    return " ".join(left) + " ⟦" + re.sub(r"\s+", " ", text[s:e]) + "⟧ " + " ".join(right)


def line_of(text: str, s: int, e: int) -> tuple[int, int]:
    ls = text.rfind("\n", 0, s) + 1
    le = text.find("\n", e)
    return ls, (len(text) if le < 0 else le)


def dates(pages: list[str]) -> list[dict]:
    out = []
    for pi, text in enumerate(pages, start=1):
        for m in DATE_RE.finditer(text):
            iso = _iso(m)
            if iso is None:
                continue
            ls, le = line_of(text, m.start(), m.end())
            out.append(
                dict(
                    kind="date",
                    value=iso,
                    page=pi,
                    char_start=m.start(),
                    char_end=m.end(),
                    raw=m.group(0),
                    ctx=_ctx(text, m.start(), m.end()),
                    line=text[ls:le].strip(),
                )
            )
    return out


def distinct_dates(cands: list[dict]) -> list[str]:
    seen = []
    for c in cands:
        if c["value"] not in seen:
            seen.append(c["value"])
    return seen


# ---------------------------------------------------------------------------------------------------- affair numbers
AFFAIR_SHAPES = re.compile(
    r"\b\d{4}\.[A-Z]{2,8}\.\d{1,6}\b"  # BE 2024.RRGR.91, 2025.GRPARL.320
    r"|\b\d{2}\.\d{3,4}\b"  # CHE 23.4086, BS 23.5048
    r"|\b\d{1,4}/\d{4}\b"  # ZH KR-Nr. 123/2024, Zürich city 2024/123 (reversed below)
    r"|\b\d{4}/\d{1,4}\b"
    r"|\b(?:M|P|PL|QUE|IN|IUE|R|RD|PRD|I|MO|PO|IP|IR|INT|MOT|POS|Q|GP)[ -]?\d{1,5}(?:-[A-Z])?\b"  # GE M 2345, VS INT_5.0460-like
    r"|\b\d{4}\.\d{1,5}\b"
)  # other year.seq shapes


def _norm_num(s: str) -> str:
    return re.sub(r"[\s_-]+", " ", s.strip()).upper()


@lru_cache(maxsize=1)
def affair_index() -> dict[str, set[str]]:
    """body_key -> set of normalised affair numbers. Built from the affairs export once, cached under data/convert/."""
    p = DATA / "convert" / "affair_numbers.json.gz"
    if not p.exists():
        build_affair_index()
    d = json.load(gzip.open(p, "rt"))
    return {b: set(v) for b, v in d.items()}


def build_affair_index() -> None:
    idx: dict[str, set[str]] = {}
    for line in gzip.open(OPD_RAW / "affairs.ndjson.gz", "rt"):
        a = json.loads(line)
        if a.get("number"):
            idx.setdefault(a["body_key"], set()).add(_norm_num(a["number"]))
    p = DATA / "convert" / "affair_numbers.json.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt") as f:
        json.dump({b: sorted(v) for b, v in sorted(idx.items())}, f, separators=(",", ":"))


def affair_numbers(pages: list[str], body: str, index: dict[str, set[str]] | None = None) -> list[dict]:
    known = (index if index is not None else affair_index()).get(body, set())
    out = []
    for pi, text in enumerate(pages, start=1):
        for m in AFFAIR_SHAPES.finditer(text):
            n = _norm_num(m.group(0))
            if n in known:
                out.append(
                    dict(
                        kind="affair_number",
                        value=n,
                        page=pi,
                        char_start=m.start(),
                        char_end=m.end(),
                        raw=m.group(0),
                        ctx=_ctx(text, m.start(), m.end()),
                    )
                )
    return out


# ---------------------------------------------------------------------------------------------------- enum labels
RECOMMENDATION = {
    "de": {"accept": "annehmen", "reject": "ablehnen", "convert": "in Postulat umwandeln"},
    "fr": {"accept": "accepter", "reject": "rejeter", "convert": "transformer en postulat"},
    "it": {"accept": "accogliere", "reject": "respingere", "convert": "trasformare in postulato"},
}


def recommendation_labels(lang: str) -> dict[str, str]:
    return RECOMMENDATION.get(lang, RECOMMENDATION["de"])
