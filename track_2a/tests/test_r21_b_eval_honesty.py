"""R21-B (POST HOC, proposed in review): the P2 model-free cascade and baseline ladder, P7 paired, the margin against
no-model ranking signals, and the draft schema v0.2.1 (`cited`) recompute from committed files and say what they claim."""
import hashlib
import json
import sys

import pytest
from pydantic import ValidationError

from eval import margin_vs_nomodel as MN
from eval.gold2 import posthoc_cascade as PC
from eval.p7 import posthoc_paired as PP
from gegenprobe.paths import ROOT
from gegenprobe.schema import v0_2_1_oos_fit as F


def _same(got: dict, path) -> None:
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(got, ensure_ascii=False)) == committed


# ---------------------------------------------------------------- P2: cascade and ladder
def test_p2_cascade_recomputes_and_matches_the_review():
    got = PC.compute()
    _same(got, PC.OUT)
    d = got["display"]
    assert (d["cascade_exact"], d["cascade_answer_dates"], d["cascade_answerless_dated"]) == ("49/62", "21/29", "5/33")
    assert (d["pointer_exact"], d["pointer_answer_dates"]) == ("53/62", "24/29")
    assert (d["discordant"], d["mcnemar_p"], d["answered_discordant"], d["answered_mcnemar_p"]) == (
        "9 vs 5", "0.42", "7 vs 4", "0.55")
    assert d["parliaments_favour"] == "4 vs 3"
    assert d["cluster95"] == "[-0.123, 0.234]" and d["cluster95_excludes_0"] is False
    assert "POST HOC" in got["label"] and "proposed in review" in got["label"]


def test_p2_ladder_is_ordered_and_every_rung_is_paired():
    got = json.loads(PC.OUT.read_text(encoding="utf-8"))
    ex = got["display"]["ladder_exact"]
    assert ex == {"rules": "35/62", "latest_date_on_answer_docs_only": "44/62", "keyword": "45/62",
                  "composite": "46/62", "keyword_cue": "47/62", "rules_then_keyword_cue": "49/62", "pointer": "53/62"}
    assert got["display"]["ladder_mcnemar_p"]["composite"] == "0.065"
    assert got["display"]["ladder_cluster95"]["composite"] == "[0.014, 0.221]"  # the README's interval, for the composite
    for row in got["ladder"][:-1]:
        assert {"pointer_only", "baseline_only", "mcnemar_p_str", "cluster95"} <= set(row)


def test_cascade_is_rules_first_then_keyword_cue():
    for r in PC.rows():
        want = r["rules"] if r["rules"] is not None else r["keyword_cue"]
        assert r[PC.CASCADE] == want


# ---------------------------------------------------------------- P7 paired
def test_p7_paired_recomputes_and_shows_the_abstention_effect():
    got = PP.compute()
    _same(got, PP.OUT)
    d = got["display"]
    assert d["shared"] == "106 vs 105 of 112" and d["shared_discordant"] == "1 vs 0" and d["shared_p"] == "1"
    assert d["yield_annotated"] == "113 vs 127 of 154" and d["yield_discordant"] == "8 vs 22"
    assert (d["p7_only"], d["trivial_only"], d["precision"]) == ("7/8", "22/34", "113/120 vs 127/146")
    w = got["weighted_frame_estimate"]
    assert w["p7_minus_trivial"] < 0 and w["interval_excludes_0"]
    # consistent with the committed unpaired overlap counts
    ov = json.loads((ROOT / "results" / "p7" / "p7_posthoc_overlap.json").read_text())["annotated"]
    assert ov["overlap"]["both"]["p7_date_hit"] == 106 and ov["overlap"]["both"]["trivial_date_hit"] == 105
    assert (ov["p7"]["date_hit"], ov["trivial"]["date_hit"]) == (113, 127)
    assert "POST HOC" in got["label"] and "proposed in review" in got["label"]


