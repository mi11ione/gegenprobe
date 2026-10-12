"""OPD's own copies of the P2 documents, for the `make run` step rederive_apertus (eval.replay_all).

    python -m eval.rederive_copies build    stream the docs exports of the P2 bodies (files.openparldata.ch/exports/docs/,
                                            through gegenprobe.net: RFC 9309 robots.txt, fail-closed, 1.2 s per host) and
                                            write data/rederive/p2_opd_copies.json: OPD doc id -> `url_oparl`
                                            (files.openparldata.ch/doc/<body>/<hash>), for every P2 document OPD keeps a
                                            copy of. No document is fetched; ids and URLs only.
    python -m eval.rederive_copies check    exit 1 unless every P2 document has an entry (a copy URL or null)

Why: in a cold `make run` some P2 sources cannot be read (sieldocs.vd.ch answers robots.txt with HTTP 503, so the fetch
path treats the host as disallowed for the run, fail-closed; other hosts time out). The step then reads the document
from OPD's own copy instead; `pdftext.fetch_pdf(expect_sha256=...)` accepts it only when its sha256 equals the committed
one (data/gold2/p2_docs.jsonl), so a copy can never stand in for a different file. The P1 held-out set is not mapped
(its 16 bodies' exports are 2.2 GB; P1 reached 151/154 in J5's cold run).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from gegenprobe.paths import DATA

MAP = DATA / "rederive" / "p2_opd_copies.json"
P2_DOCS = DATA / "gold2" / "p2_docs.jsonl"
OPD_COPY_PREFIX = "https://files.openparldata.ch/doc/"
_FIRST_ID = re.compile(r'\s*\{\s*"id"\s*:\s*(\d+)')


def _docs(path: Path = P2_DOCS) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def load(path: Path = MAP) -> dict[int, str]:
    """doc id -> OPD copy URL ({} when the map is not committed; entries without a copy are left out)."""
    if not path.exists():
        return {}
    m = json.loads(path.read_text(encoding="utf-8"))["copies"]
    return {int(k): v for k, v in m.items() if isinstance(v, str) and v.startswith(OPD_COPY_PREFIX)}


def build() -> dict:
    from gegenprobe import net
    from gegenprobe.compliance import fetchguard

    fetchguard.ensure()
    docs = _docs()
    want: dict[str, set[int]] = {}
    for d in docs:
        want.setdefault(str(d["body"]), set()).add(int(d["doc_id"]))
    copies: dict[str, str | None] = {str(d["doc_id"]): None for d in docs}
    for body in sorted(want):
        ids = set(want[body])
        for line in net.stream_ndjson_gz(f"{net.EXPORTS_PREFIX}docs/docs_{body}.ndjson.gz"):
            m = _FIRST_ID.match(line)
            if m and int(m.group(1)) not in ids:
                continue
            x = json.loads(line)
            if x.get("id") in ids:
                u = x.get("url_oparl")
                copies[str(x["id"])] = u if isinstance(u, str) and u.startswith(OPD_COPY_PREFIX) else None
                ids.discard(x["id"])
                if not ids:
                    break
        print(f"docs_{body}: {len(want[body]) - len(ids)}/{len(want[body])} rows found", file=sys.stderr, flush=True)
    out = dict(
        note=("OPD's own copy (url_oparl in OPD's docs export) of each P2 document (data/gold2/p2_docs.jsonl), read by "
              "eval.replay_all.rederive_apertus when the source cannot be read; the copy is used only if its sha256 "
              "equals the committed one. null: OPD's export keeps no copy of the document."),
        command="PYTHONPATH=src:. python -m eval.rederive_copies build",
        exports="https://files.openparldata.ch/exports/docs/docs_<body>.ndjson.gz",
        n_docs=len(docs), n_with_copy=sum(v is not None for v in copies.values()),
        copies=dict(sorted(copies.items(), key=lambda kv: int(kv[0]))),
    )
    MAP.parent.mkdir(parents=True, exist_ok=True)
    MAP.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def check() -> list[str]:
    """Problems with the committed map: a P2 document without an entry, or an entry for no P2 document."""
    if not MAP.exists():
        return [f"{MAP} not committed"]
    keys = set(json.loads(MAP.read_text(encoding="utf-8"))["copies"])
    ids = {str(d["doc_id"]) for d in _docs()}
    return [f"no entry for {i}" for i in sorted(ids - keys)] + [f"entry for no P2 document: {i}" for i in sorted(keys - ids)]


def main(argv: list[str]) -> int:
    if argv[:1] == ["build"]:
        out = build()
        print(f"{MAP}: {out['n_with_copy']}/{out['n_docs']} P2 documents with an OPD copy")
        return 0
    bad = check()
    print("\n".join(bad) if bad else f"{MAP}: every P2 document has an entry")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
