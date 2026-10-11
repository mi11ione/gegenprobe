"""The unlocked post-processing layer of qa_cli (gegenprobe/qa_post.py) and the per-parliament settings file
(convert/body_settings.py), on synthetic text modelled on the Solothurn layouts U4 met (names and texts invented).
The frozen extractor (src/gegenprobe/qa, LOCK6) is not changed; each test says what the layer adds on top of it."""
import json
from types import SimpleNamespace

import pytest

from gegenprobe import __main__ as cli
from gegenprobe import qa_cli, qa_post
from gegenprobe.convert import affair_types, batch, body_settings
from gegenprobe.qa import extract as X
from gegenprobe.validate.spans import recheck

# ---------------------------------------------------------------------------------------------- synthetic documents
SO_Q = (
    "Kantonsrat\nParlamentsdienste\n\nA 0001/2025 (DBK)\nAuftrag Fraktion Beispiel: Mehr Velowege (02.07.2025)\n"
    "Der Regierungsrat wird beauftragt, dem Kantonsrat ein Konzept für durchgehende Velowege auf allen Kantonsstrassen\n"
    "vorzulegen und die nötigen Mittel im nächsten Budget einzustellen.\n"
    "Begründung 02.07.2025: schriftlich.\n"
    "Die Velowege im Kanton sind lückenhaft und gefährlich. Viele Schulkinder fahren auf stark befahrenen Strassen ohne\n"
    "eigene Spur. Andere Kantone haben ihre Netze in den letzten Jahren deutlich ausgebaut und gute Erfahrungen gemacht.\n"
    "Unterschriften: 1. Anna Muster, 2. Peter Beispiel, 3. Laura Test, Hans Meier,\n"
    "Eva Probe, Markus\nDick, Rita Frei (7)\n"
)
SO_A = (
    "Regierungsratsbeschluss\n\nvom\n\n28. Oktober 2025\n\nNr.\n2025/1758\nA 0001/2025 (DBK)\n\n"
    "Auftrag Fraktion Beispiel: Mehr Velowege\nStellungnahme des Regierungsrates\n\n1.\n\nAuftragstext\n\n"
    "Der Regierungsrat wird beauftragt, dem Kantonsrat ein Konzept für durchgehende Velowege auf allen Kantonsstrassen "
    "vorzulegen und die nötigen Mittel im nächsten Budget einzustellen.\n\n2.\n\nBegründung (Vorstosstext)\n\n"
    "Die Velowege im Kanton sind lückenhaft und gefährlich. Viele Schulkinder fahren auf stark befahrenen Strassen ohne "
    "eigene Spur. Andere Kantone haben ihre Netze in den letzten Jahren deutlich ausgebaut und gute Erfahrungen gemacht.\n\n"
    "3.\n\nStellungnahme des Regierungsrates\n\n"
    "Der Kanton hat bereits ein Velonetz definiert, das schrittweise umgesetzt wird. Ein weiteres Konzept bringt keinen\n"
    "Mehrwert, weil die Planung abgeschlossen ist und die Mittel im Finanzplan bereits eingestellt sind. Die Umsetzung\n"
    "hängt vor allem von den Bauprojekten der Gemeinden ab, die der Kanton nicht beschleunigen kann.\n\n"
    "4.\n\nAntrag des Regierungsrates\n\nNichterheblicherklärung.\n\n"
    "Yves Muster\nStaatsschreiber\n\nVorberatende Kommission\nBau- und Verkehrskommission\n\n"
    "Verteiler\nBau- und Justizdepartement\nParlamentsdienste\n"
)
# an interpellation answered under "Zu Frage n", signature + distribution list after the last answer
I_Q = (
    "Interpellation Fraktion Beispiel: Lärm (11.11.2025)\nDer Lärm nimmt zu. Der Regierungsrat wird deshalb gebeten, "
    "folgende Fragen zu beantworten:\n1. Wie viele Messungen gab es im letzten Jahr?\n"
    "2. Welche Massnahmen plant der Regierungsrat gegen den Lärm?\n"
    "Begründung 11.11.2025: Im Vorstosstext enthalten.\n"
    "Unterschriften: Muster Anna, Beispiel Peter, Test Laura (3)\n"
)
I_A = (
    "Regierungsratsbeschluss vom 17. Februar 2026\n\nInterpellation Fraktion Beispiel: Lärm\n"
    "Stellungnahme des Regierungsrates\n\n1. Vorstosstext\n\nDer Lärm nimmt zu. Der Regierungsrat wird deshalb gebeten, "
    "folgende Fragen zu beantworten:\n1. Wie viele Messungen gab es im letzten Jahr?\n"
    "2. Welche Massnahmen plant der Regierungsrat gegen den Lärm?\n\n2. Begründung\n\nIm Vorstosstext enthalten.\n\n"
    "3. Stellungnahme des Regierungsrates\n\n3.1 Zu Frage 1:\n\n"
    "Im letzten Jahr gab es zwölf Messungen an fünf Standorten, alle an Kantonsstrassen mit vielen Klagen.\n\n"
    "3.2 Zu Frage 2:\n\n"
    "Der Regierungsrat plant weitere Kontrollen und eine Kampagne zur Sensibilisierung der Fahrzeuglenkenden.\n\n"
    "Yves Muster\nStaatsschreiber\n\nVerteiler\nDepartement des Innern\nPolizei\n"
)
# a motion whose demand lists its points as dash bullets
BUL_Q = (
    "Auftrag fraktionsübergreifend: Hunde (07.05.2025)\n"
    "Der Regierungsrat wird beauftragt, die Gesetzgebung über die Hundehaltung zu verschärfen und mindestens die\n"
    "folgenden Massnahmen in Erwägung zu ziehen:\n"
    "- Ergänzung der Liste bewilligungspflichtiger Hunde;\n"
    "- Ausdehnung der Leinenpflicht auf Spielplätze und Schulhäuser;\n"
    "- Prüfung weiterer Massnahmen durch den Regierungsrat.\n"
    "Begründung 07.05.2025: schriftlich.\nDie Vorfälle geben Anlass, die Gesetzgebung zu prüfen und zu verschärfen.\n"
    "Unterschriften: 1. Anna Muster, 2. Peter Beispiel (2)\n"
)
BUL_A = (
    "Regierungsratsbeschluss vom 23. September 2025\n\nStellungnahme des Regierungsrates\n\n"
    "Die Hundegesetzgebung bietet bereits griffige Mittel. Einzig beim Zutrittsrecht zu Liegenschaften sehen wir\n"
    "Handlungsbedarf, die übrigen Punkte sind bereits geregelt oder werden mit der laufenden Revision umgesetzt.\n\n"
    "Antrag des Regierungsrates\n\nErheblicherklärung mit geändertem Wortlaut: Der Regierungsrat wird beauftragt, das "
    "Zutrittsrecht zu regeln.\n\nYves Muster\nStaatsschreiber\n"
)


