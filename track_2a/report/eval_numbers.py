"""Display-ready numbers for the held-out evaluation (percent intervals, formatted statistics), derived only from committed
results files, so claims.tsv can trace every number the report, README and form notes print.

    python -m report.eval_numbers   -> results/report/eval_numbers.json
"""
from __future__ import annotations

import json

from gegenprobe.paths import RESULTS

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
ARMS = ("rules", "pointer", "cascade", "naive_plain", "naive_null")


def pct(ci: list[float]) -> list[float]:
    return [round(100 * ci[0], 1), round(100 * ci[1], 1)]


def main() -> dict:
    res = json.loads((RESULTS / "eval" / f"heldout__{BUILD}.json").read_text())
    hyp = json.loads((RESULTS / "eval" / f"hypotheses__{BUILD}.json").read_text())
    curve = json.loads((RESULTS / "eval" / "posthoc" / "theta_curve.json").read_text())["table"]
    ocr = json.loads((RESULTS / "eval" / "posthoc" / "ocr_it_prompt.json").read_text())["arms"]
    out: dict = dict(build=BUILD, arms={})
    for a in ARMS:
        s = res["arms"][a]["strict"]["ALL"]
        out["arms"][a] = dict(exact=s["exact"], n=s["n"], exact_ci_pct=pct(s["exact_ci"]), correct=s["correct"],
                              correct_null=s["correct_null"], false_null=s["false_null"], misattributed=s["misattributed"],
                              fabricated=s["fabricated"], invented_on_null=s["invented_on_null"], n_gold_null=s["n_gold_null"],
                              n_gold_value=s["n_gold_value"], invented_on_null_ci_pct=pct(s["invented_on_null_ci"]),
                              lenient_exact=res["arms"][a]["lenient"]["ALL"]["exact"])
    out["auroc_str"] = f"{hyp['H3']['auroc']:.3f}"
    out["h2_p_primary_str"] = f"{hyp['H2']['primary_fr_it_ocr']['p']:.2f}"
    out["h2_p_pooled_str"] = f"{hyp['H2']['secondary_pooled_all']['p']:.2f}"
    best = [r for r in curve if r["exact"] == max(x["exact"] for x in curve)]
    near0 = [r for r in curve if 0 <= r["theta"] <= 2.5]
    out["posthoc"] = dict(best_exact=best[0]["exact"], best_theta=best[0]["theta"],
                          theta0_25_exact=[min(r["exact"] for r in near0), max(r["exact"] for r in near0)],
                          theta0_25_on_null=max(r["invented_on_null"] for r in near0),
                          ocr_pointer_de=ocr["pointer_de_frozen"]["exact"], ocr_pointer_it=ocr["pointer_it"]["exact"],
                          ocr_cascade_it=ocr["cascade_it"]["exact"], ocr_n=ocr["pointer_it"]["n"])
    p = RESULTS / "report" / "eval_numbers.json"
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
