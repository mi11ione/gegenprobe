"""Display-ready numbers for the docs pass after upgrades U1-U3 (source adapters, P5, P6), derived only from committed
results files, so claims.tsv can trace the strings the documents print:

  * source adapters: number of parliaments with an adapter route; the fresh blind audit recomputed from its verdicts
    (results/repair/adapters/audit/fresh_audit_verdicts.jsonl, checked against fresh_audit_precision.json), precision
    and Wilson interval at three decimals;
  * P5 (eval/prereg6): rules-only Q/A pairing precision and recall with Wilson intervals at two decimals, and the paired
    discordant counts of H2 and H4 as "a:b" with one-sided p (results/eval6/hypotheses6__p5__*.json); the Qwen check's
    verbatim-valid files (results/eval6/p5_qwen_check.json);
  * P6 (eval/prereg7): discordant counts as "a:b" and p-values at three or two decimals
    (results/p6/hypotheses7__*.json),
    and the arms' exact scores under the Qwen labels (results/p6/qwen7_check.json);
  * P2: the pointer-vs-rules discordant counts as "a:b", on all 62 and on the 29 answered documents
    (results/eval/posthoc_r3_paired.json).

    PYTHONPATH=src:. python -m report.upd_numbers   -> results/report/upd_numbers.json
"""
from __future__ import annotations

import collections
import json
from decimal import ROUND_HALF_UP, Decimal

from gegenprobe.paths import RESULTS
from gegenprobe.stats import wilson

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"


def _r(x: float, nd: int) -> str:
    return str(Decimal(str(x)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))


def _ci(lo: float, hi: float, nd: int) -> str:
    return f"{_r(lo, nd)}–{_r(hi, nd)}"


SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def _sci(x: float) -> str:
    """p-value as printed: "7.8 × 10⁻²⁹" (two significant digits)."""
    m, e = f"{x:.1e}".split("e")
    return f"{m} × 10{str(int(e)).translate(SUP)}"


def _pair(d: dict, a: str = "a_only", b: str = "b_only") -> str:
    return f"{d[a]}:{d[b]}"


def adapters() -> dict:
    """Recomputes the fresh audit from the blind verdicts themselves (audit/fresh_audit_verdicts.jsonl) and asserts that
    it equals the committed summary (audit/fresh_audit_precision.json)."""
    base = RESULTS / "repair" / "adapters"
    s = json.loads((base / "adapters_summary.json").read_text())
    f = json.loads((base / "audit" / "fresh_audit_precision.json").read_text())
    v = collections.Counter(json.loads(x)["is_answer"] for x in open(base / "audit" / "fresh_audit_verdicts.jsonl"))
    n, yes = sum(v.values()), v["yes"]
    lo, hi = wilson(yes, n)
    assert (n, yes, v["no"], v["unclear"]) == (f["n"], f["is_answer_yes"], f["no"], f["unclear"]), (v, f)
    # the committed summary used z = 1.959964, gegenprobe.stats z = 1.96: equal to 5 decimals
    assert abs(lo - f["wilson95"][0]) < 1e-5 and abs(hi - f["wilson95"][1]) < 1e-5
    return dict(parliaments=len(s["bodies"]), fresh_n=n, fresh_yes=f"{yes}/{n}", fresh_yes_n=yes,
                fresh_no=v["no"], fresh_unclear=v["unclear"], fresh_precision=_r(yes / n, 3), fresh_wilson=_ci(lo, hi, 3))


def p5() -> dict:
    h = json.loads((RESULTS / "eval6" / f"hypotheses6__p5__{BUILD}.json").read_text())
    q = json.loads((RESULTS / "eval6" / "p5_qwen_check.json").read_text())
    pr, rc = h["H1"]["precision"], h["H1"]["recall"]
    return dict(precision=_r(pr["rate"], 2), precision_ci=_ci(*pr["ci95"], 2), recall=_r(rc["rate"], 2),
                recall_ci=_ci(*rc["ci95"], 2), h2=_pair(h["H2"]), h4=_pair(h["H4"]),
                h2_p=_sci(h["H2"]["p_one_sided"]), h4_p=_sci(h["H4"]["p_one_sided"]),
                provenance_failures=sum(v["failed"] for v in h["H5"]["recheck"].values()),
                qwen_valid=f"{q['agreement']['valid']}/{q['agreement']['n']}")


def p6() -> dict:
    h = json.loads((RESULTS / "p6" / f"hypotheses7__{BUILD}.json").read_text())
    q = json.loads((RESULTS / "p6" / "qwen7_check.json").read_text())["hypotheses_under_qwen_gold"]["qwen_strict"]
    s3 = h["S3_cascade_v2_vs_rules_on_answered"]
    return dict(h1=_pair(h["H1_v2_vs_free_null"]["doc_level"]), h1_p=_r(h["H1_v2_vs_free_null"]["doc_level"]["p"], 2),
                h3=_pair(h["H3_v2_vs_v1"]["doc_level"]), h3_p=_r(h["H3_v2_vs_v1"]["doc_level"]["p"], 2),
                s3=_pair(s3), s3_p=_r(s3["p"], 3),
                qwen_v2=f"{q['arms']['v2']['exact'][0]}/{q['arms']['v2']['exact'][1]}",
                qwen_free_null=f"{q['arms']['free_null']['exact'][0]}/{q['arms']['free_null']['exact'][1]}",
                qwen_decisions_changed=sum(int(q[k]["holds"]) != int(h[n]["holds"]) for k, n in
                                           (("H1", "H1_v2_vs_free_null"), ("H2", "H2_answerless"), ("H3", "H3_v2_vs_v1"))))


def p2() -> dict:
    c = json.loads((RESULTS / "eval" / "posthoc_r3_paired.json").read_text())["splits"]["P2"]["comparisons"]["pointer~rules"]
    return dict(h2_all=_pair(c["all"], "pointer_only", "rules_only"),
                h2_answered=_pair(c["gold_value"], "pointer_only", "rules_only"))


def main() -> dict:
    out = dict(adapters=adapters(), p5=p5(), p6=p6(), p2=p2())
    p = RESULTS / "report" / "upd_numbers.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(p)
    return out


if __name__ == "__main__":
    main()
