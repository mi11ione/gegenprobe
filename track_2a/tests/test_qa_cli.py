"""`python -m gegenprobe.qa_cli` (the Q/A extractor on one affair's question + answer document) on synthetic text: OPD
stored text (one page, or form feeds as page breaks), PDFs (text extraction stubbed), typed input errors. Rules only."""
import json
import subprocess
import sys
import urllib.robotparser

import pytest

from gegenprobe import qa_cli
from test_qa import A, Q


def run(capsys, *argv):
    rc = qa_cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


@pytest.fixture
def opd(tmp_path):
    q = tmp_path / "q.txt"
    q.write_text(Q[0], encoding="utf-8")
    a = tmp_path / "a.json"  # a docs-export row: id + text
    a.write_text(json.dumps({"id": 4711, "affair_id": 99, "text": A[0]}, ensure_ascii=False), encoding="utf-8")
    return q, a


def test_opd_text_both_documents_json(capsys, opd):
    q, a = opd
    rc, out, _ = run(capsys, "--opd-text-question", str(q), "--opd-text-answer", str(a), "--json")
    assert rc == 0
    r = json.loads(out)
    assert r["status"] == "ok" and r["mode"] == "rules_only" and r["model_calls"] == 0 and r["language"] == "de"
    for role in ("question", "answer"):
        d = r["documents"][role]
        assert d["kind"] == "opd_text" and d["pages"] == 1 and "no page breaks" in d["note"]
    assert r["documents"]["answer"]["doc_id"] == "opd:4711" and r["documents"]["question"]["doc_id"] == "file:q.txt"
    v = r["view"]
    assert len(v["questions"]) == 3 and v["answer_style"] == "per_question"
    a1 = v["answers"][0]["span"]
    assert "zwölf Kilometer" in A[0][a1["g_start"]:a1["g_end"]]
    assert v["submitter"]["name"] == "Anna Muster" and v["recommendation"] == "not_applicable"
    rec = r["records"]
    assert len(rec["qa_items"]) == 3 and all(it["answer"]["kind"] == "value" for it in rec["qa_items"])
    assert {x["page"] for it in rec["qa_items"] for x in (it["question"], it["answer"])} == {1}
    assert rec["qa_items"][0]["answer"]["doc"] == "opd:4711" and r["left_open"] == []


def test_human_report_says_one_page(capsys, opd):
    q, a = opd
    rc, out, _ = run(capsys, "--opd-text-question", str(q), "--opd-text-answer", str(a))
    assert rc == 0
    assert "no page breaks: read as one page" in out and "rules only, 0 model calls" in out
    assert "Q1  p1:" in out and "A3  p1:" in out and "submitter: Anna Muster" in out
    assert "recommendation: not_applicable" in out


def test_form_feeds_are_page_breaks(capsys, tmp_path):
    a = tmp_path / "a.txt"
    a.write_text(A[0].replace("Zu Frage 3:", "\fZu Frage 3:"), encoding="utf-8")
    q = tmp_path / "q.txt"
    q.write_text(Q[0], encoding="utf-8")
    rc, out, _ = run(capsys, "--opd-text-question", str(q), "--opd-text-answer", str(a), "--json")
    r = json.loads(out)
    assert rc == 0 and r["documents"]["answer"]["pages"] == 2 and "form feeds" in r["documents"]["answer"]["note"]
    assert r["records"]["qa_items"][2]["answer"]["page"] == 2


def test_answer_only_with_affair_type_question(capsys, opd):
    _, a = opd
    rc, out, _ = run(capsys, "--opd-text-answer", str(a), "--affair-type", "Schriftliche Anfrage", "--json")
    r = json.loads(out)
    assert rc == 0 and r["affair_type"] == "Question" and r["view"]["recommendation"] == "not_applicable"
    assert r["documents"]["question"] == {"role": "question", "given": False}


def test_unanchored_answers_are_left_open(capsys, tmp_path):
    q = tmp_path / "q.txt"
    q.write_text(Q[0], encoding="utf-8")
    a = tmp_path / "a.txt"
    a.write_text("Regierungsrat\n\nDer Regierungsrat beantwortet die Interpellation wie folgt:\n\n"
                 "Die Velowege werden laufend ergänzt. Ein Zeitplan liegt noch nicht vor, und die Mittel werden mit dem "
                 "nächsten Budget beantragt.\n\nIm Namen des Regierungsrates\n", encoding="utf-8")
    rc, out, _ = run(capsys, "--opd-text-question", str(q), "--opd-text-answer", str(a))
    assert rc == 0
    assert "left open (review):" in out and "answers (questions 1, 2, 3)" in out
    assert "A1  -" in out


def test_pdf_input(monkeypatch, capsys, tmp_path):
    """A PDF goes through convert's fetch/cache and pdftotext (stubbed here): spans keep their page numbers."""
    from gegenprobe import pdftext
    from gegenprobe.convert import batch

    pages = {"q": [Q[0][:120], Q[0][120:]], "a": A}
    monkeypatch.setattr(batch, "get_document", lambda src, **kw: (("0" if "q" in src else "1") * 64, tmp_path / src))
    monkeypatch.setattr(pdftext, "extract", lambda sha, path=None, **kw: dict(
        sha256=sha, extractor="pdftotext-test", image_only=False, pages=pages["q" if sha.startswith("0") else "a"]))
    rc, out, _ = run(capsys, "--question", "q.pdf", "--answer", "a.pdf", "--json")
    r = json.loads(out)
    assert rc == 0 and r["documents"]["question"]["pages"] == 2 and r["documents"]["question"]["kind"] == "pdf"
    assert r["documents"]["question"]["doc_id"] == "sha256:" + "0" * 16
    assert r["records"]["qa_items"][0]["question"]["page"] == 2 and r["view"]["answer_style"] == "per_question"


def test_typed_input_errors(capsys, tmp_path, opd):
    q, _ = opd
    rc, out, err = run(capsys, "--question", str(q), "--json")
    assert rc == 2 and json.loads(out)["status"] == "not_a_pdf" and "--opd-text-question" in err
    rc, _, err = run(capsys, "--answer", str(tmp_path / "missing.pdf"))
    assert rc == 2 and "file_not_found" in err
    rc, _, err = run(capsys, "--question", "x.pdf", "--opd-text-question", str(q))
    assert rc == 2 and "not both" in err
    rc, _, err = run(capsys)
    assert rc == 2 and "at least one document" in err
    with pytest.raises(SystemExit) as e:
        qa_cli.main(["--opd-text-question", str(q), "--affair-type", "no-such-type"])
    assert e.value.code == 2


def test_url_refused_when_matcher_inactive(monkeypatch, capsys):
    cls = urllib.robotparser.RobotFileParser
    monkeypatch.setattr(cls, "can_fetch", cls.can_fetch._rfc9309_orig)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("network touched"))
    rc, out, err = run(capsys, "--question", "https://example.org/q.pdf", "--json")
    assert rc == 2 and json.loads(out)["status"] == "robots_matcher_inactive"


def test_module_entry_point():
    p = subprocess.run([sys.executable, "-m", "gegenprobe.qa_cli", "--help"], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and "--opd-text-question" in p.stdout and "rules only, no model" in " ".join(p.stdout.split())
