"""Q/A pairing in the converter's product records (gegenprobe.schema.v0_2_qa): the committed pairs match the cached
texts, the overlay changes only qa[0].items, its reason and a note, the samples carry items where the documents print
questions, and validation_all.json counts them. No network, no model."""
import json

import pytest

from gegenprobe.schema import v0_2_dates as VD
from gegenprobe.schema import v0_2_parts as VP
from gegenprobe.schema import v0_2_qa as QA
from gegenprobe.schema.p8_v0_2 import OUT, schema_module


@pytest.fixture(scope="module")
def over():
    return VP.render()


def test_pairs_match_the_cached_texts():
    r = QA.check_detections()
    if r["status"] == "SKIP":
        pytest.skip(r["summary"])
    assert r["status"] == "PASS", r["summary"]


def test_committed_pairs_cover_p3_and_p3b():
    pairs = QA.load()
    assert {s for s, _ in pairs} == set(QA.SETS) and len(pairs) == 65
    for p in pairs.values():
        assert p["n_questions"] == len(p["items"]) and p["n_answers_located"] <= p["n_questions"]
        for it in p["items"]:
            q = it["question"]
            assert q["kind"] == "value" and q["doc"] == p["question_doc"] and q["char_end"] > q["char_start"]
            assert it["answer"]["kind"] in ("value", "null")


def test_records_carry_the_pairs_and_stay_valid(over):
    m = schema_module()
    val = json.loads(over["validation_all.json"])
    for k in QA.SETS:
        recs = [json.loads(x) for x in over[f"{k}_records.jsonl"].splitlines()]
        with_items = sum(any(q["items"] for q in r["qa"]) for r in recs)
        assert val["qa_pairing"]["sets"][k]["records_with_items"] == with_items > 0
        assert val["qa_pairing"]["records_with_items_before_overlay"][k] == 0
        for r in recs:
            m.validate_affair(r)
            reason = r["empty_reasons"].get("qa.0.items")
            assert bool(r["qa"][0]["items"]) != bool(reason), r["ref"]
            if reason:
                assert reason["reason"] in ("none_printed", "present_unanchored")
                assert "does not pair" not in reason["evidence"]


def test_strip_qa_undoes_the_overlay():
    over = VP.render(meta=False)  # without the OPD-metadata overlay (it fills qa[].answering_body; test_schema_v0_2_meta)
    base = {k: [json.loads(x) for x in VP.V.render()[f"{k}_records.jsonl"].splitlines()] for k in QA.SETS}
    for k in QA.SETS:
        got = [QA.strip_qa(VD.strip_date_roles(json.loads(x))) for x in over[f"{k}_records.jsonl"].splitlines()]
        assert [g["qa"] for g in got] == [b["qa"] for b in base[k]]
        assert [g["empty_reasons"].get("qa.0.items") for g in got] == [b["empty_reasons"].get("qa.0.items")
                                                                         for b in base[k]]


def test_samples_carry_qa_items(over):
    val = json.loads(over["validation_all.json"])
    r = QA.samples_check(over, val["samples"])
    assert r["status"] == "PASS", r["summary"]
    for p in val["samples"]:
        rec = json.loads((OUT.parents[2] / p).read_text(encoding="utf-8"))
        assert rec["qa"][0]["items"], p


def test_pair_on_a_numbered_question_text():
    q = (["Interpellation\n\nWir bitten den Regierungsrat um Antwort auf folgende Fragen.\n\n"
          "1. Wie viele Stellen sind besetzt?\n2. Wann wird der Bericht vorgelegt?\n"], "opd:1", "pdftotext-x")
    a = (["Antwort des Regierungsrates\n\nZu Frage 1: Es sind 12 Stellen besetzt, wie die Erhebung zeigt.\n\n"
          "Zu Frage 2: Der Bericht wird im Frühjahr vorgelegt, sobald die Daten vorliegen.\n"], "opd:2", "pdftotext-x")
    p = QA.pair(q, a, "de")
    assert p["style"] == "enumerated" and p["n_questions"] == 2
    assert all(it["question"]["doc"] == "opd:1" for it in p["items"])
    ocr = QA.pair((q[0], q[1], "tesseract-5"), a, "de")
    assert {it["question"]["route"] for it in ocr["items"]} == {"ocr+rule"}
