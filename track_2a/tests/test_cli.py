import json
import subprocess
import sys
import urllib.error

import pytest

from gegenprobe import net, pdftext
from gegenprobe.__main__ import guess_lang, main
from gegenprobe.convert import batch, output
from gegenprobe.paths import PDF_CACHE

# a German answer page with a decision anchor, and a member text with an empty answer template (frozen rules decide both)
ANSWER = ["Auszug aus dem Protokoll des Regierungsrates des Kantons Bern\nRRB-Nr.: 879/2024 vom 28. August 2024\n"
          "Antwort des Regierungsrates\nDer Regierungsrat beantwortet die Interpellation wie folgt.\n"]
QUESTION = ["Parlamentarischer Vorstoss\nEingereicht am: 14.06.2022\nRRB-Nr.:\nvom\nAntrag Regierungsrat: Auswahl\n"
            "Der Regierungsrat wird beauftragt, ...\nLetzte Bearbeitung: 19.03.2024 | Version 1\n"]


def test_guess_lang():
    assert guess_lang("Der Regierungsrat wird die Motion nicht annehmen und die") == "de"
    assert guess_lang("Le Conseil d'État est pour le rejet de la motion et des") == "fr"
    assert guess_lang("Il Consiglio di Stato è per la risposta che della mozione") == "it"


def test_value_row_has_rule_span_context_number_and_role():
    row = batch.convert_pages(ANSWER, sha="0" * 64, extractor="pdftotext-test", image_only=False,
                              inp={"source": "x.pdf", "opd_doc_id": "404590", "body": "BE", "affair_number": "2024.RRGR.91"})
    f = row["fields"]["answer_date"]
    assert row["status"] == "ok" and f["value"] == "2024-08-28" and f["route"] == "rule"
    assert f["rule_id"] and f["decision_number"] == "879/2024"
    assert ANSWER[0][f["char_start"]:f["char_end"]] == f["quote"]
    assert "vom" in f["context"] and f["quote"] in f["context"] and len(f["context"]) <= 201
    assert row["doc_role"]["value"] == "answer"
    rec = row["record"]
    assert rec["doc"]["doc_id"] == "opd:404590" and rec["doc"]["source"] == "opd" and rec["doc"]["role"] == "answer"
    assert rec["answer_date"]["rule"] == f["rule_id"] and rec["answer_date"]["decision_number"] == "879/2024"
    assert row["input"]["affair_number"] == "2024.RRGR.91"


def test_question_row_is_a_typed_null_not_the_footer_or_submission_date():
    row = batch.convert_pages(QUESTION, sha="1" * 64, extractor="pdftotext-test", image_only=False, inp={"source": "q.pdf"})
    f = row["fields"]["answer_date"]
    assert f["value"] is None and f["null_reason"] and f["evidence"]
    assert row["doc_role"]["value"] == "question"
    assert row["record"]["doc"]["doc_id"].startswith("sha256:")


class _Fake:
    build = "fake:test"

    def score(self, user, prefix, conts):  # null cont first; give the first date candidate the best score
        return [-50.0] + [-1.0 - i for i in range(len(conts) - 1)]


def test_review_mode_attaches_a_flagged_suggestion_and_never_writes_the_field():
    pages = ["Gemeinderat Musterdorf\nSitzung\nDie Antwort folgt.\nMusterdorf, 3. März 2025\n"]
    rules_only = batch.convert_pages(pages, sha="2" * 64, extractor="t", image_only=False, inp={"source": "r.pdf"})
    row = batch.convert_pages(pages, sha="2" * 64, extractor="t", image_only=False, inp={"source": "r.pdf"},
                              mode="review", backend=_Fake(), theta=0.0)
    a, b = row["fields"]["answer_date"], rules_only["fields"]["answer_date"]
    assert {k: a.get(k) for k in ("value", "null_reason", "route")} == {k: b.get(k) for k in ("value", "null_reason", "route")}
    assert rules_only["fields"]["answer_date"]["value"] is None  # the rules leave it open: the residue
    assert row["needs_review"] and row["review_suggestion"]["value"] == "2025-03-03"
    assert row["review_suggestion"]["context"] and not rules_only["needs_review"]
    # reviewer aids: the closed set with Apertus' shares, the null share, and the confidence band
    cands = a["candidates"]
    assert [c["value"] for c in cands] == ["2025-03-03"] and cands[0]["chosen"] and cands[0]["share"] > 0.99
    assert "share" not in b["candidates"][0] and a["null_share"] < 0.01
    band = row["review_suggestion"]["band"]
    assert band["band"] == "strong" and "correct" in band["measured"]


