"""P11 deviation D1 (eval/p11/DEVIATIONS_P11.md): the relabel acceptance is exactly one (label, fingerprint) pair on the
-8b name, only inside the wrapper's context, and every other mismatch still raises."""

import pytest

from eval.p11 import arms_d1 as D
from gegenprobe import llm


class _Fake(llm._Remote):
    def __init__(self, tmp, model="swiss-ai/apertus-v1.5-8b"):
        super().__init__(model)
        self.cache = llm.ModelCache("test", root=tmp)
        self.reply = {}

    def _post(self, payload):
        return dict(resp=self.reply, lp=-1.0, text="x")


def _call(be, label, fp, n=0):
    be.reply = dict(model=label, system_fingerprint=fp)
    return be.generate(f"u{n}", max_tokens=1)


def test_relabel_accepted_only_on_the_frozen_fingerprint(tmp_path):
    be = _Fake(tmp_path)
    with D.Relabel() as rl:
        assert _call(be, D.RELABEL, D.FROZEN_FP) == "x"
        assert rl.accepted == 1 and be.served == {D.FROZEN_FP}
        for i, (label, fp) in enumerate([(D.RELABEL, "vllm-other"), (D.RELABEL, None),
                                         ("swiss-ai/apertus-v1.5-70b", D.FROZEN_FP),
                                         ("aisingapore/Qwen-SEA-LION-v4-32B-IT", D.FROZEN_FP)], 1):
            with pytest.raises(llm.ServedModelMismatch):
                _call(be, label, fp, i)
        assert _call(be, D.REQUESTED, D.FROZEN_FP, 9) == "x"  # the unchanged label passes as before
        assert rl.accepted == 1


def test_relabel_not_accepted_for_another_requested_name(tmp_path):
    be = _Fake(tmp_path, model="swiss-ai/apertus-v1.5-70b")
    with D.Relabel(), pytest.raises(llm.ServedModelMismatch):
        _call(be, D.RELABEL, D.FROZEN_FP)


def test_relabel_off_outside_the_wrapper(tmp_path):
    with D.Relabel():
        pass
    with pytest.raises(llm.ServedModelMismatch):
        _call(_Fake(tmp_path), D.RELABEL, D.FROZEN_FP)


def test_without_accept_every_mismatch_raises_and_is_recorded(tmp_path):
    be = _Fake(tmp_path)
    with D.Relabel(accept=False) as rl:
        with pytest.raises(llm.ServedModelMismatch, match="vllm-new"):
            _call(be, D.RELABEL, "vllm-new")
        with pytest.raises(llm.ServedModelMismatch):
            _call(be, D.RELABEL, D.FROZEN_FP, 1)
    assert rl.accepted == 0
    assert [m["system_fingerprint"] for m in rl.mismatches] == ["vllm-new", D.FROZEN_FP]


def test_accept_refused_unless_the_probe_shows_the_frozen_build(tmp_path, monkeypatch):
    import json

    p = tmp_path / "probe.json"
    monkeypatch.setattr(D, "PROBE", p)
    assert not D.probe_ok()[0]
    p.write_text(json.dumps(dict(fingerprint_equal_to_frozen_on_every_call=False, fingerprints_live=["x"])))
    assert not D.probe_ok()[0]
    p.write_text(json.dumps(dict(fingerprint_equal_to_frozen_on_every_call=True, fingerprints_live=[D.FROZEN_FP],
                                 greedy_equal_on_every_next_top_call=True)))
    assert D.probe_ok()[0]
