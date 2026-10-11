"""Fail-closed fetch guard: no request leaves gegenprobe.net unless the RFC 9309 robots.txt matcher is active.

gegenprobe/net.py is locked (LOCK5) and asks `urllib.robotparser.RobotFileParser.can_fetch` whether a URL may be fetched.
Only after gegenprobe/robots9309.py's install() does that call follow RFC 9309 (longest match, allow wins ties, `*`, `$`);
without it the stdlib applies the first matching rule and allows paths a site disallows (docs/incidents.md, 2026-10-10).
Until round 6 a missing patch only printed a warning. Now every fetch path checks, at request time, that the matcher is
active, and refuses otherwise:

  * `patch_net(net)` wraps net.open_url (through which net.get, net.stream_ndjson_gz, pdftext.fetch_pdf and the eval
    drivers fetch) and net.allowed. Each call first checks `matcher_active()`; if it is False, open_url raises
    net.Disallowed(kind="robots_matcher_inactive") and allowed() returns False, before any byte is requested. Local
    files (file: URLs, GP_EXPORTS_DIR) are not network fetches and pass.
  * `boot()` is what runs at interpreter start, from two places: src/sitecustomize.py (src/ on PYTHONPATH: Makefile,
    Dockerfile, both nightly units, CI) and the `gegenprobe-robots9309.pth` file that `pip install -e .` (or
    `pip install .`) puts into site-packages (setup.py), so an installed checkout needs no PYTHONPATH. It installs the
    matcher and a meta-path hook that applies this guard and the OPD-copy routing (compliance/mirror.py) the moment
    gegenprobe.net is imported. If the matcher cannot be installed, the guard is installed anyway, so every fetch is
    refused.
  * `ensure()` is called by every unlocked module that imports gegenprobe.net (tests/test_fetchguard.py checks the list):
    in a process where neither sitecustomize nor the .pth ran it installs the matcher, the guard and the mirror routing
    on first import. It never raises; a failure leaves the guard refusing.

Stdlib only and free of package-relative imports: sitecustomize and the .pth load this file by path, before the
gegenprobe package exists (its __init__ installs the I/O hardening and would pull in the converter at every start).
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys
import urllib.robotparser

KIND = "robots_matcher_inactive"
_MARK = "_gegenprobe_fetchguard"
_RFC9309_MARK = "_gegenprobe_rfc9309"  # robots9309._MARK, set on the patched RobotFileParser methods
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)  # .../gegenprobe
_errors: list[str] = []


def matcher_active() -> bool:
    """RobotFileParser.can_fetch is robots9309's RFC 9309 version in this process (checked at every request)."""
    return bool(getattr(urllib.robotparser.RobotFileParser.can_fetch, _RFC9309_MARK, False))


def _chain(f):
    seen = 0
    while f is not None and seen < 16:
        yield f
        f = getattr(f, "__wrapped__", None)
        seen += 1


def installed(net) -> bool:
    """The guard sits somewhere in net.open_url's wrapper chain and on net.allowed."""
    return any(getattr(f, _MARK, False) for f in _chain(net.open_url)) and \
        any(getattr(f, _MARK, False) for f in _chain(net.allowed))


def _refusal(url) -> str:
    why = "; ".join(_errors) or "RobotFileParser.can_fetch is the stdlib's first-match version"
    return (f"{url} (not fetched: the RFC 9309 robots.txt matcher is not active in this process ({why}); start Python "
            "with src/ on PYTHONPATH or install the package so gegenprobe-robots9309.pth runs; see docs/runbook.md)")


def _is_local(net, url) -> bool:
    if not isinstance(url, str):
        return False
    try:
        url = net.local_exports(url)
    except Exception:
        pass
    return url.startswith("file:")


def patch_net(net) -> None:
    """Wrap net.open_url and net.allowed with the request-time matcher check (idempotent). Markers of wrappers already
    on open_url (e.g. compliance/mirror.py's) are carried over, so their installed() checks keep working."""
    if not any(getattr(f, _MARK, False) for f in _chain(net.open_url)):
        orig_open = net.open_url

        def open_url(url, *a, **kw):
            if not _is_local(net, url) and not matcher_active():
                raise net.Disallowed(_refusal(url), kind=KIND)
            return orig_open(url, *a, **kw)

        for k, v in vars(orig_open).items():
            if k.startswith("_gegenprobe_"):
                setattr(open_url, k, v)
        setattr(open_url, _MARK, True)
        open_url.__wrapped__ = orig_open
        open_url.__doc__ = orig_open.__doc__
        net.open_url = open_url
    if not any(getattr(f, _MARK, False) for f in _chain(net.allowed)):
        orig_allowed = net.allowed

        def allowed(url):
            if not _is_local(net, url) and not matcher_active():
                return False
            return orig_allowed(url)

        setattr(allowed, _MARK, True)
        allowed.__wrapped__ = orig_allowed
        allowed.__doc__ = orig_allowed.__doc__
        net.allowed = allowed


