"""Source adapters (repair/adapters): checks, candidate parsing per parliament, runner outcomes. Synthetic fixtures only:
short hand-written texts and API responses shaped like the real ones; no network, no document text from any parliament."""

import json
import re

import pytest

from gegenprobe import net
from gegenprobe.repair.adapters import base, inopd, lu, registry, ris4tw, robots, run, vs, zh, zurich_city


@pytest.fixture(autouse=True)
def _no_robots_fetch(monkeypatch):
    monkeypatch.setattr(robots, "allowed", lambda url: True)


def affair(**kw):
    x = dict(id=1, body="X", number="2019/375", type="Question", year=2019, cause="absent", title="Städtische "
             "Lichtemissionen, Gründe für die geringe Reduktion", answer_dates=["2019-11-27"], gov_dates=[],
             submit_dates=["2019-09-04"], external_id="6438", url_external=None)
    x.update(kw)
    return x


CITY_ANSWER = (
    "Auszug aus dem Protokoll des Stadtrats von Zürich\n\nGR Nr. 2019/375\nvom 27. November 2019\n\n1057.\n"
    "Schriftliche Anfrage betreffend städtische Lichtemissionen, Gründe für die geringe Reduktion ...\n"
    "Der Stadtrat beantwortet die An-\nfrage wie folgt:\n\nZu Frage 1: " + "x " * 120
)
CITY_QUESTION = "Stadt Zürich Gemeinderat Schriftliche Anfrage GR Nr. 2019/ 375 4. September 2019 " + "Frage " * 60


# ---------------------------------------------------------------- shared checks
def test_flatten_joins_hyphenated_line_breaks():
    assert "Anfrage wie folgt" in base.flatten("die An-\nfrage wie\n folgt")


def test_title_match_exact_and_words():
    assert base.title_match("... betreffend Krankenkassen Abrechnungssystem Tiers garant ...",
                            "Krankenkassen Abrechnungssystem Tiers garant")[0]
    assert not base.title_match("ganz anderer Text " * 20, "Krankenkassen Abrechnungssystem Tiers garant")[0]
    assert not base.title_match("Bar", "Bar")[0]  # too short to identify an affair


@pytest.mark.parametrize("dd,ev,window,label,ok", [
    ("2019-11-27", ["2019-11-27"], (0, 0), "eq", True),
    ("2009-09-09", ["2009-09-16"], (0, 15), "window(+7d)", True),
    ("2009-09-09", ["2009-09-16"], (0, 0), "near(7d)", False),
    ("2009-01-01", ["2009-09-16"], (0, 0), "differs(258d)", False),
])
def test_date_check(dd, ev, window, label, ok):
    a = zurich_city.ZurichCity()
    a.date_window = window
    got = a.date_check("kein Datum", dd, ev)
    assert got[0] == label and got[2] is ok


def test_date_check_after_submission_when_opd_has_no_dated_answer_event():
    a = inopd.InOPD("JU")
    a._submit = ["2020-05-01"]
    assert a.date_check("", "2020-08-25", [])[:3:2] == ("after_submission(+116d)", True)
    assert a.date_check("", "2022-08-25", [])[2] is None  # more than a year later: not consistent


def test_date_check_any_printed_date_and_gov_event():
    a = inopd.InOPD("X")
    assert a.date_check("Bern, 12. März 2020", None, ["2020-03-12"])[0] == "anywhere"
    assert a.date_check("", "2025-04-22", ["2025-06-11"], gov=["2025-04-22"])[0] == "eq_gov"


