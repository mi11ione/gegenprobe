"""The converter's role rules (gegenprobe.convert.roles) on printed forms, and their exploratory score
against the P8 gold (eval.converter_roles): split rule, frozen held-out rules, committed files."""
import hashlib
import json

import pytest

from eval import converter_roles as CR
from gegenprobe.convert import roles as R


PROSE = ("Die Begründung folgt den bisherigen Vorstössen und den Berichten der Verwaltung zu diesem Thema. " * 8 + "\n")


def _roles(x):
    return sorted((a["name"]["value"], a["role"], a["kind"]) for a in x["actors"])


def test_bern_form_table_gives_joint_authors_and_lodged_date():
    page = ("Parlamentarischer Vorstoss\nVorstossart:\nInterpellation\n\nEingereicht am:\n\n08.12.2021\n\n"
            "Fraktionsvorstoss:\nEingereicht von:\n\nNein\nNein\nRuchti (Seewil, SVP) (Sprecher/in)\nGerber (Schüpfen, "
            "Die Mitte)\n0\n\nWeitere Unterschriften:\nDringlichkeit verlangt:\n\nNein\n\nTitel des Vorstosses\n"
            "Der Regierungsrat wird gebeten, die folgenden Fragen zu beantworten und die Antworten zu begründen.\n")
    x = R.extract([page], None, "BE")
    assert _roles(x) == [("Gerber", "joint_author", "person"), ("Ruchti", "joint_author", "person")]
    d = next(d for d in x["dates"] if d["role"] == "lodged")
    assert d["value"] == "2021-12-08" and page[d["char_start"]:d["char_end"]] == "08.12.2021"
    assert d["quote_sha256"] == hashlib.sha256(b"08.12.2021").hexdigest()
    assert x["instrument"]["named"]["value"] == "interpellation" and x["instrument"]["function"]["value"] == "questions"


def test_graubuenden_heading_and_signatures_give_first_and_co_signatories():
    page = ("GROSSER RAT\nJunisession 2026\n\n2026-66\n\nAnfrage Said Bucher betreffend Stellung der Hausärzte\n"
            "Das Gesundheitsleitbild zeigt verschiedene Handlungsfelder auf. Die Unterzeichnenden fragen an:\n"
            "1. Wie stellt die Regierung die Versorgung sicher?\n" + PROSE + "Chur, 17. Juni 2026\n"
            "Said Bucher, Rutishauser, Collenberg, Bachmann,\nBardill, Zanetti (Sent), Zindel\n")
    x = R.extract([page], None, "GR")
    roles = {n: r for n, r, _ in _roles(x)}
    assert roles["Said Bucher"] == "first_signatory" and roles["Zindel"] == "co_signatory" and roles["Zanetti"] == "co_signatory"
    assert len(roles) == 7
    assert ("2026-06-17", "signed") in {(d["value"], d["role"]) for d in x["dates"]}


def test_fribourg_numbered_heading_and_et_consorts_in_the_answer():
    q = ("Motion 2014-GC-210\n\nLosey Michel, Badoud Antoinette\nModification de la répartition de l'impôt\n"
         "Cosignataires : 12\n\nRéception au SGC : 16.12.14\n\nDépôt et développement\nNous demandons au Conseil "
         "d'Etat de modifier la loi sur les impôts communaux pour que la répartition soit plus équitable entre les "
         "communes et que le service cantonal des contributions en soit chargé.\n")
    x = R.extract([q], None, "FR")
    assert _roles(x) == [("Badoud Antoinette", "joint_author", "person"), ("Losey Michel", "joint_author", "person")]
    assert ("2014-12-16", "received") in {(d["value"], d["role"]) for d in x["dates"]}
    a = ["Réponse de la Municipalité à l'interpellation de M. Valéry Beaud et consorts déposée le 29 août 2023\n"]
    y = R.extract(["Interpellation\nLes politiques publiques\n" + PROSE + "Merci.\n\n28 août 2023\nValéry Beaud\n\n"
                   "Feryel Kilani\n"], a, "5586")
    assert dict((n, r) for n, r, _ in _roles(y)) == {"Valéry Beaud": "first_signatory", "Feryel Kilani": "co_signatory"}


def test_group_with_spokespersons():
    q = ("Stadt Luzern\nGrosser Stadtrat\nInterpellation 133\nSicherheit von Sexarbeitenden\n"
         "Zoé Stehlin und Christoph Landolt namens der SP/JUSO-Fraktion vom 27. Oktober 2025\n")
    x = R.extract([q], None, "1061")
    got = {(a["name"]["value"], a["role"]) for a in x["actors"]}
    assert ("SP/JUSO-Fraktion", "sole_author") in got and ("Zoé Stehlin", "spokesperson") in got
    assert all(a.get("on_behalf_of") == "SP/JUSO-Fraktion" for a in x["actors"] if a["role"] == "spokesperson")


