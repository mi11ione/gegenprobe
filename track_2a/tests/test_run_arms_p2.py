"""8B-on-P2 driver (eval/run_arms_p2.py), exercised end to end with a fake backend: no model, no network, no PDF."""
import hashlib
import json

from eval import arms, run_arms_p2 as R
from gegenprobe.paths import DATA


class Fake:
    build = "fake:p2-test"

    def score(self, user, prefix, conts):
        return [-(int(hashlib.sha256((user[-50:] + c).encode()).hexdigest()[:4], 16) % 40) - 1.0 for c in conts]


def _pages(sha):
    return dict(sha256=sha, extractor="fake", image_only=False,
                pages=["Regierungsrat\nSitzung vom: 16. Oktober 2012\nBeschluss Nr.: 119\neingereicht am 10. September 2012\n"
                       "Der Regierungsrat beantwortet die Interpellation wie folgt.\nVersand: 18. Oktober 2012"])


def _setup(monkeypatch, tmp_path):
    order = R.label_order()
    skip = order[5]
    monkeypatch.setattr(R, "SHARDS", tmp_path / "eval2" / "shards")
    monkeypatch.setattr(R, "OUT", tmp_path / "eval2" / f"p2__{R.SLUG}.json")
    monkeypatch.setattr(R, "reachable", lambda d: d["doc_id"] != skip)
    monkeypatch.setattr(arms.pdftext, "extract", _pages)
    return order, skip


def test_shards_partition_the_full_label_order():
    order = R.label_order()
    assert len(order) == 62
    parts = [R.shard_ids(f"{i}/6") for i in range(6)]
    assert sorted(x for p in parts for x in p) == sorted(order)
    assert sum(len(p) for p in parts) == 62  # no overlap


def test_run_and_merge_with_fake_backend(monkeypatch, tmp_path):
    order, skip = _setup(monkeypatch, tmp_path)
    for i in range(3):
        R.run(f"{i}/3", be=Fake())
    R.run(ids=",".join(map(str, order[:2])), be=Fake())  # fill-in that re-scores two documents: must be identical
    assert arms.DATA == DATA  # frozen module restored
    res = R.merge()
    assert res["n_docs"] == 61 and res["not_scored"] == [skip]
    assert set(res["arms"]) == {"rules", "pointer", "cascade"}
    assert res["split"] == "p2" and res["build"] == R.BUILD
    assert [r["doc_id"] for r in res["per_doc"]] == [d for d in order if d != skip]
    written = json.loads(R.OUT.read_text())
    assert written["arms"]["rules"]["strict"]["ALL"]["n"] == 61
    h = json.loads((tmp_path / "eval2" / f"hypotheses2__{R.SLUG}.json").read_text())
    assert "H2_pointer_vs_rules" in h["subsets"]["all"]["theta_10_40"]
    unreach = json.loads((R.SHARDS / "unreachable_p2__0_of_3.json").read_text()) + \
        json.loads((R.SHARDS / "unreachable_p2__1_of_3.json").read_text()) + \
        json.loads((R.SHARDS / "unreachable_p2__2_of_3.json").read_text())
    assert unreach == [skip]


def test_merge_refuses_conflicting_duplicates(monkeypatch, tmp_path):
    order, _ = _setup(monkeypatch, tmp_path)
    R.run("0/6", be=Fake())
    p = R.SHARDS / "p2__gguf__0_of_6.json"
    d = json.loads(p.read_text())
    d["per_doc"][0]["pointer"]["value"] = "1900-01-01"
    (R.SHARDS / "p2__gguf__fill_1.json").write_text(json.dumps(d))
    try:
        R.merge()
    except AssertionError as e:
        assert "scored twice" in str(e)
    else:
        raise AssertionError("conflicting duplicate accepted")
