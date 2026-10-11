"""P10 pre-registration lock: sha256 of every file that decides a P10 result, written before any P10 affair is drawn.

    python -m eval.prereg10.lock10 write   -> eval/prereg10/LOCK10 (committed; the commit time is the registration time)
    python -m eval.prereg10.lock10 check   -> exit 1 listing every hashed file or input changed since LOCK10

Same style as eval/prereg9/lock9.py and eval/fed/lock_fed.py. `write` refuses if a P10 draw, key, annotation or gold
file exists, if the self-test (eval/p10/selftest.py, synthetic inputs only) fails, if the frozen role rules are not
roles-2 (sha256 FROZEN_ROLES_SHA256), if the development configuration (data/p10/p10_config.json) or results
(results/p10/dev10.json) are missing, or if any file frozen by an earlier lock (eval/prereg*/LOCK*, eval/fed/LOCKFED)
that P10 uses differs from its locked hash. Hashed: the registration and P10's own code and guide; the candidate
generator, the role pointer, its prompts and frozen configuration; the frozen role rules; the reused fetch, metadata,
annotation and statistics code; the development inputs and results; the pool probe. Inputs that are never committed are
recorded by hash under `work_inputs`: OPD's snapshot exports the frame, the rosters and the metadata come from, P8's WORK
exclusion inputs, the development runs (letter / true-false log-probabilities per candidate) and the budget gateway client
the pointer arm calls through.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from gegenprobe.paths import OPD_RAW, ROOT, WORK

FROZEN_ROLES_SHA256 = "5f6c978e0d81f591c6e790c671da210ed58d37e7d2b22311a9bc3e265ae1c2ce"  # roles-2
P10_FILES = [
    "eval/prereg10/PREREG10.md",
    "eval/prereg10/lock10.py",
    "eval/prereg10/__init__.py",
    "eval/p10/__init__.py",
    "eval/p10/common.py",
    "eval/p10/draw.py",
    "eval/p10/packets.py",
    "eval/p10/annotate.py",
    "eval/p10/arms.py",
    "eval/p10/score.py",
    "eval/p10/selftest.py",
    "eval/p10/dev.py",
    "eval/p10/GUIDE_P10.md",
    "results/p10/pool_probe.json",
    "results/p10/pool_probe_run1.txt",
    "results/p10/dev10.json",
    "data/p10/p10_config.json",
]
# the arms: candidates, pointer (+ prompts), the frozen rules, the model backend
ARMS = [
    "src/gegenprobe/convert/role_candidates.py",
    "src/gegenprobe/convert/roles_pointer.py",
    "src/gegenprobe/convert/roles.py",
    "src/gegenprobe/llm.py",
    "eval/arms.py",
] + [f"src/prompts/{lg}/{n}.txt" for lg in ("de", "fr", "it")
     for n in ("role_pointer", "role_author", "role_first", "role_author_v2", "role_notauthor_v2", "role_first_v2")]
# reused: the qualification rule and exclusions, the fetch path, metadata vendoring, annotation checks, statistics,
# the development split and inputs
REUSED = [
    "eval/p8/common.py",
    "eval/p8/annotate.py",
    "eval/p8/derive.py",
    "eval/p8/packets.py",
    "eval/p8/GUIDE_P8.md",
    "eval/converter_roles.py",
    "eval/gold/sample.py",
    "eval/gold2/sample.py",
    "eval/gold3/sample.py",
    "eval/p6/common.py",
    "src/gegenprobe/affair/meta.py",
    "src/gegenprobe/repair/common.py",
    "src/gegenprobe/stats.py",
    "src/gegenprobe/pdftext.py",
    "src/gegenprobe/net.py",
    "src/gegenprobe/robots9309.py",
    "src/gegenprobe/paths.py",
    "src/gegenprobe/devpaths.py",
    "src/gegenprobe/compliance/fetchguard.py",
    "src/gegenprobe/compliance/mirror.py",
    "data/schema/affair_types.json",
    "data/convert/rules_coverage.json",
    "data/p8/p8_gold.jsonl",
    "data/p8/p8_affairs.jsonl",
    "data/p8/opd_meta_p8.jsonl",
    "data/p8/body_names_p8.json",
    "data/fed/fed_affairs.jsonl",
    "data/gold3/p3_affairs.jsonl",
    "data/gold5/p3b_affairs.jsonl",
    "data/gold6/p5_affairs.jsonl",
    "data/gold6/p5dev_affairs.jsonl",
    "data/gold/dev_docs.jsonl",
    "data/gold/heldout_docs.jsonl",
    "data/gold/dev_ids.json",
    "data/gold2/p2_docs.jsonl",
    "data/gold4/p4_meetings.jsonl",
    "data/gold4/p4_heldout_meetings.jsonl",
    "data/gold4/p4_transfer_meetings.jsonl",
    "data/gold6/p5_fetch_log.jsonl",
    "data/gold6/p5dev_fetch_log.jsonl",
    "data/p6/dev2_docs.jsonl",
    "data/p6/p6_docs.jsonl",
]
GATEWAY = Path.home() / "Desktop" / "hackapertus" / "gateway" / "gw.py"
LOCK10 = ROOT / "eval" / "prereg10" / "LOCK10"
EARLIER = sorted((ROOT / "eval").glob("prereg*/LOCK*")) + [ROOT / "eval" / "fed" / "LOCKFED"]


def files() -> list[str]:
    return P10_FILES + ARMS + REUSED


def digest(p: Path | str) -> str:
    p = ROOT / p if isinstance(p, str) else p
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def work_inputs() -> dict[str, str]:
    from eval.p8 import common as C8

    out = {f"WORK/{k}": v for k, v in C8.work_inputs().items()}
    for n in ("affairs", "events", "contributors", "bodies"):
        out[f"OPD_RAW/{n}.ndjson.gz"] = digest(OPD_RAW / f"{n}.ndjson.gz")
    for p in sorted((WORK / "p10dev").glob("*.jsonl")):
        out[f"WORK/p10dev/{p.name}"] = digest(p)
    out["EXTERNAL/gateway/gw.py"] = digest(GATEWAY)
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
        if p.name == "LOCK10" or not p.exists():
            continue
        try:
            walk(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def write() -> None:
    from eval.p10 import common as C
    from eval.p10 import selftest

    for p in (C.AFFAIRS, C.KEY, C.GOLD, C.ANN, C.META10):
        if p.exists():
            raise SystemExit(f"{p} exists: a lock now would not pre-date the P10 draw")
    for p in (C.CONFIG, C.DEV_RESULTS, C.PROBE):
        if not p.exists():
            raise SystemExit(f"{p} missing: finish development (eval/p10/dev.py) and the probe first")
    if digest("src/gegenprobe/convert/roles.py") != FROZEN_ROLES_SHA256:
        raise SystemExit("src/gegenprobe/convert/roles.py is not the frozen roles-2")
    bad = selftest.checks()
    if bad:
        raise SystemExit(f"selftest fails: {bad}")
    fs = files()
    prev = earlier_frozen()
    drift = [f for f in fs if f in prev and digest(f) != prev[f]]
    if drift:
        raise SystemExit(f"files frozen by an earlier lock changed: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p10_files={f: digest(f) for f in fs},
             work_inputs=work_inputs(), also_frozen_by_earlier_locks=sorted(f for f in fs if f in prev),
             frozen_roles_sha256=FROZEN_ROLES_SHA256)
    LOCK10.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCK10: {len(d['p10_files'])} files, {len(d['work_inputs'])} WORK inputs "
          f"({len(d['also_frozen_by_earlier_locks'])} also frozen by earlier locks)")


def check() -> list[str]:
    d = json.loads(LOCK10.read_text())
    bad = [f for f, h in d["p10_files"].items() if not (ROOT / f).exists() or digest(f) != h]
    w = work_inputs()
    return bad + [k for k, h in d["work_inputs"].items() if w.get(k) != h]


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        write()
    else:
        ch = check()
        print("LOCK10 intact" if not ch else "changed since LOCK10: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
