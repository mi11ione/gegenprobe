"""Census: frozen classifiers on hand-made fixtures, the funnel on a synthetic mini-corpus, and replay integrity."""

import gzip
import json
import os
from pathlib import Path

import pytest

from gegenprobe.census import defs, funnel, matrix, replay
from gegenprobe.census.tables import CENSUS


# ---------------------------------------------------------------- frozen patterns
@pytest.mark.parametrize(
    "title,hid,want",
    [
        ("Beantwortet", 6, "written"),
        ("Antwort des Regierungsrates", None, "written"),
        ("Der Bundesrat beantragt die Ablehnung der Motion.", None, "written"),
        ("Réponse du Conseil d'Etat", None, "written"),
        ("Risposta del Consiglio di Stato", None, "written"),
        ("Überweisung an den Regierungsrat zur Stellungnahme", None, None),  # referral, not an answer
        ("Fragestunde: mündliche Antwort", None, "oral"),
        ("Réponse de M. le conseiller d'Etat", None, "oral"),
        ("Eingereicht", 1, None),
    ],
)
def test_classify_event(title, hid, want):
    assert defs.classify_event(title, hid) == want


@pytest.mark.parametrize(
    "name,cat,flags,want",
    [
        ("RRB-28.08.2024-de", None, [], True),
        ("Vorstoss-de", None, [], False),
        ("Vorstoss-de", None, ["ans_head"], True),
        ("POS_2025.05.113_Vermögenssteuern senken_ANT", None, [], True),
        ("Réponse du Conseil d'Etat", None, [], True),
        ("Traktandenliste", "Einladung", [], False),
    ],
)
def test_is_answer_doc(name, cat, flags, want):
    assert defs.is_answer_doc(name, cat, flags) is want


@pytest.mark.parametrize(
    "type_h, type_raw, want",
    [
        ("Question time", "Anfrage", True),
        ("Question", "Fragestunde", True),
        ("Question", "Question orale", True),
        ("Interpellation", "Interpellation orale", True),
        ("Question", "Mündliche Anfrage", True),
        ("Question", "Heure des questions", True),
        ("Question", "Interrogazione orale", True),
        ("Question", "Kleine Anfrage", False),
        ("Interpellation", "Interpellation", False),
    ],
)
def test_is_question_time(type_h, type_raw, want):
    assert defs.is_question_time(type_h, type_raw) is want


def test_text_status():
    assert defs.text_status(None) == "null"
    assert defs.text_status("  ") == "blank"
    assert defs.text_status("[extraction_failed: x]") == "failed"
    assert defs.text_status("Bitte aktivieren Sie JavaScript in Ihrem Browser") == "ph_fedlex_js"
    assert defs.text_status("JavaScript " * 500) == "ok"  # long documents are never placeholders
    assert defs.text_status("Antwort des Regierungsrates …") == "ok"


def test_year_of():
    assert defs.year_of("2024.RRGR.91", "2019-01-01") == (2024, "number")
    assert defs.year_of("INT_5.0460", "2019-11-12") == (2019, "begin")
    assert defs.year_of(None, None) == (None, "none")


def test_text_flags():
    # Frozen spike behaviour, kept as-is: the flag expects the year first ("2013/1234"); the current BE order
    # "879/2024" is not flagged, so BE answers are found by their heading/name instead (docs/census.md, known limitations).
    assert defs.TEXT_FLAGS["be_rrb_filled"].search("RRB-Nr.: 2013/1234 vom 28. August 2013")
    assert not defs.TEXT_FLAGS["be_rrb_filled"].search("RRB-Nr.: 879/2024 vom 28. August 2024")
    assert not defs.TEXT_FLAGS["be_rrb_filled"].search("RRB-Nr.: vom")  # the empty template field of a question PDF
    assert defs.TEXT_FLAGS["ans_head"].search("Antwort des Regierungsrates")


@pytest.mark.parametrize(
    "hid,title,actor,want",
    [
        (29, "Antrag: Ablehnen", "Regierung", "reject"),
        (None, "Der Bundesrat beantragt die Annahme des Postulates.", "", "accept"),
        (None, "Der Bundesrat beantragt, die Motion in ein Postulat umzuwandeln.", "", "convert"),
        (None, "Der Regierungsrat beantragt Entgegennahme", "", "accept"),
        (None, "Kommissionsantrag, nicht gleichlautend", "Kommission für Justiz", None),
        (
            30,
            "Antrag: Annehmen",
            "Commission sociale, jeunesse et enfance",
            None,
        ),  # a commission's motion is not the government's
        (None, "Antrag Gemeinderat", "", None),  # recommendation exists but its value is not in the title
    ],
)
def test_gov_rec(hid, title, actor, want):
    assert matrix.gov_rec_of(hid, title, actor) == want


def test_cell_status_and_tier():
    assert matrix.cell_status(0.95, 0.0) == "metadata"
    assert matrix.cell_status(0.5, 0.0) == "mixed"
    assert matrix.cell_status(0.05, 0.6) == "pdf"
    assert matrix.cell_status(0.05, 0.4) == "no_source"
    assert matrix.tier(["metadata"] * 8 + ["pdf"] * 2) == "feasible"
    assert matrix.tier(["metadata"] * 7 + ["no_source"] * 3) == "fundamentally different"
    assert matrix.tier(["metadata"] * 7 + ["pdf"] * 2 + ["no_source"]) == "partial"


