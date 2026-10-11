"""Round-4 ops fixes: `make run` container flags and uid mapping, the failure notifier (one alert per event), the
User-Agent contact note, the CI supply-chain pins, and the real-night workflow."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
WORKFLOWS = REPO / ".github" / "workflows"


# ------------------------------------------------------------------------------------------------ make run (Docker)
def _fake_bin(d: Path, uid: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "id").write_text(f'#!/bin/sh\ncase "$1" in -u) echo {uid};; -g) echo {uid};; *) /usr/bin/id "$@";; esac\n')
    (d / "docker").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$DOCKER_ARGS_OUT.$1"\n')
    (d / "chown").write_text('#!/bin/sh\necho "$@" > "$DOCKER_ARGS_OUT.chown"\n')
    for f in d.iterdir():
        f.chmod(0o755)


@pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
@pytest.mark.parametrize("uid,want_user", [("0", "10001:0"), ("1001", "1001:1001")])
def test_make_run_never_passes_uid_0_and_hardens_the_container(tmp_path, uid, want_user):
    _fake_bin(tmp_path / "bin", uid)
    rec = tmp_path / "args"
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", DOCKER_ARGS_OUT=str(rec))
    p = subprocess.run(["make", "-s", "run", f"RUN_OUT={tmp_path / 'out'}", f"RUN_WORK={tmp_path / 'work'}"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    args = (tmp_path / "args.run").read_text().splitlines()
    assert args[args.index("--user") + 1] == want_user
    for flag in ("--read-only", "--rm"):
        assert flag in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges"
    assert args[args.index("--tmpfs") + 1].startswith("/tmp:")
    vols = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    assert f"{tmp_path / 'out'}:/app/out" in vols and f"{tmp_path / 'work'}:/var/gegenprobe/work" in vols
    assert "GP_WORK=/var/gegenprobe/work" in args
    chowned = (tmp_path / "args.chown").exists()
    assert chowned == (uid == "0")  # a root caller hands out/ and the work dir to uid 10001 before the run


# ------------------------------------------------------------------------------------------------ failure notifier
def _systemd_unquote_single(raw: str) -> str:
    """One single-quoted ExecStart word as systemd unquotes it (systemd.syntax(7) "Quoting"): C-style backslash escapes
    are processed inside the quotes too, and "$$" is a literal "$"."""
    out, i = [], 0
    esc = {"\\": "\\", '"': '"', "'": "'", "n": "\n", "t": "\t"}
    while i < len(raw):
        c = raw[i]
        if c == "\\":
            assert raw[i + 1] in esc, f"unsupported escape \\{raw[i + 1]}"
            out.append(esc[raw[i + 1]])
            i += 2
            continue
        assert c != "'", "unescaped quote inside the word"
        out.append(c)
        i += 1
    return "".join(out).replace("$$", "$")


def _notifier_script(curl: Path) -> str:
    """The notifier's ExecStart as systemd hands it to /bin/sh (continuation lines joined with a space, then unquoted)."""
    unit = (ROOT / "deploy/nightly/gegenprobe-nightly-failure.service").read_text()
    line = re.search(r"^ExecStart=(.*?[^\\])$", re.sub(r"\\\n", " ", unit), re.M).group(1)
    m = re.fullmatch(r"/bin/sh -c '(.*)'", line.strip())
    assert m and "%" not in m.group(1)  # one quoted word; no systemd specifiers hidden in the shell text
    return _systemd_unquote_single(m.group(1)).replace("/usr/bin/curl", str(curl))