# ---------------------------------------------------------------- Zürich city: OPD's own text
def test_zurich_city_verifies_the_answer_not_the_question():
    ad = zurich_city.ZurichCity()
    opd = [dict(id=10, name="2019_0375", url="u1", text=CITY_QUESTION),
           dict(id=11, name="2019_0375", url="u2", text=CITY_ANSWER),
           dict(id=12, name="Protokolleintrag_2019-375", url="u3", text="Protokolleintrag " * 30)]
    cands = ad.candidates(affair(), opd)
    assert [c.opd_doc_id for c in cands][:2] == [11, 10] and all(c.opd_doc_id != 12 for c in cands)
    rec = run.process(ad, affair(), opd)
    assert rec["outcome"] == "verified" and rec["action"] == "tag_answer" and rec["best"]["opd_doc_id"] == 11
    assert rec["best"]["checks"]["date_match"] == "eq" and rec["best"]["checks"]["identity_by"] == "number"


def test_zurich_city_number_spellings():
    ad = zurich_city.ZurichCity()
    ok, how = ad.identity("GR Nr. 2009/039", affair(number="2009/39", title=None))
    assert ok and how == "number"
    assert not ad.identity("GR Nr. 2009/390", affair(number="2009/39", title=None))[0]


# ---------------------------------------------------------------- canton Zürich: CDWS XML
CDWS = """<?xml version="1.0" encoding="utf-8"?><SearchDetailResponse numHits="1"
 xmlns="http://www.cmiag.ch/cdws/searchDetailResponse" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<Hit Guid="g"><Geschaeft xmlns="http://www.cmiag.ch/cdws/Geschaeft"><KRNr>52/2004</KRNr><Ablaufschritte>
<Ablaufschritt><AblaufschrittTyp>Eingereicht</AblaufschrittTyp><Dokumente><Dokument><Titel>Anfrage 52/2004 T</Titel>
<eDocument ID="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-332"><Version Nr="1"><Rendition Extension="pdf"/></Version></eDocument>
</Dokument></Dokumente></Ablaufschritt>
<Ablaufschritt><AblaufschrittTyp>Antwort Regierungsrat</AblaufschrittTyp><Sitzungsdatum><Text>07.04.2004</Text>
</Sitzungsdatum><Dokumente><Dokument><Titel>Antwort RR 52/2004 T.pdf</Titel>
<eDocument ID="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-332"><Version Nr="1"/><Version Nr="2"><Rendition Extension="pdf"/>
</Version></eDocument></Dokument></Dokumente></Ablaufschritt></Ablaufschritte></Geschaeft></Hit></SearchDetailResponse>"""


def test_zh_cdws_answer_step_and_pdf_version(monkeypatch):
    monkeypatch.setattr(net, "get", lambda url, **kw: CDWS.encode())
    ad = zh.Zurich()
    ad._opd_eids = {}
    cands = ad.candidates(affair(number="52/2004"), [])
    assert len(cands) == 1 and cands[0].source_typed_answer
    assert cands[0].url.endswith("/Files/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb-332/2/pdf")
    text = ("Auszug aus dem Protokoll des Regierungsrates des Kantons Zürich\nSitzung vom 7. April 2004\n522. Anfrage "
            "(Krankenkassen Abrechnungssystem Tiers garant)\nKR-Nr. 52/2004 ... wird wie folgt beantwortet: " + "x " * 50)
    chk = ad.check(affair(number="52/2004", answer_dates=["2004-04-07"]), cands[0], text)
    assert chk["outcome"] == "verified" and chk["doc_date"] == "2004-04-07"


def test_zh_unknown_number_is_typed_not_found(monkeypatch):
    monkeypatch.setattr(net, "get", lambda url, **kw: CDWS.encode())
    ad = zh.Zurich()
    ad._opd_eids = {}
    with pytest.raises(base.Failure) as e:
        ad.candidates(affair(number="53/2004"), [])
    assert e.value.reason == "not_found"


# ---------------------------------------------------------------- SG / SO: RIS JSON
def test_ris_published_documents(monkeypatch):
    docs = [dict(document_type_name="Antwort", title="Antwort der Regierung vom 12. August 2025", id=1,
                 file="/media/a.pdf", signed_file="/media/signed/a.pdf"),
            dict(document_type_name="Wortlaut", title="Wortlaut vom 2. Juni 2025", id=2, file="/media/w.pdf")]
    monkeypatch.setattr(net, "get", lambda url, **kw: json.dumps(docs).encode())
    ad = ris4tw.RIS4tw("SG")
    cands = ad.candidates(affair(number="51.25.33"), [])
    assert [c.url for c in cands] == ["https://www.ratsinfo.sg.ch/media/signed/a.pdf"]
    assert cands[0].meta["doc_date"] == "2025-08-12" and cands[0].source_typed_answer


