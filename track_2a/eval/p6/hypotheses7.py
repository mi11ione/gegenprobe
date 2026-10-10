"""P6 hypotheses (eval/prereg7/PREREG7.md), computed from results/p6/p6__<build>.json and data/p6/p6_labels.jsonl.
Correctness per document is the frozen eval/score.py `outcome` (strict; lenient reported). No threshold is chosen here.

    python -m eval.p6.hypotheses7 publicai_swiss-ai_apertus-v1.5-8b      -> results/p6/hypotheses7__<build>.json
"""

from __future__ import annotations

import collections
import json
import math
import sys
from pathlib import Path

from eval.p6 import sample as S
from eval.score import outcome
from gegenprobe.paths import RESULTS
from gegenprobe.stats import auroc, wilson

ARMS = ["rules", "v1", "cascade_v1", "v2", "cascade_v2", "free_null", "free_plain", "free_guided",
        "latest_printed_date", "latest_on_answer_typed", "always_null"]
ALPHA = 0.05
NULL_BAR = 0.15  # H2: Wilson 95% upper bound of v2 values on answerless documents


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def sign_test(pos: int, neg: int) -> float:
    return mcnemar_exact(pos, neg)


def holm(ps: dict) -> dict:
    items = sorted(ps.items(), key=lambda kv: kv[1])
    m, out, run = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def ok(pred, r, strict=True) -> bool:
    return outcome(pred, r["gold"], set(r["doc_dates"]), r.get("lenient"), strict) in ("correct", "correct_null")


def arm_block(rows: list[dict], a: str, strict=True) -> dict:
    val = [r for r in rows if r["gold"] is not None]
    nul = [r for r in rows if r["gold"] is None]
    ex = sum(ok(r[a], r, strict) for r in rows)
    found = sum(r[a] == r["gold"] for r in val)
    oc = collections.Counter(outcome(r[a], r["gold"], set(r["doc_dates"]), r.get("lenient"), strict) for r in rows)
    on_null = sum(r[a] is not None for r in nul)
    return dict(exact=[ex, len(rows)], exact_ci=list(wilson(ex, len(rows))), dates_found=[found, len(val)],
                dates_found_ci=list(wilson(found, len(val))), wrong_printed_date=oc["misattributed"],
                fabricated=oc["fabricated"], missed=oc["false_null"], dated_answerless=[on_null, len(nul)],
                dated_answerless_ci=list(wilson(on_null, len(nul))))


def paired(rows, a, b, sel=None) -> dict:
    rs = rows if sel is None else [r for r in rows if sel(r)]
    x = sum(ok(r[a], r) and not ok(r[b], r) for r in rs)
    y = sum(ok(r[b], r) and not ok(r[a], r) for r in rs)
    return dict(a=a, b=b, a_only=x, b_only=y, p=mcnemar_exact(x, y), n=len(rs))


def per_body(rows, a, b) -> dict:
    by = collections.defaultdict(list)
    for r in rows:
        by[r["body"]].append(r)
    diff = {k: sum(ok(r[a], r) for r in v) - sum(ok(r[b], r) for r in v) for k, v in sorted(by.items())}
    pos, neg = sum(d > 0 for d in diff.values()), sum(d < 0 for d in diff.values())
    return dict(per_body_diff=diff, a_better=pos, b_better=neg, ties=len(diff) - pos - neg, p=sign_test(pos, neg))


def flatten(res: dict, labels: dict) -> list[dict]:
    rows = []
    for d in res["per_doc"]:
        lab = labels[d["doc_id"]]
        row = dict(doc_id=d["doc_id"], body=d["body"], cell=d["cell"], lang=d["lang"], dtype=d["dtype"],
                   gold=lab["answer_date"], lenient=lab.get("answer_date_lenient") or [], doc_dates=d["doc_dates"],
                   v2_stage=(d.get("v2") or {}).get("stage"), presence_margin=(d.get("v2") or {}).get("presence_margin"))
        for a in ARMS:
            if a == "rules":
                row[a] = d["rules"]["value"]
            elif a in d:
                row[a] = d[a]["value"]
        rows.append(row)
    return rows


