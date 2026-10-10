import json

from gegenprobe.convert import opdtext
from gegenprobe.schema import validate
from gegenprobe.schema.schema_v0_1 import QAItem
from gegenprobe.paths import DATA, ROOT


def test_opdtext_aligns_via_context_and_reports_ambiguity():
    opd = "Kanton Bern\n\nRRB-Nr.:   879/2024 vom\n28. August 2024\nAntwort ...\nBern, 28. August 2024"
    r = opdtext.align(opd, "28. August 2024", "RRB-Nr.: 879/2024 vom 28. August 2024")
    assert r["status"] == "unique" and r["matched_on"] == "context"
    assert opd[r["char_start"]:r["char_end"]] == "28. August 2024" and r["char_start"] < opd.rfind("Bern,")
    assert opdtext.align(opd, "28. August 2024")["status"] == "ambiguous"
    assert opdtext.align(opd, "3. März 2025")["status"] == "not_found"


def test_qaitem_and_verdict_classes():
    it = QAItem.model_validate({"n": 1, "question": {"kind": "null", "null_reason": "not_in_document", "route": "rule",
                                             "evidence": "no numbered questions"},
                                "answer": {"kind": "null", "null_reason": "present_unanchored",
                                           "route": "rule", "evidence": "one answer to all questions"}})
    assert it.n == 1
    keys = [c["key"] for c in json.loads((DATA / "schema" / "field_verdict_classes.json").read_text())]
    assert keys == ["shared", "shared_with_role_split", "body_specific"]


def test_validate_cli_on_samples_and_garbage(tmp_path):
    samples = sorted(str(p) for p in (ROOT / "results" / "schema" / "samples").glob("*.json"))
    assert validate.main(samples) == 0
    (tmp_path / "x.json").write_text(json.dumps({"hello": 1}))
    assert validate.main([str(tmp_path / "x.json")]) == 1
