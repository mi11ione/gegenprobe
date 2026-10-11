"""robots.txt under RFC 9309 (gegenprobe/robots9309.py, installed process-wide by src/sitecustomize.py): longest match,
allow wins ties, `*` and `$`, merged groups; net.allowed() refuses what the site disallows; and sitecustomize is loaded in
the environment of every entry point. Offline: robots.txt texts are inline, urlopen is stubbed."""
import io
import os
import re
import subprocess
import sys
import urllib.robotparser
from pathlib import Path

import pytest

from gegenprobe import net, robots9309
from gegenprobe.repair.adapters import robots as adapter_robots

ROOT = Path(__file__).resolve().parents[1]
UA = "hackapertus-research/0.1"
# www4.ti.ch/robots.txt as read on 10 Oct 2026 (the group that matters; the GPTBot group shows group selection)
TI_ROBOTS = """User-agent: *
Allow: /
Disallow: /poteri/gc/ricerca-messaggi-e-atti/ricerca/
Disallow: /user_librerie/php/GC/allegato.php

User-agent: GPTBot
Disallow: /
"""
TI_FETCHED = [f"https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid={i}" for i in (115005, 119023, 137701)]


def ok(text: str, path: str, ua: str = UA) -> bool:
    return robots9309.decide(robots9309.parse(text, ua), path)


# ---------------------------------------------------------------- the matcher
def test_ti_longest_match_disallows_allegato_although_allow_slash_comes_first():
    for u in TI_FETCHED:
        assert not robots9309.allowed_by(TI_ROBOTS, UA, u)
    assert ok(TI_ROBOTS, "/poteri/gc/") and ok(TI_ROBOTS, "/")
    assert not ok(TI_ROBOTS, "/poteri/gc/ricerca-messaggi-e-atti/ricerca/?q=x")
    assert not ok(TI_ROBOTS, "/", "GPTBot/1.0")  # a group naming the product token replaces the * group
    # the stdlib's first-match parser, as gegenprobe.net used it until 11 Oct 2026, lets the three files through
    rp = urllib.robotparser.RobotFileParser()
    robots9309._ORIG_PARSE(rp, TI_ROBOTS.splitlines())
    assert all(robots9309._ORIG_CAN_FETCH(rp, UA, u) for u in TI_FETCHED)


@pytest.mark.parametrize("path,allowed", [
    ("/a/b.pdf", False),          # Disallow: /*.pdf$
    ("/a/b.pdf?x=1", True),       # $ anchors the end: a query after .pdf no longer matches
    ("/a/b.pdfx", True),
    ("/public/b.pdf", True),      # Allow: /public/*.pdf$ is longer than /*.pdf$
    ("/route/x", False),
    ("/x/private/y/z.html", False),  # Disallow: /*/private/
    ("/x/private", True),
    ("/fish", False), ("/fish.html", False), ("/fish/salmon", False), ("/Fish", True),  # Disallow: /fish (prefix)
    ("/shop$/a", False),          # a $ that is not last is a literal character
])
def test_wildcards_and_dollar(path, allowed):
    text = ("User-agent: *\nDisallow: /*.pdf$\nAllow: /public/*.pdf$\nDisallow: /route/\nDisallow: /*/private/\n"
            "Disallow: /fish\nDisallow: /shop$/\n")
    assert ok(text, path) is allowed


def test_allow_wins_a_tie_and_longer_disallow_beats_allow():
    assert ok("User-agent: *\nDisallow: /page\nAllow: /page\n", "/page")
    assert ok("User-agent: *\nAllow: /page\nDisallow: /page\n", "/page.html")
    assert ok("User-agent: *\nDisallow: /folde*\nAllow: /folder\n", "/folder/a")  # 7 octets each: allow
    assert not ok("User-agent: *\nAllow: /folder\nDisallow: /folder/\n", "/folder/a")


def test_empty_disallow_allows_and_robots_txt_is_implicitly_allowed():
    assert ok("User-agent: *\nDisallow:\n", "/anything")
    assert ok("User-agent: *\nDisallow: /\n", "/robots.txt")
    assert not ok("User-agent: *\nDisallow: /\n", "/robots.txt.bak")
    assert ok("Disallow: /\nUser-agent: *\nAllow: /x\n", "/y")  # a rule before any user-agent line belongs to no group


def test_groups_for_the_same_agent_are_merged_and_matched_by_product_token():
    text = ("User-agent: hackapertus-research\nDisallow: /a/\n\nUser-agent: other\nDisallow: /\n\n"
            "User-agent: HACKAPERTUS-RESEARCH\nUser-agent: x\nDisallow: /b/\n\nUser-agent: *\nDisallow: /c/\n")
    assert not ok(text, "/a/1") and not ok(text, "/b/1") and ok(text, "/c/1")
    assert not ok(text, "/c/1", "someone-else/2.0") and ok(text, "/a/1", "someone-else/2.0")
    assert ok("User-agent: hackapertus\nDisallow: /\n", "/x")  # a prefix of our token names another agent


def test_percent_encoding_is_compared_in_one_normal_form():
    assert not ok("User-agent: *\nDisallow: /%7Euser/\n", "/~user/a")
    assert not ok("User-agent: *\nDisallow: /~user/\n", "/%7euser/a")
    assert not ok("User-agent: *\nDisallow: /zürich/\n", "/z%C3%BCrich/a")
    assert not ok("User-agent: *\nDisallow: /a%2fb\n", "/a%2Fb/c")  # an escaped reserved character stays escaped
    assert ok("User-agent: *\nDisallow: /a%2Fb\n", "/a/b")


