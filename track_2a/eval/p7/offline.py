"""P7 post-hoc scripts from a clean checkout (round 10). eval/p7/posthoc8.py, posthoc_r8.py and cluster_r9.py read the
test key, arm decisions and annotations from WORK (never committed) and, for the no-model ablation, the extracted texts
and OPD targets. When WORK has no P7 test key, each script hands over to this module, which lays out a scratch WORK from
the committed copies in data/p7/ (as eval/p7/replay8.py does for the registered scripts) and replaces the two
text-dependent steps by committed outcomes:

  date_rule_outcomes.jsonl   the adapters' date rule on every (parliament, affair, gold date) (eval/p7/replay8.py)
  rule_any_outcomes.jsonl    the no-model ablation per row (posthoc_r8._rule_any): for the 478 test-frame rows and every
                             eligible review row of the whole queue, whether some printed date of the model's view / of
                             the full text passes the date rule, the first passing date, the number of printed dates and
                             the first printed date equal to an OPD answer event. Dates and counts only, no text.

    PYTHONPATH=src:. python -m eval.p7.offline check     run all three offline into a scratch tree; byte-compare each with
                                                         results/p7/ (exit 1 on any difference); no network, no model
    PYTHONPATH=src:. python -m eval.p7.offline export    DEV ONLY (needs the real WORK): write rule_any_outcomes.jsonl
    PYTHONPATH=src:. python -m eval.p7.cluster_r9        (and posthoc8, posthoc_r8) fall back to this module by themselves
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from gegenprobe.paths import DATA, RESULTS, ROOT, WORK

P7 = DATA / "p7"
RULE_ANY = P7 / "rule_any_outcomes.jsonl"
FIELDS = ("rule_any_view", "rule_any_full", "n_view", "n_pass_view", "first_pass_view", "n_pass_full", "trivial_date")
# module -> committed output under results/p7/
SCRIPTS = {"eval.p7.posthoc8": "p7_posthoc.json", "eval.p7.posthoc_r8": "p7_posthoc_r8.json",
           "eval.p7.cluster_r9": "p7_cluster_r9.json"}
EXTRA_LAYOUT = {"test_annotations/A1.jsonl": "p7test/ann/A1.jsonl", "test_annotations/A2.jsonl": "p7test/ann/A2.jsonl"}


def needed() -> bool:
    """True when WORK lacks the P7 test key (a clean checkout): the post-hoc scripts then run on committed copies."""
    return not (WORK / "p7test" / "key.jsonl").exists()


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ------------------------------------------------------------------------------------------------ export (dev only)
def export() -> dict:
    from eval.p7 import hypotheses8 as H
    from eval.p7 import posthoc_r8 as R
    from eval.p7 import test as T
    from gegenprobe.repair.adapters import adjudicate as J

    rows = []
    for d in map(json.loads, T.DECISIONS.read_text().splitlines()):
        a = R._rule_any(d["body"], d["affair_id"], H._tg(d["body"])[d["affair_id"]])
        rows.append(dict(scope="frame", body=d["body"], affair_id=d["affair_id"], **{k: a[k] for k in FIELDS}))
    for r in J.review_rows():
        if not r["eligible"]:
            continue
        x = H._tg(r["body"]).get(r["affair_id"])
        if x is None:
            continue
        a = R._rule_any(r["body"], r["affair_id"], x)
        rows.append(dict(scope="queue", body=r["body"], affair_id=r["affair_id"], **{k: a[k] for k in FIELDS}))
    RULE_ANY.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
    return dict(file=str(RULE_ANY.relative_to(ROOT)), rows=len(rows),
                frame=sum(r["scope"] == "frame" for r in rows), queue=sum(r["scope"] == "queue" for r in rows),
                sha256=hashlib.sha256(RULE_ANY.read_bytes()).hexdigest())


# ------------------------------------------------------------------------------------------------ offline run
def _patch() -> None:
    """Inside the subprocess (GP_WORK = scratch): committed outcomes replace the texts and OPD targets."""
    import collections

    from eval.p7 import hypotheses8 as H
    from eval.p7 import posthoc_r8 as R
    from gegenprobe.repair.adapters import adjudicate as J

    out = {(o["body"], o["affair_id"], o["date"]): (o["match"], o["passes"]) for o in _jsonl(P7 / "date_rule_outcomes.jsonl")}
    committed = _jsonl(RULE_ANY)
    ra = {(o["body"], o["affair_id"]): o for o in committed if o["scope"] == "frame"}
    queue = [o for o in committed if o["scope"] == "queue"]

    def excerpt_text(body, aid):  # no text in the checkout: a marker that names the document
        return f"{body}\t{aid}"

    def date_rule(body, text, d, x):
        if not d:
            return None, False
        b, aid = text.split("\t")
        key = (body, int(aid), d)
        if b != body or key not in out:
            raise KeyError(f"no committed date-rule outcome for {key}")
        return out[key]

    class _Targets(dict):  # the targets row only feeds the date rule, which the committed outcomes replace
        def __missing__(self, k):
            return {}

    def rule_any(body, aid, x):
        o = ra[(body, aid)]
        return {k: o[k] for k in FIELDS}

    def queue_rule_any():
        import csv
        prom = collections.Counter(r["body"] for r in csv.DictReader(open(J.OUT / "promoted.tsv", encoding="utf-8"),
                                                                      delimiter="\t"))
        by = collections.defaultdict(collections.Counter)
        for o in queue:
            b = o["body"]
            by[b]["eligible"] += 1
            by[b]["rule_any_view"] += o["rule_any_view"]
            by[b]["rule_any_full"] += o["rule_any_full"]
        tot = collections.Counter()
        for b, c in by.items():
            c["p7_promoted"] = prom.get(b, 0)
            tot.update(c)
        return dict(total=dict(tot), by_parliament={b: dict(c) for b, c in sorted(by.items())})

    J.excerpt_text, J.date_rule = excerpt_text, date_rule
    H._tg = lambda body: _Targets()
    R._rule_any, R.queue_rule_any = rule_any, queue_rule_any


def _inner(module: str, out_dir: Path) -> None:
    import importlib

    _patch()
    m = importlib.import_module(module)
    name = SCRIPTS[module]
    m.OUT = out_dir / name
    out_dir.mkdir(parents=True, exist_ok=True)
    m.main()


def run(module: str, out_dir: Path = RESULTS / "p7") -> int:
    """Run one post-hoc script on a scratch WORK laid out from data/p7/; its output goes to out_dir/<committed name>."""
    from eval.p7 import replay8

    tmp = Path(tempfile.mkdtemp(prefix="p7offline"))
    try:
        for src, dst in {**replay8.LAYOUT, **EXTRA_LAYOUT}.items():
            (tmp / "work" / dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(P7 / src, tmp / "work" / dst)
        env = dict(os.environ, GP_WORK=str(tmp / "work"),
                   PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "eval.p7.offline", "_inner", module, str(out_dir)], env=env, cwd=ROOT,
                           timeout=3600)
        return p.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check() -> list[dict]:
    out = Path(tempfile.mkdtemp(prefix="p7offline_out")) / "p7"
    tests = []
    try:
        for module, name in SCRIPTS.items():
            rc = run(module, out)
            got = out / name
            same = rc == 0 and got.exists() and got.read_bytes() == (RESULTS / "p7" / name).read_bytes()
            tests.append(dict(test=f"P7 post hoc {module} from data/p7 (byte-identical results/p7/{name})", ok=same,
                              detail=[] if same else [f"exit {rc}" if rc else f"results/p7/{name} differs"]))
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)
    return tests


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "_inner":
        _inner(sys.argv[2], Path(sys.argv[3]))
        return 0
    if cmd == "export":
        print(json.dumps(export(), indent=1))
        return 0
    tests = check()
    for t in tests:
        print(f"{'PASS' if t['ok'] else 'FAIL'}  {t['test']}" + ("" if t["ok"] else f"  {t['detail'][:3]}"))
    return 0 if all(t["ok"] for t in tests) else 1


if __name__ == "__main__":
    sys.exit(main())