@pytest.mark.parametrize("exc,kind", [
    (net.Disallowed("https://x.ch/a.pdf"), "robots_disallowed"),
    (urllib.error.HTTPError("https://x.ch/a.pdf", 404, "Not Found", {}, None), "http_error"),
    (urllib.error.URLError(TimeoutError("timed out")), "timeout"),
    (urllib.error.URLError("Name or service not known"), "network_error"),
    (pdftext.FetchError("not_a_pdf", "returned an HTML page"), "not_a_pdf"),
    (pdftext.FetchError("sha_mismatch", "changed"), "sha_mismatch"),
])
def test_fetch_failures_become_typed_rows(monkeypatch, exc, kind):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(pdftext, "fetch_pdf", boom)
    row = batch.convert_one("https://x.ch/a.pdf", {"opd_doc_id": "7"})
    assert row == {"status": kind, "reason": row["reason"], "input": {"source": "https://x.ch/a.pdf", "opd_doc_id": "7"}}
    assert kind in output.FAILURE_KINDS and row["reason"]


def test_html_page_is_not_a_pdf(monkeypatch):
    monkeypatch.setattr(net, "get", lambda *a, **k: b"<!DOCTYPE html><html><body>viewer</body></html>")
    with pytest.raises(pdftext.FetchError) as e:
        pdftext.fetch_pdf("https://x.ch/viewer")
    assert e.value.kind == "not_a_pdf" and "HTML" in e.value.detail and isinstance(e.value, ValueError)


def test_single_mode_exit_code_and_stderr(capsys):
    assert main(["convert", "/nonexistent/file.pdf"]) == 2
    out, err = capsys.readouterr()
    assert json.loads(out)["status"] == "file_not_found" and err.startswith("file_not_found:")


def test_review_without_fitted_theta_explains(monkeypatch):
    monkeypatch.setattr(batch, "make_backend", lambda spec: type("B", (), {"build": "fake:unfitted"})())
    with pytest.raises(SystemExit) as e:
        batch.resolve_review("whatever")
    assert "Fitted builds:" in str(e.value) and "fake:unfitted" in str(e.value)


@pytest.mark.skipif(not any(PDF_CACHE.glob("*.pdf")), reason="needs a cached PDF in .work/pdf")
def test_convert_cli_on_a_real_pdf():
    pdf = sorted(PDF_CACHE.glob("*.pdf"))[0]
    out = subprocess.run([sys.executable, "-m", "gegenprobe", "convert", str(pdf)], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    f = d["fields"]["answer_date"]
    assert d["status"] == "ok" and d["mode"] == "rules_only" and d["review_suggestion"] is None
    assert d["record"]["schema_version"] == "0.1.0"
    if f["value"] is not None:
        assert f["page"] >= 1 and f["char_end"] > f["char_start"] and f["quote"] and f["rule_id"]
    else:
        assert f["null_reason"]


def test_rule_value_carries_its_measured_precision_and_alternatives():
    pages = ["Regierungsrat\nRegierungsratsbeschluss vom 3. Dezember 2019\nAntwort des Regierungsrates\n"
             "Basel, 4. Dezember 2019\n"]
    row = batch.convert_pages(pages, sha="3" * 64, extractor="t", image_only=False, inp={"source": "a.pdf"})
    f = row["fields"]["answer_date"]
    assert f["value"] == "2019-12-03" and f["rule_id"] == "rrb_vom"
    assert f["rule_precision"].startswith("3/5")
    vals = [c["value"] for c in f["candidates"]]
    assert vals == ["2019-12-03", "2019-12-04"] and f["candidates"][0]["chosen"] and "chosen" not in f["candidates"][1]


def test_band_thresholds():
    from gegenprobe.convert.precision import band
    assert band(-12.0, 10.4) == "strong" and band(-5.0, 10.4) == "strong"
    assert band(-4.9, 10.4) == "weak" and band(10.4, 10.4) == "weak"
    assert band(10.5, 10.4) is None and band(None, 10.4) is None


def test_multiple_recommendation_phrases_are_flagged():
    from gegenprobe.convert import output
    pages = ["Le Conseil-exécutif propose au Grand Conseil de rejeter le point 1 de la motion.\n"
             "Le Conseil-exécutif propose au Grand Conseil d'adopter les points 2 et 3 de la motion.\n"]
    rp = output.recommendation_phrases(pages)
    assert rp["multiple"] == (len(rp["labels"]) > 1)
