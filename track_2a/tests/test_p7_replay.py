"""P7 from a clean checkout (round 8): the committed copies of the WORK inputs are the files the draw hashed, and the
replay (eval/p7/replay8.py; run in full by tests/test_replay_all.py) fails when one of them changes."""
import json
import shutil

from eval.p7 import replay8


def test_committed_p7_inputs_match_the_hashes_recorded_at_the_draw():
    t = replay8.input_checks()
    assert t["ok"], t["detail"]
    assert replay8.lock8()["ok"]


def test_a_changed_decision_fails_the_input_check(tmp_path, monkeypatch):
    shutil.copytree(replay8.P7, tmp_path / "p7")
    p = tmp_path / "p7" / "test_decisions.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    rows[0]["p7"] = not rows[0]["p7"]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(replay8, "P7", tmp_path / "p7")
    monkeypatch.setattr(replay8, "MANIFEST", tmp_path / "p7" / "REPLAY8.json")
    t = replay8.input_checks()
    assert not t["ok"] and any("test_decisions.jsonl" in d for d in t["detail"])


def test_committed_p7_files_carry_no_document_text():
    feats = [json.loads(x) for x in (replay8.P7 / "dev_features.jsonl").read_text().splitlines()]
    assert all("line" not in s for f in feats for b in f["b"].values() for s in (b.get("spans") or {}).values())
    for name in ("test_key.jsonl", "dev_key.jsonl", "test_decisions.jsonl", "date_rule_outcomes.jsonl"):
        for x in (replay8.P7 / name).read_text().splitlines():
            assert all(len(str(v)) <= 64 for v in json.loads(x).values()), name
