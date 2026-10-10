"""P5 pre-registration lock: sha256 of PREREG6.md and of every file that decides a P5 result, written before the P5
affairs are drawn and before any P5 label exists (eval/prereg6/PREREG6.md, "Frozen").

    python -m eval.prereg6.lock6 write   -> eval/prereg6/LOCK6 (committed; the commit time is the registration time)
    python -m eval.prereg6.lock6 check   -> exit 1 listing every P5 file, or earlier frozen file, changed since LOCK6

Written only if LOCK5 is intact (the earlier frozen system, incl. the P1 hashes, is unchanged); LOCK6 carries the LOCK5
hashes so one check covers everything.
"""

from __future__ import annotations

import glob
import hashlib
import json
import sys
import time

from gegenprobe.paths import ROOT

P6_FIXED = [
    # registration
    "eval/prereg6/PREREG6.md",
    "eval/prereg6/__init__.py",
    "eval/prereg6/lock6.py",
    "eval/gold6/GUIDE_P5.md",
    # P5 tooling
    "eval/gold6/__init__.py",
    "eval/gold6/common6.py",
    "eval/gold6/dev6.py",
    "eval/gold6/sample6.py",
    "eval/gold6/annotate6.py",
    "eval/gold6/run6.py",
    "eval/gold6/score6.py",
    "eval/gold6/baselines6.py",
    "eval/gold6/freegen6.py",
    "eval/gold6/hypotheses6.py",
    "eval/gold6/qwen6.py",
    "eval/gold6/tune6.py",
    # extractor and runtime
    "src/gegenprobe/qa/__init__.py",
    "src/gegenprobe/qa/text.py",
    "src/gegenprobe/qa/questions.py",
    "src/gegenprobe/qa/answers.py",
    "src/gegenprobe/qa/people.py",
    "src/gegenprobe/qa/rec.py",
    "src/gegenprobe/qa/pointer.py",
    "src/gegenprobe/qa/extract.py",
    "src/prompts/qa_freegen_schema.txt",
    "src/gegenprobe/validate/__init__.py",
    "src/gegenprobe/validate/spans.py",
    "src/gegenprobe/validate/dates.py",
    # P5 development set and its labels (exclusions; θ was fitted on them)
    "data/gold6/p5dev_affairs.jsonl",
    "data/gold6/p5dev_labels.jsonl",
    "data/gold6/theta_p5dev.json",
    # dev results the θ values were fitted on
    "results/eval6/p5dev__publicai_swiss-ai_apertus-v1.5-8b.json",
    "results/eval6/p5dev_ra0_secondary.json",
]
P6_GLOBS = ["src/prompts/*/qa_*.txt"]
LOCK5 = ROOT / "eval" / "prereg5" / "LOCK5"
LOCK6 = ROOT / "eval" / "prereg6" / "LOCK6"
NOT_YET = ["data/gold6/p5_affairs.jsonl", "data/gold6/p5_labels.jsonl"]


def files() -> list[str]:
    out = list(P6_FIXED)
    for g in P6_GLOBS:
        out += sorted(str((ROOT / p).relative_to(ROOT)) for p in glob.glob(str(ROOT / g)))
    return out


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def write() -> None:
    from eval.prereg5 import lock5

    if any((ROOT / f).exists() for f in NOT_YET):
        raise SystemExit("P5 draw or labels already exist: a lock now would not pre-date them")
    missing = [f for f in files() if not (ROOT / f).exists()]
    if missing:
        raise SystemExit(f"cannot lock, missing: {missing}")
    earlier = lock5.check()
    if earlier:
        raise SystemExit(f"LOCK5 not intact: {earlier}")
    l5 = json.loads(LOCK5.read_text())
    frozen = {**l5["p1_frozen"], **l5["p5_files"]}
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p6_files={f: digest(f) for f in files()}, earlier_frozen=frozen)
    LOCK6.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK6: {len(d['p6_files'])} P5 files + {len(frozen)} earlier frozen files")


def check() -> list[str]:
    d = json.loads(LOCK6.read_text())
    return [f for f, h in {**d["earlier_frozen"], **d["p6_files"]}.items() if not (ROOT / f).exists() or digest(f) != h]


if __name__ == "__main__":
    if sys.argv[1] == "write":
        write()
    else:
        ch = check()
        print("LOCK6 intact" if not ch else "changed since LOCK6: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
