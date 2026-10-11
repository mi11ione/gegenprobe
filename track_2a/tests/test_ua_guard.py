"""Round 8: a GP_USER_AGENT with an e-mail address is refused, fail-closed, before any request (contacts must be a URL)."""
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from gegenprobe import net
from gegenprobe.compliance import fetchguard

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("ua,bad", [
    ("hackapertus-research/0.1 (+https://github.com/mi11ione/gegenprobe)", False),
    ("opd-gegenprobe/0.1 (+https://openparldata.ch/contact)", False),
    ("hackapertus-research/0.1", False),
    ("bot/1.0 (+https://github.com/@someone)", False),      # an @ in a URL path is not an address
    ("bot/1.0 (ops@example.org)", True),
    ("bot/1.0 (+mailto:ops@example.org)", True),
    ("bot/1.0 (contact: First.Last+bot@sub.example.co.uk)", True),
    ("bot/1.0 (mailto:)", True),
])
def test_ua_problem(ua, bad):
    msg = fetchguard.ua_problem(ua)
    assert bool(msg) is bad
    if bad:
        assert "e-mail address" in msg and "https://" in msg  # says what to do instead


def test_email_user_agent_refuses_every_fetch_before_any_request(monkeypatch, tmp_path):
    real = urllib.request.urlopen

    def boom(req, *a, **k):
        url = req if isinstance(req, str) else req.full_url
        if not url.startswith("file:"):
            raise AssertionError("network touched")
        return real(req, *a, **k)

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(net, "UA", "bot/1.0 (ops@example.org)")
    for call in (lambda: net.get("https://files.openparldata.ch/exports/index.json"),
                 lambda: net.open_url("https://example.org/a.pdf")):
        with pytest.raises(net.Disallowed) as e:
            call()
        assert e.value.kind == fetchguard.UA_KIND and "contains an e-mail address" in str(e.value)
    assert net.allowed("https://example.org/") is False
    f = tmp_path / "x.txt"  # local files are not requests and still read
    f.write_text("local")
    assert net.get(f.as_uri()) == b"local"


def test_nightly_network_night_stops_with_a_clear_error(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "GP_WORK": str(tmp_path / "w"), "GP_MONITOR_OUT": str(tmp_path / "r"),
           "GP_USER_AGENT": "bot/1.0 (ops@example.org)", "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}",
           "PYTHONDONTWRITEBYTECODE": "1"}
    code = ("import urllib.request\n"
            "def _boom(*a, **k): raise AssertionError('network touched')\n"
            "urllib.request.urlopen = _boom\n"
            "import sys; from gegenprobe.monitor import nightly; sys.exit(nightly.main(['run']))\n")
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert p.returncode == 1, p.stderr[-2000:]
    assert "contains an e-mail address" in p.stderr and "Traceback" not in p.stderr

