"""Shared P5 tooling (converter breadth: Q/A pairing, people, recommendation, reasoning; eval/prereg6/PREREG6.md).

Exclusions: every affair and document of P1 dev + held-out (+ spikes, dev-id sources), P2, P3, P3b, P4 (dev + held-out
meetings) and the P4 transfer cell, by the frozen `eval.gold5.sample5.exclusions` plus the P3b draw. P5 additionally
excludes the P5 dev affairs (data/gold6/p5dev_affairs.jsonl) and, where possible, the dev bodies.

Packets: the P3 format (`=== DOCUMENT question|answer ===`, `=== PAGE n ===`), written to .work only (never committed).
"""

from __future__ import annotations

import json
import random
import re

from eval.gold2.sample import fetch_one
from eval.gold3 import sample as s3
from eval.gold5 import sample5 as s5
from gegenprobe import pdftext
from gegenprobe.paths import DATA, WORK

GOLD6 = DATA / "gold6"
W6 = WORK / "p5"


def exclusions() -> tuple[set, set]:
    docs, affs = s5.exclusions()
    for line in open(DATA / "gold5" / "p3b_affairs.jsonl"):
        s5._ids(json.loads(line), docs, affs)
    return docs, affs


def pairs_for(bodies: set[str]) -> dict[str, list[dict]]:
    saved = s3.BODIES
    s3.BODIES = set(bodies)
    try:
        return s3.pairs()
    finally:
        s3.BODIES = saved


def candidates(pl: dict, body: str, lang: str | None, x_docs: set, x_affs: set, seed: int, salt: str,
               a_type: str | None = None) -> list[dict]:
    cands = [
        c
        for c in pl.get(body, [])
        if c["affair"] not in x_affs
        and (a_type is None or c["a_type"] == a_type)
        and c["question"]["id"] not in x_docs
        and c["answer"]["id"] not in x_docs
        and (lang is None or c["question"]["lg"] in (lang, None))
    ]
    cands.sort(key=lambda c: c["affair"])
    random.Random(f"{seed}:{salt}").shuffle(cands)
    return cands


def entry(c: dict, rq: dict, ra: dict, body: str, lang: str, split: str) -> dict:
    docs = []
    for role, d, r in (("question", c["question"], rq), ("answer", c["answer"], ra)):
        docs.append(
            dict(
                role=role,
                doc_id=d["id"],
                name=d.get("name"),
                url=d["url"],
                opd_text_status=d["st"],
                opd_chars=d["n"],
                **{k: r.get(k) for k in ("sha256", "pages", "chars", "extractor", "image_only")},
            )
        )
    return dict(split=split, affair_id=c["affair"], body=body, lang=lang, affair_type=c["a_type"], docs=docs)


def draw(quotas: list[tuple], seed: int, split: str, x_docs: set, x_affs: set):
    """quotas: (body, language or None, n[, affair type]). Returns (rows, log). A failed fetch is replaced by the next
    affair in seeded order."""
    pl = pairs_for({q[0] for q in quotas})
    rows, log, used = [], [], set()
    for q in quotas:
        body, lang, n = q[:3]
        a_type = q[3] if len(q) > 3 else None
        got = 0
        salt = f"{body}:{lang}" + (f":{a_type}" if a_type else "")
        cands = candidates(pl, body, lang, x_docs, x_affs, seed, salt, a_type)
        for c in cands:
            if got >= n:
                break
            if c["affair"] in used:
                continue
            rq = fetch_one(c["question"])
            ra = fetch_one(c["answer"]) if "error" not in rq else {}
            ok = "error" not in rq and "error" not in ra
            log.append(dict(affair_id=c["affair"], body=body, lang=lang, accepted=ok, q_error=rq.get("error"),
                            a_error=ra.get("error")))
            if ok:
                used.add(c["affair"])
                rows.append(entry(c, rq, ra, body, lang or c["question"]["lg"] or "", split))
                got += 1
        if got < n:
            log.append(dict(body=body, lang=lang, shortfall=n - got, pool=len(cands)))
    return rows, log


def doc_pages(d: dict) -> list[str]:
    return pdftext.extract(d["sha256"], ocr=bool(d.get("image_only")))["pages"]


def texts(row: dict) -> dict[str, list[str]]:
    return {d["role"]: doc_pages(d) for d in row["docs"]}


def write_packets(rows: list[dict], out) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for a in rows:
        parts = []
        for d in a["docs"]:
            pages = doc_pages(d)
            parts.append(f"=== DOCUMENT {d['role']} ===\n" + "".join(f"=== PAGE {i} ===\n{p}\n" for i, p in enumerate(pages, 1)))
        (out / f"{a['affair_id']}.txt").write_text("\n".join(parts), encoding="utf-8")


def packet_pages(path) -> dict[str, list[str]]:
    """Pages exactly as the packet prints them (equal to the cached pages: the packet adds only markers and newlines)."""
    txt = path.read_text(encoding="utf-8")
    out = {}
    blocks = re.split(r"(?m)^=== DOCUMENT (question|answer) ===\n", txt)
    for role, body in zip(blocks[1::2], blocks[2::2]):
        pages = re.split(r"(?m)^=== PAGE \d+ ===\n", body)[1:]
        out[role] = [p[:-1] if p.endswith("\n") else p for p in pages]
    return out


def fold(s: str) -> str:
    import unicodedata

    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch)).lower()
