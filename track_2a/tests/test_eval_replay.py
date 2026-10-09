import copy

from eval.replay import rescore
from eval.score import summarise


def _res():
    per = [dict(doc_id=1, cell="fr", gold="2021-01-02", doc_dates=["2021-01-02", "2020-05-05"], lenient=[],
                rules=dict(status="value", value="2021-01-02"), naive_plain=dict(date="2020-05-05")),
           dict(doc_id=2, cell="fr", gold=None, doc_dates=["2020-05-05"], lenient=[],
                rules=dict(status="null", value=None), naive_plain=dict(date="1999-01-01"))]
    arms = {}
    for arm, route in (("rules", "rule"), ("naive_plain", "apertus")):
        rows = []
        for d in per:
            r = d[arm]
            pred = r.get("value") if arm == "rules" and r.get("status") == "value" else r.get("date")
            rows.append(dict(cell=d["cell"], gold=d["gold"], pred=pred, route=route, lenient=[], doc_dates=d["doc_dates"]))
        arms[arm] = dict(strict=summarise(rows, True), lenient=summarise(rows, False))
    return dict(split="heldout", build="b", n_docs=2, arms=arms, per_doc=per)


def test_replay_reproduces_and_detects_tampering():
    res = _res()
    _, bad, full = rescore(res)
    assert full and bad == []
    assert res["arms"]["naive_plain"]["strict"]["ALL"]["fabricated"] == 1  # 1999-01-01 occurs nowhere
    t = copy.deepcopy(res)
    t["arms"]["rules"]["strict"]["fr"]["correct"] = 0
    assert any("rules/strict/fr/correct" in b for b in rescore(t)[1])
