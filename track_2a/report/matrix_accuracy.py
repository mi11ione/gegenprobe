"""Measured extraction accuracy for the feasibility matrix: field `answer_date` only, from the frozen held-out results, per
language x level cell (NOT per body: the gold set has too few documents per body). Bodies that contribute documents to a
cell are listed; bodies not in the gold set have no measured accuracy. No federal (CHE) documents are in the gold set.
`results/census/matrix.csv` is left untouched (the census replay asserts it byte-for-byte).

    python -m report.matrix_accuracy  -> results/census/matrix_accuracy.json
"""

from __future__ import annotations

import collections
import json

from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import wilson

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"


def main() -> dict:
    res = json.loads((RESULTS / "eval" / f"heldout__{BUILD}.json").read_text())
    bodies = collections.defaultdict(set)
    for line in open(DATA / "gold" / "heldout_docs.jsonl"):
        d = json.loads(line)
        bodies[d["cell"]].add(d["body"])
    cells = {}
    for cell in sorted(bodies):
        row = {"bodies": sorted(bodies[cell])}
        for arm in ("rules", "cascade"):
            s = res["arms"][arm]["strict"][cell]
            lo, hi = wilson(s["exact"], s["n"])
            row[arm] = dict(
                exact=s["exact"],
                n=s["n"],
                ci=[round(100 * lo, 1), round(100 * hi, 1)],
                values_on_answerless=s["invented_on_null"],
                answerless=s["n_gold_null"],
            )
        cells[cell] = row
    out = dict(
        field="answer_date",
        source=f"results/eval/heldout__{BUILD}.json (frozen, pre-registered)",
        unit="language x level cell",
        federal_documents_in_gold=0,
        other_fields_evaluated="recommendation (exploratory) only",
        cells=cells,
    )
    (RESULTS / "census" / "matrix_accuracy.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
