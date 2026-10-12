"""What OPD's metadata holds, in the converter's v0.2 records (gegenprobe.schema.v0_2_meta, post hoc): the overlay fills
only open fields, each with route metadata and the OPD record as source, replaces no value, and changes nothing else; the
completeness table and the P11 NI post hoc records are current."""
import json

import pytest

from gegenprobe.schema import v0_2_completeness as FC
from gegenprobe.schema import v0_2_meta as VM
from gegenprobe.schema import v0_2_ni as NI
from gegenprobe.schema import v0_2_parts as VP
from gegenprobe.schema.p8_v0_2 import OUT, schema_module

SETS = {k: f"{k}_records.jsonl" for k in VP.CONVERTER_SETS} | {"fed": VP.FED_OUT}


@pytest.fixture(scope="module")
def pair():
    return VP.render(meta=False), VP.render()


def _recs(files, name):
    return [json.loads(x) for x in files[name].splitlines() if x.strip()]


def test_overlay_changes_only_open_fields(pair):
    before, after = pair
    for k, name in SETS.items():
        for b, a in zip(_recs(before, name), _recs(after, name), strict=True):
            assert VM.strip_metadata(a, b) == b, (k, b["ref"])
            for f in ("procedural_state", "decision"):
                if b[f]["kind"] == "value":
                    assert a[f] == b[f]
                elif a[f] != b[f]:
                    assert b[f]["null_reason"] in ("not_extracted", "not_in_corpus") and a[f]["route"] == "metadata"
            for qb, qa in zip(b["qa"], a["qa"], strict=True):
                for f in ("answer_date", "answering_body", "answer_identifier", "items"):
                    if f != "answering_body" and (qb[f] if f == "items" else qb[f]["kind"] == "value"):
                        assert qa[f] == qb[f]
            assert b["type"]["harmonised"] in ("unknown", a["type"]["harmonised"])


def test_filled_values_name_their_opd_record(pair):
    _, after = pair
    n_body = 0
    for name in SETS.values():
        for r in _recs(after, name):
            ab = r["qa"][0]["answering_body"]
            if ab["kind"] == "value":
                n_body += 1
                assert ab["route"] == ab["basis"] == "metadata"
                assert ab["source"].startswith(("opd:bodies/", "opd:events/", "gegenprobe:data/schema/body_executives"))
            else:
                assert ab["null_reason"] == "not_extracted" and "Kommission" in ab["evidence"], r["ref"]
            schema_module().validate_affair(r)
    val = json.loads(after["validation_all.json"])
    assert n_body == 118 and val["metadata_fill"]["n_records_changed"] == 120
    assert val["metadata_fill"]["answering_body_left_open"] == {"p5": 2}


def test_the_table_is_only_for_bodies_opd_names_no_executive():
    sl, tab = VM.load(), VM.table()
    for key in tab:
        b = sl["bodies"].get(key) or {}
        assert not any(b.get(k) for k in ("executive_name", "executive_name_de", "executive_name_fr",
                                         "executive_name_it")), key


def test_slice_covers_every_record():
    ids, bodies = VM.wanted()
    sl = VM.load()
    assert {int(a) for a in sl["affairs"]} == ids and set(sl["bodies"]) == bodies
    assert all(v["affair"] for v in sl["affairs"].values())


def test_completeness_file_is_current():
    assert (OUT / "field_completeness.json").read_text(encoding="utf-8") == FC.render()
    d = json.loads(FC.render())
    s = d["summary"]
    assert s["converter_cells"] == 17 * 120 and s["all_cells"] == 17 * 186
    assert s["converter_carries"] + s["converter_unsplit"] + s["converter_typed_gap"] + s["converter_untyped"] == 17 * 120
    assert s["converter_carries"] > s["converter_carries_before"]
    ab = d["after"]["answering_body"]["converter"]
    assert ab["carries"] == 118 and d["before"]["answering_body"]["converter"]["carries"] == 0


def test_ni_posthoc_records_validate_and_p11_is_unchanged():
    m = schema_module()
    recs = [json.loads(x) for x in NI.OUT_REC.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(recs) == 15
    for r in recs:
        m.validate_affair(r)
        assert r["qa"] == [] and r["empty_reasons"]["qa"]["reason"] in ("not_applicable", "not_in_corpus")
    v = json.loads(NI.OUT_JSON.read_text(encoding="utf-8"))
    assert v["records_valid"] == 15 and v["p11_converter_arm"]["records_valid"] == 3
    # never `not_applicable` where P11's gold finds the answer field applies
    assert all(x["gold_applies_record_not_applicable"] == 0 for x in v["answer_fields_not_applicable"].values())
    arm = json.loads(NI.ARM.read_text(encoding="utf-8"))
    assert arm["records_valid"] == 3


def test_ni_posthoc_rederives_from_the_cached_texts():
    try:
        files = NI.render()
    except FileNotFoundError as e:
        pytest.skip(f"texts not cached: {e}")
    for n, t in files.items():
        assert (NI.OUT_JSON.parent / n).read_text(encoding="utf-8") == t, n
