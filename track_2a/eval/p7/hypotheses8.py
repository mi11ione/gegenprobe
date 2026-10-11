"""P7 registered analysis (eval/prereg8/PREREG8.md): joins the blind test gold with the arm outputs drawn before it.

    PYTHONPATH=src:. python -m eval.p7.hypotheses8     -> results/p7/p7_hypotheses.json

Inputs: WORK/p7test/key.jsonl and decisions.jsonl (hashes checked against results/p7/test_sample.json), the merged gold
WORK/p7test/ann/gold.jsonl ({id, is_answer, dates}), optional Qwen check WORK/p7test/ann/qwen.jsonl, and the queue run
results/repair/adapters/p7/queue_summary.json (for H2's projection).

Definitions (PREREG8):
  correct        gold is_answer == yes (unclear and no are errors)
  correct_dated  correct and some gold answer date (decision or letter) passes the adapters' date rule for the row
  weights        a packet of sampling stratum s weighs N_s / n_s (p7 rows weigh 1 when the p7 stratum is a census)
  intervals      Wilson 95% on the p7 stratum (H1); every weighted figure: stratified bootstrap (resampling packets with
                 replacement within each sampling stratum), B = 10,000, seed 20261014, percentile 95% interval
"""

from __future__ import annotations

import collections
import functools
import hashlib
import json
import math
import random

from eval.p7 import common as C
from eval.p7 import test as T
from eval.p7.tune import load_ann
from gegenprobe.paths import RESULTS
from gegenprobe.repair.adapters import adjudicate as J
from gegenprobe.repair.adapters import targets
from gegenprobe.stats import wilson

H1_LB = 0.90
H1_MIN_N = 40
H3_UB = 0.90
B = 10000
SEED = 20261014
COUNTED_BEFORE = 6613  # results/repair/adapters/adapters_summary.json totals.counted at the lock


@functools.lru_cache(maxsize=None)
def _tg(body: str) -> dict:
    return {x["id"]: x for x in targets.load(body)}


def load() -> tuple[list[dict], dict]:
    smp = json.loads((T.OUT / "test_sample.json").read_text())
    key_blob = (T.WORKDIR / "key.jsonl").read_bytes()
    dec_blob = T.DECISIONS.read_bytes()
    assert hashlib.sha256(key_blob).hexdigest() == smp["key_sha256"], "key changed after the draw"
    assert hashlib.sha256(dec_blob).hexdigest() == smp["decisions_sha256"], "arm outputs changed after the draw"
    dec = {(d["body"], d["affair_id"]): d for d in map(json.loads, dec_blob.decode().splitlines())}
    gold = load_ann(T.WORKDIR)
    rows = []
    for pid, k in sorted(C.load_key(T.WORKDIR).items()):
        d = dec[(k["body"], k["affair_id"])]
        g = gold.get(pid)
        if g is None:
            raise SystemExit(f"no gold label for {pid}")
        x = _tg(k["body"])[k["affair_id"]]
        text = J.excerpt_text(k["body"], k["affair_id"])
        dated = g["is_answer"] == "yes" and any(J.date_rule(k["body"], text, dd, x)[1] for dd in g["dates"])
        rows.append(dict(id=pid, stratum=k["stratum"], w=smp["weights"][k["stratum"]], gold=g["is_answer"],
                         gold_dates=g["dates"], correct=g["is_answer"] == "yes", correct_dated=dated, **d))
    return rows, smp


def _ratio(rows, arm, field):
    num = sum(r["w"] for r in rows if r[arm] and r[field])
    den = sum(r["w"] for r in rows if r[arm])
    return num / den if den else float("nan")


def _recall(rows, arm, field):
    num = sum(r["w"] for r in rows if r[arm] and r[field])
    den = sum(r["w"] for r in rows if r[field])
    return num / den if den else float("nan")


def _total(rows, arm, field):
    return sum(r["w"] for r in rows if r[arm] and r[field])


def boot(rows: list[dict], stat) -> list[float]:
    by = collections.defaultdict(list)
    for r in rows:
        by[r["stratum"]].append(r)
    rng = random.Random(SEED)
    vals = []
    for _ in range(B):
        res = [rng.choice(v) for v in by.values() for _ in v]
        x = stat(res)
        if not math.isnan(x):
            vals.append(x)
    vals.sort()
    if not vals:
        return [None, None]
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]


def est(rows, stat) -> dict:
    v = stat(rows)
    return dict(estimate=None if math.isnan(v) else round(v, 4), ci95=boot(rows, stat))


def kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    labs = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in labs)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def main() -> dict:
    rows, smp = load()
    p7 = [r for r in rows if r["stratum"] == "p7"]
    k, n = sum(r["correct"] for r in p7), len(p7)
    lb, ub = wilson(k, n) if n else (0.0, 1.0)
    h1 = dict(n=n, correct=k, precision=round(k / n, 4) if n else None, wilson95=[round(lb, 4), round(ub, 4)],
              gold=dict(collections.Counter(r["gold"] for r in p7)), threshold_lb=H1_LB, min_n=H1_MIN_N,
              census=smp["strata_N"].get("p7", 0) == n,
              holds=n >= H1_MIN_N and lb >= H1_LB,
              precision_dated=round(sum(r["correct_dated"] for r in p7) / n, 4) if n else None,
              date_hit=sum(1 for r in p7 if r["p7_date"] in r["gold_dates"]),
              errors=[dict(id=r["id"], gold=r["gold"], reason=r["reason"]) for r in p7 if not r["correct"]])
    arms = {}
    for arm in ("p7", "free", "trivial"):
        arms[arm] = dict(
            promoted_in_frame=smp["arms_on_frame"][arm],
            precision=est(rows, lambda rs, a=arm: _ratio(rs, a, "correct")),
            precision_dated=est(rows, lambda rs, a=arm: _ratio(rs, a, "correct_dated")),
            recall_all=est(rows, lambda rs, a=arm: _recall(rs, a, "correct")),
            recall_attainable=est(rows, lambda rs, a=arm: _recall(rs, a, "correct_dated")),
            correct_rows_in_frame=est(rows, lambda rs, a=arm: _total(rs, a, "correct")),
            correct_dated_rows_in_frame=est(rows, lambda rs, a=arm: _total(rs, a, "correct_dated")))
    arms["rules_only"] = dict(promoted_in_frame=0, precision=None, recall_all=0.0, recall_attainable=0.0)
    fo = [r for r in rows if r["stratum"] == "free_only"]
    kf, nf = sum(r["correct"] for r in fo), len(fo)
    lbf, ubf = wilson(kf, nf) if nf else (0.0, 1.0)
    h3 = dict(n=nf, correct=kf, precision=round(kf / nf, 4) if nf else None, wilson95=[round(lbf, 4), round(ubf, 4)],
              threshold_ub=H3_UB, supported=bool(nf) and ubf < H3_UB,
              statement="the rows free generation + printed-date filter promotes beyond p7 are below 0.90 precision")
    diff = est(rows, lambda rs: _ratio(rs, "p7", "correct_dated") - _ratio(rs, "trivial", "correct_dated"))
    h4 = dict(difference_precision_dated_p7_minus_trivial=diff,
              supported=diff["ci95"][0] is not None and diff["ci95"][0] > 0)
    q = J.OUT / "queue_summary.json"
    h2 = None
    if q.exists():
        qs = json.loads(q.read_text())
        m = qs["promoted"]
        h2 = dict(queue_eligible=qs["eligible"], queue_promoted=m,
                  recovered_estimate=round(m * k / n, 1) if n else None,
                  recovered_ci95=[round(m * lb, 1), round(m * ub, 1)] if n else None,
                  method="queue promotions x test precision (Wilson 95% of the p7 stratum)")
        kd = sum(r["correct_dated"] for r in p7)
        if n:
            lbd, ubd = wilson(kd, n)
            h2.update(recovered_dated_estimate=round(m * kd / n, 1), recovered_dated_ci95=[round(m * lbd, 1),
                                                                                          round(m * ubd, 1)])
    by_reason = collections.defaultdict(collections.Counter)
    for r in p7:
        by_reason[r["reason"]]["correct" if r["correct"] else "error"] += 1
    qwen = None
    qp = T.WORKDIR / "ann" / "qwen.jsonl"
    if qp.exists():
        qv = {v["id"]: v for v in map(json.loads, qp.read_text().splitlines()) if v}
        both = [r for r in rows if r["id"] in qv]
        qwen = dict(n=len(both), agree=sum(qv[r["id"]]["is_answer"] == r["gold"] for r in both),
                    kappa=kappa([r["gold"] for r in both], [qv[r["id"]]["is_answer"] for r in both]),
                    p7_rows_qwen_not_yes=[r["id"] for r in p7 if r["id"] in qv and qv[r["id"]]["is_answer"] != "yes"],
                    note="independent check; changes no gold label and no decision")
    headline = None
    if h1["holds"] and h2:
        headline = dict(counted=COUNTED_BEFORE, promoted_by_apertus=h2["queue_promoted"],
                        note="the promoted tier is reported separately next to the counted total, never merged")
    res = dict(H1=h1, H2=h2, H3=h3, H4=h4, arms=arms, p7_by_reason={k2: dict(v) for k2, v in by_reason.items()},
               labels=dict(collections.Counter(r["gold"] for r in rows)), packets=len(rows),
               strata_N=smp["strata_N"], strata_n=smp["strata_n"], qwen_check=qwen, headline=headline)
    (RESULTS / "p7" / "p7_hypotheses.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
