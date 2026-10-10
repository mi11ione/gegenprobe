"""Shared helpers for the repair routes: OPD export readers, answer-heading lexicons, multilingual date parsing, and the
OPD-export-style output writer (repair_<BODY>.tsv / .json).

Every repair row has the same plain columns (no JSON inside cells), so OPD can ingest any route with one importer:
  body, affair_id, affair_number, action, proposed_action, opd_doc_id, source_doc_uid, source_doc_title, source_url,
  snapshot, check_identity, check_heading, check_decision_nr, check_decision_date, check_answer_event_dates,
  check_date_eq_event, check_detail, verified, note
  action ∈ {relink, agenda_join, fetch, retype_oral, ocr, placeholder_replace, review}
  proposed_action  the route's action; equals `action` unless the row failed its per-row check and became `review`
  snapshot  the export dates the row was computed from (OPD exports, canton OGD)
  check_*   per-row document checks where they were run (BE relink/fetch: every row, repair.verify_all); empty = not run
  check_detail  other routes' row facts as plain `key=value; key=value`
  verified = true | false | empty (empty: not checked per row; the route's precision is measured on a sample, summary.json)
Per body, one combined file repair_<BODY>.tsv/.json, and for bodies with more than one action one file per action
(repair_<BODY>_<action>.tsv/.json).
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
    "proposed_action",
    "opd_doc_id",
    "source_doc_uid",
    "source_doc_title",
    "source_url",
    "snapshot",
    "check_identity",
    "check_heading",
    "check_decision_nr",
    "check_decision_date",
    "check_answer_event_dates",
    "check_date_eq_event",
    "check_detail",
    "verified",
    "note",
]
CHECK_COLS = [c for c in COLS if c.startswith("check_") and c != "check_detail"]
ACTIONS = {"relink", "agenda_join", "fetch", "retype_oral", "ocr", "placeholder_replace", "review"}


def snapshot() -> str:
    """Export dates the repair rows are computed from: the OPD export index and the canton OGD download."""
    from ..paths import DATA, WORK
    parts = []
    meta = DATA / "census" / "meta.json"
    if meta.exists():
        idx = json.loads(meta.read_text())["inputs"].get("index.json", {})
        if idx.get("generated_at"):
            parts.append(f"opd_exports {idx['generated_at'][:10]}")
    ogd = WORK / "be_ogd" / "dokument.csv"
    if ogd.exists():
        parts.append("be_ogd " + dt.datetime.fromtimestamp(ogd.resolve().stat().st_mtime, dt.timezone.utc).date().isoformat())
    return "; ".join(parts)


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, list | tuple):
        return " ".join(str(x) for x in v)
    return str(v)

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


def flat(r: dict, snap: str = "") -> dict:
    """Row -> plain columns. A legacy `checks` dict is spread: known keys to check_* columns, the rest to check_detail."""
    row = {k: r.get(k) for k in COLS}
    row["proposed_action"] = r.get("proposed_action") or r["action"]
    row["snapshot"] = r.get("snapshot") or snap
    chk = r.get("checks")
    if isinstance(chk, dict):
        rest = {k: v for k, v in chk.items() if f"check_{k}" not in CHECK_COLS}
        for k, v in chk.items():
            if f"check_{k}" in CHECK_COLS:
                row[f"check_{k}"] = v
        row["check_detail"] = "; ".join(f"{k}={_cell(v)}" for k, v in sorted(rest.items()) if v not in (None, ""))
    return {k: _cell(v) for k, v in row.items()}


def _write(tsv: Path, js: Path, body: str, rows: list[dict], gz: bool) -> None:
    opener = (
        (lambda p: gzip.open(p, "wt", encoding="utf-8", newline=""))
        if gz
        else (lambda p: open(p, "w", encoding="utf-8", newline=""))
    )
    with opener(tsv) as f:
        w = csv.DictWriter(f, COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with opener(js) as f:
        f.write(
            json.dumps(
                dict(body=body, n=len(rows), columns=COLS, rows=rows), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        )


def write_rows(body: str, rows: list[dict], out: Path = OUT) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    for r in rows:
        assert r["action"] in ACTIONS, r["action"]
    snap = snapshot()
    flat_rows = [flat(r, snap) for r in rows]
    gz = len(rows) > GZIP_ABOVE
    ext = ".gz" if gz else ""
    for old in [*out.glob(f"repair_{body}.*"), *(p for a in ACTIONS for p in out.glob(f"repair_{body}_{a}.*"))]:
        old.unlink()
    tsv, js = out / f"repair_{body}.tsv{ext}", out / f"repair_{body}.json{ext}"
    _write(tsv, js, body, flat_rows, gz)
    actions = sorted({r["action"] for r in flat_rows})
    if len(actions) > 1:
        for a in actions:
            sel = [r for r in flat_rows if r["action"] == a]
            g = len(sel) > GZIP_ABOVE
            e = ".gz" if g else ""
            _write(out / f"repair_{body}_{a}.tsv{e}", out / f"repair_{body}_{a}.json{e}", body, sel, g)
    return tsv, js


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True))
