"""Round-5 converter and product post-processing: resume re-runs rows whose options changed, --anchors-review, the
letter-line hint, and the whole-affair post-processing (no false typed null, the Luzern submission-date guard)."""
import json
from pathlib import Path

from gegenprobe import __main__ as cli
from gegenprobe import affair_post
from gegenprobe.convert import batch, hints, overlay

ROOT = Path(__file__).resolve().parents[1]

# the Schaffhausen answer-letter layout U4 met (names and text invented): letterhead, address to the parliament, place-date
SH = [
    "Kanton Schaffhausen\nRegierungsrat\nBeckenstube 7\nCH-8200 Schaffhausen\n\nRegierungsrat\n\nAn die\n"
    "Mitglieder des Kantonsrates\n\nSchaffhausen, 21. Dezember 2021\n\nPostulat Nr. 2021/10 von Kantonsrat Max Muster; "
    "Bericht über die Härtefallklausel\nSchriftliche Beantwortung\nSehr geehrter Herr Präsident\n\nKantonsrat Max Muster "
    "hat am 14. November 2021 in seinem Postulat den Regierungsrat eingeladen, zu berichten.\n" + "Text der Antwort. " * 80,
]


def _fake_convert_one(calls):
    def f(source, inp=None, **kw):
        calls.append((source, kw.get("anchors_review")))
        return {"status": "ok", "input": {"source": source, **{k: v for k, v in (inp or {}).items() if v}},
                "needs_review": False}
    return f


# ------------------------------------------------------------------------------------------------ 5a resume
def test_resume_reruns_rows_when_the_anchors_file_or_an_option_changed(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(batch, "convert_one", _fake_convert_one(calls))
    inp = tmp_path / "in.txt"
    inp.write_text("https://x.ch/a.pdf\nhttps://x.ch/b.pdf\n")
    out = tmp_path / "out.jsonl"
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"bodies": {"SH": {"answer_date": [{"pattern": "Beschluss vom {DATE}"}]}}}))
    args = ["convert", "--batch", str(inp), "--out", str(out), "--anchors", str(anchors)]
    assert cli.main(args) == 0 and len(calls) == 2
    assert cli.main(args) == 0 and len(calls) == 2  # unchanged: skipped
    assert "skipped (already done) 2" in capsys.readouterr().err
    anchors.write_text(json.dumps({"bodies": {"SH": {"answer_date": [{"pattern": "Beschluss vom {DATE}"},
                                                                     {"pattern": "Schaffhausen, {DATE}"}]}}}))
    assert cli.main(args) == 0 and len(calls) == 4  # one more anchor: both rows again
    assert "re-run (options changed) 2" in capsys.readouterr().err
    assert cli.main(args + ["--queue-nulls"]) == 0 and len(calls) == 6  # another option: again
    assert cli.main(args + ["--queue-nulls"]) == 0 and len(calls) == 6
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(rows) == 6 and len({r["options"]["hash"] for r in rows}) == 3
    assert rows[-1]["options"]["queue_nulls"] is True and len(rows[-1]["options"]["anchors_sha256"]) == 64


def test_write_queue_reads_the_last_row_per_input(tmp_path):
    rows = tmp_path / "rows.jsonl"
    rows.write_text("".join(json.dumps(r) + "\n" for r in (
        {"status": "ok", "input": {"source": "a"}, "needs_review": True},
        {"status": "ok", "input": {"source": "a"}, "needs_review": False},  # re-run with a better anchor: resolved
        {"status": "ok", "input": {"source": "b"}, "needs_review": True})))
    assert batch.write_queue(str(rows), str(tmp_path / "q.jsonl")) == 1


def test_affair_type_change_reruns_the_row():
    a = batch.options_of({"source": "s", "affair_type": "Question"}, mode="rules_only")
    b = batch.options_of({"source": "s", "affair_type": "Interpellation"}, mode="rules_only")
    c = batch.options_of({"source": "other-url", "affair_type": "Question"}, mode="rules_only")
    assert a["hash"] != b["hash"] and a["hash"] == c["hash"] and a["affair_type"] == "Question"


# ------------------------------------------------------------------------------------------------ 5b --anchors-review
def _anchors(tmp_path) -> dict:
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"bodies": {"SH": {"answer_date": [
        {"id": "sh_letter", "pattern": r"Kantonsrates\s+Schaffhausen, {DATE}", "role": "dispatch"}]}}}))
    return overlay.load_anchors(str(f))


def test_anchors_review_keeps_user_anchor_values_flagged(tmp_path):
    kw = dict(sha="0" * 64, extractor="pdftotext", image_only=False, inp=dict(body="SH"), anchors=_anchors(tmp_path))
    plain = batch.convert_pages(SH, **kw)
    f = plain["fields"]["answer_date"]
    assert f["value"] == "2021-12-21" and f["route"] == "user_anchor"
    assert not f.get("needs_review")  # documented default: a user-anchor value is not flagged
    flagged = batch.convert_pages(SH, **kw, anchors_review=True)
    g = flagged["fields"]["answer_date"]
    assert g["value"] == "2021-12-21" and g["needs_review"] and "--anchors-review" in g["review_reason"]
    assert flagged["needs_review"] and "sh_letter" in flagged["review_reasons"][0]["reason"]