# ---------------------------------------------------------------- margin vs no-model signals
def test_margin_vs_nomodel_recomputes_and_reproduces_the_margin_aurocs():
    got = MN.compute()
    _same(got, MN.OUT)
    assert all(got["margin_matches_closed_vs_free"].values())
    assert got["display"]["margin_auroc"] == {"P1": 0.732, "P2": 0.896, "P6": 0.713}
    for b in got["sets"].values():
        assert set(b["signals"]) == set(MN.SIGNALS)
        assert b["residue"]["values"] <= b["values"]
        lo, hi = b["margin"]["ci95"]
        assert lo <= b["margin"]["auroc"] <= hi
    assert "POST HOC" in got["label"] and "proposed in review" in got["label"]


def test_vectorised_bootstrap_auroc_equals_mann_whitney():
    import numpy as np

    from gegenprobe.stats import auroc
    s = np.array([3.0, 1.0, 2.0, 2.0, 5.0, 0.0])
    y = np.array([1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
    k = MN._kernel(s, y)
    c = np.ones(len(y))
    assert (c @ k @ c) / (y.sum() * (1 - y).sum()) == pytest.approx(
        auroc([x for x, t in zip(s, y) if t], [x for x, t in zip(s, y) if not t]))


# ---------------------------------------------------------------- schema v0.2.1 draft
def _sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_schema_v0_2_stays_as_locked():
    want = json.loads((ROOT / "eval" / "p11" / "LOCKP11").read_text())
    flat = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                flat[k] = v if isinstance(v, str) else flat.get(k)
                walk(v)
    walk(want)
    assert _sha(ROOT / "schema" / "gegenprobe_schema_v0_2.py") == flat["schema/gegenprobe_schema_v0_2.py"]


def test_schema_v0_2_1_adds_cited_only_and_round_trips():
    m = F.schema_module()
    v02 = m._v02
    from typing import get_args
    assert set(get_args(m.DateRole)) - set(get_args(v02.DateRole)) == {"cited"}
    recs = [json.loads(x) for x in (ROOT / "results" / "schema" / "v0_2" / "p8_records.jsonl").read_text().splitlines()
            if x.strip()]
    for r in recs:
        a = m.upgrade_v0_2(r)
        assert a.schema_version == "0.2.1"
        back = m.downgrade_to_v0_2(a)
        assert back == v02.Affair.model_validate(r).model_dump(mode="json")
    d = m.upgrade_v0_2(next(r for r in recs if r["dates"])).model_dump(mode="json")
    d["dates"][0]["role"] = "cited"
    a = m.validate_affair(d)
    with pytest.raises(ValidationError):
        m.downgrade_to_v0_2(a)  # v0.2.0 cannot carry `cited`
    d["dates"][0]["role"] = "not_a_role"
    with pytest.raises(ValidationError):
        m.validate_affair(d)


def test_schema_v0_2_1_loads_without_gegenprobe(tmp_path):
    import shutil
    import subprocess
    for f in ("gegenprobe_schema.py", "gegenprobe_schema_v0_2.py", "gegenprobe_schema_v0_2_1.py"):
        shutil.copy(ROOT / "schema" / f, tmp_path / f)
    code = (f"import sys; sys.path.insert(0, {str(tmp_path)!r}); "
            "import gegenprobe_schema_v0_2_1 as m, json; s = m.json_schema(); "
            "assert s['version'] == '0.2.1' and 'cited' in json.dumps(s); print('ok')")
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr


def test_v0_2_1_fit_recomputes_41_of_43():
    outs = F.outputs()
    for k, v in outs.items():
        assert (F.OUT_DIR / k).read_text(encoding="utf-8") == v, k
    got = json.loads(outs["oos_role_fit.json"])
    assert got["changed"]["non_interventions"] == "36/43 -> 41/43"
    assert got["changed"]["submission_date_role_p11_ni"] == "7/12 -> 12/12"
    assert got["changed"]["interventions_unchanged"] is True
    assert "POST HOC" in got["label"] and "proposed in review" in got["label"]
