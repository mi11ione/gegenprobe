"""Converter tests: lattice, frozen rules, pointer/calibration plumbing (FakeBackend, no model), cascade, naive scorer."""

import json

import pytest

from eval import naive_baseline
from eval.score import outcome, summarise
from gegenprobe.convert import calibrate, cascade, lattice, pointer, rules
from gegenprobe.paths import DATA, RESULTS

BE_NO_ANSWER = (
    "I\nParlamentarischer Vorstoss\nVorstoss-Nr.:\nVorstossart:\nGeschäftsnummer:\n\n001-2024\nInterpellation\n"
    "2024.RRGR.5\n\nEingereicht am:\n\n23.01.2024\n\nRRB-Nr.:\nDirektion:\nKlassifizierung:\n\nvom\n"
    "Bau- und Verkehrsdirektion\nNicht klassifiziert\n\nBarrierefreie Haltestellen\nText der Interpellation.\n\n"
    "Nicht klassifiziert | Letzte Bearbeitung: 19.03.2024 | Version: 4 | Dok.-Nr.: 280232 | Geschäftsnummer: 2024.RRGR.5\n"
)
BE_ANSWER = (
    "I\nParlamentarischer Vorstoss\nAntwort des Regierungsrates\nVorstoss-Nr.:\nGeschäftsnummer:\n\n125-2025\n"
    "Interpellation\n2025.GRPARL.320\n\nEingereicht am:\n\n04.06.2025\n\nRRB-Nr.:\nDirektion:\nKlassifizierung:\n\n"
    "1057/2025\nvom 15. Oktober 2025\nBau- und Verkehrsdirektion\nNicht klassifiziert\n\nText.\n"
    "Nicht klassifiziert | Letzte Bearbeitung: 16.10.2025 | Version: 2\n"
)


class FakeBackend:
    """Deterministic stand-in for Apertus: scores ' null' at `lp_null`, the continuation containing `favour` at 0, others −10."""

    build = "fake"

    def __init__(self, lp_null=-5.0, favour=None):
        self.lp_null, self.favour, self.calls = lp_null, favour, []

    def score(self, user_text, prefix, conts):
        self.calls.append((user_text, prefix, conts))
        return [self.lp_null if c == " null" else (0.0 if self.favour and self.favour in c else -10.0) for c in conts]


# ------------------------------------------------------------------------------------------------ lattice
@pytest.mark.parametrize(
    "text,iso",
    [
        ("RRB-Nr.: 879/2024 vom 28. August 2024", "2024-08-28"),
        ("Genève, le 1er mars 2023", "2023-03-01"),
        ("il 1° ottobre 2023", "2023-10-01"),
        ("Bellinzona, 7 febbraio 2024", "2024-02-07"),
        ("am 3. Juli 2023", "2023-07-03"),
        ("du 3 déc. 2022", "2022-12-03"),
        ("15 sett. 2021", "2021-09-15"),
        ("12/03/2024", "2024-03-12"),
        ("2024-06-19", "2024-06-19"),
        ("déposée le 15juillet 2022", "2022-07-15"),
        ("ris. mun.: 01/02/2012", "2012-02-01"),
        ("1. gennaio 2009", "2009-01-01"),
    ],
)
def test_lattice_dates(text, iso):
    c = lattice.dates([text])
    assert [x["value"] for x in c] == [iso]
    x = c[0]
    assert text[x["char_start"] : x["char_end"]] == x["raw"]


def test_lattice_rejects_invalid_and_tracks_pages():
    assert lattice.dates(["31.02.2024 and 12.13.2024 and 1.1.1700"]) == []
    c = lattice.dates(["nothing", "Basel, 1. November 2023"])
    assert c[0]["page"] == 2 and "⟦1. November 2023⟧" in c[0]["ctx"]


def test_affair_numbers_only_known():
    idx = {"BE": {"2024.RRGR.91"}}
    c = lattice.affair_numbers(["siehe 2024.RRGR.91 und 2024.RRGR.9999"], "BE", idx)
    assert [x["value"] for x in c] == ["2024.RRGR.91"]


# ------------------------------------------------------------------------------------------------ rules
def test_rules_be_empty_template_is_null():
    r = rules.answer_date([BE_NO_ANSWER])
    assert r["status"] == "null" and r["null_reason"] == "not_in_document"


def test_rules_be_split_header_and_footer_never_chosen():
    r = rules.answer_date([BE_ANSWER])
    assert r["status"] == "value" and r["value"] == "2025-10-15" and r["number"] == "1057/2025" and r["role"] == "decision"
    assert BE_ANSWER[r["span"]["char_start"] : r["span"]["char_end"]] == "15. Oktober 2025"


def test_footer_distractor_only_date():
    # an answer heading plus only a footer date: the footer must not become the answer date
    t = "Antwort des Regierungsrates\nText ohne Datum.\nNicht klassifiziert | Letzte Bearbeitung: 19.03.2024 | Version: 4\n"
    assert rules.answer_date([t]).get("value") is None


