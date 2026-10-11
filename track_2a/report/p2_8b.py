"""The real Apertus v1.5 8B (GGUF Q4_K_M, CPU) on P2, the unseen parliaments, set against the 70B and the trivial
baselines on the same documents. POST HOC: the 8B arms on P2 are the PREREG2 exploratory arms, run after the
review (DEVIATIONS2 D2-6); 52 of the 62 documents were reachable from the CI runners.

Reads only committed files: results/eval2/p2__<build>.json (8B and 70B per-document rows of the frozen scorer),
results/eval2/hypotheses2__<8B>.json (eval/gold2/hypotheses2.py, unchanged, on the 8B rows), data/gold2/p2_docs.jsonl
(body and OPD document type, for the type-gated latest-date baselines exactly as eval/posthoc_r3.py builds them) and the
unreachable lists in results/eval2/shards/. Correctness is eval/score.py's `outcome`, strict. No model call.

    PYTHONPATH=src:. python -m report.p2_8b   -> results/eval2/p2_8b_analysis.json
"""
from __future__ import annotations

import json
from collections import defaultdict

from eval.score import outcome
from gegenprobe.paths import DATA, RESULTS

B8 = "gguf_apertus-v1.5-8b-text-q4_k_m"
B70 = "publicai_swiss-ai_apertus-v1.5-8b"  # the 70B weights, served under the -8b name (report §3)
ARMS = ("rules", "pointer", "cascade")
BASELINES = ("always_null", "latest_date_gated_by_doc_type", "latest_date_on_answer_docs_only")


def p_str(p: float) -> str:
    """As the documents print p: two significant digits, scientific below 0.001."""
    if p >= 0.001:
        return f"{p:.2g}"
    m, e = f"{p:.1e}".split("e")
    return f"{m} × 10" + str(int(e)).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))


def mcnemar_exact(b: int, c: int) -> float:
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def _pred(row: dict, arm: str):
    x = row[arm]
    if arm == "rules":
        return x.get("value") if x.get("status") == "value" else None
    return x.get("value")


def _outcome(pred, row) -> str:
    return outcome(pred, row["gold"], set(row["doc_dates"]), row.get("lenient"), True)


def _ok(pred, row) -> bool:
    return _outcome(pred, row) in ("correct", "correct_null")


def _baseline(name: str, row: dict, dtype: str):
    dd = row.get("doc_dates") or []
    latest = max(dd) if dd else None
    if name == "always_null":
        return None
    if name == "latest_date_gated_by_doc_type":
        return None if dtype == "intervention" else latest
    return latest if dtype == "answer" else None


def _profile(preds: dict[int, object], rows: dict[int, dict]) -> dict:
    c = defaultdict(int)
    for d, r in rows.items():
        c[_outcome(preds[d], r)] += 1
    nulls = [d for d, r in rows.items() if r["gold"] is None]
    vals = [d for d, r in rows.items() if r["gold"] is not None]
    return dict(n=len(rows), exact=c["correct"] + c["correct_null"], dates_found=c["correct"], n_gold_value=len(vals),
                wrong_printed_date_on_answered=sum(_outcome(preds[d], rows[d]) == "misattributed" for d in vals),
                dates_on_answerless=sum(preds[d] is not None for d in nulls), n_answerless=len(nulls),
                fabricated=c["fabricated"], missed=c["false_null"],
                values_returned=sum(v is not None for v in preds.values()))


def _pair(a: dict, b: dict, rows: dict[int, dict], subset=None) -> dict:
    ids = [d for d in rows if subset is None or subset(rows[d])]
    a_only = sum(_ok(a[d], rows[d]) and not _ok(b[d], rows[d]) for d in ids)
    b_only = sum(_ok(b[d], rows[d]) and not _ok(a[d], rows[d]) for d in ids)
    p = mcnemar_exact(a_only, b_only)
    return dict(n=len(ids), a_only=a_only, b_only=b_only, p=p, p_str=p_str(p))


