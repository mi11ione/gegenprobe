"""Repair routes: pure logic on synthetic inputs, plus regression on the committed outputs (no network, no large caches)."""

import csv
import json

import pytest

from gegenprobe.paths import DATA, RESULTS
from gegenprobe.repair import be, che, common, vs

HEADER = (
    "Geschäftsnummer: 2024.RRGR.91\nDringlichkeit verlangt:\nDringlichkeit gewährt:\n\nNein\n\nRRB-Nr.:\nDirektion:\n"
    "Klassifizierung:\n\n879/2024\nvom 28. August 2024\nBildungs- und Kulturdirektion\n\nAntwort des Regierungsrates\n"
)


def test_parse_rrb_header_reading_order():
    assert be.parse_rrb(HEADER) == ("879/2024", "2024-08-28")


def test_parse_rrb_ignores_body_citation_without_colon():
    t = "Der Regierungsrat ist in seiner Antwort (RRB-Nr. 1108/2024 vom\n06.11.2024) nicht eingegangen.\n" + HEADER
    assert be.parse_rrb(t) == ("879/2024", "2024-08-28")


def test_parse_rrb_v2_split_columns_only_in_v2():
    t = "RRB-Nr.:\nDirektion:\nKlassifizierung:\n\n927/2020\nStaatskanzlei\nNicht klassifiziert\n\nvom 19. August 2020\n"
    assert be.parse_rrb(t, version=1) == (None, None)
    assert be.parse_rrb(t, version=2) == ("927/2020", "2020-08-19")


def test_verify_text_triple():
    c = be.verify_text(HEADER, "2024.RRGR.91", None, ["2024-08-28"])
    assert c["identity"] and c["heading"] and c["date_eq_event"] and c["triple"]
    c = be.verify_text(HEADER, "2024.RRGR.91", None, ["2024-09-04"])
    assert c["date_eq_event"] is False and not c["triple"]
    c = be.verify_text(HEADER, "2024.RRGR.92", None, ["2024-08-28"])
    assert not c["identity"]
    assert be.verify_text(HEADER, "2024.RRGR.91", None, [])["date_eq_event"] is None


def test_join_prefers_parentless_german_copy():
    answers = {
        "g1": [
            dict(dokument_uid="u_fr", dokument_titel="RRB-01.01.2024-fr", dokument_url="x"),
            dict(dokument_uid="u_de", dokument_titel="RRB-01.01.2024-de", dokument_url="y"),
        ],
        "g2": [dict(dokument_uid="u2", dokument_titel="RRB-02.02.2024-de", dokument_url="z")],
    }
    affairs = {
        1: dict(number="2024.RRGR.1", external_id="g1"),
        2: dict(number="2024.RRGR.2", external_id="g2"),
        3: dict(number="2024.RRGR.3", external_id="g3"),
    }
    rows, c = be.join(answers, affairs, {"u_de": dict(id=10), "u_fr": dict(id=11)})
    assert dict(c) == {"relink": 1, "fetch": 1, "no_source_answer": 1}
    assert rows[0]["opd_doc_id"] == 10 and rows[0]["source_doc_uid"] == "u_de"
    assert rows[1]["action"] == "fetch" and rows[1]["opd_doc_id"] is None


def test_dates_multilingual():
    got = [
        d for d, _, _ in common.parse_dates("Bellinzona 1° aprile 2020; Sion, le 3 mars 2021; Bern, 28. August 2024; 04.06.2020")
    ]
    assert got == ["2020-04-01", "2021-03-03", "2024-08-28", "2020-06-04"]


def test_answer_heading_lexicon():
    for s in (
        "Antwort des Regierungsrates",
        "Réponse du Conseil-exécutif",
        "Réponse du Conseil d'État",
        "Risposta del Consiglio di Stato",
    ):
        assert common.ANSWER_HEADING.search(s), s


def test_vs_stub_rule():
    stub = "cf. réponse orale du Conseil d’Etat \n\n s. mündliche Antwort des Staatsrats"
    assert vs.is_stub("INT_2020.03.048_Deponie_ANT", stub)
    assert not vs.is_stub("INT_2020.03.048_Deponie_REP", stub)  # not an _ANT document
    assert not vs.is_stub("INT_2020.03.048_Deponie_ANT", stub + " x" * 200)  # long text is a real answer
    assert not vs.is_stub("INT_2020.03.048_Deponie_ANT", "Pas de réponse pour les Interpellations")


def test_che_verify_rule():
    x = dict(citation="BBl 2014 9657", year="2014", page="9657")
    assert che.verify_text("Bundesbeschluss BBl 2014 9657 " + "x" * 1200, x)["verified"]
    assert not che.verify_text("Bitte aktivieren Sie Javascript " + "x" * 1200, x)["verified"]
    assert not che.verify_text("Bundesbeschluss 2014 9657 kurz", x)["verified"]
    assert che.www_filestore("https://fedlex.data.admin.ch/filestore/a/b.pdf") == "https://www.fedlex.admin.ch/filestore/a/b.pdf"


