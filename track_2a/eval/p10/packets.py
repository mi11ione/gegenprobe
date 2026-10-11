"""P10 blind packets (eval/prereg10/PREREG10.md §5). Model-free; written to WORK only (never committed).

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.packets build    (run by eval.p10.draw after the draw; deterministic)

A packet holds an opaque id and the two documents as extracted (the sha256-verified cached text, the same text the arms
read), page-delimited. It carries no OPD metadata (no names, no type, no contributor list), no parliament key, no
stratum, no candidate list and no arm output. Packet ids are assigned in a seeded random order (common.SEED).

Out: WORK/p10/packets/<id>.txt, WORK/p10/key.jsonl (id -> affair, parliament, stratum, cell; kept in WORK until the gold
is merged).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.p10 import common as C  # noqa: E402
from gegenprobe import pdftext  # noqa: E402


def doc_pages(d: dict) -> list[str]:
    return pdftext.extract(d["sha256"], ocr=bool(d.get("image_only")))["pages"]


def pages_of(e: dict) -> dict[str, list[str]]:
    return {d["role"]: doc_pages(d) for d in e["docs"]}


def render(pid: str, pages: dict[str, list[str]]) -> str:
    parts = [f"P10 packet {pid}\n"]
    for role in ("question", "answer"):
        parts.append(f"=== DOCUMENT {role} ===\n" + "".join(f"=== PAGE {i} ===\n{p}\n" for i, p in enumerate(pages[role], 1)))
    parts.append("=== END ===\n")
    return "".join(parts)


def packet_pages(pid: str, text: str | None = None) -> dict[str, list[str]]:
    """Pages exactly as the packet prints them (the cached pages; the packet adds only markers and one newline per page)."""
    txt = text if text is not None else (C.PACK / f"{pid}.txt").read_text(encoding="utf-8")
    txt = re.split(r"(?m)^=== END ===\n", txt, maxsplit=1)[0]
    out = {}
    blocks = re.split(r"(?m)^=== DOCUMENT (question|answer) ===\n", txt)
    for role, body in zip(blocks[1::2], blocks[2::2]):
        out[role] = [p[:-1] for p in re.split(r"(?m)^=== PAGE \d+ ===\n", body)[1:]]
    return out


def load_key() -> dict[str, dict]:
    return {r["id"]: r for r in C._jsonl(C.KEY)}


def build() -> dict:
    rows = C._jsonl(C.AFFAIRS)
    if not rows:
        raise SystemExit(f"{C.AFFAIRS} missing: draw first (python -m eval.p10.draw)")
    order = sorted(rows, key=lambda r: r["affair_id"])
    random.Random(C.SEED).shuffle(order)
    C.PACK.mkdir(parents=True, exist_ok=True)
    key, shas = [], {}
    for i, r in enumerate(order, 1):
        pid = f"P10-{i:03d}"
        pages = pages_of(r)
        txt = render(pid, pages)
        (C.PACK / f"{pid}.txt").write_text(txt, encoding="utf-8")
        shas[pid] = hashlib.sha256(txt.encode()).hexdigest()
        key.append(dict(id=pid, affair_id=r["affair_id"], body=r["body"], stratum=r["stratum"], cell=r["cell"],
                        affair_type=r["affair_type"]))
        assert packet_pages(pid, txt) == pages, f"{pid}: packet pages differ from the cached text"
    blob = "".join(json.dumps(k, sort_keys=True) + "\n" for k in key)
    C.KEY.write_text(blob, encoding="utf-8")
    return dict(packets=len(key), key_sha256=hashlib.sha256(blob.encode()).hexdigest(),
                packets_sha256=hashlib.sha256(json.dumps(shas, sort_keys=True).encode()).hexdigest(),
                blind="packets carry an opaque id and the two documents only; no OPD metadata, parliament key, stratum, "
                      "candidate list or arm output")


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        print(json.dumps(build(), indent=1))
    else:
        print(__doc__)
