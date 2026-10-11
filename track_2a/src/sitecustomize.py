"""Process-wide fixes that must hold before any Gegenprobe code runs. Python's `site` module imports `sitecustomize` at
interpreter start from the first sys.path entry that has one; every Gegenprobe entry point puts this directory (src/) on
PYTHONPATH (Makefile `export PYTHONPATH := src:.`, Dockerfile `ENV PYTHONPATH=/app/src:/app` for `make run` and the Docker
nightly unit, the venv nightly unit `Environment=PYTHONPATH=/opt/gegenprobe/track_2a/src`, CI, the subprocesses that
monitor/nightly.py and monitor/smoke.py start). tests/test_robots9309.py checks each of them. An installed checkout
(`pip install -e .`) gets the same start-up from site-packages/gegenprobe-robots9309.pth (setup.py); whichever runs first
boots, the other is a no-op.

The work is done by gegenprobe/compliance/fetchguard.py `boot()`, loaded from its file without importing the gegenprobe
package (whose __init__ installs the I/O hardening and would pull in the converter at every interpreter start):

1. robots.txt under RFC 9309 (longest match, allow wins ties, `*` and `$`) instead of urllib.robotparser's first match:
   gegenprobe/robots9309.py, see docs/incidents.md (2026-10-10).

2. Fail-closed: the moment gegenprobe.net is imported, its open_url and allowed are wrapped so that every request first
   checks that the RFC 9309 matcher is active, and is refused (net.Disallowed, kind robots_matcher_inactive) when it is
   not. If step 1 fails, nothing is fetched in this process.

3. Documents whose original URL robots.txt disallows are requested from OPD's own copy (files.openparldata.ch):
   gegenprobe/compliance/mirror.py, mapping data/compliance/mirror_urls.json. gegenprobe.net is locked (LOCK5), so the
   same meta-path hook patches it (net.open_url, through which net.get, pdftext.fetch_pdf and the eval drivers fetch), in
   every process: the samplers and evaluation code that LOCK files freeze included.

4. OCR fails loudly: the moment gegenprobe.pdftext (locked) is imported, gegenprobe/ocrguard.py wraps its OCR path, so a
   missing deu/fra/ita language pack, a non-zero tesseract exit or an empty OCR result is a typed `ocr_failed` error and
   is never cached (found in review: a scan used to become a cached page of empty text and then a typed null).

5. The local 8B path: gegenprobe/gguf_guard.py re-hashes the GGUF weights at every load, renders the GGUF's
   chat template in a Jinja sandbox, takes an operator's file from GP_GGUF_FILE / GP_GGUF_SHA256, and makes the model
   requests of the locked gegenprobe.llm and gegenprobe.convert.roles_pointer carry GP_USER_AGENT.

A sitecustomize further down sys.path (a distribution's own) is executed afterwards, so it is not shadowed.
"""
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
    _guard = sys.modules.get("_gegenprobe_fetchguard") or _load(
        "_gegenprobe_fetchguard", os.path.join(_HERE, "gegenprobe", "compliance", "fetchguard.py"))
    _guard.boot(os.path.join(_HERE, "gegenprobe"))
except Exception as e:  # never break interpreter start; fetchguard.ensure() in the fetch modules installs the guard
    print(f"[sitecustomize] Gegenprobe fetch guard NOT booted: {type(e).__name__}: {e}", file=sys.stderr)



class _PdftextHook:
    """4. OCR fails loudly (gegenprobe/ocrguard.py): after the locked gegenprobe.pdftext executes, its OCR path is
    wrapped so that a missing language pack, a non-zero tesseract exit or an empty OCR result is a typed `ocr_failed`
    error and is never cached. Applies in every process, the frozen evaluation code included."""

    def __init__(self, guard):
        self.guard = guard

    def find_spec(self, name, path=None, target=None):
        if name != "gegenprobe.pdftext":
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return spec
        run = spec.loader.exec_module

        def exec_module(module, _run=run, _guard=self.guard):
            _run(module)
            _guard.patch(module)

        spec.loader.exec_module = exec_module
        return spec


try:
    _ocr = sys.modules.get("_gegenprobe_ocrguard") or _load(
        "_gegenprobe_ocrguard", os.path.join(_HERE, "gegenprobe", "ocrguard.py"))
    if "gegenprobe.pdftext" in sys.modules:
        _ocr.patch(sys.modules["gegenprobe.pdftext"])
    sys.meta_path.insert(0, _PdftextHook(_ocr))
except Exception as e:  # never break interpreter start; ocrguard.ensure() in the entry points installs it
    print(f"[sitecustomize] Gegenprobe OCR guard NOT booted: {type(e).__name__}: {e}", file=sys.stderr)



class _GGUFHook:
    """5. The local 8B path (gegenprobe/gguf_guard.py): after the locked gegenprobe.llm, gegenprobe.gguf_fast or
    the locked gegenprobe.convert.roles_pointer executes, the weights are re-hashed at every load, the GGUF chat template
    is rendered in a Jinja sandbox, GP_GGUF_FILE / GP_GGUF_SHA256 select an operator's file, and their HTTP requests
    carry GP_USER_AGENT."""

    def __init__(self, guard):
        self.guard = guard

    def find_spec(self, name, path=None, target=None):
        if name not in self.guard.TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return spec
        run = spec.loader.exec_module

        def exec_module(module, _run=run, _guard=self.guard):
            _run(module)
            _guard.patch(module)

        spec.loader.exec_module = exec_module
        return spec


try:
    _gg = sys.modules.get("_gegenprobe_gguf_guard") or _load(
        "_gegenprobe_gguf_guard", os.path.join(_HERE, "gegenprobe", "gguf_guard.py"))
    for _n in _gg.TARGETS:
        if _n in sys.modules:
            _gg.patch(sys.modules[_n])
    sys.meta_path.insert(0, _GGUFHook(_gg))
except Exception as e:  # never break interpreter start; gguf_guard.ensure() in the entry points installs it
    print(f"[sitecustomize] Gegenprobe GGUF guard NOT booted: {type(e).__name__}: {e}", file=sys.stderr)

_rest = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
_spec = importlib.machinery.PathFinder.find_spec("sitecustomize", _rest)
if _spec is not None and _spec.origin and os.path.abspath(_spec.origin) != os.path.abspath(__file__):
    _load("_sitecustomize_next", _spec.origin)
