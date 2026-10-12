"""Review mode exits 3 when the server answers under another model label (the 12 Oct 2026 build switch, P11 D1): the
label check (llm._Remote._check) runs before the fingerprint guard, so the CLI maps ServedModelMismatch to exit 3 as it
maps BuildMismatch. No network: OpenAICompat._post is a stub and the cache is not written."""

import pytest

from gegenprobe import __main__ as cli
from gegenprobe import affair_cli, llm
from gegenprobe.convert import batch

NEW_LABEL, NEW_FP = "swiss-ai/Apertus-v1.5-70B", "vllm-0.1.dev1+g54b4292c2-tp2-bfd70257"


@pytest.fixture
def switched(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.publicai.co/v1")
    monkeypatch.setenv("LLM_NAME", "swiss-ai/apertus-v1.5-8b")
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.delenv("GP_OFFLINE", raising=False)
    monkeypatch.setattr(llm.OpenAICompat, "_post", lambda self, payload: dict(
        resp=dict(id="sim", model=NEW_LABEL, system_fingerprint=NEW_FP), lp=-1.0, toks=["x"], n_prompt=1, ts=0))
    monkeypatch.setattr(llm.ModelCache, "put", lambda self, k, v: None)


def test_switched_build_is_refused_before_any_value(switched):
    be, theta = batch.resolve_review("openai")  # the registered θ exists for publicai:swiss-ai/apertus-v1.5-8b
    with pytest.raises(llm.ServedModelMismatch, match=NEW_LABEL):
        be.score("a text no cache holds (test_review_served_label)", '{"answer_date": ', ["null"])


@pytest.mark.parametrize("cmd", ["convert", "affair"])
def test_cli_maps_served_label_mismatch_to_exit_3(monkeypatch, capsys, cmd):
    def boom(*a, **kw):
        raise llm.ServedModelMismatch(f"requested swiss-ai/apertus-v1.5-8b, served {NEW_LABEL}")
    monkeypatch.setattr(cli, "_convert", boom)
    monkeypatch.setattr(affair_cli, "main_args", boom)
    argv = ["convert", "x.pdf", "--mode", "review"] if cmd == "convert" else ["affair", "--opd-affair", "1"]
    assert cli.main(argv) == 3
    err = capsys.readouterr().err
    assert NEW_LABEL in err and "Refit θ" in err
