"""Unlocked overlay on the frozen converter (convert/overlay.py, wired in convert/batch.py): partial recommendations, rule
coverage per parliament, dates right after an answer heading, user anchors, --explain. Offline, no model."""
import json

import pytest

from gegenprobe import paths
from gegenprobe.__main__ import main
from gegenprobe.convert import batch, overlay, rules
from gegenprobe.schema.schema_v0_1 import DocExtraction

ROOT = paths.ROOT
SG_ANCHORS = ROOT / "docs" / "examples" / "anchors_SG.json"


def conv(pages, **inp):
    anchors = inp.pop("anchors", None)
    explain = inp.pop("explain", False)
    row = batch.convert_pages(pages, sha="a" * 64, extractor="pdftotext-test", image_only=False,
                              inp={"source": "t.pdf", **inp}, anchors=anchors, explain=explain)
    DocExtraction.model_validate(row["record"])  # the record stays a valid schema v0.1 object
    return row


# ---------------------------------------------------------------- 1. partial recommendation (U4: FR 508438)
FR_508438 = ["Réponse du Conseil d’Etat à un instrument parlementaire\nMotion 2024-GC-316\n",
             "il\nconvient de modifier ces deux actes en conséquence.\n"
             "Le Conseil d’Etat invite donc le Grand Conseil à accepter partiellement la motion dans le sens\nsuivant :\n"
             "> Le Conseil d’Etat propose au Grand Conseil une modification de l’article 8a al. 2 de la loi.\n"]


def test_fr_508438_accepter_partiellement_is_partial_with_the_qualifier_in_the_quote():
    assert rules.recommendation(FR_508438)["value"] == "accept"  # the frozen rule alone (unchanged)
    row = conv(FR_508438, affair_type="Motion")
    f = row["fields"]["recommendation"]
    assert f["value"] == "partial" and f["rule_id"] == "rec_accept+qualifier_partial"
    assert f["quote"].endswith("accepter partiellement") and FR_508438[1][f["char_start"]:f["char_end"]].endswith("partiellement")
    assert f["qualifier"]["text"] == "partiellement" and f["qualifier"]["effect"] == "partial"
    q = f["qualifier"]
    assert FR_508438[q["page"] - 1][q["char_start"]:q["char_end"]] == "partiellement"
    assert f["rule_precision"].startswith("not measured")  # the frozen rule's 2/2 does not carry over
    assert row["record"]["recommendation"]["value"] == "partial"
    assert row["record"]["recommendation"]["quote"].endswith("partiellement")


@pytest.mark.parametrize("sentence,value,review", [
    ("Der Regierungsrat beantragt, die Motion teilweise erheblich zu erklären.", "partial", False),
    ("Le Conseil d'État propose de rejeter partiellement la motion.", "partial", False),
    ("Il Consiglio di Stato invita ad accogliere parzialmente la mozione.", "partial", False),
    ("Il Consiglio di Stato invita ad accogliere in parte la mozione.", "partial", False),
    ("Der Regierungsrat beantragt, die Motion im Sinne der Erwägungen erheblich zu erklären.", "accept", True),
    ("Der Regierungsrat beantragt, die Motion mit geändertem Wortlaut anzunehmen.", "accept", True),
    ("Le Conseil d'État propose de rejeter la motion sous réserve des moyens disponibles.", "reject", True),
    ("Le Conseil d'État propose de rejeter le point 1 de la motion.", "reject", False),  # per point: not a qualifier here
    ("Der Regierungsrat beantragt, die Motion anzunehmen. Teilweise ist sie bereits umgesetzt.", "accept", False),
])
def test_recommendation_qualifiers(sentence, value, review):
    row = conv([sentence + "\n"], affair_type="Motion", body="BE")  # a covered body: only the qualifier can flag
    f = row["fields"]["recommendation"]
    assert f["value"] == value and bool(f.get("needs_review")) == review and row["needs_review"] == review
    if review:
        assert "qualified" in f["review_reason"] and row["review_reasons"][0]["field"] == "recommendation"


# ---------------------------------------------------------------- 2. parliaments without rules
SG_QUESTION = ["Kantonsrat St.Gallen\n\n42.26.14\n\nSJD / Motion SVP-Fraktion vom 10. Juni 2026\n\nTitel\n"
               "Antrag der Regierung vom 18. August 2026\n\nNichteintreten.\n\nBegründung:\nDie Grundlagen ...\n"]


