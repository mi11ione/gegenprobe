"""Shared helpers for the repair routes: OPD export readers, answer-heading lexicons, multilingual date parsing, and the
OPD-export-style output writer (repair_<BODY>.tsv / .json).

Every repair row has the same columns, so OPD can ingest any route with one importer:
  body, affair_id, affair_number, action, opd_doc_id, source_doc_uid, source_doc_title, source_url, checks, verified, note
  action ∈ {relink, agenda_join, fetch, retype_oral, ocr, placeholder_replace}
  checks  = JSON object of named boolean/string checks (null when not run for that row)
  verified = true | false | null (null: not checked; the route's precision is measured on a sample, see summary.json)
"""

from __future__ import annotations

import csv
import datetime as dt
import glob
import gzip
import json
import re
from pathlib import Path

from ..paths import DOCS_META, OPD_RAW, RESULTS

OUT = RESULTS / "repair"
COLS = [
    "body",
    "affair_id",
    "affair_number",
    "action",
    "opd_doc_id",
    "source_doc_uid",
    "source_doc_title",
    "source_url",
    "checks",
    "verified",
    "note",
]
ACTIONS = {"relink", "agenda_join", "fetch", "retype_oral", "ocr", "placeholder_replace"}

# ---------------------------------------------------------------- answer headings (DE / FR / IT)
ANSWER_HEADING = re.compile(
    r"Antwort des (Regierungsrate?s?|Bundesrate?s?|Stadtrate?s?|Gemeinderate?s?|Kleinen Rate?s?|Staatsrate?s?)|"
    r"Antwort Regierungsrat|Der Regierungsrat beantwortet|"
    r"Stellungnahme des (Regierungsrate?s?|Bundesrate?s?|Stadtrate?s?|Gemeinderate?s?)|"
    r"R[ée]ponse du (Conseil[- ]ex[ée]cutif|Conseil d.[ÉE]tat|Conseil communal|Conseil municipal|Gouvernement|"
    r"Conseil f[ée]d[ée]ral)|"
    r"Le Conseil d.[ÉE]tat r[ée]pond|"
    r"Risposta del (Consiglio di Stato|Municipio|Consiglio federale)|Il Consiglio di Stato risponde|"
    r"Beantwortung der (Interpellation|Anfrage|Frage|Kleinen Anfrage)",
    re.I,
)

MONTHS = {
    **{
        m: i + 1
        for i, m in enumerate(
            [
                "januar",
                "februar",
                "märz",
                "april",
                "mai",
                "juni",
                "juli",
                "august",
                "september",
                "oktober",
                "november",
                "dezember",
            ]
        )
    },
    "maerz": 3,
    "marz": 3,
    **{
        m: i + 1
        for i, m in enumerate(
            [
                "janvier",
                "février",
                "mars",
                "avril",
                "mai",
                "juin",
                "juillet",
                "août",
                "septembre",
                "octobre",
                "novembre",
                "décembre",
            ]
        )
    },
    "fevrier": 2,
    "aout": 8,
    "decembre": 12,
    **{
        m: i + 1
        for i, m in enumerate(
            [
                "gennaio",
                "febbraio",
                "marzo",
                "aprile",
                "maggio",
                "giugno",
                "luglio",
                "agosto",
                "settembre",
                "ottobre",
                "novembre",
                "dicembre",
            ]
        )
    },
}
_MON_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_RX = re.compile(r"\b(\d{1,2})(?:\.|er|°)?\s*(?:(\d{1,2})\.\s*|(" + _MON_RX + r")\s+)(\d{4})\b", re.I)


def iso_date(day: str, month_num: str | None, month_name: str | None, year: str) -> str | None:
    mo = int(month_num) if month_num else MONTHS.get((month_name or "").lower())
    try:
        return dt.date(int(year), mo, int(day)).isoformat() if mo else None
    except ValueError:
        return None


def parse_dates(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in DATE_RX.finditer(text):
        d = iso_date(m.group(1), m.group(2), m.group(3), m.group(4))
        if d:
            out.append((d, m.start(), m.end()))
    return out


def norm_ws(s: str) -> str:
    return re.sub(r"[ \t ]+", " ", s)


# ---------------------------------------------------------------- OPD export readers (cached snapshot; stream, no full text)
def iter_ndjson(name: str):
    with gzip.open(OPD_RAW / f"{name}.ndjson.gz", "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def iter_docs_meta(bodies: set[str] | None = None):
    """Rows of census.scan output (one per OPD doc, deduplicated by id): id, b, a, m, ag, name, cat, url, st, n, fl, ..."""
    seen = set()
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                if d["id"] in seen or (bodies and d["b"] not in bodies):
                    continue
                seen.add(d["id"])
                yield d


UID_IN_URL = re.compile(r"/([0-9a-f]{32})-\d+(?:/|\.pdf)")


def canton_uid(url: str | None) -> str | None:
    m = UID_IN_URL.search(url or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- output
GZIP_ABOVE = 5000  # rows; large files (CHE placeholders) are written gzipped to keep the repository small


def write_rows(body: str, rows: list[dict], out: Path = OUT) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    for r in rows:
        assert r["action"] in ACTIONS, r["action"]
    gz = len(rows) > GZIP_ABOVE
    ext = ".gz" if gz else ""
    for old in out.glob(f"repair_{body}.*"):
        old.unlink()
    tsv, js = out / f"repair_{body}.tsv{ext}", out / f"repair_{body}.json{ext}"
    opener = (
        (lambda p: gzip.open(p, "wt", encoding="utf-8", newline=""))
        if gz
        else (lambda p: open(p, "w", encoding="utf-8", newline=""))
    )
    with opener(tsv) as f:
        w = csv.DictWriter(f, COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            row = {k: r.get(k) for k in COLS}
            row["checks"] = json.dumps(r.get("checks"), ensure_ascii=False, sort_keys=True) if r.get("checks") is not None else ""
            row["verified"] = "" if r.get("verified") is None else str(bool(r["verified"])).lower()
            w.writerow({k: ("" if v is None else v) for k, v in row.items()})
    with opener(js) as f:
        f.write(
            json.dumps(
                dict(body=body, n=len(rows), columns=COLS, rows=rows), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        )
    return tsv, js


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True))
