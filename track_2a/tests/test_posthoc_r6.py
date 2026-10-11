import json

from eval import posthoc_r6 as r6
from gegenprobe.paths import RESULTS


def test_committed_raw_p6_dev2_annotations_reproduce_the_merged_labels():
    for s, r in r6.check_annotations().items():
        assert r["labels_equal"] and r["agreement_equal"], s


def test_cluster_file_recomputes(tmp_path, monkeypatch):
    committed = json.loads(r6.OUT_CLUSTER.read_text())
    monkeypatch.setattr(r6, "OUT_CLUSTER", tmp_path / "c.json")
    got = r6.cluster()
    assert json.loads(json.dumps(got)) == committed
    p5 = got["p5_h1"]
    assert (p5["precision"]["k"], p5["precision"]["n"], p5["recall"]["n"]) == (118, 143, 176)  # = hypotheses6 H1
    pair = got["p6"]["paired"]["cascade_v2 vs rules"]
    assert (pair["a_only"], pair["b_only"]) == (11, 5)
    assert got["p6"]["arms"]["model_free_cascade"]["exact"] == [55, 68]


def test_annotation_sessions_order_holds_for_every_set():
    o = json.loads((RESULTS / "eval" / "annotation_sessions.json").read_text())
    assert o["overall"]["all_order_checks_hold"]
    for s in o["sets"]:
        assert s["summary"]["label_files_mtime_in_session"] == s["summary"]["label_files_total"], s["set"]