# ---------------------------------------------------------------- VS: front-end API, oral pointers
def test_vs_candidates_both_languages_and_oral_pointer(monkeypatch):
    ent = dict(members=[dict(id=7, label="MO_5.016_ANT", _type_class="Document"),
                        dict(id=8, label="MO_5.016_Text", _type_class="Document")])

    def fake(url, **kw):
        if "entity" in url:
            return json.dumps(ent).encode()
        loc = url.rsplit("=", 1)[1]
        return json.dumps(dict(parl_process_number="MO_5.016", date="2010-05-26", attachment_versions=[
            dict(attachment_type="application/pdf", attachment_path=f"https://parlement.vs.ch/f_{loc}.pdf")])).encode()

    monkeypatch.setattr(net, "get", fake)
    cands = vs.Valais().candidates(affair(number="MO_5.016", external_id="161425"), [])
    assert [c.url for c in cands] == ["https://parlement.vs.ch/f_fr.pdf", "https://parlement.vs.ch/f_de.pdf"]
    monkeypatch.setattr(vs, "fetch_text", lambda url, body, ocr=True: ("cf. réponse orale du Conseil d'Etat", {}))
    with pytest.raises(base.Failure) as e:
        vs.Valais().text(cands[0])
    assert e.value.reason == "oral_pointer"


# ---------------------------------------------------------------- LU: affair page links
def test_lu_answer_link(monkeypatch):
    page = ('<a class="k" href="/-/klu/ris/cdws/document?fileid=' + "a" * 32 + '" target="_blank">Antwort des '
            'Regierungsrates</a><a href="/-/klu/ris/cdws/document?fileid=' + "b" * 32 + '">Vorstoss</a>')
    monkeypatch.setattr(net, "get", lambda url, **kw: page.encode())
    cands = lu.Lucerne().candidates(affair(number="2025A 721", url_external="https://www.lu.ch/kr/x?ges=1"), [])
    assert len(cands) == 1 and cands[0].uid == "a" * 32
    assert lu.Lucerne().identity("Nummer: A 721", affair(number="2025A 721", title=None))[0]


# ---------------------------------------------------------------- generic in-OPD formulas
@pytest.mark.parametrize("text", [
    "Der Stadtrat beantwortet die Einfache Anfrage wie folgt:",
    "Auf Antrag der Stadtpräsidentin beantwortet der Stadtrat die Interpellation wie folgt:",
    "REPONSE DU GOUVERNEMENT À LA QUESTION ÉCRITE DE MONSIEUR X",
    "Réponse écrite du Conseil d'État, transmise aux membres du Grand Conseil le 25 avril 2012",
    "rispondiamo alla sua interrogazione citata sopra",
    "RAPPORT DU CONSEIL D'ETAT AU GRAND CONSEIL sur le postulat",
    "Der Regierungsrat des Kantons Thurgau an den Grossen Rat",
])
def test_inopd_answer_formulas(text):
    assert inopd.HEADING.search(text)


@pytest.mark.parametrize("text", [
    "Le Conseil d'État est prié de répondre aux questions suivantes",
    "Souhait d'une réponse écrite : OUI",
    "prend acte de la réponse de la Municipalité à ladite interpellation",
    "Wir bitten den Stadtrat um Beantwortung der folgenden Fragen",
    "So lässt der Stadtrat in seiner Beantwortung der Schriftlichen Anfrage 2023.13 durchblicken",
    "Letzten Freitag ging aus der Beantwortung der schriftlichen Anfrage hervor",
])
def test_inopd_question_and_minutes_phrases_are_not_answers(text):
    assert not inopd.HEADING.search(text)


