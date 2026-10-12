"""POST HOC (12 Oct 2026; proposed in review; not pre-registered): P2's Apertus pointer against the no-model baseline of
P2's results table, the latest printed date on documents OPD types as answers (eval/baselines.py
`latest_date_on_answer_docs_only`; 44/62 exact, 18/29 answer dates; the post hoc keyword rule,
results/eval/p2_posthoc_keyword.json, is exact on 45/62 and finds 16/29). No registered decision depends on this file. No
model call, no network: the committed P2 predictions (results/eval2/p2__<build>.json), labels and document metadata.

  * exact accuracy of both arms and the paired difference on all 62 documents and on the 29 with a gold answer date:
    exact McNemar on the discordant documents and a parliament-cluster percentile bootstrap of the accuracy difference
    (eval.posthoc_r6.doc_level_block: B = 10,000, seed 20261011, the method of the P2-H2 cluster interval; shown to 3
    decimals rounded outward);
  * the documents the pointer gets right and the baseline does not, by OPD's document type: on a document OPD types
    as an intervention the baseline returns null by construction.

    PYTHONPATH=src:. python -m eval.gold2.posthoc_best_baseline   -> results/eval2/p2_posthoc_best_baseline.json
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter

from eval import posthoc_r6 as R6
from gegenprobe.paths import DATA, RESULTS

OUT = RESULTS / "eval2" / "p2_posthoc_best_baseline.json"
BASE = "latest_date_on_answer_docs_only"
LABEL = ("POST HOC (12 Oct 2026; proposed in review; not pre-registered): P2 pointer vs the latest date on answer-typed "
         "documents, the no-model baseline of P2's results table; no registered decision depends on this file")


def rows() -> list[dict]:
    dtype = {d["doc_id"]: d["dtype"] for d in map(json.loads, open(DATA / "gold2" / "p2_docs.jsonl"))}
    out = []
    for r in R6._p12_rows("P2"):
        dd = r["doc_dates"]
        r[BASE] = (max(dd) if dd else None) if dtype[r["doc_id"]] == "answer" else None
        r["dtype"] = dtype[r["doc_id"]]
        out.append(r)
    return out


def _outward(ci: list[float], nd: int = 3) -> str:
    """The interval to `nd` decimals, rounded outward (lower bound down, upper bound up): never narrower than computed."""
    f = 10 ** nd
    return f"[{math.floor(ci[0] * f) / f:.{nd}f}, {math.ceil(ci[1] * f) / f:.{nd}f}]"


def compute() -> dict:
    rs = rows()
    blk = R6.doc_level_block(rs, ["pointer", BASE], [("pointer", BASE),
                                                     ("pointer", BASE, lambda r: r["gold"] is not None, "answered")])
    answered = [r for r in rs if r["gold"] is not None]
    wins = [r for r in answered if R6._ok(r["pointer"], r) and not R6._ok(r[BASE], r)]
    losses = [r for r in answered if R6._ok(r[BASE], r) and not R6._ok(r["pointer"], r)]
    found = {a: sum(R6._ok(r[a], r) for r in answered) for a in ("pointer", BASE)}
    p_all = blk["paired"][f"pointer vs {BASE}"]
    p_ans = blk["paired"][f"pointer vs {BASE} (answered)"]
    return dict(
        label=LABEL,
        method="eval.posthoc_r6.doc_level_block (strict outcome; exact McNemar; parliament-cluster percentile bootstrap, "
               f"B = {R6.B_BOOT}, seed {R6.SEED})",
        n=len(rs), n_answered=len(answered), n_parliaments=blk["n_parliaments"],
        arms=blk["arms"], answer_dates_found={a: [k, len(answered)] for a, k in found.items()},
        paired=blk["paired"],
        answered_wins_by_dtype=dict(Counter(r["dtype"] for r in wins)),
        answered_losses_by_dtype=dict(Counter(r["dtype"] for r in losses)),
        display=dict(
            exact=f"{blk['arms']['pointer']['exact'][0]}/{len(rs)} vs {blk['arms'][BASE]['exact'][0]}/{len(rs)}",
            answer_dates=f"{found['pointer']}/{len(answered)} vs {found[BASE]}/{len(answered)}",
            discordant=f"{p_all['a_only']} vs {p_all['b_only']}",
            mcnemar_p=f"{p_all['mcnemar_exact_p']:.4f}",
            cluster95=_outward(p_all["cluster_bootstrap95"]),
            answered_discordant=f"{p_ans['a_only']} vs {p_ans['b_only']}",
            answered_wins_on_intervention_typed=sum(r["dtype"] == "intervention" for r in wins),
        ),
        note="on documents OPD types as interventions the baseline returns null by construction, so part of the "
             "pointer's edge over it rests on OPD's document typing",
    )


def main() -> dict:
    r = compute()
    OUT.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return r


if __name__ == "__main__":
    print(json.dumps(main()["display"], indent=1))
    sys.exit(0)
