"""P4 hypotheses exactly as registered in eval/prereg4/PREREG4.md, applied to the frozen P4 score and prediction files.
Written after the run; it only applies the registered definitions.

  P4-H1 segmentation: rules item recall >= 0.90            P4-H2 types: rules type accuracy >= 0.85 on matched items
  P4-H3 (primary) decisions: review decision recall > rules_only (exact McNemar on items with a gold decision,
        alpha 0.05) with invented decisions at a Wilson upper bound <= 15%
  P4-H4 meeting date: the derived meeting date equals the gold meeting date on every held-out meeting
        (the derived date is the one embedded in each virtual affair number, 'V <date> - <no>').

    python -m eval.gold4.hypotheses4 publicai_swiss-ai_apertus-v1.5-8b   -> results/eval4/hypotheses4__<build>.json
"""
from __future__ import annotations

import collections
import json
import math
import re
import sys

from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import wilson


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def main(build: str) -> dict:
    sc = json.loads((RESULTS / "eval4" / f"p4_heldout__{build}__score.json").read_text())
    pred = json.loads((RESULTS / "eval4" / f"p4_heldout__{build}.json").read_text())
    gold = [json.loads(x) for x in open(DATA / "gold4" / "p4_heldout_labels.jsonl")]
    r, v = sc["arms"]["rules_only"], sc["arms"]["review"]
    out = dict(build=build)
    k, n = r["segmentation_recall"][:2]
    out["H1"] = dict(recall=[k, n], ci=list(wilson(k, n)), precision=r["segmentation_precision"][:2], holds=k / n >= 0.90)
    k, n = r["type_accuracy"][:2]
    out["H2"] = dict(accuracy=[k, n], ci=list(wilson(k, n)), holds=k / n >= 0.85, review=v["type_accuracy"][:2])
    # H3: paired per gold-decision item, matched by meeting + agenda number
    gdec = {(g["meeting"], g["no"]): g["decision"] for g in gold if g["decision"] not in (None, "none", "not_applicable")}
    by = collections.defaultdict(dict)
    for row in pred["rows"]:
        by[row["arm"]][(row["meeting"], row["no"])] = row.get("decision")
    b = c = 0
    for key, gd in gdec.items():
        ok_r, ok_v = by["rules_only"].get(key) == gd, by["review"].get(key) == gd
        b += ok_v and not ok_r
        c += ok_r and not ok_v
    inv_k, inv_n = v["invented_decisions"][:2]
    p = mcnemar_exact(b, c)
    out["H3"] = dict(review_recall=v["decision_recall"][:2], rules_recall=r["decision_recall"][:2], review_only=b,
                     rules_only=c, p=p, invented=[inv_k, inv_n], invented_upper=wilson(inv_k, inv_n)[1],
                     holds=(p < 0.05 and b > c and wilson(inv_k, inv_n)[1] <= 0.15))
    # H4: derived meeting date per meeting
    dates = collections.defaultdict(set)
    for row in pred["rows"]:
        m = re.match(r"V (\d{4}-\d{2}-\d{2})", row.get("number") or "")
        dates[row["meeting"]].add(m.group(1) if m else None)
    meetings = sorted({g["meeting"] for g in gold})
    ok = [m for m in meetings if dates.get(m) == {m}]
    out["H4"] = dict(correct=len(ok), n=len(meetings), wrong=[m for m in meetings if m not in ok], holds=len(ok) == len(meetings))
    path = RESULTS / "eval4" / f"hypotheses4__{build}.json"
    path.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1))
