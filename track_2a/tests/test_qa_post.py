"""Round 7: the unlocked post-processing layer of qa_cli (gegenprobe/qa_post.py) and the per-parliament settings file
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
