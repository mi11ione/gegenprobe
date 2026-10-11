"""P7 pre-registration lock: sha256 of every file that decides a P7 result, written before any P7 test row is drawn.

    python -m eval.prereg8.lock8 write   -> eval/prereg8/LOCK8 (committed; the commit time is the registration time)
    python -m eval.prereg8.lock8 check   -> exit 1 listing every hashed file changed since LOCK8

`write` refuses if the P7 test key or sample exists, or if any file frozen by an earlier lock (eval/prereg*/LOCK*) that
P7 uses differs from its locked hash. Inputs in WORK (never committed: the adapter targets, the dev key, the audit
samples that define the exclusions) are recorded by hash under `work_inputs`.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time

from gegenprobe.paths import ROOT, WORK

ADAPTERS = ["adjudicate", "base", "registry", "inopd", "run", "lists", "audit3", "targets", "filters", "zh",
            "zurich_city", "ris4tw", "vs", "lu", "aarau", "opd_docs"]
P7_FILES = [
    "eval/prereg8/PREREG8.md",
    "eval/prereg8/lock8.py",
    "eval/prereg8/__init__.py",
    "eval/p7/__init__.py",
    "eval/p7/common.py",
    "eval/p7/dev.py",
    "eval/p7/tune.py",
    "eval/p7/test.py",
    "eval/p7/hypotheses8.py",
    "eval/p7/qwen8.py",
    "data/p7/p7_config.json",
    "data/p7/dev_annotations/A1.jsonl",
    "data/p7/dev_annotations/A2.jsonl",
    "data/p7/dev_annotations/A3.jsonl",
    "data/p7/dev_annotations/a3_order.json",
    "data/p7/dev_annotations/gold.jsonl",
    "results/p7/dev_sample.json",
    "results/p7/dev_table.json",
    *[f"src/gegenprobe/repair/adapters/{m}.py" for m in ADAPTERS],
    "src/gegenprobe/repair/common.py",
    "src/gegenprobe/convert/pointer_v2.py",
    "src/gegenprobe/llm.py",
    "src/gegenprobe/stats.py",
    "src/gegenprobe/paths.py",
    "eval/arms.py",
    "results/repair/adapters/adapters_summary.json",
]
LOCK8 = ROOT / "eval" / "prereg8" / "LOCK8"
EARLIER = sorted((ROOT / "eval").glob("prereg*/LOCK*"))


def files() -> list[str]:
    lists = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "results/repair/adapters").glob("adapters_*.tsv"))
    return P7_FILES + lists


def work_inputs() -> dict[str, str]:
    out = {}
    for rel in ("adapters/targets.json.gz", "p7dev/key.jsonl", "adapters/audit3/key.jsonl"):
        out[f"WORK/{rel}"] = hashlib.sha256((WORK / rel).read_bytes()).hexdigest()
    for g in ("audit", "audit_orig_backup", "audit2"):
        h = hashlib.sha256()
        for p in sorted((WORK / "adapters" / g).glob("*.jsonl")):
            h.update(p.name.encode() + b"\0" + p.read_bytes())
        out[f"WORK/adapters/{g}/*.jsonl"] = h.hexdigest()
    return out


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


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
        if p.name == "LOCK8":
            continue
        try:
            walk(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def write() -> None:
    for p in (WORK / "p7test" / "key.jsonl", ROOT / "results/p7/test_sample.json"):
        if p.exists():
            raise SystemExit(f"{p} exists: a lock now would not pre-date the P7 test draw")
    fs = files()
    prev = earlier_frozen()
    drift = [f for f in fs if f in prev and digest(f) != prev[f]]
    if drift:
        raise SystemExit(f"files frozen by an earlier lock changed: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p7_files={f: digest(f) for f in fs},
             work_inputs=work_inputs(), also_frozen_by_earlier_locks=sorted(f for f in fs if f in prev))
    LOCK8.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK8: {len(d['p7_files'])} files, {len(d['work_inputs'])} WORK inputs "
          f"({len(d['also_frozen_by_earlier_locks'])} also frozen by earlier locks)")


def check() -> list[str]:
    d = json.loads(LOCK8.read_text())
    bad = [f for f, h in d["p7_files"].items() if not (ROOT / f).exists() or digest(f) != h]
    w = work_inputs()
    return bad + [k for k, h in d["work_inputs"].items() if w.get(k) != h]


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        write()
    else:
        ch = check()
        print("LOCK8 intact" if not ch else "changed since LOCK8: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
