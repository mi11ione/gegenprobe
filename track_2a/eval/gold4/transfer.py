"""P4 exploratory transfer cell (PREREG4; seed and eligibility fixed in eval/prereg4/DEVIATIONS4.md D4-4 before the draw).

Two meetings of La Chaux-de-Fonds (OPD body 6421), the only French-speaking frontier body whose OPD meeting documents
include both an agenda ("Ordre du jour") and minutes ("Procès-verbal") under the same meeting, drawn with seed 20261015.
Same packet format as the Bulle held-out set, so the frozen guide, checker, runner and scorer apply unchanged.

    python -m eval.gold4.transfer draw --fetch   -> data/gold4/p4_transfer_meetings.jsonl
    python -m eval.gold4.transfer packets        -> .work/gold4/packets/transfer/<date>.txt
    python -m eval.gold4.transfer disagreements  -> .work/gold4/transfer/a3/<date>.json
                                                    (annotator files: .work/gold4/transfer/ann/<A>/<date>.json)
    python -m eval.gold4.transfer merge          -> data/gold4/p4_transfer_labels.jsonl, data/gold4/annotations_transfer/,
                                                    results/eval4/gold4_transfer_agreement.json
The merge uses the frozen eval/gold4/merge4.py functions unchanged, pointed at the transfer paths.
Scoring: python -m eval.gold4.run_p4 predict --split transfer --backend <spec> --theta 0 ; ... score --split transfer --build <b>
"""
from __future__ import annotations

import collections
import glob
import gzip
import json
import random
import re
import sys

from gegenprobe import pdftext
from gegenprobe.paths import DATA, DOCS_META, WORK
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

BODY = "6421"
SEED = 20261015
N = 2
OUT = DATA / "gold4" / "p4_transfer_meetings.jsonl"
PACK = WORK / "gold4" / "packets" / "transfer"


def candidates() -> list[dict]:
    rows = [json.loads(line) for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz")))
            for line in gzip.open(f, "rt")]
    rows = [r for r in rows if str(r.get("b")) == BODY and r.get("st") == "ok" and r.get("m")]
    by_meeting = collections.defaultdict(list)
    for r in rows:
        by_meeting[r["m"]].append(r)
    out = []
    for m, rs in by_meeting.items():
        oj = [r for r in rs if re.search(r"ordre du jour", r.get("name") or "", re.I)]
        pv = [r for r in rs if re.search(r"proc[eè]s.verbal", r.get("name") or "", re.I)]
        if oj and pv:
            out.append(dict(meeting_id=m, date=(oj[0].get("date") or "")[:10], agenda=oj[0], minutes=pv[0], n_docs=len(rs)))
    return sorted(out, key=lambda x: (x["date"], x["meeting_id"]))


def draw(fetch: bool) -> None:
    cand = candidates()
    pick = sorted(random.Random(SEED).sample(cand, N), key=lambda x: x["date"])
    with open(OUT, "w") as f:
        for c in pick:
            rec = dict(body=BODY, meeting_id=c["meeting_id"], date=c["date"], n_docs=c["n_docs"])
            for role in ("agenda", "minutes"):
                r = c[role]
                rec[role] = dict(doc_id=r["id"], name=r.get("name"), url=r.get("url"), opd_chars=r.get("n"))
                if fetch:
                    sha, path = pdftext.fetch_pdf(r["url"])
                    t = pdftext.extract(sha, path)
                    rec[role].update(sha256=sha, pages=len(t["pages"]), chars=sum(map(len, t["pages"])),
                                     extractor=t["extractor"], image_only=t["image_only"])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(rec["date"], rec["meeting_id"], rec["agenda"].get("chars"), rec["minutes"].get("chars"))
    print(f"{len(cand)} candidate meetings, {N} drawn (seed {SEED})")


def packets() -> None:
    PACK.mkdir(parents=True, exist_ok=True)
    for line in open(OUT):
        m = json.loads(line)
        a = pdftext.extract(m["agenda"]["sha256"])["pages"]
        mi = pdftext.extract(m["minutes"]["sha256"])["pages"]
        txt = "".join(f"\n=== AGENDA PAGE {i} ===\n{p}" for i, p in enumerate(a, 1))
        txt += "".join(f"\n=== MINUTES PAGE {i} ===\n{p}" for i, p in enumerate(mi, 1))
        (PACK / f"{m['date']}.txt").write_text(txt.lstrip("\n"), encoding="utf-8")
    print(f"packets in {PACK}")


def _redirect():
    """Point the frozen merge4 at the transfer paths; returns (tmp data dir, tmp results dir)."""
    import tempfile
    from pathlib import Path

    from eval.gold4 import merge4
    tmp = Path(tempfile.mkdtemp(prefix="p4t_"))
    (tmp / "data" / "gold4").mkdir(parents=True)
    (tmp / "results").mkdir()
    merge4.G = WORK / "gold4" / "transfer"
    merge4.ANN = merge4.G / "ann"
    merge4.DATA, merge4.RESULTS = tmp / "data", tmp / "results"
    return merge4, tmp


def merge() -> None:
    import shutil

    from gegenprobe.paths import RESULTS
    merge4, tmp = _redirect()
    merge4.merge()
    shutil.copyfile(tmp / "data" / "gold4" / "p4_heldout_labels.jsonl", DATA / "gold4" / "p4_transfer_labels.jsonl")
    dst = DATA / "gold4" / "annotations_transfer"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(tmp / "data" / "gold4" / "annotations", dst)
    shutil.copyfile(tmp / "results" / "eval4" / "gold4_agreement.json", RESULTS / "eval4" / "gold4_transfer_agreement.json")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "draw":
        draw("--fetch" in sys.argv)
    elif cmd == "packets":
        packets()
    elif cmd == "disagreements":
        _redirect()[0].disagreements()
    elif cmd == "merge":
        merge()
