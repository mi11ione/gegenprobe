"""Accepted values of the converter's --affair-type (and the `affair_type` batch column).

The frozen rules (convert/rules.py) compare the affair type with OPD's harmonised English type names: "Interpellation",
"Question" and "Question time" get recommendation `not_applicable` (no government recommendation is expected). Before
round 4 any other spelling ("Question écrite", "question") was passed through unchanged and silently treated as "some
other type". Now every value is normalised to OPD's harmonised name, and an unknown value is an error.

Accepted, case- and whitespace-insensitive:
  * the schema vocabulary keys (data/schema/affair_types.json, schema/vocab.py AFFAIR_TYPE_LABELS): motion, postulate,
    interpellation, question, question_time, ...
  * their DE / FR / IT / EN labels (Interpellanza, Anfrage, Written question, Heure des questions, ...)
  * OPD's harmonised English names as they appear in the exports (type_harmonized_en: Question, Question time,
    Government affairs, Postulate, Votaziun, ...)
  * common OPD type names (type_raw) that OPD's own data maps to one harmonised type (6 Oct 2026 census): Question
    écrite, Schriftliche Anfrage, Kleine Anfrage, Einfache Anfrage, Dringliche Interpellation, Fragestunde. Frage, Anzug,
    Vorlage (RAW_ALIASES)
"""
from __future__ import annotations

import json
import re
import unicodedata

from ..paths import DATA

# OPD harmonised English names (type_harmonized_en) per vocabulary key, as written in the exports (census affairs table,
# column type_h; two OPD spellings are odd: "Votaziun" for elections, "information document" in lower case).
OPD_NAME = {
    "miscellaneous": "Miscellaneous",
    "motion": "Motion",
    "postulate": "Postulate",
    "parliamentary_initiative": "Parliamentary initiative",
    "consultation": "Consultation",
    "election": "Votaziun",
    "popular_initiative": "Popular initiative",
    "interpellation": "Interpellation",
    "government_affair": "Government affairs",
    "question_time": "Question time",
    "petition": "Petition",
    "question": "Question",
    "amendment": "Amendment",
    "naturalisation": "Naturalisation",
    "information_document": "information document",
    "report": "Report",
    "approval_decision": "Parliamentary approval decision",
    # no OPD harmonised id: passed on as the English label
    "cantonal_initiative": "Cantonal initiative",
    "budget": "Budget",
    "unknown": None,
}

# OPD type_raw spellings -> vocabulary key (census 6 Oct 2026: each maps to this harmonised type in OPD's own data).
# Only spellings with OPD affairs behind them; counts = affairs with that type_raw and that harmonised type.
RAW_ALIASES = {
    "question écrite": "question",  # 4,992
    "schriftliche anfrage": "question",  # 5,747
    "kleine anfrage": "question",  # 5,468 (154 without a harmonised type)
    "kleine anfragen": "question",  # 3,389
    "einfache anfrage": "question",  # 4,340
    "dringliche interpellation": "interpellation",  # 1,409
    "fragestunde. frage": "question_time",  # 17,494
    "anzug": "postulate",  # 2,555
    "vorlage": "government_affair",  # 7,172
}


def _norm(v: str) -> str:
    v = unicodedata.normalize("NFC", v).strip().lower()
    return re.sub(r"[\s_]+", " ", v)


def _table() -> dict[str, str]:
    t: dict[str, str] = {}
    for entry in json.loads((DATA / "schema" / "affair_types.json").read_text(encoding="utf-8")):
        key = entry["key"]
        for v in [key, *entry["labels"].values()]:
            t.setdefault(_norm(v), key)
    for key, name in OPD_NAME.items():
        if name:
            t.setdefault(_norm(name), key)
    for raw, key in RAW_ALIASES.items():
        t.setdefault(_norm(raw), key)
    return t


TABLE = _table()
KEYS = [e["key"] for e in json.loads((DATA / "schema" / "affair_types.json").read_text(encoding="utf-8"))]


class UnknownAffairType(ValueError):
    pass


def normalize(value: str | None) -> str | None:
    """-> OPD's harmonised English name (what the frozen rules compare with), None for empty/unknown-type input.
    Raises UnknownAffairType for a value that is not in the vocabulary."""
    if value is None or not str(value).strip():
        return None
    key = TABLE.get(_norm(str(value)))
    if key is None:
        raise UnknownAffairType(
            f"unknown affair type {value!r}. Use a vocabulary key ({', '.join(KEYS)}), one of their DE/FR/IT/EN "
            "labels, or OPD's harmonised type name (e.g. Interpellation, Question, Question time, Motion, Postulate); "
            "list: data/schema/affair_types.json")
    return OPD_NAME[key]


def arg_type(value: str) -> str | None:
    """argparse `type=`: a clear error instead of a silently ignored value."""
    import argparse

    try:
        return normalize(value)
    except UnknownAffairType as e:
        raise argparse.ArgumentTypeError(str(e)) from None
