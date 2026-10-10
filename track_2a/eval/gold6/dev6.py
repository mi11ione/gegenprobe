"""P5 development set (not a test): ~40 fresh whole affairs from parliaments with varied layouts, labelled by blind
agent annotators (eval/gold6/GUIDE_P5.md) and used to develop and tune the Q/A, people, recommendation and reasoning
extractor (src/gegenprobe/qa/). The P5 test (eval/prereg6/PREREG6.md) is drawn later, after its lock, from other bodies.

    python -m eval.gold6.dev6 draw       network: polite PDF fetches -> data/gold6/p5dev_affairs.jsonl (+ fetch log)
    python -m eval.gold6.dev6 packets    -> .work/p5dev/packets/<affair_id>.txt (never committed)
"""

from __future__ import annotations

import collections
import json
import sys

from eval.gold6 import common6 as C
from gegenprobe.paths import WORK

SEED = 20261020
DEV = C.GOLD6 / "p5dev_affairs.jsonl"
DEV_LOG = C.GOLD6 / "p5dev_fetch_log.jsonl"
PACK = WORK / "p5dev" / "packets"
# (body, language of the member's text or None = any, n). Bodies here are NOT used for the P5 test sample.
QUOTAS = [
    ("BS", None, 3),
    ("ZH", None, 3),
    ("LU", None, 3),
    ("261", None, 3),  # Zürich city
    ("BE", "de", 2),
    ("BE", "fr", 1),
    ("NW", None, 2),
    ("OW", None, 2),
    ("62", None, 2),  # Kloten
    ("VD", None, 4),
    ("GE", None, 3),
    ("6643", None, 2),  # Vernier
    ("TI", None, 5),
    ("5002", None, 5),  # Bellinzona
]
# Top-up after the first draw (10 Oct): NW, OW and Kloten were unreachable (robots.txt fail-closed) and Bellinzona's
# member texts had no extractable text; motions/postulates were too few for the recommendation field. Drawn with the same
# seed, excluding every affair already drawn.
TOPUP = [
    ("TI", None, 3),
    ("131", None, 2),  # Adliswil
    ("53", None, 2),  # Bülach
    ("191", None, 2),  # Dübendorf
    ("BS", None, 2, "Postulate"),
    ("BS", None, 1, "Motion"),
    ("LU", None, 2, "Motion"),
    ("261", None, 1, "Motion"),
]
DEV_BODIES = sorted({q[0] for q in QUOTAS + TOPUP})


def rows() -> list[dict]:
    return [json.loads(line) for line in open(DEV)]


def draw() -> None:
    if DEV.exists():
        raise SystemExit(f"{DEV} exists")
    xd, xa = C.exclusions()
    got, log = C.draw(QUOTAS, SEED, "p5dev", xd, xa)
    C.GOLD6.mkdir(parents=True, exist_ok=True)
    with open(DEV, "w") as f:
        for r in got:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(DEV_LOG, "w") as f:
        for r in log:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(collections.Counter((r["body"], r["affair_type"]) for r in got))
    print("total", len(got))


def topup() -> None:
    have = rows()
    if any(r.get("topup") for r in have):
        raise SystemExit("top-up already drawn")
    xd, xa = C.exclusions()
    xa |= {r["affair_id"] for r in have}
    got, log = C.draw(TOPUP, SEED, "p5dev", xd, xa)
    with open(DEV, "a") as f:
        for r in got:
            f.write(json.dumps(dict(r, topup=True), ensure_ascii=False) + "\n")
    with open(DEV_LOG, "a") as f:
        for r in log:
            f.write(json.dumps(dict(r, topup=True), ensure_ascii=False) + "\n")
    print(collections.Counter((r["body"], r["affair_type"]) for r in got))
    print("top-up", len(got), "total", len(have) + len(got))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "draw":
        draw()
    elif cmd == "topup":
        topup()
    elif cmd == "packets":
        C.write_packets(rows(), PACK)
        print(f"{len(rows())} packets in {PACK}")