def run(capsys, *argv):
    rc = qa_cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


@pytest.fixture
def so(tmp_path):
    q, a = tmp_path / "q.txt", tmp_path / "a.txt"
    q.write_text(SO_Q, encoding="utf-8")
    a.write_text(SO_A, encoding="utf-8")
    return str(q), str(a)


def _txt(s: str, sp: dict) -> str:
    return s[sp["g_start"]:sp["g_end"]]


def _recheck_all(r: dict, q: str, a: str) -> None:
    pages = {r["documents"]["question"]["doc_id"]: [q], r["documents"]["answer"]["doc_id"]: [a]}
    rec = r["records"]
    vals = [x for it in rec["qa_items"] for x in (it["question"], it["answer"])]
    vals += [x["name"] for x in rec["actors"]] + [rec["recommendation"], rec["reasoning"]]
    for x in vals:
        if x.get("kind") == "value":
            c = recheck(SimpleNamespace(**{k: x.get(k) for k in ("value", "basis", "route", "page", "char_start",
                                                                  "char_end", "quote")}), pages[x["doc"]])
            assert c.ok, c


# ---------------------------------------------------------------------------------------------- 1 --body / --anchors / --explain
def test_body_outside_coverage_flags_values_and_warns(capsys, so):
    q, a = so
    rc, out, err = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--affair-type", "Auftrag",
                       "--body", "SO", "--json")
    r = json.loads(out)
    assert rc == 0 and r["body"] == "SO" and r["rules_coverage"]["status"] == "not_covered"
    assert r["needs_review"] and {x["field"] for x in r["review_reasons"]} >= {"reasoning", "people", "recommendation"}
    assert "warning: body SO is not in data/convert/rules_coverage.json" in err
    _recheck_all(r, SO_Q, SO_A)


def test_covered_body_is_not_flagged_for_coverage(capsys, so):
    q, a = so
    rc, out, err = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--body", "BE", "--json")
    r = json.loads(out)
    assert rc == 0 and r["rules_coverage"]["status"] == "covered" and not r["needs_review"] and "warning" not in err


def test_explain_and_malformed_anchors(capsys, so, tmp_path):
    q, a = so
    rc, out, err = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--explain")
    assert rc == 0 and "frozen rule (LOCK6)" in err and "recommendation:" in err and "'Antrag' heading" in err
    rc, out, err = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--explain", "--json")
    ppl = json.loads(out)["explain"]["fields"]["people"]
    assert ppl[0]["step"] == "frozen rule (LOCK6)" and ppl[-1] == dict(step="decided by", result="post_signature_list_numbered")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"bodies": {"SO": {"recommendation": [{"pattern": "x", "label": "maybe"}]}}}))
    rc, _, err = run(capsys, "--opd-text-answer", a, "--anchors", str(bad))
    assert rc == 2 and "label must be one of" in err


# ---------------------------------------------------------------------------------------------- 2 recommendation
def test_frozen_null_but_antrag_heading_gives_the_value_with_span(capsys, so):
    q, a = so
    out = X.extract([SO_Q], [SO_A], "de", None)
    assert out["view"]["recommendation"] == "none" and out["view"]["recommendation_span"] is None  # frozen: not_in_document
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--json")
    r = json.loads(txt)
    assert r["view"]["recommendation"] == "reject" and r["rules"]["recommendation"] == "post_antrag_heading"
    assert _txt(SO_A, r["view"]["recommendation_span"]) == "Nichterheblicherklärung"
    assert r["records"]["recommendation"]["value"] == "reject" and r["records"]["recommendation"]["quote"] == \
        "Nichterheblicherklärung"


