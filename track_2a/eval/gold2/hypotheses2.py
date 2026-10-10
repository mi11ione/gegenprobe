"""P2 hypotheses (eval/prereg2/PREREG2.md), computed from the frozen per-document rows of results/eval2/p2__<build>.json.
Correctness per document is the frozen eval/score.py `outcome` (strict). θ = 0 decisions are derived from the same cached
pointer margins: a value kept at θ = 10.40 is kept at θ = 0 iff its margin ≤ 0; an abstention at 10.40 stays an abstention.
Every block is reported for all P2 documents and without Bellinzona (5002), as registered.

    python -m eval.gold2.hypotheses2 publicai_swiss-ai_apertus-v1.5-8b
"""

from __future__ import annotations

import json
import math
import sys

from eval.score import outcome
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import auroc, wilson

P1_RULES_VALUE_RECALL = (
    47,
    64,
)  # P1 held-out, frozen rules: correct values / gold-value documents (results/eval/heldout__none.json)


def ok(pred, r) -> bool:
    return outcome(pred, r["gold"], set(r["doc_dates"]), r.get("lenient"), True) in ("correct", "correct_null")


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def newcombe(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """95% CI of p1 - p2 for independent proportions (Newcombe 1998, method 10, from Wilson intervals)."""
    if not n1 or not n2:
        return (float("nan"), float("nan"))
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    return (d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))


def decisions(r: dict, theta0: bool) -> dict:
    """Predictions per arm for one document; θ = 0 derived from the frozen margins."""
    p = r["pointer"]
    ptr = p.get("value")
    if theta0 and ptr is not None and p.get("margin") is not None and p["margin"] > 0:
        ptr = None
    st = r["rules"]["status"]
    if st == "value":
        cas, route = r["rules"]["value"], "rule"
    elif st == "null":
        cas, route = None, "rule"
    else:
        # residue: the cascade's pointer call is the same scored call as the pointer arm (same prompt, anchors, θ)
        cas = ptr if theta0 else r["cascade"].get("value")
        route = r["cascade"].get("route")
    out = dict(rules=r["rules"].get("value") if st == "value" else None, pointer=ptr, cascade=cas, cascade_route=route)
    for arm in ("naive_plain", "naive_null"):
        if arm in r:
            g = r[arm].get("date")
            out[arm] = None if (g is None or str(g).startswith("unparseable")) else g
    return out


def block(rows: list[dict], theta0: bool) -> dict:
    val = [r for r in rows if r["gold"] is not None]
    nul = [r for r in rows if r["gold"] is None]
    dec = {r["doc_id"]: decisions(r, theta0) for r in rows}
    arms_ = [a for a in ("rules", "pointer", "cascade", "naive_plain", "naive_null") if all(a in dec[r["doc_id"]] for r in rows)]
    out = dict(n=len(rows), n_gold_value=len(val), n_gold_null=len(nul), always_null_exact=[len(nul), len(rows)], arms={})
    for a in arms_:
        exact = sum(ok(dec[r["doc_id"]][a], r) for r in rows)
        vr = sum(ok(dec[r["doc_id"]][a], r) for r in val)
        on_null = sum(dec[r["doc_id"]][a] is not None for r in nul)
        out["arms"][a] = dict(
            exact=[exact, len(rows)],
            exact_ci=list(wilson(exact, len(rows))),
            value_recall=[vr, len(val)],
            value_recall_ci=list(wilson(vr, len(val))),
            values_on_gold_null=[on_null, len(nul)],
            values_on_gold_null_ci=list(wilson(on_null, len(nul))),
        )
    ap = [r for r in rows if dec[r["doc_id"]]["cascade_route"] == "apertus" and dec[r["doc_id"]]["cascade"] is not None]
    out["apertus_decided_values"] = dict(n=len(ap), correct=sum(ok(dec[r["doc_id"]]["cascade"], r) for r in ap))
    # P2-H2 (primary at θ 10.40): pointer vs rules on gold-value documents
    b = sum(ok(dec[r["doc_id"]]["pointer"], r) and not ok(dec[r["doc_id"]]["rules"], r) for r in val)
    c = sum(ok(dec[r["doc_id"]]["rules"], r) and not ok(dec[r["doc_id"]]["pointer"], r) for r in val)
    out["H2_pointer_vs_rules"] = dict(
        pointer_only=b, rules_only=c, p=mcnemar_exact(b, c), holds=mcnemar_exact(b, c) < 0.05 and b > c
    )
    b2 = sum(ok(dec[r["doc_id"]]["cascade"], r) and not ok(dec[r["doc_id"]]["rules"], r) for r in val)
    c2 = sum(ok(dec[r["doc_id"]]["rules"], r) and not ok(dec[r["doc_id"]]["cascade"], r) for r in val)
    out["cascade_vs_rules_on_values"] = dict(cascade_only=b2, rules_only=c2, p=mcnemar_exact(b2, c2))
    # P2-H3: cascade values on gold-null documents, Wilson upper <= 15%
    k = sum(dec[r["doc_id"]]["cascade"] is not None for r in nul)
    lo, hi = wilson(k, len(nul))
    out["H3_cascade_values_on_null"] = dict(k=k, n=len(nul), ci=[lo, hi], holds=hi <= 0.15)
    return out


def main(build: str) -> dict:
    res = json.loads((RESULTS / "eval2" / f"p2__{build}.json").read_text())
    body = {json.loads(x)["doc_id"]: json.loads(x)["body"] for x in open(DATA / "gold2" / "p2_docs.jsonl")}
    rows = res["per_doc"]
    out = dict(build=build, theta_primary=res["theta"], n=len(rows), subsets={})
    for name, sel in (("all", rows), ("without_bellinzona", [r for r in rows if body[r["doc_id"]] != "5002"])):
        s = dict(theta_10_40=block(sel, False), theta_0=block(sel, True))
        val = [r for r in sel if r["gold"] is not None]
        k2 = sum(ok(r["rules"].get("value") if r["rules"]["status"] == "value" else None, r) for r in val)
        k1, n1 = P1_RULES_VALUE_RECALL
        s["H1_rules_value_recall"] = dict(
            p1=[k1, n1],
            p2=[k2, len(val)],
            diff_ci=list(newcombe(k1, n1, k2, len(val))),
            confirmed_drop=newcombe(k1, n1, k2, len(val))[0] > 0,
        )
        pos = [r["pointer"]["margin"] for r in sel if r["gold"] is None and r["pointer"].get("n_cands")]
        neg = [r["pointer"]["margin"] for r in sel if r["gold"] is not None and r["pointer"].get("n_cands")]
        a = auroc(pos, neg)
        s["H4_auroc"] = dict(auroc=a, n_null=len(pos), n_value=len(neg), holds=a >= 0.80)
        out["subsets"][name] = s
    p = RESULTS / "eval2" / f"hypotheses2__{build}.json"
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1)[:6000])
