"""Which build answers the `swiss-ai/apertus-v1.5-8b` route right now? (eval/refit_bfd70257/NOTE.md, addendum)

    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.probe [--n 6] [--out FILE]

Byte-for-byte replays of date-pointer requests whose responses are cached for BOTH builds: the registered build
(data/model_cache/publicai_swiss-ai_apertus-v1.5-8b/, P1 dev) and the new build (…_bfd70257/, the refit's dev calls).
The requests are rebuilt by the frozen code (eval.arms.load_split + convert.pointer on P1 dev documents, a cache-only
replay that records the payloads), sent sequentially through the budget gateway (tag 2a-refit; the model name is always
`swiss-ai/apertus-v1.5-8b`, one user message plus the candidate prefill, as every registered run), and each response is
recorded with its label, fingerprint and log-probability next to both cached ones. No prompt text is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path

from gegenprobe.compliance import fetchguard

fetchguard.ensure()

from eval import arms  # noqa: E402
from eval.refit_bfd70257 import run as R  # noqa: E402
from gegenprobe import llm  # noqa: E402
from gegenprobe.convert import pointer  # noqa: E402


def payloads(n: int) -> list[tuple[str, dict]]:
    """(kind, payload) of the first score call of each P1 dev document whose response both caches hold."""
    old = llm.ModelCache(R.ROUTE_BUILD, readonly=True)
    new = llm.ModelCache(R.NEW_BUILD, readonly=True)
    seen: list[dict] = []
    orig = llm.ModelCache.key

    def key(build, kind, payload):
        if build == R.ROUTE_BUILD and kind == "score":
            seen.append(json.loads(json.dumps(payload)))
        return orig(build, kind, payload)

    be = llm.OpenAICompat(base_url="http://offline.invalid", model=R.REQUESTED, build=R.ROUTE_BUILD, cache_readonly=True)
    be.offline = True
    saved = arms.SPIKES
    arms.SPIKES = Path(tempfile.mkdtemp(prefix="probe_")) / "x"
    (arms.SPIKES / "round8").mkdir(parents=True)
    (arms.SPIKES / "round8" / "ptr_items.json").write_text("[]")
    llm.ModelCache.key = staticmethod(key)
    out = []
    try:
        for d in arms.load_split("dev"):
            seen.clear()
            pointer.answer_date(be, d["pages"], arms._lang(d), theta=0.0)
            for p in seen[:1]:
                if old.get(orig(R.ROUTE_BUILD, "score", p)) and new.get(orig(R.NEW_BUILD, "score", p)):
                    out.append(("score", p))
            if len(out) >= n:
                break
    finally:
        llm.ModelCache.key = staticmethod(orig)
        arms.SPIKES = saved
    return out


def probe(n: int) -> dict:
    usd0 = R.spent()
    gw = llm.Gateway(R.REQUESTED, tag=R.TAG, cap_usd=R.CAP, build="probe-not-cached")
    old = llm.ModelCache(R.ROUTE_BUILD, readonly=True)
    new = llm.ModelCache(R.NEW_BUILD, readonly=True)
    calls = []
    for kind, p in payloads(n):
        assert p["model"] == R.REQUESTED and [m["role"] for m in p["messages"]] == ["user", "assistant"]
        o = old.get(llm.ModelCache.key(R.ROUTE_BUILD, kind, p))
        c = new.get(llm.ModelCache.key(R.NEW_BUILD, kind, p))
        t = time.time()
        live = gw._post(p)  # sent as every registered run sends it; nothing is cached
        r = live["resp"]
        calls.append(dict(
            utc=time.strftime("%H:%M:%SZ", time.gmtime(t)),
            payload_sha256=hashlib.sha256(json.dumps(p, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            live_label=r.get("model"), live_fingerprint=r.get("system_fingerprint"), live_lp=live["lp"],
            registered_lp=o["lp"], newbuild_lp=c["lp"],
            equals_registered=abs(live["lp"] - o["lp"]) < 1e-6, equals_newbuild=abs(live["lp"] - c["lp"]) < 1e-6))
    pairs = sorted({f"{c['live_label']} | {c['live_fingerprint']}" for c in calls})
    return dict(label=R.LABEL, written=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), route=f"gateway, requested "
                f"{R.REQUESTED}, tag {R.TAG}", n=len(calls), label_fingerprint_pairs=pairs, calls=calls,
                usd=round(R.spent() - usd0, 6))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out")
    a = ap.parse_args()
    res = probe(a.n)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "calls"}, indent=1))
    for c in res["calls"]:
        print(c["utc"], c["live_label"], c["live_fingerprint"], "reg" if c["equals_registered"] else "",
              "new" if c["equals_newbuild"] else "", round(c["live_lp"], 3), round(c["registered_lp"], 3),
              round(c["newbuild_lp"], 3))