def test_user_anchor_wins_and_qualifier_is_flagged(capsys, so, tmp_path):
    q, a = so
    f = tmp_path / "so.json"
    f.write_text(json.dumps({"bodies": {"SO": {"recommendation": [
        {"id": "so_nicht", "label": "reject",
         "pattern": "Antrag des Regierungsrates\\s*(?P<phrase>Nichterheblicherkl(ä|a)rung)"}]}}}))
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--body", "SO", "--anchors", str(f), "--json")
    r = json.loads(txt)
    assert r["rules"]["recommendation"] == "user_anchor:so_nicht" and r["records"]["recommendation"]["route"] == "user_anchor"
    assert not any(x["field"] == "recommendation" for x in r["review_reasons"])
    qq, aa = tmp_path / "bq.txt", tmp_path / "ba.txt"
    qq.write_text(BUL_Q, encoding="utf-8")
    aa.write_text(BUL_A, encoding="utf-8")
    rc, txt, _ = run(capsys, "--opd-text-question", str(qq), "--opd-text-answer", str(aa), "--json")
    r = json.loads(txt)
    assert r["view"]["recommendation"] == "accept"
    assert any("geändertem Wortlaut" in x["reason"] for x in r["review_reasons"] if x["field"] == "recommendation")


def test_nichterheblich_read_as_accept_by_the_frozen_lexicon_becomes_reject():
    a = SO_A.replace("4.\n\nAntrag des Regierungsrates\n\nNichterheblicherklärung.",
                     "Der Regierungsrat beantragt Nichterheblicherklärung.")
    out = X.extract([SO_Q], [a], "de", None)
    assert out["view"]["recommendation"] == "accept"  # the frozen lexicon matches "erheblicherkl" inside it
    p = qa_post.apply(out, [SO_Q], [a])
    assert p["view"]["recommendation"] == "reject" and p["rules"]["recommendation"].endswith("+post_nichterheblich")


def test_open_null_is_no_rules_for_body_or_flagged_and_printed_as_null(capsys, tmp_path):
    a = SO_A.replace("4.\n\nAntrag des Regierungsrates\n\nNichterheblicherklärung.\n\n", "")
    qf, af = tmp_path / "q.txt", tmp_path / "a.txt"
    qf.write_text(SO_Q, encoding="utf-8")
    af.write_text(a, encoding="utf-8")
    rc, txt, _ = run(capsys, "--opd-text-question", str(qf), "--opd-text-answer", str(af), "--body", "SO", "--json")
    r = json.loads(txt)
    assert r["records"]["recommendation"]["null_reason"] == "no_rules_for_body"
    assert any(x["field"] == "recommendation" for x in r["left_open"]) and r["needs_review"]
    rc, txt, _ = run(capsys, "--opd-text-question", str(qf), "--opd-text-answer", str(af), "--json")
    r = json.loads(txt)  # no --body: the null stays not_in_document, but a reviewer is asked to confirm it
    assert r["records"]["recommendation"]["null_reason"] == "not_in_document"
    assert any(x["field"] == "recommendation" for x in r["left_open"]) and r["needs_review"]
    rc, txt, _ = run(capsys, "--opd-text-question", str(qf), "--opd-text-answer", str(af))
    line = next(x for x in txt.splitlines() if x.startswith("recommendation:"))
    assert line.startswith("recommendation: null (not_in_document") and "none" not in line.split("rule")[0].split("(")[0]
    rc, txt, _ = run(capsys, "--opd-text-question", str(qf), "--opd-text-answer", str(af), "--body", "BE", "--json")
    r = json.loads(txt)  # a covered body: the rules' not_in_document stands unflagged
    assert r["records"]["recommendation"]["null_reason"] == "not_in_document" and not r["left_open"]


# ---------------------------------------------------------------------------------------------- 3 people
def test_numbered_signature_list_first_is_submitter_labels_and_counts_stripped(capsys, so):
    q, a = so
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--json")
    r = json.loads(txt)
    v = r["view"]
    assert v["submitter"]["name"] == "Anna Muster" and v["submitter"]["rule"] == "post_signature_list_numbered"
    co = [c["name"] for c in v["co_signatories"]]
    assert co == ["Peter Beispiel", "Laura Test", "Hans Meier", "Eva Probe", "Markus Dick", "Rita Frei"]
    assert all("(" not in c and ":" not in c for c in co)
    md = next(c for c in v["co_signatories"] if c["name"] == "Markus Dick")
    assert _txt(SO_Q, md["span"]) == "Markus\nDick"
    _recheck_all(r, SO_Q, SO_A)


def test_surname_first_list_without_numbers(capsys, tmp_path):
    q, a = tmp_path / "q.txt", tmp_path / "a.txt"
    q.write_text(I_Q, encoding="utf-8")
    a.write_text(I_A, encoding="utf-8")
    rc, txt, _ = run(capsys, "--opd-text-question", str(q), "--opd-text-answer", str(a), "--json")
    v = json.loads(txt)["view"]
    assert v["submitter"]["name"] == "Muster Anna" and [c["name"] for c in v["co_signatories"]] == ["Beispiel Peter",
                                                                                                   "Test Laura"]