def test_uncovered_body_gets_no_rules_for_body_and_needs_review():
    row = conv(SG_QUESTION, body="SG", affair_type="Motion")
    assert row["rules_coverage"]["status"] == "not_covered" and row["needs_review"]
    for name in ("answer_date", "recommendation"):
        f = row["fields"][name]
        assert f["value"] is None and f["null_reason"] == "no_rules_for_body" and f["needs_review"]
        assert "SG" in f["evidence"] and row["record"][name]["null_reason"] == "no_rules_for_body"
    assert overlay.coverage_warning(row["rules_coverage"]).startswith("warning: body SG")


def test_covered_and_unknown_bodies_keep_present_unanchored():
    for inp in ({"body": "BE"}, {"body": "261"}, {}):
        row = conv(SG_QUESTION, affair_type="Motion", **inp)
        assert row["fields"]["answer_date"]["null_reason"] == "present_unanchored"
        assert not row["needs_review"] and row["rules_coverage"]["status"] in ("covered", "unknown")
        assert overlay.coverage_warning(row["rules_coverage"]) is None


def test_rule_value_on_an_uncovered_body_is_kept_but_flagged():
    pages = ["Regierungsratsbeschluss vom 3. Dezember 2019\nAntwort des Regierungsrates\n"]
    row = conv(pages, body="AG")
    f = row["fields"]["answer_date"]
    assert f["value"] == "2019-12-03" and f["route"] == "rule" and f["needs_review"] and "AG" in f["review_reason"]


