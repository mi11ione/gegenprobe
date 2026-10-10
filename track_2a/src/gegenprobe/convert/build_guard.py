"""Review mode in operation: refuse to apply θ when the model actually served is not the build θ was fitted on.

θ (data/convert/theta/<build>.json) is a margin threshold fitted on one served build. It does not transfer across builds,
quantisations or prompts, and a host can swap the weights or the inference stack behind an unchanged model name. So the
review path wraps the backend in a guard:

  remote builds (openai, gateway)  every live response carries the server's `system_fingerprint`; the guard compares each
                                   new fingerprint with the ones θ was fitted on: the θ file's `served_fingerprints`
                                   plus the build-level fingerprints in results/eval/served_models.json. The first
                                   response from another fingerprint stops the run (BuildMismatch, exit code 3) before any
                                   suggestion from it is attached. A θ file that records no fingerprint cannot be checked
                                   and is refused up front.
  local GGUF                       the weights file is the build: a file given by path is hashed and compared with the
                                   sha256 pinned in served_models.json (`gguf_pin`); the default file is fetched through
                                   llm.fetch_gguf, which already refuses any other sha256.

--allow-build-mismatch turns the refusal into a warning; every suggestion made under a mismatch then carries
`build_mismatch` (fitted vs served), so a reviewer sees it. A θ given with --theta is the operator's own choice and is not
checked. Cache hits replay responses recorded under the same build key and do not change the served set.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from ..paths import RESULTS, ROOT

SERVED = RESULTS / "eval" / "served_models.json"


class BuildMismatch(SystemExit):
    """The served model is not the build θ was fitted on. A SystemExit, so per-document error handling cannot turn it into
    a failure row: the whole run stops."""

    def __init__(self, msg: str):
        super().__init__(3)
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def fitted(theta_file: Path, served_file: Path = SERVED) -> dict:
    """What θ was fitted on: build, fingerprints (θ file + served_models.json), and the GGUF sha256 pin."""
    t = json.loads(theta_file.read_text())
    fps = {f for f in t.get("served_fingerprints") or [] if f}
    pin = None
    if served_file.exists():
        s = json.loads(served_file.read_text())
        entry = s.get("files", {}).get(_rel(theta_file)) or {}
        for blk in (entry, entry.get("build_level") or {}):
            fps |= {f for f in (blk.get("system_fingerprints") or {}) if f and f != "null"}
        pin = (s.get("gguf_pin") or {}).get("sha256")
    return dict(build=t.get("build"), theta_file=_rel(theta_file), fingerprints=sorted(fps), gguf_sha256=pin)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 24):
            h.update(b)
    return h.hexdigest()


class BuildGuard:
    """Proxy for a review backend that checks, after every call, that the served build is the one θ was fitted on."""

    def __init__(self, inner, fit: dict, allow_mismatch: bool = False, warn=None):
        self.inner, self.fit, self.allow = inner, fit, allow_mismatch
        self.mismatch: dict | None = None
        self._warn = warn or (lambda m: print(m, file=sys.stderr))
        self._preflight()

    def __getattr__(self, name):  # build, kind, cache, served, ... of the wrapped backend
        return getattr(self.inner, name)

    def _refuse(self, what: str, served) -> None:
        mm = dict(fitted_build=self.fit["build"], fitted=self.fit.get("fingerprints") or self.fit.get("gguf_sha256"),
                  served=served, theta_file=self.fit["theta_file"])
        msg = (f"review mode: {what}. θ in {self.fit['theta_file']} was fitted on build '{self.fit['build']}' "
               f"({', '.join(mm['fitted']) if isinstance(mm['fitted'], list) else mm['fitted']}); "
               f"served: {served}. θ does not transfer across builds. Refit θ for this build (docs/runbook.md, "
               "\"Review mode in operation\"), or pass --allow-build-mismatch to attach suggestions anyway, each marked "
               "build_mismatch.")
        if not self.allow:
            raise BuildMismatch(msg)
        if self.mismatch is None:
            self._warn("warning: " + msg.replace(" Refit θ", " Continuing (--allow-build-mismatch). Refit θ"))
        self.mismatch = mm

    def _preflight(self) -> None:
        build = getattr(self.inner, "build", "")
        if build != self.fit["build"]:
            self._refuse("the backend's build is not the θ file's build", build)
        if str(build).startswith("gguf:"):
            path = getattr(self.inner, "path", None)
            if path and self.fit.get("gguf_sha256"):
                got = _sha256(path)
                if got != self.fit["gguf_sha256"]:
                    self._refuse(f"the GGUF file {path} is not the pinned weights", got)
            return
        if not self.fit.get("fingerprints"):
            self._refuse("the θ file records no served fingerprint, so the served build cannot be checked", "unknown")

    def _verify(self) -> None:
        if str(getattr(self.inner, "build", "")).startswith("gguf:"):
            return
        new = sorted(set(getattr(self.inner, "served", set()) or set()) - set(self.fit["fingerprints"]))
        if new:
            self._refuse("the server answered from a fingerprint θ was not fitted on", new)

    def score(self, *a, **kw):
        out = self.inner.score(*a, **kw)
        self._verify()
        return out

    def generate(self, *a, **kw):
        out = self.inner.generate(*a, **kw)
        self._verify()
        return out