def main(build: str, res_path: Path | None = None, labels_path: Path | None = None, out_path: Path | None = None) -> dict:
    res = json.loads((res_path or RESULTS / "p6" / f"p6__{build}.json").read_text())
    labels = {r["doc_id"]: r for r in map(json.loads, open(labels_path or S.LABELS))}
    rows = flatten(res, labels)
    arms_ = [a for a in ARMS if all(a in r for r in rows)]
    nul = lambda r: r["gold"] is None  # noqa: E731
    out = dict(build=build, n=len(rows), n_answered=sum(r["gold"] is not None for r in rows),
               n_answerless=sum(nul(r) for r in rows), n_bodies=len({r["body"] for r in rows}),
               underpowered=len(rows) < 60,
               arms={a: arm_block(rows, a) for a in arms_}, arms_lenient={a: arm_block(rows, a, False) for a in arms_})
    if "v2" not in arms_:
        return out
    # H1 primary: v2 vs registered free prompting (null allowed, corrected parser), exact accuracy
    h1 = paired(rows, "v2", "free_null")
    h1b = per_body(rows, "v2", "free_null")
    out["H1_v2_vs_free_null"] = dict(doc_level=h1, per_parliament=h1b,
                                     holds=h1["p"] < ALPHA and h1["a_only"] > h1["b_only"],
                                     holds_across_parliaments=h1b["p"] < ALPHA and h1b["a_better"] > h1b["b_better"])
    # H2: v2 dates few answerless documents (absolute bar) and no more than v1 and free_null
    k, n = out["arms"]["v2"]["dated_answerless"]
    lo, hi = wilson(k, n)
    k1, k2 = out["arms"]["v1"]["dated_answerless"][0], out["arms"]["free_null"]["dated_answerless"][0]
    out["H2_answerless"] = dict(v2=[k, n], wilson95=[lo, hi], v1=k1, free_null=k2,
                                paired_vs_v1_on_answerless=paired(rows, "v2", "v1", nul),
                                paired_vs_free_null_on_answerless=paired(rows, "v2", "free_null", nul),
                                holds=hi <= NULL_BAR and k <= k1 and k <= k2)
    # H3: v2 vs v1 exact accuracy
    h3 = paired(rows, "v2", "v1")
    out["H3_v2_vs_v1"] = dict(doc_level=h3, per_parliament=per_body(rows, "v2", "v1"),
                              holds=h3["p"] < ALPHA and h3["a_only"] > h3["b_only"])
    out["holm"] = holm({"H1": h1["p"], "H3": h3["p"]})
    # secondary, reported without a decision
    out["S1_v2_vs_free_guided"] = dict(doc_level=paired(rows, "v2", "free_guided"),
                                       per_parliament=per_body(rows, "v2", "free_guided"))
    out["S2_cascade_v2_vs_cascade_v1"] = paired(rows, "cascade_v2", "cascade_v1")
    out["S3_cascade_v2_vs_rules_on_answered"] = paired(rows, "cascade_v2", "rules", lambda r: r["gold"] is not None)
    pos = [r["presence_margin"] for r in rows if nul(r) and r["presence_margin"] is not None
           and math.isfinite(r["presence_margin"])]
    neg = [r["presence_margin"] for r in rows if not nul(r) and r["presence_margin"] is not None
           and math.isfinite(r["presence_margin"])]
    out["S4_presence_auroc"] = dict(auroc=auroc(pos, neg) if pos and neg else None, n_answerless=len(pos), n_answered=len(neg))
    out["S5_v2_stage_counts"] = dict(collections.Counter(r["v2_stage"] for r in rows))
    out["S6_per_language"] = {lg: {a: arm_block([r for r in rows if r["lang"] == lg], a)["exact"] for a in arms_}
                              for lg in sorted({r["lang"] for r in rows})}
    out["S7_fabricated"] = {a: out["arms"][a]["fabricated"] for a in arms_}
    p = out_path or RESULTS / "p6" / f"hypotheses7__{build}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=1)[:5000])