# ---------------------------------------------------------------------------------------------- 4 closing, 5 reprint, 7 headings
def test_reasoning_skips_reprint_and_ends_before_antrag_and_signature(capsys, so):
    q, a = so
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--json")
    r = json.loads(txt)
    reas = _txt(SO_A, r["view"]["reasoning"])
    assert reas.startswith("Der Kanton hat bereits ein Velonetz") and reas.endswith("nicht beschleunigen kann.")
    a1 = _txt(SO_A, r["view"]["answers"][0]["span"])
    assert a1 == reas and "Staatsschreiber" not in a1 and "Verteiler" not in a1
    _recheck_all(r, SO_Q, SO_A)


def test_section_number_headings_on_one_line_and_closing_block(capsys, tmp_path):
    q, a = tmp_path / "q.txt", tmp_path / "a.txt"
    q.write_text(I_Q, encoding="utf-8")
    a.write_text(I_A, encoding="utf-8")
    prepared, n = qa_post.prepare([I_A])
    assert n == 2 and len(prepared[0]) == len(I_A) and "3.1\nZu Frage 1:" in prepared[0]
    rc, txt, _ = run(capsys, "--opd-text-question", str(q), "--opd-text-answer", str(a), "--json")
    r = json.loads(txt)
    v = r["view"]
    assert v["answer_style"] == "per_question" and [x["joint_with"] for x in v["answers"]] == [[], []]
    assert _txt(I_A, v["answers"][0]["span"]).startswith("Im letzten Jahr gab es zwölf Messungen")
    a2 = _txt(I_A, v["answers"][1]["span"])
    assert a2.endswith("der Fahrzeuglenkenden.") and "Staatsschreiber" not in a2
    assert "Vorstosstext" not in _txt(I_A, v["reasoning"]) and "Verteiler" not in _txt(I_A, v["reasoning"])
    _recheck_all(r, I_Q, I_A)


@pytest.mark.parametrize("closing", ["Le Conseil d'Etat\n\nLa chancelière\n", "Per il Consiglio di Stato\nIl Presidente\n",
                                     "Im Namen des Regierungsrates\nDie Präsidentin\n", "Mitteilung an\n- Departement\n",
                                     "Copie à\n- Département\n"])
def test_closing_blocks_are_generic(closing):
    a = I_A.replace("Yves Muster\nStaatsschreiber\n\nVerteiler\nDepartement des Innern\nPolizei\n", closing)
    p = qa_post.apply(X.extract([I_Q], qa_post.prepare([a])[0], "de", None), [I_Q], [a])
    a2 = _txt(a, p["view"]["answers"][1]["span"])
    assert a2.endswith("der Fahrzeuglenkenden.") and _txt(a, p["view"]["reasoning"]).endswith("der Fahrzeuglenkenden.")


# ---------------------------------------------------------------------------------------------- 6 motion demand
def test_dash_bullets_in_a_motion_demand_are_one_item(capsys, tmp_path):
    q, a = tmp_path / "q.txt", tmp_path / "a.txt"
    q.write_text(BUL_Q, encoding="utf-8")
    a.write_text(BUL_A, encoding="utf-8")
    assert len(X.extract([BUL_Q], [BUL_A], "de", None, affair_type="Motion")["view"]["questions"]) == 3  # frozen
    rc, txt, _ = run(capsys, "--opd-text-question", str(q), "--opd-text-answer", str(a), "--affair-type", "Auftrag", "--json")
    r = json.loads(txt)
    v = r["view"]
    assert v["question_style"] == "single" and len(v["questions"]) == 1 and len(r["records"]["qa_items"]) == 1
    q1 = _txt(BUL_Q, v["questions"][0]["span"])
    assert q1.startswith("Der Regierungsrat wird beauftragt") and q1.endswith("durch den Regierungsrat.")
    assert v["answers"][0]["span"] == v["reasoning"] and r["left_open"] == []
    _recheck_all(r, BUL_Q, BUL_A)


def test_numbered_demands_stay_separate():
    q = BUL_Q.replace("- Ergänzung", "1. Ergänzung").replace("- Ausdehnung", "2. Ausdehnung").replace("- Prüfung", "3. Prüfung")
    out = X.extract([q], [BUL_A], "de", None, affair_type="Motion")
    p = qa_post.apply(out, [q], [BUL_A], affair_type="Motion")
    assert len(p["view"]["questions"]) == len(out["view"]["questions"])


# ---------------------------------------------------------------------------------------------- 8 affair types
@pytest.mark.parametrize("raw,want", [("Auftrag", "Motion"), ("auftrag", "Motion"), ("Dringliches Postulat", "Postulate"),
                                      ("Interpellation écrite", "Interpellation"), ("Dringliche Anfrage", "Question")])
def test_opd_type_names_derived_from_the_census(raw, want):
    assert affair_types.normalize(raw) == want


def test_committed_alias_file_is_a_recompute():
    d = affair_types.derive(write=False)
    committed = json.loads(affair_types.ALIAS_FILE.read_text(encoding="utf-8"))
    assert d["aliases"] == committed["aliases"] and any(a["type_raw"] == "auftrag" and a["key"] == "motion"
                                                        for a in d["aliases"])


