"""Round-5 operations: streamed-byte counter, the two-night Docker workflow, the review-mode build guard, the systemd
sandbox of both units and its CI score gate."""
import gzip
import json
import re
import subprocess
from pathlib import Path

import pytest

from gegenprobe.census import scan
from gegenprobe.convert import batch, build_guard
from gegenprobe.monitor import night_bytes, nightly

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
WORKFLOWS = REPO / ".github" / "workflows"
UNITS = ROOT / "deploy" / "nightly"


# ------------------------------------------------------------------------------------------------ 1 byte counter
def _gz(path: Path, n: int) -> int:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"id": i, "text": "x" * 50}) + "\n")
    return path.stat().st_size


def test_stream_counted_counts_every_compressed_byte_and_partial_reads(tmp_path, monkeypatch):
    from gegenprobe import net

    p = tmp_path / "docs" / "docs_XX.ndjson.gz"
    p.parent.mkdir()
    size = _gz(p, 2000)
    monkeypatch.setenv("GP_EXPORTS_DIR", str(tmp_path))
    url = net.EXPORTS_PREFIX + "docs/docs_XX.ndjson.gz"
    tally = {}
    assert sum(1 for _ in scan.stream_counted(url, tally)) == 2000
    assert tally["bytes"] == size and tally["local"] is True
    # an attempt that breaks off after a few lines still counts what it read (closed generator)
    tally2 = {}
    g = scan.stream_counted(url, tally2)
    next(g)
    g.close()
    assert 0 < tally2["bytes"] <= size


def test_bytes_summary_network_local_offline():
    s = dict(bytes=6_000, declared=6_000, files=2, local=0)
    net_ = nightly.bytes_summary(200, s, 10, 30, local=False, offline=False)
    assert net_["total"] == net_["over_network"] == 6_240 and net_["single_exports"] == 200
    loc = nightly.bytes_summary(0, dict(s, local=2), 10, 30, local=True, offline=False)
    assert loc["over_network"] == 30 and loc["docs_texts_streamed"] == 6_000  # only the canton tables travel
    off = nightly.bytes_summary(0, dict(bytes=0, declared=0, files=0, local=0), 0, 0, local=False, offline=True)
    assert off["over_network"] == 0 and off["read_from"].startswith("cached")


def test_add_streamed_marks_parts_without_a_count(tmp_path):
    acc = dict(bytes=0, declared=0, files=0, local=0)
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "stream_bytes.json").write_text(json.dumps(dict(bytes=5, declared=5, files={"docs_A": {"local": True}})))
    nightly.add_streamed(acc, tmp_path / "a" / "stream_bytes.json")
    nightly.add_streamed(acc, tmp_path / "b" / "stream_bytes.json")
    assert acc == dict(bytes=5, declared=5, files=1, local=1, parts_without_count=1)


def test_real_night_bytes_reconstructed_from_the_index_it_read():
    r = night_bytes.compute()
    assert r["single_exports_match"] and r["single_exports_index_bytes"] == 198_074_501
    assert r["docs_texts_files_streamed"] == r["docs_texts_files_in_index"] == 116
    assert r["docs_texts_streamed_gb"] == 6.2 and r["index_generated_at"].startswith("2026-10-10")
    committed = json.loads((ROOT / "results" / "monitor" / "night_real_bytes.json").read_text())
    assert committed == r


# ------------------------------------------------------------------------------------------------ 2 two Docker nights
@pytest.mark.skipif(not WORKFLOWS.exists(), reason="workflows live in the repository root")
def test_two_night_docker_workflow_is_manual_and_runs_night_two_on_night_ones_state():
    w = (WORKFLOWS / "nightly-real-docker.yml").read_text()
    assert re.search(r"^on:\s*\n\s+workflow_dispatch:", w, re.M) and not re.search(r"^\s*(schedule|push|pull_request):", w, re.M)
    assert "sudo sh deploy/nightly/install.sh\n" in w and "--venv" not in w  # the Docker variant, as documented
    assert w.count("docker-night.sh 1") == 1 and w.count("docker-night.sh 2") == 1
    assert "two_nights.json" in w and "upload-artifact@" in w and "GP_USER_AGENT" in w
    assert "from gegenprobe import net" in w  # the index poll goes through net (robots, pacing, User-Agent)
    sh = REPO / ".github" / "scripts" / "docker-night.sh"
    t = sh.read_text()
    assert "systemctl start gegenprobe-nightly.service" in t and "state_before" in t and "wall_s" in t
    assert "journal_excerpt.txt" in t and "rm -rf" not in t  # night 2 must find night 1's state
    assert subprocess.run(["sh", "-n", str(sh)]).returncode == 0


