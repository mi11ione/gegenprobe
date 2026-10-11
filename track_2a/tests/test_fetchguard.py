"""Fail-closed fetch guard (gegenprobe/compliance/fetchguard.py): no request leaves gegenprobe.net unless the RFC 9309
robots.txt matcher is active; the guard reaches every start-up path (sitecustomize, the installed .pth, ensure() in every
unlocked fetch module). Offline: urlopen is stubbed to fail loudly, so a refused fetch never touches the network."""
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.robotparser
from pathlib import Path

import pytest

from gegenprobe import net
from gegenprobe.compliance import fetchguard
from gegenprobe.convert import output

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
NO_NET = ("import urllib.request\n"
          "def _boom(*a, **k): raise AssertionError('network touched')\n"
          "urllib.request.urlopen = _boom\n")


def _stdlib_matcher(monkeypatch):
    """Simulate the RFC 9309 patch missing in this process: RobotFileParser back to the stdlib's first match."""
    cls = urllib.robotparser.RobotFileParser
    monkeypatch.setattr(cls, "can_fetch", cls.can_fetch._rfc9309_orig)
    monkeypatch.setattr(cls, "parse", cls.parse._rfc9309_orig)
    assert not fetchguard.matcher_active()


def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network touched")
    monkeypatch.setattr(urllib.request, "urlopen", boom)


# ---------------------------------------------------------------- in this process
def test_guard_is_installed_and_matcher_active_under_pytest():
    assert fetchguard.matcher_active() and fetchguard.installed(net)
    assert sys.modules["_gegenprobe_mirror"].installed(net) if "_gegenprobe_mirror" in sys.modules else True


def test_matcher_missing_refuses_every_fetch_before_any_request(monkeypatch):
    _stdlib_matcher(monkeypatch)
    _no_network(monkeypatch)
    for call in (lambda: net.get("https://www4.ti.ch/poteri/gc/"), lambda: net.open_url("https://example.org/a.pdf"),
                 lambda: list(net.stream_ndjson_gz("https://files.openparldata.ch/exports/docs/docs_1.ndjson.gz"))):
        with pytest.raises(net.Disallowed) as e:
            call()
        assert e.value.kind == fetchguard.KIND and "RFC 9309" in str(e.value)
    assert net.allowed("https://example.org/") is False


def test_matcher_missing_typed_failure_row(monkeypatch):
    _stdlib_matcher(monkeypatch)
    _no_network(monkeypatch)
    from gegenprobe.convert import batch
    row = batch.convert_one("https://example.org/doc.pdf")
    assert row["status"] == "robots_matcher_inactive" and "RFC 9309" in row["reason"]
    assert "robots_matcher_inactive" in output.FAILURE_KINDS


def test_local_files_still_read_when_matcher_missing(monkeypatch, tmp_path):
    _stdlib_matcher(monkeypatch)
    f = tmp_path / "x.txt"
    f.write_text("local")
    assert net.get(f.as_uri()) == b"local"


def test_guard_keeps_the_mirror_marker_and_is_idempotent():
    before = net.open_url
    fetchguard.patch_net(net)
    fetchguard.ensure()
    assert net.open_url is before


# ---------------------------------------------------------------- fresh interpreters without / with each start-up path
def _run(code: str, *, pythonpath: str | None = None, isolated: bool = True, cwd: Path = ROOT):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "GP_EXPORTS_DIR")}
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    args = [sys.executable] + (["-I"] if isolated else []) + ["-c", code]
    return subprocess.run(args, env=env, cwd=cwd, capture_output=True, text=True, timeout=120)


def test_no_startup_hook_unlocked_fetch_module_installs_the_guard():
    """-I: no PYTHONPATH, so no sitecustomize and no .pth. Importing an unlocked fetch module (convert.output, as the
    convert CLI does) runs fetchguard.ensure(): matcher, guard and mirror routing are installed before any fetch."""
    code = (f"import sys; sys.path[:0] = [{str(SRC)!r}, {str(ROOT)!r}]\n" + NO_NET +
            "from gegenprobe import net\n"
            "import urllib.robotparser as r\n"
            "print('before', getattr(r.RobotFileParser.can_fetch, '_gegenprobe_rfc9309', False))\n"
            "from gegenprobe.convert import output\n"
            "from gegenprobe.compliance import fetchguard as g\n"
            "print('after', g.matcher_active(), g.installed(net))\n")
    p = _run(code)
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["before", "False", "after", "True", "True"]


def test_no_startup_hook_and_matcher_unavailable_fetch_refused():
    """The hook is missing AND the RFC 9309 module cannot be imported: ensure() still installs the guard, every network
    fetch is refused with robots_matcher_inactive, and stderr says why."""
    code = (f"import sys; sys.path[:0] = [{str(SRC)!r}, {str(ROOT)!r}]\n" + NO_NET +
            "import importlib.abc\n"
            "class Block(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'gegenprobe.robots9309': raise ImportError('simulated: robots9309 missing')\n"
            "sys.meta_path.insert(0, Block())\n"
            "from gegenprobe import net\n"
            "from gegenprobe.compliance import fetchguard as g\n"
            "print('active', g.ensure(), 'guard', g.installed(net))\n"
            "try:\n"
            "    net.get('https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid=115005')\n"
            "except net.Disallowed as e:\n"
            "    print('refused', e.kind)\n"
            "print('allowed', net.allowed('https://example.org/'))\n")
    p = _run(code)
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["active", "False", "guard", "True", "refused", "robots_matcher_inactive", "allowed", "False"]
    assert "NOT installed" in p.stderr and "simulated: robots9309 missing" in p.stderr