@pytest.mark.parametrize(
    "text,iso,rule",
    [
        (
            "Auszug aus dem Protokoll\ndes Regierungsrates des Kantons Zürich\n\nSitzung vom 27. September 2023\n",
            "2023-09-27",
            "protokoll_sitzung",
        ),
        (
            "Regierungsrat des Kantons Basel-Stadt\nBasel, 1. November 2023\nRegierungsratsbeschluss vom 31. Oktober 2023\n",
            "2023-10-31",
            "rrb_vom",
        ),
        (
            "Consiglio di Stato\nBellinzona\n3 luglio 2024\nInterrogazione n. 57.24 del 16 maggio 2024\n"
            "RG n. 3382 del 3 luglio 2024\n",
            "2024-07-03",
            "it_rg",
        ),
        (
            "Réponse de la Municipalité à l’interpellation de M. X déposée le 12 mars 2024\n"
            "Ainsi adopté en séance de Municipalité, à Lausanne, le 24 octobre 2024.\n",
            "2024-10-24",
            "fr_adopte_seance",
        ),
        (
            "Winterthur, 30. November 2016\nGGR-Nr. 2016.111\nBeantwortung der Schriftlichen Anfrage betreffend X\n"
            "Am 19. September 2016 reichte Gemeinderat Y folgende Anfrage ein:\n",
            "2016-11-30",
            "place_date_head",
        ),
    ],
)
def test_rules_anchors(text, iso, rule):
    r = rules.answer_date([text])
    assert (r.get("value"), r["rule"]) == (iso, rule)


def test_rules_intervention_place_date_is_not_an_answer():
    t = "Lugano, 3 febbraio 2025\nInterpellanza\nabbiamo preso atto della risoluzione municipale del 30 gennaio 2025\n"
    assert rules.answer_date([t])["status"] == "abstain"


def test_self_deletion_removes_value():
    """Remove the anchor line: the field must no longer return that date."""
    t = BE_ANSWER.replace("vom 15. Oktober 2025\n", "")
    assert rules.answer_date([t]).get("value") != "2025-10-15"


def test_recommendation_priority_and_subject():
    assert (
        rules.recommendation(
            ["Der Regierungsrat beantragt daher dem Kantonsrat, Motion und Postulat nicht zu überweisen."], "Motion"
        )["value"]
        == "reject"
    )
    assert (
        rules.recommendation(["Antrag Regierungsrat:\n15.03.2021 / Erheblicherklärung als Postulat"], "Motion")["value"]
        == "convert"
    )
    # a commission (not the executive) recommending acceptance is not the government's recommendation
    assert rules.recommendation(["La commission propose d'accepter ce projet de loi."], "Motion")["status"] == "abstain"
    assert rules.recommendation(["x"], "Interpellation")["null_reason"] == "not_applicable"


# ------------------------------------------------------------------------------------------------ pointer + calibrate
def test_pointer_decide_and_provenance():
    be = FakeBackend(lp_null=-20.0, favour="15.10.2025")
    p = pointer.answer_date(be, [BE_ANSWER], "de", theta=0.0, anchors=rules.anchors([BE_ANSWER]))
    assert p.value == "2025-10-15" and p.span["page"] == 1
    assert BE_ANSWER[p.span["char_start"] : p.span["char_end"]] == "15. Oktober 2025"
    user, prefix, conts = be.calls[0]
    assert prefix == '{"antwort_datum":' and conts[0] == " null"
    assert ' "16.10.2025"' in conts  # the footer date is offered too: the closed set is every date in the document
    assert "<dokument>" in user and BE_ANSWER[:30] in user


def test_pointer_null_above_theta_and_only_document_values():
    be = FakeBackend(lp_null=-1.0)
    p = pointer.answer_date(be, [BE_NO_ANSWER], "de", theta=0.0)
    assert p.value is None and p.margin > 0
    # every continuation offered to the model is a date that occurs in the document, or null
    doc_values = {lattice.dates([BE_NO_ANSWER])[i]["value"] for i in range(len(lattice.dates([BE_NO_ANSWER])))}
    offered = {c.strip().strip('"') for c in be.calls[0][2][1:]}
    assert offered == {pointer.ddmmyyyy(v) for v in doc_values}


def test_prompt_spike8a_verbatim():
    t, pid = pointer.template("answer_date", "de", "spike8a")
    assert t.startswith("Hier ist ein Dokument eines Schweizer Kantonsparlaments zu einer Interpellation.") and pid.startswith(
        "de/"
    )
    for lang in ("de", "fr", "it"):
        assert "{doc}" in pointer.template("answer_date", lang)[0]


def test_fit_theta_synthetic():
    m = [5.0, 6.0, 7.0, -3.0, -4.0]
    y = [True, True, True, False, False]
    th, acc = calibrate.fit_theta(m, y)
    assert acc == 1.0 and -3.0 < th < 5.0 and th == pytest.approx(1.0)
    c = calibrate.calibrate("b", "p", list(range(5)), m, y)
    assert c.auroc == 1.0 and c.loo["correct"] == 5


