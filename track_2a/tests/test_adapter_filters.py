"""Document-type filters of the source adapters (repair/adapters/filters.py). One fixture per class found in the blind
audit of the first run (docs/adapters.md, "Audit"), plus the near misses each filter must let through. Synthetic,
hand-written excerpts only: they copy the shape of the real documents (header, subject line, closing), never their text."""

import json

import pytest

from gegenprobe.repair.adapters import base, filters, inopd, opd_docs, registry, ris4tw, run, zh

FILLER = " Lorem ipsum dolor sit amet, consectetur adipiscing elit." * 6


def screen(text, title="", number="2014.SR.000106", body="351", shape=None, heading=None, patterns=None):
    x = dict(id=1, body=body, number=number)
    return filters.screen(base.flatten(text), title, x, heading, shape, patterns)


# ---------------------------------------------------------------- extension requests
@pytest.mark.parametrize("text,title", [
    # Bern city: the Gemeinderat's Vortrag asks the council for more time (subject line ends "; Fristverlängerung")
    ("2014.SR.000106\nVortrag des Gemeinderats an den Stadtrat\nPostulat Fraktion AB (X. Muster): Ein Platz für alle; "
     "Fristverlängerung\nIn der Sitzung vom 1. März 2014 wurde das folgende Postulat erheblich erklärt:" + FILLER, ""),
    # Zürich canton: the government's motion for the council's decision to extend the reporting deadline
    ("Antrag des Regierungsrates vom 1. Juli 2025\nKR-Nr. 12a/2021\nBeschluss des Kantonsrates über die "
     "Fristerstreckung für die Berichterstattung und Antragstellung zur Motion KR-Nr. 12/2021" + FILLER, ""),
    # Zürich canton, 1990s: the RR minutes extract, subject "(Fristerstreckung)"
    ("Auszug aus dem Protokoll des Regierungsrates\nSitzung vom 2. April 1997\n77. Motion betreffend Musterweg "
     "(Fristerstreckung)\nSehr geehrte Frau Präsidentin" + FILLER, ""),
    ("Le Conseil communal au Conseil général\nPostulat 12-34 : prolongation du délai de réponse" + FILLER, ""),
    ("Il Municipio al Consiglio comunale\nMozione 1234: richiesta di proroga del termine" + FILLER, ""),
    ("Vortrag des Gemeinderats an den Stadtrat" + FILLER, "Postulat Muster; Fristverlängerung"),
])
def test_extension_request_is_failed(text, title):
    hit = screen(text, title)
    assert hit and hit.reason == "extension_request" and hit.outcome == "failed"


@pytest.mark.parametrize("text", [
    # the answer itself tells the history of an extension (narrative, far below the subject line)
    "Vortrag des Gemeinderats an den Stadtrat\nMotion Muster: Ein Platz für alle; Abschreibung\n" + FILLER * 3
    + " Im Oktober 2003 beantragte der Gemeinderat eine Fristverlängerung.",
    # the subject announces the closing report together with the extension
    "Vortrag des Gemeinderats an den Stadtrat\nPostulat Muster: Ein Platz; Prüfungsbericht und Fristverlängerung"
    + FILLER,
    # history after the subject: "die Frist zur Vorlage eines Prüfungsberichts" is not the subject
    "Antwort des Stadtrates\nDie Anfrage wird wie folgt beantwortet: Eine Fristerstreckung ist nicht nötig." + FILLER,
])
def test_extension_mentioned_with_or_inside_the_answer_passes(text):
    assert screen(text) is None


def test_extension_in_subject_with_report_mentioned_later_is_still_an_extension():
    text = ("Vortrag des Gemeinderats an den Stadtrat\nPostulat Muster: Viererfeld; Fristverlängerung Punkte 2 - 4\n"
            "Mit SRB 1 vom 6. März 2008 hat der Stadtrat die Frist zur Vorlage eines Prüfungsberichts verlängert.")
    assert screen(text + FILLER).reason == "extension_request"


