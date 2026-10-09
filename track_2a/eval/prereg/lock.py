"""Pre-registration lock: sha256 of every file that decides a held-out result, written before any held-out label exists.

    python -m eval.prereg.lock write   -> eval/prereg/LOCK (committed; the commit timestamp is the registration time)
    python -m eval.prereg.lock check   -> exit 1 and list every frozen file whose content changed since LOCK

A change after the lock is allowed only as a reported deviation (eval/prereg/DEVIATIONS.md); `check` makes it visible.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time

from gegenprobe.paths import ROOT

FROZEN = [
    "eval/prereg/PREREG.md",
    "docs/gold_protocol.md",
    "data/gold/README.md",
    "data/gold/heldout_docs.jsonl",
    "eval/gold/annotate.py",
    "eval/score.py",
    "eval/arms.py",
    "eval/naive_baseline.py",
    "src/gegenprobe/convert/lattice.py",
    "src/gegenprobe/convert/rules.py",
    "src/gegenprobe/convert/pointer.py",
    "src/gegenprobe/convert/calibrate.py",
    "src/gegenprobe/convert/cascade.py",
    "src/gegenprobe/llm.py",
]
FROZEN_GLOBS = ["src/prompts/*/*.txt", "data/convert/theta/*.json"]
LOCK = ROOT / "eval" / "prereg" / "LOCK"


def files() -> list[str]:
    out = list(FROZEN)
    for g in FROZEN_GLOBS:
        out += sorted(str(p.relative_to(ROOT)) for p in ROOT.glob(g))
    return out


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def write() -> None:
    missing = [f for f in files() if not (ROOT / f).exists()]
    if missing:
        raise SystemExit(f"cannot lock, missing: {missing}")
    if (ROOT / "data" / "gold" / "heldout_labels.jsonl").exists():
        raise SystemExit("held-out labels already exist: a lock now would not pre-date them")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), files={f: digest(f) for f in files()})
    LOCK.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK: {len(d['files'])} files")


def check() -> list[str]:
    d = json.loads(LOCK.read_text())
    changed = [f for f, h in d["files"].items() if not (ROOT / f).exists() or digest(f) != h]
    return changed


if __name__ == "__main__":
    if sys.argv[1] == "write":
        write()
    else:
        ch = check()
        print("LOCK intact" if not ch else "changed since LOCK: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
