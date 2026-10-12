"""Review mode on a re-built route: a deployment θ file outside the hash-locked evaluation record.

The frozen lookup (`convert.batch.resolve_review`, `convert.build_guard`) finds θ by build key in data/convert/theta/,
whose files are the evaluation record (eval/prereg/LOCK). Since 12 Oct 2026 ~01:05 UTC Public AI answers requests for
`swiss-ai/apertus-v1.5-8b` from another build (label `swiss-ai/Apertus-v1.5-70B`, fingerprint
`vllm-0.1.dev1+g54b4292c2-tp2-bfd70257`), so that lookup refuses the route (exit 3). A refit for the new build
(eval/refit_bfd70257/NOTE.md) is a deployment file in data/deploy/ (`theta_<build>.json`); this module lets the CLI use
it, and nothing else:

  when            a remote backend (openai on api.publicai.co, or gateway:<model>:...) resolves to a file's `route_build`
                  and requests its `requested_model`, the run is live (not GP_OFFLINE=1), no --theta is given, and a
                  preflight request shows that the route serves exactly the file's (`served_label`, `served_fingerprints`)
                  now. The preflight is one plain user message ("Antworte nur mit: ok", max_tokens 1, never cached) to the
                  same model name; the route has switched builds twice on 12 Oct 2026 (~01:05 UTC to bfd70257, ~03:33 UTC
                  back), so the build is read before θ is chosen. If the route serves anything else, the frozen path runs:
                  the registered θ for the registered build, exit 3 for any other build.
  what changes    the backend moves to the file's own build key (its own model cache: a cached old-build response is never
                  replayed as a new-build one); its response check accepts exactly the file's (`served_label`,
                  `served_fingerprints`) and nothing else: the old label, the old fingerprint, a missing fingerprint or
                  any other label stop the run (ServedModelMismatch, exit 3); the BuildGuard is fitted from the file
                  (θ and fingerprints), so a fingerprint change stops it too (BuildMismatch, exit 3)
  what does not   requests (same model name, one plain user message, the prefill only to llm.PREFILL_OK names); no
                  request names a -70b model; the frozen modules; the registered θ files; offline replays

"""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

from .. import llm
from ..paths import DATA

DEPLOY_DIR = DATA / "deploy"
REQUIRED = ("build", "route_build", "requested_model", "served_label", "served_fingerprints", "answer_date")


def files(deploy_dir: Path | None = None) -> list[tuple[Path, dict]]:
    """Every deployment θ file (theta_*.json) with the keys this module needs; a malformed file is an error."""
    d = DEPLOY_DIR if deploy_dir is None else deploy_dir
    out = []
    for p in sorted(d.glob("theta_*.json")) if d.exists() else []:
        t = json.loads(p.read_text())
        miss = [k for k in REQUIRED if not t.get(k)]
        if miss or "theta" not in t["answer_date"]:
            raise SystemExit(f"deployment θ file {p} lacks {', '.join(miss) or 'answer_date.theta'}")
        out.append((p, t))
    return out


def for_backend(be) -> tuple[Path, dict] | None:
    """The deployment file that applies to this backend, or None (then the frozen path runs)."""
    if not isinstance(be, llm._Remote) or getattr(be, "offline", False):
        return None
    hits = [(p, t) for p, t in files() if be.build in (t["route_build"], t["build"]) and be.model == t["requested_model"]]
    if len(hits) > 1:
        raise SystemExit(f"more than one deployment θ file for {be.build}: {', '.join(str(p) for p, _ in hits)}")
    return hits[0] if hits else None


def accept_only(be, label: str, fingerprints, requested: str):
    """Install, on this backend instance only, a response check that accepts exactly (requested name -> `label` with a
    fingerprint in `fingerprints`). Counts are kept in `be.relabel` (checked, accepted)."""
    fps = set(fingerprints)
    stats = dict(checked=0, accepted=0, label=label, fingerprints=sorted(fps), requested=requested)

    def _check(resp: dict) -> None:
        stats["checked"] += 1
        got, fp = resp.get("model"), resp.get("system_fingerprint")
        if be.model == requested and got == label and fp in fps:
            stats["accepted"] += 1
            be.served.add(fp)
            return
        raise llm.ServedModelMismatch(
            f"requested {be.model}, served {got} (system_fingerprint {fp}); the deployment θ accepts only {label} with "
            f"{', '.join(sorted(fps))}")

    be._check = _check  # instance attribute: _cached_call and roles_pointer call self._check / backend._check
    be.relabel = stats
    return be


def switch(be, path: Path, t: dict):
    """Move a route backend onto the deployment build (own build key, own cache, the narrow response check)."""
    if be.build != t["build"]:
        be.build = t["build"]
        be.cache = llm.ModelCache(t["build"], readonly=getattr(be.cache, "readonly", False))
    accept_only(be, t["served_label"], t["served_fingerprints"], t["requested_model"])
    be.deploy_theta_file = str(path)
    return be


PREFLIGHT = dict(temperature=0.0, max_tokens=1, messages=[{"role": "user", "content": "Antworte nur mit: ok"}])


def served_now(be) -> tuple[str | None, str | None]:
    """One live request to the route (one plain user message, max_tokens 1, never cached): (label, fingerprint)."""
    r = be._post(dict(PREFLIGHT, model=be.model))["resp"]
    return r.get("model"), r.get("system_fingerprint")


def applies(be) -> tuple[Path, dict] | None:
    """The deployment file to use for this backend now, or None: a file for the route, and the route serving its build."""
    hit = for_backend(be)
    if not hit:
        return None
    path, t = hit
    label, fp = served_now(be)
    if label == t["served_label"] and fp in t["served_fingerprints"]:
        print(f"review mode: {be.model} is served by {label} ({fp}); θ and response check from {path.name}",
              file=sys.stderr)
        return hit
    print(f"review mode: {be.model} is served by {label} ({fp}), not the build of {path.name}; frozen lookup",
          file=sys.stderr)
    return None


def make_backend(orig, spec: str):
    be = orig(spec)
    hit = applies(be)
    return switch(be, *hit) if hit else be


def resolve_review(orig, orig_make, spec: str, theta_override: float | None = None, allow_build_mismatch: bool = False):
    """The frozen resolve_review, plus the deployment lookup for remote backends (see the module docstring). An explicit
    θ (--theta) and every backend the lookup does not apply to go through the frozen function with the frozen
    make_backend."""
    from . import batch
    from .build_guard import BuildGuard, fitted

    if theta_override is None and (spec == "openai" or spec.startswith("gateway:")):
        be = orig_make(spec)
        hit = applies(be)
        if hit:
            path, t = hit
            switch(be, path, t)
            return BuildGuard(be, fitted(path), allow_mismatch=allow_build_mismatch), float(t["answer_date"]["theta"])
    wrapped, batch.make_backend = batch.make_backend, orig_make
    try:
        return orig(spec, theta_override, allow_build_mismatch=allow_build_mismatch)
    finally:
        batch.make_backend = wrapped


@contextlib.contextmanager
def installed():
    """For one CLI call: batch.resolve_review and batch.make_backend with the deployment lookup; restored afterwards."""
    from . import batch

    orig_resolve, orig_make = batch.resolve_review, batch.make_backend
    batch.resolve_review = lambda spec, theta_override=None, allow_build_mismatch=False: resolve_review(
        orig_resolve, orig_make, spec, theta_override, allow_build_mismatch)
    batch.make_backend = lambda spec: make_backend(orig_make, spec)
    try:
        yield
    finally:
        batch.resolve_review, batch.make_backend = orig_resolve, orig_make