# ---------------------------------------------------------------- reports of parliamentary bodies
@pytest.mark.parametrize("text,title", [
    ("- 1 -\nRAPPORTO DELLA COMMISSIONE DELLA PIANIFICAZIONE SULLA MOZIONE NO. 1234 DEGLI ON.LI X E Y" + FILLER,
     "RapportoMozione_ 1234_Pianificazione.pdf"),
    ("RAPPORTO DI MAGGIORANZA DELLA COMMISSIONE DELLE PETIZIONI RELATIVO ALLA MOZIONE NO. 99" + FILLER, ""),
    ("Grosser Rat des Kantons Muster\nRatsbüro\nAn den Grossen Rat\nBasel, 9. Januar 2023\n"
     "Bericht des Ratsbüros betreffend Teilrevision der Geschäftsordnung sowie Bericht zum Anzug X" + FILLER, ""),
    ("Bericht der Geschäftsprüfungskommission zum Postulat 12/2020" + FILLER, ""),
    ("Rapport de la commission chargée d'examiner le postulat Muster" + FILLER, ""),
])
def test_parliament_report_is_failed(text, title):
    hit = screen(text, title, number="1234", body="5192")
    assert hit and hit.reason == "parliament_report" and hit.outcome == "failed"


@pytest.mark.parametrize("text", [
    # the executive's answer cites a commission report in its own text
    "Risposta del Consiglio di Stato\n" + FILLER + " 1.1 Quale seguito ha avuto il rapporto della Commissione "
    "sanità sull'iniziativa?",
    # the executive's observation on a motion, with a commission named in the header
    "OSSERVAZIONI DEL MUNICIPIO sul rapporto della commissione della pianificazione, mozione 1234" + FILLER,
])
def test_executive_documents_citing_a_commission_pass(text):
    assert screen(text, number="1234", body="5192") is None


# ---------------------------------------------------------------- minutes that only refer to the answer
def test_minutes_that_only_refer_to_the_written_answer_are_failed():
    text = ("Grosser Gemeinderat\nProtokoll der 24. Sitzung vom Donnerstag, 1. Februar 2001\nInterpellation X betreffend "
            "Fluglärm — Beantwortung (Geschäft Nr. 106/00)\nDie Antwort des Stadtrates liegt schriftlich vor. Eine "
            "Diskussion wird nicht verlangt. Im Schlusswort zeigt sich der Interpellant teilweise befriedigt." + FILLER)
    hit = screen(text, "20010201_PROTA_Beantwortung_Interpellation", number="2000/106", body="296")
    assert hit.reason == "minutes_reference" and hit.outcome == "failed"
    text = ("AUSZUG AUS DEM PROTOKOLL SITZUNG VOM 8. MAI 2025\nInterpellation Y - Beantwortung / Schlussbehandlung\n"
            "Der Stadtrat übermittelt mit Beschluss vom 3. April 2025 die schriftliche Antwort auf die zu Grunde liegende "
            "Interpellation; auf die separaten Akten verwiesen wird." + FILLER)
    assert screen(text, number="2025/086", body="296").reason == "minutes_reference"


def test_minutes_that_print_the_answer_pass():
    text = ("Protokoll der 7. Sitzung vom 11. Mai 2000\nInterpellation Z — Begründung und Beantwortung\n"
            "Stadträtin M. erteilt mündlich die Antwort des Stadtrates: 1. Die Kosten betragen ..." + FILLER)
    assert screen(text, "20000511_PROTA_Begründung und Beantwortung", number="2000/1", body="296") is None


