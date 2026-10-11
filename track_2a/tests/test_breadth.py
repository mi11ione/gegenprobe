"""Breadth table (eval/breadth.py): P1/P2 per stratum, reproducible from committed files, consistent with the totals."""
import json

from eval import breadth


def test_committed_breadth_file_is_current():
    assert breadth.OUT.read_text(encoding="utf-8") == breadth.render()


def test_strata_add_up_and_only_ticino_scans_are_scanned():
    d = json.loads(breadth.render())
    for name, s in d["sets"].items():
        cells = {k: v for k, v in s["cells"].items() if k != "ALL"}
        for arm in breadth.ARMS:
            for k in ("exact", "found", "answerless_dated"):
                assert sum(c[arm][k] for c in cells.values()) == s["cells"]["ALL"][arm][k], (name, arm, k)
        assert {k for k, c in cells.items() if c["source"] != "born-digital"} == ({"ocr_ti"} if name == "P1" else set())
    p1, p2 = d["sets"]["P1"]["cells"]["ALL"], d["sets"]["P2"]["cells"]["ALL"]
    assert (p1["rules"]["exact"], p1["n"]) == (135, 154) and (p2["pointer"]["exact"], p2["pointer"]["found"]) == (53, 24)
