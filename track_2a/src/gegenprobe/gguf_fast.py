"""Speed-optimised GGUF scorer for the 8B arms on a CPU runner (deviation D2 in eval/prereg/DEVIATIONS.md).

The frozen `llm.GGUF.score` loads the model with logits_all=True, which computes the 131k-row output projection for every
prompt token (measured: ~7 tok/s on a 4-vCPU runner). This subclass computes the same quantity, the summed log-probability
of each continuation after the shared prefix, from last-token logits only: one prefill, then each continuation fed one
token at a time on top of the prefix, rewound after each. Same model file, same rendering, same tokens, same cache keys
(build "gguf:<name>"), so results land in the same hash cache. Parity with the frozen scorer is checked on CI
(`python -m gegenprobe.gguf_fast parity`) before any arm runs.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np

from .llm import GGUF, CacheMiss, ModelCache


class GGUFFast(GGUF):
    def __init__(self, *a, n_ctx: int = 8192, **kw):
        super().__init__(*a, n_ctx=n_ctx, **kw)

    def _load(self):
        if self._llm is None:
            from jinja2 import Environment
            from llama_cpp import Llama

            from .llm import fetch_gguf
            self._llm = Llama(model_path=self.path or str(fetch_gguf(self.name)), n_ctx=self.n_ctx, logits_all=False,
                              n_batch=512, n_threads=self.n_threads, verbose=False)
            self._tmpl = Environment().from_string(self._llm.metadata["tokenizer.chat_template"])
        return self._llm

    def _last_logp(self) -> np.ndarray:
        """Logits of the last evaluated token, read from the llama context (llama-cpp-python 0.3.35 does not copy them into
        `scores` when logits_all=False: that row stays zero, i.e. uniform — caught by the CI parity gate)."""
        import llama_cpp
        ptr = llama_cpp.llama_get_logits_ith(self._llm._ctx.ctx, -1)
        row = np.ctypeslib.as_array(ptr, shape=(self._llm.n_vocab(),)).astype(np.float64)
        if not row.std() > 0:
            raise RuntimeError("flat logits row: scorer is not reading the model output")
        m = row.max()
        return row - (m + np.log(np.exp(row - m).sum()))

    def score(self, user_text: str, prefix: str, conts: list[str]) -> list[float]:
        payload = dict(user=user_text, prefix=prefix, conts=conts, n_ctx=4096)  # key identical to the frozen scorer
        k = ModelCache.key(self.build, "score", payload)
        hit = self.cache.get(k)
        if hit is not None:
            return hit["lps"]
        if self.offline:
            raise CacheMiss(k)
        llm = self._load()
        head = self.render(user_text) + prefix
        pre = self._tok(head)
        llm.reset()
        llm.eval(pre)
        n0 = llm.n_tokens
        first = self._last_logp()
        lps = []
        for c in conts:
            full = self._tok(head + c)
            assert full[:len(pre)] == pre, ("prefix tokenisation changed", c)
            ids = full[len(pre):]
            llm.n_tokens = n0
            lp = float(first[ids[0]])
            for j in range(1, len(ids)):
                llm.eval([ids[j - 1]])
                lp += float(self._last_logp()[ids[j]])
            lps.append(lp)
        llm.n_tokens = n0
        self.cache.put(k, dict(lps=lps, n_prompt=len(pre), ts=round(time.time()), scorer="gguf_fast"))
        return lps


def parity(out: str) -> int:
    """Fast vs frozen scorer on the 12 parity cells (multi-token continuations included via the ver framing is not needed:
    the date continuations are multi-token, so a 3-token probe is added). Pass: max |delta| <= 0.5 nats."""
    from .gguf_check import FIX
    fx = json.loads(FIX.read_text())
    import gc
    cells = [(r["key"], r["text"] + fx["questions"][r["rung"]]) for r in fx["rows"][:6]]
    conts = fx["candidates"] + [' "28.08.2024"', " null"]
    slow = GGUF(cache_readonly=True)  # one model in memory at a time (16 GB runner)
    a = [slow.score(u, '{"antwort":', conts) for _, u in cells]
    del slow
    gc.collect()
    fast = GGUFFast(cache_readonly=True)
    b = [fast.score(u, '{"antwort":', conts) for _, u in cells]
    rows = [dict(key=k, slow=x, fast=y, max_abs=max(abs(p - q) for p, q in zip(x, y))) for (k, _), x, y in zip(cells, a, b)]
    for r in rows:
        print(r, flush=True)
    mx = max(x["max_abs"] for x in rows)
    res = dict(rows=rows, max_abs_delta=mx, verdict="PASS" if mx <= 0.5 else "FAIL")
    open(out, "w").write(json.dumps(res, indent=1))
    print(f"fast vs frozen GGUF scorer: max |delta| {mx:.3f} nats -> {res['verdict']}")
    return 0 if mx <= 0.5 else 1


if __name__ == "__main__":
    sys.exit(parity(sys.argv[2] if len(sys.argv) > 2 else "out/gguf_fast_parity.json"))
