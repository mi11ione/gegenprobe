"""P2 sample: documents from parliaments the converter has never seen (eval/prereg2/PREREG2.md). Model-free.

Bodies, quotas, seed and length window are the ones written in PREREG2.md before drawing. Candidates come from the OPD
metadata scan (.work/docs_meta/part*/docs_meta.jsonl.gz); the document type is the same metadata guess as P1
(eval/gold/doctype.py), used only for stratification. PDFs are fetched politely (gegenprobe.net via pdftext.fetch_pdf);
a failure is replaced by the next candidate of the same body and type in seeded order and logged.

usage: python -m eval.gold2.sample [--fetch]
Out: data/gold2/p2_docs.jsonl (ids, url, sha256, pages, chars, extractor, body, lang, level, dtype; never the text),
     data/gold2/p2_fetch_log.jsonl
"""

from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import random
import urllib.parse

from eval.gold.doctype import doc_type
from eval.gold.sample import LEN_BAND, affair_types, lang_of, spike_exclusions
from gegenprobe import pdftext
from gegenprobe.paths import DATA, DOCS_META

SEED = 20261011
GOLD = DATA / "gold"
GOLD2 = DATA / "gold2"

# (cell, body, language or None, dtype, n) — exactly the PREREG2 table
QUOTAS = [
    ("de_canton", "NW", None, "answer", 6),
    ("de_canton", "OW", None, "answer", 2),
    ("de_canton", "SZ", None, "intervention", 2),
    ("de_canton", "GL", None, "intervention", 3),
    ("de_canton", "SH", None, "intervention", 3),
    ("de_canton", "AR", None, "intervention", 3),
    ("de_canton", "OW", None, "intervention", 2),
    ("de_canton", "NW", None, "intervention", 2),
    ("de_commune", "1061", None, "intervention", 4),
    ("de_commune", "247", None, "intervention", 3),
    ("de_commune", "62", None, "intervention", 3),
    ("fr_canton", "VD", "fr", "answer", 8),
    ("fr_commune", "6643", None, "answer", 3),
    ("fr_commune", "6266", None, "answer", 3),
    ("fr_commune", "2196", None, "answer", 3),
    ("fr_commune", "6421", None, "intervention", 3),
    ("fr_commune", "6266", None, "intervention", 3),
    ("it_commune", "5002", None, "answer", 6),
]
UNSEEN = {b for _, b, _, _, _ in QUOTAS}


def seen() -> tuple[set, set, set]:
    """(seen doc ids, seen affair ids, seen bodies) over P1 dev + held-out + every dev_ids source (spikes, audit, Bilanz)."""
    docs, affs = spike_exclusions()
    for v in json.load(open(GOLD / "dev_ids.json"))["ids"].values():
        docs |= {int(x) for x in v}
    for f in ("dev_docs.jsonl", "heldout_docs.jsonl"):
        for line in open(GOLD / f):
            x = json.loads(line)
            docs.add(x["doc_id"])
            if x.get("affair_id"):
                affs.add(x["affair_id"])
    bodies = set()
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt"):
            d = json.loads(line)
            if d["id"] in docs:
                bodies.add(d["b"])
    return docs, affs, bodies


def pool() -> dict:
    at = affair_types()
    out, ids = collections.defaultdict(list), set()
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt"):
            d = json.loads(line)
            if d["id"] in ids or d["b"] not in UNSEEN or not d.get("url"):
                continue
            ids.add(d["id"])
            if d["st"] != "ok" or not (LEN_BAND[0] <= d["n"] <= LEN_BAND[1]):
                continue
            d["a_type"] = at.get(d.get("a"))
            d["dtype"] = doc_type(d)
            d["lg"] = lang_of(d)
            if d["dtype"] in ("answer", "intervention"):
                out[(d["b"], d["dtype"])].append(d)
    return out


def fetch_one(d: dict) -> dict:
    try:
        url = urllib.parse.quote(d["url"], safe=":/?&=%#+,;@!$'()*~")
        sha, path = pdftext.fetch_pdf(url)
        t = pdftext.extract(sha, path, ocr=True, max_ocr_pages=6)
        chars = sum(len(p) for p in t["pages"])
        if chars < 1000:
            return dict(error=f"text too short after extraction ({chars} chars)")
        return dict(
            sha256=sha,
            pages=len(t["pages"]),
            chars=chars,
            tokens_est=chars // 4,
            extractor=t["extractor"],
            image_only=t["image_only"],
        )
    except Exception as e:  # robots disallow, not a PDF, HTTP error -> replaced from the same body and type
        return dict(error=f"{type(e).__name__}: {e}"[:200])


def draw(fetch: bool) -> list[dict]:
    s_docs, s_affs, s_bodies = seen()
    clash = UNSEEN & s_bodies
    assert not clash, f"bodies in the P2 list are not unseen: {clash}"
    pl = pool()
    chosen, log, used_affs = [], [], set(s_affs)
    for cell, body, lg, dt, n in QUOTAS:
        cands = sorted(
            (d for d in pl[(body, dt)] if d["id"] not in s_docs and (lg is None or d["lg"] == lg)), key=lambda d: d["id"]
        )
        random.Random(f"{SEED}:{body}:{dt}:{lg}").shuffle(cands)
        got = []
        for d in cands:
            if len(got) >= n:
                break
            if d.get("a") is not None and d["a"] in used_affs:
                continue
            r = fetch_one(d) if fetch else {}
            ok = "error" not in r
            log.append(dict(doc_id=d["id"], body=body, dtype=dt, accepted=ok, **r))
            if ok:
                if d.get("a") is not None:
                    used_affs.add(d["a"])
                got.append(dict(d, **r))
        if len(got) < n:
            log.append(dict(body=body, dtype=dt, shortfall=n - len(got), pool=len(cands)))
        for d in got:
            chosen.append(
                dict(
                    split="p2",
                    cell=cell,
                    level=cell.split("_")[1],
                    dtype=dt,
                    doc_id=d["id"],
                    body=body,
                    affair_id=d.get("a"),
                    affair_type=d.get("a_type"),
                    lang=d["lg"],
                    name=d.get("name"),
                    url=d["url"],
                    opd_text_status=d["st"],
                    opd_chars=d["n"],
                    **{k: d.get(k) for k in ("sha256", "pages", "chars", "tokens_est", "extractor", "image_only")},
                )
            )
    GOLD2.mkdir(parents=True, exist_ok=True)
    with open(GOLD2 / "p2_docs.jsonl", "w") as f:
        for x in chosen:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(GOLD2 / "p2_fetch_log.jsonl", "w") as f:
        for x in log:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return chosen


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args()
    rows = draw(a.fetch)
    for k, v in sorted(collections.Counter((r["cell"], r["body"], r["dtype"]) for r in rows).items()):
        print(k, v)
    print("total", len(rows))
