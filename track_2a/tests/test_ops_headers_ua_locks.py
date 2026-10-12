"""Operations: the evidence site's security headers (gegenprobe.viewer.headers), the required contact User-Agent in the
deploy template and install.sh, the dev lock that installs pytest, and the PDF's metadata title. No network, no model."""
import re
import subprocess
from pathlib import Path

import pytest

from gegenprobe.monitor import nightly
from gegenprobe.viewer import headers as H

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


# ------------------------------------------------------------------------------------------------ site headers
def test_headers_hash_every_inline_block_and_allow_nothing_else(tmp_path):
    (tmp_path / "index.html").write_text("<html><head><style>body{color:red}</style>"
                                         "<script id='data' type='application/json'>{\"a\":1}</script>"
                                         "<script>console.log(1)</script><script src='x.js'></script></head></html>")
    text = H.render(tmp_path)
    csp = re.search(r"Content-Security-Policy: (.*)", text).group(1)
    assert "default-src 'self'" in csp and "'unsafe-inline'" not in csp.replace("style-src-attr 'unsafe-inline'", "")
    assert H._hash("console.log(1)") in csp and H._hash("body{color:red}") in csp
    assert H._hash('{"a":1}') not in csp  # the JSON data block is not executed
    for k in ("Strict-Transport-Security: max-age=31536000", "X-Content-Type-Options: nosniff",
              "Referrer-Policy: no-referrer", "frame-ancestors 'none'", "object-src 'none'"):
        assert k in text


def test_committed_site_headers_match_the_pages():
    assert (SITE / "_headers").read_text(encoding="utf-8") == H.render(SITE)


def test_deploy_ships_the_site_directory_with_its_headers():
    w = (ROOT / "deploy" / "site" / "wrangler.jsonc").read_text()
    assert '"directory": "../../site"' in w
    mk = (ROOT / "Makefile").read_text()
    assert "deploy-site: site" in mk and "gegenprobe.viewer build" in mk


# ------------------------------------------------------------------------------------------------ User-Agent
TEMPLATE = ROOT / "deploy" / "nightly" / "alerts.env.example"
INSTALL = ROOT / "deploy" / "nightly" / "install.sh"


def _template_ua() -> str:
    lines = [x for x in TEMPLATE.read_text().splitlines() if x.startswith("GP_USER_AGENT=")]
    assert len(lines) == 1, "one active GP_USER_AGENT line"
    return lines[0].split("=", 1)[1]


def test_template_contact_line_is_active_and_fails_closed():
    ua = _template_ua()
    assert nightly.contact_url(ua) is None
    assert nightly.ua_refusal(dict(value=ua, has_contact=False, source="GP_USER_AGENT"))


@pytest.mark.parametrize("ua,ok", [
    ("opd-gegenprobe/0.1 (+https://www.openparldata.ch)", True),
    ("hackapertus-research/0.1 (+https://github.com/mi11ione/gegenprobe)", True),
    ("hackapertus-research/0.1", False),
    ("x/0.1 (+https://example.org/contact)", False),
    ("x/0.1 (+https://localhost/)", False),
    ("x/0.1 (ops@example.ch)", False),
])
def test_install_sh_and_the_night_agree_on_a_contact(ua, ok, tmp_path):
    fn = re.search(r"^ua_ok\(\) \{.*?^\}", INSTALL.read_text(), re.S | re.M).group(0)
    script = tmp_path / "ua.sh"
    script.write_text(fn + '\nua_ok "$1"\n')
    r = subprocess.run(["sh", str(script), ua], capture_output=True)
    assert (r.returncode == 0) is ok
    night_ok = nightly.ua_refusal(dict(value=ua, has_contact=nightly.contact_url(ua) is not None, source="x")) is None
    assert night_ok is ok
    assert (r.returncode == 0) is ok and ("--user-agent" in INSTALL.read_text())


def test_install_sh_refuses_before_installing_units():
    s = INSTALL.read_text()
    check = s.index('if ! ua_ok "$UA_SET"; then')
    assert check < s.index("useradd --system") and check < s.index("\nsystemctl enable --now")
    assert "exit 1" in s[check:check + 600]


# ------------------------------------------------------------------------------------------------ locks and report
def test_test_tools_live_in_the_dev_lock_only():
    """The runtime lock (the image, the nightly venv) carries only what they import; pytest and its dependencies are
    hash-pinned in requirements-dev.lock, which installs on top of it (CI test job, make test)."""
    dev, run = (ROOT / "requirements-dev.lock").read_text(), (ROOT / "requirements.lock").read_text()

    def pins(s):
        return {m.group(1).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==(\S+) \\$", s, re.M)}

    for pkg in ("pytest", "iniconfig", "packaging", "pluggy", "pygments", "ruff"):
        assert re.search(rf"^{pkg}==\S+ \\\n(?:    --hash=sha256:[0-9a-f]{{64}}(?: \\)?\n)+", dev, re.M), pkg
        assert pkg not in pins(run), f"{pkg} is test-only: requirements-dev.lock, not requirements.lock"
    txt = {m.group(1).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==(\S+)$",
                                                                (ROOT / "requirements.txt").read_text(), re.M)}
    assert txt == pins(run), "requirements.txt and requirements.lock pin the same runtime set"
    assert not set(pins(dev)) & set(pins(run)), "no package is pinned in both locks"


def test_report_pdf_title_is_the_report_heading():
    pytest.importorskip("markdown")  # report rendering deps are not in the test job's lock
    from report import render

    md = (ROOT / "technical_report.md").read_text(encoding="utf-8")
    assert render.title(md) == re.search(r"^# (.+)$", md, re.M).group(1).strip()
    assert "<title>" in Path(render.__file__).read_text()
