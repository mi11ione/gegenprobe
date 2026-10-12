"""P11 blind packets (eval/p11/PROTOCOL.md §5). Model-free; written to WORK only (never committed).

    PYTHONPATH=src:. .venv/bin/python -m eval.p11.packets build    (run by `eval.p11.draw fetch`; deterministic)

Text: the sha256-verified cached extraction of each fetched document (gegenprobe.pdftext, the text every arm reads).

IT packets (`IT-001`, ...) are P8 packets, rendered by the frozen P8 functions (`eval.p8.packets.render`, `date_list`,
`packet_pages`): `DOCUMENT question` (the member's text), `DOCUMENT answer` (the document OPD links as the executive's
answer), `PAGE n` markers, and the parser's date list.
NI packets (`NI-001`, ...) show up to three documents of the affair as `DOCUMENT d1`, `d2`, `d3` (common.packet_docs,
in OPD id order) with `PAGE n` markers, and the same date list over all of them (the frozen parser
`gegenprobe.repair.common.parse_dates`, P8's line excerpts).
Neither carries OPD metadata (no type, number, title, names, dates, language tag), the body, the stratum or any arm
output. Packet ids are assigned per cell in a seeded random order (common.SEED).

Out: WORK/p11/packets/<id>.txt, WORK/p11/key_{it,ni}.jsonl (id -> affair, body, stratum; WORK until that cell's merge),
     data/p11/p11_datelists.jsonl (id -> letter -> ISO date with the document and page of each occurrence; no text).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.p8 import packets as P8P  # noqa: E402
from eval.p11 import common as C  # noqa: E402
from gegenprobe import pdftext  # noqa: E402
from gegenprobe.repair.common import parse_dates  # noqa: E402


def doc_pages(d: dict) -> list[str]:
    """The cached extraction of one fetched document; the sha256 names the cached PDF, so the text is the fetched one."""
    t = pdftext.extract(d["sha256"], ocr=bool(d.get("image_only")))
    if t.get("sha256") not in (None, d["sha256"]):
        raise SystemExit(f"document {d['doc_id']}: cached text is not the fetched file {d['sha256']}")
    return t["pages"]


def pages_of(entry: dict) -> dict[str, list[str]]:
    """role (question/answer for IT, d1..d3 for NI) -> pages."""
    return {d["role"]: doc_pages(d) for d in entry["docs"]}


# ------------------------------------------------------------------------------------------------ NI render
def ni_roles(pages: dict) -> list[str]:
    return sorted(pages, key=lambda r: int(r[1:]))


def ni_date_list(pages: dict[str, list[str]]) -> list[dict]:
    """P8's date list over the NI documents in order (first occurrence order; the frozen parser and line excerpts)."""
    out: dict[str, dict] = {}
    for role in ni_roles(pages):
        for pno, page in enumerate(pages[role], 1):
            for iso, s, e in parse_dates(page):
                x = out.setdefault(iso, dict(date=iso, occ=[]))
                x["occ"].append(dict(doc=role, page=pno, start=s, end=e, line=P8P._line(page, s, e)))
    lst = list(out.values())
    for i, x in enumerate(lst, 1):
        x["letter"] = f"D{i:02d}"
    return lst


def ni_render(pid: str, pages: dict[str, list[str]], dl: list[dict]) -> str:
    parts = [f"Packet {pid}\n"]
    for role in ni_roles(pages):
        parts.append(f"=== DOCUMENT {role} ===\n" + "".join(f"=== PAGE {i} ===\n{p}\n" for i, p in enumerate(pages[role], 1)))
    lines = ["=== DATES (every distinct date the date parser finds in the documents) ==="]
    for x in dl:
        occ = "; ".join(f'{o["doc"]} p{o["page"]}: «{o["line"]}»' for o in x["occ"][:P8P.MAX_LINES])
        more = f" (+{len(x['occ']) - P8P.MAX_LINES} more)" if len(x["occ"]) > P8P.MAX_LINES else ""
        lines.append(f"{x['letter']} {x['date']} | {occ}{more}")
    if not dl:
        lines.append("(none)")
    parts.append("\n".join(lines) + "\n")
    return "".join(parts)


