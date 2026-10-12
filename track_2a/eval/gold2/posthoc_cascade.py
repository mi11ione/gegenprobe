"""POST HOC (12 Oct 2026; proposed in review; not pre-registered): P2's Apertus pointer against a model-free cascade, the
registered rules first and, where they return no value, the reviewer's keyword+cue rule; and the whole ladder of P2's
model-free baselines next to the pointer. No registered decision depends on this file. No model call, no network, no
document text: committed results and per-document dates only.

    PYTHONPATH=src:. python -m eval.gold2.posthoc_cascade   -> results/eval/p2_posthoc_cascade.json

Why: the composite (46/62; eval/gold2/posthoc_composite.py) was called the strongest model-free rule, but the
keyword+cue rule in the same file scores 47/62 alone, and chaining the registered rules arm in front of it (the same
construction as the P1 model-free cascade: rules first, then a fallback) reaches 49/62. A reviewer (round 20) proposed
this cascade; it is implemented here exactly as proposed, nothing tuned by the team.

Arms (every one scored with the frozen strict outcome, eval.score.outcome via eval.baselines._score / eval.posthoc_r6._ok):
  rules                            the registered rules arm (results/eval2/p2__<build>.json `rules`)
  latest_date_on_answer_docs_only  the results-table baseline: latest printed date on documents OPD types as answers
  keyword                          eval/gold2/posthoc_keyword.py's rule alone (answer-typed documents only)
  composite                        eval/gold2/posthoc_composite.py (latest date on answers, cue on interventions)
  keyword_cue                      eval/gold2/posthoc_composite.py's second arm: the keyword rule (posthoc_keyword.pred) on
                                   answer-typed documents, its cue part (cue_only) on intervention-typed ones
  rules_then_keyword_cue           THE CASCADE: the rules' value where they return one, else keyword_cue
  rules_then_keyword, rules_then_composite   the same construction with the other two fallbacks (sensitivity)
  pointer                          the registered Apertus closed-set pointer (θ = 10.40)
The per-document dates of keyword, composite and keyword_cue are read from results/eval/p2_posthoc_composite.json
(`per_doc`, dates only), where eval.gold2.posthoc_composite derived them from the sha256-checked PDFs.

Paired with the pointer: eval.posthoc_r3._pair (exact McNemar, two-sided, on all 62, the 29 with a gold date and the 33
without; per parliament the sign test and the exact cluster permutation) and eval.posthoc_r6.doc_level_block (the
parliament-cluster percentile bootstrap of the accuracy difference, B = 10,000, seed 20261011).
"""

from __future__ import annotations

import json
import math
import sys

from eval import baselines as BL
from eval import posthoc_r3 as R3
from eval import posthoc_r6 as R6
from gegenprobe.paths import DATA, RESULTS

OUT = RESULTS / "eval" / "p2_posthoc_cascade.json"
COMPOSITE = RESULTS / "eval" / "p2_posthoc_composite.json"
LABEL = ("POST HOC (12 Oct 2026; proposed in review; not pre-registered): P2 pointer vs a model-free cascade (registered "
         "rules, then the reviewer's keyword+cue rule) and the ladder of P2's model-free baselines; implemented as "
         "proposed, not tuned by the team; no registered decision depends on this file")
BASE = "latest_date_on_answer_docs_only"
CASCADE = "rules_then_keyword_cue"
# the ladder, weakest to strongest model-free baseline, then the pointer
LADDER = ("rules", BASE, "keyword", "composite", "keyword_cue", CASCADE)
SENSITIVITY = ("rules_then_keyword", "rules_then_composite")
ARMS = LADDER + SENSITIVITY + ("cascade", "pointer")
NAMES = {
    "rules": "registered rules arm alone",
    BASE: "latest printed date on answer-typed documents (the results-table baseline)",
    "keyword": "keyword rule alone (eval/gold2/posthoc_keyword.py; answer-typed documents only)",
    "composite": "composite (latest date on answers, the keyword rule's cue on interventions)",
    "keyword_cue": "keyword+cue (the keyword rule on answers, its cue on interventions)",
    CASCADE: "cascade: registered rules, then keyword+cue",
    "rules_then_keyword": "rules, then the keyword rule alone (sensitivity)",
    "rules_then_composite": "rules, then the composite (sensitivity)",
    "cascade": "registered cascade: rules, then the Apertus pointer",
    "pointer": "Apertus closed-set pointer (registered P2 arm)",
}


def _outward(ci: list[float], nd: int = 3) -> str:
    f = 10 ** nd
    return f"[{math.floor(ci[0] * f) / f:.{nd}f}, {math.ceil(ci[1] * f) / f:.{nd}f}]"


def rows() -> list[dict]:
    """P2 rows (registered results and labels) with every arm's predicted date; no text."""
    comp = {p["doc_id"]: p for p in json.loads(COMPOSITE.read_text(encoding="utf-8"))["per_doc"]}
    dtype = {d["doc_id"]: d["dtype"] for d in map(json.loads, open(DATA / "gold2" / "p2_docs.jsonl", encoding="utf-8"))}
    res = json.loads((RESULTS / "eval2" / f"p2__{R6.BUILD}.json").read_text(encoding="utf-8"))
    rules_value = {d["doc_id"]: d["rules"]["value"] for d in res["per_doc"]}
    out = R6._p12_rows("P2")
    for r in out:
        p = comp[r["doc_id"]]
        assert p["dtype"] == dtype[r["doc_id"]], r["doc_id"]
        assert r["rules"] == rules_value[r["doc_id"]], r["doc_id"]  # the registered rules value, as committed
        dd = r["doc_dates"]
        r["dtype"] = p["dtype"]
        r[BASE] = (max(dd) if dd else None) if p["dtype"] == "answer" else None
        r["keyword"], r["composite"], r["keyword_cue"] = p["keyword"], p["composite"], p["keyword_cue"]
        r[CASCADE] = r["rules"] if r["rules"] is not None else p["keyword_cue"]
        r["rules_then_keyword"] = r["rules"] if r["rules"] is not None else p["keyword"]
        r["rules_then_composite"] = r["rules"] if r["rules"] is not None else p["composite"]
    return out


