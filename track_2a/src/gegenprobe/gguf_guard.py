"""The local Apertus 8B path, hardened at runtime WITHOUT editing the locked gegenprobe/llm.py (LOCK) or
gegenprobe/convert/roles_pointer.py (LOCK10), the way hardening.py and ocrguard.py do it (round 16, J3).

  sha256 at every load      llm.GGUF._load and gguf_fast.GGUFFast._load hash the weights file each time a model is
                            loaded and compare it with the pin (llm.GGUF_PINS, or GP_GGUF_SHA256 for an operator's file);
                            a mismatch refuses the load (GGUFIntegrityError). The locked fetch_gguf only compares the
                            size of a cached file, and hardening.py's re-check is remembered by size + mtime; this one is
                            not remembered (about 10-20 s per load for the 5 GB Q4_K_M on a laptop SSD)
  sandboxed chat template   the chat template embedded in the GGUF (tokenizer.chat_template, i.e. text from the model
                            file) is rendered by jinja2.sandbox.ImmutableSandboxedEnvironment instead of a plain
                            Environment(): no access to Python internals (__class__, __globals__, ...) and no mutation
                            of passed-in objects from a crafted template (jinja2.exceptions.SecurityError). Default
                            Environment options are kept. Checked on the pinned file's own template (16,614 characters,
                            sha256 d23af285...; read from the GGUF header): the plain and the sandboxed render are
                            identical for user messages, so the prompt and its tokens are unchanged
  operator's own file       GP_GGUF_FILE=/path/model.gguf with GP_GGUF_SHA256=<64 hex> loads that file instead of the
                            pinned download (e.g. the self-quantised file docs/runbook.md recommends). Both are required
                            (fail-closed). If the sha256 is a pinned one, the build stays that pin's build (same weights,
                            another location); otherwise the build is gguf:<file stem>@<sha256[:12]>, so its model cache
                            and θ are its own (θ does not transfer across quantisations: review mode refuses until one is
                            fitted, as for any build)
  GP_USER_AGENT             the HTTP requests made by llm.py (OpenAICompat._post, the GGUF download in fetch_gguf) and
                            by roles_pointer._post_openai carry GP_USER_AGENT (default hackapertus-research/0.1, as
                            gegenprobe.net) instead of the hard-coded default. The Gateway backend (development only)
                            sends through the external gateway module (gw.py), outside this repository; its User-Agent is
                            not set here

Installed in every process: src/sitecustomize.py patches gegenprobe.llm, gegenprobe.gguf_fast and
gegenprobe.convert.roles_pointer the moment each is imported (src/ on PYTHONPATH: make run, Docker, CI, nightly), and
`ensure()` is called by the unlocked entry points (python -m gegenprobe, its affair command) for an install without
sitecustomize. Idempotent. Stdlib only at import time (sitecustomize loads this file by path).
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_UA = "hackapertus-research/0.1"
TARGETS = ("gegenprobe.llm", "gegenprobe.gguf_fast", "gegenprobe.convert.roles_pointer")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MARK = "_gp_gguf_guard"


_twin = sys.modules.get("_gegenprobe_gguf_guard")  # the copy src/sitecustomize.py loaded by path, if any
if _twin is not None and __name__ != "_gegenprobe_gguf_guard" and hasattr(_twin, "GGUFIntegrityError"):
    GGUFIntegrityError = _twin.GGUFIntegrityError  # one exception class, whichever copy patched the targets
else:
    class GGUFIntegrityError(RuntimeError):
        """The GGUF weights file is not the pinned one (or has no pin)."""


def user_agent() -> str:
    return os.environ.get("GP_USER_AGENT") or DEFAULT_UA


# ------------------------------------------------------------------------------------------------------- User-Agent
class _RequestModule:
    """urllib.request with every Request carrying GP_USER_AGENT."""

    def __getattr__(self, name):
        return getattr(urllib.request, name)

    @staticmethod
    def Request(*args, **kw):  # noqa: N802 - mirrors urllib.request.Request
        req = urllib.request.Request(*args, **kw)
        req.add_header("User-Agent", user_agent())
        return req


class _Urllib:
    """Stands in for the `urllib` name inside llm.py and roles_pointer.py (they `import urllib.request`)."""
    request = _RequestModule()
    error = urllib.error

    def __getattr__(self, name):
        import urllib as real

        return getattr(real, name)


# ------------------------------------------------------------------------------------------------------- weights
def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 24):
            h.update(b)
    return h.hexdigest()


def operator_file() -> tuple[Path, str] | None:
    """(file, sha256) from GP_GGUF_FILE / GP_GGUF_SHA256, None when neither is set; ValueError when only one is or the
    hash is not 64 hex characters."""
    f, s = os.environ.get("GP_GGUF_FILE", "").strip(), os.environ.get("GP_GGUF_SHA256", "").strip().lower()
    if not f and not s:
        return None
    if not (f and s):
        raise ValueError("GP_GGUF_FILE and GP_GGUF_SHA256 go together: name the file and its sha256 (fail-closed)")
    if not _HEX64.fullmatch(s):
        raise ValueError(f"GP_GGUF_SHA256 must be 64 hexadecimal characters, got {s[:80]!r}")
    return Path(f).expanduser(), s


def _pins() -> dict:
    llm = sys.modules.get("gegenprobe.llm")
    return dict(getattr(llm, "GGUF_PINS", {}) or {})


def expected_sha(obj) -> str | None:
    want = getattr(obj, "_gp_expected_sha256", None)
    if want:
        return want
    pin = _pins().get(getattr(obj, "name", None))
    return pin["sha256"] if pin else None


def verified_path(obj) -> str:
    """The weights file of a GGUF backend, hashed now and compared with its pin; raises GGUFIntegrityError."""
    llm = sys.modules["gegenprobe.llm"]
    path = obj.path or str(llm.fetch_gguf(obj.name))
    want = expected_sha(obj)
    if not want:
        raise GGUFIntegrityError(f"no sha256 pin for the GGUF file {path} (model name {obj.name!r}); set GP_GGUF_FILE and "
                                 "GP_GGUF_SHA256 for an operator's file")
    got = sha256_file(path)
    if got != want:
        raise GGUFIntegrityError(f"the GGUF file {path} has sha256 {got}, expected {want}; refused (not loaded)")
    obj.weights_sha256 = got
    return path


def sandboxed_template(source: str):
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    return ImmutableSandboxedEnvironment().from_string(source)


def _make_load(llama_kw: dict):
    def _load(self):
        if self._llm is None:
            from llama_cpp import Llama

            path = verified_path(self)
            self._llm = Llama(model_path=path, n_ctx=self.n_ctx, n_threads=self.n_threads, verbose=False, **llama_kw)
            self._tmpl = sandboxed_template(self._llm.metadata["tokenizer.chat_template"])
        return self._llm

    _load.__wrapped_by__ = "gegenprobe.gguf_guard"
    return _load


def _wrap_init(orig):
    def __init__(self, *a, **kw):
        orig(self, *a, **kw)
        op = operator_file()
        if op is None or kw.get("path") or (len(a) > 1 and a[1]):
            return  # an explicit path given in code keeps its name's pin
        f, sha = op
        llm = sys.modules["gegenprobe.llm"]
        pinned = next((n for n, p in llm.GGUF_PINS.items() if p["sha256"] == sha), None)
        self.path = str(f)
        self.name = pinned or f.stem
        self.build = f"gguf:{pinned}" if pinned else f"gguf:{f.stem}@{sha[:12]}"
        self.cache = llm.ModelCache(self.build, readonly=self.cache.readonly)
        self._gp_expected_sha256 = sha

    __init__.__wrapped__ = orig
    return __init__


# ------------------------------------------------------------------------------------------------------- install
def patch(module) -> None:
    """Patch one target module (idempotent)."""
    name = getattr(module, "__name__", "")
    if getattr(module, _MARK, False):
        return
    if name == "gegenprobe.llm":
        module.urllib = _Urllib()
        module.GGUF.__init__ = _wrap_init(module.GGUF.__init__)
        module.GGUF._load = _make_load(dict(logits_all=True))
    elif name == "gegenprobe.gguf_fast":
        module.GGUFFast._load = _make_load(dict(logits_all=False, n_batch=512))
    elif name == "gegenprobe.convert.roles_pointer":
        module.urllib = _Urllib()
    else:
        return
    setattr(module, _MARK, True)


def ensure() -> bool:
    """Import and patch the three targets (llm, gguf_fast, roles_pointer). True when installed."""
    try:
        import importlib

        for n in TARGETS:
            patch(importlib.import_module(n))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[gegenprobe] GGUF guard NOT installed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def status() -> dict:
    """Which targets are patched in this process (tests, `python -m gegenprobe.gguf_guard`)."""
    return {n: bool(getattr(sys.modules.get(n), _MARK, False)) for n in TARGETS}


if __name__ == "__main__":
    import json

    ensure()
    print(json.dumps(dict(patched=status(), user_agent=user_agent(), operator_file=os.environ.get("GP_GGUF_FILE")),
                     indent=1))