def ni_packet_pages(pid: str, text: str | None = None) -> dict[str, list[str]]:
    """Pages exactly as an NI packet prints them."""
    txt = text if text is not None else (C.PACK / f"{pid}.txt").read_text(encoding="utf-8")
    txt = re.split(r"(?m)^=== DATES \(", txt, maxsplit=1)[0]
    out = {}
    blocks = re.split(r"(?m)^=== DOCUMENT (d\d+) ===\n", txt)
    for role, body in zip(blocks[1::2], blocks[2::2]):
        out[role] = [p[:-1] for p in re.split(r"(?m)^=== PAGE \d+ ===\n", body)[1:]]
    return out


def packet_pages(pid: str, text: str | None = None) -> dict[str, list[str]]:
    """Pages exactly as the packet prints them (IT: the frozen P8 parser; NI: ni_packet_pages)."""
    txt = text if text is not None else (C.PACK / f"{pid}.txt").read_text(encoding="utf-8")
    return ni_packet_pages(pid, txt) if pid.startswith("NI-") else P8P.packet_pages(pid, txt)


def load_key(cell: str) -> dict[str, dict]:
    return {r["id"]: r for r in C._jsonl(C.KEY[cell])}


def load_datelists() -> dict[str, dict[str, str]]:
    return {r["id"]: {x["letter"]: x["date"] for x in r["dates"]} for r in C._jsonl(C.DATELISTS)}


# ------------------------------------------------------------------------------------------------ build
def _key(cell: str, pid: str, r: dict) -> dict:
    k = dict(id=pid, affair_id=r["affair_id"], body=r["body"], stratum=r["stratum"], affair_type=r["affair_type"],
             type_source=r["type_source"], lang=r["lang"])
    if cell == "it":
        k.update(group=r["group"], fill=r["fill"], docs={d["role"]: dict(doc_id=d["doc_id"], opd_lang=d.get("opd_lang"))
                                                          for d in r["docs"]})
    else:
        k.update(ni_type=r["ni_type"], docs={d["role"]: dict(doc_id=d["doc_id"], opd_lang=d.get("opd_lang"))
                                             for d in r["docs"]})
    return k


def build() -> dict:
    rows = C._jsonl(C.AFFAIRS)
    if not rows:
        raise SystemExit(f"{C.AFFAIRS} missing: run `eval.p11.draw fetch` first")
    C.PACK.mkdir(parents=True, exist_ok=True)
    out, dls = {}, []
    for cell in C.CELLS:
        order = sorted((r for r in rows if r["cell"] == cell), key=lambda r: r["affair_id"])
        random.Random(f"{C.SEED}:packets:{cell}").shuffle(order)
        key, shas = [], {}
        for i, r in enumerate(order, 1):
            pid = f"{C.PREFIX[cell]}-{i:03d}"
            pages = pages_of(r)
            if cell == "it":
                dl = P8P.date_list(pages)
                txt = P8P.render(pid, pages, dl).replace("P8 packet", "Packet", 1)
            else:
                dl = ni_date_list(pages)
                txt = ni_render(pid, pages, dl)
            (C.PACK / f"{pid}.txt").write_text(txt, encoding="utf-8")
            shas[pid] = hashlib.sha256(txt.encode()).hexdigest()
            assert packet_pages(pid, txt) == pages, f"{pid}: packet pages differ from the cached text"
            key.append(_key(cell, pid, r))
            dls.append(dict(id=pid, dates=[dict(letter=x["letter"], date=x["date"],
                                                at=[[o["doc"], o["page"]] for o in x["occ"]]) for x in dl]))
        blob = "".join(json.dumps(k, sort_keys=True, ensure_ascii=False) + "\n" for k in key)
        C.W11.mkdir(parents=True, exist_ok=True)
        C.KEY[cell].write_text(blob, encoding="utf-8")
        out[cell] = dict(packets=len(key), key_sha256=hashlib.sha256(blob.encode()).hexdigest(),
                         packets_sha256=hashlib.sha256(json.dumps(shas, sort_keys=True).encode()).hexdigest())
    C.D11.mkdir(parents=True, exist_ok=True)
    with open(C.DATELISTS, "w", encoding="utf-8") as f:
        for x in dls:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    out["blind"] = ("packets carry an opaque id, the documents and the parser's date list only; no OPD metadata, body, "
                    "stratum, hypothesis or arm output")
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        print(json.dumps(build(), indent=1))
    else:
        print(__doc__)
