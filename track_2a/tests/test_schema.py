import copy
import json
import typing

import pytest
from pydantic import ValidationError

from gegenprobe.paths import DATA, RESULTS
from gegenprobe.schema import schema_v0_1 as S
from gegenprobe.schema.schema_v0_1 import Affair, DateValue, TypedNull

SAMPLES = sorted((RESULTS / "schema" / "samples").glob("*.json"))


def _load(name):
    return json.loads((RESULTS / "schema" / "samples" / f"{name}.json").read_text())


def test_samples_exist_and_validate():
    assert {p.stem for p in SAMPLES} >= {"be_2024_RRGR_91", "be_2024_RRGR_97", "che_14_089"}
    for p in SAMPLES:
        Affair.model_validate(json.loads(p.read_text()))


def test_json_schema_export_matches_model():
    exported = json.loads((RESULTS / "schema" / "affair.schema.json").read_text())
    assert exported == json.loads(json.dumps(Affair.model_json_schema()))


def test_vocab_files_match_literals():
    pairs = {"affair_types": S.AffairType, "date_roles": S.DateRole, "actor_roles": S.ActorRole,
             "procedural_states": S.ProceduralState, "decision_outcomes": S.DecisionOutcome,
             "government_recommendations": S.GovRecommendation, "null_reasons": S.NullReason,
             "answer_link_status": S.AnswerLinkStatus}
    for name, lit in pairs.items():
        v = json.loads((DATA / "schema" / f"{name}.json").read_text())
        assert [x["key"] for x in v] == list(typing.get_args(lit)), name
        for x in v:
            assert set(x["labels"]) == {"de", "fr", "it", "en"} and all(x["labels"].values()), (name, x["key"])


def test_opd_event_map_targets_are_vocabulary():
    for e in json.loads((DATA / "schema" / "opd_event_titles.json").read_text()):
        m = e["maps_to"]
        if "date_role" in m:
            assert m["date_role"] in typing.get_args(S.DateRole)
        if "decision" in m:
            assert m["decision"] in typing.get_args(S.DecisionOutcome)


def test_unlinked_null_needs_related_doc_and_metadata_route():
    with pytest.raises(ValidationError):
        TypedNull(null_reason="unlinked", route="metadata", evidence="x")
    with pytest.raises(ValidationError):
        TypedNull(null_reason="unlinked", route="rule", evidence="x", related_doc="opd:1")
    TypedNull(null_reason="unlinked", route="metadata", evidence="x", related_doc="opd:1")


def test_model_route_needs_build_theta_margin():
    with pytest.raises(ValidationError):
        TypedNull(null_reason="present_unanchored", route="apertus", evidence="abstained")
    with pytest.raises(ValidationError):   # an abstention must have margin > theta
        TypedNull(null_reason="present_unanchored", route="apertus", evidence="abstained", model_build="b", theta=2.0, margin=1.0)
    TypedNull(null_reason="present_unanchored", route="apertus", evidence="abstained", model_build="b", theta=2.0, margin=3.5)
    with pytest.raises(ValidationError):   # rule route must not carry model fields
        TypedNull(null_reason="present_unanchored", route="rule", evidence="x", theta=1.0)


def test_rule_value_needs_span_and_quote():
    with pytest.raises(ValidationError):
        DateValue(value="2024-08-28", basis="normalised", route="rule", doc="d")
    with pytest.raises(ValidationError):
        DateValue(value="2024-08-28", basis="normalised", route="rule", doc="d", page=1, char_start=5, char_end=5, quote="x")
    DateValue(value="2024-08-28", basis="normalised", route="rule", doc="d", page=1, char_start=5, char_end=20, quote="x")


def test_metadata_basis_route_coupled():
    with pytest.raises(ValidationError):
        DateValue(value="2024-08-28", basis="metadata", route="rule", source="opd:events/1")
    with pytest.raises(ValidationError):
        DateValue(value="2024-08-28", basis="metadata", route="metadata")
    with pytest.raises(ValidationError):
        DateValue(value="2024-08-28", basis="extracted", route="metadata", source="opd:events/1")


def test_unknown_field_and_dangling_doc_rejected():
    obj = _load("be_2024_RRGR_91")
    bad = copy.deepcopy(obj)
    bad["answer_date"] = "2024-08-28"
    with pytest.raises(ValidationError):
        Affair.model_validate(bad)
    bad = copy.deepcopy(obj)
    bad["qa"][0]["answer_date"]["doc"] = "opd:999"
    with pytest.raises(ValidationError):
        Affair.model_validate(bad)


def test_bare_none_is_not_a_field_value():
    obj = _load("be_2024_RRGR_97")
    obj["decision"] = None
    with pytest.raises(ValidationError):
        Affair.model_validate(obj)


def test_extracted_vs_inferred_is_explicit():
    a = Affair.model_validate(_load("che_14_089"))
    assert a.government_recommendation.basis == "inferred"
    a = Affair.model_validate(_load("be_2024_RRGR_91"))
    assert a.qa[0].answer_identifier.basis == "extracted" and a.qa[0].answer_date.basis == "normalised"


def test_virtual_affair_and_unspecified_language():
    """OPD (correspondence, 10 Oct 2026): communes with meeting documents only get 'virtual affairs'; an empty document
    language means 'not specified'; bilingual bodies need several languages."""
    obj = _load("be_2024_RRGR_91")
    doc_id = obj["documents"][0]["doc_id"]
    v = copy.deepcopy(obj)
    v["ref"].update(virtual=True, derived_from=doc_id, number="V 2021-06-28")
    v["documents"][0]["language"] = "unspecified"
    v["body"]["languages"] = ["de", "fr"]
    Affair.model_validate(v)
    bad = copy.deepcopy(v)
    bad["ref"]["virtual"] = False
    with pytest.raises(ValidationError):
        Affair.model_validate(bad)
    bad = copy.deepcopy(v)
    bad["ref"]["derived_from"] = "opd:999"
    with pytest.raises(ValidationError):
        Affair.model_validate(bad)
