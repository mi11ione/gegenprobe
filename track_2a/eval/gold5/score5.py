"""P3b scoring: P3's scorer (`eval.gold3.score3.score_all`, frozen) applied to a P3b results file and the merged P3b labels.
Model-free; for a results file written before the labels existed (the arms may run before labelling).

    python -m eval.gold5.score5 publicai_swiss-ai_apertus-v1.5-8b     -> adds `scores` to results/eval5/p3b__<build>.json
"""

from __future__ import annotations

import json
import sys

from eval.gold3.score3 import score_all
from eval.gold5.run_p3b import LABELS5, OUT5, affairs


def rescore(build: str) -> dict:
    p = OUT5 / f"p3b__{build}.json"
    res = json.loads(p.read_text())
    gold = {g["affair_id"]: g for g in map(json.loads, open(LABELS5))}
    res["scores"] = score_all(res["per_affair"], gold, {r["affair_id"]: r for r in affairs()})
    p.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


if __name__ == "__main__":
    r = rescore(sys.argv[1])
    for f, v in r["scores"]["fields"].items():
        print(f, {arm: f"{s.get('correct', 0)}/{s['n']}" for arm, s in v.items()})
    for f, v in r["scores"]["sets"].items():
        print(f, {arm: f"P {s['tp']}/{s['tp'] + s['fp']} R {s['tp']}/{s['tp'] + s['fn']}" for arm, s in v.items()})
