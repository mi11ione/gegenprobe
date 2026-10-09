"""Cost of the converter, measured on the frozen held-out run (no model calls: the pointer is replayed from the committed
hash cache and the token counts are read from the cached responses).

  pointer (review mode): calls per document = 1 (null) + one per distinct printed date; each call is a full prefill of the
    prompt (the API bills every call's prompt tokens; a server with prefix caching computes the shared prefix once).
  rules_only (default): CPU time of rules.answer_date over the held-out page texts, measured here.
Projection: OPD's docs export holds 902,754 documents (results/census); the pointer runs only on the rules' residue.

    python -m report.cost  -> results/report/cost.json
"""

from __future__ import annotations

import json
import os
import statistics
import time

from eval import arms
from gegenprobe.convert import pointer, rules
from gegenprobe.paths import RESULTS

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
PRICE_IN = 0.10  # USD per million prompt tokens, Public AI list price for the swiss-ai/apertus-v1.5-8b name (gateway/gw.py)


def main() -> dict:
    os.environ["GP_OFFLINE"] = "1"
    be = arms.backend("gateway:swiss-ai/apertus-v1.5-8b:2a-cost:0.0")
    be.offline = True
    seen = []
    orig = be._cached_call

    def rec(kind, payload):
        r = orig(kind, payload)
        seen.append(r.get("n_prompt", 0))
        return r

    be._cached_call = rec
    res = json.loads((RESULTS / "eval" / f"heldout__{BUILD}.json").read_text())
    status = {r["doc_id"]: r["rules"]["status"] for r in res["per_doc"]}
    docs = arms.load_split("heldout")
    per_doc, t_rules = [], 0.0
    for d in docs:
        t0 = time.perf_counter()
        rules.answer_date(d["pages"], d["image_only"])
        t_rules += time.perf_counter() - t0
        if status[d["doc_id"]] != "abstain":
            continue
        seen.clear()
        pointer.answer_date(be, d["pages"], arms._lang(d), float("inf"), anchors=rules.anchors(d["pages"]))
        per_doc.append(dict(calls=len(seen), billed_prompt_tokens=sum(seen), max_prompt_tokens=max(seen, default=0)))
    n_docs, n_res = len(docs), len(per_doc)
    billed = [x["billed_prompt_tokens"] for x in per_doc]
    n_corpus = json.loads((RESULTS / "census" / "summary.json").read_text())["parentless_docs"]["docs_total"]
    share = n_res / n_docs
    per_res_doc = statistics.mean(billed)
    proj = n_corpus * share * per_res_doc
    out = dict(
        build=BUILD,
        heldout_docs=n_docs,
        residue_docs=n_res,
        residue_share=share,
        calls_per_residue_doc_mean=statistics.mean(x["calls"] for x in per_doc),
        billed_prompt_tokens_per_residue_doc_mean=per_res_doc,
        unique_prefill_tokens_per_residue_doc_mean=statistics.mean(x["max_prompt_tokens"] for x in per_doc),
        heldout_pointer_billed_prompt_tokens=sum(billed),
        corpus_documents=n_corpus,
        projection_billed_prompt_tokens=proj,
        projection_billed_prompt_tokens_x10=10 * proj,
        projection_billed_prompt_tokens_billions=proj / 1e9,
        projection_usd_at_list_price=proj * PRICE_IN / 1e6,
        projection_usd_at_list_price_x10=10 * proj * PRICE_IN / 1e6,
        price_usd_per_million_prompt_tokens=PRICE_IN,
        rules_cpu_seconds_heldout=t_rules,
        rules_docs_per_second=n_docs / t_rules,
        rules_cpu_hours_corpus=n_corpus / (n_docs / t_rules) / 3600,
        corpus_source="results/census/summary.json parentless_docs.docs_total (OPD docs export rows)",
        caveat="residue share measured on the stratified held-out sample, not on the corpus mix",
    )
    (RESULTS / "report" / "cost.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
