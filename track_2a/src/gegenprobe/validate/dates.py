"""Multilingual (DE/FR/IT) date recognition and normalisation to ISO 8601.

    normalise_date("28. August 2024") == normalise_date("28.08.2024") == normalise_date("28 août 2024")
        == normalise_date("28 agosto 2024") == normalise_date("2024-08-28") == "2024-08-28"

Accepted: day-month-year with a 4-digit year ("28.8.2024", "28. 08. 2024", "1er août 2024", "1° agosto 2024", "1º", "1.",
"28 Aug. 2024", "Sept."), ISO yyyy-mm-dd, and dd/mm/yyyy. Refused: 2-digit years ("28.08.24"), impossible dates (30.02.2024),
month-year only. `find_dates` returns every match with its character span, for span re-checks and candidate lattices.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

_MONTHS = {
    1: ["januar", "jänner", "janvier", "gennaio", "jan", "janv", "genn", "gen"],
    2: ["februar", "feber", "février", "fevrier", "febbraio", "feb", "febr", "févr", "fevr"],
    3: ["märz", "maerz", "mars", "marzo", "mär", "mrz", "mar"],
    4: ["april", "avril", "aprile", "apr", "avr"],
    5: ["mai", "maggio", "mag"],
    6: ["juni", "juin", "giugno", "jun", "giu"],
    7: ["juli", "juillet", "luglio", "jul", "juil", "lug"],
    8: ["august", "août", "aout", "agosto", "aug", "ago"],
    9: ["september", "septembre", "settembre", "sep", "sept", "set", "sett"],
    10: ["oktober", "octobre", "ottobre", "okt", "oct", "ott"],
    11: ["november", "novembre", "nov"],
    12: ["dezember", "décembre", "decembre", "dicembre", "dez", "déc", "dec", "dic"],
}
MONTH = {name: m for m, names in _MONTHS.items() for name in names}
_mon_alt = "|".join(sorted((re.escape(n) for n in MONTH), key=len, reverse=True))

DATE_RE = re.compile(
    r"(?<![\d.])(?P<d1>[0-3]?\d)\s?(?:\.|er|°|º|o)?\s*(?:(?P<m1>[01]?\d)\s?\.\s?|(?P<mn>" + _mon_alt + r")\.?\s+)"
    r"(?P<y1>(?:1[89]|2\d)\d\d)(?![\d])"
    r"|(?<![\d])(?P<y2>(?:1[89]|2\d)\d\d)-(?P<m2>[01]\d)-(?P<d2>[0-3]\d)(?![\d])"
    r"|(?<![\d/])(?P<d3>[0-3]?\d)/(?P<m3>[01]?\d)/(?P<y3>(?:1[89]|2\d)\d\d)(?![\d])",
    re.IGNORECASE,
)


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).lower()


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def _from_match(mt: re.Match) -> str | None:
    g = mt.groupdict()
    if g["y1"]:
        m = int(g["m1"]) if g["m1"] else MONTH.get(_fold(g["mn"]))
        return _iso(int(g["y1"]), m, int(g["d1"])) if m else None
    if g["y2"]:
        return _iso(int(g["y2"]), int(g["m2"]), int(g["d2"]))
    return _iso(int(g["y3"]), int(g["m3"]), int(g["d3"]))


def find_dates(text: str) -> list[dict]:
    """All dates in text: [{"iso", "start", "end", "raw"}] (impossible dates dropped)."""
    out = []
    for mt in DATE_RE.finditer(text):
        iso = _from_match(mt)
        if iso:
            out.append(dict(iso=iso, start=mt.start(), end=mt.end(), raw=mt.group(0)))
    return out


def normalise_date(s: str) -> str | None:
    """ISO form of a string that is (essentially) one date; None if it is not exactly one valid date."""
    s = re.sub(r"\s+", " ", s.strip()).strip(" ,;:()")
    found = find_dates(s)
    if len(found) != 1:
        return None
    f = found[0]
    rest = (s[:f["start"]] + s[f["end"]:]).strip(" ,;:.")
    # allow a leading weekday / "vom" / "du" / "del" etc., but not other numbers
    if re.search(r"\d", rest):
        return None
    return f["iso"]
