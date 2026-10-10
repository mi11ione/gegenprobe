"""Round-4 converter CLI: strict --affair-type, --queue-nulls with OPD's document category, the public schema exports."""
import json

import pytest

from gegenprobe import __main__ as cli
from gegenprobe.convert import affair_types, batch

# an answer letter in the layout U1 met (Collombey-Muraz 868821; names and text invented): the date is printed first, no
# answer heading, so the frozen rules leave a typed null and doc_role is `other`
LETTER = [
    "Ville-Exemple, le 15 juillet 2019\n\nCourrier A\n\nMonsieur\nJean Exemple\nRue de l'Exemple 1\n1000 Ville-Exemple\n\n"
    "Votre question écrite datée du 12.05.2019 intitulée :\nRéseau de pistes cyclables\n\nMonsieur le Conseiller général,\n"
    "Dans le délai prévu par le règlement du Conseil général, nous donnons suite à votre question écrite mentionnée en "
    "titre.\nAprès examen de vos interrogations par le Conseil municipal, nous y répondons comme suit :\n"
    + "Texte de la réponse. " * 60,
    "En espérant avoir répondu à vos questions, veuillez agréer nos salutations les meilleures.\n\nLe Président\n",
]


@pytest.mark.parametrize("raw,want", [
    ("Interpellation", "Interpellation"), ("interpellation", "Interpellation"), ("Interpellanza", "Interpellation"),
    ("Question écrite", "Question"), ("question", "Question"), ("Written question", "Question"), ("Anfrage", "Question"),
    ("Schriftliche Anfrage", "Question"), ("question_time", "Question time"), ("Question time", "Question time"),
    ("Heure des questions", "Question time"), ("  MOTION ", "Motion"), ("Postulat", "Postulate"),
    ("Government affairs", "Government affairs"), ("unknown", None), ("", None), (None, None),
])
def test_affair_type_aliases_normalise_to_opd_names(raw, want):
    assert affair_types.normalize(raw) == want


def test_every_vocabulary_key_is_accepted():
    for key in affair_types.KEYS:
        affair_types.normalize(key)


def test_unknown_affair_type_is_an_error_not_silently_ignored(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["convert", "x.pdf", "--affair-type", "Questionnaire"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "unknown affair type 'Questionnaire'" in err and "question_time" in err


def test_normalised_type_reaches_the_frozen_rule():
    """'Question écrite' used to fall through to present_unanchored; now it is OPD's 'Question' -> not_applicable."""
    r = batch.convert_pages(LETTER, sha="0" * 64, extractor="pdftotext", image_only=False,
                            inp=dict(affair_type=affair_types.normalize("Question écrite")))
    assert r["fields"]["recommendation"]["null_reason"] == "not_applicable"


def test_batch_unknown_affair_type_names_the_line(tmp_path, capsys):
    f = tmp_path / "in.tsv"
    f.write_text("url\taffair_type\nhttps://example.org/a.pdf\tQuestion écrite\nhttps://example.org/b.pdf\tFoo\n")
    with pytest.raises(affair_types.UnknownAffairType, match="line 3"):
        batch.read_inputs(str(f))
    assert cli.main(["convert", "--batch", str(f)]) == 2
    assert "line 3" in capsys.readouterr().err
    f.write_text("url\taffair_type\tcategory_harmonized\nhttps://example.org/a.pdf\tQuestion écrite\tresponse_text\n")
    row = batch.read_inputs(str(f))[0]
    assert row["affair_type"] == "Question" and row["doc_category"] == "response_text"


@pytest.mark.parametrize("queue_nulls,category,flagged", [
    (False, "response_text", False),  # default unchanged: the null stays unattended
    (True, "", False),                # no evidence that this is an answer
    (True, "response_text", True),    # OPD's harmonised category
    (True, "Réponses aux questions écrites", True),  # OPD's category label (census answer-document pattern)
    (True, "Procès-verbal", False),
])
def test_queue_nulls_on_answer_documents(queue_nulls, category, flagged):
    r = batch.convert_pages(LETTER, sha="0" * 64, extractor="pdftotext", image_only=False,
                            inp=dict(opd_doc_id="1", body="6152", doc_category=category), queue_nulls=queue_nulls)
    f = r["fields"]["answer_date"]
    assert f["value"] is None and r["doc_role"]["value"] == "other"
    assert f["candidates"][0]["value"] == "2019-07-15"  # the right date is first, for the reviewer
    assert r["needs_review"] is flagged and bool(f.get("needs_review")) is flagged
    if flagged:
        assert "rules-only null on an answer document" in r["review_reasons"][0]["reason"]


def test_queue_nulls_rows_reach_the_review_queue(tmp_path, monkeypatch):
    rows = tmp_path / "rows.jsonl"
    for cat in ("response_text", ""):
        r = batch.convert_pages(LETTER, sha="0" * 64, extractor="pdftotext", image_only=False,
                                inp=dict(opd_doc_id=cat or "2", body="6152", doc_category=cat), queue_nulls=True)
        with open(rows, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    q = tmp_path / "queue.jsonl"
    assert batch.write_queue(str(rows), str(q)) == 1
    row = json.loads(q.read_text())
    assert row["fields"]["answer_date"]["candidates"][0]["value"] == "2019-07-15"


def test_public_schema_exports():
    from gegenprobe.schema import public

    for name in public.__all__:
        assert hasattr(public, name), name
    assert {"DocExtraction", "Affair", "Document", "TypedNull", "DateValue", "NullReason"} <= set(public.__all__)
    s = public.json_schema("doc_extraction")
    assert s["$id"].endswith("/results/schema/doc_extraction.schema.json") and s["version"] == public.SCHEMA_VERSION
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    from gegenprobe.paths import RESULTS
    assert json.loads((RESULTS / "schema" / "doc_extraction.schema.json").read_text()) == json.loads(json.dumps(s))


def test_census_replay_explains_gap_prime(monkeypatch, capsys):
    from gegenprobe.census import replay

    monkeypatch.setattr(replay, "replay", lambda data: ([], 0.0))
    monkeypatch.setattr("sys.argv", ["replay"])
    assert replay.main() == 0
    out = capsys.readouterr().out
    assert "gap' 16,157" in out and "gap' = the gap after the in-corpus agenda join" in out
