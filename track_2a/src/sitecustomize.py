"""Process-wide fixes that must hold before any Gegenprobe code runs. Python's `site` module imports `sitecustomize` at
interpreter start from the first sys.path entry that has one; every Gegenprobe entry point puts this directory (src/) on
PYTHONPATH (Makefile `export PYTHONPATH := src:.`, Dockerfile `ENV PYTHONPATH=/app/src:/app` for `make run` and the Docker
nightly unit, the venv nightly unit `Environment=PYTHONPATH=/opt/gegenprobe/track_2a/src`, CI, the subprocesses that
monitor/nightly.py and monitor/smoke.py start). tests/test_robots9309.py checks each of them.

1. robots.txt under RFC 9309 (longest match, allow wins ties, `*` and `$`) instead of urllib.robotparser's first match:
   gegenprobe/robots9309.py, see docs/incidents.md (2026-10-10). Loaded from its file, without importing the gegenprobe
   package (whose __init__ installs the I/O hardening and would pull in the converter at every interpreter start).

2. Documents whose original URL robots.txt disallows are requested from OPD's own copy (files.openparldata.ch):
   gegenprobe/compliance/mirror.py, mapping data/compliance/mirror_urls.json. gegenprobe.net is locked (LOCK5), so a
   meta-path hook patches it the moment it is imported (net.open_url, through which net.get, pdftext.fetch_pdf and the
   eval drivers fetch), in every process: the samplers and evaluation code that LOCK files freeze included.

A sitecustomize further down sys.path (a distribution's own) is executed afterwards, so it is not shadowed.
"""
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    _load("_gegenprobe_robots9309", os.path.join(_HERE, "gegenprobe", "robots9309.py")).install()
except Exception as e:  # never break interpreter start; the tests and CI assert that the patch is active
    print(f"[sitecustomize] RFC 9309 robots.txt patch NOT installed: {type(e).__name__}: {e}", file=sys.stderr)

try:
    _mirror = _load("_gegenprobe_mirror", os.path.join(_HERE, "gegenprobe", "compliance", "mirror.py"))

    class _NetHook(importlib.abc.MetaPathFinder):
        """After gegenprobe.net executes, route mapped URLs to OPD's copy (mirror.patch_net)."""

        def find_spec(self, name, path=None, target=None):
            if name != "gegenprobe.net":
                return None
            spec = importlib.machinery.PathFinder.find_spec(name, path)
            if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
                return spec
            run = spec.loader.exec_module

            def exec_module(module, _run=run):
                _run(module)
                try:
                    _mirror.patch_net(module)
                except Exception as e:  # never break the import; tests assert the patch
                    print(f"[sitecustomize] OPD mirror patch NOT installed: {type(e).__name__}: {e}", file=sys.stderr)

            spec.loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _NetHook())
except Exception as e:
    print(f"[sitecustomize] OPD mirror hook NOT installed: {type(e).__name__}: {e}", file=sys.stderr)

_rest = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
_spec = importlib.machinery.PathFinder.find_spec("sitecustomize", _rest)
if _spec is not None and _spec.origin and os.path.abspath(_spec.origin) != os.path.abspath(__file__):
    _load("_sitecustomize_next", _spec.origin)
