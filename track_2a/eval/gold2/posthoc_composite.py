"""POST HOC (12 Oct 2026; proposed in review; not pre-registered): P2's Apertus pointer against a composite no-model
baseline that is not null by construction on intervention-typed documents. No registered decision depends on this file.
No model call; no network unless a cached PDF is missing (then the project's fetch path only, as in
eval.gold2.posthoc_keyword.doc_text: robots fail closed, sha256 checked).

Why: P2's results-table baseline, the latest printed date on documents OPD types as answers
(`latest_date_on_answer_docs_only`, results/eval2/p2_posthoc_best_baseline.json), returns null by construction on the 31
of 62 P2 documents OPD types as interventions, and 4 of the pointer's 7 answered wins sit there. A reviewer proposed
dating those documents with the cue part of the post hoc keyword rule (eval/gold2/posthoc_keyword.py). The arms, as the
reviewer wrote them (implemented unchanged; nothing tuned by the team):

  composite        on answer-typed documents the latest printed date (the results-table baseline, unchanged); on
                   intervention-typed documents `cue_only`: the text must name a government (GOV) and an answer cue
                   (ANS), then the first date within 80 characters after a session / minutes cue (CUE); else null (no
                   latest-date fallback on interventions).
  keyword_cue      on answer-typed documents the keyword rule (eval.gold2.posthoc_keyword.pred); on intervention-typed
                   documents `cue_only` (the reviewer's second variant; secondary).

Scored like every P2 arm (eval.score.outcome, strict; eval.baselines._score), and paired with the registered pointer
(results/eval2/p2__publicai_swiss-ai_apertus-v1.5-8b.json):
  * eval.posthoc_r3._pair: exact McNemar (two-sided) on all 62, on the 29 with a gold date and on the 33 without; per
    parliament the sign test and the exact cluster permutation (joint flip per parliament);
  * eval.posthoc_r6.doc_level_block: the parliament-cluster percentile bootstrap of the accuracy difference (B = 10,000,
    seed 20261011; the method of the P2-H2 cluster interval), on all 62 and on the 29 answered.
The per-document predictions of both arms (dates only, no document text) are written to the output, so that the scores
re-derive from committed files without the PDFs (`rescore`).

    PYTHONPATH=src:. python -m eval.gold2.posthoc_composite   -> results/eval/p2_posthoc_composite.json
"""

from __future__ import annotations

import json
import math
import re
import sys

from eval import baselines as BL
from eval import posthoc_r3 as R3
from eval import posthoc_r6 as R6
from eval.gold2 import posthoc_keyword as K
from gegenprobe.paths import DATA, RESULTS

OUT = RESULTS / "eval" / "p2_posthoc_composite.json"
LABEL = ("POST HOC (12 Oct 2026; proposed in review; not pre-registered): P2 pointer vs a composite no-model baseline "
         "(latest date on answer-typed documents; the reviewer's cue-anchored date on intervention-typed documents), "
         "implemented as proposed, not tuned by the team; no registered decision depends on this file")
BASE = "latest_date_on_answer_docs_only"
ARMS = ("pointer", "composite", "keyword_cue", BASE, "keyword")


# ---------------------------------------------------------------- the reviewer's intervention-document rule, verbatim
def cue_only(t):
    if not t or not (re.search(K.GOV, t) and re.search(K.ANS, t, re.I)):
        return None
    ds = K.dates(t)
    for m in K.CUE.finditer(t):
        after = [d for p, d in ds if p >= m.end() and p - m.end() < 80]
        if after:
            return after[0]
    return None
# ---------------------------------------------------------------- end of the reviewer's rule


def composite_date(text: str, dtype: str, doc_dates: list[str]) -> str | None:
    """Answer-typed: the latest printed date (the results-table baseline); intervention-typed: cue_only."""
    if dtype == "answer":
        return max(doc_dates) if doc_dates else None
    return cue_only(text)


def keyword_cue_date(text: str, dtype: str) -> str | None:
    """Answer-typed: the keyword rule; intervention-typed: cue_only."""
    return K.pred(text) if dtype == "answer" else cue_only(text)


def predictions(texts: dict[int, str | None]) -> list[dict]:
    """Per document: doc_id, dtype and the two composite arms' dates (no text)."""
    rows = K.rows_with_keyword(texts)
    return [dict(doc_id=r["doc_id"], dtype=r["dtype"],
                 composite=composite_date(texts.get(r["doc_id"]) or "", r["dtype"], r["doc_dates"]),
                 keyword_cue=keyword_cue_date(texts.get(r["doc_id"]) or "", r["dtype"]),
                 keyword=r["pred"]["keyword"]) for r in rows]


def _outward(ci: list[float], nd: int = 3) -> str:
    f = 10 ** nd
    return f"[{math.floor(ci[0] * f) / f:.{nd}f}, {math.ceil(ci[1] * f) / f:.{nd}f}]"