def test_cli_warns_on_stderr_for_an_uncovered_body(monkeypatch, capsys):
    monkeypatch.setattr(batch, "convert_one", lambda src, inp, **kw: conv(SG_QUESTION, **inp))
    assert main(["convert", "x.pdf", "--body", "SG"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["needs_review"] and "warning: body SG is not in data/convert/rules_coverage.json" in err


# ---------------------------------------------------------------- 3. a date right after the answer heading
SG_923254 = ("Kantonsrat St.Gallen\n\n51.26.59\n\nBUD / Interpellation Lemmenmeier-St.Gallen vom 9. Juni 2026\n\n"
             "Funktioniert die Alt-Medikamentenentsorgung im Kanton St.Gallen?\nAntwort der Regierung vom 1. September 2026\n\n"
             "Eva Lemmenmeier-St.Gallen erkundigt sich in ihrer Interpellation vom 9. Juni 2026 nach ...\n")
FR_HEAD_ONE_LINE = ("Conseil d'Etat CE\nRéponse du Conseil d'Etat à un instrument parlementaire\nMotion 2024-GC-316\n"
                    "Dépôt : 19.12.2024\nRéponse du Conseil d'Etat : 06.05.2025\nI. Résumé de la motion\nPar motion ...\n")
FR_HEAD_PDFTOTEXT = ("Conseil d’Etat CE\nStaatsrat SR\n\nRéponse du Conseil d’Etat à un instrument parlementaire\n—\n"
                     "Motion 2024-GC-316\nDépôt :\n\n19.12.2024\n\nRéponse du Conseil d’Etat :\n\n06.05.2025\n\n"
                     "I. Résumé de la motion\n")


@pytest.mark.parametrize("text,value,quote", [
    (SG_923254, "2026-09-01", "1. September 2026"),
    (FR_HEAD_ONE_LINE, "2025-05-06", "06.05.2025"),
    (FR_HEAD_PDFTOTEXT, "2025-05-06", "06.05.2025"),
])
def test_heading_proximity_surfaces_the_date_first_but_never_fills_the_field(text, value, quote):
    assert rules.answer_date([text])["rule"] == "heading_without_date"  # the frozen rules abstain
    row = conv([text])
    f = row["fields"]["answer_date"]
    assert f["value"] is None and f["evidence"] == "heading_without_date" and f["needs_review"]
    c = f["candidates"][0]
    assert c["value"] == value and c["suggested_by_heading_proximity"] and text[c["char_start"]:c["char_end"]] == quote
    assert sum(1 for x in f["candidates"] if x["value"] == value) == 1
    assert row["needs_review"] and "candidates[0]" in row["review_reasons"][0]["reason"]
    assert row["record"]["answer_date"]["kind"] == "null"


def test_heading_naming_the_instrument_is_followed_by_the_instruments_date():
    text = "Réponse à l'interpellation du 5.9.2025\nDépositaires: ...\nA. Propos liminaires\nLe stade actuel ...\n"
    assert rules.answer_date([text])["rule"] == "heading_without_date"
    assert overlay.heading_date([text]) is None


def test_heading_followed_by_prose_is_not_a_heading_date():
    text = ("Antwort des Regierungsrates\nDer Regierungsrat hat die Interpellation am 3. März 2025 erhalten. "
            "Er beantwortet sie wie folgt.\n")
    assert rules.answer_date([text])["rule"] == "heading_without_date"
    assert overlay.heading_date([text]) is None
    row = conv([text])
    assert "suggested_by_heading_proximity" not in row["fields"]["answer_date"]["candidates"][0]
    assert not row["needs_review"]


# ---------------------------------------------------------------- 6. user anchors
def test_sg_example_anchors_fill_both_fields_with_route_user_anchor():
    anchors = overlay.load_anchors(str(SG_ANCHORS))
    row = conv(SG_QUESTION, body="SG", affair_type="Motion", anchors=anchors)
    ad, rec = row["fields"]["answer_date"], row["fields"]["recommendation"]
    assert ad["value"] == "2026-08-18" and ad["route"] == "user_anchor"
    assert ad["rule_id"] == "user_anchor:sg_antrag_der_regierung_vom"
    assert SG_QUESTION[0][ad["char_start"]:ad["char_end"]] == ad["quote"] == "18. August 2026" and ad["page"] == 1
    assert rec["value"] == "reject" and rec["quote"] == "Nichteintreten" and rec["route"] == "user_anchor"
    assert not row["needs_review"] and row["rules_coverage"]["status"] == "user_anchors"
    assert row["doc_role"]["value"] == "answer"
    r = row["record"]
    assert r["answer_date"]["route"] == "user_anchor" and r["answer_date"]["basis"] == "normalised"
    assert r["answer_date"]["rule"] == "user_anchor:sg_antrag_der_regierung_vom"
    assert r["answer_date"]["quote"] == "18. August 2026"
    assert r["recommendation"]["route"] == "user_anchor" and r["recommendation"]["value"] == "reject"


def test_sg_heading_layout_with_anchors():
    row = conv([SG_923254], body="SG", affair_type="Interpellation", anchors=overlay.load_anchors(str(SG_ANCHORS)))
    ad = row["fields"]["answer_date"]
    assert ad["value"] == "2026-09-01" and ad["route"] == "user_anchor" and not row["needs_review"]
    assert row["fields"]["recommendation"]["null_reason"] == "not_applicable"


def test_anchors_run_only_after_the_frozen_rules():
    anchors = overlay.load_anchors(str(SG_ANCHORS))
    pages = ["Regierungsratsbeschluss vom 3. Dezember 2019\nAntwort der Regierung vom 1. September 2026\n"]
    row = conv(pages, body="SG", anchors=anchors)
    assert row["fields"]["answer_date"]["value"] == "2019-12-03" and row["fields"]["answer_date"]["route"] == "rule"


def _write(tmp_path, d):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(d))
    return str(p)


def test_anchor_without_date_group_takes_the_next_date_and_needs_review(tmp_path):
    spec = {"bodies": {"*": {"answer_date": [{"id": "x", "pattern": "Antrag der Regierung"}]}}}
    a = overlay.load_anchors(_write(tmp_path, spec))
    row = conv(SG_QUESTION, body="ZZ", anchors=a)
    f = row["fields"]["answer_date"]
    assert f["value"] == "2026-08-18" and f["route"] == "user_anchor" and f["needs_review"] and row["needs_review"]


def test_anchor_whose_date_group_does_not_parse_gives_no_value(tmp_path):
    a = overlay.load_anchors(_write(tmp_path, {"bodies": {"SG": {"answer_date": [
        {"id": "bad", "pattern": r"Antrag der Regierung vom (?P<date>\d+\. \w+)"}]}}}))
    row = conv(SG_QUESTION, body="SG", anchors=a, explain=True)
    assert row["fields"]["answer_date"]["value"] is None
    assert row["fields"]["answer_date"]["null_reason"] == "no_rules_for_body"
    assert any("does not parse" in s["result"] for s in row["explain"]["answer_date"])


@pytest.mark.parametrize("bad,msg", [
    ({"x": 1}, "needs an object"),
    ({"bodies": {"SG": {"answer_date": [{"pattern": "("}]}}}, "invalid regular expression"),
    ({"bodies": {"SG": {"recommendation": [{"pattern": "Nein", "label": "maybe"}]}}}, "label must be one of"),
    ({"bodies": {"SG": {"answerdate": []}}}, "only 'answer_date'"),
])
def test_malformed_anchor_files_are_refused(tmp_path, bad, msg):
    with pytest.raises(overlay.AnchorError, match=msg):
        overlay.load_anchors(_write(tmp_path, bad))


def test_cli_malformed_anchors_exit_2(tmp_path, capsys):
    assert main(["convert", "x.pdf", "--anchors", str(tmp_path / "missing.json")]) == 2
    assert "no such file" in capsys.readouterr().err


# ---------------------------------------------------------------- 7. --explain and the cache path
def test_explain_lists_every_frozen_rule_and_matches_the_frozen_decision():
    for pages in (SG_QUESTION, [SG_923254], [FR_HEAD_PDFTOTEXT], ["RRB-Nr.: 879/2024 vom 28. August 2024\n"],
                  ["Antwort des Regierungsrates\nBasel, 4. Dezember 2019\n"]):
        tr = overlay.trace_answer_date(pages)
        assert [s for s in tr if s["result"].startswith("fired")][-1]["step"] == rules.answer_date(pages)["rule"]
    tr = overlay.trace_answer_date(SG_QUESTION)
    assert [s["step"] for s in tr[1:1 + len(rules.DECISION)]] == [rid for rid, _ in rules.DECISION]
    assert any("dispatch rules" in s["result"] for s in tr)  # why the place-date rules were not tried


def test_explain_row_carries_cache_path_and_traces(monkeypatch, capsys):
    row = conv([SG_923254], body="SG", affair_type="Motion", explain=True)
    ex = row["explain"]
    assert ex["cache"]["work"] == str(paths.WORK) and ex["cache"]["pdf_cache"] == str(paths.PDF_CACHE)
    # SG is outside the rule coverage: after the frozen trace (ending at no_anchor) the Q/A lexicon is tried (round 8)
    steps = [s["step"] for s in ex["recommendation"]]
    assert ex["answer_date"][-1]["step"] == "heading proximity" and steps[-2:] == ["no_anchor", "Q/A lexicon (qa_cli's rule)"]
    monkeypatch.setattr(batch, "convert_one", lambda src, inp, **kw: conv([SG_923254], explain=kw["explain"], **inp))
    assert main(["convert", "x.pdf", "--body", "SG", "--explain"]) == 0
    err = capsys.readouterr().err
    assert f"cache: {paths.WORK}" in err and "be_rrb_inline" in err and "heading proximity" in err


def test_verbose_prints_the_cache_path(monkeypatch, capsys):
    monkeypatch.setattr(batch, "convert_one", lambda src, inp, **kw: conv([SG_923254], **inp))
    main(["convert", "x.pdf", "--body", "BE", "-v"])
    assert f"cache: {paths.WORK}" in capsys.readouterr().err


# ---------------------------------------------------------------- whole-affair output (P3): metadata vs document values
def test_p3_affairs_mark_metadata_values_and_give_every_document_value_a_span():
    from gegenprobe.schema.schema_v0_1 import Affair, Valued, iter_fields
    files = sorted((paths.RESULTS / "eval3").glob("p3__*.json"))
    if not files:
        pytest.skip("no committed P3 output")
    found = []

    def find(x):
        if isinstance(x, dict):
            if x.get("schema_version") == "0.1.0" and "qa" in x and "ref" in x:
                found.append(x)
                return
            for v in x.values():
                find(v)
        elif isinstance(x, list):
            for v in x:
                find(v)
    for f in files:
        find(json.loads(f.read_text()))
    assert found
    n_meta = n_doc = 0
    for a in found:
        for path, v in iter_fields(Affair.model_validate(a)):
            if not isinstance(v, Valued):
                continue
            if v.route == "metadata":
                assert v.basis == "metadata" and v.source and v.page is None, path
                n_meta += 1
            elif not (v.route in ("apertus", "ocr+apertus") and v.page is None):  # doc-level model enum: no single span
                assert v.doc and v.page and v.char_end > v.char_start and v.quote, path
                n_doc += 1
    assert n_meta and n_doc
