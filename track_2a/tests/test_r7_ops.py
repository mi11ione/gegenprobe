"""Round-7 operations: the Docker unit mounts GP_EXPORTS_DIR, development paths come from the environment, the canary run
and template, licences over results/, the incident bound recomputed from the run snapshot. Offline."""
import json
import os
import re
from pathlib import Path

import pytest

from gegenprobe import devpaths

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
UNIT = ROOT / "deploy" / "nightly" / "gegenprobe-nightly.service"
MOUNT = "--mount type=bind,source=${GP_EXPORTS_DIR},target=${GP_EXPORTS_DIR},readonly"


# ------------------------------------------------------------------------------------------- 1 GP_EXPORTS_DIR in Docker
def test_docker_unit_mounts_the_exports_dir_read_only_at_the_same_path():
    u = UNIT.read_text()
    default = "Environment=GP_EXPORTS_DIR=/var/lib/gegenprobe/no-exports"
    # the default comes first, so a value in alerts.env (EnvironmentFile, read later) overrides it
    assert u.index(default) < u.index("EnvironmentFile=-/etc/gegenprobe/alerts.env")
    assert "ExecStartPre=/usr/bin/install -d -m 0755 /var/lib/gegenprobe/no-exports" in u
    start = u[u.index("ExecStart=/usr/bin/docker run"):u.index("ExecStopPost=")]
    assert MOUNT in start and "--env-file /etc/gegenprobe/alerts.env" in start
    assert start.index(MOUNT) < start.index("${GP_IMAGE}")


@pytest.mark.skipif(not (REPO / ".github").exists(), reason="workflows live in the repository root")
def test_ci_smoke_runs_a_local_exports_night_with_the_units_mount():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    job = ci[ci.index("  nightly-smoke:"):ci.index("  secrets:")]
    assert MOUNT in job and "--env-file" in job and "--network none" in job and "--read-only" in job
    assert "gegenprobe.monitor.nightly run" in job and "local-exports-check" in job
    assert "chmod -R a+rX,a-w" in job  # OPD's directory: readable, not writable


# ------------------------------------------------------------------------------------------- 2 development paths
def test_devpaths_from_environment_with_clear_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SPIKES_DIR", str(tmp_path / "nope"))
    monkeypatch.setenv("GP_GATEWAY_DIR", str(tmp_path / "gw"))
    assert devpaths.spikes() == tmp_path / "nope"
    with pytest.raises(devpaths.DevPathMissing, match="GP_SPIKES_DIR"):
        devpaths.require_spikes("x")
    monkeypatch.delitem(__import__("sys").modules, "gw", raising=False)
    with pytest.raises(devpaths.DevPathMissing, match="GP_GATEWAY_DIR.*openai"):
        devpaths.import_gw("x")
    monkeypatch.delenv("GP_SPIKES_DIR")
    assert devpaths.spikes() == ROOT.parent.parent / "spikes"  # default: next to the checkout, never a fixed home path


def test_no_unlocked_module_names_a_developer_path():
    from tests.test_fetchguard import _locked
    locked = _locked()
    bad = []
    for base in ("src", "eval", "tools", "report"):
        for f in (ROOT / base).rglob("*.py"):
            rel = str(f.relative_to(ROOT))
            if rel in locked or rel == "eval/devrun.py":  # devrun names the locked modules' literal prefixes to redirect them
                continue
            if re.search(r"/Users/|Desktop/hackapertus", f.read_text(encoding="utf-8")):
                bad.append(rel)
    assert not bad, bad


def test_devrun_redirects_the_locked_literal_paths(monkeypatch, tmp_path):
    from eval import devrun
    orig = os.path.expanduser
    try:
        devrun.install(dict(spikes=tmp_path / "s", gateway=tmp_path / "g"))
        assert os.path.expanduser("~/Desktop/hackapertus/spikes") == str(tmp_path / "s")
        assert os.path.expanduser("~/Desktop/hackapertus/spikes/round8/x.json") == str(tmp_path / "s" / "round8/x.json")
        assert os.path.expanduser("~/Desktop/hackapertus/gateway") == str(tmp_path / "g")
        assert os.path.expanduser("~/other") == orig("~/other")
    finally:
        os.path.expanduser = orig
    monkeypatch.setenv("GP_SPIKES_DIR", "none")
    t = devrun.targets()
    assert json.loads((t["spikes"] / "round8" / "ptr_items.json").read_text()) == []
    monkeypatch.setenv("GP_SPIKES_DIR", str(tmp_path / "missing"))
    with pytest.raises(devpaths.DevPathMissing, match="GP_SPIKES_DIR=none"):
        devrun.preflight("eval.arms", ["fit", "--backend", "none"], devrun.targets())
    devrun.preflight("eval.arms", ["run", "--split", "heldout", "--backend", "none"], devrun.targets())  # no spikes needed


