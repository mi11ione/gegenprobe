"""Federal cell: blind packets in P8's packet format (eval/fed/PROTOCOL.md §5). Model-free; written to WORK only.

    PYTHONPATH=src:. .venv/bin/python -m eval.fed.packets build    (run by `eval.fed.draw fetch`; deterministic)

The federal texts are not PDFs: each affair's texts are rows of OPD's texts_CHE export, one HTML version per language
slot. A packet shows the stratum's slot only, converted by the frozen `eval.fed.common.plain`:
  DOCUMENT question  PAGE 1 the title, PAGE 2 the text as submitted, PAGE 3 the reasoning (only if OPD stores one)
  DOCUMENT answer    PAGE 1 the answer text
and the parser's date list, rendered by the frozen P8 functions (`eval.p8.packets.date_list`, `render`,
`packet_pages`). No OPD metadata (no type, number, names, dates, language slot), no stratum, no cell, no hypothesis.
Packet ids are assigned in a seeded random order (common.SEED).

Out: WORK/fed/packets/<id>.txt, WORK/fed/key.jsonl (id -> affair, stratum, group, type; kept in WORK until the merge),
     data/fed/fed_datelists.jsonl (id -> letter -> ISO date with document and page of each occurrence; no text).
"""

from __future__ import annotations

import hashlib
import json
import random
import sys

from eval.fed import common as C
from eval.p8 import packets as P8P


def load_texts(affair: int) -> dict:
    return json.loads((C.TEXTS / f"{affair}.json").read_text(encoding="utf-8"))


def pages_of(entry: dict) -> dict[str, list[str]]:
    """The two documents of one drawn affair as packet pages (the stored HTML of the stratum's slot, sha256-checked)."""
    t = load_texts(entry["affair_id"])
    s = entry["stratum"]
    for role in ("member", "reason", "answer"):
        raw = t["rows"].get(role)
        want = entry["sha"].get(role)
        if (raw and C.sha(raw) != want) or (want and not raw):
            raise SystemExit(f"affair {entry['affair_id']}: the {role} text of slot {s} differs from the drawn sha256")
    q = [C.plain(t["rows"].get("title") or t.get("title_fallback") or ""), C.plain(t["rows"]["member"])]
    if t["rows"].get("reason"):
        q.append(C.plain(t["rows"]["reason"]))
    return {"question": q, "answer": [C.plain(t["rows"]["answer"])]}


def build() -> dict:
    rows = [json.loads(x) for x in open(C.AFFAIRS, encoding="utf-8")] if C.AFFAIRS.exists() else []
    if not rows:
        raise SystemExit(f"{C.AFFAIRS} missing: run `eval.fed.draw fetch` first")
    order = sorted(rows, key=lambda r: r["affair_id"])
    random.Random(C.SEED).shuffle(order)
    C.PACK.mkdir(parents=True, exist_ok=True)
    key, dls, shas = [], [], {}
    for i, r in enumerate(order, 1):
        pid = f"FED-{i:03d}"
        pages = pages_of(r)
        dl = P8P.date_list(pages)
        txt = P8P.render(pid, pages, dl).replace("P8 packet", "Packet", 1)
        (C.PACK / f"{pid}.txt").write_text(txt, encoding="utf-8")
        shas[pid] = hashlib.sha256(txt.encode()).hexdigest()
        key.append(dict(id=pid, affair_id=r["affair_id"], stratum=r["stratum"], group=r["group"], cell=r["cell"],
                        affair_type=r["affair_type"]))
        dls.append(dict(id=pid, dates=[dict(letter=x["letter"], date=x["date"],
                                            at=[[o["doc"], o["page"]] for o in x["occ"]]) for x in dl]))
        assert P8P.packet_pages(pid, txt) == pages, f"{pid}: packet pages differ from the converted text"
    blob = "".join(json.dumps(k, sort_keys=True) + "\n" for k in key)
    C.WF.mkdir(parents=True, exist_ok=True)
    C.KEY.write_text(blob, encoding="utf-8")
    C.DF.mkdir(parents=True, exist_ok=True)
    with open(C.DATELISTS, "w", encoding="utf-8") as f:
        for x in dls:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return dict(packets=len(key), key_sha256=hashlib.sha256(blob.encode()).hexdigest(),
                packets_sha256=hashlib.sha256(json.dumps(shas, sort_keys=True).encode()).hexdigest(),
                blind="packets carry an opaque id, the two documents and the parser's date list only; no OPD metadata, "
                      "stratum, cell or hypothesis")


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        print(json.dumps(build(), indent=1))
    else:
        print(__doc__)
