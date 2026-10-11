"""P7 post hoc, round 8 (11 Oct 2026; NOT registered, written after the P7 test gold was read; no model call, no registered
decision changes). Asked for by the round-8 jury (J2, J5): how much of P7's result is Apertus, how much is the adapters'
date rule, the queue's base rate and one dominant parliament.

    PYTHONPATH=src:. python -m eval.p7.posthoc_r8     -> results/p7/p7_posthoc_r8.json
    (without WORK/p7test, e.g. a clean checkout, it runs on the committed copies in data/p7/: eval/p7/offline.py)

Inputs as eval.p7.hypotheses8 (WORK/p7test key, arm decisions and merged gold, hash-checked), the Qwen check
(WORK/p7test/ann/qwen.jsonl), the raw A1/A2 files, the extracted texts and OPD targets (for the no-model ablation), and
results/repair/adapters/p7/promoted.tsv (the whole-queue promotions).

  per_parliament     annotated rows per parliament: p7 promotions judged and correct (precision), gold yes and
                     yes-with-a-passing-date, the arms' weighted recall within the parliament; frame counts per arm
  without_frauenfeld every headline P7 figure with parliament 4566 (Frauenfeld) left out (domain estimate, same weights)
  cluster            parliaments resampled with replacement (B = 10,000, seed 20261014, percentile 95%), each keeping its
                     annotated rows and their stratum weights: H1 precision and H4; plus a parliament-as-unit Wilson bound
  h4_unweighted      the registered weighted H4 next to the plain counts over the annotated rows, and why they differ
  trivial            the no-model date match (some printed date equals an OPD answer event) on is_answer and on gold no
  ablation           no model at all: the adapters' date rule (adjudicate.date_rule, the same rule p7 applies to its chosen
                     date) applied to EVERY printed date of the model's view (the closed set p7 chooses from), and of the
                     full text; a row is promoted when any printed date passes. Also: p7's is_answer gate (m_yes > theta_A,
                     cached margins) + any-date rule, which isolates what the date choice adds over the gate.
  date hit           per arm with a date: the share of its promotions whose written date is one of the gold answer dates
                     (stricter than the registered correct_dated, which asks only that SOME gold date passes the rule)
  qwen               Cohen's kappa (and prevalence-adjusted PABAK) of the Qwen check with the gold, and of A1 with A2
  base_rate          precision of every arm against the frame's base rate (promote every eligible review row)
"""

from __future__ import annotations

import collections
import csv
import json
import math
import random

from eval.p7 import hypotheses8 as H
from eval.p7 import test as T
from gegenprobe.paths import RESULTS
from gegenprobe.repair.adapters import adjudicate as J
from gegenprobe.repair.common import parse_dates
from gegenprobe.stats import wilson

OUT = RESULTS / "p7" / "p7_posthoc_r8.json"
FRAUENFELD = "4566"
B = H.B
SEED = H.SEED
LABEL = ("POST HOC (11 Oct 2026, round 8; not pre-registered): written after the P7 test gold was read; no model call; "
         "no registered decision depends on this file")
ARMS = ("p7", "free", "trivial", "rule_any_view", "rule_any_full", "gate_rule_any", "gate_only", "all_rows")
ARM_NAMES = dict(
    p7="the frozen P7 configuration (Apertus is_answer gate + Apertus date choice + the adapters' date rule)",
    free="free generation (yes + a printed date passing the same date rule)",
    trivial="no model: some printed date equals an OPD answer event",
    rule_any_view="no model: some printed date of the model's view (p7's closed set, at most 25) passes the date rule",
    rule_any_full="no model: some printed date of the full text passes the date rule",
    gate_rule_any="Apertus is_answer gate (m_yes > theta_A, cached) + some printed date of the view passes the date rule "
                  "(no date choice)",
    gate_only="Apertus is_answer gate alone (m_yes > theta_A, cached), no date check",
    all_rows="promote every eligible review row (the base rate)")


def _r(x, nd=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, nd)


def _w(k, n):
    return [_r(v) for v in wilson(k, n)] if n else [None, None]


