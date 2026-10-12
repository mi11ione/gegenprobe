"""P11 lock: sha256 of every file that decides a P11 result, written before any P11 affair is drawn.

    python -m eval.p11.lock_p11 write   -> eval/p11/LOCKP11 (committed; the commit time is the registration time)
    python -m eval.p11.lock_p11 check   -> exit 1 listing every hashed file or input changed since LOCKP11

Same style as eval/fed/lock_fed.py and eval/prereg10/lock10.py. `write` refuses if a P11 draw, affair, key, annotation or
gold file exists, if the pool probe is missing, if a hashed file is missing, if the self-test (eval/p11/selftest.py,
synthetic inputs only) fails, or if any file frozen by an earlier lock (eval/prereg*/LOCK*, eval/fed/LOCKFED) that P11
uses differs from its locked hash. Hashed: the protocol and the cell's own code and guides; the pool probe (from which
the IT quotas are computed); the converter as the whole-affair command runs it (gegenprobe.affair_cli and everything it
calls), the P1 date rules and pointer with θ, the P10 role reader with its frozen configuration and prompts, the fetch
path and its OPD-copy map; the reused P8, P10 and federal-cell tooling (packets, checks, derivation, scorers) and every
file LOCK9 and LOCK10 freeze; the schema vocabularies. Inputs that are never committed are recorded by hash under
`work_inputs`: OPD's snapshot exports and the census document metadata the frames, orders and metadata come from, P8's
WORK exclusion inputs, and the budget gateway client the model arms call through.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from gegenprobe import devpaths
from gegenprobe.paths import DOCS_META, OPD_RAW, ROOT

P11_FILES = [
    "eval/p11/PROTOCOL.md",
    "eval/p11/lock_p11.py",
    "eval/p11/__init__.py",
    "eval/p11/common.py",
    "eval/p11/draw.py",
    "eval/p11/packets.py",
    "eval/p11/annotate.py",
    "eval/p11/arms.py",
    "eval/p11/score.py",
    "eval/p11/selftest.py",
    "eval/p11/GUIDE_P11_IT.md",
    "eval/p11/GUIDE_P11_NI.md",
    "results/p11/pool_probe.json",
]
# the converter as `gegenprobe affair` runs it, and what the arms call besides
CONVERTER = [
    "src/gegenprobe/affair_cli.py",
    "src/gegenprobe/affair_post.py",
    "src/gegenprobe/affair/build.py",
    "src/gegenprobe/affair/extract.py",
    "src/gegenprobe/affair/meta.py",
    "src/gegenprobe/convert/affair_types.py",
    "src/gegenprobe/convert/batch.py",
    "src/gegenprobe/convert/body_settings.py",
    "src/gegenprobe/convert/build_guard.py",
    "src/gegenprobe/convert/cascade.py",
    "src/gegenprobe/convert/hints.py",
    "src/gegenprobe/convert/lattice.py",
    "src/gegenprobe/convert/modes.py",
    "src/gegenprobe/convert/output.py",
    "src/gegenprobe/convert/overlay.py",
    "src/gegenprobe/convert/parts.py",
    "src/gegenprobe/convert/pointer.py",
    "src/gegenprobe/convert/role_candidates.py",
    "src/gegenprobe/convert/roles.py",
    "src/gegenprobe/convert/roles_pointer.py",
    "src/gegenprobe/convert/rules.py",
    "src/gegenprobe/qa/__init__.py",
    "src/gegenprobe/qa/answers.py",
    "src/gegenprobe/qa/extract.py",
    "src/gegenprobe/qa/people.py",
    "src/gegenprobe/qa/pointer.py",
    "src/gegenprobe/qa/questions.py",
    "src/gegenprobe/qa/rec.py",
    "src/gegenprobe/qa/text.py",
    "src/gegenprobe/schema/body_languages.py",
    "src/gegenprobe/schema/p8_v0_2.py",
    "src/gegenprobe/schema/role_consistency.py",
    "src/gegenprobe/schema/schema_v0_1.py",
    "src/gegenprobe/schema/v0_2_all.py",
    "src/gegenprobe/schema/v0_2_qa.py",
    "src/gegenprobe/schema/v0_2_roles.py",
    "schema/gegenprobe_schema.py",
    "schema/gegenprobe_schema_v0_2.py",
    "src/gegenprobe/census/defs.py",
    "src/gegenprobe/census/scan.py",
    "src/gegenprobe/deadline.py",
    "src/gegenprobe/hardening.py",
    "src/gegenprobe/llm.py",
    "src/gegenprobe/net.py",
    "src/gegenprobe/pdftext.py",
    "src/gegenprobe/robots9309.py",
    "src/gegenprobe/compliance/fetchguard.py",
    "src/gegenprobe/compliance/mirror.py",
    "src/gegenprobe/repair/common.py",
    "src/gegenprobe/stats.py",
    "src/gegenprobe/paths.py",
    "src/gegenprobe/devpaths.py",
    "data/census/bodies.tsv.gz",
    "data/compliance/mirror_urls.json",
    "data/convert/rules_coverage.json",
    "data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json",
    "results/eval/served_models.json",
    "data/schema/null_reasons.json",
    "data/schema/affair_types.json",
    "data/schema/field_verdict_classes.json",
    "data/p10/p10_config.json",
    "data/p10/p10_affairs.jsonl",
    "data/fed/fed_affairs.jsonl",
] + [f"src/prompts/{lg}/{p}.txt" for lg in ("de", "fr", "it") for p in (
    "answer_date", "recommendation", "affair_submitter", "affair_submitted", "affair_addressed_body", "affair_affair_type")]
# reused evaluation code: the P1 scorer and backend, the federal cell's label checks, P10's scorer, arms and post hoc
# document-order baseline (P8's tooling comes with lock9.files(), P10's with lock10.files())
REUSED = [
    "eval/arms.py",
    "eval/score.py",
    "eval/gold/annotate.py",
    "eval/gold/sample.py",
    "eval/gold2/GUIDE.md",
    "eval/gold3/sample.py",
    "eval/p6/common.py",
    "eval/fed/annotate.py",
    "eval/fed/common.py",
    "eval/p10/arms.py",
    "eval/p10/posthoc_baselines.py",
]
LOCK = ROOT / "eval" / "p11" / "LOCKP11"
EARLIER = sorted((ROOT / "eval").glob("prereg*/LOCK*")) + [ROOT / "eval" / "fed" / "LOCKFED"]
GATEWAY = devpaths.gateway_dir() / "gw.py"


def files() -> list[str]:
    from eval.prereg9 import lock9
    from eval.prereg10 import lock10

    return list(dict.fromkeys(P11_FILES + CONVERTER + REUSED + lock9.files() + lock10.files()))


def digest(rel: str | Path) -> str:
    p = ROOT / rel if isinstance(rel, str) else rel
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def work_inputs() -> dict[str, str]:
    from eval.p8 import common as C8

    out = {f"WORK/{k}": v for k, v in C8.work_inputs().items()}
    for n in ("affairs.ndjson.gz", "events.ndjson.gz", "contributors.ndjson.gz", "bodies.ndjson.gz", "index.json"):
        out[f"OPD_RAW/{n}"] = digest(OPD_RAW / n)
    for p in sorted(DOCS_META.glob("part*/docs_meta.jsonl.gz")):
        out[f"DOCS_META/{p.relative_to(DOCS_META)}"] = digest(p)
    out["EXTERNAL/gateway/gw.py"] = digest(GATEWAY) if GATEWAY.exists() else "missing"
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
        if not p.exists():
            continue
        try:
            walk(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def write() -> None:
    from eval.p11 import common as C
    from eval.p11 import selftest

    for p in (C.DRAW, C.AFFAIRS, C.META, C.ANN, *C.KEY.values(), *C.GOLD.values()):
        if p.exists():
            raise SystemExit(f"{p} exists: a lock now would not pre-date the P11 draw")
    if not C.PROBE.exists():
        raise SystemExit(f"{C.PROBE} missing: run `python -m eval.p11.common probe` first")
    fs = files()
    missing = [f for f in fs if not (ROOT / f).exists()]
    if missing:
        raise SystemExit(f"hashed files missing: {missing}")
    bad = selftest.checks()
    if bad:
        raise SystemExit(f"the self-test fails: {bad}")
    prev = earlier_frozen()
    drift = [f for f in fs if f in prev and digest(f) != prev[f]]
    if drift:
        raise SystemExit(f"files frozen by an earlier lock changed: {drift}")
    d = dict(written=time.strftime("%Y-%m-%dT%H:%M:%S%z"), p11_files={f: digest(f) for f in fs},
             work_inputs=work_inputs(), also_frozen_by_earlier_locks=sorted(f for f in fs if f in prev),
             it_quotas=[list(q) for q in C.it_quotas()], ni_quotas=[list(q) for q in C.NI_QUOTAS])
    LOCK.write_text(json.dumps(d, indent=1) + "\n")
    print(f"LOCKP11: {len(d['p11_files'])} files, {len(d['work_inputs'])} WORK/external inputs "
          f"({len(d['also_frozen_by_earlier_locks'])} also frozen by earlier locks); IT quotas {d['it_quotas']}")


def check() -> list[str]:
    d = json.loads(LOCK.read_text())
    bad = [f for f, h in d["p11_files"].items() if not (ROOT / f).exists() or digest(f) != h]
    w = work_inputs()
    return bad + [k for k, h in d["work_inputs"].items() if w.get(k) != h]


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        write()
    else:
        if not LOCK.exists():
            print("LOCKP11 not written")
            sys.exit(1)
        ch = check()
        print("LOCKP11 intact" if not ch else "changed since LOCKP11: " + ", ".join(ch))
        sys.exit(1 if ch else 0)