# ------------------------------------------------------------------------------------------------ 3 review build guard
class Fake:
    """A remote-like backend: each live call records the fingerprint the server answered from."""

    def __init__(self, build="publicai:swiss-ai/apertus-v1.5-8b", fp="vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840"):
        self.build, self.fp, self.served, self.kind = build, fp, set(), "openai"

    def score(self, user_text, prefix, conts):
        self.served.add(self.fp)
        return [-1.0 for _ in conts]


def _guarded(monkeypatch, fake, allow=False):
    monkeypatch.setattr(batch, "make_backend", lambda spec: fake)
    return batch.resolve_review("fake", allow_build_mismatch=allow)


def test_guard_passes_the_build_theta_was_fitted_on(monkeypatch):
    be, theta = _guarded(monkeypatch, Fake())
    assert isinstance(be, build_guard.BuildGuard) and theta == pytest.approx(10.395, abs=1e-3)
    assert be.score("u", "p", ["a", "b"]) == [-1.0, -1.0] and be.mismatch is None and be.build == Fake().build


def test_guard_stops_on_another_fingerprint_before_the_value_is_used(monkeypatch):
    be, _ = _guarded(monkeypatch, Fake(fp="vllm-0.30.0-tp4-ffffffff"))
    with pytest.raises(build_guard.BuildMismatch) as e:
        be.score("u", "p", ["a"])
    assert e.value.code == 3 and "vllm-0.30.0-tp4-ffffffff" in str(e.value) and "--allow-build-mismatch" in str(e.value)
    assert isinstance(e.value, SystemExit)  # per-document error handling cannot swallow it into a failure row


def test_guard_allow_mismatch_warns_once_and_marks(monkeypatch, capsys):
    be, _ = _guarded(monkeypatch, Fake(fp="other-fp"), allow=True)
    be.score("u", "p", ["a"])
    be.score("u", "p", ["a"])
    assert be.mismatch["served"] == ["other-fp"] and be.mismatch["fitted_build"] == Fake().build
    assert capsys.readouterr().err.count("warning: review mode") == 1


def test_guard_refuses_a_theta_without_fingerprints_and_a_wrong_gguf(tmp_path):
    t = tmp_path / "t.json"
    t.write_text(json.dumps(dict(build="publicai:x", served_fingerprints=[], answer_date=dict(theta=1.0))))
    with pytest.raises(build_guard.BuildMismatch, match="records no served fingerprint"):
        build_guard.BuildGuard(Fake(build="publicai:x"), build_guard.fitted(t, tmp_path / "none.json"))
    g = ROOT / "data" / "convert" / "theta" / "gguf_apertus-v1.5-8b-text-q4_k_m.json"
    weights = tmp_path / "w.gguf"
    weights.write_bytes(b"not the pinned weights")
    fake = Fake(build="gguf:apertus-v1.5-8b-text-q4_k_m")
    fake.path = str(weights)
    with pytest.raises(build_guard.BuildMismatch, match="not the pinned weights"):
        build_guard.BuildGuard(fake, build_guard.fitted(g))
    fake.path = None  # the default file: llm.fetch_gguf already refuses another sha256
    build_guard.BuildGuard(fake, build_guard.fitted(g)).score("u", "p", ["a"])


def test_cli_review_mismatch_exits_3(monkeypatch, capsys):
    from gegenprobe import __main__ as cli

    monkeypatch.setattr(batch, "make_backend", lambda spec: Fake(fp="swapped"))

    def convert_one(source, inp=None, *, backend=None, **kw):
        backend.score("u", "p", ["a"])  # the pointer's first live call
        raise AssertionError("not reached")
    monkeypatch.setattr(batch, "convert_one", convert_one)
    assert cli.main(["convert", "x.pdf", "--mode", "review", "--backend", "fake"]) == 3
    assert "swapped" in capsys.readouterr().err


def test_suggestion_made_under_an_allowed_mismatch_says_so(monkeypatch):
    from gegenprobe.convert import modes

    class G:
        build, mismatch = "publicai:x", dict(fitted_build="publicai:x", served=["swapped"])

    sugg = dict(value="2024-01-02", page=1, char_start=0, char_end=10, margin=-20.0, theta=10.0)
    monkeypatch.setattr(modes, "answer_date", lambda doc, mode, be, th, use_metadata=True: dict(
        value=None, residue=True, rule="no_anchor", null_reason="present_unanchored", route="rule", evidence="x",
        status="abstain", field="answer_date", mode=mode, needs_review=True, suggestion=sugg))
    monkeypatch.setattr(batch.pointer, "answer_date", lambda *a, **k: type("P", (), {"probs": {}, "choices": []})())
    monkeypatch.setattr(batch.output, "pointer_shares", lambda p: {None: 0.1})
    r = batch.convert_pages(["Text " * 200], sha="0" * 64, extractor="pdftotext", image_only=False, inp={},
                            mode="review", backend=G(), theta=10.0)
    assert r["review_suggestion"]["build_mismatch"]["served"] == ["swapped"]


