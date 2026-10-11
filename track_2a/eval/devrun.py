"""Run a LOCKED module with the development directories taken from the environment instead of the developer's layout.

The frozen modules name two directories outside the repository literally: `~/Desktop/hackapertus/spikes`
(eval/arms.py `SPIKES`: texts of the 30 spike dev items; eval/gold/sample.py: spike exclusions of the gold draw) and
`~/Desktop/hackapertus/gateway` (src/gegenprobe/llm.py `Gateway`, eval/gold6/qwen6.py: the developer's budget gateway).
The LOCK files (eval/prereg*/LOCK*) freeze those files, so they cannot be edited. This entry point redirects exactly
those two prefixes to GP_SPIKES_DIR / GP_GATEWAY_DIR (gegenprobe/devpaths.py; default: `spikes` / `gateway` next to the
checkout) and then runs the module as `__main__`, unchanged:

    python -m eval.devrun eval.arms fit --backend openai          # θ refit (Makefile `theta`)
    python -m eval.devrun eval.arms run --split heldout --backend openai
    GP_SPIKES_DIR=none python -m eval.devrun eval.arms fit --backend openai
                       # no spike folder: θ is fitted on the 97 committed dev documents (the 30 spike items are skipped)

Clear errors instead of a bare FileNotFoundError: a `gateway:` backend without gw.py, and a dev-split command of
eval.arms without the spike items, stop before any work with the variable to set.
"""
from __future__ import annotations

import os
import runpy
import sys
import tempfile
from pathlib import Path

from gegenprobe import devpaths

LEGACY = {"~/Desktop/hackapertus/spikes": "spikes", "~/Desktop/hackapertus/gateway": "gateway"}
_expanduser = os.path.expanduser


def _empty_spikes() -> Path:
    d = Path(tempfile.mkdtemp(prefix="gp_nospikes_"))
    (d / "round8").mkdir()
    (d / "round8" / "ptr_items.json").write_text("[]")
    return d


def targets() -> dict[str, Path]:
    sp = os.environ.get("GP_SPIKES_DIR", "")
    return dict(spikes=_empty_spikes() if sp.lower() == "none" else devpaths.spikes(), gateway=devpaths.gateway_dir())


def install(t: dict[str, Path]) -> None:
    """Redirect the two legacy prefixes in os.path.expanduser (the call the locked modules use)."""

    def expanduser(p):
        s = os.fspath(p)
        for prefix, kind in LEGACY.items():
            if s == prefix or s.startswith(prefix + "/"):
                return str(t[kind]) + s[len(prefix):]
        return _expanduser(p)

    os.path.expanduser = expanduser


def preflight(module: str, args: list[str], t: dict[str, Path]) -> None:
    if any(a.startswith("gateway:") for a in args) or module == "eval.gold6.qwen6":
        devpaths.import_gw(f"{module} with the gateway backend")  # imported once; the locked `import gw` reuses it
    i = args.index("--split") + 1 if "--split" in args else len(args)
    split = args[i] if i < len(args) else "heldout"
    dev = module == "eval.arms" and (args[:1] == ["fit"] or split == "dev")
    if (dev or module == "eval.gold.sample") and not t["spikes"].exists():
        raise devpaths.DevPathMissing(
            f"{module} {' '.join(args)} reads development spike material that is not in the repository: {t['spikes']} "
            "does not exist. Set GP_SPIKES_DIR to the spikes directory"
            + (", or GP_SPIKES_DIR=none to fit on the 97 committed dev documents only." if module == "eval.arms" else "."))


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    module, args = argv[0], argv[1:]
    t = targets()
    try:
        preflight(module, args, t)
    except devpaths.DevPathMissing as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    install(t)
    sys.argv = [module] + args
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    except FileNotFoundError as e:
        name = str(e.filename or "")
        for kind, base in t.items():
            if name.startswith(str(base)):
                var = "GP_SPIKES_DIR" if kind == "spikes" else "GP_GATEWAY_DIR"
                print(f"error: {module} needs {name}, development material outside the repository; set {var} "
                      f"(now {base}).", file=sys.stderr)
                return 2
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