# ---------------------------------------------------------------- the member's text only
@pytest.mark.parametrize("text", [
    "Zürich, 31. Mai 1999\nKR-Nr. 163/1999\nANFRAGE von X. Muster (SP, Zürich) betreffend Musterwesen\n" + FILLER
    + " Ich frage den Regierungsrat an: 1. Wie? 2. Wann? X. Muster",
    "Zürich, 19. Oktober 1998\nKR-Nr. 393/1998\nA N F R A G E von Y (SP, Zürich) betreffend Z" + FILLER,
    "X. Muster\nConsigliere comunale\nLocarno, 20 ottobre 2020\nINTERROGAZIONE\nI sottoscritti presentano la seguente "
    "interrogazione: \"Ascensore guasto\"" + FILLER + " Nell'attesa di una risposta, cordiali saluti.",
    "Conseil communal de Lausanne\nInitiative : interpellation urgente\nTitre : Muster\n" + FILLER
    + " Lausanne, le 21 novembre 2023",
    "Einwohnerrat Musterstadt\nDringliche Anfrage an den Stadtrat\nAusgangslage" + FILLER
    + " Wir bitten daher um eine rasche Beantwortung der Anfrage.",
    "Interpellation Muster\n" + FILLER + " Nous remercions le Gouvernement de ses réponses. Delémont, le 29 janvier 2014",
])
def test_member_text_only_is_failed(text):
    hit = screen(text, number="163/1999", body="ZH", heading=inopd.HEADING)
    assert hit and hit.reason == "member_text_only" and hit.outcome == "failed"


@pytest.mark.parametrize("text", [
    # the government's answer quotes the question in full, then answers it
    "Auszug aus dem Protokoll des Regierungsrates\nKR-Nr. 163/1999\nSitzung vom 7. Juli 1999\nX. Muster hat am 31. Mai "
    "1999 folgende Anfrage eingereicht: ... Ich frage den Regierungsrat an: 1. Wie?\nAuf Antrag der Direktion "
    "beschliesst der Regierungsrat: I. Die Anfrage X. Muster wird wie folgt beantwortet:" + FILLER,
    # an answer whose subject line spells "Interpellation von" in lower case
    "Auszug aus dem Protokoll des Stadtrates Sitzung vom 1. Oktober 2009\nInterpellation von H. Muster betreffend Tarife "
    "Beantwortung\nGemäss Art. 51 der Geschäftsordnung kann eine Anfrage an den Stadtrat gerichtet werden." + FILLER,
    "Città di Locarno\nMunicipio\nEgregio signore, con riferimento all'interrogazione citata, si risponde come segue:"
    + FILLER + " Nell'attesa di una risposta del Cantone, porgiamo cordiali saluti.",
])
def test_answers_quoting_the_question_pass(text):
    assert screen(text, number="163/1999", body="ZH", heading=inopd.HEADING) is None


def test_a_formula_inside_a_citation_does_not_count_as_the_answer():
    text = ("MOZIONE Parità nella pubblica amministrazione\n" + FILLER + " I dati sono stati forniti dal Municipio nella "
            "risposta all'interrogazione 1069. Nell'attesa di una risposta, cordiali saluti.")
    assert screen(text, number="4024", body="5192", heading=inopd.HEADING).reason == "member_text_only"


# ---------------------------------------------------------------- affair number cross-check
SO = ris4tw.SHAPES["SO"]


def test_header_number_of_another_affair():
    text = ("Regierungsratsbeschluss vom 29. Oktober 2024\nNr. 2024/1732\nA 0110/2024 (BJD)\nAuftrag X: Regionale "
            "Baukommission ermöglichen\nStellungnahme des Regierungsrates" + FILLER)
    hit = screen(text, number="A 0113/2024", body="SO", shape=SO, patterns=[r"A\s*0113/2024"])
    assert hit.reason == "wrong_affair" and hit.outcome == "review" and "A 0110/2024" in hit.quote


@pytest.mark.parametrize("text,number", [
    ("Regierungsratsbeschluss vom 1. Mai 2024\nNr. 2024/1\nA 0113/2024 (BJD)" + FILLER, "A 0113/2024"),
    # joint answer: another affair heads the document, the target is printed further down
    ("Regierungsratsbeschluss vom 1. Mai 2024\nNr. 2024/1\nA 0110/2024 (BJD)" + FILLER + " und A 0113/2024",
     "A 0113/2024"),
])
def test_header_number_of_the_target_or_a_joint_answer_passes(text, number):
    assert screen(text, number=number, body="SO", shape=SO, patterns=[r"A\s*0113/2024"]) is None