@pytest.mark.parametrize("status,alert_exit,posts", [
    ("3", None, False),   # alerts: the job delivered them; the notifier stays silent (one alert per event)
    ("5", "5", False),    # same with a custom GP_ALERT_EXIT
    ("1", None, True),    # job or delivery failure: one post
    ("2", None, True),    # empty cache
    ("", None, True),     # systemd < 251 passes no exit status: post (previous behaviour)
])
def test_failure_notifier_posts_once_per_event(tmp_path, status, alert_exit, posts):
    curl = tmp_path / "curl"
    curl.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path / "posted"}\n')
    curl.chmod(0o755)
    env = dict(PATH="/usr/bin:/bin", GP_ALERT_WEBHOOK="https://hooks.example.org/x", MONITOR_SERVICE_RESULT="exit-code")
    if status:
        env["MONITOR_EXIT_STATUS"] = status
    if alert_exit:
        env["GP_ALERT_EXIT"] = alert_exit
    p = subprocess.run(["/bin/sh", "-c", _notifier_script(curl)], env=env, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    assert (tmp_path / "posted").exists() == posts, p.stdout
    if posts:
        import json
        argv = (tmp_path / "posted").read_text()
        body = argv[argv.index("-d ") + 3:argv.rindex(" https://")]
        assert json.loads(body)["text"].startswith("gegenprobe-nightly on ")


# ------------------------------------------------------------------------------------------------ User-Agent
def test_user_agent_contact_note(monkeypatch):
    from gegenprobe import net
    from gegenprobe.monitor import nightly

    monkeypatch.delenv("GP_USER_AGENT", raising=False)
    monkeypatch.setattr(net, "UA", "hackapertus-research/0.1")
    ua = nightly.user_agent()
    assert ua == dict(value="hackapertus-research/0.1", has_contact=False, source="default")
    assert "GP_USER_AGENT" in nightly.ua_note(ua)
    monkeypatch.setenv("GP_USER_AGENT", "x")
    monkeypatch.setattr(net, "UA", "hackapertus-research/0.1 (+https://github.com/mi11ione/gegenprobe)")
    assert nightly.user_agent()["has_contact"] and nightly.ua_note(nightly.user_agent()) is None
    # round 8: an e-mail address is not a contact; the fetch guard refuses it (tests/test_ua_guard.py)
    monkeypatch.setattr(net, "UA", "opd/1.0 (data@example.org)")
    assert not nightly.user_agent()["has_contact"]


# ------------------------------------------------------------------------------------------------ CI supply chain
def _workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


@pytest.mark.skipif(not WORKFLOWS.exists(), reason="workflows live in the repository root")
def test_every_action_is_pinned_to_a_commit_sha_with_its_version():
    uses = [(f.name, line.strip()) for f in _workflows() for line in f.read_text().splitlines() if "uses:" in line]
    assert uses
    bad = [u for u in uses if not re.search(r"uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$", u[1])]
    assert bad == []


@pytest.mark.skipif(not WORKFLOWS.exists(), reason="workflows live in the repository root")
def test_ci_verifies_gitleaks_and_installs_with_hashes():
    ci = (WORKFLOWS / "ci.yml").read_text()
    assert "sha256sum -c" in ci and re.search(r"GITLEAKS_SHA256=[0-9a-f]{64}", ci)
    assert "pip install --require-hashes -r requirements.lock -r requirements-dev.lock" in ci
    assert "pip install -r requirements.txt" not in ci
    lock = (ROOT / "requirements-dev.lock").read_text()
    assert re.search(r"^ruff==0\.16\.10 \\$", lock, re.M) and len(re.findall(r"--hash=sha256:[0-9a-f]{64}", lock)) >= 2


@pytest.mark.skipif(not WORKFLOWS.exists(), reason="workflows live in the repository root")
def test_nightly_real_workflow_is_manual_polite_and_runs_under_systemd():
    w = (WORKFLOWS / "nightly-real.yml").read_text()
    assert re.search(r"^on:\s*\n\s+workflow_dispatch:\s*\n\S", w, re.M)  # manual only: no schedule, push or PR
    assert 'UA: "hackapertus-research/0.1 (+https://github.com/mi11ione/gegenprobe)"' in w
    assert "printf 'GP_USER_AGENT=%s\\n' \"$UA\" | sudo tee -a /etc/gegenprobe/alerts.env" in w
    assert "install.sh --venv" in w and "systemctl start gegenprobe-nightly.service" in w
    assert "--require-hashes -r" in w
    assert "run.json" in w and "journal" in w