def test_inopd_skips_legislative_minutes():
    ad = inopd.InOPD("5586")
    opd = [dict(id=1, name="Délibéré 10e séance", url="u", url_oparl="o",
                text="EXTRAIT DU PROCÈS-VERBAL DU CONSEIL COMMUNAL ... prend acte de la réponse " + "x " * 120)]
    assert ad.candidates(affair(), opd) == []


# ---------------------------------------------------------------- runner: outcomes, rows, failures
class Fake(base.Adapter):
    body = "X"
    label = "fake"
    route = "fake route"
    heading = zurich_city.HEADING
    header_date = zurich_city.HEADER_DATE

    def __init__(self, cands=None, exc=None):
        self._c, self._e = cands, exc

    def candidates(self, x, opd):
        if self._e:
            raise self._e
        return self._c


def test_runner_failure_reasons_and_review_row(monkeypatch):
    rec = run.process(Fake(exc=net.Disallowed("x", kind="robots_disallowed")), affair(), [])
    assert rec["outcome"] == "failed" and rec["reason"] == "robots_disallowed"
    assert run.process(Fake(cands=[]), affair(), [])["reason"] == "no_candidate"
    # identity and heading, date one week off -> review, never verified
    c = base.Candidate(url="https://example.org/a.pdf", title="a", origin="source", text=CITY_ANSWER.replace(
        "27. November", "20. November"))
    rec = run.process(Fake(cands=[c]), affair(), [])
    assert rec["outcome"] == "review" and rec["reason"] == "date_mismatch"
    row = run.to_row(rec, "snap", Fake())
    assert row["action"] == "review" and row["proposed_action"] == "fetch" and row["verified"] is False
    assert "date_match=near(7d)" in row["check_detail"] and len(row["check_detail"]) < 1000


def test_registry_has_source_and_generic_adapters():
    assert registry.get("ZH").route and registry.get("SG").body == "SG"
    assert isinstance(registry.get("4566"), inopd.InOPD) and registry.get("4566").date_window == (-3, 3)


# ---------------------------------------------------------------- robots.txt, RFC 9309 longest match
TI_ROBOTS = """User-agent: *
Allow: /
Disallow: /poteri/gc/ricerca-messaggi-e-atti/ricerca/
Disallow: /user_librerie/php/GC/allegato.php

User-agent: GPTBot
Disallow: /
"""


def test_robots_longest_match_beats_first_match():
    rules = robots.parse(TI_ROBOTS)
    assert not robots.decide(rules, "/user_librerie/php/GC/allegato.php?allid=131008")
    assert robots.decide(rules, "/poteri/gc/")
    import urllib.robotparser

    from gegenprobe import robots9309
    url = "https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid=1"
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(TI_ROBOTS.splitlines())  # patched process-wide (src/sitecustomize.py): RFC 9309, disallowed
    assert not rp.can_fetch("hackapertus-research/0.1", url)
    # the unpatched stdlib applies the first match and allows it (the 10 Oct 2026 incident, docs/incidents.md)
    assert robots9309._ORIG_CAN_FETCH(rp, "hackapertus-research/0.1", url)


def test_robots_wildcards_and_allow_tie():
    rules = robots.parse("User-agent: *\nDisallow: /*.pdf$\nAllow: /public/*.pdf$\nDisallow: /route/\n")
    assert not robots.decide(rules, "/a/b.pdf") and robots.decide(rules, "/public/b.pdf")
    assert robots.decide(rules, "/a/b.pdf?x=1") and not robots.decide(rules, "/route/x")


