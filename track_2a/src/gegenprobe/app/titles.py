"""The app's slice of OPD's affair metadata that the committed census tables do not carry: each affair's title as OPD
has it (title_de / title_fr / title_it) and the parliament's own page for it (OPD's url_external_*), for the 91,268
interventions with a recorded government answer (results/census/interventions.tsv.gz) and the affairs that have a v0.2
record (results/schema/v0_2/*_records.jsonl).

    python -m gegenprobe.app.titles      GP_OPD_RAW/affairs.ndjson.gz -> data/app/affair_titles.tsv.gz (no network)

The slice is committed, so `make site` builds from committed files only. Deterministic: rows sorted by affair id,
whitespace collapsed, a title that repeats another language's title verbatim is left empty, gzip without a timestamp.
Licence: CDLA-Permissive-2.0 (data/LICENSE), derived from OpenParlData.ch.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import sys
from pathlib import Path

from ..paths import DATA, OPD_RAW, RESULTS

OUT = DATA / "app" / "affair_titles.tsv.gz"
COLS = ("affair_id", "title_de", "title_fr", "title_it", "url_external")
LANGS = ("de", "fr", "it")
RECORD_SETS = ("p3", "p3b", "p5", "p8", "fed")


def record_ids() -> set[int]:
    out = set()
    for s in RECORD_SETS:
        p = RESULTS / "schema" / "v0_2" / f"{s}_records.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.add(int(json.loads(line)["ref"]["opd_id"]))
    return out


def wanted() -> set[int]:
    with gzip.open(RESULTS / "census" / "interventions.tsv.gz", "rt", encoding="utf-8") as f:
        ids = {int(r["affair_id"]) for r in csv.DictReader(f, delimiter="\t")}
    return ids | record_ids()


def _clean(s) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def row_of(d: dict) -> dict:
    titles, seen = {}, set()
    for lg in LANGS:
        t = _clean(d.get(f"title_{lg}"))
        titles[f"title_{lg}"] = "" if t in seen else t
        if t:
            seen.add(t)
    url = next((u for u in (_clean(d.get(f"url_external_{lg}")) for lg in ("de", "fr", "it", "rm")) if u), "")
    return dict(affair_id=int(d["id"]), **titles, url_external=url)


def vendor(raw: Path = OPD_RAW / "affairs.ndjson.gz", out: Path = OUT) -> dict:
    ids = wanted()
    rows = {}
    with gzip.open(raw, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            try:
                aid = int(d["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if aid in ids:
                rows[aid] = row_of(d)
    buf = io.StringIO()
    w = csv.DictWriter(buf, COLS, delimiter="\t", lineterminator="\n")
    w.writeheader()
    for aid in sorted(rows):
        w.writerow(rows[aid])
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh, gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0, compresslevel=9) as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    return dict(out=str(out.relative_to(DATA.parent)), rows=len(rows), missing=sorted(ids - set(rows))[:20],
                bytes=out.stat().st_size)


def load(path: Path = OUT) -> dict[int, dict]:
    """affair_id -> {title_de, title_fr, title_it, url_external} (empty strings where OPD has none)."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return {int(r["affair_id"]): r for r in csv.DictReader(f, delimiter="\t")}


def main(argv: list[str]) -> int:
    print(json.dumps(vendor(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