# ---------------------------------------------------------------- the patched stdlib parser, and net.allowed()
def test_urllib_robotparser_is_patched_in_this_process():
    assert robots9309.installed()
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(TI_ROBOTS.splitlines())
    assert not any(rp.can_fetch(UA, u) for u in TI_FETCHED) and rp.can_fetch(UA, "https://www4.ti.ch/poteri/gc/")
    rp.disallow_all = True  # what net sets for an unreachable robots.txt: still fail-closed
    assert not rp.can_fetch(UA, "https://www4.ti.ch/")
    assert not urllib.robotparser.RobotFileParser().can_fetch(UA, "https://x/")  # not read yet: nothing allowed


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def ti_net(monkeypatch):
    monkeypatch.setattr(net, "_robots", {})
    monkeypatch.setattr(net, "_robots_note", {})
    monkeypatch.setattr(net, "_robots_lenient", {})
    monkeypatch.setattr(net, "_wait", lambda host: None)
    if hasattr(net.open_url, "__wrapped__"):  # OPD-copy routing off: these tests check net's own robots.txt refusal
        monkeypatch.setitem(net.open_url.__globals__, "_map", {})
    seen = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        seen.append(url)
        if url == "https://www4.ti.ch/robots.txt":
            return _Resp(TI_ROBOTS.encode())
        pytest.fail(f"a document request reached the network: {url}")

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_net_refuses_the_ti_allegato_urls(ti_net):
    for u in TI_FETCHED:
        assert not net.allowed(u)
        with pytest.raises(net.Disallowed) as e:
            net.get(u)
        assert e.value.kind == "robots_disallowed"
    assert net.allowed("https://www4.ti.ch/poteri/gc/")
    assert ti_net == ["https://www4.ti.ch/robots.txt"]  # robots.txt read once, no document fetched


def test_adapter_check_and_net_use_the_same_matcher(monkeypatch):
    monkeypatch.setattr(adapter_robots, "_rules", {})
    monkeypatch.setattr(adapter_robots.net, "get", lambda url, **kw: TI_ROBOTS.encode())
    assert adapter_robots.decide is robots9309.decide and adapter_robots.parse is robots9309.parse
    assert not any(adapter_robots.allowed(u) for u in TI_FETCHED)


# ---------------------------------------------------------------- sitecustomize in every entry point's environment
def _pythonpath_of(entry: str) -> tuple[str, Path]:
    """(PYTHONPATH, working directory) as each entry point sets them, read from the committed files."""
    if entry == "make":  # Makefile: export PYTHONPATH := src:.  (make test/run-host targets, cwd = track_2a)
        m = re.search(r"^export PYTHONPATH := (.+)$", (ROOT / "Makefile").read_text(), re.M)
        return m.group(1).strip(), ROOT
    if entry == "docker":  # Dockerfile ENV (make run, the Docker nightly unit, nightly-smoke): /app = this directory
        m = re.search(r"PYTHONPATH=(\S+)", (ROOT / "Dockerfile").read_text())
        return m.group(1).replace("/app", str(ROOT)), ROOT
    if entry == "venv-unit":  # deploy/nightly/gegenprobe-nightly-venv.service, WorkingDirectory=/var/lib/gegenprobe
        unit = (ROOT / "deploy/nightly/gegenprobe-nightly-venv.service").read_text()
        m = re.search(r"^Environment=PYTHONPATH=(\S+)", unit, re.M)
        return m.group(1).replace("/opt/gegenprobe/track_2a", str(ROOT)), Path("/")
    if entry == "nightly-subprocess":  # monitor/nightly.py and monitor/smoke.py: PYTHONPATH=<ROOT>/src
        src = (ROOT / "src/gegenprobe/monitor/nightly.py").read_text()
        assert 'PYTHONPATH=str(ROOT / "src")' in src
        return str(ROOT / "src"), Path("/")
    raise KeyError(entry)


@pytest.mark.parametrize("entry", ["make", "docker", "venv-unit", "nightly-subprocess"])
def test_sitecustomize_patches_robotparser_in_every_entry_point(entry):
    pp, cwd = _pythonpath_of(entry)
    code = ("import urllib.robotparser as r, sys; from gegenprobe import net; "
            "rp = r.RobotFileParser(); rp.parse(sys.argv[1].splitlines()); "
            "print(r.RobotFileParser.can_fetch.__module__, rp.can_fetch(net.UA, sys.argv[2]))")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONNOUSERSITE")}
    env.update(PYTHONPATH=pp, PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, "-c", code, TI_ROBOTS, TI_FETCHED[0]], env=env, cwd=cwd, capture_output=True,
                         text=True, check=True)
    assert out.stdout.split() == ["_gegenprobe_robots9309", "False"], out.stderr
    assert "NOT installed" not in out.stderr


def test_pytest_itself_runs_with_sitecustomize_when_started_like_make_test():
    if "src" not in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        pytest.skip("started without PYTHONPATH=src (tests/conftest.py installs the patch instead)")
    assert "_gegenprobe_robots9309" in sys.modules