def test_convert_cli_accepts_auftrag_and_settings_aliases(tmp_path, capsys, monkeypatch):
    seen = {}
    monkeypatch.setattr(batch, "convert_one", lambda src, inp, **kw: seen.update(inp) or {
        "status": "ok", "input": inp, "needs_review": False, "rules_coverage": {"status": "covered"}})
    assert cli.main(["convert", "x.pdf", "--affair-type", "Auftrag"]) == 0 and seen["affair_type"] == "Motion"
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"bodies": {"XX": {"affair_types": {"Vorstoss Typ A": "interpellation"}}}}))
    assert cli.main(["convert", "x.pdf", "--body", "XX", "--anchors", str(f), "--affair-type", "Vorstoss Typ A"]) == 0
    assert seen["affair_type"] == "Interpellation"
    with pytest.raises(SystemExit) as e:  # the alias is per body: elsewhere it stays unknown
        cli.main(["convert", "x.pdf", "--body", "YY", "--anchors", str(f), "--affair-type", "Vorstoss Typ A"])
    assert e.value.code == 2


# ---------------------------------------------------------------------------------------------- 9 settings file / confirm_rules
def _settings(tmp_path, spec) -> dict:
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"bodies": {"SO": spec}}))
    return body_settings.load(str(f))


def test_settings_file_validation(tmp_path):
    with pytest.raises(SystemExit, match="confirm_rules must be a list"):
        _settings(tmp_path, {"confirm_rules": "rrb_vom"})
    with pytest.raises(SystemExit, match="not a vocabulary key"):
        _settings(tmp_path, {"affair_types": {"Auftrag": "no-such"}})
    with pytest.raises(SystemExit, match="invalid regular expression"):
        _settings(tmp_path, {"closing": ["("]})
    s = _settings(tmp_path, {"confirm_rules": ["rrb_vom"], "recommendation": [{"pattern": "x", "label": "reject"}]})
    assert s["bodies"]["SO"]["recommendation"][0]["label"] == "reject" and body_settings.confirmed(s, "so") == {"rrb_vom"}
    assert body_settings.is_confirmed(s, "SO", "rrb_vom") and not body_settings.is_confirmed(s, "SO", "be_rrb_inline")
    assert not body_settings.is_confirmed(s, "SO", "rrb_vom+post_closing")  # every part must be confirmed


def test_convert_confirmed_rule_is_not_flagged_unconfirmed_is(tmp_path):
    kw = dict(sha="0" * 64, extractor="pdftotext", image_only=False, inp=dict(body="SO", affair_type="Motion"))
    plain = batch.convert_pages([SO_A], **kw)
    assert plain["fields"]["answer_date"]["value"] == "2025-10-28" and plain["fields"]["answer_date"]["rule_id"] == "rrb_vom"
    assert any(x["field"] == "answer_date" for x in plain["review_reasons"])
    ok = batch.convert_pages([SO_A], anchors=_settings(tmp_path, {"confirm_rules": ["rrb_vom"]}), **kw)
    assert not any(x["field"] == "answer_date" for x in ok["review_reasons"])
    assert "confirm_rules" in ok["fields"]["answer_date"]["confirmed_by"]
    other = batch.convert_pages([SO_A], anchors=_settings(tmp_path, {"confirm_rules": ["be_rrb_inline"]}), **kw)
    assert any(x["field"] == "answer_date" for x in other["review_reasons"])


def test_qa_confirmed_rules_clear_the_coverage_flags(capsys, so, tmp_path):
    q, a = so
    f = tmp_path / "so.json"
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--body", "SO", "--json")
    r = json.loads(txt)
    rules = sorted({p for x in r["rules"].values() if x for p in str(x).split("+")})
    f.write_text(json.dumps({"bodies": {"SO": {"confirm_rules": rules}}}))
    rc, txt, err = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--body", "SO", "--anchors", str(f),
                       "--json", "--explain")
    r = json.loads(txt)
    assert rc == 0 and not r["needs_review"] and r["review_reasons"] == [] and "confirm_rules" in err


