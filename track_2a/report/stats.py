"""Small derived numbers the technical report prints that no other results file holds.

    python -m report.stats   -> results/report/report_numbers.json, results/report/cited_spikes.json

`report_numbers.json` is recomputed from committed inputs (held-out label composition, θ file).
`cited_spikes.json` copies prior spike results with their source file; they are cited, not recomputed here
(the spike folders are not part of the repository).
"""
from __future__ import annotations

import collections
import json

from gegenprobe.paths import DATA, RESULTS

CITED = {
    "role_scoring_auroc": dict(value=0.57,
                               source="spikes/inversions/results.md (S6 role pointer on BE: AUROC of max P(government_answer))"),
    "public_ai_identical_greedy_cells": dict(value=760, of=792,
                                             source="spikes/live/results.md §0 (apertus-v1.5-8b vs -70b names)"),
    "mmlu_8b_name": dict(value=84.4, source="FINAL/vision-2A.md correction 2 (250 MMLU items, -8b name)"),
    "mmlu_v1_8b_route": dict(value=70.8, source="FINAL/vision-2A.md correction 2 (apertus-8b-instruct, same items)"),
    "qwen_fallback": dict(value=3, of=3, source="spikes/live/results.md §e (system message or prefill to apertus-v1.5-70b)"),
    "decode_tok_s_8b_name": dict(value="21–28", source="spikes/live/results.md §0 speed probe"),
    "decode_tok_s_v1_8b": dict(value=93, source="spikes/live/results.md §0 speed probe"),
}


def main() -> None:
    labels = [json.loads(line) for line in open(DATA / "gold" / "heldout_labels.jsonl")]
    by_cell = collections.Counter((r["cell"], r["answer_date"] is not None) for r in labels)
    theta = json.loads((DATA / "convert" / "theta" / "publicai_swiss-ai_apertus-v1.5-8b.json").read_text())["answer_date"]
    out = dict(
        heldout=dict(n=len(labels), with_value=sum(r["answer_date"] is not None for r in labels),
                     gold_null=sum(r["answer_date"] is None for r in labels),
                     cells=len({r["cell"] for r in labels}),
                     by_cell={f"{c}|{'value' if v else 'null'}": n for (c, v), n in sorted(by_cell.items())},
                     rec_values=sum(r["recommendation"] in ("accept", "reject", "convert", "partial") for r in labels)),
        theta=dict(value=theta["theta"], auroc=theta["auroc"], loo_correct=theta["loo"]["correct"], loo_n=theta["loo"]["n"],
                   loo_ci_pct=[round(100 * x, 1) for x in theta["loo"]["wilson95"]], fitted_on=theta["fitted_on"]),
    )
    (RESULTS / "report").mkdir(parents=True, exist_ok=True)
    (RESULTS / "report" / "report_numbers.json").write_text(json.dumps(out, indent=1))
    (RESULTS / "report" / "cited_spikes.json").write_text(json.dumps(CITED, indent=1, ensure_ascii=False))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