def test_aarau_answer_link_next_to_the_question_opd_holds(monkeypatch):
    from gegenprobe.repair.adapters import aarau
    page = ('<a href="https://www.aarau.ch/public/upload/assets/30965/2025-291%20Anfrage%20X.pdf?fp=1">Anfrage</a>'
            '<a href="https://www.aarau.ch/public/upload/assets/31322/2025-291%20Beantwortung%20Anfrage%20X.pdf?fp=2">'
            'Antwort Stadtrat</a><a href="/public/upload/assets/31103/2025-292%20Anfrage%20Y.pdf">Anfrage</a>')
    monkeypatch.setattr(robots, "get", lambda url, **kw: page.encode())
    ad = aarau.Aarau()
    opd = [dict(id=5, name="Anfrage", url="https://www.aarau.ch/public/upload/assets/30965/2025-291%20Anfrage", text="")]
    cands = ad.candidates(affair(number="2025/291"), opd)
    assert [c.uid for c in cands if c.origin == "source"] == ["31322"]
    assert not ad.index().get("31103")  # a question without an answer on the page has no candidate


def test_recheck_rejudges_saved_excerpts_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "STATE", tmp_path)
    monkeypatch.setattr(base, "ADIR", tmp_path)
    monkeypatch.setattr(run.registry, "get", lambda body: zurich_city.ZurichCity())
    monkeypatch.setattr(run.targets, "load", lambda body=None, cause=None: [affair()])
    ex = base.save_excerpt("261", 1, CITY_ANSWER, dict(affair_id=1))
    old = dict(affair_id=1, affair_number="2019/375", body="261", cause="absent", type="Question", year=2019,
               outcome="review", reason="heading_fail", action="tag_answer", excerpt=str(ex), tried=[],
               best=dict(url="u", title="t", origin="opd_text", opd_doc_id=11, checks=dict(outcome="review")))
    (tmp_path / "261.jsonl").write_text(json.dumps(old) + "\n")
    assert run.recheck("261")[("review", "verified")] == 1
    assert run.load_state("261")[1]["outcome"] == "verified"


# ---------------------------------------------------------------- verification tiers (docs/adapters.md)
def test_tier_of_date_classes():
    assert run.tier_of("eq") == run.tier_of("eq_gov") == "exact_doc_date"
    assert run.tier_of("anywhere") == "exact_any_printed_date"
    assert run.tier_of("window(+7d)") == run.tier_of("latest_in_window(+3d)") == "date_window"
    assert run.tier_of("after_submission(+41d)") == "identity_wording_only"
    assert run.COUNTED == ("exact_doc_date", "exact_any_printed_date", "date_window")
    for bad in ("near(5d)", "anywhere_conflict(-90d)"):
        with pytest.raises(ValueError):
            run.tier_of(bad)


def test_any_printed_date_needs_a_document_date_within_30_days():
    a = inopd.InOPD("X")
    text = "Frauenfeld, 16. April 2008 ... Antwort des Stadtrates vom 17. März 2009"
    assert a.date_check(text, None, ["2009-03-17"])[::2] == ("anywhere", True)  # no document date read
    assert a.date_check(text, "2009-02-20", ["2009-03-17"])[::2] == ("anywhere", True)  # 25 days: counts
    got = a.date_check(text, "2008-04-16", ["2009-03-17"])  # the document date is the question's: review
    assert got[0] == "anywhere_conflict(335d)" and got[2] is False


def _verified(**kw):
    rec = dict(affair_id=7, affair_number="1/2020", body="ZH", cause="absent", type="Question", year=2020,
               outcome="verified", reason=None, action="tag_answer", tried=[],
               best=dict(url="https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Files/" + "a" * 32 + "-332/2/pdf", title="t",
                         origin="source", uid="a" * 32 + "-332", opd_doc_id=None,
                         cmeta=dict(opd_holds=dict(id=11, affair_id=7, chars=900, same_affair=True)),
                         checks=dict(date_match="eq", doc_date="2020-05-05", answer_events=["2020-05-05"])))
    rec.update(kw)
    return rec


