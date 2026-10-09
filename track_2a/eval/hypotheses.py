"""Pre-registered hypotheses H1-H4 (eval/prereg/PREREG.md) computed from the frozen per-document held-out rows.
Reads results/eval/heldout__<build>.json, writes results/eval/hypotheses__<build>.json. No model calls, no new scoring rules:
correctness per document is eval/score.py's `outcome` (strict).

    python -m eval.hypotheses publicai_swiss-ai_apertus-v1.5-8b
"""

from __future__ import annotations

import collections
import json
import math
import sys

from eval.score import outcome
from gegenprobe.paths import RESULTS
from gegenprobe.stats import auroc, wilson

FR_IT_OCR = ("fr_canton", "fr_commune", "it_canton", "it_commune", "ocr_ti")


def correct(r: dict, arm: str) -> bool:
    return outcome(r[arm].get("value"), r["gold"], set(r["doc_dates"]), r.get("lenient"), True) in ("correct", "correct_null")


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: binomial(b + c, 1/2) on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * p)


def main(build: str) -> dict:
    d = json.loads((RESULTS / "eval" / f"heldout__{build}.json").read_text())
    rows = d["per_doc"]
    out: dict = dict(build=build, theta=d["theta"], n=len(rows))

    # H1: cascade values on gold-null documents, per cell (<= 1) and pooled (Wilson upper bound <= 10%)
    per_cell = collections.Counter()
    nulls = collections.Counter()
    for r in rows:
        if r["gold"] is None:
            nulls[r["cell"]] += 1
            per_cell[r["cell"]] += r["cascade"].get("value") is not None
    k, n = sum(per_cell.values()), sum(nulls.values())
    lo, hi = wilson(k, n)
    naive_k = sum(
        r["gold"] is None
        and r["naive_plain"].get("date") not in (None,)
        and not str(r["naive_plain"]["date"]).startswith("unparseable")
        for r in rows
    )
    out["H1"] = dict(
        per_cell={c: [per_cell[c], nulls[c]] for c in sorted(nulls)},
        max_per_cell=max(per_cell.values()),
        pooled=[k, n],
        pooled_ci=[lo, hi],
        pass_per_cell=max(per_cell.values()) <= 1,
        pass_pooled=hi <= 0.10,
        naive_plain_values_on_null=[naive_k, n],
    )
    out["H1"]["pass"] = out["H1"]["pass_per_cell"] and out["H1"]["pass_pooled"]

    # H2: cascade vs rules, correct-or-not per document, pooled FR + IT + OCR, exact McNemar two-sided alpha 0.05
    def mcn(sel):
        b = sum(correct(r, "cascade") and not correct(r, "rules") for r in sel)
        c = sum(correct(r, "rules") and not correct(r, "cascade") for r in sel)
        return dict(
            n=len(sel),
            cascade_correct=sum(correct(r, "cascade") for r in sel),
            rules_correct=sum(correct(r, "rules") for r in sel),
            cascade_only=b,
            rules_only=c,
            p=mcnemar_exact(b, c),
        )

    prim = mcn([r for r in rows if r["cell"] in FR_IT_OCR])
    out["H2"] = dict(
        primary_fr_it_ocr=prim,
        branch="A" if (prim["p"] < 0.05 and prim["cascade_only"] > prim["rules_only"]) else "B",
        secondary_pooled_all=mcn(rows),
    )
    b = sum(correct(r, "pointer") and not correct(r, "rules") for r in rows)
    c = sum(correct(r, "rules") and not correct(r, "pointer") for r in rows)
    out["H2"]["secondary_pointer_vs_rules_all"] = dict(pointer_only=b, rules_only=c, p=mcnemar_exact(b, c))

    # H3: AUROC of the pointer null margin, gold-null vs gold-value (documents with no date candidate have no margin)
    pos = [r["pointer"]["margin"] for r in rows if r["gold"] is None and r["pointer"].get("n_cands")]
    neg = [r["pointer"]["margin"] for r in rows if r["gold"] is not None and r["pointer"].get("n_cands")]
    a = auroc(pos, neg)
    out["H3"] = dict(
        auroc=a,
        n_null=len(pos),
        n_value=len(neg),
        no_candidates=sum(not r["pointer"].get("n_cands") for r in rows),
        pass_=a >= 0.80,
    )

    # H4: cascade wrong (misattributed or fabricated) on Apertus-decided FR/IT values
    sel = [
        r for r in rows if r["cell"][:2] in ("fr", "it") and r["cascade"].get("route") == "apertus" and r["cascade"].get("value")
    ]
    wrong = [r["doc_id"] for r in sel if not correct(r, "cascade")]
    out["H4"] = dict(
        apertus_decided_fr_it_values=len(sel), wrong=len(wrong), wrong_ids=wrong, triggers_posthoc_curve=len(wrong) > 1
    )

    # model share: values (non-null) the cascade took from Apertus / all non-null cascade values
    vals = [r for r in rows if r["cascade"].get("value")]
    out["model_share"] = dict(
        apertus=sum(r["cascade"].get("route") == "apertus" for r in vals),
        values=len(vals),
        apertus_decisions_incl_nulls=sum(r["cascade"].get("route") == "apertus" for r in rows),
        n=len(rows),
    )
    p = RESULTS / "eval" / f"hypotheses__{build}.json"
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1))