def test_boot_with_unloadable_matcher_refuses(tmp_path):
    """What sitecustomize / the .pth do when robots9309.py cannot be loaded: boot() notes it, the meta-path hook still
    wraps gegenprobe.net at import, and nothing is fetched (previously: a warning, then fetches under urllib's matcher)."""
    code = (f"import sys; sys.path[:0] = [{str(SRC)!r}]\n" + NO_NET +
            "import importlib.util as u\n"
            f"s = u.spec_from_file_location('_gegenprobe_fetchguard', {str(SRC / 'gegenprobe/compliance/fetchguard.py')!r})\n"
            "g = u.module_from_spec(s); sys.modules[s.name] = g; s.loader.exec_module(g)\n"
            f"g.boot({str(tmp_path)!r})  # a package dir without robots9309.py\n"
            "from gegenprobe import net\n"
            "print('guard', g.installed(net), 'active', g.matcher_active())\n"
            "try:\n"
            "    net.get('https://example.org/x.pdf')\n"
            "except net.Disallowed as e:\n"
            "    print('refused', e.kind)\n")
    p = _run(code)
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["guard", "True", "active", "False", "refused", "robots_matcher_inactive"]
    assert "RFC 9309 robots.txt patch NOT installed" in p.stderr


def test_sitecustomize_boots_guard_and_reverting_the_matcher_refuses():
    """PYTHONPATH=src (Makefile, Dockerfile, units): sitecustomize boots the matcher, the guard and the mirror routing at
    interpreter start; if anything later reverts the matcher, the next fetch is refused."""
    code = (NO_NET +
            "import sys, urllib.robotparser as r\n"
            "from gegenprobe import net\n"
            "g = sys.modules['_gegenprobe_fetchguard']\n"
            "print(r.RobotFileParser.can_fetch.__module__, g.installed(net), sys.modules['_gegenprobe_mirror'].installed(net))\n"
            "r.RobotFileParser.can_fetch = r.RobotFileParser.can_fetch._rfc9309_orig\n"
            "try:\n"
            "    net.get('https://example.org/x.pdf')\n"
            "except net.Disallowed as e:\n"
            "    print('refused', e.kind)\n")
    p = _run(code, pythonpath=f"{SRC}{os.pathsep}{ROOT}", isolated=False, cwd=Path("/"))
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["_gegenprobe_robots9309", "True", "True", "refused", "robots_matcher_inactive"]


def test_installed_pth_boots_without_pythonpath(tmp_path):
    """A non-editable install: site-packages holds the gegenprobe package and gegenprobe-robots9309.pth (setup.py). Python
    runs the .pth at start-up (site.addsitedir does the same processing); no PYTHONPATH, no sitecustomize."""
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    (site_dir / "gegenprobe").symlink_to(SRC / "gegenprobe", target_is_directory=True)
    (site_dir / fetchguard_pth()).write_text((SRC / fetchguard_pth()).read_text())
    code = (NO_NET +
            f"import site; site.addsitedir({str(site_dir)!r})\n"
            "import sys, urllib.robotparser as r\n"
            "print(getattr(sys, '_gegenprobe_booted', False), r.RobotFileParser.can_fetch.__module__)\n"
            "from gegenprobe import net\n"
            "print(sys.modules['_gegenprobe_fetchguard'].installed(net) if '_gegenprobe_fetchguard' in sys.modules\n"
            "      else __import__('gegenprobe.compliance.fetchguard').compliance.fetchguard.installed(net))\n")
    p = _run(code, cwd=Path("/"))
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["True", "_gegenprobe_robots9309", "True"], p.stderr
    assert "Error processing line" not in p.stderr


def fetchguard_pth() -> str:
    """The .pth file name setup.py ships."""
    return re.search(r'PTH = "([^"]+)"', (ROOT / "setup.py").read_text()).group(1)


def test_pth_file_is_the_documented_line_and_shipped_by_setup_py():
    pth = fetchguard_pth()
    assert pth == "gegenprobe-robots9309.pth"
    assert (SRC / pth).read_text().strip() == fetchguard.PTH_LINE
    assert (SRC / pth).read_text().startswith("import ")  # site executes only lines that start with "import"
    setup = (ROOT / "setup.py").read_text()
    assert "build_py" in setup and "self.build_lib" in setup
    assert 'build-backend = "setuptools.build_meta"' in (ROOT / "pyproject.toml").read_text()


# ---------------------------------------------------------------- every unlocked fetch module calls ensure()
def _locked() -> set[str]:
    out: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v):
                    out.add(k)
                else:
                    walk(v)
    for f in glob.glob(str(ROOT / "eval" / "prereg*" / "LOCK*")):
        walk(json.loads(Path(f).read_text()))
    return out


NET_IMPORT = re.compile(r"^\s*(from\s+(\.+|gegenprobe)\s+import\s+[^\n]*\bnet\b|import\s+gegenprobe\.net\b)", re.M)


def test_every_unlocked_module_that_imports_net_calls_ensure():
    locked = _locked()
    missing, seen = [], 0
    for base in ("src/gegenprobe", "eval", "tools", "report"):
        for f in sorted((ROOT / base).rglob("*.py")):
            rel = str(f.relative_to(ROOT))
            src = f.read_text(encoding="utf-8")
            if rel in locked or not NET_IMPORT.search(src) or rel.endswith("fetchguard.py"):
                continue
            seen += 1
            if "fetchguard.ensure()" not in src:
                missing.append(rel)
    assert seen >= 15 and not missing, missing
    # the locked ones rely on interpreter start (sitecustomize / the .pth); they are the only exceptions
    assert {"src/gegenprobe/pdftext.py", "src/gegenprobe/hardening.py"} <= locked
