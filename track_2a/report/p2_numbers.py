"""Display-ready numbers for the P2 (unseen parliaments) pre-registered test and the cross-test framing, derived only from
committed results files, so claims.tsv can trace every number the README, report, form notes and site print.

    python -m report.p2_numbers   -> results/report/p2_numbers.json
"""
from __future__ import annotations

import json

from gegenprobe.paths import DATA, RESULTS

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
ARMS = ("rules", "pointer", "cascade", "naive_plain", "naive_null")


def pct(ci: list[float]) -> list[float]:
    return [round(100 * ci[0], 1), round(100 * ci[1], 1)]


def sci(p: float) -> str:
    """4.76837158203125e-07 -> '4.8 × 10⁻⁷'."""
    m, e = f"{p:.1e}".split("e")
    sup = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
    return f"{m} × 10{str(int(e)).translate(sup)}"


def main() -> dict:
    board = json.loads((RESULTS / "eval2" / f"p2__{BUILD}.json").read_text())
    hyp = json.loads((RESULTS / "eval2" / f"hypotheses2__{BUILD}.json").read_text())
    agree = json.loads((RESULTS / "eval2" / "gold2_agreement.json").read_text())
    docs = [json.loads(x) for x in open(DATA / "gold2" / "p2_docs.jsonl")]
    dev_bodies = {json.loads(x)["body"] for x in open(DATA / "gold" / "dev_docs.jsonl")}
    held_bodies = {json.loads(x)["body"] for x in open(DATA / "gold" / "heldout_docs.jsonl")}
    matrix = json.loads((RESULTS / "census" / "matrix.json").read_text())
    s_all = hyp["subsets"]["all"]
    s_nb = hyp["subsets"]["without_bellinzona"]
    t = s_all["theta_10_40"]
    out: dict = dict(build=BUILD, n=board["n_docs"], n_bodies=len({d["body"] for d in docs}), arms={})
    for a in ARMS:
        s = board["arms"][a]["strict"]["ALL"]
        h = t["arms"].get(a, {})
        out["arms"][a] = dict(exact=s["exact"], n=s["n"], exact_ci_pct=pct(s["exact_ci"]), correct=s["correct"],
                              correct_null=s["correct_null"], false_null=s["false_null"], misattributed=s["misattributed"],
                              fabricated=s["fabricated"], invented_on_null=s["invented_on_null"], n_gold_null=s["n_gold_null"],
                              n_gold_value=s["n_gold_value"],
                              value_recall=h.get("value_recall", [None, None])[0])
    out["always_null"] = t["always_null_exact"]
    out["n_gold_value"] = t["n_gold_value"]
    out["n_gold_null"] = t["n_gold_null"]
    h2 = t["H2_pointer_vs_rules"]
    out["H2"] = dict(pointer_only=h2["pointer_only"], rules_only=h2["rules_only"], p=h2["p"], p_str=sci(h2["p"]),
                     holds=h2["holds"])
    h2nb = s_nb["theta_10_40"]["H2_pointer_vs_rules"]
    out["H2_without_bellinzona"] = dict(pointer_only=h2nb["pointer_only"], rules_only=h2nb["rules_only"], p=h2nb["p"],
                                        p_str=sci(h2nb["p"]), holds=h2nb["holds"])
    h3 = t["H3_cascade_values_on_null"]
    out["H3"] = dict(k=h3["k"], n=h3["n"], upper_pct=round(100 * h3["ci"][1], 1), holds=h3["holds"])
    h3z = s_all["theta_0"]["H3_cascade_values_on_null"]
    out["H3_theta0"] = dict(k=h3z["k"], n=h3z["n"], holds=h3z["holds"])
    h1 = s_all["H1_rules_value_recall"]
    out["H1"] = dict(p1=h1["p1"], p2=h1["p2"], diff_ci_pct=pct(h1["diff_ci"]), confirmed_drop=h1["confirmed_drop"])
    h4 = s_all["H4_auroc"]
    out["H4"] = dict(auroc=h4["auroc"], auroc_str=f"{h4['auroc']:.3f}", holds=h4["holds"])
    out["gold"] = dict(n=agree["n"], date_agree=agree["agreement"]["answer_date"]["raw"],
                       kappa_date=agree["agreement"]["answer_date"]["kappa"], decided_by_a3=agree["decided_by_A3"],
                       oracle_match=agree["oracle"].get("match", 0),
                       oracle_checked=agree["oracle"].get("match", 0) + agree["oracle"].get("mismatch", 0))
    # parliaments the rules were developed on (dev bodies) vs the census scope
    out["bodies_rules_developed_on"] = len(dev_bodies)
    out["bodies_in_scope"] = matrix["n_bodies"]
    out["bodies_without_rules"] = matrix["n_bodies"] - len(dev_bodies)
    out["p2_bodies_disjoint"] = not ({d["body"] for d in docs} & (dev_bodies | held_bodies))
    rob = json.loads((RESULTS / "eval" / "robustness.json").read_text())["paired"]["primary_fr_it_ocr"]
    out["p1_primary"] = dict(diff_pts=f"+{100 * rob['difference']:.1f}",
                             ci_pts=f"{100 * rob['ci95'][0]:.1f} to {100 * rob['ci95'][1]:.1f}".replace("-", "−"))
    out["p1_primary"]["mde_pts"] = f"{100 * rob['mde_80pct_power']:.1f}"
    comp = json.loads((RESULTS / "census" / "comparability.json").read_text())
    antrag = next(e for e in comp["type"]["ambiguous_examples"] if e["label"] == "antrag")
    out["antrag_concepts"] = len(antrag["concepts"])
    p = RESULTS / "report" / "p2_numbers.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