def test_spike_replay_reproduces_f2_and_shape():
    """The repo's calibrate.py reproduces spikes/inversions F2 and round-8 SHAPE (a) from the vendored margins."""
    if not (DATA / "convert" / "spike_margins.json").exists():
        pytest.skip("vendored spike margins missing")
    from eval import replay_spikes

    r = replay_spikes.main()
    f = r["f2"]["final|chat_plain"]
    assert f["auroc"] == 1.0 and f["loo_correct"] == 20 and round(f["theta"], 1) == -32.3
    assert round(r["f2"]["final_dwq|chat_null"]["theta"], 1) == -14.8
    s = r["shape"]["a_json_null"]
    assert s["BE_auroc"] == 1.0 and s["BE_loo"]["correct"] == 20 and s["ctrl_kept_correct"] == 10 and round(s["theta"], 1) == 4.9
    n = r["naive"]["round7_dwq_8b|null"]
    assert n["invented_on_null_docs"] == 14 and n["invented_passing_receipt_check"] == 10 and n["fabricated"] == 2
    assert r["naive"]["round7_dwq_8b|plain"]["invented_on_null_docs"] == 15
    assert (RESULTS / "convert" / "spike_replay.json").exists()


# ------------------------------------------------------------------------------------------------ cascade
def test_cascade_routes():
    # rules decide: no model call
    be = FakeBackend()
    out = cascade.answer_date(dict(pages=[BE_ANSWER], lang="de"), be, theta=0.0)
    assert out["route"] == "rule" and out["value"] == "2025-10-15" and not be.calls
    # rules null on explicit empty template: no model call either
    out = cascade.answer_date(dict(pages=[BE_NO_ANSWER], lang="de"), be, theta=0.0)
    assert out["value"] is None and out["null_reason"] == "not_in_document" and out["route"] == "rule" and not be.calls
    # residue goes to the pointer
    doc = dict(pages=["Ein Bericht.\nAm 3. März 2021 wurde beraten.\n"], lang="de")
    out = cascade.answer_date(doc, FakeBackend(lp_null=-30.0, favour="03.03.2021"), theta=0.0)
    assert out["route"] == "apertus" and out["value"] == "2021-03-03" and out["residue"]
    out = cascade.answer_date(doc, FakeBackend(lp_null=0.0), theta=0.0)
    assert out["value"] is None and out["null_reason"] == "not_in_document"
    # metadata route only when the event date is printed in the document
    out = cascade.answer_date(dict(pages=[BE_ANSWER], lang="de", opd_answer_dates=["2025-10-15"]), None)
    assert out["route"] == "metadata"
    out = cascade.answer_date(dict(pages=[BE_NO_ANSWER], lang="de", opd_answer_dates=["2024-06-26"]), None)
    assert out["route"] == "rule" and out["value"] is None


def test_cascade_typed_nulls():
    assert cascade.answer_date(dict(pages=[""], image_only=True), None)["null_reason"] == "image_only"
    assert (
        cascade.answer_date(dict(pages=["cf. réponse orale du Conseil d'Etat / s. mündliche Antwort des Staatsrats"]), None)[
            "null_reason"
        ]
        == "oral"
    )


# ------------------------------------------------------------------------------------------------ scoring
def test_outcomes_and_naive_parse():
    assert outcome(None, None, set()) == "correct_null"
    assert outcome("2024-03-19", None, {"2024-03-19"}) == "misattributed"
    assert outcome("2024-04-23", None, {"2024-03-19"}) == "fabricated"
    assert outcome("2023-03-08", "2023-03-07", set(), ["2023-03-08"], strict=False) == "correct"
    s = summarise(
        [dict(cell="x", pred=None, gold=None, doc_dates=[]), dict(cell="x", pred="2024-01-01", gold=None, doc_dates=[])]
    )
    assert s["x"]["invented_on_null"] == 1 and s["ALL"]["n"] == 2
    o = naive_baseline.parse(
        '```json\n{"antwort_datum": "2024-04-23", "rrb_nr": "2024-28", "beleg": "RRB-Nr. 2024-28 vom 23.04.2024"}\n```'
    )
    assert naive_baseline.to_iso(o["antwort_datum"]) == "2024-04-23"
    assert not naive_baseline.receipt_ok(o, BE_NO_ANSWER)  # the quote does not exist in the document
    o2 = {"antwort_datum": "2024-03-19", "beleg": "Letzte Bearbeitung: 19.03.2024"}
    assert naive_baseline.receipt_ok(o2, BE_NO_ANSWER)  # …but a footer quote passes the naive receipt check


def test_dev_labels_disjoint_from_heldout():
    p = DATA / "gold" / "heldout_docs.jsonl"
    if not p.exists():
        pytest.skip("held-out not drawn")
    dev = json.load(open(DATA / "gold" / "dev_ids.json"))["ids"]
    devset = {i for v in dev.values() for i in v}
    held = [json.loads(line) for line in open(p)]
    assert not devset & {h["doc_id"] for h in held}
    affs = [h["affair_id"] for h in held if h.get("affair_id")]
    assert len(affs) == len(set(affs)), "one document per affair"