# ---- Thurgau-like layouts
# U4 on the Grosser Rat Thurgau: scanned question documents with a "Begründung", a handwritten signature line
# and a numbered co-signature table; born-digital answers whose title line names every signer. Names and texts invented.
TG_Q = (
    "Anna Muster\nFDP\nBeispielstrasse 1\n8500 Frauenfeld\n\nInterpellation\nLärm an Kantonsstrassen\n\n"
    "Der Regierungsrat wird ersucht, die nachfolgenden Fragen zu beantworten:\n"
    "1. Wie viele Lärmmessungen gab es im Jahr 2025?\n"
    "2. Welche Strassenabschnitte überschreiten die Grenzwerte?\n"
    "3. Was unternimmt der Regierungsrat, um den Lärm zu lindem?\n\n\n"
    "Begründung\nDer Verkehr nimmt zu, und mit ihm der Lärm an vielen Kantonsstrassen.\n"
    "Frauenfeld, 3. Dezember 2025\n\n7 f-/^.^ v ^\\<>^me—\n\nAnna Muster ' Peter Beispie^l\n\n"
    "Mitunterzeichnerinnen und Mitunterzeichner der Interpellation von Anna Muster\n\nName / Vorname\n\nUnterschrift\n\n"
    "4.\n\nBreniicT M^rho\n\n5\n\n^^1\n"
)
TG_A = (
    "Der Regierungsrat des Kantons Thurgau\nan den Grossen Rat\n\nFrauenfeld, 3. August 2026\nNr. 123\n\n"
    "Interpellation von Anna Muster, Peter Beispiel und Laura Test vom 3. Dezember 2025 „Lärm an Kantonsstrassen\"\n"
    "Beantwortung\n\nSehr geehrter Herr Präsident\nSehr geehrte Damen und Herren\n\n"
    "Frage 1: Wie viele Lärmmessungen gab es im Jahr 2025?\n"
    "Im Jahr 2025 wurden an zwölf Standorten Messungen durchgeführt, alle an stark befahrenen Kantonsstrassen."
    " Die Messungen erfolgen nach den Vorgaben des Bundes und werden jährlich ausgewertet.\n"
    "Die Ergebnisse fliessen in die Planung der Sanierungsprojekte ein und werden den Gemeinden mitgeteilt.\n"
    "Weitere Abklärungen sind im Gang und werden im nächsten Bericht des Departements dargestellt.\n\n"
    "Frage 2: Welche Strassenabschnitte überschreiten die Grenzwerte?\n"
    "Vier Abschnitte überschreiten die Immissionsgrenzwerte, zwei davon in Ortsdurchfahrten mit Wohnnutzung."
    " Die Messungen erfolgen nach den Vorgaben des Bundes und werden jährlich ausgewertet.\n"
    "Die Ergebnisse fliessen in die Planung der Sanierungsprojekte ein und werden den Gemeinden mitgeteilt.\n"
    "Weitere Abklärungen sind im Gang und werden im nächsten Bericht des Departements dargestellt.\n\n"
    "Frage 3: Was unternimmt der Regierungsrat, um den Lärm zu lindern?\n"
    "Der Regierungsrat lässt lärmarme Beläge einbauen und prüft Temporeduktionen in den betroffenen Ortsdurchfahrten."
    " Die Messungen erfolgen nach den Vorgaben des Bundes und werden jährlich ausgewertet.\n"
    "Die Ergebnisse fliessen in die Planung der Sanierungsprojekte ein und werden den Gemeinden mitgeteilt.\n"
    "Weitere Abklärungen sind im Gang und werden im nächsten Bericht des Departements dargestellt.\n\n"
    "Die Präsidentin des Regierungsrates\n\nDer Staatsschreiber\n"
)
TG_EA_Q = (
    "Einfache Anfrage\nHitze auf Baustellen\nDer Regierungsrat wird ersucht, die nachfolgenden Fragen zu beantworten:\n"
    "1. Gibt es im Kanton verbindliche Regeln für Arbeiten bei grosser Hitze?\n"
    "2. Wie oft wurde deren Einhaltung in den letzten fünf Jahren kontrolliert?\n\n"
    "Begründung\nDie Zahl der Hitzetage steigt seit Jahren, auch auf den Baustellen im Kanton.\n\n"
    "Arbon, den 01. Juli 2026\ni //,.y\n\nJaco\n\nDidi 1-euerle\n\nLaura Test\n"
)
TG_EA_A = (
    "Der Regierungsrat des Kantons Thurgau\nan den Grossen Rat\n\nFrauenfeld, 25. August 2026\nNr. 491\n\n"
    "Einfache Anfrage von Jacob Muster, Didi Beispiel und Laura Test vom\n1. Juli 2026 „Hitze auf Baustellen\"\n"
    "Beantwortung\n\nSehr geehrter Herr Präsident\nSehr geehrte Damen und Herren\n\n"
    "Frage 1: Gibt es im Kanton verbindliche Regeln für Arbeiten bei grosser Hitze?\n"
    "Die Arbeitgeber sind bereits heute verpflichtet, Gefährdungen am Arbeitsplatz zu ermitteln und zu beheben.\n\n"
    "Frage 2: Wie oft wurde deren Einhaltung in den letzten fünf Jahren kontrolliert?\n"
    "Dazu liegen dem Regierungsrat keine statistischen Angaben vor, die Kontrollen erfolgen durch die Suva.\n"
)
TG_MO_A = (
    "Der Regierungsrat des Kantons Thurgau\nan den Grossen Rat\n\nFrauenfeld, 26. Mai 2026\nNr. 289\n\n"
    "Motion von Anna Muster, Peter Beispiel und Laura Test vom 2. April 2025 „Einheitliche Gebühren\"\n"
    "Beantwortung\n\nSehr geehrter Herr Präsident\nSehr geehrte Damen und Herren\n\n1. Ausgangslage\n"
    "Die Gebühren sind heute in den Gemeinden geregelt, und eine kantonale Regelung würde die Autonomie einschränken.\n\n"
    "5. Antrag\nAus den dargelegten Gründen beantragen wir Ihnen, sehr geehrter Herr Präsident, sehr geehrte Damen und "
    "Herren, die Motion nicht erheblich zu erklären.\n\nDie Präsidentin des Regierungsrates\n\nDer Staatsschreiber\n"
)


def _tg(tmp_path, q, a):
    qf, af = tmp_path / "q.txt", tmp_path / "a.txt"
    qf.write_text(q, encoding="utf-8")
    af.write_text(a, encoding="utf-8")
    return str(qf), str(af)


