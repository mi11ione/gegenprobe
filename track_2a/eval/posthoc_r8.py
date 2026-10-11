"""POST HOC (11 Oct 2026; not pre-registered): multiplicity across every registered confirmatory test of P1-P7,
parliament-resampled intervals for the primary results of P5, P6 and P7, and the "no answer at all" split of P2/P6.
No model call; committed result files only (P7: results/p7/p7_hypotheses.json and p7_posthoc_r8.json; for H4's p-value
the registered stratified bootstrap is replayed on the WORK inputs via eval.p7.hypotheses8.load).

  multiplicity  family = the 9 tests of eval.posthoc_r4.multiplicity (P1-P4, P3b; recomputed, same rules) + P5 (H1, H2,
                H3a, H3b, H4), P6 (H1, H2, H3) and P7 (H1, H3, H4): m = 20. Interval rules -> the p-value of the test the
                interval inverts (Wilson: score test; P7-H4's percentile bootstrap: 2 x the share of replicates on the far
                side of 0, (count + 1) / (B + 1)); conjunctions (P5-H1 tier, P6-H2) -> intersection-union p (the largest
                component p; a deterministic component that fails makes p = 1). Holm and Benjamini-Hochberg at 0.05.
  clusters      parliaments resampled with replacement: P5-H1 (eval.posthoc_r6.p5_cluster), P5-H2 and P5-H4 paired
                differences (here), P6-H1 (eval.posthoc_r6.p6_cluster), P7-H1 and P7-H4 (results/p7/p7_posthoc_r8.json)
                -> both into results/eval/posthoc_r8_multiplicity.json
  noanswer      P2 and P6 "answerless" documents (gold answer_date null) split by the gold answer_present field into
                "no answer at all" (answer_present no or oral) and "an answer that prints no qualifying answer date"
                (answer_present yes, answer_date null), with every arm's dates on each kind, 70B and 8B
                -> results/eval/posthoc_r8_noanswer.json

    PYTHONPATH=src:. python -m eval.posthoc_r8 [multiplicity|noanswer|all]
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

from eval import posthoc_r4 as R4
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import wilson

LABEL = "POST HOC (11 Oct 2026; not pre-registered): no registered decision depends on this file"
B70, B8 = R4.B70, R4.B8
OUT_MULT = RESULTS / "eval" / "posthoc_r8_multiplicity.json"
OUT_NOANS = RESULTS / "eval" / "posthoc_r8_noanswer.json"
ALPHA = 0.05


def _j(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


# ------------------------------------------------------------------------------------------------------------ P5-P7 tests
def p7_h4_boot_p() -> dict:
    from eval.p7 import hypotheses8 as H
    from eval.p7 import posthoc_r8 as P
    rows, _ = H.load()
    stat = lambda rs: P._ratio(rs, "p7", "correct_dated") - P._ratio(rs, "trivial", "correct_dated")  # noqa: E731
    vals = P.boot_vals(rows, stat)
    le, ge = sum(v <= 0 for v in vals), sum(v >= 0 for v in vals)
    return dict(replicates=len(vals), at_or_below_0=le, at_or_above_0=ge,
                p=min(1.0, 2 * (min(le, ge) + 1) / (len(vals) + 1)), ci95=P._pct(vals))


def new_tests() -> list[dict]:
    h5 = _j(RESULTS / "eval6" / f"hypotheses6__p5__{B70}.json")
    h6 = _j(RESULTS / "p6" / f"hypotheses7__{B70}.json")
    h7 = _j(RESULTS / "p7" / "p7_hypotheses.json")
    t = []

    def add(tid, prereg, what, rule, p, holds, src, **kw):
        t.append(dict(id=tid, prereg=prereg, what=what, registered_rule=rule, p=p,
                      registered_outcome="holds" if holds else "fails", source=src, **kw))

    s5 = f"results/eval6/hypotheses6__p5__{B70}.json"
    pr, rc = h5["H1"]["precision"], h5["H1"]["recall"]
    a, b = R4.score_test_p(pr["k"], pr["n"], 0.70, "greater"), R4.score_test_p(rc["k"], rc["n"], 0.40, "greater")
    add("P5-H1 primary", "eval/prereg6/PREREG6.md", f"rules Q/A pairing, precision {pr['k']}/{pr['n']}, recall "
        f"{rc['k']}/{rc['n']} (tier '{h5['H1']['tier']}')", "tier not 'not yet': precision Wilson LB >= 0.70 and recall "
        "Wilson LB >= 0.40; intersection-union test: p = max of the two score-test p-values",
        max(a["p_equiv_two_sided"], b["p_equiv_two_sided"]), h5["H1"]["holds"], f"{s5} H1",
        p_kind="intersection-union (CI inversion, score test)",
        components=dict(precision_p=a["p_equiv_two_sided"], recall_p=b["p_equiv_two_sided"]))
    x = h5["H2"]
    add("P5-H2", "eval/prereg6/PREREG6.md", f"rules vs paragraph-order pairing, discordant {x['a_only']}-{x['b_only']}",
        "exact one-sided McNemar, alpha 0.05, rules better", x["p_one_sided"], x["holds"], f"{s5} H2",
        p_kind="exact McNemar (one-sided, as registered)")
    x = h5["H3"]["residue_recall"]
    c = R4.score_test_p(x["k"], x["n"], 0.50, "greater")
    add("P5-H3a", "eval/prereg6/PREREG6.md", f"pointer on the residue, recall {x['k']}/{x['n']}",
        "Wilson 95% lower bound >= 0.50", c["p_equiv_two_sided"], False, f"{s5} H3.residue_recall",
        p_kind="CI inversion (score test)", detail=c, registered_verdict=h5["H3"]["verdict"])
    x = h5["H3"]["suggestion_precision"]
    add("P5-H3b", "eval/prereg6/PREREG6.md", f"pointer suggestion precision {x['k']}/{x['n']} (no suggestion made)",
        "Wilson 95% lower bound >= 0.70", 1.0, False, f"{s5} H3.suggestion_precision",
        p_kind="untestable (0 suggestions): p = 1, kept in the family so that m is not reduced after the result")
    x = h5["H4"]
    add("P5-H4", "eval/prereg6/PREREG6.md",
        f"rules vs free generation (the pointer never fired, H3), discordant {x['a_only']}-{x['b_only']}",
        "exact one-sided McNemar, alpha 0.05, pointer better", x["p_one_sided"], x["holds"], f"{s5} H4",
        p_kind="exact McNemar (one-sided, as registered)")

    s6 = f"results/p6/hypotheses7__{B70}.json"
    x = h6["H1_v2_vs_free_null"]["doc_level"]
    add("P6-H1 primary", "eval/prereg7/PREREG7.md", f"v2 vs free_null exact accuracy, discordant {x['a_only']}-{x['b_only']}",
        "exact two-sided McNemar, alpha 0.05, v2 right on more", x["p"], h6["H1_v2_vs_free_null"]["holds"],
        f"{s6} H1_v2_vs_free_null", p_kind="exact McNemar")
    x = h6["H2_answerless"]
    k, n = x["v2"]
    c = R4.score_test_p(k, n, 0.15, "less")
    det = dict(v2_le_v1=k <= x["v1"], v2_le_free_null=k <= x["free_null"])
    add("P6-H2", "eval/prereg7/PREREG7.md", f"v2 dates {k}/{n} answerless documents (v1 {x['v1']}, free_null "
        f"{x['free_null']})", "Wilson 95% upper bound <= 15% AND v2 <= v1 AND v2 <= free_null; intersection-union: a "
        "failed count condition makes p = 1", c["p_equiv_two_sided"] if all(det.values()) else 1.0, x["holds"],
        f"{s6} H2_answerless", p_kind="intersection-union (CI inversion + count conditions)",
        components=dict(bound_p=c["p_equiv_two_sided"], **det))
    x = h6["H3_v2_vs_v1"]["doc_level"]
    add("P6-H3", "eval/prereg7/PREREG7.md", f"v2 vs v1 exact accuracy, discordant {x['a_only']}-{x['b_only']}",
        "exact two-sided McNemar, alpha 0.05, v2 right on more", x["p"], h6["H3_v2_vs_v1"]["holds"], f"{s6} H3_v2_vs_v1",
        p_kind="exact McNemar")

    s7 = "results/p7/p7_hypotheses.json"
    x = h7["H1"]
    c = R4.score_test_p(x["correct"], x["n"], 0.90, "greater")
    add("P7-H1 primary", "eval/prereg8/PREREG8.md", f"promotion precision {x['correct']}/{x['n']}",
        "Wilson 95% lower bound >= 0.90 with >= 40 judged (the count condition holds)", c["p_equiv_two_sided"], x["holds"],
        f"{s7} H1", p_kind="CI inversion (score test)", detail=c)
    x = h7["H3"]
    c = R4.score_test_p(x["correct"], x["n"], 0.90, "less")
    add("P7-H3", "eval/prereg8/PREREG8.md", f"free generation's extra promotions {x['correct']}/{x['n']}",
        "Wilson 95% upper bound < 0.90 ('supported')", c["p_equiv_two_sided"], x["supported"], f"{s7} H3",
        p_kind="CI inversion (score test)", detail=c)
    bp = p7_h4_boot_p()
    x = h7["H4"]
    assert bp["ci95"] == x["difference_precision_dated_p7_minus_trivial"]["ci95"], "bootstrap replay differs from H4"
    add("P7-H4", "eval/prereg8/PREREG8.md", "precision_dated p7 - trivial "
        f"{x['difference_precision_dated_p7_minus_trivial']['estimate']} {bp['ci95']}",
        "stratified bootstrap 95% interval lower bound > 0", bp["p"], x["supported"], f"{s7} H4",
        p_kind="bootstrap inversion: 2 x (replicates on the far side of 0 + 1) / (B + 1)", detail=bp)
    return t


# ------------------------------------------------------------------------------------------------------------ clusters
def p5_paired_cluster() -> dict:
    from eval import posthoc_r6 as R6
    from eval.gold6.hypotheses6 import per_answer
    from eval.gold6.score6 import gold_view
    res = _j(RESULTS / "eval6" / f"p5__{B70}.json")
    gold = {r["affair_id"]: gold_view(r) for r in _jsonl(DATA / "gold6" / "p5_labels.jsonl")}
    rows = [p for p in res["per_affair"] if p["affair_id"] in gold]

    def ok(p, arm):
        v = p[arm]["view"] if arm in ("R", "RA", "G") else p["B"][arm]
        return [c for _, _, c in per_answer(v, gold[p["affair_id"]])]
    out = {}
    for name, a, b in (("P5-H2 R vs B_order", "R", "B_order"), ("P5-H4 RA vs G", "RA", "G")):
        bodies = sorted({p["body"] for p in rows})
        t = np.zeros((len(bodies), 3))
        for p in rows:
            i = bodies.index(p["body"])
            oa, ob = ok(p, a), ok(p, b)
            t[i] += (sum(oa), sum(ob), len(oa))
        bt = R6._boot(t, R6._diff(0, 1, 2))
        per = t[:, 0] - t[:, 1]
        out[name] = dict(n_gold_answers=int(t[:, 2].sum()), a_correct=int(t[:, 0].sum()), b_correct=int(t[:, 1].sum()),
                         recall_difference=float((t[:, 0].sum() - t[:, 1].sum()) / t[:, 2].sum()),
                         parliament_cluster95=bt["ci95"], n_parliaments=len(bodies),
                         excludes_0=bt["ci95"][0] is not None and bt["ci95"][0] > 0,
                         parliaments_a_better=int((per > 0).sum()), parliaments_b_better=int((per < 0).sum()),
                         parliaments_tied=int((per == 0).sum()),
                         parliament_sign_test_p=R4.sign_test(int((per > 0).sum()), int((per < 0).sum())))
    return out


def clusters() -> dict:
    from eval import posthoc_r6 as R6
    p5 = R6.p5_cluster()
    p6 = R6.p6_cluster()
    p7 = _j(RESULTS / "p7" / "p7_posthoc_r8.json")
    h7 = _j(RESULTS / "p7" / "p7_hypotheses.json")
    return dict(
        method="percentile bootstrap resampling parliaments with replacement, B = 10,000 (P5/P6: seed 20261011 as in "
               "eval.posthoc_r6; P7: seed 20261014, each parliament keeping its annotated rows and stratum weights)",
        p5_h1=dict(precision=p5["precision"], recall=p5["recall"], registered_tier=p5["registered_tier"],
                   n_parliaments=p5["n_parliaments"]),
        p5_paired=p5_paired_cluster(),
        p6_h1=dict(p6["paired"]["v2 vs free_null"], n=p6["n"], note=p6["note"]),
        p6_h3=p6["paired"]["v2 vs v1"],
        p7_h1=dict(k=h7["H1"]["correct"], n=h7["H1"]["n"], wilson95=h7["H1"]["wilson95"],
                   parliament_cluster95=p7["cluster"]["h1_precision"]["ci95"],
                   parliament_as_unit=p7["cluster"]["h1_parliament_as_unit"],
                   without_frauenfeld=p7["without_frauenfeld"]["h1"]),
        p7_h4=dict(estimate=h7["H4"]["difference_precision_dated_p7_minus_trivial"]["estimate"],
                   stratified95=h7["H4"]["difference_precision_dated_p7_minus_trivial"]["ci95"],
                   parliament_cluster95=p7["cluster"]["h4"]["ci95"], excludes_0=p7["cluster"]["h4"]["excludes_0"],
                   without_frauenfeld=p7["without_frauenfeld"]["h4"]),
    )


def multiplicity() -> dict:
    with tempfile.TemporaryDirectory() as d:
        old = R4.multiplicity(Path(d) / "r4.json")
    keep = ("id", "prereg", "what", "registered_rule", "p", "registered_outcome", "source", "p_kind", "detail", "components")
    tests = [{k: x[k] for k in keep if k in x} for x in old["tests"]] + new_tests()
    ps = [x["p"] for x in tests]
    for x, a, b in zip(tests, R4.holm(ps), R4.bh(ps)):
        x["p_holm"], x["p_bh"] = a, b
        x["holds_after_holm"] = x["registered_outcome"] == "holds" and a < ALPHA
        x["holds_after_bh"] = x["registered_outcome"] == "holds" and b < ALPHA
    m9 = {x["id"]: x["p_holm"] for x in old["tests"]}
    for x in tests:
        if x["id"] in m9:
            x["p_holm_m9_round4"] = m9[x["id"]]
    held = [x for x in tests if x["registered_outcome"] == "holds"]
    survive = [x["id"] for x in tests if x["holds_after_holm"]]
    lost = [x["id"] for x in held if not x["holds_after_holm"]]
    worst = max((x for x in tests if x["holds_after_holm"]), key=lambda x: x["p_holm"])
    out = dict(
        label=LABEL,
        method=__doc__.split("  clusters")[0].split("  multiplicity")[1].strip(),
        m=len(tests), tests=tests,
        n_registered_holds=len(held), registered_holds=[x["id"] for x in held],
        survive_holm=survive, n_survive_holm=len(survive), lost_after_holm=lost,
        survive_bh=[x["id"] for x in tests if x["holds_after_bh"]],
        by_id={x["id"]: dict(p=x["p"], p_holm=x["p_holm"], p_bh=x["p_bh"], registered_outcome=x["registered_outcome"],
                             holds_after_holm=x["holds_after_holm"]) for x in tests},
        display={x["id"]: dict(p=R4.p_str(x["p"]), p_holm=R4.p_str(x["p_holm"]), p_bh=R4.p_str(x["p_bh"])) for x in tests},
        smallest_margin=dict(id=worst["id"], p_holm=worst["p_holm"]),
        conclusion=("%d of the %d registered confirmatory tests of P1-P7 held as registered; %s survive Holm over all %d "
                    "(smallest margin %s, Holm p = %s). No failed test turns into a pass." % (
                        len(held), len(tests), "all %d" % len(held) if not lost else f"{len(survive)} (lost: {', '.join(lost)})",
                        len(tests), worst["id"], R4.p_str(worst["p_holm"]))),
        not_in_family=old["not_in_family"] + [
            dict(id="P5-H5", rule="0 provenance re-check failures (deterministic count)", registered_outcome="holds"),
            dict(id="P5 S1/S2 verdict", rule="derived from H1 and H2"),
            dict(id="P6 secondary (S1-S7) and the 8B run", rule="registered without a decision / exploratory"),
            dict(id="P7-H2", rule="an estimate (queue promotions x H1 precision), no test"),
        ],
        clusters=clusters(),
    )
    c = out["clusters"]
    pc = lambda ci: [round(100 * v, 1) for v in ci]  # noqa: E731
    out["summary_display"] = dict(
        smallest_margin_holm=R4.p_str(worst["p_holm"]),
        p7_h1_holm=R4.p_str(out["by_id"]["P7-H1 primary"]["p_holm"]) if "by_id" in out else None,
        p6_h1_cluster_pts=pc(c["p6_h1"]["cluster_bootstrap95"]),
        p5_h2_cluster_pts=pc(c["p5_paired"]["P5-H2 R vs B_order"]["parliament_cluster95"]),
        p5_h4_cluster_pts=pc(c["p5_paired"]["P5-H4 RA vs G"]["parliament_cluster95"]),
        p5_h1_precision_cluster_pct=pc(c["p5_h1"]["precision"]["parliament_cluster95"]),
        p5_h1_recall_cluster_pct=pc(c["p5_h1"]["recall"]["parliament_cluster95"]),
        p7_h4_cluster_pts=pc(c["p7_h4"]["parliament_cluster95"]))
    R4._write(OUT_MULT, out)
    return out


# ------------------------------------------------------------------------------------------------------------ no answer
def _value(arm: dict | None):
    arm = arm or {}
    return arm.get("value") or arm.get("date")


def split(results_file: str, labels_file: str, arms: list[str]) -> dict:
    lab = {r["doc_id"]: r for r in _jsonl(DATA / labels_file)}
    per = _j(RESULTS / results_file)["per_doc"]
    nod = [r for r in per if not lab[r["doc_id"]].get("answer_date")]
    kinds = {r["doc_id"]: lab[r["doc_id"]]["answer_present"] for r in nod}
    none = [d for d, k in kinds.items() if k in ("no", "oral")]
    noq = [d for d, k in kinds.items() if k == "yes"]
    other = [d for d, k in kinds.items() if k not in ("no", "oral", "yes")]
    out = dict(results=f"results/{results_file}", labels=f"data/{labels_file}", n_docs=len(per), answerless=len(nod),
               answer_present_counts={k: sum(v == k for v in kinds.values()) for k in sorted(set(kinds.values()))},
               no_answer_at_all=len(none), answer_without_qualifying_date=len(noq), other=len(other), arms={})
    for a in arms:
        dated = {r["doc_id"] for r in nod if _value(r.get(a))}
        k0 = len(dated & set(none))
        out["arms"][a] = dict(dated_answerless=len(dated), on_no_answer_at_all=k0,
                              on_no_answer_at_all_wilson95=[round(v, 4) for v in wilson(k0, len(none))],
                              on_answer_without_qualifying_date=len(dated & set(noq)))
    return out


def noanswer() -> dict:
    p2 = split(f"eval2/p2__{B70}.json", "gold2/p2_labels.jsonl", ["rules", "pointer", "cascade", "naive_null",
                                                                 "naive_plain"])
    p6 = split(f"p6/p6__{B70}.json", "p6/p6_labels.jsonl", ["rules", "v1", "v2", "cascade_v2", "free_null", "free_guided",
                                                            "free_plain"])
    p6_8b = split(f"p6/p6__{B8}.json", "p6/p6_labels.jsonl", ["rules", "v1", "v2", "cascade_v2", "free_null",
                                                             "free_guided"])
    n0 = p2["no_answer_at_all"] + p6["no_answer_at_all"]
    k0 = p2["arms"]["pointer"]["on_no_answer_at_all"] + p6["arms"]["v2"]["on_no_answer_at_all"]
    kq = p2["arms"]["pointer"]["on_answer_without_qualifying_date"] + p6["arms"]["v2"]["on_answer_without_qualifying_date"]
    nq = p2["answer_without_qualifying_date"] + p6["answer_without_qualifying_date"]
    out = dict(
        label=("POST HOC (11 Oct 2026): this split was defined on 11 Oct 2026 in report/r7docs_numbers.py, AFTER "
               "the P2 and P6 results were known; neither PREREG2 nor PREREG7 registers it. The registered 'answerless' "
               "outcome (P2-H3, P6-H2) is unchanged and failed."),
        definition=dict(
            answerless="gold answer_date is null (the registered P2/P6 'answerless' or gold-null documents)",
            no_answer_at_all="answerless AND gold answer_present is 'no' (no written answer in the document) or 'oral' "
                             "(answered orally in the sitting; P6 only)",
            answer_without_qualifying_date="answerless AND gold answer_present is 'yes': the document contains the "
                                           "answer but prints no date the guide accepts as the answer date",
            dated="the arm returns a date (any value) on the document; every such date on an answerless document is "
                  "wrong under the registered scorer"),
        p2_70b=p2, p6_70b=p6, p6_8b=p6_8b,
        headline=dict(
            what="Apertus 70B closed-set arms (P2 pointer, P6 reader v2) on documents with no answer at all",
            no_answer_docs=n0, dated=k0, wilson95=[round(v, 4) for v in wilson(k0, n0)],
            dates_on_answers_without_qualifying_date=[kq, nq],
            dated_answerless_total=p2["arms"]["pointer"]["dated_answerless"] + p6["arms"]["v2"]["dated_answerless"],
            still_wrong=("all %d dates the two arms put on answerless documents are wrong under the registered scorer; "
                         "they fall on documents that do contain an answer" % (kq + k0))),
        comparators=dict(
            p2_naive_null=p2["arms"]["naive_null"]["on_no_answer_at_all"],
            p6_free_null=p6["arms"]["free_null"]["on_no_answer_at_all"],
            p6_free_guided=p6["arms"]["free_guided"]["on_no_answer_at_all"],
            p2_naive_plain=p2["arms"]["naive_plain"]["on_no_answer_at_all"],
            p6_free_plain=p6["arms"]["free_plain"]["on_no_answer_at_all"],
            free_null_allowed_total=p2["arms"]["naive_null"]["on_no_answer_at_all"]
            + p6["arms"]["free_null"]["on_no_answer_at_all"],
            note="70B free prompts on the same %d documents: null allowed %d (P2 %d, P6 %d), plain %d" % (
                n0, p2["arms"]["naive_null"]["on_no_answer_at_all"] + p6["arms"]["free_null"]["on_no_answer_at_all"],
                p2["arms"]["naive_null"]["on_no_answer_at_all"], p6["arms"]["free_null"]["on_no_answer_at_all"],
                p2["arms"]["naive_plain"]["on_no_answer_at_all"] + p6["arms"]["free_plain"]["on_no_answer_at_all"])),
        p6_8b_headline=dict(no_answer_docs=p6_8b["no_answer_at_all"], v2=p6_8b["arms"]["v2"]["on_no_answer_at_all"],
                            v1=p6_8b["arms"]["v1"]["on_no_answer_at_all"],
                            free_null=p6_8b["arms"]["free_null"]["on_no_answer_at_all"],
                            free_guided=p6_8b["arms"]["free_guided"]["on_no_answer_at_all"]),
        display=dict(wilson95_pct=[round(100 * v, 1) for v in wilson(k0, n0)]),
        p1="P1 labels have no answer_present field; the P1 figure (rules then Apertus date 7 of 90 gold-null documents) is "
           "not split",
    )
    R4._write(OUT_NOANS, out)
    return out


def main(cmd: str) -> None:
    if cmd in ("multiplicity", "all"):
        o = multiplicity()
        print(o["conclusion"])
        for x in o["tests"]:
            print(f"  {x['id']:16s} p={R4.p_str(x['p']):>14s} holm={R4.p_str(x['p_holm']):>14s} "
                  f"{x['registered_outcome']:5s} holds_after_holm={x['holds_after_holm']}")
    if cmd in ("noanswer", "all"):
        o = noanswer()
        print(json.dumps(o["headline"]), json.dumps(o["comparators"]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
