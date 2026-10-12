"""Review mode on the re-built Public AI route through a deployment θ file (convert/deploy_theta.py,
eval/refit_bfd70257/NOTE.md). No network: OpenAICompat._post is a stub and the model cache is not written.

  * with a deployment file and the route serving its build (one preflight request): the CLI's lookup moves the route
    backend to the file's build key, accepts exactly the recorded (label, fingerprint) pair, and guards with the
    file's θ and fingerprint; a later response from anything else (old label, old fingerprint, another fingerprint, a
    missing one) stops the run: exit 3
  * the route serving the registered build again: the frozen path (registered θ); any third build: exit 3
  * without the file, offline, or with --theta: the frozen path, unchanged (the new build still exits 3)
"""
import json

import pytest

from gegenprobe import __main__ as cli
from gegenprobe import affair_cli, llm
from gegenprobe.convert import batch, build_guard, deploy_theta
from gegenprobe.paths import DATA, ROOT

REQ = "swiss-ai/apertus-v1.5-8b"
NEW_LABEL, NEW_FP = "swiss-ai/Apertus-v1.5-70B", "vllm-0.1.dev1+g54b4292c2-tp2-bfd70257"
OLD_FP = "vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840"
NEW_BUILD = "publicai:swiss-ai/apertus-v1.5-8b@bfd70257"
TEXT = "a text no cache holds (test_deploy_theta)"


def _file(d, theta=7.5, **kw):
    d.mkdir(parents=True, exist_ok=True)
    t = dict(build=NEW_BUILD, route_build=f"publicai:{REQ}", requested_model=REQ, served_label=NEW_LABEL,
             served_fingerprints=[NEW_FP], answer_date=dict(theta=theta)) | kw
    (d / "theta_bfd70257.json").write_text(json.dumps(t))
    return d / "theta_bfd70257.json"


@pytest.fixture
def route(monkeypatch, tmp_path):
    """The Public AI route as the openai backend sees it. `served` is the queue of the server's answers: each call takes
    the first one while more than one is left, then the last one repeats."""
    monkeypatch.setenv("LLM_BASE_URL", "https://api.publicai.co/v1")
    monkeypatch.setenv("LLM_NAME", REQ)
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.delenv("GP_OFFLINE", raising=False)
    served = [dict(model=NEW_LABEL, system_fingerprint=NEW_FP)]
    sent = []

    def post(self, payload):
        sent.append(payload)
        ans = served.pop(0) if len(served) > 1 else served[0]
        return dict(resp=dict(id="sim", **ans), lp=-1.0, toks=["x"], n_prompt=1, ts=0)
    monkeypatch.setattr(llm.OpenAICompat, "_post", post)
    monkeypatch.setattr(llm.ModelCache, "put", lambda self, k, v: None)
    monkeypatch.setattr(deploy_theta, "DEPLOY_DIR", tmp_path / "deploy")
    return dict(served=served, sent=sent, dir=tmp_path / "deploy")


def test_deployment_file_makes_review_run_on_the_new_build(route):
    _file(route["dir"], theta=7.5)
    with deploy_theta.installed():
        be, theta = batch.resolve_review("openai")
    assert isinstance(be, build_guard.BuildGuard) and theta == 7.5
    assert be.build == NEW_BUILD and be.inner.cache.dir.name == llm._slug(NEW_BUILD)  # own cache, never the old one
    assert be.fit["fingerprints"] == [NEW_FP]
    assert be.score(TEXT, '{"answer_date": ', ["null"]) == [-1.0]
    assert be.relabel["accepted"] == 1 and be.served == {NEW_FP}
    # requests: the preflight (one plain user message) and the score call (user message + prefill), both to the -8b name;
    # never a -70b name, never a system message
    pre, p = route["sent"]
    assert pre["model"] == REQ and [m["role"] for m in pre["messages"]] == ["user"] and pre["max_tokens"] == 1
    assert p["model"] == REQ and [m["role"] for m in p["messages"]] == ["user", "assistant"]


@pytest.mark.parametrize("answer", [
    dict(model=REQ, system_fingerprint=OLD_FP),  # the old build came back
    dict(model=NEW_LABEL, system_fingerprint="vllm-0.2.0-tp2-ffffffff"),  # same label, another build
    dict(model=NEW_LABEL, system_fingerprint=None),  # no fingerprint: cannot be checked
    dict(model="swiss-ai/apertus-v1.5-70b", system_fingerprint=NEW_FP),  # another label
])
def test_deployment_accepts_exactly_the_recorded_pair(route, answer):
    _file(route["dir"])
    route["served"][:] = [dict(model=NEW_LABEL, system_fingerprint=NEW_FP), answer]  # preflight, then a switch
    with deploy_theta.installed():
        be, _ = batch.resolve_review("openai")
    with pytest.raises(llm.ServedModelMismatch, match="deployment θ accepts only"):
        be.score(TEXT, '{"answer_date": ', ["null"])