def _load(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def _note(msg: str) -> None:
    _errors.append(msg)
    print(f"[gegenprobe] {msg}; every network fetch will be refused (kind {KIND})", file=sys.stderr)


def _patch_module(net, mirror) -> None:
    """Guard first, then the OPD-copy routing on top (mirror.installed(net) checks the outermost wrapper)."""
    try:
        patch_net(net)
    except Exception as e:  # cannot wrap: make net refuse every network URL by itself
        _note(f"fetch guard NOT installed: {type(e).__name__}: {e}")
        net.allowed = lambda url: _is_local(net, url)
    if mirror is not None:
        try:
            mirror.patch_net(net)
        except Exception as e:  # the guard still holds; disallowed originals are refused by the matcher
            print(f"[gegenprobe] OPD mirror patch NOT installed: {type(e).__name__}: {e}", file=sys.stderr)


class _NetHook(importlib.abc.MetaPathFinder):
    """After gegenprobe.net executes: the fetch guard, then the OPD-copy routing."""

    def __init__(self, mirror):
        self.mirror = mirror

    def find_spec(self, name, path=None, target=None):
        if name != "gegenprobe.net":
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return spec
        run = spec.loader.exec_module

        def exec_module(module, _run=run):
            _run(module)
            _patch_module(module, self.mirror)

        spec.loader.exec_module = exec_module
        return spec


def boot(pkg_dir: str | None = None) -> None:
    """Interpreter start (sitecustomize or the .pth). Idempotent across both: the first caller wins."""
    if getattr(sys, "_gegenprobe_booted", False):
        return
    sys._gegenprobe_booted = True
    pkg = pkg_dir or _PKG
    try:
        _load("_gegenprobe_robots9309", os.path.join(pkg, "robots9309.py")).install()
    except Exception as e:
        _note(f"RFC 9309 robots.txt patch NOT installed: {type(e).__name__}: {e}")
    mirror = None
    try:
        mirror = _load("_gegenprobe_mirror", os.path.join(pkg, "compliance", "mirror.py"))
    except Exception as e:
        print(f"[gegenprobe] OPD mirror routing NOT loaded: {type(e).__name__}: {e}", file=sys.stderr)
    if "gegenprobe.net" in sys.modules:
        _patch_module(sys.modules["gegenprobe.net"], mirror)
    sys.meta_path.insert(0, _NetHook(mirror))


PTH_LINE = ('import importlib.util as u, os; s = u.find_spec("gegenprobe"); '
            'f = s and os.path.join(list(s.submodule_search_locations)[0], "compliance", "fetchguard.py"); '
            'm = f and os.path.exists(f) and u.spec_from_file_location("_gegenprobe_fetchguard", f); '
            'g = m and u.module_from_spec(m); g and (m.loader.exec_module(g), g.boot_from_site())')


def boot_from_site() -> None:
    """Called by the .pth line (PTH_LINE) on this file loaded by path: boot, never raising."""
    try:
        boot()
    except Exception as e:  # never break interpreter start; ensure() and the guard refuse fetches instead
        print(f"[gegenprobe] boot from site-packages failed: {type(e).__name__}: {e}", file=sys.stderr)


def ensure() -> bool:
    """Called at import by every unlocked module that fetches through gegenprobe.net: install the matcher, the guard and
    the OPD-copy routing in this process if interpreter start did not (idempotent, never raises). Returns
    matcher_active()."""
    try:
        from gegenprobe import net
    except Exception:
        return matcher_active()
    try:
        from gegenprobe import robots9309
        robots9309.install()
    except Exception as e:
        _note(f"RFC 9309 robots.txt patch NOT installed: {type(e).__name__}: {e}")
    mirror = sys.modules.get("_gegenprobe_mirror")
    if mirror is None:
        try:
            from gegenprobe.compliance import mirror
        except Exception:
            mirror = None
    _patch_module(net, mirror)
    return matcher_active()