def main() -> dict:
    res8 = json.loads((RESULTS / "eval2" / f"p2__{B8}.json").read_text())
    res70 = json.loads((RESULTS / "eval2" / f"p2__{B70}.json").read_text())
    hyp8 = json.loads((RESULTS / "eval2" / f"hypotheses2__{B8}.json").read_text())
    meta = {d["doc_id"]: d for d in map(json.loads, open(DATA / "gold2" / "p2_docs.jsonl"))}
    r8 = {r["doc_id"]: r for r in res8["per_doc"]}
    r70_all = {r["doc_id"]: r for r in res70["per_doc"]}
    r70 = {d: r70_all[d] for d in r8}
    assert all(r8[d]["gold"] == r70[d]["gold"] for d in r8), "gold differs between the two result files"
    unreach = sorted({d for p in sorted((RESULTS / "eval2" / "shards").glob("unreachable_p2__*.json"))
                      for d in json.loads(p.read_text())})
    assert set(unreach) == set(res8["not_scored"]) and not set(unreach) & set(r8)

    preds = {f"8b_{a}": {d: _pred(r, a) for d, r in r8.items()} for a in ARMS}
    preds.update({f"70b_{a}": {d: _pred(r, a) for d, r in r70.items()} for a in ARMS})
    preds.update({b: {d: _baseline(b, r, meta[d]["dtype"]) for d, r in r8.items()} for b in BASELINES})
    profiles = {k: _profile(v, r8) for k, v in preds.items()}

    answered = lambda r: r["gold"] is not None  # noqa: E731
    # a_only / b_only: documents right only under the first / only under the second named arm (exact McNemar)
    comparisons = {
        "pointer8_vs_rules_answered": _pair(preds["8b_pointer"], preds["8b_rules"], r8, answered),
        "pointer8_vs_rules_all": _pair(preds["8b_pointer"], preds["8b_rules"], r8),
        "cascade8_vs_rules_all": _pair(preds["8b_cascade"], preds["8b_rules"], r8),
        "pointer8_vs_pointer70": _pair(preds["8b_pointer"], preds["70b_pointer"], r8),
        "cascade8_vs_cascade70": _pair(preds["8b_cascade"], preds["70b_cascade"], r8),
        "pointer8_vs_latest_gated": _pair(preds["8b_pointer"], preds["latest_date_gated_by_doc_type"], r8),
        "pointer70_vs_rules_answered": _pair(preds["70b_pointer"], preds["70b_rules"], r8, answered),
        "pointer70_vs_latest_gated": _pair(preds["70b_pointer"], preds["latest_date_gated_by_doc_type"], r8),
    }
    # registered P2-H2 on the 8B rows, from eval/gold2/hypotheses2.py (unchanged); must equal the recomputation above
    h2 = hyp8["subsets"]["all"]["theta_10_40"]["H2_pointer_vs_rules"]
    c = comparisons["pointer8_vs_rules_answered"]
    assert (h2["pointer_only"], h2["rules_only"]) == (c["a_only"], c["b_only"])
    # the rules arm is the same code on the same text: decisions must agree between the two runs
    rules_same = sum(preds["8b_rules"][d] == preds["70b_rules"][d] for d in r8)
    # 70B on all 62, for the side-by-side with the full set
    full70 = _profile({d: _pred(r, "pointer") for d, r in r70_all.items()}, r70_all)
    bodies = defaultdict(lambda: dict(docs=0, answered=0))
    for d, r in r8.items():
        bodies[meta[d]["body"]]["docs"] += 1
        bodies[meta[d]["body"]]["answered"] += r["gold"] is not None
    out = dict(
        label="POST HOC (10 Oct 2026): real 8B on P2 (DEVIATIONS2 D2-6); 70B and baselines restricted to the "
              "same documents. Strict scoring (eval/score.py outcome).",
        build_8b=B8, build_70b=B70, theta_8b=res8["theta"], theta_70b=res70["theta"],
        n_p2=len(r70_all), n_scored=len(r8), n_unreachable=len(unreach), unreachable_doc_ids=unreach,
        unreachable_bodies=sorted({meta[d]["body"] for d in unreach}),
        unreachable_answered=sum(r70_all[d]["gold"] is not None for d in unreach),
        bodies_scored=len(bodies), bodies_with_answers_scored=sum(v["answered"] > 0 for v in bodies.values()),
        rules_identical_8b_vs_70b_run=[rules_same, len(r8)],
        profiles=profiles,
        comparisons=comparisons,
        registered_h2_8b=dict(pointer_only=h2["pointer_only"], rules_only=h2["rules_only"], p=h2["p"],
                              p_str=p_str(h2["p"]), holds=h2["holds"]),
        p70_pointer_all_62=full70,
        display=dict(
            exact_8b=f"rules {profiles['8b_rules']['exact']}, pointer {profiles['8b_pointer']['exact']}, "
                     f"cascade {profiles['8b_cascade']['exact']} of {len(r8)}",
            exact_70b=f"pointer {profiles['70b_pointer']['exact']}, cascade {profiles['70b_cascade']['exact']} of {len(r8)}",
        ),
    )
    p = RESULTS / "eval2" / "p2_8b_analysis.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
