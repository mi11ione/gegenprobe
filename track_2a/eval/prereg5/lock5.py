"""P3b pre-registration lock: sha256 of PREREG5.md and of every file that decides a P3b result, written before the P3b
affairs are drawn and before any P3b label exists (eval/prereg5/PREREG5.md, "Frozen").

    python -m eval.prereg5.lock5 write   -> eval/prereg5/LOCK5 (committed; the commit time is the registration time)
    python -m eval.prereg5.lock5 check   -> exit 1 listing every P3b file, or P1 frozen file, changed since LOCK5

Written only if LOCK3 is intact (the extractor, prompts, runner, scorer and annotation tooling are byte-identical to P3's)
and the P1 frozen files equal eval/prereg/LOCK; LOCK5 carries the P1 hashes so one check covers the whole frozen system.
"""

from __future__ import annotations

import glob
import hashlib
import json
import sys
import time

from gegenprobe.paths import ROOT

P5_FIXED = [
    # registration
    "eval/prereg5/PREREG5.md",
    "eval/prereg5/__init__.py",
    "eval/prereg5/lock5.py",
    "eval/gold3/GUIDE.md",
    # P3b tooling (wrappers around the P3 code)
    "eval/gold5/__init__.py",
    "eval/gold5/sample5.py",
    "eval/gold5/packets5.py",
    "eval/gold5/run_p3b.py",
    "eval/gold5/score5.py",
    "eval/gold5/hypotheses5.py",
    # P3 code the wrappers call
    "eval/gold3/__init__.py",
    "eval/gold3/sample.py",
    "eval/gold3/annotate3.py",
    "eval/gold3/run_p3.py",
    "eval/gold3/score3.py",
    "eval/gold3/hypotheses3.py",
    "eval/baselines.py",
    # sampling and backend
    "eval/__init__.py",
    "eval/gold/__init__.py",
    "eval/gold/sample.py",
    "eval/gold/doctype.py",
    "eval/gold2/__init__.py",
    "eval/gold2/sample.py",
    "eval/arms.py",
    "eval/score.py",
    "eval/naive_baseline.py",
    # extractor, converter (incl. the overlay), runtime
    "src/gegenprobe/__init__.py",
    "src/gegenprobe/paths.py",
    "src/gegenprobe/pdftext.py",
    "src/gegenprobe/net.py",
    "src/gegenprobe/hardening.py",
    "src/gegenprobe/llm.py",
    "src/gegenprobe/stats.py",
    "src/gegenprobe/schema/__init__.py",
    "src/gegenprobe/schema/schema_v0_1.py",
    "src/gegenprobe/census/__init__.py",
    "src/gegenprobe/census/defs.py",
    "src/gegenprobe/census/tables.py",
    "src/gegenprobe/census/funnel.py",
    "src/gegenprobe/convert/__init__.py",
    "src/gegenprobe/convert/calibrate.py",
    "src/gegenprobe/convert/cascade.py",
    "src/gegenprobe/convert/lattice.py",
    "src/gegenprobe/convert/pointer.py",
    "src/gegenprobe/convert/rules.py",
    "src/gegenprobe/convert/overlay.py",
    # data read at run time
    "data/schema/affair_types.json",
    "data/schema/opd_event_titles.json",
    "data/convert/affair_numbers.json.gz",
    "data/convert/rules_coverage.json",
    "data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json",
    "data/census/affairs.tsv.gz",
    "data/census/events.tsv.gz",
    "data/census/agendas.tsv.gz",
    "data/census/docs.tsv.gz",
    "data/census/docs_other.tsv.gz",
    "data/census/texts.tsv.gz",
    "data/census/be_ogd_answers.tsv.gz",
    # exclusion sources
    "data/gold/dev_ids.json",
    "data/gold/dev_docs.jsonl",
    "data/gold/heldout_docs.jsonl",
    "data/gold2/p2_docs.jsonl",
    "data/gold3/p3_affairs.jsonl",
    "data/gold4/p4_meetings.jsonl",
    "data/gold4/p4_heldout_meetings.jsonl",
    "data/gold4/p4_transfer_meetings.jsonl",
    # P3 reference for the success criteria
    "results/eval3/hypotheses3__publicai_swiss-ai_apertus-v1.5-8b.json",
]
P5_GLOBS = ["src/gegenprobe/affair/*.py", "src/prompts/*/affair_*.txt"]
LOCK1 = ROOT / "eval" / "prereg" / "LOCK"
LOCK5 = ROOT / "eval" / "prereg5" / "LOCK5"
NOT_YET = ["data/gold5/p3b_affairs.jsonl", "data/gold5/p3b_labels.jsonl"]


def files() -> list[str]:
    out = list(P5_FIXED)
    for g in P5_GLOBS:
        out += sorted(str((ROOT / p).relative_to(ROOT)) for p in glob.glob(str(ROOT / g)))
    return out


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def write() -> None:
    from eval.prereg3 import lock3

    if any((ROOT / f).exists() for f in NOT_YET):
        raise SystemExit("P3b draw or labels already exist: a lock now would not pre-date them")
    missing = [f for f in files() if not (ROOT / f).exists()]
    if missing:
        raise SystemExit(f"cannot lock, missing: {missing}")
    p3 = lock3.check()
    if p3:
        raise SystemExit(f"LOCK3 not intact (the P3b extractor must equal P3's): {p3}")
    p1 = json.loads(LOCK1.read_text())["files"]
    drift = [f for f, h in p1.items() if digest(f) != h]
    if drift:
        raise SystemExit(f"P1 frozen files changed since LOCK: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p5_files={f: digest(f) for f in files()}, p1_frozen=p1)
    LOCK5.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK5: {len(d['p5_files'])} P3b files + {len(p1)} P1 frozen files")


def check() -> list[str]:
    d = json.loads(LOCK5.read_text())
    return [f for f, h in {**d["p1_frozen"], **d["p5_files"]}.items() if not (ROOT / f).exists() or digest(f) != h]


if __name__ == "__main__":
    if sys.argv[1] == "write":
        write()
    else:
        ch = check()
        print("LOCK5 intact" if not ch else "changed since LOCK5: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
