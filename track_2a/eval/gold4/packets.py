"""P4 annotation packets and held-out draw.

    python -m eval.gold4.packets build --split dev|heldout   -> .work/gold4/packets/<split>/<meeting>.txt (never committed)
    python -m eval.gold4.packets draw-heldout --fetch        -> data/gold4/p4_heldout_meetings.jsonl
        run ONLY after LOCK4: seed HELDOUT_SEED, drawn from the candidate meetings not in dev
    python -m eval.gold4.packets check <split> <meeting>     -> verbatim check of an annotator file (.work/gold4/ann/<A>/...)
"""
from __future__ import annotations

import json
import random
import re
import sys

from eval.gold4 import sample
from gegenprobe import pdftext
from gegenprobe.paths import DATA, WORK

HELDOUT_SEED = 20261013
N_HELDOUT = 6
PACK = WORK / "gold4" / "packets"


def build(split: str) -> None:
    from eval.gold4.run_p4 import meetings
    d = PACK / split
    d.mkdir(parents=True, exist_ok=True)
    for m in meetings(split):
        a = pdftext.extract(m["agenda"]["sha256"])["pages"]
        mi = pdftext.extract(m["minutes"]["sha256"])["pages"]
        txt = "".join(f"\n=== AGENDA PAGE {i} ===\n{p}" for i, p in enumerate(a, 1))
        txt += "".join(f"\n=== MINUTES PAGE {i} ===\n{p}" for i, p in enumerate(mi, 1))
        (d / f"{m['date']}.txt").write_text(txt.lstrip("\n"), encoding="utf-8")
    print(f"packets in {d}")


def draw_heldout(fetch: bool) -> None:
    dev = {json.loads(line)["meeting_id"] for line in open(DATA / "gold4" / "p4_meetings.jsonl")}
    cand = [c for c in sample.candidates() if c["meeting_id"] not in dev]
    pick = sorted(random.Random(HELDOUT_SEED).sample(cand, N_HELDOUT), key=lambda x: x["date"])
    with open(DATA / "gold4" / "p4_heldout_meetings.jsonl", "w") as f:
        for c in pick:
            rec = dict(body=sample.BODY, meeting_id=c["meeting_id"], date=c["date"], n_docs=c["n_docs"])
            for role in ("agenda", "minutes"):
                r = c[role]
                rec[role] = dict(doc_id=r["id"], name=r.get("name"), url=r.get("url"), opd_chars=r.get("n"))
                if fetch:
                    sha, path = pdftext.fetch_pdf(r["url"])
                    t = pdftext.extract(sha, path)
                    rec[role].update(sha256=sha, pages=len(t["pages"]), chars=sum(map(len, t["pages"])),
                                     extractor=t["extractor"], image_only=t["image_only"])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(rec["date"])


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def check(path: str, split: str) -> list[str]:
    ann = json.loads(open(path).read())
    pk = (PACK / split / f"{ann['meeting']}.txt").read_text(encoding="utf-8")
    pages = {}
    for kind, n, body in re.findall(r"=== (AGENDA|MINUTES) PAGE (\d+) ===\n(.*?)(?=\n=== (?:AGENDA|MINUTES) PAGE|\Z)", pk, re.S):
        pages[(kind, int(n))] = _ws(body)
    agenda = " ".join(v for (k, _), v in pages.items() if k == "AGENDA")
    errs = []
    for it in ann["items"]:
        if _ws(it["title_quote"])[:60] not in agenda:
            errs.append(f"{it['no']}: title_quote not verbatim in agenda")
        if it.get("decision_quote"):
            pg = pages.get(("MINUTES", int(it.get("decision_page") or 0)))
            if not pg or _ws(it["decision_quote"]) not in pg:
                errs.append(f"{it['no']}: decision_quote not verbatim on minutes page {it.get('decision_page')}")
    return errs


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(sys.argv[sys.argv.index("--split") + 1] if "--split" in sys.argv else "dev")
    elif cmd == "draw-heldout":
        draw_heldout("--fetch" in sys.argv)
    elif cmd == "check":
        e = check(sys.argv[3], sys.argv[2])
        print("OK" if not e else "ERRORS: " + "; ".join(e))
        sys.exit(1 if e else 0)
