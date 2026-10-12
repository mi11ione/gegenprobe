"""`gegenprobe convert <pdf> --schema v0.2`: a bare PDF (no OPD affair id) -> a validated schema v0.2 record
(convert/v02_pdf.py). Synthetic texts in a temporary cache; no network, no model."""
import json
import sys

import pytest

from gegenprobe import convert as convert_pkg
from gegenprobe import pdftext
from gegenprobe.__main__ import main
from gegenprobe.convert import batch, v02_pdf
from gegenprobe.schema import v0_2_roles
from gegenprobe.schema.p8_v0_2 import schema_module

PARA = ("Der Wald im Kanton Bern ist für die Bevölkerung und die Natur von grosser Bedeutung, und die Bewirtschaftung "
        "muss deshalb nachhaltig sein. Wir bitten den Regierungsrat, die folgenden Fragen zu beantworten.\n\n")
ANSWER = [f"Antwort des Regierungsrates\nRRB-Nr.: 879/2022 vom 18. Mai 2022\nGeschäftsnummer: 2021.RRGR.388\n\n{PARA}"
          "Der Regierungsrat beantwortet die Interpellation wie folgt.\n"]
QUESTION = [f"Interpellation 2021.RRGR.388\nEingereicht von: Fritz Ruchti (SVP)\nEingereicht am: 8. Dezember 2021\n\n{PARA}"
            "1. Wie wird der Wald gepflegt?\n"]
OTHER = ["Inhaltsverzeichnis\nSeite 1\n" + "Wald " * 80]
SHA = {"a.pdf": "a" * 64, "q.pdf": "b" * 64, "o.pdf": "c" * 64}
PAGES = {"a.pdf": ANSWER, "q.pdf": QUESTION, "o.pdf": OTHER}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    tc, pc = tmp_path / "text", tmp_path / "pdf"
    tc.mkdir()
    pc.mkdir()
    monkeypatch.setattr(pdftext, "TEXT_CACHE", tc)
    monkeypatch.setattr(pdftext, "PDF_CACHE", pc)
    monkeypatch.setattr(pdftext, "poppler_version", lambda: "test")
    monkeypatch.setattr(v0_2_roles, "TEXT_CACHE", tc)
    for name, sha in SHA.items():
        (tc / f"{sha}.pdftotext-test.json").write_text(json.dumps(
            dict(sha256=sha, extractor="pdftotext-test", pages=PAGES[name], image_only=False)))
    monkeypatch.setattr(batch, "get_document", lambda src, timeout=60, tries=2: (SHA[src.rsplit("/", 1)[-1]],
                                                                               pc / "none.pdf"))
    monkeypatch.delattr(convert_pkg, "parts", raising=False)  # no parts detector: typed not_extracted
    monkeypatch.setitem(sys.modules, "gegenprobe.convert.parts", None)
    return tmp_path


def _walk(o, out):
    if isinstance(o, dict):
        out.append(o)
        for v in o.values():
            _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)
    return out


def test_bare_answer_pdf_gives_a_valid_v02_record_with_spans_and_typed_metadata_nulls(cache):
    row = v02_pdf.convert("a.pdf", body="BE", affair_type="Interpellation")
    assert row["status"] == "ok" and row["schema_version"] == "0.2.0"
    rec = row["record"]
    schema_module().validate_affair(rec)  # validates again from the JSON
    assert rec["schema_version"] == "0.2.0" and "opd_id" not in rec["ref"] and rec["ref"]["body_key"] == "BE"
    doc = rec["documents"][0]
    assert doc["doc_id"].startswith("sha256:") and doc["source"] == "other" and doc["sha256"] == SHA["a.pdf"]
    assert doc["role"] == "answer"
    # no trace of the pipeline's OPD-shaped placeholder id
    assert "opd:" + v02_pdf.PLACEHOLDER not in json.dumps(rec)
    ad = rec["qa"][0]["answer_date"]
    assert ad["value"] == "2022-05-18" and ad["route"] == "rule" and ad["doc"] == doc["doc_id"]
    assert ANSWER[ad["page"] - 1][ad["char_start"]:ad["char_end"]] == ad["quote"]
    # what only OPD's metadata supplies is a typed null not_in_corpus that says why
    meta_nulls = [x for x in _walk(rec, []) if x.get("kind") == "null" and x.get("route") == "metadata"
                  and x.get("null_reason") == "not_in_corpus"]
    assert meta_nulls and all(x["evidence"] == v02_pdf.BARE for x in meta_nulls)
    assert rec["procedural_state"]["null_reason"] == "not_in_corpus"
    assert rec["empty_reasons"]["title"] == dict(reason="not_in_corpus", route="metadata", evidence=v02_pdf.BARE)
    assert rec["type"]["harmonised"] == "interpellation"
    assert rec["government_recommendation"]["null_reason"] == "not_applicable"  # an interpellation
    # every value is from the document (rule) or the caller's reference, never invented metadata
    assert not [x for x in _walk(rec, []) if x.get("kind") == "value" and x.get("route") == "metadata"]


def test_bare_question_pdf_reads_the_printed_submission_and_author(cache):
    row = v02_pdf.convert("q.pdf", body="BE", doc_role="question", affair_number="2021.RRGR.388")
    assert row["status"] == "ok"
    rec = row["record"]
    assert rec["ref"]["number"] == "2021.RRGR.388"
    assert rec["documents"][0]["role"] == "question"
    dates = {d["role"]: d["date"] for d in rec["dates"] if d["date"]["kind"] == "value"}
    assert any(v["value"] == "2021-12-08" and v["route"] == "rule" for v in dates.values())
    assert rec["qa"][0]["answer_date"]["kind"] == "null"
    assert row["sources"]["document"]["role_basis"] == "--doc-role"


def test_level_and_doc_role_are_required_when_unknown(cache):
    assert v02_pdf.convert("a.pdf")["status"] == "level_unknown"
    assert v02_pdf.convert("a.pdf", body="XX")["status"] == "level_unknown"  # not an OPD body: give --level
    ok = v02_pdf.convert("a.pdf", body="XX", level="communal")
    assert ok["status"] == "ok" and ok["record"]["body"]["level"] == "communal"
    other = v02_pdf.convert("o.pdf", body="BE")
    assert other["status"] == "doc_role_unknown" and "--doc-role" in other["reason"]
    assert v02_pdf.convert("o.pdf", body="BE", doc_role="answer")["status"] == "ok"


def test_cli_schema_v02_writes_the_row(cache, capsys):
    out = cache / "rec.json"
    assert main(["convert", "a.pdf", "--schema", "v0.2", "--body", "BE", "--out", str(out)]) == 0
    row = json.loads(out.read_text())
    assert row["status"] == "ok" and row["record"]["schema_version"] == "0.2.0"
    assert main(["convert", "a.pdf", "--schema", "v0.2"]) == 2
    assert "level_unknown" in capsys.readouterr().err
    assert main(["convert", "--batch", "x.txt", "--schema", "v0.2", "--body", "BE"]) == 2