def test_zurich_vorlage_letter_belongs_to_the_same_affair():
    text = "Antrag des Regierungsrates vom 1. Juli 2025\nKR-Nr. 276c/2021\nBericht zur Motion" + FILLER
    assert filters.wrong_affair(base.flatten(text), dict(number="276/2021"), zh.Zurich.number_shape, []) is None


def test_filters_run_inside_check_and_never_move_a_row_up():
    ad = registry.get("SO")
    text = ("Regierungsratsbeschluss vom 29. Oktober 2024\nNr. 2024/1732\nA 0110/2024 (BJD)\nAuftrag X: Regionale "
            "Baukommission ermöglichen\nStellungnahme des Regierungsrates" + FILLER)
    x = dict(id=1, body="SO", number="A 0113/2024", title="Regionale Baukommission ermöglichen",
             answer_dates=["2024-12-12"], gov_dates=["2024-10-29"], submit_dates=[])
    c = base.Candidate(url="u", title="Stellungnahme RR zu A 0113/2024", origin="source", source_typed_answer=True,
                       meta=dict(doc_date="2024-10-29"))
    chk = ad.check(x, c, text)
    # identity by title, heading and the executive's date pass; the header number moves the row to review
    assert chk["identity"] and chk["date_ok"] and chk["outcome"] == "review" and chk["reason"] == "wrong_affair"
    assert chk["filter"] == "wrong_affair" and "A 0110/2024" in chk["filter_quote"]
    x["title"] = "Etwas ganz anderes"
    chk = ad.check(x, c, text)  # identity fails anyway: failed keeps its own reason, the filter is recorded
    assert chk["outcome"] == "failed" and chk["reason"] == "identity_fail" and chk["filter"] == "wrong_affair"


# ---------------------------------------------------------------- reply to a council resolution
def test_reply_to_a_council_resolution_goes_to_review():
    text = ("Ville de Muster\nMunicipalité\nA Mesdames et Messieurs les membres du Conseil communal\nMuster, le 12 janvier "
            "2023\nRésolution de Mme X du 9 novembre 2021 adoptée par le Conseil communal suite à la réponse à "
            "l'interpellation urgente de Mme X « Un projet »" + FILLER)
    hit = screen(text, number="INT21/048", body="5586", heading=inopd.HEADING)
    assert hit.reason == "resolution_reply" and hit.outcome == "review"
    assert screen("Réponse de la Municipalité à l'interpellation de M. Y" + FILLER, number="INT21/048", body="5586",
                  heading=inopd.HEADING) is None