# ------------------------------------------------------------------------------------------------------------ ablation
def _rule_any(body: str, aid: int, x: dict) -> dict:
    text = J.excerpt_text(body, aid)
    view, _ = J.model_view(text)
    values, _, _ = J.options(view)
    passing = [d for d in values if J.date_rule(body, text, d, x)[1]]
    full = list(dict.fromkeys(d for d, _, _ in parse_dates(text)))
    passing_full = [d for d in full if J.date_rule(body, text, d, x)[1]]
    ev = set(x.get("answer_dates") or [])
    return dict(rule_any_view=bool(passing), rule_any_full=bool(passing_full), n_view=len(values),
                n_pass_view=len(passing), first_pass_view=passing[0] if passing else None, n_pass_full=len(passing_full),
                trivial_date=next((d for d in full if d in ev), None))


def frame_rows(theta_a: float) -> list[dict]:
    """Every row of the test frame T (the 478 rows the arms ran on) with the arm outputs and the no-model ablation."""
    dec = [json.loads(x) for x in T.DECISIONS.read_text().splitlines() if x.strip()]
    out = []
    for d in dec:
        x = H._tg(d["body"])[d["affair_id"]]
        a = _rule_any(d["body"], d["affair_id"], x)
        out.append(dict(d, **a, gate_only=d["m_yes"] > theta_a, gate_rule_any=d["m_yes"] > theta_a and a["rule_any_view"],
                        all_rows=True))
    return out


def queue_rule_any() -> dict:
    """The no-model any-date rule over the whole eligible review queue (863 rows), next to the 214 p7 promotions."""
    prom = collections.Counter(r["body"] for r in csv.DictReader(open(J.OUT / "promoted.tsv", encoding="utf-8"),
                                                                  delimiter="\t"))
    by = collections.defaultdict(collections.Counter)
    for r in J.review_rows():
        if not r["eligible"]:
            continue
        x = H._tg(r["body"]).get(r["affair_id"])
        if x is None:
            continue
        a = _rule_any(r["body"], r["affair_id"], x)
        by[r["body"]]["eligible"] += 1
        by[r["body"]]["rule_any_view"] += a["rule_any_view"]
        by[r["body"]]["rule_any_full"] += a["rule_any_full"]
    tot = collections.Counter()
    for b, c in by.items():
        c["p7_promoted"] = prom.get(b, 0)
        tot.update(c)
    return dict(total=dict(tot), by_parliament={b: dict(c) for b, c in sorted(by.items())})


# ------------------------------------------------------------------------------------------------------------ estimators
def _ratio(rows, arm, field):
    num = sum(r["w"] for r in rows if r[arm] and r[field])
    den = sum(r["w"] for r in rows if r[arm])
    return num / den if den else float("nan")


def _recall(rows, arm, field):
    num = sum(r["w"] for r in rows if r[arm] and r[field])
    den = sum(r["w"] for r in rows if r[field])
    return num / den if den else float("nan")


