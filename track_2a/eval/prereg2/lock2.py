"""P2 pre-registration lock: sha256 of every file that decides a P2 result, written before any P2 label exists.

    python -m eval.prereg2.lock2 write   -> eval/prereg2/LOCK2 (committed; the commit time is the registration time)
    python -m eval.prereg2.lock2 check   -> exit 1 listing every P2 file, or P1 frozen file, changed since LOCK2

LOCK2 also carries the P1 frozen hashes (copied from eval/prereg/LOCK, verified equal at write time), so one check covers
the whole frozen system P2 runs on. New relative to P1: text extraction (src/gegenprobe/pdftext.py) is hashed too.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time

from gegenprobe.paths import ROOT

P2_FILES = [
    "eval/prereg2/PREREG2.md",
    "eval/gold2/SEEDS.md",
    "eval/gold2/GUIDE.md",
    "data/gold2/p2_docs.jsonl",
    "eval/gold2/__init__.py",
    "eval/gold2/sample.py",
    "eval/gold2/annotate2.py",
    "eval/gold2/run_p2.py",
    "eval/gold2/hypotheses2.py",
    "src/gegenprobe/pdftext.py",
]
LOCK1 = ROOT / "eval" / "prereg" / "LOCK"
LOCK2 = ROOT / "eval" / "prereg2" / "LOCK2"


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def write() -> None:
    if (ROOT / "data" / "gold2" / "p2_labels.jsonl").exists():
        raise SystemExit("P2 labels already exist: a lock now would not pre-date them")
    p1 = json.loads(LOCK1.read_text())["files"]
    drift = [f for f, h in p1.items() if digest(f) != h]
    if drift:
        raise SystemExit(f"P1 frozen files changed since LOCK: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p2_files={f: digest(f) for f in P2_FILES}, p1_frozen=p1)
    LOCK2.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK2: {len(d['p2_files'])} P2 files + {len(p1)} P1 frozen files")


def check() -> list[str]:
    d = json.loads(LOCK2.read_text())
    files = {**d["p1_frozen"], **d["p2_files"]}
    return [f for f, h in files.items() if not (ROOT / f).exists() or digest(f) != h]


if __name__ == "__main__":
    if sys.argv[1] == "write":
        write()
    else:
        ch = check()
        print("LOCK2 intact" if not ch else "changed since LOCK2: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