# ------------------------------------------------------------------------------------------------ 5d letter-line hint
def test_letter_line_hint_puts_the_date_first_but_never_fills_the_field():
    r = batch.convert_pages(SH, sha="0" * 64, extractor="pdftotext", image_only=False, inp=dict(body="SH"),
                            explain=True)
    f = r["fields"]["answer_date"]
    assert f["value"] is None and f["null_reason"] == "no_rules_for_body"  # rules_only: nothing written
    c = f["candidates"][0]
    assert c["value"] == "2021-12-21" and c["suggested_by_letter_line"] and c["address"] == "An die Mitglieder des Kantonsrates"
    assert f["needs_review"] and "suggested_by_letter_line" in f["review_reason"]
    assert any(t["step"] == "letter-line hint" for t in r["explain"]["answer_date"])


def test_letter_line_hint_ignores_letters_to_the_government_and_executive_addressees():
    member = ["Schaffhausen, 1. Oktober 2026\n\nAn den Regierungsrat\ndes Kantons Schaffhausen\n\nInterpellation\n" + "x " * 50]
    assert hints.letter_line_date(member) is None
    city = ["An den Gemeinderat\n\nBern, 3. März 2024\n\n" + "x " * 50]  # Bern's Gemeinderat is the executive
    assert hints.letter_line_date(city) is None
    fr = ["Au Grand Conseil\ndu canton de Vaud\n\nLausanne, le 4 avril 2012\n\n" + "x " * 50]
    assert hints.letter_line_date(fr)["value"] == "2012-04-04"
    it = ["Al Gran Consiglio\n\nBellinzona, 3 luglio 2024\n\n" + "x " * 50]
    assert hints.letter_line_date(it)["value"] == "2024-07-03"


# ------------------------------------------------------------------------------------------------ 5e/5f post-processing
def _p3b() -> dict:
    return json.loads((ROOT / "results" / "eval5" / "p3b__publicai_swiss-ai_apertus-v1.5-8b.json").read_text())


def test_post_keeps_opds_date_when_the_rule_read_the_submission_date():
    x = next(a for a in _p3b()["per_affair"] if a["affair_id"] == 240980)  # Luzern, rule lu_antrag
    assert x["affair"]["qa"][0]["answer_date"]["value"] == "2021-03-16"  # the frozen (scored) output is unchanged
    p = affair_post.finalize(x["affair"])
    ad = p["affair"]["qa"][0]["answer_date"]
    assert ad["value"] == "2021-10-19" and ad["route"] == "metadata" and ad["source"].startswith("opd:events/")
    assert p["needs_review"] and p["review"][0]["rule_value"]["value"] == "2021-03-16"
    assert "submission date" in p["review"][0]["reason"]
    affair_post.validate(p)


def test_post_no_false_typed_null_and_not_applicable_decision():
    x = next(a for a in _p3b()["per_affair"] if a["affair_id"] == 301273)  # the site's showcase (BL interpellation)
    p = affair_post.finalize(x["affair"])
    qa = p["affair"]["qa"][0]
    assert "answering_body" not in qa and p["omitted"][0]["field"] == "qa.0.answering_body"
    assert "no null reason" in p["omitted"][0]["note"]
    assert p["affair"]["decision"]["null_reason"] == "not_applicable" and p["affair"]["decision"]["route"] == "metadata"
    assert not p["needs_review"]
    affair_post.validate(p)
    # a decision OPD records is kept
    a = dict(x["affair"], decision=dict(kind="value", value="rejected", basis="metadata", route="metadata", source="opd:x"))
    assert affair_post.finalize(a)["affair"]["decision"]["value"] == "rejected"


def test_post_check_on_p3_and_p3b_matches_the_committed_file():
    committed = json.loads((ROOT / "results" / "eval5" / "affair_post_check.json").read_text())
    t = committed["tests"]
    assert t["P3"]["guard_fired"] == 0 and t["P3b"]["guard_fired"] == 3 and t["P3b"]["guard_kept_correct"] == 3
    assert {r["body"] for r in t["P3b"]["answer_date_guard"]} == {"LU"}
    assert t["P3"]["valid"] == t["P3"]["affairs"] == 29 and t["P3b"]["valid"] == t["P3b"]["affairs"] == 36


def test_showcase_uses_the_post_processed_record():
    """Round 12: the showcase is the post-processed product record carried to schema v0.2, where the field nobody
    extracted carries the typed null `not_extracted` and the record validates as a whole (nothing is left out)."""
    from gegenprobe.schema.p8_v0_2 import schema_module
    from gegenprobe.viewer import data

    s = data.schema_view()["sample"]
    ab = s["record"]["qa"][0]["answering_body"]
    assert ab["kind"] == "null" and ab["null_reason"] == "not_extracted" and not s["omitted"]
    assert s["record"]["schema_version"] == s["schema_version"] == "0.2.0"
    assert s["record"]["decision"]["null_reason"] == "not_applicable"
    schema_module().validate_affair(s["record"])