def test_classify_joins_the_opd_document_by_source_file_and_flags_two(monkeypatch):
    run.lists._by_source_file.cache_clear()
    one = [dict(id=11, affair_id=7, url="https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Files/" + "a" * 32 + "-332/2/pdf")]
    monkeypatch.setattr(run.lists.opd_docs, "url_index", lambda body: one)
    c = run.classify("ZH", _verified())
    assert (c["tier"], c["counted"], c["opd_doc_id"]) == ("exact_doc_date", True, 11)
    run.lists._by_source_file.cache_clear()
    two = one + [dict(id=12, affair_id=7, url="https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Files/" + "a" * 32 + "-332/1/pdf")]
    monkeypatch.setattr(run.lists.opd_docs, "url_index", lambda body: two)
    c = run.classify("ZH", _verified())
    assert (c["tier"], c["counted"], c["opd_doc_id"]) == ("review", False, None)
    assert c["review_reason"].startswith("opd_doc_ambiguous") and "11 12" in c["review_reason"] and "read is 11" in c[
        "review_reason"]
    run.lists._by_source_file.cache_clear()
    # Jura: identity + wording only -> listed, not counted, verified=false and action=review in the list
    ju = _verified(body="JU", best=dict(url="u", title="t", origin="opd_text", opd_doc_id=5, checks=dict(
        date_match="after_submission(+41d)")))
    c = run.classify("JU", ju)
    assert (c["tier"], c["counted"], c["opd_doc_id"]) == ("identity_wording_only", False, 5)
    row = run.to_row(ju, "snap", registry.get("JU"), c)
    assert (row["verified"], row["action"], row["proposed_action"], row["tier"]) == (False, "review", "tag_answer",
                                                                                     "identity_wording_only")
    assert row["target_category"] == "response_text" and row["target_category_note"]


def test_committed_summary_counts_only_tiers_with_a_date_check():
    s = json.loads(run.SUMMARY.read_text())
    t, c = s["tiers"], s["coverage"]
    counted = sum(t[k]["n"] for k in run.COUNTED)
    assert s["totals"]["verified"] == counted and not t["identity_wording_only"]["counted"]
    assert c["repairable_deterministic_with_adapters"] == run.BASELINE + counted == run.BASELINE + c["adapter_rows_counted"]
    assert c["needs_adapters_after"] == run.NEEDS_ADAPTERS - sum(t[k]["absent"] for k in run.COUNTED)
    assert s["bodies"]["JU"]["tiers"]["identity_wording_only"] == t["identity_wording_only"]["n"]  # Jura only
    assert s["totals"]["adapters_with_counted"] == sum(1 for b in s["bodies"].values() if b["counted"])
    tiers = json.loads((run.OUT / "tiers.json").read_text())["tiers"]
    for x in tiers["date_window"]["by_body"].values():  # every window row lies inside its parliament's window
        lo, hi = x["window_days"]
        assert lo <= x["observed_days"][0] <= x["observed_days"][1] <= hi and x["max_abs_days"] == max(-lo, hi)


def test_committed_lists_have_the_hygiene_columns():
    import csv
    n = 0
    for p in sorted(run.OUT.glob("adapters_*.tsv")):
        with open(p, encoding="utf-8") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        for r in rows:
            n += 1
            assert r["tier"] in run.ROW_TIERS and r["tier"] != "failed"
            assert r["verified"] == r["counted"] == ("true" if r["tier"] in run.COUNTED else "false")
            assert (r["action"] == r["proposed_action"]) if r["counted"] == "true" else r["action"] == "review"
            if r["counted"] == "true":
                assert re.fullmatch(r"[0-9a-f]{64}", r["text_sha256"]), (p.name, r["affair_id"])
                if r["action"] in ("tag_answer", "extract_tag"):
                    assert r["opd_doc_id"], (p.name, r["affair_id"])  # every row pointing at an OPD document names it
                assert r["target_category"] == "response_text" and r["target_category_note"]
            else:
                assert r["review_reason"], (p.name, r["affair_id"])
            if "anywhere" in r["check_detail"] and r["counted"] == "true":  # never a document date > 30 days off
                assert "anywhere_conflict" not in r["check_detail"]
    assert n and not list(run.OUT.glob("repair_*.tsv")) and not (run.OUT / "summary.json").exists()
