"""Accepted values of the converter's --affair-type (and the `affair_type` batch column).

The frozen rules (convert/rules.py) compare the affair type with OPD's harmonised English type names: "Interpellation",
"Question" and "Question time" get recommendation `not_applicable` (no government recommendation is expected). Before
this fix any other spelling ("Question écrite", "question") was passed through unchanged and silently treated as "some
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
  * OPD type names derived from the committed census table (data/census/affairs.tsv.gz) by `derive()`: a type_raw whose
    affairs OPD maps, where it maps them at all, to one harmonised type (>= 98% of >= 100 mapped affairs, and at least
    half of all its affairs mapped). Written to data/convert/affair_type_aliases.json with the counts (e.g. "Auftrag":
    1,016 of 1,018 mapped affairs are Motion, in SO and GR; "Dringliches Postulat", "Interpellation écrite", ...).
    Regenerate: python -m gegenprobe.convert.affair_types derive
  * per parliament, the `affair_types` map of a settings/anchors file (convert/body_settings.py), e.g. {"Auftrag": "motion"}
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


ALIAS_FILE = DATA / "convert" / "affair_type_aliases.json"
DERIVE_MIN_MAPPED = 100   # affairs with a harmonised type behind a type_raw
DERIVE_MIN_SHARE = 0.98   # of those, the share in the top harmonised type
DERIVE_MIN_COVER = 0.5    # affairs with any harmonised type / all affairs of that type_raw


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
    for raw, key in derived_aliases().items():
        t.setdefault(_norm(raw), key)
    return t


def derived_aliases() -> dict[str, str]:
    try:
        return {a["type_raw"]: a["key"] for a in json.loads(ALIAS_FILE.read_text(encoding="utf-8"))["aliases"]}
    except (OSError, ValueError, KeyError):
        return {}


def derive(census: str | None = None, write: bool = True) -> dict:
    """OPD type_raw -> vocabulary key, from OPD's own harmonisation in the committed census affairs table. Deterministic;
    writes ALIAS_FILE. Spellings already accepted (vocabulary, labels, harmonised names, RAW_ALIASES) are not repeated."""
    import collections
    import csv
    import gzip

    base: dict[str, str] = {}
    for entry in json.loads((DATA / "schema" / "affair_types.json").read_text(encoding="utf-8")):
        for v in [entry["key"], *entry["labels"].values()]:
            base.setdefault(_norm(v), entry["key"])
    name2key = {_norm(n): k for k, n in OPD_NAME.items() if n}
    base.update(name2key)
    base.update({_norm(r): k for r, k in RAW_ALIASES.items()})
    path = census or str(DATA / "census" / "affairs.tsv.gz")
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    bodies: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            raw = _norm(r.get("type_raw") or "")
            if raw:
                counts[raw][_norm(r.get("type_h") or "")] += 1
                bodies[raw][r.get("body") or ""] += 1
    out = []
    for raw, cnt in counts.items():
        mapped = {t: n for t, n in cnt.items() if t}
        n_mapped, n_all = sum(mapped.values()), sum(cnt.values())
        if raw in base or n_mapped < DERIVE_MIN_MAPPED or n_mapped < DERIVE_MIN_COVER * n_all:
            continue
        top, n_top = max(mapped.items(), key=lambda x: (x[1], x[0]))
        if top not in name2key or n_top < DERIVE_MIN_SHARE * n_mapped:
            continue
        out.append(dict(type_raw=raw, key=name2key[top], opd_harmonised=OPD_NAME[name2key[top]], affairs_mapped=n_mapped,
                        affairs_to_key=n_top, affairs_total=n_all, bodies=len(bodies[raw]),
                        top_bodies=[b for b, _ in bodies[raw].most_common(3)]))
    out.sort(key=lambda a: (-a["affairs_to_key"], a["type_raw"]))
    doc = dict(source="data/census/affairs.tsv.gz (OPD affairs export, 6 Oct 2026 census): columns type_raw, type_h",
               rule=f"type_raw with >= {DERIVE_MIN_MAPPED} affairs that OPD maps to a harmonised type, >= "
                    f"{DERIVE_MIN_SHARE:.0%} of them to one type, and >= {DERIVE_MIN_COVER:.0%} of all its affairs mapped; "
                    "spellings already accepted are not repeated",
               generated_by="python -m gegenprobe.convert.affair_types derive", aliases=out)
    if write:
        ALIAS_FILE.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


TABLE = _table()
KEYS = [e["key"] for e in json.loads((DATA / "schema" / "affair_types.json").read_text(encoding="utf-8"))]


class UnknownAffairType(ValueError):
    pass


def normalize(value: str | None, extra: dict[str, str] | None = None) -> str | None:
    """-> OPD's harmonised English name (what the frozen rules compare with), None for empty/unknown-type input.
    `extra`: per-parliament aliases (normalised spelling -> vocabulary key) from a settings file; they win.
    Raises UnknownAffairType for a value that is not in the vocabulary."""
    if value is None or not str(value).strip():
        return None
    key = (extra or {}).get(_norm(str(value))) or TABLE.get(_norm(str(value)))
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


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["derive"]:
        d = derive()
        print(f"{len(d['aliases'])} derived aliases -> {ALIAS_FILE}")