def test_question_list_ends_at_begruendung_and_signature_rows_are_not_questions(capsys, tmp_path):
    q, a = _tg(tmp_path, TG_Q, TG_A)
    out = X.extract([TG_Q], [TG_A], "de", None, affair_type="Interpellation")
    assert len(out["view"]["questions"]) == 4  # the frozen chain runs into the signature table ("4. BreniicT M^rho")
    rc, txt, err = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--affair-type", "Interpellation",
                       "--json", "--explain")
    r = json.loads(txt)
    qs = r["view"]["questions"]
    assert rc == 0 and [x["n"] for x in qs] == [1, 2, 3] and [x["n"] for x in r["view"]["answers"]] == [1, 2, 3]
    assert _txt(TG_Q, qs[-1]["span"]).endswith("zu lindem?") and "Begründung" not in _txt(TG_Q, qs[-1]["span"])
    assert not r["left_open"] and r["view"]["answer_style"] == "per_question"
    assert r["rules"]["questions"].endswith("+post_questions_end")
    steps = {s["step"]: s["result"] for s in r["explain"]["fields"]["questions"]}
    assert "reasoning heading 'Begründung'" in steps["questions end"] and "item(s) 4 after it dropped" in steps["questions end"]
    # the answer repeats question 3 with "lindern" where the OCR of the question reads "lindem": still cut
    a3 = _txt(TG_A, r["view"]["answers"][2]["span"])
    assert a3.startswith("Der Regierungsrat lässt") and "lindern?" not in a3
    _recheck_all(r, TG_Q, TG_A)


def test_garbled_trailing_row_is_dropped_without_a_heading():
    q = ("Der Regierungsrat wird ersucht, folgende Fragen zu beantworten:\n1. Wie hoch sind die Kosten?\n"
         "2. Wer trägt sie?\n3. BreniicT M^rho\n")
    out = X.extract([q], None, "de", None)
    assert len(out["view"]["questions"]) == 3
    p = qa_post.apply(out, [q], None)
    assert [x["n"] for x in p["view"]["questions"]] == [1, 2]
    assert "OCR-garbled table row" in next(x["result"] for x in p["post"] if x["step"] == "questions end")


def test_questions_end_from_the_settings_file_and_a_reason_under_each_question(tmp_path):
    q = ("Der Regierungsrat wird ersucht, folgende Fragen zu beantworten:\n1. Wie hoch sind die Kosten?\n"
         "2. Wer trägt die Kosten heute\nErläuterungen der Fraktion\n3. Mehr Infos im Anhang\n")
    out = X.extract([q], None, "de", None)
    s = _settings(tmp_path, {"questions_end": ["^\\s*Erläuterungen"]})
    p = qa_post.apply(out, [q], None, body="SO", settings=s)
    assert [x["n"] for x in p["view"]["questions"]] == [1, 2]
    assert "questions_end (settings file)" in next(x["result"] for x in p["post"] if x["step"] == "questions end")
    # a "Begründung" under each question is not the end of the list
    q2 = ("Der Regierungsrat wird ersucht, folgende Fragen zu beantworten:\n1. Wie hoch sind die Kosten?\n"
          "Begründung: Die Kosten steigen.\n2. Wer trägt die Kosten?\nBegründung: Das ist unklar.\n")
    out2 = X.extract([q2], None, "de", None)
    p2 = qa_post.apply(out2, [q2], None)
    assert len(p2["view"]["questions"]) == len(out2["view"]["questions"]) == 2


def test_garbled_signature_block_yields_to_the_answer_title(capsys, tmp_path):
    q, a = _tg(tmp_path, TG_EA_Q, TG_EA_A)
    out = X.extract([TG_EA_Q], [TG_EA_A], "de", None, affair_type="Question")
    assert out["rules"]["people"] == "signature_block" and out["view"]["submitter"]["name"] == "Laura Test"
    rc, txt, err = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--affair-type", "Einfache Anfrage",
                       "--json", "--explain")
    r = json.loads(txt)
    v = r["view"]
    assert v["submitter"]["name"] == "Jacob Muster" and v["submitter"]["span"]["doc"] == "answer"
    assert [c["name"] for c in v["co_signatories"]] == ["Didi Beispiel", "Laura Test"] and r["rules"]["people"] == "answer_title"
    assert "OCR-garbled" in next(s["result"] for s in r["explain"]["fields"]["people"] if s["step"] == "answer title")
    _recheck_all(r, TG_EA_Q, TG_EA_A)