def test_makefile_runs_locked_dev_modules_through_devrun():
    mk = (ROOT / "Makefile").read_text()
    assert "-m eval.devrun eval.arms fit" in mk and "-m eval.devrun eval.arms run" in mk
    assert "-m eval.devrun eval.gold.sample --split dev" in mk and "gold-dev-fetch:" in mk
    assert "dev-install:" in mk and "--no-deps -e ." in mk


def test_audit3_second_auditor_through_an_openai_compatible_server(monkeypatch, tmp_path):
    from gegenprobe import llm
    from gegenprobe.repair.adapters import audit3
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.org/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_NAME", "vendor/other-model")
    calls = []

    def post(self, payload):
        calls.append(payload)
        return dict(resp=dict(model="vendor/other-model"), text='{"is_answer": "yes", "date_ok": "no", "quote": "", '
                                                                 '"note": ""}')

    monkeypatch.setattr(llm.OpenAICompat, "_post", post)
    monkeypatch.setattr(audit3, "WORKDIR", tmp_path)
    monkeypatch.setattr(audit3, "packets", lambda: [dict(id="A3-001", affair_number="1", title="t", type="Anfrage",
                                                         answer_event_dates=[], excerpt_path="x")])
    monkeypatch.setattr(audit3, "item_prompt", lambda p: "prompt")
    r = audit3.qwen(backend="openai")
    assert r["new"] == 1 and r["served_models"] == {"vendor/other-model": 1} and calls[0]["temperature"] == 0.0
    v = json.loads((tmp_path / "verdicts_qwen.jsonl").read_text())
    assert (v["is_answer"], v["date_ok"]) == ("yes", "no")
    monkeypatch.setenv("LLM_NAME", "swiss-ai/apertus-70b")
    with pytest.raises(SystemExit, match="Apertus"):
        audit3.qwen(backend="openai")


# ------------------------------------------------------------------------------------------- 3 canary
def test_canary_on_in_the_template_and_the_live_run_committed():
    tpl = (ROOT / "deploy" / "nightly" / "alerts.env.example").read_text()
    assert re.search(r"^GP_ADAPTER_CANARY=1$", tpl, re.M)
    run = json.loads((ROOT / "results" / "repair" / "adapters" / "canary_runs" / "2026-10-11.json").read_text())
    cfg = json.loads((ROOT / "results" / "repair" / "adapters" / "canary.json").read_text())
    assert run["mode"] == "network" and run["verified"] == run["expected"] == len(cfg["canaries"]) == 7
    assert not run["alerts"] and all(r["same_text"] for r in run["results"])
    assert {r["affair_id"] for r in run["results"]} == {c["affair_id"] for c in cfg["canaries"]}


# ------------------------------------------------------------------------------------------- 4 licences
def test_results_licence_and_opd_attribution():
    for p in (ROOT / "results" / "LICENSE", ROOT / "data" / "LICENSE"):
        t = p.read_text()
        assert "CDLA-Permissive-2.0" in t and "Source: OpenParlData.ch" in t and "CC BY 4.0" in t
        assert "Community Data License Agreement - Permissive, Version 2.0" in t  # the full text


# ------------------------------------------------------------------------------------------- 5 incident bound
def test_ci_repeats_recomputed_from_the_run_snapshot():
    from gegenprobe.compliance import ci_repeats
    res = ci_repeats.compute()
    assert json.loads(ci_repeats.OUT.read_text()) == json.loads(json.dumps(res))
    assert res["disallowed_ti_urls_per_set"] == dict(gold_dev=21, gold_heldout=40, gold_p2=0, p6_test=0, convert_demo=3)
    w = res["workflows"]
    assert w["arms-8b-p2.yml"]["downloads_max"] == 0 and w["gguf-8b.yml"]["downloads_max"] == 0
    assert w["gguf-8b.yml"]["skipped_fetch_steps"] == w["gguf-8b.yml"]["runs_before_fix"] == 4
    assert w["ci.yml"]["downloads_max"] == 96 * 43
    assert res["upper_bound_downloads"] <= res["upper_bound_total"] <= res["upper_bound_requests_with_retries"]
    assert res["max_concurrent_fetching_steps"] == len(res["max_concurrency_at"]["steps"])
    snap = json.loads(ci_repeats.SNAPSHOT.read_text())
    assert all(r["created_at"] < ci_repeats.FIX_PUSHED for r in snap["runs"])


def test_audit3_key_commitment_has_githubs_push_time():
    smp = json.loads((ROOT / "results" / "repair" / "adapters" / "audit3" / "sample.json").read_text())
    assert smp["key_committed_github_time"] == "2026-10-11T00:56:16Z" and "ce416a8" in smp["key_committed_note"]
    assert "join" in smp["blind"] and "by instruction" in smp["blind"]
