"""P3 hypotheses exactly as registered in eval/prereg3/PREREG3.md (thresholds fixed there), from the frozen P3 results file
and the P3 labels. Written after the run; it only applies the registered definitions to the per-affair rows.

    python -m eval.gold3.hypotheses3 publicai_swiss-ai_apertus-v1.5-8b   -> results/eval3/hypotheses3__<build>.json
"""
from __future__ import annotations

import json
import sys

from eval.gold3.score3 import REC_NULL, SINGLE, gold_value, same
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import wilson

H2_FIELDS = ("number", "affair_type", "submitter", "submitted")
H3_FIELDS = ("submitter", "submitted", "addressed_body", "affair_type", "answer_date", "recommendation")
DOC_ROUTE = ("addressed_body", "submitted", "answer_date", "recommendation", "decision_number")


def _pv(p, arm, f):
    v = p["arms"][arm].get(f)
    return None if (f == "recommendation" and v in REC_NULL) else v


def main(build: str) -> dict:
    res = json.loads((RESULTS / "eval3" / f"p3__{build}.json").read_text())
    gold = {g["affair_id"]: g for g in map(json.loads, open(DATA / "gold3" / "p3_labels.jsonl"))}
    rows = [p for p in res["per_affair"] if p["affair_id"] in gold]
    out: dict = dict(build=build, n=len(rows))

    # H1: per field, C accuracy with Wilson CI; tiers
    h1 = {}
    for f in SINGLE:
        k = n = unprinted = 0
        for p in rows:
            g = gold[p["affair_id"]]
            gv, pv = gold_value(f, g), _pv(p, "C", f)
            if gv is None:
                unprinted += pv is not None
                continue
            n += 1
            k += pv is not None and same(f, pv, gv, g.get(f + "_lenient") or ())
        lo, hi = wilson(k, n)
        guard = (unprinted <= 1) if f in DOC_ROUTE else True
        tier = ("extractable unattended" if lo >= 0.80 and guard else "partial" if lo >= 0.50 else "not yet") if n else "no gold"
        h1[f] = dict(correct=k, n=n, ci=[lo, hi], values_where_doc_prints_none=unprinted, tier=tier)
    out["H1"] = h1

    # H2: metadata (M) equals the printed value, among affairs where both exist
    h2 = {}
    for f in H2_FIELDS:
        k = n = 0
        for p in rows:
            g = gold[p["affair_id"]]
            gv, mv = gold_value(f, g), _pv(p, "M", f)
            if gv is None or mv is None:
                continue
            n += 1
            k += same(f, mv, gv, g.get(f + "_lenient") or ())
        h2[f] = dict(agree=k, n=n, ci=list(wilson(k, n)))
    out["H2"] = h2

    # H3: Apertus on the residue: (affair, field) pairs that C leaves open
    rec_k = rec_n = prec_k = prec_n = 0
    per_field = {}
    for f in H3_FIELDS:
        fk = fn = fs = fc = 0
        for p in rows:
            if _pv(p, "C", f) is not None:
                continue
            g = gold[p["affair_id"]]
            gv, av = gold_value(f, g), _pv(p, "CA", f)
            ok = av is not None and gv is not None and same(f, av, gv, g.get(f + "_lenient") or ())
            if gv is not None:
                fn += 1
                fk += ok
            if av is not None:
                fs += 1
                fc += ok
        per_field[f] = dict(recall=[fk, fn], precision=[fc, fs])
        rec_k, rec_n, prec_k, prec_n = rec_k + fk, rec_n + fn, prec_k + fc, prec_n + fs
    r_lo = wilson(rec_k, rec_n)[0]
    p_lo = wilson(prec_k, prec_n)[0]
    a, b = r_lo >= 0.50, p_lo >= 0.70
    out["H3"] = dict(recall=[rec_k, rec_n], recall_ci=list(wilson(rec_k, rec_n)), precision=[prec_k, prec_n],
                     precision_ci=list(wilson(prec_k, prec_n)), recall_holds=a, precision_holds=b, per_field=per_field,
                     decision=("review suggestions recommended" if a and b else
                               "recommended with a reviewer gate" if a else "pointer not recommended beyond the answer date"))

    # H4: R and C on seen vs unseen bodies (descriptive; the scorer's split)
    out["H4"] = res["scores"]["by_rules_coverage"]
    p = RESULTS / "eval3" / f"hypotheses3__{build}.json"
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1)[:5000])
