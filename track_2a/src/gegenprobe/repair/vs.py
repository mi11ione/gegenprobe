"""Valais (VS): "missing" written answers that are in fact oral answers.

The VS parliament attaches an `_ANT` (answer) document to every intervention. When the Conseil d'État answered orally in
the session, that document is a one-line pointer, not a lost written answer:
    "cf. réponse orale du Conseil d'Etat / s. mündliche Antwort des Staatsrats"   (87 characters in OPD's text)

Stub rule (precise, applied to OPD's own `text` of the doc):
  body == VS  ∧  doc name matches /_ANT\\b/  ∧  len(text.strip()) < 200
  ∧  text matches /r[ée]ponse orale|m[üu]ndliche Antwort/ (case-insensitive)
An affair whose answer documents are all stubs, and which the funnel counts as a gap, is retyped: answer_link_status `oral`,
action `retype_oral`. The answer exists (it was given orally and is in the session minutes); no document is missing.

usage:
  python -m gegenprobe.repair.vs scan    stream docs_VS from files.openparldata.ch once; keep (id, affair, name, len, stub) only
  python -m gegenprobe.repair.vs list    repair_VS.{tsv,json} for the VS funnel-gap affairs
"""

from __future__ import annotations

import collections
import gzip
import json
import re
import sys
import time

from .. import net
from gegenprobe.compliance import fetchguard
from ..paths import DATA, WORK
from ..stats import wilson_pct
from .common import OUT, dump, iter_ndjson, write_rows

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

URL = "https://files.openparldata.ch/exports/docs/docs_VS.ndjson.gz"
SCAN = WORK / "vs_ant_docs.jsonl.gz"
ANT = re.compile(r"_ANT\b")
STUB = re.compile(r"r[ée]ponse orale|m[üu]ndliche Antwort", re.I)
GAP_IDS = DATA / "repair" / "vs_gap_ids.json"


def is_stub(name: str | None, text: str | None) -> bool:
    t = (text or "").strip()
    return bool(ANT.search(name or "")) and len(t) < 200 and bool(STUB.search(t))


def scan() -> dict:
    t0, n, k = time.time(), 0, 0
    with gzip.open(SCAN, "wt", encoding="utf-8") as out:
        for line in net.stream_ndjson_gz(URL):
            d = json.loads(line)
            n += 1
            if not ANT.search(d.get("name") or ""):
                continue
            t = d.get("text") or ""
            k += 1
            out.write(
                json.dumps(
                    dict(
                        id=d["id"],
                        a=d.get("affair_id"),
                        name=d.get("name"),
                        n=len(t.strip()),
                        stub=is_stub(d.get("name"), t),
                        head=t.strip()[:100] if len(t.strip()) < 200 else None,
                    ),
                    ensure_ascii=False,
                )
                + "\n"
            )
    return dict(url=URL, rows=n, ant_docs=k, secs=round(time.time() - t0))


def build() -> tuple[list[dict], dict]:
    gap = json.loads(GAP_IDS.read_text())
    gap_ids = {g["id"]: g for g in gap["rows"]}
    num = {a["id"]: a["number"] for a in iter_ndjson("affairs") if a["body_key"] == "VS"}
    by_aff = collections.defaultdict(list)
    with gzip.open(SCAN, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["a"]:
                by_aff[d["a"]].append(d)
    rows, c = [], collections.Counter()
    short_heads = collections.Counter()
    for aid in sorted(gap_ids):
        ds = by_aff.get(aid, [])
        c["gap"] += 1
        c["gap_with_ant_doc"] += bool(ds)
        for d in ds:
            if d["n"] < 200:
                short_heads[re.sub(r"\d+", "#", d["head"] or "")[:60]] += 1
        if ds and all(d["stub"] for d in ds):
            c["retype_oral"] += 1
            rows.append(
                dict(
                    body="VS",
                    affair_id=aid,
                    affair_number=num.get(aid),
                    action="retype_oral",
                    opd_doc_id=ds[0]["id"],
                    source_doc_uid=None,
                    source_doc_title=ds[0]["name"],
                    source_url=None,
                    checks=dict(ant_docs=len(ds), all_stub=True, stub_chars=[d["n"] for d in ds]),
                    verified=True,
                    note="_ANT document is the oral-answer pointer 'cf. réponse orale du Conseil d'Etat'",
                )
            )
        elif ds and any(d["stub"] for d in ds):
            c["mixed_stub_and_text"] += 1
    stats = dict(
        counts=dict(c),
        short_text_heads=short_heads.most_common(10),
        stub_share_of_gap_with_ant=dict(
            k=c["retype_oral"], n=c["gap_with_ant_doc"], ci=wilson_pct(c["retype_oral"], c["gap_with_ant_doc"])
        ),
    )
    return rows, stats


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "scan":
        r = scan()
        dump(OUT / "vs_scan.json", r)
        print(r)
    elif cmd == "list":
        rows, stats = build()
        write_rows("VS", rows)
        dump(OUT / "vs_summary.json", stats)
        print(stats)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
