"""Stream every docs_*.ndjson.gz and texts_*.ndjson.gz export from files.openparldata.ch and keep per-row metadata only (no
full text): text status, length, boilerplate fingerprint, answer-marker flags. One request per file via gegenprobe.net
(UA hackapertus-research/0.1, >= 1.2 s per host). Ported from spikes/recovery/scripts/scan_exports.py; output format
identical (GP_DOCS_META/<part>/{docs,texts}_meta.jsonl.gz), so census/extract.py reads either.

usage: python -m gegenprobe.census.scan <outdir> [body_key ... | -body_key ...] [@docs|@texts]
  ≈ 6 GB transfer, ≈ 25 min CPU (parsing-bound). The 8 Oct 2026 scan used for the committed census is in four parts A–D.

Bytes: every file is read through a counting wrapper (compressed bytes as they come off the wire, every attempt counted);
<outdir>/stream_bytes.json records them per file next to the size index.json declares. The nightly job sums these into
run.json (`bytes.docs_texts_streamed`). A file read from GP_EXPORTS_DIR is counted the same way and marked `local`.
"""

from __future__ import annotations

import collections
import gzip
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

from .. import net
from gegenprobe.compliance import fetchguard
from . import defs

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

INDEX = "https://files.openparldata.ch/exports/index.json"


def doc_row(d: dict, bk: str) -> tuple[dict, str, str]:
    t = d.get("text")
    st = defs.text_status(t)
    s = defs.norm((t or "")[:25000])
    h = hashlib.sha1(s[:300].encode()).hexdigest()[:12] if s else ""
    flags = [k for k, rx in defs.TEXT_FLAGS.items() if rx.search(s)]
    cat = d.get("category") or {}
    row = dict(
        id=d["id"],
        b=d.get("body_key") or bk,
        a=d.get("affair_id"),
        m=d.get("meeting_id"),
        ag=d.get("agenda_id"),
        name=d.get("name"),
        cat=cat.get("de") or cat.get("fr") or cat.get("it"),
        ch=d.get("category_harmonized"),
        lang=d.get("language"),
        date=d.get("date"),
        size=d.get("size"),
        url=d.get("url"),
        st=st,
        n=len((t or "").strip()),
        h=h,
        fl=flags,
    )
    return row, h, s[:200]


def text_row(d: dict, bk: str) -> dict:
    tx = {L: d.get("text_" + L) for L in ("de", "fr", "it", "rm")}
    lens = {L: len(defs.norm(re.sub(r"<[^>]+>", " ", v or ""))) for L, v in tx.items()}
    ph = [L for L, v in tx.items() if v and len(v) < 4000 and defs.PLACEHOLDERS[1][1].search(v)]
    return dict(
        id=d["id"],
        b=d.get("body_key") or bk,
        a=d.get("affair_id"),
        type=d.get("type_de") or d.get("type_fr") or d.get("type_it"),
        date=d.get("text_date"),
        lens=lens,
        ph=ph,
    )


class CountingReader:
    """Read-through wrapper that counts the bytes read from the underlying (compressed) stream."""

    def __init__(self, raw):
        self.raw, self.n = raw, 0

    def read(self, size: int = -1) -> bytes:
        b = self.raw.read(size)
        self.n += len(b)
        return b


def stream_counted(url: str, tally: dict):
    """net.stream_ndjson_gz (same open_url: robots, pacing, retries, GP_EXPORTS_DIR) plus a byte count in tally['bytes']."""
    r = net.open_url(url, timeout=600)
    c = CountingReader(r)
    tally["local"] = net.local_exports(url).startswith("file:")
    try:
        yield from io.TextIOWrapper(gzip.GzipFile(fileobj=c), encoding="utf-8")
    finally:
        tally["bytes"] = tally.get("bytes", 0) + c.n
        r.close()


def scan(out: Path, only: set[str], skip: set[str], ents: set[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    idx = json.loads(net.get(INDEX))
    heads = collections.defaultdict(collections.Counter)
    sample: dict[str, str] = {}
    counted: dict[str, dict] = {}
    with gzip.open(out / "docs_meta.jsonl.gz", "wt") as dout, gzip.open(out / "texts_meta.jsonl.gz", "wt") as tout:
        for ent in idx["files"]:
            if ent["entity"] not in ents:
                continue
            for f in sorted(ent["files"], key=lambda x: x["size"]):
                bk = f["filename"].split("_", 1)[1].split(".")[0]
                if (only and bk not in only) or bk in skip:
                    continue
                tally = counted.setdefault(f["filename"], dict(declared=f.get("size"), bytes=0, attempts=0))
                for attempt in range(4):
                    t0, n, ok = time.time(), 0, False
                    tally["attempts"] += 1
                    lines = stream_counted(f["url"], tally)
                    try:
                        for line in lines:
                            d = json.loads(line)
                            n += 1
                            if ent["entity"] == "docs":
                                row, h, s = doc_row(d, bk)
                                if h:
                                    heads[bk][h] += 1
                                    sample.setdefault(h, s)
                                dout.write(json.dumps(row, ensure_ascii=False) + "\n")
                            else:
                                tout.write(json.dumps(text_row(d, bk), ensure_ascii=False) + "\n")
                        ok = True
                    except Exception as ex:  # network hiccup: retry the whole file (rows are deduplicated by id later)
                        print("FAIL", f["filename"], n, ex, flush=True)
                        time.sleep(30 * (attempt + 1))
                    finally:
                        lines.close()  # counts the bytes of a partial attempt too
                    print(ent["entity"], bk, n, f"{time.time() - t0:.0f}s", "complete" if ok else "partial", flush=True)
                    if ok:
                        break
    (out / "stream_bytes.json").write_text(json.dumps(dict(
        bytes=sum(v["bytes"] for v in counted.values()), declared=sum(v["declared"] or 0 for v in counted.values()),
        files=counted), indent=1))
    top = {bk: [(h, c, sample[h]) for h, c in cnt.most_common(8) if c >= 20] for bk, cnt in heads.items()}
    (out / "boilerplate_heads.json").write_text(json.dumps(top, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    args = sys.argv[1:]
    scan(
        Path(args[0]),
        {x for x in args[1:] if not x.startswith(("-", "@"))},
        {x[1:] for x in args[1:] if x.startswith("-")},
        {x[1:] for x in args[1:] if x.startswith("@")} or {"docs", "texts"},
    )
