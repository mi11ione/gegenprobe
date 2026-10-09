import json
from pathlib import Path

import pytest

from gegenprobe import llm

FIX = Path(__file__).parent / "fixtures" / "prefill_probe_tail.json"


def test_tail_logprob_reads_actual_token_not_top1():
    """Recorded Public AI response (spikes/live/raw/probe_prefill_8b.json): the prefilled ' nicht' is rank 27."""
    pl = json.loads(FIX.read_text())["prompt_logprobs_tail"]
    lp, toks = llm._tail_logprob(pl, " nicht schuldig")
    assert toks == [" nicht", " sch", "uldig"]
    assert lp == pytest.approx(-16.37836456298828 - 0.014042853377759457 + 0)


def test_tail_logprob_refuses_misaligned_boundary():
    pl = json.loads(FIX.read_text())["prompt_logprobs_tail"]
    with pytest.raises(ValueError):
        llm._tail_logprob(pl, "cht schuldig")


class _Fake(llm._Remote):
    def __init__(self, served_model, tmp):
        super().__init__("swiss-ai/apertus-v1.5-8b")
        self.cache = llm.ModelCache("test", root=tmp)
        self.served_model = served_model

    def _post(self, payload):
        return dict(resp=dict(model=self.served_model, system_fingerprint="fp"), lp=-1.0, text="x")


def test_served_model_mismatch_is_fatal(tmp_path):
    with pytest.raises(llm.ServedModelMismatch):
        _Fake("aisingapore/Qwen-SEA-LION-v4-32B-IT", tmp_path).score("u", "{", [" null"])


def test_prefill_refused_on_70b_name(tmp_path):
    f = _Fake("swiss-ai/apertus-v1.5-70b", tmp_path)
    f.model = "swiss-ai/apertus-v1.5-70b"
    with pytest.raises(ValueError):
        f.score("u", "{", [" null"])


def test_cache_replays_without_network(tmp_path, monkeypatch):
    f = _Fake("swiss-ai/apertus-v1.5-8b", tmp_path)
    assert f.score("u", "{", [" null"]) == [-1.0]
    monkeypatch.setenv("GP_OFFLINE", "1")
    g = _Fake("swiss-ai/apertus-v1.5-8b", tmp_path)
    g._post = None  # any network attempt would crash
    assert g.score("u", "{", [" null"]) == [-1.0]
    with pytest.raises(llm.CacheMiss):
        g.score("u", "{", [' "x"'])
