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
    """The committed files are this render with the document-parts overlay (gegenprobe.schema.v0_2_parts);
    tests/test_schema_v0_2_parts.py checks that stripping the overlay gives this render's records back exactly."""
    from gegenprobe.schema import v0_2_parts

    over = v0_2_parts.render()
    assert set(files) <= set(over)
    for name, text in over.items():
        assert (OUT / name).read_text(encoding="utf-8") == text, f"run make schema-v02 ({name})"


def test_every_record_validates(val):
    assert {k: (s["n_valid"], s["n_affairs"]) for k, s in val["sets"].items()} == {
        "p3": (29, 29), "p3b": (36, 36), "p5": (40, 40), "p8": (66, 66)}
    assert val["n_valid"] == val["n_affairs"] == 171 and val["n_invalid"] == 0
    assert val["converter_made"] == dict(n_affairs=105, n_valid=105, sets=["p3", "p3b", "p5"], n_parliaments=22)
    assert val["product_records"]["n_valid"] == val["product_records"]["n_affairs"] == 65


def test_converter_records_carry_no_annotator_value(val):
    for k in ("p3", "p3b", "p5"):
        assert set(val["sets"][k]["counts"]["routes"]) <= {"metadata", "rule", "ocr+rule"}, k


def test_carry_changes_only_the_declared_fields():
    """carry_v0_1: version tag, language_tag, answering_body (typed not_extracted), body.languages (official languages)
    and empty_reasons; nothing else of the converter's record changes."""
    from gegenprobe.schema import body_languages

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
        assert set(rec["empty_reasons"]) == set(m.empty_fields(rec))
        assert rec["body"]["languages"] == (body_languages.languages(rec["body"]["key"])[0] or post["body"]["languages"])
        # everything else is the converter's record
        back = json.loads(json.dumps(rec))
        for q in back["qa"]:
            q.pop("answering_body")
        for d in back["documents"]:
            d.pop("language_tag")
        back.pop("empty_reasons")
        back["body"]["languages"] = post["body"]["languages"]
        back["schema_version"] = back["extraction"]["schema_version"] = post["schema_version"]
        back["extraction"]["notes"] = post["extraction"].get("notes")
        if back["extraction"]["notes"] is None:
            back["extraction"].pop("notes")
        assert back == post


def test_p5_records_are_the_commands_with_the_arms_qa_items():
    """R21: the published P5 records are the operator command's on P5's documents (gegenprobe.affair_product p5), not the
    rules arm's assembly. The command pairs Q/A items by the same P5 rules, so the items equal the arm's; every answer
    date is located in the answer text (route rule) or OPD's event (route metadata)."""
    res = json.loads(V.P5.read_text(encoding="utf-8"))
    recs = {r["ref"]["opd_id"]: r for r in map(json.loads, (OUT / "p5_records.jsonl").read_text().splitlines())}
    for x in res["per_affair"]:
        r, R = recs[x["affair_id"]], x["R"]["records"]
        assert r["extraction"]["converter_version"] == "gegenprobe-0.1.0+affair"
        assert [i["n"] for i in r["qa"][0].get("items", [])] == [i["n"] for i in R["qa_items"]]
        ad = r["qa"][0]["answer_date"]
        assert ad["kind"] == "null" or ad["route"] in ("rule", "ocr+rule", "metadata")
        assert r.get("title"), x["affair_id"]


def test_samples_are_converter_records_that_validate(val):
    m = schema_module()
    assert len(val["samples"]) == 3
    for p in val["samples"]:
        rec = json.loads((OUT.parents[2] / p).read_text(encoding="utf-8"))
        m.validate_affair(rec)
        assert "annotator" not in json.dumps(rec) and "hand-built" not in json.dumps(rec)


def test_converter_records_carry_the_roles(val):
    """The converter's own records carry v0.2's roles read from the documents, and every empty list
    has a typed reason."""
    for k in ("p3", "p3b", "p5"):
        rc = val["sets"][k]["counts"]["records_carrying"]
        n = val["sets"][k]["n_affairs"]
        assert rc["empty_reasons_typed"] == n
        assert rc["language_of_text_all_documents"] == n
        assert rc["printed_author_with_role"] >= n // 2 and rc["instrument_function"] >= n // 2, (k, rc)
    used = set(val["v02_additions"]["used_in_converter_records"])
    assert {"actor_role:joint_author", "actor_role:sole_author", "instrument_function", "language_of_text",
            "date_role:signed", "date_role:lodged"} <= used


def test_samples_follow_the_rule(files, val):
    m = schema_module()
    valid_by = {k: [json.loads(x) for x in files[f"{k}_records.jsonl"].splitlines()] for k in ("p3", "p3b", "p5")}
    picked = [f"results/schema/v0_2/samples/{k}_{r['ref']['body_key']}_{r['ref']['opd_id']}.json"
              for k, r in V.pick_samples(valid_by)]
    assert picked == val["samples"] and val["sample_rule"] == V.SAMPLE_RULE
    langs = []
    for p in val["samples"]:
        rec = json.loads((OUT.parents[2] / p).read_text(encoding="utf-8"))
        m.validate_affair(rec)
        assert V.role_score(rec) >= 4, p
        langs.append([d["language_of_text"] for d in rec["documents"] if d["role"] == "question"][0])
    assert langs == [["de"], ["fr"], ["it"]]


def test_bern_sample_reads_the_document_not_the_tag():
    """the Bern answer is French although OPD tags it 'de'; the document prints 'Eingereicht von: Ruchti
    (Sprecher/in), Gerber' (joint authors, no co-signatory)."""
    rec = json.loads((OUT / "samples" / "p3_BE_39369.json").read_text(encoding="utf-8"))
    roles = {a["name"]["value"]: a["role"] for a in rec["actors"] if a["name"]["kind"] == "value"}
    assert roles == {"Ruchti": "joint_author", "Gerber": "joint_author"}
    # the roles the record does not carry say why (gegenprobe.schema.v0_2_gaps): no co-signatory next to joint authors
    nulls = {a["role"]: a["name"]["null_reason"] for a in rec["actors"] if a["name"]["kind"] == "null"}
    assert nulls == {"co_signatory": "not_applicable", "addressed_body": "present_unanchored"}
    ans = next(d for d in rec["documents"] if d["role"] == "answer")
    assert ans["language_tag"] == "de" and ans["language_of_text"] == ["fr"] and ans["language_of_text_method"]
    assert rec["body"]["languages"] == ["de", "fr"]
    assert rec["type"]["instrument_function"]["value"] == "questions"


def test_roles_file_matches_the_texts_when_cached():
    from gegenprobe.schema import v0_2_roles

    r = v0_2_roles.check()
    if r["status"] == "SKIP":
        pytest.skip(r["summary"])
    assert r["status"] == "PASS", r["summary"]


def test_additions_partition(val):
    a = val["v02_additions"]
    assert sorted(a["used_in_converter_records"] + a["used_only_in_p8"] + a["used_nowhere"]) == sorted(a["all"])