def test_write_rows_roundtrip(tmp_path):
    r = dict(
        body="XX",
        affair_id=1,
        affair_number="1",
        action="relink",
        opd_doc_id=2,
        source_doc_uid="u",
        source_doc_title="t",
        source_url="s",
        checks=dict(a=True),
        verified=True,
        note="n",
    )
    tsv, js = common.write_rows("XX", [r], out=tmp_path)
    row = next(csv.DictReader(open(tsv), delimiter="\t"))
    assert row["action"] == "relink" and row["proposed_action"] == "relink" and row["verified"] == "true"
    assert row["check_detail"] == "a=true"  # no JSON inside cells
    with pytest.raises(AssertionError):
        common.write_rows("XX", [dict(r, action="guess")], out=tmp_path)


def test_write_rows_plain_checks_and_per_action_split(tmp_path):
    base = dict(body="XX", affair_id=1, affair_number="1", opd_doc_id=2, source_doc_uid="u", source_doc_title="t",
                source_url="s", note="n")
    rows = [
        dict(base, action="relink", checks=dict(identity=True, heading=True, decision_date="2024-08-28",
                                                answer_event_dates=["2024-08-28"], date_eq_event=True), verified=True),
        dict(base, affair_id=3, action="review", proposed_action="relink",
             checks=dict(identity=True, heading=False, fetch_error=None), verified=False),
        dict(base, affair_id=4, action="fetch"),
    ]
    common.write_rows("XX", rows, out=tmp_path)
    got = list(csv.DictReader(open(tmp_path / "repair_XX.tsv"), delimiter="\t"))
    assert [r["action"] for r in got] == ["relink", "review", "fetch"]
    assert got[0]["check_answer_event_dates"] == "2024-08-28" and got[0]["check_date_eq_event"] == "true"
    assert got[1]["proposed_action"] == "relink" and got[1]["check_heading"] == "false" and got[2]["verified"] == ""
    assert not any(c.startswith("{") for r in got for c in r.values())
    for a in ("relink", "review", "fetch"):
        assert (tmp_path / f"repair_XX_{a}.tsv").exists()


def test_ogd_alerts():
    from gegenprobe.monitor.nightly import ogd_alerts

    ok = dict(missing_columns=[], missing_answer_types=[], answer_documents=9577)
    assert ogd_alerts(dict(answer_documents=9500), ok) == []
    bad = dict(missing_columns=["dokument_typ_deutsch"], missing_answer_types=["RRB"], answer_documents=0)
    assert {a["kind"] for a in ogd_alerts(dict(answer_documents=9577), bad)} == {"be_ogd_schema_change",
                                                                                 "be_ogd_answers_collapsed"}
    assert [a["kind"] for a in ogd_alerts(dict(answer_documents=9577), dict(ok, answer_documents=4000))] == [
        "be_ogd_answers_collapsed"]


def test_acceptance_score():
    from gegenprobe.repair.acceptance import score

    want = {10: 1, 11: 2, 12: 3, 13: 4}
    docs = [dict(id=10, a=1, ag=None, m=None), dict(id=11, a=None, ag=None, m=None), dict(id=12, a=9, ag=None, m=None)]
    r = score(docs, want)
    assert (r["attached_to_listed_affair"], r["still_parentless"], r["attached_elsewhere"], r["doc_not_in_snapshot"]) == (
        1, 1, 1, 1) and not r["passed"]


# ---------------------------------------------------------------- regression on committed outputs
def test_be_list_matches_fixture():
    rows = [
        dict(r, affair_id=int(r["affair_id"]), opd_doc_id=int(r["opd_doc_id"]) if r["opd_doc_id"] else None)
        for r in (
            dict(x, action=x.get("proposed_action") or x["action"])  # rows sent to review keep their route
            for x in csv.DictReader(open(RESULTS / "repair" / "repair_BE.tsv", encoding="utf-8"), delimiter="\t")
        )
        if r["action"] in ("relink", "fetch")
    ]
    reg = be.regress(rows)
    assert reg["identical"] and reg["fixture_actions"] == {"relink_parentless_opd_doc": 2459, "fetch_from_canton": 49}


def test_be_verify40_reproduces():
    v = json.loads((RESULTS / "repair" / "be_verify40.json").read_text())
    assert (v["verified_spike_rule"], v["n"], v["event_eq_rrb"], v["with_answer_event"]) == (40, 40, 39, 39)


def test_prereg_hash_matches():
    import hashlib

    s = json.loads((RESULTS / "repair" / "be_relink_sample.json").read_text())
    assert s["prereg_sha256"] == hashlib.sha256((DATA / "repair" / "prereg_be_relink_sample.md").read_bytes()).hexdigest()
    assert (DATA / "repair" / "prereg_be_relink_sample.sha256").read_text().split()[0] == s["prereg_sha256"]
