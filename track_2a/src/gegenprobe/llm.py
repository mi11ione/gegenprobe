"""Model access for the converter and the evaluation arms.

Three backends speak one protocol:
  score(user_text, prefix, conts) -> list[float]   summed log-probability of each continuation after the assistant prefix
                                                  (exact forced choice: candidate prefilled, read back via prompt_logprobs)
  generate(user_text, max_tokens, seed) -> str     free generation (only the naive contrast arm uses this)

  OpenAICompat  any vLLM-style OpenAI endpoint (LLM_BASE_URL / LLM_API_KEY / LLM_NAME). Forced choice needs the vLLM extras
                continue_final_message + prompt_logprobs; generation works on any OpenAI-compatible server.
  Gateway       development only: the same calls routed through Roman's budget gateway (gateway/gw.py: caps, ledger, cache).
  GGUF          llama-cpp-python in-process on a pinned GGUF (CPU); one prefill per document, continuations scored on top.

Hazards measured on Public AI (spikes/live/results.md) that this module enforces:
  * Only a single plain user message is ever sent. A system message or prefill sent to the `apertus-v1.5-70b` name is answered
    by Qwen-SEA-LION-v4-32B; therefore prefill (forced choice) is only sent to names on the allow-list below, and the response
    `model` field is checked on every call (ServedModelMismatch otherwise).
  * Identical requests come back from a provider response cache; generation passes an explicit `seed` and logs it.
  * The name `swiss-ai/apertus-v1.5-8b` serves the 70B weights. BUILD_LABELS records what each name really is.

Every result is stored in a hash-keyed cache (data/model_cache/<build>/...): key = sha256(build, kind, payload). `make run`
replays from it and only a small live slice goes to the network.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .paths import MODEL_CACHE

# Names that accept an assistant prefill (vLLM backend). The 70B name does not (silent Qwen fallback).
PREFILL_OK = {"swiss-ai/apertus-v1.5-8b", "swiss-ai/apertus-70b-instruct"}
BUILD_LABELS = {
    "swiss-ai/apertus-v1.5-8b": "Apertus v1.5 70B weights (Public AI serves the 70B under the -8b name; spikes/live)",
    "swiss-ai/apertus-v1.5-70b": "Apertus v1.5 70B (Public AI; free generation only, user message only)",
    "gguf:apertus-v1.5-8b-text-q4_k_m": "Apertus v1.5 8B, GGUF Q4_K_M (Colby), llama.cpp CPU",
}
GGUF_PINS = {
    "apertus-v1.5-8b-text-q4_k_m": dict(
        url="https://huggingface.co/Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF/resolve/main/apertus-v1.5-8b-text-q4_k_m.gguf",
        sha256="a037df8d87ff6caacee794ee85f55342f2152e0d359b7389033300c3bee5f299", size=5059027136),
}


class ServedModelMismatch(RuntimeError):
    pass


class CacheMiss(RuntimeError):
    pass


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


class ModelCache:
    def __init__(self, build: str, root: Path = MODEL_CACHE, readonly: bool = False):
        self.dir = root / _slug(build)
        self.readonly = readonly

    @staticmethod
    def key(build: str, kind: str, payload: dict) -> str:
        return hashlib.sha256(json.dumps(dict(build=build, kind=kind, payload=payload), sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()

    def path(self, k: str) -> Path:
        return self.dir / k[:2] / f"{k}.json"

    def get(self, k: str):
        p = self.path(k)
        return json.loads(p.read_text()) if p.exists() else None

    def put(self, k: str, value: dict) -> None:
        if self.readonly:
            return
        p = self.path(k)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
        tmp.replace(p)


def _tail_logprob(prompt_logprobs: list, cont: str) -> tuple[float, list[str]]:
    """Sum the logprobs of the trailing prompt tokens whose decoded text concatenates to exactly `cont`."""
    acc, lp, toks = "", 0.0, []
    for e in reversed(prompt_logprobs):
        if e is None:
            break
        vals = list(e.values())
        act = vals[0] if len(vals) == 1 else next(v for v in vals if v.get("rank") != 1)
        acc = act["decoded_token"] + acc
        lp += act["logprob"]
        toks.insert(0, act["decoded_token"])
        if acc == cont:
            return lp, toks
        if len(acc) > len(cont) or not cont.endswith(acc):
            break
    raise ValueError(f"token boundary does not align with continuation {cont!r}: got {acc!r}")


class _Remote:
    """Shared logic for HTTP backends: build payloads, check the served model, cache."""
    kind = "remote"

    def __init__(self, model: str, build: str | None = None, cache_readonly: bool = False):
        self.model = model
        self.build = build or model
        self.cache = ModelCache(self.build, readonly=cache_readonly)
        self.offline = os.environ.get("GP_OFFLINE") == "1"
        self.served: set[str] = set()

    def _post(self, payload: dict) -> dict:  # -> {"choice":..., "resp":...}
        raise NotImplementedError

    def _check(self, resp: dict) -> None:
        got = resp.get("model")
        if got != self.model:
            raise ServedModelMismatch(f"requested {self.model}, served {got}")
        fp = resp.get("system_fingerprint")
        if fp:
            self.served.add(fp)

    def _cached_call(self, kind: str, payload: dict) -> dict:
        k = ModelCache.key(self.build, kind, payload)
        hit = self.cache.get(k)
        if hit is not None:
            return hit
        if self.offline:
            raise CacheMiss(k)
        out = self._post(payload)
        self._check(out["resp"])
        self.cache.put(k, out)
        return out

    def score(self, user_text: str, prefix: str, conts: list[str]) -> list[float]:
        if self.model not in PREFILL_OK:
            raise ValueError(f"{self.model} does not accept an assistant prefill (Qwen fallback); no forced choice")
        out = []
        for c in conts:
            # `_cont` is never sent; it tells _reduce which trailing tokens to sum
            payload = dict(model=self.model, temperature=0.0, max_tokens=1,
                           messages=[{"role": "user", "content": user_text}, {"role": "assistant", "content": prefix + c}],
                           continue_final_message=True, add_generation_prompt=False, prompt_logprobs=1, _cont=c)
            out.append(self._cached_call("score", payload)["lp"])
        return out

    def generate(self, user_text: str, max_tokens: int = 200, seed: int = 0) -> str:
        payload = dict(model=self.model, temperature=0.0, max_tokens=max_tokens, seed=seed,
                       messages=[{"role": "user", "content": user_text}])
        return self._cached_call("generate", payload)["text"]


def _reduce(payload: dict, choice: dict, resp: dict) -> dict:
    """Keep only what we need from a response (prompt_logprobs of a 3k-token prompt is ~1 MB)."""
    out = dict(resp={k: resp.get(k) for k in ("id", "model", "system_fingerprint")}, ts=round(time.time()))
    if payload.get("prompt_logprobs"):
        lp, toks = _tail_logprob(resp["prompt_logprobs"], payload["_cont"])
        out.update(lp=lp, toks=toks, n_prompt=len(resp["prompt_logprobs"]))
    else:
        out.update(text=(choice.get("message") or {}).get("content") or "", finish=choice.get("finish_reason"))
    return out


class OpenAICompat(_Remote):
    kind = "openai"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None, **kw):
        self.base = (base_url or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
        self.key = api_key or os.environ.get("LLM_API_KEY", "")
        super().__init__(model or os.environ.get("LLM_NAME", ""), **kw)

    def _post(self, payload: dict) -> dict:
        body = {k: v for k, v in payload.items() if not k.startswith("_")}
        req = urllib.request.Request(self.base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                                              "User-Agent": "hackapertus-research/0.1"})
        for i in range(6):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    d = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and i < 5:
                    time.sleep(15 * (i + 1))
                    continue
                raise
        return _reduce(payload, d["choices"][0], {k: v for k, v in d.items() if k not in ("choices", "usage")})


class Gateway(_Remote):
    """Development backend: every call through ~/Desktop/hackapertus/gateway/gw.py (budget caps, ledger)."""
    kind = "gateway"

    def __init__(self, model: str, tag: str, cap_usd: float, **kw):
        import sys
        sys.path.insert(0, os.path.expanduser("~/Desktop/hackapertus/gateway"))
        import gw  # noqa: E402
        self.gw, self.tag, self.cap = gw, tag, cap_usd
        super().__init__(model, **kw)

    def _post(self, payload: dict) -> dict:
        extra = {k: v for k, v in payload.items() if k not in ("model", "messages", "max_tokens", "temperature")
                 and not k.startswith("_")}
        for i in range(6):
            try:
                choice, meta = self.gw.chat(payload["messages"], model=payload["model"], max_tokens=payload["max_tokens"],
                                            temperature=payload["temperature"], tag=self.tag, tag_cap_usd=self.cap,
                                            full=True, nocache=True, **extra)
                break
            except Exception as e:  # 429 / disconnects; never retry a budget refusal
                if "BUDGET" in str(e) or i == 5:
                    raise
                time.sleep(20 * (i + 1))
        return _reduce(payload, choice, meta["resp"])


class GGUF:
    """llama-cpp-python in-process scorer. The chat template embedded in the GGUF is rendered with enable_thinking=False,
    which for Apertus v1.5 gives the same token ids as the HF/MLX stack (spikes/gguf: 1058/1058)."""
    kind = "gguf"

    def __init__(self, name: str = "apertus-v1.5-8b-text-q4_k_m", path: str | None = None, n_ctx: int = 4096,
                 n_threads: int | None = None, cache_readonly: bool = False):
        self.name = name
        self.build = f"gguf:{name}"
        self.cache = ModelCache(self.build, readonly=cache_readonly)
        self.path = path
        self.n_ctx, self.n_threads = n_ctx, n_threads
        self._llm = None
        self.offline = os.environ.get("GP_OFFLINE") == "1"

    # -- lazy load ------------------------------------------------------------------------------------------------
    def _load(self):
        if self._llm is None:
            from llama_cpp import Llama
            from jinja2 import Environment
            self._llm = Llama(model_path=self.path or str(fetch_gguf(self.name)), n_ctx=self.n_ctx, logits_all=True,
                              n_threads=self.n_threads, verbose=False)
            tmpl = self._llm.metadata["tokenizer.chat_template"]
            self._tmpl = Environment().from_string(tmpl)
        return self._llm

    def render(self, user_text: str) -> str:
        self._load()
        return self._tmpl.render(messages=[{"role": "user", "content": user_text}], add_generation_prompt=True,
                                 enable_thinking=False, bos_token="<s>")

    def _tok(self, s: str) -> list[int]:
        return self._llm.tokenize(s.encode(), add_bos=False, special=True)

    def score(self, user_text: str, prefix: str, conts: list[str]) -> list[float]:
        payload = dict(user=user_text, prefix=prefix, conts=conts, n_ctx=self.n_ctx)
        k = ModelCache.key(self.build, "score", payload)
        hit = self.cache.get(k)
        if hit is not None:
            return hit["lps"]
        if self.offline:
            raise CacheMiss(k)
        import numpy as np
        llm = self._load()
        head = self.render(user_text) + prefix
        pre = self._tok(head)
        llm.reset()
        llm.eval(pre)
        n0 = llm.n_tokens
        lps = []
        for c in conts:
            full = self._tok(head + c)
            assert full[:len(pre)] == pre, ("prefix tokenisation changed", c)
            ids = full[len(pre):]
            llm.n_tokens = n0  # rewind; llama-cpp-python drops the KV cache beyond n_tokens on the next eval
            if len(ids) > 1:
                llm.eval(ids[:-1])
            rows = np.asarray(llm.scores[n0 - 1:n0 - 1 + len(ids)], dtype=np.float64)
            m = rows.max(axis=1, keepdims=True)
            logp = rows - (m + np.log(np.exp(rows - m).sum(axis=1, keepdims=True)))
            lps.append(float(sum(logp[j, t] for j, t in enumerate(ids))))
        llm.n_tokens = n0
        self.cache.put(k, dict(lps=lps, n_prompt=len(pre), ts=round(time.time())))
        return lps

    def generate(self, user_text: str, max_tokens: int = 200, seed: int = 0) -> str:
        payload = dict(user=user_text, max_tokens=max_tokens, seed=seed)
        k = ModelCache.key(self.build, "generate", payload)
        hit = self.cache.get(k)
        if hit is not None:
            return hit["text"]
        if self.offline:
            raise CacheMiss(k)
        llm = self._load()
        llm.reset()
        out = llm.create_completion(self.render(user_text), max_tokens=max_tokens, temperature=0.0, seed=seed)
        text = out["choices"][0]["text"]
        self.cache.put(k, dict(text=text, ts=round(time.time())))
        return text


def fetch_gguf(name: str):
    """Download a pinned GGUF into GP_WORK/models (never committed) and verify its sha256."""
    from .paths import WORK
    pin = GGUF_PINS[name]
    dest = WORK / "models" / f"{name}.gguf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == pin["size"]:
        return dest
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(pin["url"], headers={"User-Agent": "hackapertus-research/0.1"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 22)
            if not b:
                break
            h.update(b)
            f.write(b)
    if h.hexdigest() != pin["sha256"]:
        tmp.unlink()
        raise RuntimeError(f"sha256 mismatch for {name}")
    tmp.replace(dest)
    return dest


def softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    s = sum(e)
    return [v / s for v in e]


def backend_from_env():
    """make run: LLM_BASE_URL set -> OpenAICompat; GP_GGUF=1 -> local GGUF; else None (replay only)."""
    if os.environ.get("GP_GGUF") == "1":
        return GGUF()
    if os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_NAME"):
        return OpenAICompat()
    return None