def test_no_author_printed_gives_no_actor():
    x = R.extract(["Interpellation\nDie Regierung wird gebeten, die folgenden Fragen zu beantworten.\n"], None, "ZH")
    assert x["actors"] == []


def test_language_of_text_by_paragraph_profile():
    de = ("Der Regierungsrat wird beauftragt, dem Kantonsrat eine Vorlage zu unterbreiten, mit der die Gemeinden bei "
          "der Finanzierung der familienergänzenden Kinderbetreuung unterstützt werden und die Beiträge des Kantons "
          "an die Kosten nicht gekürzt werden.")
    fr = ("Le Conseil d'Etat est chargé de présenter au Grand Conseil un projet de loi qui permette aux communes de "
          "financer les structures d'accueil de la petite enfance et qui ne réduise pas la participation du canton "
          "aux frais des familles.")
    it = ("Il Municipio è invitato a presentare al Consiglio comunale un messaggio per sostenere le famiglie con un "
          "contributo per ogni figlio nato, anche nella fase della adozione, e per garantire che la città sia "
          "attrattiva per le giovani coppie della regione che sono in difficoltà con i costi del alloggio.")
    assert R.language_of_text([de]) == ["de"] and R.language_of_text([fr]) == ["fr"] and R.language_of_text([it]) == ["it"]
    assert R.language_of_text([de + "\n\n" + fr]) in (["de", "fr"], ["fr", "de"])
    assert R.language_of_text(["   ", "1 2 3"]) == []


def test_instrument_mapping_per_body_and_unmapped_is_other():
    assert R.instrument(["Auftrag Sgier betreffend Bargeld\nDie Regierung wird beauftragt ...\n"], "GR")["function"]["value"] \
        == "mandate"
    assert R.instrument(["Anzug betreffend Verkehr\nDie Unterzeichneten bitten ...\n"], "BS")["function"]["value"] \
        == "examine_report"
    x = R.instrument(["Auftrag betreffend Bargeld\nDie Regierung wird beauftragt ...\n"], "ZH")
    assert x["named"]["value"] == "other" and x["function"]["value"] == "other"
    assert x["function"]["rule"] == "instrument_function:unmapped"
    assert R.instrument(["Der Regierungsrat wird gebeten ...\n"], "ZH") is None


def test_spans_point_at_the_printed_name():
    page = "Stadt Zürich\nGemeinderat\n\nMotion\n\nvon Jehuda Spielman (FDP)\nund Sandra Gallizzi (EVP)\n\nDer Stadtrat ...\n"
    x = R.extract([page], None, "261")
    for a in x["actors"]:
        v = a["name"]
        assert page[v["char_start"]:v["char_end"]] == v["value"] and v["page"] == 1 and v["doc"] == "question"
        assert v["quote_sha256"] == hashlib.sha256(v["value"].encode()).hexdigest()


def test_split_is_the_written_rule():
    sp = CR.split()
    assert sorted(k for k, v in sp.items() if v == "held_out") == ["351", "5192", "TG", "VD", "VS"]
    order = sorted(CR.PARLIAMENTS, key=lambda k: hashlib.sha256((CR.SPLIT_SALT + k).encode()).hexdigest())
    assert set(order[:5]) == {k for k, v in sp.items() if v == "held_out"}


def test_frozen_rules_are_the_scored_bytes():
    assert hashlib.sha256(CR.FROZEN.read_bytes()).hexdigest() == CR.FROZEN_SHA256
    res = json.loads((CR.OUT / "converter_roles.json").read_text(encoding="utf-8"))
    assert res["frozen"]["rules_sha256"] == CR.FROZEN_SHA256 and res["frozen"]["rules_version"] == "roles-1"
    assert res["frozen"]["held_out"]["parliaments"] == ["351", "5192", "TG", "VD", "VS"]
    assert res["post_hoc"]["rules_version"] == R.RULES_VERSION
    assert "exploratory" in res["status"]


def test_wilson():
    assert CR.wilson(0, 0) is None
    lo, hi = CR.wilson(60, 60)
    assert hi == 1.0 and 0.93 < lo < 0.95


def test_committed_scores_are_current_when_texts_cached():
    from gegenprobe.paths import TEXT_CACHE

    affs = [json.loads(x) for x in (CR.D8 / "p8_affairs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if not all(any(TEXT_CACHE.glob(f"{d['sha256']}.*.json")) for a in affs for d in a["docs"]):
        pytest.skip("P8 document texts not cached (WORK/text)")
    files = CR.render()
    for name, text in files.items():
        assert (CR.OUT / name).read_text(encoding="utf-8") == text, f"run python -m eval.converter_roles write ({name})"
