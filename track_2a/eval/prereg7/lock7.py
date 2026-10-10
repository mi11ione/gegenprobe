"""P6 pre-registration lock: sha256 of every file that decides a P6 result, written before any P6 document is drawn.

    python -m eval.prereg7.lock7 write   -> eval/prereg7/LOCK7 (committed; the commit time is the registration time)
    python -m eval.prereg7.lock7 check   -> exit 1 listing every hashed file changed since LOCK7

`write` refuses if the P6 document list or labels exist, or if any file frozen by an earlier lock (eval/prereg*/LOCK*) that
P6 imports differs from its locked hash.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time

from gegenprobe.paths import ROOT

PROMPTS = [
    f"src/prompts/{lg}/{n}.txt"
    for lg in ("de", "fr", "it")
    for n in ("answer_present", "answer_decision_mcq", "answer_dispatch_mcq", "answer_date_mcq", "naive_guided",
              "naive_null", "naive_plain", "answer_date")
]
P6_FILES = [
    "eval/prereg7/PREREG7.md",
    "eval/prereg7/lock7.py",
    "eval/p6/__init__.py",
    "eval/p6/common.py",
    "eval/p6/sample.py",
    "eval/p6/dev2.py",
    "eval/p6/run_p6.py",
    "eval/p6/hypotheses7.py",
    "eval/p6/DEV2_SELECTION.md",
    "data/p6/v2_config.json",
    "data/p6/dev2_docs.jsonl",
    "results/p6/dev2_selection.json",
    "src/gegenprobe/convert/pointer_v2.py",
    "src/gegenprobe/convert/pointer.py",
    "src/gegenprobe/convert/cascade.py",
    "src/gegenprobe/convert/rules.py",
    "src/gegenprobe/convert/lattice.py",
    "src/gegenprobe/llm.py",
    "src/gegenprobe/pdftext.py",
    "src/gegenprobe/net.py",
    "src/gegenprobe/stats.py",
    "data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json",
    "eval/arms.py",
    "eval/score.py",
    "eval/naive_baseline.py",
    "eval/posthoc_r3.py",
    "eval/gold/annotate.py",
    "eval/gold/sample.py",
    "eval/gold2/sample.py",
    "eval/gold2/GUIDE.md",
    *PROMPTS,
]
LOCK7 = ROOT / "eval" / "prereg7" / "LOCK7"
EARLIER = sorted((ROOT / "eval").glob("prereg*/LOCK*"))


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def earlier_frozen() -> dict[str, str]:
    """Every file hash recorded by an earlier lock, flattened (later locks re-record the P1 files; they must agree)."""
    out: dict[str, str] = {}

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, str) and len(v) == 64 and "/" in k:
                    out.setdefault(k, v)
                else:
                    walk(v)

    for p in EARLIER:
        if p.name == "LOCK7":
            continue
        try:
            walk(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def write() -> None:
    for rel in ("data/p6/p6_docs.jsonl", "data/p6/p6_labels.jsonl"):
        if (ROOT / rel).exists():
            raise SystemExit(f"{rel} exists: a lock now would not pre-date the P6 draw")
    prev = earlier_frozen()
    drift = [f for f in P6_FILES if f in prev and digest(f) != prev[f]]
    if drift:
        raise SystemExit(f"files frozen by an earlier lock changed: {drift}")
    d = dict(
        written=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        p6_files={f: digest(f) for f in P6_FILES},
        also_frozen_by_earlier_locks=sorted(f for f in P6_FILES if f in prev),
    )
    LOCK7.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK7: {len(d['p6_files'])} files ({len(d['also_frozen_by_earlier_locks'])} also frozen by earlier locks)")


def check() -> list[str]:
    d = json.loads(LOCK7.read_text())
    return [f for f, h in d["p6_files"].items() if not (ROOT / f).exists() or digest(f) != h]


if __name__ == "__main__":
    if sys.argv[1] == "write":
        write()
    else:
        ch = check()
        print("LOCK7 intact" if not ch else "changed since LOCK7: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
