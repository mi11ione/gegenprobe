"""P8 blind packets (eval/prereg9/PREREG9.md §5). Model-free; written to WORK only (never committed).

    PYTHONPATH=src:. .venv/bin/python -m eval.p8.packets build    (run by eval.p8.sample after the draw; deterministic)

A packet holds an opaque id, the two documents as extracted (the same sha256-verified cached text every earlier set
used), page-delimited, and a list of every distinct date the frozen parser (`gegenprobe.repair.common.parse_dates`)
finds in either document, each with a letter and up to three printed lines where it occurs. It carries no OPD
metadata (no type, no names, no dates, no language tag), no parliament key, no cell and no hypothesis. Packet ids are
assigned in a seeded random order (common.SEED).

Out: WORK/p8/packets/<id>.txt, WORK/p8/key.jsonl (id -> affair, parliament, cell; kept in WORK until the gold is merged),
     data/p8/p8_datelists.jsonl (id -> letter -> ISO date with document and page of each occurrence; no text).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.p8 import common as C  # noqa: E402
from gegenprobe import pdftext  # noqa: E402
from gegenprobe.repair.common import parse_dates  # noqa: E402

MAX_LINES = 3
LINE_CHARS = 160


def doc_pages(d: dict) -> list[str]:
    return pdftext.extract(d["sha256"], ocr=bool(d.get("image_only")))["pages"]


def _line(page: str, s: int, e: int) -> str:
    a = page.rfind("\n", 0, s) + 1
    b = page.find("\n", e)
    b = len(page) if b < 0 else b
    ln = re.sub(r"\s+", " ", page[a:b]).strip()
    if len(ln) > LINE_CHARS:
        mid = (s - a) + (e - s) // 2
        lo = max(0, mid - LINE_CHARS // 2)
        ln = ln[lo:lo + LINE_CHARS]
    return ln


def date_list(pages: dict[str, list[str]]) -> list[dict]:
    """Distinct printed dates in first-occurrence order (member text first): letter, ISO date, occurrences."""
    out: dict[str, dict] = {}
    for role in ("question", "answer"):
        for pno, page in enumerate(pages[role], 1):
            for iso, s, e in parse_dates(page):
                x = out.setdefault(iso, dict(date=iso, occ=[]))
                x["occ"].append(dict(doc=role, page=pno, start=s, end=e, line=_line(page, s, e)))
    lst = list(out.values())
    for i, x in enumerate(lst, 1):
        x["letter"] = f"D{i:02d}"
    return lst


def render(pid: str, pages: dict[str, list[str]], dl: list[dict]) -> str:
    parts = [f"P8 packet {pid}\n"]
    for role in ("question", "answer"):
        parts.append(f"=== DOCUMENT {role} ===\n" + "".join(f"=== PAGE {i} ===\n{p}\n" for i, p in enumerate(pages[role], 1)))
    lines = ["=== DATES (every distinct date the date parser finds in the two documents) ==="]
    for x in dl:
        occ = "; ".join(f'{o["doc"]} p{o["page"]}: «{o["line"]}»' for o in x["occ"][:MAX_LINES])
        more = f" (+{len(x['occ']) - MAX_LINES} more)" if len(x["occ"]) > MAX_LINES else ""
        lines.append(f"{x['letter']} {x['date']} | {occ}{more}")
    if not dl:
        lines.append("(none)")
    parts.append("\n".join(lines) + "\n")
    return "".join(parts)


def packet_pages(pid: str, text: str | None = None) -> dict[str, list[str]]:
    """Pages exactly as the packet prints them (the cached pages; the packet adds only markers and one newline per page)."""
    txt = text if text is not None else (C.PACK / f"{pid}.txt").read_text(encoding="utf-8")
    txt = re.split(r"(?m)^=== DATES \(", txt, maxsplit=1)[0]
    out = {}
    blocks = re.split(r"(?m)^=== DOCUMENT (question|answer) ===\n", txt)
    for role, body in zip(blocks[1::2], blocks[2::2]):
        out[role] = [p[:-1] for p in re.split(r"(?m)^=== PAGE \d+ ===\n", body)[1:]]
    return out


def load_key() -> dict[str, dict]:
    return {r["id"]: r for r in C._jsonl(C.KEY)}


def load_datelists() -> dict[str, dict[str, str]]:
    return {r["id"]: {x["letter"]: x["date"] for x in r["dates"]} for r in C._jsonl(C.DATELISTS)}


def build() -> dict:
    rows = C._jsonl(C.AFFAIRS)
    if not rows:
        raise SystemExit(f"{C.AFFAIRS} missing: draw first (python -m eval.p8.sample)")
    order = sorted(rows, key=lambda r: r["affair_id"])
    random.Random(C.SEED).shuffle(order)
    C.PACK.mkdir(parents=True, exist_ok=True)
    key, dls, shas = [], [], {}
    for i, r in enumerate(order, 1):
        pid = f"P8-{i:03d}"
        pages = {d["role"]: doc_pages(d) for d in r["docs"]}
        dl = date_list(pages)
        txt = render(pid, pages, dl)
        (C.PACK / f"{pid}.txt").write_text(txt, encoding="utf-8")
        shas[pid] = hashlib.sha256(txt.encode()).hexdigest()
        key.append(dict(id=pid, affair_id=r["affair_id"], body=r["body"], cell=r["cell"], group=r["group"],
                        affair_type=r["affair_type"]))
        dls.append(dict(id=pid, dates=[dict(letter=x["letter"], date=x["date"],
                                            at=[[o["doc"], o["page"]] for o in x["occ"]]) for x in dl]))
        assert packet_pages(pid, txt) == pages, f"{pid}: packet pages differ from the cached text"
    blob = "".join(json.dumps(k, sort_keys=True) + "\n" for k in key)
    C.KEY.write_text(blob, encoding="utf-8")
    with open(C.DATELISTS, "w", encoding="utf-8") as f:
        for x in dls:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return dict(packets=len(key), key_sha256=hashlib.sha256(blob.encode()).hexdigest(),
                packets_sha256=hashlib.sha256(json.dumps(shas, sort_keys=True).encode()).hexdigest(),
                blind="packets carry an opaque id, the two documents and the parser's date list only; no OPD metadata, "
                      "parliament key, cell or hypothesis")


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        print(json.dumps(build(), indent=1))
    else:
        print(__doc__)
