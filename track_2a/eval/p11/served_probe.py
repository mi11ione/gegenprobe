"""P11 deviation D1 evidence (eval/p11/DEVIATIONS_P11.md): did the build behind `swiss-ai/apertus-v1.5-8b` change when
Public AI began returning the label `swiss-ai/Apertus-v1.5-70B` for it (12 Oct 2026, ~01:05 UTC)?

    PYTHONPATH=src:. .venv/bin/python -m eval.p11.served_probe      -> results/p11/served_model_probe.json

Three live calls through the project's budget gateway (tag 2a-probe, cap USD 0.10), each a byte-for-byte replay of a
request whose response was cached during a registered run on the frozen build:
  * two P10 role-reader requests (`roles_pointer.next_token_top`: one user message + JSON-prefix assistant prefill,
    max_tokens 1, logprobs, top_logprobs) on the first P10 test affair of the Italian stratum;
  * one P1 date-pointer request (`llm._Remote.score`: user message + prefilled candidate, prompt_logprobs) on the first
    Italian P1 held-out document.
The requests are rebuilt by the frozen code itself (a cache-only replay with GP_OFFLINE=1 that records every payload whose
key it reads), so the prompt is the registered one. Only `swiss-ai/apertus-v1.5-8b` is ever called (assert). Recorded per
call: sha256 of the payload, the cache key, the cached and the live `model` and `system_fingerprint`, the greedy token and
the log-probability deltas. No prompt text is written.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time

from gegenprobe.compliance import fetchguard

fetchguard.ensure()

from gegenprobe import llm  # noqa: E402
from gegenprobe.paths import ROOT  # noqa: E402

MODEL = "swiss-ai/apertus-v1.5-8b"
BUILD = f"publicai:{MODEL}"
TAG, CAP = "2a-probe", 0.10
OUT = ROOT / "results" / "p11" / "served_model_probe.json"
FROZEN_FP = "vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840"


def _sha(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class _Recorder:
    """Records every (key -> kind, payload) the frozen code computes while it replays from the cache."""

    def __init__(self):
        self.seen: dict[str, tuple[str, dict]] = {}
        self._orig = llm.ModelCache.key

    def __enter__(self):
        orig = self._orig

        def key(build, kind, payload):
            k = orig(build, kind, payload)
            if build == BUILD:
                self.seen.setdefault(k, (kind, json.loads(json.dumps(payload))))
            return k

        llm.ModelCache.key = staticmethod(key)
        return self

    def __exit__(self, *exc):
        llm.ModelCache.key = staticmethod(self._orig)


def _offline_backend():
    os.environ["GP_OFFLINE"] = "1"
    from eval import arms as EA

    return EA.backend(f"gateway:{MODEL}:{TAG}:{CAP}")


def p10_requests(n: int = 2) -> list[tuple[str, str, dict, dict]]:
    """The first n next_top requests of the first Italian P10 test affair, each with its cached response."""
    from eval.p10 import arms as A10
    from gegenprobe.convert import roles_pointer as RP

    C, PK, rows, M, N = A10._load_test()
    cfg = json.loads(C.CONFIG.read_text())
    cands = {r["affair_id"]: r for r in C._jsonl(C.CANDS10)}
    be = _offline_backend()
    e = next(r for r in rows if r["stratum"] == "it")
    pages = PK.pages_of(e)
    with _Recorder() as rec:
        RP.read(be, pages["question"], pages["answer"], cands[e["affair_id"]]["candidates"],
                A10.lang_of(e["stratum"], pages["question"]), cfg["pointer"])
    out = []
    for k, (kind, payload) in rec.seen.items():
        hit = be.cache.get(k)
        if kind == "next_top" and hit is not None:
            out.append((f"P10 role reader, affair {e['affair_id']}", k, payload, hit))
        if len(out) == n:
            break
    return out


def p1_request() -> tuple[str, str, dict, dict]:
    """The first score request of the first Italian P1 held-out document, with its cached response."""
    from eval import arms as EA
    from gegenprobe.convert import pointer, rules

    be = _offline_backend()
    theta = json.loads(EA.theta_path(be.build).read_text())["answer_date"]["theta"]
    d = next(x for x in EA.load_split("heldout") if EA._lang(x) == "it")
    with _Recorder() as rec:
        pointer.answer_date(be, d["pages"], "it", theta, anchors=rules.anchors(d["pages"]))
    for k, (kind, payload) in rec.seen.items():
        hit = be.cache.get(k)
        if kind == "score" and hit is not None:
            return (f"P1 held-out date pointer, doc {d['doc_id']}", k, payload, hit)
    raise SystemExit("no cached P1 score request found")


def live(payload: dict) -> tuple[dict, dict]:
    assert payload["model"] == MODEL, payload["model"]  # never a prefill to a -70b name
    from gegenprobe import devpaths

    gw = devpaths.import_gw("the served-model probe")

    extra = {k: v for k, v in payload.items() if k not in ("model", "messages", "max_tokens", "temperature")
             and not k.startswith("_")}
    for i in range(6):  # 429 / 5xx / disconnects, as llm.Gateway; never retry a budget refusal
        try:
            return gw.chat(payload["messages"], model=MODEL, max_tokens=payload["max_tokens"],
                           temperature=payload["temperature"], tag=TAG, tag_cap_usd=CAP, full=True, nocache=True, **extra)
        except Exception as e:
            if "BUDGET" in str(e) or i == 5:
                raise
            print(f"retry {i + 1}: {type(e).__name__}: {str(e)[:80]}", file=sys.stderr, flush=True)
            time.sleep(20 * (i + 1))
    raise RuntimeError("unreachable")


def compare(what: str, k: str, payload: dict, hit: dict) -> dict:
    choice, meta = live(payload)
    resp = meta["resp"]
    row = dict(what=what, kind="next_top" if "logprobs" in payload else "score", cache_key=k,
               payload_sha256=_sha({x: v for x, v in payload.items()}), requested_model=payload["model"],
               cached=dict(model=hit["resp"].get("model"), system_fingerprint=hit["resp"].get("system_fingerprint"),
                           ts=hit.get("ts")),
               live=dict(model=resp.get("model"), system_fingerprint=resp.get("system_fingerprint"),
                         ts=round(time.time()), usd=round(meta.get("usd") or 0.0, 6)))
    if row["kind"] == "next_top":
        content = ((choice.get("logprobs") or {}).get("content") or [{}])[0]
        top = {t["token"]: t["logprob"] for t in content.get("top_logprobs") or []}
        old = hit["top"]
        shared = sorted(set(top) & set(old))
        d = [abs(top[t] - old[t]) for t in shared]
        row.update(greedy_cached=_sha(hit.get("token")), greedy_live=_sha(content.get("token")),
                   greedy_equal=hit.get("token") == content.get("token"), top_k=len(top),
                   top_tokens_equal=set(top) == set(old), top_order_equal=sorted(top, key=top.get, reverse=True)
                   == sorted(old, key=old.get, reverse=True), shared_tokens=len(shared),
                   max_abs_logprob_delta=max(d) if d else None, mean_abs_logprob_delta=sum(d) / len(d) if d else None)
    else:
        red = llm._reduce(payload, choice, resp)
        row.update(lp_cached=hit["lp"], lp_live=red["lp"], abs_logprob_delta=abs(red["lp"] - hit["lp"]),
                   tokens_equal=red["toks"] == hit["toks"], n_prompt_cached=hit.get("n_prompt"),
                   n_prompt_live=red.get("n_prompt"))
    return row


def main() -> dict:
    reqs = p10_requests(2) + [p1_request()]
    os.environ.pop("GP_OFFLINE", None)
    rows = [compare(*r) for r in reqs]
    deltas = [r.get("max_abs_logprob_delta", r.get("abs_logprob_delta")) for r in rows]
    fp_same = all(r["live"]["system_fingerprint"] == r["cached"]["system_fingerprint"] == FROZEN_FP for r in rows)
    out = dict(
        label="P11 D1 evidence (eval/p11/DEVIATIONS_P11.md): served-label change on the -8b route",
        written=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), route=f"gateway, requested {MODEL}, tag {TAG}",
        frozen_build_fingerprint=FROZEN_FP,
        labels_served_live=sorted({r["live"]["model"] for r in rows}),
        labels_cached=sorted({r["cached"]["model"] for r in rows}),
        fingerprints_live=sorted({r["live"]["system_fingerprint"] for r in rows}),
        fingerprint_equal_to_frozen_on_every_call=fp_same,
        max_abs_logprob_delta=max(d for d in deltas if d is not None),
        greedy_equal_on_every_next_top_call=all(r["greedy_equal"] for r in rows if r["kind"] == "next_top"),
        usd=round(sum(r["live"]["usd"] for r in rows), 6),
        note="No prompt text is stored: payload_sha256 is sha256 of the request JSON (sort_keys), cache_key the "
             "model-cache key under data/model_cache/publicai_swiss-ai_apertus-v1.5-8b/; greedy tokens are hashed.",
        calls=rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {k: v for k, v in out.items() if k != "calls"}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
    sys.exit(0)