# ---------------------------------------------------------------- funnel on a synthetic mini-corpus
def _w(d: Path, name: str, cols: list[str], rows: list[list]):
    with gzip.open(d / f"{name}.tsv.gz", "wt", encoding="utf-8") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join("" if v is None else str(v) for v in r) + "\n")


@pytest.fixture
def mini(tmp_path):
    d = tmp_path
    _w(
        d,
        "affairs",
        ["id", "body", "type_h", "type_raw", "number", "begin", "end", "state_raw", "state_h", "ext"],
        [
            [1, "BE", "Interpellation", "Interpellation", "2024.RRGR.1", "2024-01-10", "", "", "", "u1"],  # attached
            [2, "BE", "Interpellation", "Interpellation", "2024.RRGR.2", "2024-01-10", "", "", "", "u2"],  # agenda
            [3, "BE", "Motion", "Motion", "2024.RRGR.3", "2024-01-10", "", "", "", "u3"],  # parentless
            [4, "VS", "Question", "Question", "Q_1", "2024-02-01", "", "", "", ""],  # VS oral stub
            [5, "TI", "Question", "Interrogazione", "5.1", "2024-02-01", "", "", "", ""],  # image only
            [6, "ZH", "Postulate", "Postulat", "2024/6", "2024-03-01", "", "", "", ""],  # absent
            [7, "ZH", "Postulate", "Postulat", "2024/7", "2024-03-01", "", "", "", ""],  # not applicable
            [8, "ZH", "Report", "Bericht", "2024/8", "2024-03-01", "", "", "", ""],  # out of scope
            [9, "GR", "Question time", "Fragestunde", "2024-9", "2024-03-01", "", "", "", ""],  # question time: oral
            [10, "CHE", "Question time", "Fragestunde. Frage", "24.9", "2024-03-01", "", "", "", ""],  # written: absent
            [11, "VD", "Question", "Question orale", "24_1", "2024-03-01", "", "", "", ""],  # raw label: oral
        ],
    )
    _w(
        d,
        "events",
        ["affair", "date", "hid", "title", "actor"],
        [[a, "2024-04-01", 6, "Beantwortet", ""] for a in (1, 2, 3, 4, 5, 6, 9, 11)]
        + [[7, "2024-01-01", 1, "Eingereicht", ""], [10, "2024-04-01", None, "Schriftliche Beantwortung der Frage", ""]],
    )
    _w(d, "agendas", ["id", "affair"], [[900, 2]])
    _w(
        d,
        "docs",
        ["id", "body", "affair", "agenda", "meeting", "status", "n", "flags", "lang", "cat_h", "be_uid", "name", "cat"],
        [
            [10, "BE", 1, "", 0, "ok", 5000, 0, "de", "", "", "RRB-01.04.2024-de", ""],
            [11, "BE", "", 900, 0, "ok", 5000, 0, "de", "", "", "RRB-01.04.2024-de", ""],
            [12, "BE", "", "", 0, "ok", 5000, 0, "de", "", "c" * 32, "RRB-01.04.2024-de", ""],
            [13, "VS", 4, "", 0, "ok", 87, 0, "", "", "", "Q_1_Titel_ANT", ""],
            [14, "TI", 5, "", 0, "null", 0, 0, "", "", "", "Risposta del CdS", ""],
        ],
    )
    _w(
        d,
        "docs_other",
        ["affair", "body", "status", "usable", "lang", "cat_h", "meeting", "agenda", "count"],
        [["", "ZH", "ok", 1, "de", "", 0, 0, 3]],
    )
    _w(d, "texts", ["id", "body", "affair", "type", "date", "maxlen"], [])
    _w(d, "be_ogd_answers", ["geschaeft_uid", "dokument_uid", "typ", "titel"], [["u3", "c" * 32, "RRB", "RRB-01.04.2024-de"]])
    return d


def test_funnel_mini(mini):
    res, aff = funnel.compute(mini)
    assert {a: x["link"] for a, x in aff.items()} == {
        1: "attached",
        2: "agenda",
        3: "parentless",
        4: "oral",
        5: "image_only",
        6: "absent",
        7: "not_applicable",
        9: "oral",
        10: "absent",
        11: "oral",
    }
    summ = funnel.summarise(res, aff)
    s = summ["national"]
    # question-time typing changes the cause only: the gap still counts all three
    assert (s["n"], s["ev_answer"], s["gap"], s["gap_after_agenda_join"]) == (10, 9, 8, 7)
    assert summ["gap_oral_split"]["question_time"] == 2 and summ["gap_oral_split"]["vs_stub"] == 1
    assert res["parentless_docs_by_body"] == {"BE": 1, "ZH": 3}


# ---------------------------------------------------------------- committed data and replay
def test_committed_tables_match_meta():
    assert replay.verify_inputs(CENSUS) == []


def test_data_budget():
    assert sum(p.stat().st_size for p in CENSUS.iterdir()) < 30e6


def test_no_person_names_in_contributors():
    meta = json.loads((CENSUS / "meta.json").read_text())
    with gzip.open(CENSUS / "contributors.tsv.gz", "rt") as f:
        assert f.readline().strip().split("\t") == ["affair", "role_h", "type", "n"]
    assert meta["rows"]["contributors"] > 0


@pytest.mark.skipif(os.environ.get("GP_SLOW") != "1", reason="full replay takes ~1 min; set GP_SLOW=1")
def test_full_replay():
    errs, _ = replay.replay()
    assert errs == []
