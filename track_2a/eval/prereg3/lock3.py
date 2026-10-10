"""P3 pre-registration lock: sha256 of every file that decides a P3 result, written before any P3 label exists.

    python -m eval.prereg3.lock3 write   -> eval/prereg3/LOCK3 (requires eval/prereg3/PREREG3.md: the draft, renamed when final)
    python -m eval.prereg3.lock3 check   -> exit 1 listing every P3 file, or P1 frozen file, changed since LOCK3

LOCK3 carries the P1 frozen hashes (from eval/prereg/LOCK, verified equal at write time): P3 reuses the frozen cascade,
lattice, rules and pointer, and the frozen θ for the answer date.
"""

from __future__ import annotations

import glob
import hashlib
import json
import sys
import time

from gegenprobe.paths import ROOT

P3_FIXED = [
    "eval/prereg3/PREREG3.md",
    "eval/gold3/GUIDE.md",
    "data/gold3/p3_affairs.jsonl",
    "data/gold3/opd_meta_p3.jsonl",
    "data/gold3/body_names_p3.json",
    "eval/gold3/__init__.py",
    "eval/gold3/sample.py",
    "eval/gold3/annotate3.py",
    "eval/gold3/run_p3.py",
    "eval/gold3/score3.py",
    "src/gegenprobe/pdftext.py",
]
P3_GLOBS = ["src/gegenprobe/affair/*.py", "src/prompts/*/affair_*.txt"]
LOCK1 = ROOT / "eval" / "prereg" / "LOCK"
LOCK3 = ROOT / "eval" / "prereg3" / "LOCK3"


def files() -> list[str]:
    out = list(P3_FIXED)
    for g in P3_GLOBS:
        out += sorted(str((ROOT / p).relative_to(ROOT)) for p in glob.glob(str(ROOT / g)))
    return out


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def write() -> None:
    if (ROOT / "data" / "gold3" / "p3_labels.jsonl").exists():
        raise SystemExit("P3 labels already exist: a lock now would not pre-date them")
    missing = [f for f in files() if not (ROOT / f).exists()]
    if missing:
        raise SystemExit(f"cannot lock, missing: {missing}")
    p1 = json.loads(LOCK1.read_text())["files"]
    drift = [f for f, h in p1.items() if digest(f) != h]
    if drift:
        raise SystemExit(f"P1 frozen files changed since LOCK: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p3_files={f: digest(f) for f in files()}, p1_frozen=p1)
    LOCK3.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK3: {len(d['p3_files'])} P3 files + {len(p1)} P1 frozen files")


def check() -> list[str]:
    d = json.loads(LOCK3.read_text())
    return [f for f, h in {**d["p1_frozen"], **d["p3_files"]}.items() if not (ROOT / f).exists() or digest(f) != h]


if __name__ == "__main__":
    if sys.argv[1] == "write":
        write()
    else:
        ch = check()
        print("LOCK3 intact" if not ch else "changed since LOCK3: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
