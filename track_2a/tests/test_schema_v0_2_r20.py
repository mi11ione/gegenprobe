"""R20 (post hoc) carrier layers of the converter's v0.2 records: the role of every answer date
(gegenprobe.schema.v0_2_dates), a typed reason for every silent role (gegenprobe.schema.v0_2_gaps) and the page boxes of
the located values (gegenprobe.schema.v0_2_bbox). No network, no model."""
import copy
import json

import pytest

from gegenprobe.paths import PDF_CACHE
from gegenprobe.schema import v0_2_bbox as VB
from gegenprobe.schema import v0_2_completeness as FC
from gegenprobe.schema import v0_2_dates as VD
from gegenprobe.schema import v0_2_gaps as VG
from gegenprobe.schema import v0_2_roles
from gegenprobe.schema.p8_v0_2 import OUT, schema_module

SETS = {"p3": "p3_records.jsonl", "p3b": "p3b_records.jsonl", "p5": "p5_records.jsonl", "fed": "fed_records.jsonl"}


@pytest.fixture(scope="module")
def recs():
    return {k: [json.loads(x) for x in (OUT / n).read_text(encoding="utf-8").splitlines() if x.strip()]
            for k, n in SETS.items()}


@pytest.fixture(scope="module")
def val():
    return json.loads((OUT / "validation_all.json").read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------------------------------------- gaps
def test_every_converter_cell_is_typed(recs, val):
    m = schema_module()
    for k, rs in recs.items():
        for r in rs:
            m.validate_affair(r)
            assert VG.untyped_cells(r) == [], (k, r["ref"])
    g = val["typed_gaps"]
    assert g["untyped_cells_left"]["converter"] == 0 and g["n_added"] == 250
    fc = json.loads((OUT / "field_completeness.json").read_text(encoding="utf-8"))["summary"]
    assert fc["converter_untyped"] == 0 and fc["fields_untyped_somewhere_in_converter"] == []


def test_an_untyped_cell_fails(recs):
    r = copy.deepcopy(next(x for x in recs["p3"] if x["ref"]["opd_id"] == 39369))
    r["actors"] = [a for a in r["actors"] if a["role"] != "addressed_body"]
    assert VG.untyped_cells(r) == ["addressed_body"]
    with pytest.raises(ValueError, match="without a value or a typed reason"):
        VG.require_typed([r], "p3")


def test_gap_reasons_are_typed_nulls_that_name_their_source(recs):
    for k, rs in recs.items():
        for r in rs:
            for a in r["actors"]:
                n = a["name"]
                if n.get("kind") == "null" and n["evidence"].startswith(VG.TAG):
                    assert a["role"] in ("co_signatory", "addressed_body")
                    if n["null_reason"] in ("present_unanchored", "not_in_document", "not_applicable"):
                        assert n.get("doc") in {d["doc_id"] for d in r["documents"]}, (k, r["ref"])


def test_addressed_rule_rerun_reproduces_the_carried_values(recs):
    rows = VG.Inputs.load().addressed
    fired = {(s, r["affair_id"]): r["match"] for (s, _), r in rows.items() if r["match"]}
    carried = {}
    for k in VG.ADDRESSED_SETS:
        for r in recs[k]:
            for a in r["actors"]:
                if a["role"] == "addressed_body" and a["name"]["kind"] == "value":
                    n = a["name"]
                    carried[(k, r["ref"]["opd_id"])] = (n["rule"], n["page"], n["char_start"], n["char_end"])
    assert len(carried) == 19  # R21: P3/P3b 6 + P5 13 (P5 is the command's, which reads the addressed body)
    assert {k: (m["rule"], m["page"], m["char_start"], m["char_end"]) for k, m in fired.items()} == carried


def test_detections_match_the_cached_texts():
    for c in (VG.check_detections(), VD.check_detections()):
        if c["status"] == "SKIP":
            pytest.skip(c["summary"])
        assert c["status"] == "PASS", c["summary"]


# ----------------------------------------------------------------------------------------------------------- dates
def test_every_answer_date_has_a_role_and_its_source(recs, val):
    b = val["answer_date_roles"]
    srcs = {"rule_role", "printed_anchor", "date_trust_verified"}
    reasons = {"same_as_submission", "unlabelled_date_line", "not_at_anchor", "no_answer_text"}
    for e in b["values"]:
        if e.get("counterpart"):
            continue
        assert (e["role"] in ("answer_decided", "answer_dispatched") and e["source"] in srcs) or \
            (e["role"] == "answered" and e["reason"] in reasons), e
    for rs in recs.values():
        for r in rs:
            q = (r.get("qa") or [None])[0]
            if q is not None and q["answer_date"]["kind"] == "value":
                assert q["answer_date"]["role"] in VD.ANSWER_ROLES
            assert not any(d["role"] == "answered" and d["date"]["kind"] == "value" and "; role answered" not in
                           (d.get("label") or "") for d in r.get("dates") or [])
    assert b["values_by_role"] == {"answer_decided": 25, "answer_dispatched": 17, "answered": 100}  # R21: P5 by the command
    assert b["records_with_a_split_role"] == 28 and b["counterparts"]["n"] == 28


def test_roles_agree_with_the_blind_gold(val):
    g = val["answer_date_roles"]["gold_check"]
    assert g["p3"]["disagreements"] == [] == g["p3b"]["disagreements"]
    assert g["p3"]["agree"] + g["p3b"]["agree"] == 32


def test_sample_answer_date_is_the_decision(recs):
    r = next(x for x in recs["p3"] if x["ref"]["opd_id"] == 39369)
    assert r["qa"][0]["answer_date"]["role"] == "answer_decided"
    ev = [d for d in r["dates"] if d["date"].get("source") == "opd:events/333247"]
    assert ev[0]["role"] == "answer_decided" and "printed_anchor" in ev[0]["label"]
    cp = [d for d in r["dates"] if (d.get("label") or "").startswith(VD.COUNTERPART)]
    assert cp[0]["role"] == "answer_dispatched" and cp[0]["date"]["null_reason"] == "not_in_document"


def test_rule_values_sit_on_their_committed_anchor(recs):
    det = VD.load()
    n = 0
    for k, rs in recs.items():
        for r in rs:
            q = (r.get("qa") or [None])[0]
            v = (q or {}).get("answer_date") or {}
            if v.get("kind") != "value" or VD.rule_role(v.get("rule")) is None:
                continue
            row = det[(k, q["answer_doc"])]
            assert any(a["rule"] == v["rule"] and a["page"] == v["page"] and a["char_start"] == v["char_start"]
                       and a["char_end"] == v["char_end"] for a in row["anchors"]), (k, r["ref"])
            n += 1
    assert n == 30  # R21: + P5's located answer dates (the command reads them)


def test_printed_role_names_only_labelled_anchors():
    assert VD.printed_role("rrb_vom") == "decision" and VD.printed_role("be_ace_split") == "decision"
    assert VD.printed_role("signature_block") == "dispatch" and VD.printed_role("date_de_depot_head") == "dispatch"
    for r in ("place_date_head", "place_date_tail", "date_line_above_heading_head", "ti_header_date_head"):
        assert VD.printed_role(r) == "date_line"
    assert VD.printed_role(VD.OPD_LOCATED) is None


# ----------------------------------------------------------------------------------------------------------- boxes
def test_every_located_value_has_a_box_or_a_reason(recs, val):
    b = val["span_bboxes"]
    assert b["n_spans"] == len(VB.spans(recs)) == 1580
    assert b["with_bbox"] == b["exact"] == 1573 and b["statuses"] == {"exact": 1573, "no_pdf": 7}
    s = b["sample"]
    assert s["bbox"] == [277.92, 355.76, 325.46, 365.13] and s["page_size"] == [595.28, 841.89]


def test_sample_box_rederives_from_the_cached_pdf(val):
    s = val["span_bboxes"]["sample"]
    d = VB._doc_index()[s["doc"]]
    pdf = PDF_CACHE / f"{d['sha256']}.pdf"
    got = v0_2_roles.pages_of(d["sha256"])
    if got is None or not pdf.exists():
        pytest.skip("PDF not cached")
    words, size = VB.page_words(pdf, s["page"])
    text = got[0][s["page"] - 1]
    assert text[s["char_start"]:s["char_end"]] == "18 mai 2022"
    box = VB.box_of(s["char_start"], s["char_end"], text, VB.align(text, words), words)
    assert box["bbox"] == s["bbox"] and box["status"] == "exact"


# ----------------------------------------------------------------------------------------------------------- provenance
def test_provenance_counts_add_up(recs):
    fc = json.loads((OUT / "field_completeness.json").read_text(encoding="utf-8"))["provenance"]["groups"]
    c = fc["converter"]
    assert c["n_values"] == sum(n for k, n in c["kinds"].items() if k != "typed_null")
    assert set(c["kinds"]) <= {"page_span", "opd_record", "other_record", "typed_null"}
    assert c["kinds"]["page_span"] == 1580
    n = sum(1 for rs in recs.values() for r in rs for _ in FC._walk(r))
    assert n == c["n_values"] + c["n_typed_nulls"]
