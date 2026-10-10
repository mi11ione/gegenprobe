"""P5 hypotheses exactly as registered in eval/prereg6/PREREG6.md (definitions and thresholds fixed there), applied to a
results file of eval.gold6.run6 and the merged labels.

    python -m eval.gold6.hypotheses6 <split> <build>   -> results/eval6/hypotheses6__<split>__<build>.json
(split p5 is the registered test; p5dev gives the same numbers on the development set, in-sample.)
"""

from __future__ import annotations

import json
import math
import sys

from eval.gold6.score6 import gold_view, iou, score
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import wilson


def binom_tail(k: int, n: int) -> float:
    """P(X >= k) for X ~ Bin(n, 1/2) (exact one-sided McNemar on discordant pairs)."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n if n else 1.0


def mcnemar(a: list[bool], b: list[bool]) -> dict:
    """a better than b, one-sided exact; also the two-sided p."""
    ab = sum(x and not y for x, y in zip(a, b))
    ba = sum(y and not x for x, y in zip(a, b))
    n = ab + ba
    one = binom_tail(ab, n)
    two = min(1.0, 2 * min(binom_tail(ab, n), binom_tail(ba, n))) if n else 1.0
    return dict(a_only=ab, b_only=ba, p_one_sided=one, p_two_sided=two)


def tier(k: int, n: int, hi_bar: float = 0.80, lo_bar: float = 0.50) -> dict:
    lo, hi = wilson(k, n) if n else (None, None)
    t = "no gold" if not n else ("extractable unattended" if lo >= hi_bar else "partial" if lo >= lo_bar else "not yet")
    return dict(k=k, n=n, ci95=[lo, hi], tier=t)


def per_answer(view: dict, gold: dict) -> list[tuple[int, int, bool]]:
    """(affair, n, correct) for every gold non-null answer."""
    pa = {x["n"]: x["span"] for x in view.get("answers") or []}
    return [(0, x["n"], iou(x["span"], pa.get(x["n"])) >= 0.5) for x in gold["answers"] if x["span"] is not None]


def residue(rows, gold, arm: str) -> dict:
    """Residue = gold non-null answers whose question R leaves without a span; suggestions = answer spans the arm adds
    where R has none; spans_on_gold_null = suggestions where the gold answer is null (or the question is not in gold)."""
    res_gold = res_ok = sugg = sugg_ok = on_null = 0
    for p in rows:
        g = gold[p["affair_id"]]
        rv = {x["n"]: x["span"] for x in p["R"]["view"]["answers"]}
        av = {x["n"]: x["span"] for x in p[arm]["view"]["answers"]}
        gs = {x["n"]: x["span"] for x in g["answers"]}
        for n, sp in av.items():
            if rv.get(n) is None and sp is not None:
                sugg += 1
                sugg_ok += gs.get(n) is not None and iou(gs[n], sp) >= 0.5
                on_null += gs.get(n) is None
        for x in g["answers"]:
            if x["span"] is not None and rv.get(x["n"]) is None:
                res_gold += 1
                res_ok += av.get(x["n"]) is not None and iou(x["span"], av[x["n"]]) >= 0.5
    rec_t, prec_t = tier(res_ok, res_gold, 0.50, 0.50), tier(sugg_ok, sugg, 0.70, 0.70)
    if res_gold < 10:
        verdict = "inconclusive (underpowered: fewer than 10 residue answers)"
    elif (rec_t["ci95"][0] or 0) >= 0.50 and (prec_t["ci95"][0] or 0) >= 0.70:
        verdict = "pointer adds answers unattended"
    elif (rec_t["ci95"][0] or 0) >= 0.50:
        verdict = "pointer finds answers; review gate (precision below bar)"
    else:
        verdict = "no measurable gain"
    return dict(arm=arm, residue_recall=rec_t, suggestion_precision=prec_t, suggestions=sugg,
                spans_on_gold_null=on_null, verdict=verdict)


def main(split: str, build: str) -> dict:
    res = json.loads((RESULTS / "eval6" / f"{split}__{build}.json").read_text())
    gold = {r["affair_id"]: gold_view(r) for r in map(json.loads, open(DATA / "gold6" / f"{split}_labels.jsonl"))}
    rows = [p for p in res["per_affair"] if p["affair_id"] in gold]
    out: dict = dict(split=split, build=build, n_affairs=len(rows), prereg="eval/prereg6/PREREG6.md")
    sc = {arm: score({p["affair_id"]: (p[arm]["view"] if arm in ("R", "RA", "RA0", "G") else p["B"][arm]) for p in rows}, gold)
          for arm in ("R", "RA", "RA0", "G", "B_order", "B_whole")
          if all((arm in p) or (arm.startswith("B") and "B" in p) for p in rows)}

    def correct_list(arm):
        out_l = []
        for p in rows:
            v = p[arm]["view"] if arm in ("R", "RA", "RA0", "G") else p["B"][arm]
            out_l += [c for _, _, c in per_answer(v, gold[p["affair_id"]])]
        return out_l

    # H1 (primary): rules-only Q/A pairing
    r = sc["R"]["qa_pairs"]
    plo = r["precision"]["ci95"][0] or 0
    rlo = r["recall"]["ci95"][0] or 0
    t = ("per-question pairing extractable unattended" if plo >= 0.85 and rlo >= 0.60 else
         "partial" if plo >= 0.70 and rlo >= 0.40 else "not yet")
    out["H1"] = dict(recall=r["recall"], precision=r["precision"], false_span_on_gold_null=r["false_span_on_gold_null"],
                     tier=t, holds=t != "not yet")
    # H2: rules beat the paragraph-order baseline on gold non-null answers (one-sided exact McNemar, alpha 0.05)
    R_ok, B_ok = correct_list("R"), correct_list("B_order")
    m = mcnemar(R_ok, B_ok)
    out["H2"] = dict(m, holds=m["p_one_sided"] < 0.05, n_gold_answers=len(R_ok))
    # H3 (primary pointer arm RA) and H3b (secondary arm RA0, θ_pair = 0): the pointer on the residue
    for h, arm in (("H3", "RA"), ("H3b_secondary", "RA0")):
        if arm in sc:
            out[h] = residue(rows, gold, arm)
    if "RA" in sc:
        out["H3"]["rec_residue"] = sum(1 for p in rows if p["R"]["view"]["recommendation"] is None)
        out["H3"]["rec_residue_correct"] = sum(1 for p in rows if p["R"]["view"]["recommendation"] is None
                                               and p["RA"]["view"]["recommendation"] == gold[p["affair_id"]]["recommendation"])
    # H4: closed-set pointer system vs free generation on Q/A pairing (paired on gold non-null answers)
    if "G" in sc and "RA" in sc:
        G_ok, RA_ok = correct_list("G"), correct_list("RA")
        m4 = mcnemar(RA_ok, G_ok)
        out["H4"] = dict(m4, RA_precision=sc["RA"]["qa_pairs"]["precision"], G_precision=sc["G"]["qa_pairs"]["precision"],
                         G_unlocatable_values=sum(p["G"].get("unlocatable", 0) for p in rows),
                         G_parse_failures=sum(not p["G"].get("parse_ok", False) for p in rows),
                         holds=m4["p_one_sided"] < 0.05)
    # H5: every value of the R / RA records validates and re-checks against its span
    rc = {arm: dict(ok=sum(p[arm]["recheck"]["ok"] for p in rows), failed=sum(p[arm]["recheck"]["failed"] for p in rows))
          for arm in ("R", "RA", "RA0") if all(arm in p and "recheck" in p[arm] for p in rows)}
    out["H5"] = dict(recheck=rc, holds=all(v["failed"] == 0 for k, v in rc.items() if k in ("R", "RA")))
    # descriptive per-field tiers (rules arm R and RA), as P3's H1 bars
    out["fields"] = {arm: dict(
        questions_recall=tier(s["questions"]["recall"]["k"], s["questions"]["recall"]["n"]),
        questions_precision=tier(s["questions"]["precision"]["k"], s["questions"]["precision"]["n"]),
        submitter=tier(s["submitter"]["k"], s["submitter"]["n"]),
        co_signatories_recall=tier(s["co_signatories"]["recall"]["k"], s["co_signatories"]["recall"]["n"]),
        co_signatories_precision=tier(s["co_signatories"]["precision"]["k"], s["co_signatories"]["precision"]["n"]),
        recommendation=tier(s["recommendation"]["k"], s["recommendation"]["n"]),
        reasoning=tier(s["reasoning"]["match"]["k"], s["reasoning"]["match"]["n"]),
        reasoning_mean_iou=s["reasoning"]["mean_iou"],
    ) for arm, s in sc.items()}
    out["scores"] = {arm: {k: v for k, v in s.items() if k != "per_affair"} for arm, s in sc.items()}
    # success criteria
    s1 = out["H1"]["holds"]
    s2 = out["H2"]["holds"]
    out["verdict"] = ("supported" if s1 and s2 else "partially supported" if (s1 or s2) else "not supported")
    p = RESULTS / "eval6" / f"hypotheses6__{split}__{build}.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    o = main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "publicai_swiss-ai_apertus-v1.5-8b")
    print(json.dumps({k: v for k, v in o.items() if k not in ("scores", "fields")}, indent=1))
