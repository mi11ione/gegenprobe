"""P4 pre-registration lock (virtual affairs): sha256 of every file that decides a P4 result, written before the P4
held-out meetings are drawn and before any P4 label exists.

    python -m eval.prereg4.lock4 write   -> eval/prereg4/LOCK4 (committed; the commit time is the registration time)
    python -m eval.prereg4.lock4 check   -> exit 1 listing every P2 file, or P1 frozen file, changed since LOCK2

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
    "eval/prereg4/PREREG4.md",
    "eval/gold4/GUIDE.md",
    "data/gold4/p4_meetings.jsonl",
    "eval/gold4/__init__.py",
    "eval/gold4/sample.py",
    "eval/gold4/packets.py",
    "eval/gold4/run_p4.py",
    "eval/gold4/merge4.py",
    "src/gegenprobe/virtual/__init__.py",
    "src/gegenprobe/virtual/agenda.py",
    "src/gegenprobe/virtual/minutes.py",
    "src/gegenprobe/virtual/classify.py",
    "src/gegenprobe/virtual/pointer4.py",
    "src/gegenprobe/virtual/derive.py",
    "src/prompts/fr/virtual_decision.txt",
    "src/prompts/fr/virtual_type.txt",
    "src/prompts/de/virtual_decision.txt",
    "src/prompts/de/virtual_type.txt",
    "src/gegenprobe/pdftext.py",
]
LOCK1 = ROOT / "eval" / "prereg" / "LOCK"
LOCK2 = ROOT / "eval" / "prereg4" / "LOCK4"


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def write() -> None:
    g4 = ROOT / "data" / "gold4"
    if (g4 / "p4_heldout_labels.jsonl").exists() or (g4 / "p4_heldout_meetings.jsonl").exists():
        raise SystemExit("P4 held-out draw or labels already exist: a lock now would not pre-date them")
    p1 = json.loads(LOCK1.read_text())["files"]
    drift = [f for f, h in p1.items() if digest(f) != h]
    if drift:
        raise SystemExit(f"P1 frozen files changed since LOCK: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p2_files={f: digest(f) for f in P2_FILES}, p1_frozen=p1)
    LOCK2.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK4: {len(d['p2_files'])} P4 files + {len(p1)} P1 frozen files")


def check() -> list[str]:
    d = json.loads(LOCK2.read_text())
    files = {**d["p1_frozen"], **d["p2_files"]}
    return [f for f, h in files.items() if not (ROOT / f).exists() or digest(f) != h]


if __name__ == "__main__":
    if sys.argv[1] == "write":
        write()
    else:
        ch = check()
        print("LOCK4 intact" if not ch else "changed since LOCK4: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
