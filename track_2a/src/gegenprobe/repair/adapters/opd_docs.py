"""OPD's own documents for the adapter targets, with their stored text, from the docs exports on files.openparldata.ch.

The census reads document names and a few text markers; it does not keep texts. Several parliaments file the
government answer on the affair under a generic name (the intervention's title, "Vorstoss - V2017.154", a file name), so
the census cannot tell it from the question. Before asking the parliament's site, an adapter looks at what OPD already
holds on the affair. This module streams docs_<body>.ndjson.gz once per body and keeps, for the target affairs only,
each document's id, name, URLs, hash, format, language, date and text. The cache lives in WORK (never committed).

usage: python -m gegenprobe.repair.adapters.opd_docs [BODY ...]     (default: every body with >= 15 target affairs)
"""
from __future__ import annotations

import gzip
import json
import sys
import time

from ... import net
from gegenprobe.compliance import fetchguard
from ...paths import WORK
from . import targets

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

DOCS_URL = "https://files.openparldata.ch/exports/docs/docs_{body}.ndjson.gz"
CACHE = WORK / "adapters" / "opd_docs"
KEEP = ("id", "affair_id", "agenda_id", "meeting_id", "name", "url", "url_oparl", "hash", "format", "language", "date",
        "size", "category_de", "category_fr", "category_it", "category_harmonized", "updated_at")


def path(body: str):
    return CACHE / f"{body}.jsonl.gz"


def snapshot(body: str, affair_ids: set[int]) -> dict:
    """Stream the body's docs export; write the target affairs' documents (with text). Atomic: .part then rename."""
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / f"{body}.jsonl.gz.part"
    utmp = CACHE / f"{body}.urls.jsonl.gz.part"
    n = kept = 0
    t0 = time.time()
    with gzip.open(tmp, "wt", encoding="utf-8") as out, gzip.open(utmp, "wt", encoding="utf-8") as uout:
        for line in net.stream_ndjson_gz(DOCS_URL.format(body=body)):
            n += 1
            d = json.loads(line)
            uout.write(json.dumps(dict(id=d.get("id"), url=d.get("url"), affair_id=d.get("affair_id"),
                                       agenda_id=d.get("agenda_id"), meeting_id=d.get("meeting_id"),
                                       name=(d.get("name") or "")[:120], chars=len((d.get("text") or "").strip())),
                                  ensure_ascii=False) + "\n")
            if d.get("affair_id") not in affair_ids:
                continue
            row = {k: d.get(k) for k in KEEP}
            row["text"] = d.get("text") or ""
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            kept += 1
    tmp.replace(path(body))
    utmp.replace(CACHE / f"{body}.urls.jsonl.gz")
    meta = dict(body=body, url=DOCS_URL.format(body=body), rows=n, kept=kept, seconds=round(time.time() - t0, 1),
                fetched=time.strftime("%Y-%m-%d"))
    (CACHE / f"{body}.meta.json").write_text(json.dumps(meta))
    return meta


def load(body: str) -> dict[int, list[dict]]:
    """affair id -> OPD documents (with text) from the cached snapshot; {} if the body was never snapshotted."""
    out: dict[int, list[dict]] = {}
    p = path(body)
    if not p.exists():
        return out
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out.setdefault(d["affair_id"], []).append(d)
    return out


def url_index(body: str) -> list[dict]:
    """Every OPD document of the body (id, url, parents, name, text length), for relink detection: a source document
    whose URL OPD already holds is re-attached, not fetched."""
    p = CACHE / f"{body}.urls.jsonl.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def meta(body: str) -> dict | None:
    p = CACHE / f"{body}.meta.json"
    return json.loads(p.read_text()) if p.exists() else None


def main(argv: list[str]) -> int:
    xs = targets.load()
    by_body: dict[str, set[int]] = {}
    for x in xs:
        by_body.setdefault(x["body"], set()).add(x["id"])
    bodies = [a for a in argv if not a.startswith("--")] or [
        b for b, ids in sorted(by_body.items(), key=lambda kv: -len(kv[1])) if len(ids) >= 15]
    for b in bodies:
        if b == "--force":
            continue
        if path(b).exists() and (CACHE / f"{b}.urls.jsonl.gz").exists() and "--force" not in argv:
            print(b, "cached", flush=True)
            continue
        try:
            print(json.dumps(snapshot(b, by_body.get(b, set()))), flush=True)
        except Exception as e:  # one body failing must not stop the others
            print(b, "ERROR", type(e).__name__, str(e)[:200], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
