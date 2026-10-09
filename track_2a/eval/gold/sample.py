"""Draw the dev and held-out gold documents (model-free), fetch the PDFs politely, extract text, record hashes.

Design (vision §8): cells = language × level (+ one OCR cell of TI scans); three doc types (intervention text = expected
null class; executive answer/decision; report or minutes page); length-matched: OPD text length 4,000–8,000 chars
(≈ 1,000–2,000 tokens at chars/4) for every non-OCR doc, both classes; one doc per affair; disjoint from dev and the spikes.
The type is a metadata guess used only for stratification; annotators set the labels.

usage: python -m eval.gold.sample --split dev|heldout [--fetch]
Out: data/gold/{dev,heldout}_docs.jsonl  (ids, url, sha256, pages, chars, stratum; never the text)
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import random
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gegenprobe import pdftext
from gegenprobe.paths import DATA, DOCS_META, OPD_RAW

from .doctype import doc_type

SEEDS = {"dev": 20261009, "heldout": 20261010}
SPIKES = Path(os.path.expanduser("~/Desktop/hackapertus/spikes"))
GOLD = DATA / "gold"

# cell -> list of (body, language or None for any)
CELLS = {
    "de_canton": [("BE", "de"), ("ZH", None), ("BS", None), ("LU", None)],
    "de_commune": [("261", None), ("230", None), ("3203", None)],  # Zürich city, Winterthur, St. Gallen city
    "fr_canton": [("GE", None), ("BE", "fr"), ("JU", None), ("VS", "fr")],
    "fr_commune": [
        ("5586", None),
        ("6152", None),
        ("6621", None),
    ],  # Lausanne, Collombey-Muraz, Genève city (Monthey: HTML pages)
    "it_canton": [("TI", None)],
    "it_commune": [("5192", None), ("5254", None), ("5113", None)],  # Lugano, Mendrisio, Locarno
    "ocr_ti": [("TI", None)],
}
QUOTA = {"dev": {"intervention": 4, "answer": 4, "report": 2}, "heldout": {"intervention": 10, "answer": 8, "report": 4}}
QUOTA_OCR = {"dev": {"intervention": 2, "answer": 3}, "heldout": {"intervention": 10, "answer": 12}}
LEN_BAND = (4000, 8000)
SUBSTITUTIONS = {
    "6153 Monthey": "replaced by 5586 Lausanne and 6621 Genève city: Monthey's OPD documents are HTML pages, not PDFs",
    "5254 Mendrisio": "kept but docs are unlinked to affairs in OPD (affair id null); Locarno 5113 added for volume",
    "JU": "few typed docs: question and answer usually share one document, typed 'intervention' only when the name says so",
}


def spike_exclusions() -> tuple[set, set]:
    docs, affs = set(), set()
    for x in json.load(open(SPIKES / "round7/null_items.json")) + json.load(open(SPIKES / "round8/ptr_items.json")):
        docs.add(int(x["doc_id"]))
        affs.add(int(x["affair_id"]))
    for x in json.load(open(SPIKES / "round8/opd_ctrl/ctrl_raw.json")):
        docs.add(int(x["doc_id"]))
        affs.add(int(x["affair_id"]))
    for p in (SPIKES / "recovery/data/audit_docs").glob("*.txt"):
        if p.stem.isdigit():
            docs.add(int(p.stem))
    for line in gzip.open(SPIKES / "bilanz/data/docs.jsonl.gz", "rt"):
        x = json.loads(line)
        docs.add(int(x["doc_id"]))
        affs.add(int(x["affair"]["id"]))
    return docs, affs


def affair_types() -> dict[int, str]:
    out = {}
    for line in gzip.open(OPD_RAW / "affairs.ndjson.gz", "rt"):
        a = json.loads(line)
        out[a["id"]] = a.get("type_harmonized_en")
    return out


def lang_of(d: dict) -> str | None:
    n = (d.get("name") or "").lower()
    for lg in ("de", "fr", "it"):
        if n.endswith(f"-{lg}") or f"-{lg} " in n or f"-{lg}." in n or n.endswith(f"-{lg} (pdf)"):
            return lg
    return (d.get("lang") or "").split(";")[0] or None


def pool() -> list[dict]:
    want = {b for cell in CELLS.values() for b, _ in cell}
    at = affair_types()
    seen, out = set(), []
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt"):
            d = json.loads(line)
            if d["id"] in seen or d["b"] not in want or not d.get("url"):
                continue
            seen.add(d["id"])
            d["a_type"] = at.get(d.get("a"))
            d["dtype"] = doc_type(d)
            d["lg"] = lang_of(d)
            if d["dtype"]:
                out.append(d)
    return out


def strata(pool_: list[dict], split: str, exclude_docs: set, exclude_affs: set) -> dict:
    """cell -> dtype -> ordered candidate list (seeded shuffle, bodies interleaved round-robin)."""
    res = {}
    for cell, bodies in CELLS.items():
        ocr = cell == "ocr_ti"
        res[cell] = {}
        for dt in (QUOTA_OCR if ocr else QUOTA)[split]:
            rnd = random.Random(f"{SEEDS[split]}:{cell}:{dt}")  # independent stream per stratum
            per_body = []
            for b, lg in bodies:
                c = [
                    d
                    for d in pool_
                    if d["b"] == b
                    and d["dtype"] == dt
                    and (lg is None or d["lg"] == lg)
                    and d["id"] not in exclude_docs
                    and (d.get("a") is None or d["a"] not in exclude_affs)
                ]
                if ocr:
                    c = [d for d in c if d["st"] in ("null", "blank")]
                else:
                    c = [d for d in c if d["st"] == "ok" and LEN_BAND[0] <= d["n"] <= LEN_BAND[1]]
                c.sort(key=lambda d: d["id"])
                rnd.shuffle(c)
                per_body.append(c)
            order, i = [], 0
            while any(i < len(c) for c in per_body):
                for c in per_body:
                    if i < len(c):
                        order.append(c[i])
                i += 1
            res[cell][dt] = order
    return res


def fetch_one(d: dict, ocr: bool) -> dict | None:
    try:
        # some OPD URLs carry raw spaces/umlauts; percent-encode them (the host sees the same resource)
        url = urllib.parse.quote(d["url"], safe=":/?&=%#+,;@!$'()*~")
        sha, path = pdftext.fetch_pdf(url)
        if b"%PDF-" not in path.read_bytes()[:1024]:
            return dict(error="not a PDF")
        t = pdftext.extract(sha, path, ocr=ocr, max_ocr_pages=6)
        chars = sum(len(p) for p in t["pages"])
        return dict(
            sha256=sha,
            pages=len(t["pages"]),
            chars=chars,
            tokens_est=chars // 4,
            extractor=t["extractor"],
            image_only=t["image_only"],
        )
    except Exception as e:  # network / parse errors -> replace from the same stratum
        return dict(error=f"{type(e).__name__}: {e}"[:200])


def draw(split: str, fetch: bool) -> list[dict]:
    excl_d, excl_a = spike_exclusions()
    if split == "heldout":
        for line in open(GOLD / "dev_docs.jsonl"):
            x = json.loads(line)
            excl_d.add(x["doc_id"])
            if x.get("affair_id"):
                excl_a.add(x["affair_id"])
    st = strata(pool(), split, excl_d, excl_a)
    chosen, log = [], []
    used_affs: set = set()  # one document per affair across the whole split (not only within a stratum)
    for cell, by_dt in st.items():
        ocr = cell == "ocr_ti"
        for dt, order in by_dt.items():
            need = (QUOTA_OCR if ocr else QUOTA)[split][dt]
            got, k = [], 0
            while len(got) < need and k < len(order):
                batch = []
                while len(batch) < (need - len(got)) * 2 and k < len(order):
                    d = order[k]
                    k += 1
                    if d.get("a") is not None and d["a"] in used_affs:
                        continue
                    if d.get("a") is not None:
                        used_affs.add(d["a"])
                    batch.append(d)
                if not fetch:
                    got += [dict(d) for d in batch[: need - len(got)]]
                    continue
                with ThreadPoolExecutor(4) as ex:
                    res = list(ex.map(fetch_one, batch, [ocr] * len(batch)))
                for d, r in zip(batch, res):
                    ok = r is not None and "error" not in r and (ocr or r["chars"] >= 1000) and (not ocr or r["image_only"])
                    log.append(dict(doc_id=d["id"], cell=cell, dtype=dt, **(r or {}), accepted=bool(ok and len(got) < need)))
                    if ok and len(got) < need:
                        got.append(dict(d, **r))
            for d in got:
                chosen.append(
                    dict(
                        split=split,
                        cell=cell,
                        dtype=dt,
                        doc_id=d["id"],
                        body=d["b"],
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
            if len(got) < need:
                log.append(dict(cell=cell, dtype=dt, shortfall=need - len(got), pool=len(order)))
    GOLD.mkdir(parents=True, exist_ok=True)
    with open(GOLD / f"{split}_docs.jsonl", "w") as f:
        for x in chosen:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(GOLD / f"{split}_fetch_log.jsonl", "w") as f:
        for x in log:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return chosen


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "heldout"], required=True)
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args()
    rows = draw(a.split, a.fetch)
    import collections

    c = collections.Counter((r["cell"], r["dtype"]) for r in rows)
    for k, v in sorted(c.items()):
        print(k, v)