# ------------------------------------------------------------------------------------------------ 4 systemd sandbox
def _keys(unit: Path) -> dict:
    out = {}
    for line in unit.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), []).append(v.strip())
    return out


def test_venv_unit_is_sandboxed():
    k = _keys(UNITS / "gegenprobe-nightly-venv.service")
    want = dict(ProtectSystem="strict", ProtectHome="yes", PrivateTmp="yes", PrivateDevices="yes", NoNewPrivileges="yes",
                CapabilityBoundingSet="", AmbientCapabilities="", RestrictSUIDSGID="yes", ProtectKernelTunables="yes",
                ProtectKernelModules="yes", ProtectKernelLogs="yes", ProtectControlGroups="yes", ProtectClock="yes",
                LockPersonality="yes", RestrictRealtime="yes", RestrictNamespaces="yes", SystemCallArchitectures="native",
                RestrictAddressFamilies="AF_INET AF_INET6 AF_UNIX", ReadWritePaths="/var/lib/gegenprobe",
                User="gegenprobe", UMask="0027")
    for key, v in want.items():
        assert k.get(key, [None])[-1] == v, key
    assert k["SystemCallFilter"] == ["@system-service", "~@privileged"]
    # everything the job writes is under the one writable path
    env = " ".join(k["Environment"])
    assert "GP_WORK=/var/lib/gegenprobe/work" in env and "GP_MONITOR_OUT=/var/lib/gegenprobe/results" in env
    assert "HOME=/var/lib/gegenprobe" in env and "PYTHONDONTWRITEBYTECODE=1" in env


def test_docker_unit_sandboxes_its_client_without_breaking_it():
    k = _keys(UNITS / "gegenprobe-nightly.service")
    assert k["RestrictAddressFamilies"] == ["AF_UNIX"] and k["NoNewPrivileges"] == ["yes"]
    assert k["SystemCallFilter"] == ["@system-service"]
    # the client must still create/chown the state dirs and touch alerts.env: no ProtectSystem/ProtectHome/capability cut
    assert not {"ProtectSystem", "ProtectHome", "CapabilityBoundingSet", "User"} & set(k)


@pytest.mark.skipif(not WORKFLOWS.exists(), reason="workflows live in the repository root")
def test_ci_gates_the_exposure_score_of_both_units():
    ci = (WORKFLOWS / "ci.yml").read_text()
    assert "systemd-analyze security --offline=true" in ci and '--threshold="$max"' in ci
    assert "for variant in venv:20 docker:50" in ci
    rb = (ROOT / "docs" / "runbook.md").read_text()
    assert "2.0" in rb and "5.0" in rb and "systemd-analyze security" in rb


# ------------------------------------------------------------------------------------------------ 6 site downloads
def test_site_downloads_are_the_committed_files_and_the_opd_box_links_them(tmp_path):
    from gegenprobe.viewer import __main__ as viewer
    from gegenprobe.viewer import data

    d = data.downloads()
    names = {f["name"] for f in d["files"]}
    assert {"repair_BE_relink.tsv", "repair_BE_fetch.tsv", "repair_BE_review.tsv", "repair_BE_begin_date.tsv",
            "apply_BE_plan.sql.txt", "apply_BE_relink_plan.csv", "apply_BE_begin_date_plan.csv", "apply_BE_plan.json",
            "affair.schema.json", "doc_extraction.schema.json"} == names
    assert d["repo"] == "https://github.com/mi11ione/gegenprobe"
    relink = next(f for f in d["files"] if f["name"] == "repair_BE_relink.tsv")
    assert relink["rows"] == 2421 and relink["href"] == "downloads/repair_BE_relink.tsv"
    copied = viewer.copy_downloads(tmp_path)
    # + the adapter lists (one TSV per parliament) and their manifest (census/corrected.write_lists, round 6)
    lists = {f["href"].split("/")[-1] for f in d["adapter_lists"]["files"]} | {"adapters_manifest.json"}
    assert sorted(p.name for p in copied) == sorted(names | lists)
    for f in d["files"]:  # byte-identical to the results files
        assert (tmp_path / f["href"]).read_bytes() == (ROOT / f["source"]).read_bytes()
    site = ROOT / "site"
    if (site / "downloads").is_dir():  # the committed site ships them next to index.html
        assert sorted(p.name for p in (site / "downloads").iterdir()) == sorted(names | lists)
        for n in lists:  # the committed lists are what write_lists produces from the committed results
            assert (site / "downloads" / n).read_bytes() == (tmp_path / "downloads" / n).read_bytes(), n
    t = (ROOT / "src" / "gegenprobe" / "viewer" / "template.html").read_text()
    assert 'id="opdDownloads"' in t and "DL.repo" in t
    # a build into another directory (make run's out/) carries the downloads too
    viewer.render(json.loads((site / "data.json").read_text()), tmp_path / "out")
    assert (tmp_path / "out" / "downloads" / "repair_BE_relink.tsv").exists()
