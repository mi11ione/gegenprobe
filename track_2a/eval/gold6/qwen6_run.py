"""Operational wrapper for the registered Qwen check (eval/gold6/qwen6.py is frozen by LOCK6 and unchanged): the frozen
`annotate()` stops at the first HTTP 429 from Public AI. This wrapper calls the frozen `qwen6.call` one affair at a time,
retries a 429 / disconnect with back-off, and writes the same output file in the same format. Recorded as deviation
D6-3 in eval/prereg6/DEVIATIONS6.md (no change to prompt, model, parameters, tag or cap; the gateway's content cache
makes a retried call free when the first one had completed).

    python -m eval.gold6.qwen6_run
"""

from __future__ import annotations

import json
import time

from eval.gold6 import qwen6
from eval.gold6.annotate6 import _rows


def main() -> None:
    done = {}
    if qwen6.OUT.exists():
        done = {r["affair_id"]: r for r in map(json.loads, open(qwen6.OUT))}
    for r in _rows("p5"):
        i = r["affair_id"]
        if i in done:
            continue
        for k in range(8):
            try:
                done[i] = qwen6.call(i)
                break
            except Exception as e:  # 429 / disconnect; a budget refusal is re-raised
                if "BUDGET" in str(e) or k == 7:
                    raise
                time.sleep(30 * (k + 1))
        qwen6.OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(qwen6.OUT, "w") as f:
            for key in sorted(done):
                f.write(json.dumps(done[key], ensure_ascii=False) + "\n")
    print(f"{len(done)} Qwen labels -> {qwen6.OUT}")


if __name__ == "__main__":
    main()
