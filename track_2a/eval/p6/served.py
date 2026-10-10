"""Served model of every P6 model call, re-derived from the hash cache (no request is sent: GP_OFFLINE=1 replay of the
frozen runner, recording the stored response metadata of each entry it reads).

    GP_OFFLINE=1 PYTHONPATH=src:. python -m eval.p6.served     -> results/p6/p6_served.json
"""

from __future__ import annotations

import collections
import json
import os
import tempfile
from pathlib import Path

from eval import arms
from eval.p6 import run_p6
from gegenprobe.paths import RESULTS

SPEC = "gateway:swiss-ai/apertus-v1.5-8b:2a-p6:2.0"


def main() -> dict:
    os.environ["GP_OFFLINE"] = "1"
    be = arms.backend(SPEC)
    seen: collections.Counter = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    orig = be._cached_call

    def rec(kind, payload):
        out = orig(kind, payload)
        r = out.get("resp") or {}
        seen[(r.get("model"), r.get("system_fingerprint"))] += 1
        kinds[kind] += 1
        return out

    be._cached_call = rec
    old = run_p6.OUT
    run_p6.OUT = Path(tempfile.mkdtemp(prefix="p6served_"))
    real = arms.backend
    arms.backend = lambda spec: be
    try:
        run_p6.main(SPEC)
    finally:
        run_p6.OUT, arms.backend = old, real
    res = dict(build=be.build, requested=be.model, n_entries=sum(seen.values()), by_kind=dict(kinds),
               served=[dict(model=m, system_fingerprint=f, n=n) for (m, f), n in seen.most_common()],
               all_match=all(m == be.model for (m, _f) in seen))
    (RESULTS / "p6" / "p6_served.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
