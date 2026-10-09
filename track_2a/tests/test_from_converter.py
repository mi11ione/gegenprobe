"""convert.cascade output -> schema_v0_1.DocExtraction (the single adapter)."""
import pytest
from pydantic import ValidationError

from gegenprobe.convert import cascade
from gegenprobe.schema.schema_v0_1 import DocExtraction, GovRecommendationValue, TypedNull, from_converter
from gegenprobe.validate import recheck

PAGES = ["Kanton Bern\nRRB-Nr.: 879/2024 vom 28. August 2024\nAntwort des Regierungsrates\nText.\n"]


def _rec(fields, extractor="pdftotext-26.02.0"):
    return dict(doc_id=404590, sha256="a" * 64, extractor=extractor, fields=fields)


def test_rule_value_quote_is_exact_span_and_rechecks():
    f = cascade.answer_date(dict(pages=PAGES, lang="de"), None, None)
    x = cascade.to_schema(_rec({"answer_date": f}), pages=PAGES)
    assert isinstance(x, DocExtraction)
    v = x.answer_date
    assert v.kind == "value" and v.value.isoformat() == "2024-08-28" and v.route == "rule"
    assert v.role == "answer_decided" and v.doc == "opd:404590"
    assert v.quote == PAGES[0][v.char_start:v.char_end] and "RRB-Nr." in v.context
    assert recheck(v, PAGES).ok


def test_ocr_routes_only_for_text_reading_decisions():
    fields = {"answer_date": dict(value=None, null_reason="not_in_document", route="rule", rule="x"),
              "recommendation": dict(value=None, null_reason="not_applicable", route="rule", rule="affair_type")}
    x = from_converter(_rec(fields, extractor="tesseract-5.5.3-deu+fra+ita"))
    assert x.answer_date.route == "ocr+rule" and x.doc.image_only
    assert x.recommendation.route == "rule"  # decided from the affair type, no text read


def test_model_abstention_carries_margin_theta_build():
    f = dict(value=None, null_reason="not_in_document", route="apertus", model_build="b", theta=4.9, margin=7.0,
             candidates=3)
    x = from_converter(_rec({"answer_date": f}))
    assert isinstance(x.answer_date, TypedNull) and "7.00 > theta 4.90" in x.answer_date.evidence
    with pytest.raises(ValidationError):  # an "abstention" below θ is not an abstention
        from_converter(_rec({"answer_date": dict(f, margin=1.0)}))


def test_document_level_model_classification_needs_candidate_set():
    m = dict(route="apertus", model_build="b", theta=0.0, margin=-3.0)
    x = from_converter(_rec({"answer_date": dict(value=None, null_reason="not_in_document", route="rule", rule="x"),
                             "recommendation": dict(value="reject", candidates=4, **m)}))
    assert isinstance(x.recommendation, GovRecommendationValue) and x.recommendation.page is None
    with pytest.raises(ValidationError):
        from_converter(_rec({"answer_date": dict(value=None, null_reason="not_in_document", route="rule", rule="x"),
                             "recommendation": dict(value="reject", **m)}))


def test_not_in_document_is_not_a_metadata_reason():
    with pytest.raises(ValidationError):
        TypedNull(null_reason="not_in_document", route="metadata", evidence="x")