def boot_vals(rows, stat, seed=SEED) -> list[float]:
    """The registered stratified bootstrap (eval.p7.hypotheses8.boot), returning every replicate."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["stratum"]].append(r)
    rng = random.Random(seed)
    vals = []
    for _ in range(B):
        res = [rng.choice(v) for v in by.values() for _ in v]
        x = stat(res)
        if not math.isnan(x):
            vals.append(x)
    return sorted(vals)


def _pct(vals):
    if not vals:
        return [None, None]
    return [_r(vals[int(0.025 * len(vals))]), _r(vals[int(0.975 * len(vals)) - 1])]


def est(rows, stat) -> dict:
    v = stat(rows)
    return dict(estimate=_r(v), ci95=_pct(boot_vals(rows, stat)))


def cluster_vals(rows, stat, key="body", seed=SEED) -> tuple[list[float], int]:
    cl = collections.defaultdict(list)
    for r in rows:
        cl[r[key]].append(r)
    names = sorted(cl)
    rng = random.Random(seed)
    vals, undefined = [], 0
    for _ in range(B):
        res = [r for _ in names for r in cl[rng.choice(names)]]
        x = stat(res)
        if math.isnan(x):
            undefined += 1
        else:
            vals.append(x)
    return sorted(vals), undefined


def arm_block(rows) -> dict:
    out = {}
    for arm in ARMS:
        a = [r for r in rows if r[arm]]
        out[arm] = dict(
            annotated=dict(n=len(a), correct=sum(r["correct"] for r in a), correct_dated=sum(r["correct_dated"] for r in a),
                           gold_no=sum(r["gold"] == "no" for r in a)),
            precision=est(rows, lambda rs, x=arm: _ratio(rs, x, "correct")),
            precision_dated=est(rows, lambda rs, x=arm: _ratio(rs, x, "correct_dated")),
            recall_all=_r(_recall(rows, arm, "correct")), recall_attainable=_r(_recall(rows, arm, "correct_dated")))
        if f"hit_{arm}" in rows[0]:
            out[arm]["annotated"]["date_hit"] = sum(r[f"hit_{arm}"] for r in a)
            out[arm]["precision_date_hit"] = est(rows, lambda rs, x=arm: _ratio(rs, x, f"hit_{x}"))
    return out


def kappa_block(a: list[str], b: list[str]) -> dict:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    labs = sorted(set(a) | set(b))
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in labs)
    k = len(labs)
    return dict(n=n, agree=sum(x == y for x, y in zip(a, b)), kappa=_r((po - pe) / (1 - pe), 3) if pe < 1 else None,
                pabak=_r((k * po - 1) / (k - 1), 3) if k > 1 else None, expected_agreement=_r(pe, 3),
                confusion={f"{x}|{y}": c for (x, y), c in sorted(collections.Counter(zip(a, b)).items())})


def _ann_file(name: str) -> dict[str, str]:
    p = T.WORKDIR / "ann" / name
    return {r["id"]: r["is_answer"] for r in map(json.loads, p.read_text().splitlines()) if r}


# ------------------------------------------------------------------------------------------------------------ main
def main() -> dict:
    rows, smp = H.load()
    cfg = J.load_config()
    fr = frame_rows(cfg.theta_a)
    frk = {(r["body"], r["affair_id"]): r for r in fr}
    key = {r["id"]: r for r in map(json.loads, (T.WORKDIR / "key.jsonl").read_text().splitlines())}
    for r in rows:
        k = key[r["id"]]
        f = frk[(k["body"], k["affair_id"])]
        for a in ("rule_any_view", "rule_any_full", "gate_rule_any", "gate_only", "all_rows", "first_pass_view",
                  "n_pass_view", "n_view", "trivial_date"):
            r[a] = f[a]
        # date hit: the date the arm would write is one of the gold answer dates (p7: its chosen date; free: its date;
        # trivial: the first printed date equal to an OPD answer event; any-date rules: the first passing printed date)
        for arm, d in (("p7", r["p7_date"]), ("free", r["free_date"]), ("trivial", r["trivial_date"]),
                       ("rule_any_view", r["first_pass_view"]), ("gate_rule_any", r["first_pass_view"])):
            r[f"hit_{arm}"] = bool(r["correct"] and d and d in r["gold_dates"])
    p7 = [r for r in rows if r["stratum"] == "p7"]
    in_frame = {a: sum(bool(f[a]) for f in fr) for a in ARMS}

    # (a) per parliament + without Frauenfeld
    bodies = sorted({r["body"] for r in rows})
    per = {}
    for b in bodies:
        rs = [r for r in rows if r["body"] == b]
        pp = [r for r in rs if r["stratum"] == "p7"]
        per[b] = dict(
            annotated=len(rs), by_stratum=dict(collections.Counter(r["stratum"] for r in rs)),
            gold_yes=sum(r["correct"] for r in rs), gold_yes_dated=sum(r["correct_dated"] for r in rs),
            gold_no=sum(r["gold"] == "no" for r in rs),
            p7_promoted_judged=len(pp), p7_correct=sum(r["correct"] for r in pp),
            p7_correct_dated=sum(r["correct_dated"] for r in pp),
            p7_precision_wilson95=_w(sum(r["correct"] for r in pp), len(pp)),
            weighted_recall=dict(p7=_r(_recall(rs, "p7", "correct")), trivial=_r(_recall(rs, "trivial", "correct")),
                                 rule_any_view=_r(_recall(rs, "rule_any_view", "correct"))),
            weighted_recall_attainable=dict(p7=_r(_recall(rs, "p7", "correct_dated")),
                                            trivial=_r(_recall(rs, "trivial", "correct_dated"))),
            frame=dict(rows=sum(f["body"] == b for f in fr),
                       **{a: sum(bool(f[a]) for f in fr if f["body"] == b) for a in ("p7", "free", "trivial",
                                                                                         "rule_any_view")}))
    queue = queue_rule_any()
    nf = [r for r in rows if r["body"] != FRAUENFELD]
    nfp7 = [r for r in nf if r["stratum"] == "p7"]
    k, n = sum(r["correct"] for r in nfp7), len(nfp7)
    h4_stat = lambda rs: _ratio(rs, "p7", "correct_dated") - _ratio(rs, "trivial", "correct_dated")  # noqa: E731
    without_f = dict(
        parliament=FRAUENFELD, name="Frauenfeld",
        queue_promotions=dict(all=queue["total"]["p7_promoted"], frauenfeld=queue["by_parliament"][FRAUENFELD]["p7_promoted"],
                              without=queue["total"]["p7_promoted"] - queue["by_parliament"][FRAUENFELD]["p7_promoted"]),
        frame_rows=dict(all=len(fr), frauenfeld=sum(f["body"] == FRAUENFELD for f in fr)),
        frame_p7_promotions=dict(all=in_frame["p7"], frauenfeld=sum(f["p7"] for f in fr if f["body"] == FRAUENFELD)),
        annotated=dict(all=len(rows), frauenfeld=len(rows) - len(nf), without=len(nf)),
        h1=dict(n=n, correct=k, precision=_r(k / n) if n else None, wilson95=_w(k, n),
                registered_rule_met=n >= H.H1_MIN_N and wilson(k, n)[0] >= H.H1_LB,
                frauenfeld_only=dict(n=len(p7) - n, correct=sum(r["correct"] for r in p7) - k)),
        p7_precision_dated=dict(k=sum(r["correct_dated"] for r in nfp7), n=n),
        h4=est(nf, h4_stat), arms=arm_block(nf),
        base_rate_yes=_r(sum(r["w"] for r in nf if r["correct"]) / sum(r["w"] for r in nf)))

    # cluster bootstrap over parliaments
    h1_stat = lambda rs: (sum(r["correct"] for r in rs if r["stratum"] == "p7")  # noqa: E731
                          / max(1, sum(r["stratum"] == "p7" for r in rs))) if any(r["stratum"] == "p7" for r in rs) \
        else float("nan")
    cv1, u1 = cluster_vals(rows, h1_stat)
    cv4, u4 = cluster_vals(rows, h4_stat)
    cvd, ud = cluster_vals(rows, lambda rs: _ratio(rs, "p7", "correct_dated"))
    p7_bodies = sorted({r["body"] for r in p7})
    cluster = dict(
        method="parliaments (bodies) of the 190 annotated rows resampled with replacement, each with all its annotated rows "
               "and their sampling-stratum weights; B = 10,000, seed 20261014, percentile 95%; resamples without a p7 row "
               "(H1) or without an arm's promotion (ratios) are undefined and dropped",
        n_parliaments=len(bodies), n_parliaments_with_p7_rows=len(p7_bodies),
        h1_precision=dict(estimate=_r(h1_stat(rows)), ci95=_pct(cv1), undefined_resamples=u1,
                          note="every judged p7 promotion is correct, so every resample is 1.0: the cluster bootstrap "
                               "cannot widen a 100% rate; see parliament_as_unit"),
        h1_parliament_as_unit=dict(k=sum(all(r["correct"] for r in p7 if r["body"] == b) for b in p7_bodies),
                                   n=len(p7_bodies), wilson95=_w(len(p7_bodies), len(p7_bodies)),
                                   note="the most conservative reading: each parliament with a judged p7 promotion counts "
                                        "as ONE observation (all its promotions correct or not)"),
        h4=dict(estimate=_r(h4_stat(rows)), ci95=_pct(cv4), undefined_resamples=u4,
                excludes_0=bool(cv4) and _pct(cv4)[0] > 0),
        p7_precision_dated=dict(estimate=_r(_ratio(rows, "p7", "correct_dated")), ci95=_pct(cvd), undefined_resamples=ud),
    )

    # (b) unweighted H4
    def cnt(arm, sel=lambda r: True):
        a = [r for r in rows if r[arm] and sel(r)]
        return [sum(r["correct_dated"] for r in a), len(a)]
    p7c, trc = cnt("p7"), cnt("trivial")
    uw = lambda rs: (sum(r["correct_dated"] for r in rs if r["p7"]) / max(1, sum(r["p7"] for r in rs))  # noqa: E731
                     - sum(r["correct_dated"] for r in rs if r["trivial"]) / max(1, sum(r["trivial"] for r in rs)))
    rng = random.Random(SEED)
    uvals = sorted(uw([rng.choice(rows) for _ in rows]) for _ in range(B))
    h4u = dict(
        registered_weighted=dict(estimate=_r(h4_stat(rows)), ci95=H.est(rows, h4_stat)["ci95"],
                                 p7=_r(_ratio(rows, "p7", "correct_dated")),
                                 trivial=_r(_ratio(rows, "trivial", "correct_dated"))),
        unweighted=dict(p7=p7c, trivial=trc, p7_rate=_r(p7c[0] / p7c[1]), trivial_rate=_r(trc[0] / trc[1]),
                        difference=_r(p7c[0] / p7c[1] - trc[0] / trc[1]), row_bootstrap95=_pct(uvals),
                        note="plain counts over the 190 annotated rows, every row weight 1; describes the sample, not the "
                             "frame: p7-stratum rows are sampled at 120/135, rest rows at 40/305"),
        trivial_by_stratum={s: dict(zip(("correct_dated", "promoted"), cnt("trivial", lambda r, s=s: r["stratum"] == s)),
                                    weight=_r(smp["weights"][s], 3)) for s in ("p7", "free_only", "rest")},
        why="the trivial match promotes rest-stratum rows (weight 7.625) whose own gold date fails the date rule; the "
            "weighted figure counts each such row 7.6 times, as the registered frame estimator requires",
        weight_sensitivity={s: dict(p7=cnt("p7", lambda r, s=s: r["stratum"] != s),
                                    trivial=cnt("trivial", lambda r, s=s: r["stratum"] != s),
                                    weighted_difference_without=_r(h4_stat([r for r in rows if r["stratum"] != s])))
                            for s in ("rest", "free_only")},
    )

    # (c) trivial
    gold_no = [r for r in rows if r["gold"] == "no"]
    trivial = dict(
        annotated_is_answer=[sum(r["correct"] for r in rows if r["trivial"]), sum(r["trivial"] for r in rows)],
        annotated_is_answer_wilson95=_w(sum(r["correct"] for r in rows if r["trivial"]), sum(r["trivial"] for r in rows)),
        p7_annotated_is_answer=[sum(r["correct"] for r in p7), len(p7)],
        gold_no=len(gold_no), gold_no_stopped=dict(
            p7=sum(not r["p7"] for r in gold_no), trivial=sum(not r["trivial"] for r in gold_no),
            free=sum(not r["free"] for r in gold_no), rule_any_view=sum(not r["rule_any_view"] for r in gold_no),
            gate_only=sum(not r["gate_only"] for r in gold_no)),
        promoted_in_frame=dict(p7=in_frame["p7"], trivial=in_frame["trivial"]),
        overlap_annotated=dict(both=sum(r["p7"] and r["trivial"] for r in rows),
                               p7_only=sum(r["p7"] and not r["trivial"] for r in rows),
                               trivial_only=sum(r["trivial"] and not r["p7"] for r in rows)),
        overlap_frame=dict(both=sum(f["p7"] and f["trivial"] for f in fr),
                           p7_only=sum(f["p7"] and not f["trivial"] for f in fr),
                           trivial_only=sum(f["trivial"] and not f["p7"] for f in fr)),
        p7_date_hit=[sum(1 for r in p7 if r["p7_date"] in r["gold_dates"]), len(p7)],
    )

    # (d) no-model ablation
    rv = [r for r in rows if r["rule_any_view"]]
    abl = dict(
        what=ARM_NAMES, promoted_in_frame=in_frame, frame=len(fr), arms=arm_block(rows), queue=queue,
        first_passing_date_hits_gold=[sum(1 for r in rv if r["first_pass_view"] in r["gold_dates"]), len(rv)],
        rows_with_one_passing_date=sum(r["n_pass_view"] == 1 for r in rv),
        rows_with_several_passing_dates=sum(r["n_pass_view"] > 1 for r in rv),
        differences=dict(
            p7_minus_rule_any_view_precision_dated=est(
                rows, lambda rs: _ratio(rs, "p7", "correct_dated") - _ratio(rs, "rule_any_view", "correct_dated")),
            p7_minus_rule_any_view_precision=est(
                rows, lambda rs: _ratio(rs, "p7", "correct") - _ratio(rs, "rule_any_view", "correct")),
            p7_minus_gate_rule_any_precision_dated=est(
                rows, lambda rs: _ratio(rs, "p7", "correct_dated") - _ratio(rs, "gate_rule_any", "correct_dated")),
            p7_minus_rule_any_view_date_hit=est(
                rows, lambda rs: _ratio(rs, "p7", "hit_p7") - _ratio(rs, "rule_any_view", "hit_rule_any_view")),
            p7_minus_trivial_date_hit=est(
                rows, lambda rs: _ratio(rs, "p7", "hit_p7") - _ratio(rs, "trivial", "hit_trivial")),
            gate_rule_any_minus_rule_any_view_precision=est(
                rows, lambda rs: _ratio(rs, "gate_rule_any", "correct") - _ratio(rs, "rule_any_view", "correct"))),
        p7_inside_rule_any_view=dict(frame=sum(f["p7"] and f["rule_any_view"] for f in fr), p7=in_frame["p7"]),
        note="p7 promotes only rows where its chosen printed date passes the rule, so every p7 promotion is also a "
             "rule_any_view row; the difference between the two arms is what Apertus's is_answer gate and date choice add",
    )

    # (e) Qwen kappa, A1 vs A2
    qv = _ann_file("qwen.jsonl")
    both = [r for r in rows if r["id"] in qv]
    a1, a2 = _ann_file("A1.jsonl"), _ann_file("A2.jsonl")
    ids = sorted(set(a1) & set(a2))
    qwen = dict(
        qwen_vs_gold=kappa_block([r["gold"] for r in both], [qv[r["id"]] for r in both]),
        qwen_vs_gold_p7_stratum=dict(n=sum(r["id"] in qv for r in p7),
                                     qwen_yes=sum(qv.get(r["id"]) == "yes" for r in p7)),
        a1_vs_a2=kappa_block([a1[i] for i in ids], [a2[i] for i in ids]),
        disagreements=[dict(id=r["id"], gold=r["gold"], qwen=qv[r["id"]], stratum=r["stratum"]) for r in both
                       if qv[r["id"]] != r["gold"]],
        gold_prevalence_yes=_r(sum(r["gold"] == "yes" for r in rows) / len(rows)),
        note="kappa is low at high agreement because 180 of 190 gold labels are yes (expected agreement is high); PABAK "
             "is the prevalence-adjusted figure. Qwen-SEA-LION-v4-32B-IT saw the same packets as the annotators, "
             "including OPD's answer-event dates")

    # (f) base rate
    wsum = sum(r["w"] for r in rows)
    base = dict(
        yes=_r(sum(r["w"] for r in rows if r["correct"]) / wsum),
        yes_dated=_r(sum(r["w"] for r in rows if r["correct_dated"]) / wsum),
        h1_bar=H.H1_LB,
        h1_bar_minus_base_points=_r(100 * (H.H1_LB - sum(r["w"] for r in rows if r["correct"]) / wsum), 1),
        arms={a: dict(precision=abl["arms"][a]["precision"]["estimate"],
                      precision_dated=abl["arms"][a]["precision_dated"]["estimate"],
                      promoted_in_frame=in_frame[a],
                      lift_over_base_points=_r(100 * (abl["arms"][a]["precision"]["estimate"]
                                                      - sum(r["w"] for r in rows if r["correct"]) / wsum), 1),
                      dated_lift_over_base_points=_r(100 * (abl["arms"][a]["precision_dated"]["estimate"]
                                                            - sum(r["w"] for r in rows if r["correct_dated"]) / wsum), 1))
              for a in ARMS},
        note="'yes' is is_answer only; 'yes_dated' also needs a gold answer date that passes the adapters' rule (the "
             "registered correct_dated); precision of promoting every row equals the base rate by construction")

    def pc(ci):
        return [None if v is None else round(100 * v, 1) for v in ci]

    def pts(v):
        return round(100 * v, 1)
    dif = abl["differences"]
    display = dict(
        nf_h1_wilson_pct=pc(without_f["h1"]["wilson95"]),
        parliament_unit_wilson_pct=pc(cluster["h1_parliament_as_unit"]["wilson95"]),
        h4_cluster_pts=pc(cluster["h4"]["ci95"]), h4_nf_pts=pts(without_f["h4"]["estimate"]),
        h4_nf_pts_ci=pc(without_f["h4"]["ci95"]), h4_unweighted_pts=pts(h4u["unweighted"]["difference"]),
        h4_unweighted_pts_ci=pc(h4u["unweighted"]["row_bootstrap95"]),
        h4_without_rest_pts=pts(h4u["weight_sensitivity"]["rest"]["weighted_difference_without"]),
        p7_minus_rule_dated_pts=pts(dif["p7_minus_rule_any_view_precision_dated"]["estimate"]),
        p7_minus_rule_dated_pts_ci=pc(dif["p7_minus_rule_any_view_precision_dated"]["ci95"]),
        p7_minus_rule_is_answer_pts=pts(dif["p7_minus_rule_any_view_precision"]["estimate"]),
        p7_minus_rule_is_answer_pts_ci=pc(dif["p7_minus_rule_any_view_precision"]["ci95"]),
        date_choice_pts=pts(dif["p7_minus_gate_rule_any_precision_dated"]["estimate"]),
        date_choice_pts_ci=pc(dif["p7_minus_gate_rule_any_precision_dated"]["ci95"]),
        p7_minus_rule_date_hit_pts=pts(dif["p7_minus_rule_any_view_date_hit"]["estimate"]),
        p7_minus_rule_date_hit_pts_ci=pc(dif["p7_minus_rule_any_view_date_hit"]["ci95"]),
        bar_minus_base_pts=base["h1_bar_minus_base_points"],
        qwen_kappa=f'{qwen["qwen_vs_gold"]["kappa"]:.3f}', qwen_pabak=f'{qwen["qwen_vs_gold"]["pabak"]:.3f}',
        a1_a2_kappa=f'{qwen["a1_vs_a2"]["kappa"]:.3f}')
    res = dict(label=LABEL, display=display, inputs=dict(key_sha256=smp["key_sha256"], decisions_sha256=smp["decisions_sha256"]),
               config=dict(theta_a=cfg.theta_a, theta_b=cfg.theta_b, is_answer=cfg.is_answer),
               packets=len(rows), frame=len(fr), strata_N=smp["strata_N"], strata_n=smp["strata_n"],
               weights=smp["weights"], per_parliament=per, without_frauenfeld=without_f, cluster=cluster,
               h4_unweighted=h4u, trivial=trivial, ablation=abl, qwen=qwen, base_rate=base)
    OUT.write_text(json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return res


if __name__ == "__main__":
    from eval.p7 import offline
    if offline.needed():  # clean checkout: no WORK/p7test; run on the committed copies in data/p7/ (eval/p7/offline.py)
        raise SystemExit(offline.run(__spec__.name))
    r = main()
    print(json.dumps(dict(without_frauenfeld=r["without_frauenfeld"]["h1"], cluster=r["cluster"],
                          ablation={a: (r["ablation"]["promoted_in_frame"][a], r["ablation"]["arms"][a]["precision"],
                                        r["ablation"]["arms"][a]["precision_dated"]) for a in ARMS},
                          qwen=r["qwen"]["qwen_vs_gold"]), indent=1))