def compute() -> dict:
    rs = rows()
    rows3 = [dict(doc_id=r["doc_id"], body=r["body"], gold=r["gold"], lenient=r["lenient"], doc_dates=r["doc_dates"],
                  pred={a: r[a] for a in ARMS}) for r in rs]
    scores = {a: BL._score([dict(gold=r["gold"], lenient=r["lenient"], doc_dates=r["doc_dates"], pred=r["pred"][a])
                            for r in rows3]) for a in ARMS}
    answered = lambda r: r["gold"] is not None  # noqa: E731
    others = [a for a in ARMS if a != "pointer"]
    blk = R6.doc_level_block(rs, list(ARMS), [("pointer", a) for a in others]
                             + [("pointer", a, answered, "answered") for a in others])
    mcn = {a: R3._pair(rows3, "pointer", a) for a in others}
    ladder = []
    for a in LADDER + ("pointer",):
        s = scores[a]
        row = dict(arm=a, name=NAMES[a], exact=[s["exact"], s["n"]], answer_dates_found=s["value_recall"],
                   answerless_dated=s["values_on_gold_null"], printed_nowhere=s["fabricated"])
        if a != "pointer":
            m, c, ca = mcn[a], blk["paired"][f"pointer vs {a}"], blk["paired"][f"pointer vs {a} (answered)"]
            row.update(
                pointer_only=m["all"]["pointer_only"], baseline_only=m["all"][f"{a}_only"],
                mcnemar_p=m["all"]["p_mcnemar_exact"], mcnemar_p_str=m["all"]["p_str"],
                answered_pointer_only=m["gold_value"]["pointer_only"], answered_baseline_only=m["gold_value"][f"{a}_only"],
                answered_mcnemar_p_str=m["gold_value"]["p_str"],
                parliaments_favour=[m["bodies"]["favour_pointer"], m["bodies"][f"favour_{a}"]],
                parliament_permutation_p_str=m["bodies"]["cluster_permutation_p_str"],
                cluster95=_outward(c["cluster_bootstrap95"]), cluster95_excludes_0=c["cluster_interval_excludes_0"],
                answered_cluster95=_outward(ca["cluster_bootstrap95"]),
                answered_cluster95_excludes_0=ca["cluster_interval_excludes_0"])
        ladder.append(row)
    c = next(x for x in ladder if x["arm"] == CASCADE)
    sp = scores["pointer"]
    return dict(
        label=LABEL,
        proposed_by="proposed in review (round-20 skeptical-ML review); construction as the reviewer wrote it, run by the "
                    "team",
        method=__doc__.split("Paired with the pointer:")[1].strip(),
        n=len(rows3), n_answered=sum(map(answered, rows3)), n_parliaments=blk["n_parliaments"],
        arm_names=NAMES, arms=scores, ladder=ladder,
        mcnemar=mcn, cluster_bootstrap=blk["paired"], cluster_bootstrap_arms=blk["arms"],
        rules_returned_value=sum(r["rules"] is not None for r in rs),
        display=dict(
            cascade_exact=f"{c['exact'][0]}/{c['exact'][1]}", cascade_answer_dates="{}/{}".format(*c["answer_dates_found"]),
            cascade_answerless_dated="{}/{}".format(*c["answerless_dated"]),
            pointer_exact=f"{sp['exact']}/{sp['n']}", pointer_answer_dates="{}/{}".format(*sp["value_recall"]),
            discordant=f"{c['pointer_only']} vs {c['baseline_only']}", mcnemar_p=c["mcnemar_p_str"],
            answered_discordant=f"{c['answered_pointer_only']} vs {c['answered_baseline_only']}",
            answered_mcnemar_p=c["answered_mcnemar_p_str"],
            parliaments_favour=f"{c['parliaments_favour'][0]} vs {c['parliaments_favour'][1]}",
            parliament_permutation_p=c["parliament_permutation_p_str"],
            cluster95=c["cluster95"], cluster95_excludes_0=c["cluster95_excludes_0"],
            answered_cluster95=c["answered_cluster95"],
            ladder_exact={x["arm"]: f"{x['exact'][0]}/{x['exact'][1]}" for x in ladder},
            ladder_answer_dates={x["arm"]: "{}/{}".format(*x["answer_dates_found"]) for x in ladder},
            ladder_mcnemar_p={x["arm"]: x["mcnemar_p_str"] for x in ladder if x["arm"] != "pointer"},
            ladder_cluster95={x["arm"]: x["cluster95"] for x in ladder if x["arm"] != "pointer"},
        ),
        reading=("Against the strongest model-free baseline built from parts already in the repository (registered rules, "
                 "then the keyword+cue rule) the pointer's exact-match lead is 53 vs 49 of 62 (discordant 9 vs 5, exact "
                 "McNemar p = {p}; parliament-cluster 95% interval {ci}, which includes 0), and 24 vs 21 of 29 answer "
                 "dates found. Post hoc, one review's construction; it does not change any registered result.").format(
                     p=c["mcnemar_p_str"], ci=c["cluster95"]),
    )


def main(argv: list[str]) -> int:
    out = compute()
    blob = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == blob
        print(OUT.name, "matches" if same else "DIFFERS from a recompute")
        return 0 if same else 1
    OUT.write_text(blob, encoding="utf-8")
    print(json.dumps(out["display"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
