"""P8 pre-registration lock: sha256 of every file that decides a P8 result, written before any P8 affair is drawn.

    python -m eval.prereg9.lock9 write   -> eval/prereg9/LOCK9 (committed; the commit time is the registration time)
    python -m eval.prereg9.lock9 check   -> exit 1 listing every hashed file changed since LOCK9

`write` refuses if a P8 draw, key, annotation or gold file exists, or if any file frozen by an earlier lock
(eval/prereg*/LOCK*) that P8 uses differs from its locked hash. The WORK files that define part of the exclusions (P7
dev and test keys, adapter audits; never committed) are recorded by hash under `work_inputs`.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time

from gegenprobe.paths import ROOT

P8_FILES = [
    "eval/prereg9/PREREG9.md",
    "eval/prereg9/lock9.py",
    "eval/prereg9/__init__.py",
    "eval/p8/__init__.py",
    "eval/p8/common.py",
    "eval/p8/derive.py",
    "eval/p8/sample.py",
    "eval/p8/packets.py",
    "eval/p8/annotate.py",
    "eval/p8/score.py",
    "eval/p8/hypotheses9.py",
    "eval/p8/qwen9.py",
    "eval/p8/selftest.py",
    "eval/p8/GUIDE_P8.md",
    "results/p8/pool_probe.json",
]
# reused code and data: the qualification rule, the fetch path, the metadata route, the date parser, the statistics
REUSED = [
    "src/gegenprobe/affair/extract.py",
    "src/gegenprobe/affair/meta.py",
    "src/gegenprobe/census/defs.py",
    "src/gegenprobe/repair/common.py",
    "src/gegenprobe/stats.py",
    "src/gegenprobe/pdftext.py",
    "src/gegenprobe/paths.py",
    "src/gegenprobe/devpaths.py",
    "src/gegenprobe/compliance/fetchguard.py",
    "data/schema/affair_types.json",
    "data/schema/opd_event_titles.json",
    "eval/gold/sample.py",
    "eval/gold/doctype.py",
    "eval/gold2/sample.py",
    "eval/gold3/sample.py",
    "eval/p6/common.py",
]
# the committed lists that define the exclusions (with WORK inputs below)
EXCLUSION_LISTS = [
    "data/gold/dev_docs.jsonl",
    "data/gold/heldout_docs.jsonl",
    "data/gold/dev_ids.json",
    "data/gold2/p2_docs.jsonl",
    "data/gold3/p3_affairs.jsonl",
    "data/gold5/p3b_affairs.jsonl",
    "data/gold4/p4_meetings.jsonl",
    "data/gold4/p4_heldout_meetings.jsonl",
    "data/gold4/p4_transfer_meetings.jsonl",
    "data/gold6/p5_affairs.jsonl",
    "data/gold6/p5_fetch_log.jsonl",
    "data/gold6/p5dev_affairs.jsonl",
    "data/gold6/p5dev_fetch_log.jsonl",
    "data/p6/dev2_docs.jsonl",
    "data/p6/p6_docs.jsonl",
]
LOCK9 = ROOT / "eval" / "prereg9" / "LOCK9"
EARLIER = sorted((ROOT / "eval").glob("prereg*/LOCK*"))


def files() -> list[str]:
    return P8_FILES + REUSED + EXCLUSION_LISTS


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def work_inputs() -> dict[str, str]:
    from eval.p8 import common as C

    return {f"WORK/{k}": v for k, v in C.work_inputs().items()}


def earlier_frozen() -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, str) and len(v) == 64 and "/" in k:
                    out.setdefault(k, v)
                else:
                    walk(v)

    for p in EARLIER:
        if p.name == "LOCK9":
            continue
        try:
            walk(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def write() -> None:
    from eval.p8 import common as C

    for p in (C.AFFAIRS, C.KEY, C.GOLD, C.ANN, C.DATELISTS):
        if p.exists():
            raise SystemExit(f"{p} exists: a lock now would not pre-date the P8 draw")
    fs = files()
    prev = earlier_frozen()
    drift = [f for f in fs if f in prev and digest(f) != prev[f]]
    if drift:
        raise SystemExit(f"files frozen by an earlier lock changed: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p8_files={f: digest(f) for f in fs},
             work_inputs=work_inputs(), also_frozen_by_earlier_locks=sorted(f for f in fs if f in prev))
    LOCK9.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK9: {len(d['p8_files'])} files, {len(d['work_inputs'])} WORK inputs "
          f"({len(d['also_frozen_by_earlier_locks'])} also frozen by earlier locks)")


def check() -> list[str]:
    d = json.loads(LOCK9.read_text())
    bad = [f for f, h in d["p8_files"].items() if not (ROOT / f).exists() or digest(f) != h]
    w = work_inputs()
    return bad + [k for k, h in d["work_inputs"].items() if w.get(k) != h]


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        write()
    else:
        ch = check()
        print("LOCK9 intact" if not ch else "changed since LOCK9: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