# ---------------------------------------------------------------- runner: refilter re-processes what a filter moved
def test_refilter_moves_an_extension_down_and_finds_the_answer_next_to_it(monkeypatch, tmp_path):
    ad = registry.get("351")
    ext = ("2014.SR.000106\nVortrag des Gemeinderats an den Stadtrat\nPostulat Fraktion AB (X. Muster): Ein Platz für "
           "alle; Fristverlängerung\nBern, 11. März 2015" + FILLER)
    ans = ("2014.SR.000106\nVortrag des Gemeinderats an den Stadtrat\nPostulat Fraktion AB (X. Muster): Ein Platz für "
           "alle; Prüfungsbericht\nBern, 11. März 2015" + FILLER)
    x = dict(id=7, body="351", number="2014.SR.000106", type="Postulate", year=2014, cause="absent",
             title="Ein Platz für alle", answer_dates=["2015-03-11"], gov_dates=[], submit_dates=[])
    docs = [dict(id=1, name="Vortrag", url="u1", url_oparl="o1", text=ext),
            dict(id=2, name="Vortrag", url="u2", url_oparl="o2", text=ans)]
    monkeypatch.setattr(run, "STATE", tmp_path)
    monkeypatch.setattr(base, "ADIR", tmp_path)
    monkeypatch.setattr(run.targets, "load", lambda body=None, cause=None: [x])
    monkeypatch.setattr(opd_docs, "load", lambda body: {7: docs})
    monkeypatch.setattr(run, "seed_url_cache", lambda body: None)
    # the first run's record: the extension verified (checks without filters), the answer never tried
    old = dict(affair_id=7, affair_number=x["number"], body="351", cause="absent", type="Postulate", year=2014,
               outcome="verified", reason=None, action="tag_answer", tried=[],
               excerpt=str(base.save_excerpt("351", 7, ext, dict(affair_id=7))),
               best=dict(url="u1", title="Vortrag", origin="opd_text", opd_doc_id=1,
                         checks=dict(outcome="verified", reason=None)))
    (tmp_path / "351.jsonl").write_text(json.dumps(old) + "\n")
    assert ad.check(x, base.Candidate(url="u1", title="Vortrag", origin="opd_text"), ext)["reason"] == "extension_request"
    out = run.refilter("351")
    assert out["rechecked"] == {"verified->failed": 1} and out["reprocessed"] == {"failed->verified": 1}
    r = run.load_state("351")[7]
    assert r["outcome"] == "verified" and r["best"]["opd_doc_id"] == 2
    assert r["refiltered_from"] == dict(outcome="failed", reason="extension_request", url="u1")


def test_write_never_redraws_an_existing_audit_sample(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "AUDIT", tmp_path)
    (tmp_path / "X.jsonl").write_text("judged\n")
    called = []
    monkeypatch.setattr(run, "audit", lambda body, recs: called.append(body))
    monkeypatch.setattr(run, "OUT", tmp_path / "out")
    monkeypatch.setattr(run, "load_state", lambda body: {})
    monkeypatch.setattr(run, "write_summary", lambda: {})
    monkeypatch.setattr(run.registry, "get", lambda body: inopd.InOPD("X"))
    monkeypatch.setattr(run, "snapshot", lambda body: "snap")
    run.write("X")
    assert called == [] and (tmp_path / "X.jsonl").read_text() == "judged\n"


def test_fresh_audit_is_proportional_with_a_floor_and_excludes_the_first_audit(monkeypatch, tmp_path):
    out, first, res = tmp_path / "audit2", tmp_path / "audit", tmp_path / "res"
    first.mkdir()
    res.mkdir()
    (first / "A.jsonl").write_text(json.dumps(dict(body="A", affair_id=1)) + "\n")
    pools = {"A": range(1, 101), "B": range(1, 4), "C": range(1, 31)}
    for b, ids in pools.items():
        affairs = [dict(affair_id=i, number=str(i), cause="absent", outcome="verified", date_match="eq") for i in ids]
        (res / f"{b}.json").write_text(json.dumps(dict(affairs=affairs)))
    ex = tmp_path / "ex.txt"
    ex.write_text("{}\n\ntext")
    monkeypatch.setattr(run, "OUT", res)
    monkeypatch.setattr(run, "load_state", lambda b: {i: dict(affair_number=str(i), outcome="verified", excerpt=str(ex), best={})
                                                     for i in pools[b]})
    monkeypatch.setattr(run.targets, "load", lambda b=None, cause=None: [])
    got = run.fresh_audit(20, seed=1, out=out, exclude_dir=first)
    assert got["n"] == 20 and got["per_body"]["B"] == 3 and got["per_body"]["C"] >= 5
    assert got["pool"] == 99 + 3 + 30 and got["excluded"] == 1
    rows = [json.loads(x) for x in (out / "A.jsonl").read_text().splitlines()]
    assert all(r["affair_id"] != 1 for r in rows) and all(r["excerpt_path"].startswith(str(out)) for r in rows)
    assert got == run.fresh_audit(20, seed=1, out=out, exclude_dir=first)  # reproducible
