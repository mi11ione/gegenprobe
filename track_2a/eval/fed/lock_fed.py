"""Federal cell lock: sha256 of every file that decides a federal-cell result, written before any federal affair is drawn.

    python -m eval.fed.lock_fed write   -> eval/fed/LOCKFED (committed; the commit time is the registration time)
    python -m eval.fed.lock_fed check   -> exit 1 listing every hashed file or input changed since LOCKFED

Same style as eval/prereg9/lock9.py. `write` refuses if a federal draw, key, annotation or gold file exists, if the
self-test fails, or if any file frozen by an earlier lock (eval/prereg*/LOCK*) that the cell uses differs from its locked
hash. Hashed: the protocol and the cell's own code and guide; the converter and pointer code, prompts and θ the arms
run; the P8 tooling and every file LOCK9 freezes (the cell reuses P8's packet format, annotation checks, derivation and
exclusions); the pool probe. Inputs that are never committed are recorded by hash under `work_inputs`: the texts_CHE scan
(from which the frame and the draw are computed), OPD's snapshot exports the frame and the metadata come from, P8's
WORK exclusion inputs, and the budget gateway client the pointer arm calls through.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from gegenprobe import devpaths
from gegenprobe.paths import OPD_RAW, ROOT, WORK

FED_FILES = [
    "eval/fed/PROTOCOL.md",
    "eval/fed/lock_fed.py",
    "eval/fed/__init__.py",
    "eval/fed/common.py",
    "eval/fed/draw.py",
    "eval/fed/packets.py",
    "eval/fed/annotate.py",
    "eval/fed/arms.py",
    "eval/fed/score.py",
    "eval/fed/selftest.py",
    "eval/fed/GUIDE_FED.md",
    "results/fed/pool_probe.json",
]
# what the arms run: the P1 answer-date rules and pointer, the P3 whole-affair converter, the product post-processing,
# the v0.2 carry and validation, the review-mode build guard, prompts and θ, the backend and the fetch path
CONVERTER = [
    "src/gegenprobe/convert/rules.py",
    "src/gegenprobe/convert/pointer.py",
    "src/gegenprobe/convert/lattice.py",
    "src/gegenprobe/convert/cascade.py",
    "src/gegenprobe/convert/batch.py",
    "src/gegenprobe/convert/build_guard.py",
    "src/gegenprobe/affair/build.py",
    "src/gegenprobe/affair/extract.py",
    "src/gegenprobe/affair/meta.py",
    "src/gegenprobe/affair_post.py",
    "src/gegenprobe/schema/schema_v0_1.py",
    "src/gegenprobe/schema/v0_2_all.py",
    "src/gegenprobe/schema/p8_v0_2.py",
    "schema/gegenprobe_schema_v0_2.py",
    "src/gegenprobe/llm.py",
    "src/gegenprobe/net.py",
    "src/gegenprobe/robots9309.py",
    "src/gegenprobe/compliance/fetchguard.py",
    "src/gegenprobe/census/defs.py",
    "src/gegenprobe/census/scan.py",
    "src/gegenprobe/stats.py",
    "src/gegenprobe/paths.py",
    "data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json",
    "results/eval/served_models.json",
    "data/schema/null_reasons.json",
    "eval/arms.py",
    "eval/score.py",
    "eval/gold/annotate.py",
    "eval/gold2/GUIDE.md",
    "eval/p8/derive.py",
    "eval/p8/packets.py",
    "eval/p8/annotate.py",
] + [f"src/prompts/{lg}/{p}.txt" for lg in ("de", "fr", "it") for p in (
    "answer_date", "recommendation", "affair_submitter", "affair_submitted", "affair_addressed_body", "affair_affair_type")]
# the converter's role rules (round 13): frozen and run as an arm only if committed when the lock is written
ROLES = "src/gegenprobe/convert/roles.py"
LOCKFED = ROOT / "eval" / "fed" / "LOCKFED"
EARLIER = sorted((ROOT / "eval").glob("prereg*/LOCK*"))
GATEWAY = devpaths.gateway_dir() / "gw.py"


def files() -> list[str]:
    from eval.prereg9 import lock9

    roles = [ROLES, "src/gegenprobe/repair/common.py"] if roles_committed() else []
    return list(dict.fromkeys(FED_FILES + CONVERTER + roles + lock9.files()))


def roles_committed() -> bool:
    """The role rules join the registered converter only as committed (tracked, no uncommitted change)."""
    import subprocess

    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ROLES], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", ROLES], cwd=ROOT).returncode == 0
    return tracked and clean


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 24):
            h.update(b)
    return h.hexdigest()


def work_inputs() -> dict[str, str]:
    from eval.fed import common as C
    from eval.p8 import common as C8

    out = {f"WORK/{p.relative_to(WORK)}": _sha_file(p) for p in (C.SCAN, C.SCAN_INFO)}
    out.update({f"OPD_RAW/{n}.ndjson.gz": _sha_file(OPD_RAW / f"{n}.ndjson.gz") for n in ("affairs", "events", "contributors")})
    out.update({f"WORK/{k}": v for k, v in C8.work_inputs().items()})
    out["EXTERNAL/gateway/gw.py"] = _sha_file(GATEWAY) if GATEWAY.exists() else "missing"
    return out


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
        try:
            walk(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def write() -> None:
    from eval.fed import common as C
    from eval.fed import selftest

    for p in (C.DF / "fed_draw.jsonl", C.AFFAIRS, C.KEY, C.GOLD, C.ANN):
        if p.exists():
            raise SystemExit(f"{p} exists: a lock now would not pre-date the federal draw")
    if selftest.main() != 0:
        raise SystemExit("the self-test fails: no lock")
    fs = files()
    prev = earlier_frozen()
    drift = [f for f in fs if f in prev and digest(f) != prev[f]]
    if drift:
        raise SystemExit(f"files frozen by an earlier lock changed: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), fed_files={f: digest(f) for f in fs},
             work_inputs=work_inputs(), also_frozen_by_earlier_locks=sorted(f for f in fs if f in prev))
    LOCKFED.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCKFED: {len(d['fed_files'])} files, {len(d['work_inputs'])} WORK/external inputs "
          f"({len(d['also_frozen_by_earlier_locks'])} also frozen by earlier locks)")


def check() -> list[str]:
    d = json.loads(LOCKFED.read_text())
    bad = [f for f, h in d["fed_files"].items() if not (ROOT / f).exists() or digest(f) != h]
    w = work_inputs()
    return bad + [k for k, h in d["work_inputs"].items() if w.get(k) != h]


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        write()
    else:
        ch = check()
        print("LOCKFED intact" if not ch else "changed since LOCKFED: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
