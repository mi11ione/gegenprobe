from gegenprobe.schema import schema_v0_1 as S
from gegenprobe.validate.spans import recheck_affair
from gegenprobe.virtual import agenda, classify, derive, minutes, pointer4

AGENDA = """Ville de Bulle

10 mai 2017

Convocation
Le Conseil général de la Ville de Bulle
est convoqué en séance
les lundi 29 et 30 mai 2017 à 19h30
Ordre du jour
1. Approbation du procès-verbal de la séance du 12 décembre 2016
2. Ratification du dépassement de crédit relatif aux travaux d’assainissement de la grande salle
3.

Décision de transmission du postulat de Madame Camille Lavalette demandant le ramassage des déchets organiques
4. Election du/de la Président/e du Conseil général
5. Divers
AU NOM DU CONSEIL GENERAL
"""

MINUTES = """PROCES-VERBAL DE LA SEANCE DU CONSEIL GENERAL
le 29 mai 2017 – de 19h30 à 22h10
Ordre du jour
1. Approbation du procès-verbal de la séance du 12 décembre 2016
2. Ratification du dépassement de crédit relatif aux travaux d’assainissement de la grande salle
3. Décision de transmission du postulat de Madame Camille Lavalette demandant le ramassage
4. Election du/de la Président/e du Conseil général
5. Divers

Point 1 - Approbation du procès-verbal de la séance du 12 décembre 2016
Au vote, le Conseil général accepte à l’unanimité le procès-verbal.

""" + "Discussion. " * 300 + """
Point 2 - Ratification du dépassement de crédit relatif aux travaux d’assainissement de la grande salle
Le débat est ouvert. """ + "Intervention. " * 300 + """
Au vote, le Conseil général accepte par 46 OUI et 2 ABSTENTIONS le dépassement de crédit de Fr. 120'000.-.

Point 3 - Transmission du postulat de Madame Camille Lavalette demandant le ramassage
""" + "Débat. " * 300 + """
Au vote, le Conseil général refuse par 20 OUI et 26 NON la transmission du postulat.

Point 4 - Election du/de la Président/e du Conseil général
Madame X est élue.
"""


def test_agenda_items_and_meeting_date():
    a = agenda.parse([AGENDA])
    assert [i.no for i in a.items] == ["1", "2", "3", "4", "5"]
    assert a.items[2].title.startswith("Décision de transmission du postulat")  # number-only line, title after a blank
    assert a.meeting_date["value"] == "2017-05-29" and a.meeting_date["rule"] == "first_of_two_days"
    for it in a.items:
        assert AGENDA[it.char_start:it.char_end].split("\n")[0] in it.title


def test_minutes_sections_skip_the_listing_and_read_the_final_vote():
    a = agenda.parse([AGENDA])
    secs = minutes.sections(MINUTES, a.items)
    assert MINUTES[secs[1].start:].startswith("Point 2")
    d2 = minutes.decision(MINUTES, secs[1])
    assert d2["outcome"] == "adopted" and "46 OUI" in d2["quote"]
    d3 = minutes.decision(MINUTES, secs[2])
    assert d3["outcome"] == "rejected"


def test_type_rules():
    assert classify.item_type("Décision de transmission du postulat de M. X")["value"] == "postulate"
    assert classify.item_type("Détermination du Conseil communal sur la proposition de Mme Y")["value"] == "motion"
    assert classify.item_type("Approbation du procès-verbal de la séance du 1 mai")["value"] == "approval_decision"
    assert classify.item_type("Allocation pour la piscine") is None


def test_derive_rules_only_is_schema_valid_with_spans():
    out = derive.derive(dict(key="2125", name="Bulle", languages=["fr"]), dict(doc_id="opd:1"), [AGENDA],
                        dict(doc_id="opd:2"), [MINUTES])
    pages = {"opd:1": [AGENDA], "opd:2": [MINUTES]}
    assert len(out["affairs"]) == 5
    a2 = out["affairs"][1]
    assert a2.ref.virtual and a2.ref.number == "V 2017-05-29 - 2" and a2.ref.derived_from == "opd:1"
    assert isinstance(a2.decision, S.DecisionValue) and a2.decision.value == "adopted"
    for aff in out["affairs"]:
        bad = [(p, c) for p, c in recheck_affair(aff, pages) if not c.ok]
        assert not bad, bad
    assert out["affairs"][3].decision.null_reason == "not_applicable"      # election
    assert out["affairs"][2].decision.value == "rejected"


class Fake:
    build = "fake"

    def score(self, user, prefix, conts):
        return [-1.0 if c == " null" else (-0.5 if "accepté" in c else -9.0) for c in conts]


def test_pointer_is_closed_set():
    c = pointer4.choose(Fake(), "decision", "fr", "texte", classify.DECISION_LABELS["fr"], theta=0.0, title="t")
    assert c["value"] == "adopted" and c["candidates"] == 5
    c2 = pointer4.choose(Fake(), "decision", "fr", "texte", classify.DECISION_LABELS["fr"], theta=-5.0, title="t")
    assert c2["value"] is None  # margin > θ -> null


def test_scorer_matches_items_and_counts_invented_decisions(tmp_path, monkeypatch):
    import json

    from eval.gold4 import run_p4
    out, data = tmp_path / "out", tmp_path / "data"
    (data / "gold4").mkdir(parents=True)
    out.mkdir()
    rows = [dict(meeting="2017-05-29", arm="rules_only", no="1", title="Approbation du procès-verbal", type="approval_decision",
                 decision="adopted", decision_route="rule"),
            dict(meeting="2017-05-29", arm="rules_only", no="2", title="Divers", type="miscellaneous", decision="adopted",
                 decision_route="rule"),
            dict(meeting="2017-05-29", arm="rules_only", no="9", title="Extra item", type="question", decision=None,
                 decision_route="rule")]
    (out / "p4_dev__none.json").write_text(json.dumps(dict(rows=rows)))
    gold = [dict(meeting="2017-05-29", no="1", title_quote="Approbation du procès-verbal", type="approval_decision",
                 decision="adopted"),
            dict(meeting="2017-05-29", no="2", title_quote="Divers", type="miscellaneous", decision="not_applicable")]
    (data / "gold4" / "p4_dev_labels.jsonl").write_text("\n".join(json.dumps(g) for g in gold))
    monkeypatch.setattr(run_p4, "OUT", out)
    monkeypatch.setattr(run_p4, "DATA", data)
    s = run_p4.score("dev", "none")["arms"]["rules_only"]
    assert s["segmentation_recall"][:2] == [2, 2] and s["segmentation_precision"][:2] == [2, 3]
    assert s["decision_accuracy"][:2] == [1, 1] and s["invented_decisions"][:2] == [1, 1]