def test_clean_signature_block_is_kept_unless_prefer_answer_title(capsys, tmp_path):
    clean_q = TG_EA_Q.replace("i //,.y\n\nJaco\n\nDidi 1-euerle\n\n", "")
    q, a = _tg(tmp_path, clean_q, TG_EA_A)
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--json")
    v = json.loads(txt)["view"]
    assert v["submitter"]["name"] == "Laura Test" and json.loads(txt)["rules"]["people"] == "signature_block"
    f = tmp_path / "tg.json"
    f.write_text(json.dumps({"bodies": {"TG": {"prefer_answer_title": True}}}))
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--body", "TG", "--anchors", str(f), "--json")
    r = json.loads(txt)
    assert r["view"]["submitter"]["name"] == "Jacob Muster" and len(r["view"]["co_signatories"]) == 2
    assert r["rules"]["people"] == "answer_title"
    _recheck_all(r, clean_q, TG_EA_A)
    # a question title line ("Motion von ...") also yields to the answer title with the key set
    mq = "Motion von Anna Muster betreffend Gebühren\nDer Regierungsrat wird beauftragt, die Gebühren zu vereinheitlichen.\n"
    q2, a2 = _tg(tmp_path, mq, TG_MO_A)
    rc, txt, _ = run(capsys, "--opd-text-question", q2, "--opd-text-answer", a2, "--json")
    assert json.loads(txt)["rules"]["people"] == "title_line"
    rc, txt, _ = run(capsys, "--opd-text-question", q2, "--opd-text-answer", a2, "--body", "TG", "--anchors", str(f), "--json")
    r = json.loads(txt)
    assert [r["view"]["submitter"]["name"]] + [c["name"] for c in r["view"]["co_signatories"]] == [
        "Anna Muster", "Peter Beispiel", "Laura Test"]


def test_prefer_answer_title_must_be_a_boolean(tmp_path):
    with pytest.raises(SystemExit, match="prefer_answer_title must be true or false"):
        _settings(tmp_path, {"prefer_answer_title": "yes"})
    s = _settings(tmp_path, {"prefer_answer_title": True, "questions_end": ["^Ende"]})
    assert body_settings.flag(s, "prefer_answer_title", "so") and not body_settings.flag(s, "prefer_answer_title", "BE")
    assert body_settings.patterns(s, "questions_end", "SO")[0].pattern == "^Ende"


def test_convert_and_qa_cli_agree_on_the_recommendation_outside_coverage(capsys, tmp_path):
    kw = dict(sha="0" * 64, extractor="pdftotext", image_only=False, inp=dict(body="TG", affair_type="Motion"))
    row = batch.convert_pages([TG_MO_A], explain=True, **kw)
    f = row["fields"]["recommendation"]
    assert f["value"] == "reject" and f["rule_id"] == "lexicon_reject" and f["needs_review"]
    assert "lexicon rule lexicon_reject (the rule qa_cli uses)" in f["review_reason"]
    assert any(s["step"] == "Q/A lexicon (qa_cli's rule)" for s in row["explain"]["recommendation"])
    assert row["record"]["recommendation"]["kind"] == "value"
    q, a = _tg(tmp_path, "Motion von Anna Muster betreffend Gebühren\nDer Regierungsrat wird beauftragt, x zu tun.\n",
               TG_MO_A)
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--affair-type", "Motion", "--body", "TG",
                     "--json")
    r = json.loads(txt)
    rr = r["records"]["recommendation"]
    assert r["view"]["recommendation"] == "reject" and r["rules"]["recommendation"] == "lexicon_reject"
    assert (rr["page"], rr["char_start"], rr["char_end"]) == (f["page"], f["char_start"], f["char_end"])  # same sentence
    # confirm_rules clears the flag in both tools
    sf = tmp_path / "tg_confirm.json"
    sf.write_text(json.dumps({"bodies": {"TG": {"confirm_rules": ["lexicon_reject"]}}}))
    ok = batch.convert_pages([TG_MO_A], anchors=body_settings.load(str(sf)), **kw)
    assert ok["fields"]["recommendation"]["value"] == "reject" and not ok["fields"]["recommendation"].get("needs_review")
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--affair-type", "Motion", "--body", "TG",
                     "--anchors", str(sf), "--json")
    assert not any(x["field"] == "recommendation" for x in json.loads(txt)["review_reasons"])
    # a covered body keeps convert's measured behaviour (no Q/A lexicon)
    be = batch.convert_pages([TG_MO_A], **dict(kw, inp=dict(body="BE", affair_type="Motion")))
    assert be["fields"]["recommendation"]["value"] is None


def test_anchor_beats_the_frozen_lexicon_outside_coverage_as_in_convert(capsys, tmp_path):
    q, a = _tg(tmp_path, "Motion von Anna Muster betreffend Gebühren\nDer Regierungsrat wird beauftragt, x zu tun.\n",
               TG_MO_A)
    f = tmp_path / "tg.json"
    pat = "beantragen wir Ihnen[^.]{0,160}?(?P<phrase>nicht erheblich zu erkl(ä|a)ren)"
    f.write_text(json.dumps({"bodies": {"TG": {"recommendation": [{"id": "tg_ne", "label": "reject", "pattern": pat}]}}}))
    rc, txt, _ = run(capsys, "--opd-text-question", q, "--opd-text-answer", a, "--affair-type", "Motion", "--body", "TG",
                     "--anchors", str(f), "--json")
    r = json.loads(txt)
    conv = batch.convert_pages([TG_MO_A], sha="0" * 64, extractor="pdftotext", image_only=False,
                               inp=dict(body="TG", affair_type="Motion"), anchors=body_settings.load(str(f)))
    c = conv["fields"]["recommendation"]
    rr = r["records"]["recommendation"]
    assert r["rules"]["recommendation"] == c["rule_id"] == "user_anchor:tg_ne" and r["view"]["recommendation"] == c["value"]
    assert (rr["page"], rr["char_start"], rr["char_end"]) == (c["page"], c["char_start"], c["char_end"])
    assert not any(x["field"] == "recommendation" for x in r["review_reasons"])