def test_route_back_on_the_registered_build_uses_the_registered_theta(route):
    _file(route["dir"])
    route["served"][:] = [dict(model=REQ, system_fingerprint=OLD_FP)]
    with deploy_theta.installed():
        be, theta = batch.resolve_review("openai")
    assert be.build == f"publicai:{REQ}" and theta == pytest.approx(10.395, abs=1e-3) and not hasattr(be, "relabel")
    assert be.score(TEXT, '{"answer_date": ', ["null"]) == [-1.0]  # the frozen check and guard pass the registered build


def test_a_third_build_is_refused_with_or_without_the_file(route):
    _file(route["dir"])
    route["served"][:] = [dict(model=REQ, system_fingerprint="vllm-9.9-tp1-cafecafe")]
    with deploy_theta.installed():
        be, _ = batch.resolve_review("openai")
    with pytest.raises(build_guard.BuildMismatch):
        be.score(TEXT, '{"answer_date": ', ["null"])


def test_without_the_file_the_new_build_is_still_refused(route):
    with deploy_theta.installed():
        be, theta = batch.resolve_review("openai")
    assert be.build == f"publicai:{REQ}" and theta == pytest.approx(10.395, abs=1e-3)  # the registered θ
    with pytest.raises(llm.ServedModelMismatch, match=NEW_LABEL):
        be.score(TEXT, '{"answer_date": ', ["null"])


def test_offline_and_explicit_theta_keep_the_frozen_path(route, monkeypatch):
    _file(route["dir"])
    with deploy_theta.installed():
        be, theta = batch.resolve_review("openai", 3.0)  # --theta: the operator's choice, frozen path
        assert theta == 3.0 and be.build == f"publicai:{REQ}" and not hasattr(be, "relabel")
        monkeypatch.setenv("GP_OFFLINE", "1")  # replays of the registered build
        be, theta = batch.resolve_review("openai")
        assert be.build == f"publicai:{REQ}" and theta == pytest.approx(10.395, abs=1e-3)


def test_role_backend_is_switched_too(route):
    _file(route["dir"])
    with deploy_theta.installed():
        be = batch.make_backend("openai")  # affair --roles apertus without --mode review
    assert be.build == NEW_BUILD and be.relabel["requested"] == REQ
    with pytest.raises(llm.ServedModelMismatch):
        be._check(dict(model=REQ, system_fingerprint=OLD_FP))


def test_installed_restores_the_frozen_functions(route):
    orig = batch.resolve_review, batch.make_backend
    with deploy_theta.installed():
        assert batch.resolve_review is not orig[0]
    assert (batch.resolve_review, batch.make_backend) == orig


def test_malformed_file_is_refused(route):
    route["dir"].mkdir(parents=True)
    (route["dir"] / "theta_x.json").write_text(json.dumps(dict(build=NEW_BUILD)))
    with deploy_theta.installed(), pytest.raises(SystemExit, match="lacks"):
        batch.resolve_review("openai")


@pytest.mark.parametrize("cmd", ["convert", "affair"])
def test_cli_exit_codes_with_and_without_the_file(route, monkeypatch, capsys, cmd):
    def one_call(*a, **kw):
        be, _ = batch.resolve_review("openai")
        be.score(TEXT, '{"answer_date": ', ["null"])  # the pointer's first live call
        return 0
    monkeypatch.setattr(cli, "_convert", one_call)
    monkeypatch.setattr(affair_cli, "main_args", one_call)
    argv = (["convert", "x.pdf", "--mode", "review", "--backend", "openai"] if cmd == "convert"
            else ["affair", "--opd-affair", "39369", "--mode", "review", "--backend", "openai"])
    assert cli.main(argv) == 3  # no deployment file: the new build is refused
    assert NEW_LABEL in capsys.readouterr().err
    _file(route["dir"])
    assert cli.main(argv) == 0
    route["served"][:] = [dict(model=NEW_LABEL, system_fingerprint=NEW_FP), dict(model=REQ, system_fingerprint=OLD_FP)]
    assert cli.main(argv) == 3  # switched mid-run: the file accepts only the build it was fitted on


def test_committed_deployment_file_if_present():
    """data/deploy/theta_bfd70257.json: outside the locked θ folder, not hash-locked, consistent with the refit note."""
    p = DATA / "deploy" / "theta_bfd70257.json"
    if not p.exists():
        pytest.skip("no deployment θ file committed")
    t = json.loads(p.read_text())
    assert t["build"] == NEW_BUILD and t["route_build"] == f"publicai:{REQ}" and t["requested_model"] == REQ
    assert t["served_label"] == NEW_LABEL and t["served_fingerprints"] == [NEW_FP]
    assert set(t["served_fingerprints_live"]) <= {NEW_FP}
    assert t["note"] == "eval/refit_bfd70257/NOTE.md" and "EXPLORATORY" in t["label"]
    assert t["dev"]["n_docs"] == 97 and t["answer_date"]["loo"]["n"] <= 97
    assert t["relabel"]["accepted"] <= t["relabel"]["checked"]
    locked = set()
    for lock in ROOT.glob("eval/**/LOCK*"):
        for v in json.loads(lock.read_text()).values():
            if isinstance(v, dict):
                locked |= set(v)
    assert "data/deploy/theta_bfd70257.json" not in locked and not p.is_relative_to(DATA / "convert" / "theta")
    assert deploy_theta.files() and deploy_theta.files()[0][0] == p
