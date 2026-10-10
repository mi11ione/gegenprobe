import json

from eval import replay_all
from gegenprobe.paths import DATA, RESULTS

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"


def test_replay_all_passes_on_committed_files():
    r = replay_all.replay()
    assert r["n"] >= 15
    assert r["failing"] == 0, [t for t in r["tests"] if not t["ok"]]


def test_rescore_detects_a_changed_label(tmp_path):
    res = json.loads((RESULTS / "eval" / f"heldout__{BUILD}.json").read_text())
    assert replay_all.rescore_arms(res, DATA / "gold" / "heldout_labels.jsonl") == []
    labels = [json.loads(x) for x in open(DATA / "gold" / "heldout_labels.jsonl", encoding="utf-8") if x.strip()]
    i = next(k for k, lab in enumerate(labels) if lab["answer_date"])
    labels[i]["answer_date"] = "1900-01-01"
    bad_file = tmp_path / "labels.jsonl"
    bad_file.write_text("".join(json.dumps(lab) + "\n" for lab in labels))
    bad = replay_all.rescore_arms(res, bad_file)
    assert any(str(labels[i]["doc_id"]) in b for b in bad)  # stored gold differs from the label file
    assert any("committed" in b and "recomputed" in b for b in bad)  # and the recomputed counts differ


def test_locks_verify():
    assert all(t["ok"] for t in replay_all.replay_locks())