def rescore(per_doc: list[dict]) -> dict:
    """Every score from the committed P2 results, labels and the per-document predictions (no PDF needed)."""
    pred = {p["doc_id"]: p for p in per_doc}
    dtype = {d["doc_id"]: d["dtype"] for d in map(json.loads, open(DATA / "gold2" / "p2_docs.jsonl"))}
    rows6 = R6._p12_rows("P2")
    for r in rows6:
        p = pred[r["doc_id"]]
        assert p["dtype"] == dtype[r["doc_id"]], r["doc_id"]
        dd = r["doc_dates"]
        r[BASE] = (max(dd) if dd else None) if p["dtype"] == "answer" else None
        r["composite"], r["keyword_cue"], r["keyword"], r["dtype"] = (p["composite"], p["keyword_cue"], p["keyword"],
                                                                       p["dtype"])
    rows3 = [dict(doc_id=r["doc_id"], body=r["body"], gold=r["gold"], lenient=r["lenient"], doc_dates=r["doc_dates"],
                  dtype=r["dtype"], pred={a: r[a] for a in ARMS}) for r in rows6]
    answered = lambda r: r["gold"] is not None  # noqa: E731
    blk = R6.doc_level_block(rows6, list(ARMS), [
        ("pointer", "composite"), ("pointer", "composite", answered, "answered"),
        ("pointer", "keyword_cue"), ("pointer", "keyword_cue", answered, "answered"),
        ("composite", BASE)])
    scores = {a: BL._score([dict(gold=r["gold"], lenient=r["lenient"], doc_dates=r["doc_dates"], pred=r["pred"][a])
                            for r in rows3]) for a in ARMS}
    interv = [r for r in rows3 if r["dtype"] == "intervention"]
    pc, pa = blk["paired"]["pointer vs composite"], blk["paired"]["pointer vs composite (answered)"]
    mc = R3._pair(rows3, "pointer", "composite")
    out = dict(
        n=len(rows3), n_answered=sum(map(answered, rows3)), n_parliaments=blk["n_parliaments"],
        n_intervention_typed=len(interv),
        intervention_typed=dict(
            n=len(interv), with_gold_date=sum(r["gold"] is not None for r in interv),
            composite_dated=sum(r["pred"]["composite"] is not None for r in interv),
            composite_right=sum(R6._ok(r["pred"]["composite"], r) for r in interv),
            baseline_right=sum(R6._ok(r["pred"][BASE], r) for r in interv),
            pointer_right=sum(R6._ok(r["pred"]["pointer"], r) for r in interv)),
        arms=scores,
        mcnemar=dict(pointer_vs_composite=mc,
                     pointer_vs_keyword_cue=R3._pair(rows3, "pointer", "keyword_cue"),
                     composite_vs_results_table_baseline=R3._pair(rows3, "composite", BASE)),
        cluster_bootstrap=blk["paired"],
        cluster_bootstrap_arms=blk["arms"],
        display=dict(
            composite_exact=f"{scores['composite']['exact']}/{len(rows3)}",
            composite_answer_dates="{}/{}".format(*scores["composite"]["value_recall"]),
            pointer_exact=f"{scores['pointer']['exact']}/{len(rows3)}",
            pointer_answer_dates="{}/{}".format(*scores["pointer"]["value_recall"]),
            discordant=f"{pc['a_only']} vs {pc['b_only']}",
            mcnemar_p=f"{pc['mcnemar_exact_p']:.3f}",
            answered_discordant=f"{pa['a_only']} vs {pa['b_only']}",
            answered_mcnemar_p=f"{pa['mcnemar_exact_p']:.3f}",
            parliament_permutation_p=mc["bodies"]["cluster_permutation_p_str"],
            parliament_favour=f"{mc['bodies']['favour_pointer']} vs {mc['bodies']['favour_composite']}",
            cluster95=_outward(pc["cluster_bootstrap95"]),
            cluster95_excludes_0=pc["cluster_interval_excludes_0"],
            answered_cluster95=_outward(pa["cluster_bootstrap95"]),
            keyword_cue_exact=f"{scores['keyword_cue']['exact']}/{len(rows3)}",
            keyword_cue_answer_dates="{}/{}".format(*scores["keyword_cue"]["value_recall"]),
            keyword_cue_mcnemar_p=f"{blk['paired']['pointer vs keyword_cue']['mcnemar_exact_p']:.3f}",
            keyword_cue_permutation_p=R3._pair(rows3, "pointer", "keyword_cue")["bodies"]["cluster_permutation_p_str"],
        ),
    )
    return out


def main() -> dict:
    docs = [json.loads(x) for x in open(DATA / "gold2" / "p2_docs.jsonl")]
    texts, how = {}, {}
    for d in docs:
        texts[d["doc_id"]], how[d["doc_id"]] = K.doc_text(d)
    per_doc = predictions(texts)
    out = dict(label=LABEL, proposed_by="proposed in review (round-19 skeptical-ML review); rule text as the reviewer "
               "wrote it, run by the team", method=__doc__.split("Scored like")[1].split("    PYTHONPATH")[0].strip(),
               inputs=dict(sha256_verified=sum(v in ("cache", "fetched") for v in how.values()),
                           fetched=sum(v == "fetched" for v in how.values()),
                           unavailable=sorted(k for k, v in how.items() if v not in ("cache", "fetched"))),
               **rescore(per_doc), per_doc=per_doc)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main()["display"], indent=1))
    sys.exit(0)
