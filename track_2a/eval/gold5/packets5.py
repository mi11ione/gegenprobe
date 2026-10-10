"""P3b annotation tooling: P3's (`eval.gold3.annotate3`, frozen) with its paths rebound to .work/gold5 and data/gold5, the
P3b affairs, and the P3b tie-break seed. No logic of its own (eval/prereg5/PREREG5.md, "Gold"); guide eval/gold3/GUIDE.md.

  packets                 .work/gold5/packets/<affair_id>.txt (question then answer document, === DOCUMENT/PAGE === markers;
                          .work is gitignored: document text is never committed)
  verify <A1|A2|A3>       schema + verbatim quotes of .work/gold5/ann/<A>/*.json
  selfcheck <A> <id>      one file (annotators run this)
  disagreements           -> .work/gold5/disagreements.json
  a3packets               -> .work/gold5/a3/<affair_id>.json (both labels as X/Y, seed 20261018; key in a3_order.json)
  merge                   -> data/gold5/p3b_labels.jsonl, data/gold5/annotations/{A1,A2,A3}.jsonl,
                             results/eval5/gold5_agreement.json
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys

from eval.gold3 import annotate3 as a3
from eval.gold5.run_p3b import AFFAIRS, GOLD5, LABELS5
from gegenprobe.paths import RESULTS, WORK

G5 = WORK / "gold5"
SEED = 20261018
STAGE = G5 / "stage_merge"


def affairs() -> list[dict]:
    return [json.loads(line) for line in open(AFFAIRS)]


@contextlib.contextmanager
def gold5_paths():
    names = ("G", "PACK", "ANN", "GOLD3", "RESULTS", "SEED", "affairs")
    saved = {k: getattr(a3, k) for k in names}
    a3.G, a3.PACK, a3.ANN = G5, G5 / "packets", G5 / "ann"
    a3.GOLD3, a3.RESULTS = STAGE / "gold", STAGE / "results"  # merge writes here first; moved to the P3b names below
    a3.SEED, a3.affairs = SEED, affairs
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(a3, k, v)


def merge() -> None:
    if LABELS5.exists():
        raise SystemExit(f"{LABELS5} exists: merge once")
    shutil.rmtree(STAGE, ignore_errors=True)
    (STAGE / "gold").mkdir(parents=True)
    with gold5_paths():
        a3.merge()
    shutil.move(str(STAGE / "gold" / "p3_labels.jsonl"), LABELS5)
    shutil.rmtree(GOLD5 / "annotations", ignore_errors=True)
    shutil.move(str(STAGE / "gold" / "annotations"), GOLD5 / "annotations")
    (RESULTS / "eval5").mkdir(parents=True, exist_ok=True)
    shutil.move(str(STAGE / "results" / "eval3" / "gold3_agreement.json"), RESULTS / "eval5" / "gold5_agreement.json")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "merge":
        merge()
        sys.exit(0)
    with gold5_paths():
        if cmd == "packets":
            a3.packets()
        elif cmd == "verify":
            sys.exit(a3.verify(sys.argv[2]))
        elif cmd == "selfcheck":
            a = json.loads((a3.ANN / sys.argv[2] / f"{sys.argv[3]}.json").read_text())
            e = a3.check(a)
            print("OK" if not e else f"ERRORS: {e}")
            sys.exit(1 if e else 0)
        elif cmd == "disagreements":
            a3.disagreements()
        elif cmd == "a3packets":
            a3.a3packets()
        else:
            raise SystemExit(f"unknown command {cmd}")
