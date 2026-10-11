"""Schema v0.2 beyond P8 (gegenprobe.schema.v0_2_all): the converter's own P3, P3b and P5 records carried to v0.2
validate, the committed files are current, and nothing but the declared changes is made to a converter record."""
import json

import pytest

from gegenprobe.affair_post import finalize
from gegenprobe.schema import v0_2_all as V
from gegenprobe.schema.p8_v0_2 import OUT, schema_module


@pytest.fixture(scope="module")
def files():
    return V.render()


@pytest.fixture(scope="module")
def val(files):
    return json.loads(files["validation_all.json"])


def test_committed_files_are_current(files):
    for name, text in files.items():
        assert (OUT / name).read_text(encoding="utf-8") == text, f"run python -m gegenprobe.schema.v0_2_all ({name})"


def test_every_record_validates(val):
    assert {k: (s["n_valid"], s["n_affairs"]) for k, s in val["sets"].items()} == {
        "p3": (29, 29), "p3b": (36, 36), "p5": (40, 40), "p8": (66, 66)}
    assert val["n_valid"] == val["n_affairs"] == 171 and val["n_invalid"] == 0
    assert val["converter_made"] == dict(n_affairs=105, n_valid=105, sets=["p3", "p3b", "p5"], n_parliaments=22)
    assert val["product_records"]["n_valid"] == val["product_records"]["n_affairs"] == 65


def test_converter_records_carry_no_annotator_value(val):
    for k in ("p3", "p3b", "p5"):
        assert set(val["sets"][k]["counts"]["routes"]) <= {"metadata", "rule", "ocr+rule"}, k


def test_carry_changes_only_version_tag_and_answering_body():
    m = schema_module()
    res = json.loads(V.P3.read_text(encoding="utf-8"))
    for x in res["per_affair"]:
        post = finalize(x["affair"])["affair"]
        rec = V.carry_v0_1(post)
        v = m.validate_affair(rec)
        assert v.extraction.converter_version == post["extraction"]["converter_version"]
        for q in v.qa:
            ab = q.answering_body
            assert ab.kind == "null" and ab.null_reason == "not_extracted"
        # everything else is the converter's record
        back = json.loads(json.dumps(rec))
        for q in back["qa"]:
            q.pop("answering_body")
        for d in back["documents"]:
            d.pop("language_tag")
        back["schema_version"] = back["extraction"]["schema_version"] = post["schema_version"]
        back["extraction"]["notes"] = post["extraction"].get("notes")
        if back["extraction"]["notes"] is None:
            back["extraction"].pop("notes")
        assert back == post


def test_p5_records_keep_the_rules_arm_values():
    res = json.loads(V.P5.read_text(encoding="utf-8"))
    recs = {r["ref"]["opd_id"]: r for r in map(json.loads, (OUT / "p5_records.jsonl").read_text().splitlines())}
    for x in res["per_affair"]:
        r, R = recs[x["affair_id"]], x["R"]["records"]
        items = r["qa"][0].get("items", [])
        assert [i["n"] for i in items] == [i["n"] for i in R["qa_items"]]
        assert [a["name"]["value"] for a in r["actors"]] == [a["name"].get("value") for a in R["actors"]]
        assert r["qa"][0]["answer_date"]["null_reason"] == "not_extracted"


def test_samples_are_converter_records_that_validate(val):
    m = schema_module()
    assert len(val["samples"]) == 3
    for p in val["samples"]:
        rec = json.loads((OUT.parents[2] / p).read_text(encoding="utf-8"))
        m.validate_affair(rec)
        assert "annotator" not in json.dumps(rec) and "hand-built" not in json.dumps(rec)


def test_additions_partition(val):
    a = val["v02_additions"]
    assert sorted(a["used_in_converter_records"] + a["used_only_in_p8"] + a["used_nowhere"]) == sorted(a["all"])
