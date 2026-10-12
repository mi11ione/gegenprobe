"""Document parts (gegenprobe.convert.parts, gegenprobe.schema.v0_2_parts): the rules on synthetic inputs, the committed
detections against the cached PDFs, and the overlay on the converter's v0.2 records (nothing else of a record changes)."""
import json
import typing

import pytest

from gegenprobe.convert import parts as P
from gegenprobe.paths import PDF_CACHE
from gegenprobe.schema import role_consistency as RC
from gegenprobe.schema import v0_2_all as V
from gegenprobe.schema import v0_2_parts as VP
from gegenprobe.schema import v0_2_qa as QA
from gegenprobe.schema.p8_v0_2 import OUT, schema_module


@pytest.fixture(scope="module")
def base():
    return V.render()


@pytest.fixture(scope="module")
def over():
    return VP.render()


@pytest.fixture(scope="module")
def val(over):
    return json.loads(over["validation_all.json"])


# ----------------------------------------------------------------------------------------------------------- rules
LAYOUT = """Tabelle 1: Kurse
   Anno          Corsi       Corsi        Corsi
                proposti   confermati   annullati
   2020/21        1'220        722          498
   2021/22        1'592        931          661
   2022/23        1'437        892          545

Der Regierungsrat hat  die Frage  geprüft und  kommt zum Schluss.
"""


def test_table_block_from_aligned_columns():
    blocks = P.table_blocks(LAYOUT)
    assert len(blocks) == 1
    b = blocks[0]
    assert b["rows"] == 5 and b["columns"] == 4 and (b["line_from"], b["line_to"]) == (1, 5)


def test_prose_with_double_spaces_is_not_a_table():
    text = "\n".join(["Dies ist  ein Satz  mit  doppelten Leerzeichen der weitergeht und weitergeht."] * 2 + [""] * 3)
    assert P.table_blocks(text) == []


def test_budget_and_signature_kinds():
    budget = ("Konto                         RE 2023      BU 2025     BU 2026\n"
              "3118 Anschaffung              7’336’962    5’559’000   6’451’000\n"
              "3133 Informatik               24’703       492’799     6’319’349\n"
              "Total                         7’361’665    7’810’853   11’070’673\n")
    b = P.table_blocks(budget)[0]
    assert P._kind_of_block(b, budget.split("\n")) == "budget_table"
    names = ("Ballif Laurent          Courdesse Régis          Freymond Isabelle\n"
             "Bendahan Samuel         Cretegny Gérald          Gander Hugues\n"
             "Berthoud Alexandre      Cretegny Laurence        Jaquier Rémy\n")
    b = P.table_blocks(names)[0]
    assert P._kind_of_block(b, names.split("\n")) == "signature"


def test_annex_headings_lists_and_references():
    pages = ["Antwort\nDie Zahlen stehen im Anhang 1 bis 4.\nDie Anlagen genehmigt.\n",
             "Anhang 1: Übersicht Bundesgesetz\n1 2 3\n",
             "Text\nmehr Text\nnoch mehr\n\nAnhang 2\nZahlen\n",
             "Allegato\nfoto\n"]
    sig = P.annex_signals(pages)
    assert [(h["page"], h["label"]) for h in sig["headings"]] == [(2, "Anhang 1"), (3, "Anhang 2"), (4, "Allegato")]
    assert sig["references"] and sig["references"][0]["page"] == 1
    parts = P.annex_parts(sig, len(pages))
    assert [(p["page_from"], p["page_to"]) for p in parts] == [(2, 2), (3, 3), (4, 4)]
    assert all(p["kind"] == "annex" and len(p["label"]) <= 200 for p in parts)


def test_attachment_list_is_a_signal_and_pages_after_it_an_annex():
    letter = "Brief\n" + "Satz.\n" * 8 + "Beilagen:\n- Bericht\n- Karte\n"
    sig = P.annex_signals([letter])
    assert not sig["headings"] and sig["attachment_lists"] and P.annex_parts(sig, 1) == []
    sig = P.annex_signals([letter, "Bericht\nInhalt\n"])
    assert [(p["page_from"], p["page_to"], p["subtype"]) for p in P.annex_parts(sig, 2)] == [(2, 2, "after_attachment_list")]


def test_word_anlage_and_numbered_list_items_are_not_headings():
    sig = P.annex_signals(["Text\n" * 6 + "Anlage\nAnlagen genehmigt.\nBeilage 1: Bericht\nBeilage 2: Karte\n"])
    assert sig["headings"] == [] and len(sig["attachment_lists"]) == 2


def test_html_tables_and_images():
    html = [None, "<p>Text</p><table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table><img src='x.png'>"]
    det = P.detect_html(html, ["Titel", "Text\na b\n1 2"])
    assert [(p["kind"], p["page_from"]) for p in det["parts"]] == [("image", 2), ("table", 2)]
    assert det["parts"][1]["rows"] == 2 and det["parts"][1]["columns"] == 2


def test_schema_parts_are_valid_document_parts():
    m = schema_module()
    det = dict(parts=[dict(kind="table", page_from=2, page_to=2, label="x" * 300)])
    got = P.schema_parts(det)
    assert len(got[0]["label"]) == 200
    m._v01.DocumentPart.model_validate(got[0])
    assert set(VP.KINDS) <= set(typing.get_args(m._v01.PartKind))


# ----------------------------------------------------------------------------------------------------------- detections
def test_detections_match_the_cached_documents():
    r = VP.check_detections()
    if r["status"] == "SKIP":
        pytest.skip(r["summary"])
    assert r["status"] == "PASS", r["summary"]


def test_detections_write_no_text():
    for line in VP.DETECTIONS.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for p in r["parts"]:
            assert 1 <= p["page_from"] <= p["page_to"] <= r["n_pages"], (r["doc_id"], p)
            assert len(p["label"]) <= 200 and "quote" not in json.dumps(p).replace("quote_sha256", "")
            if p.get("span"):
                assert len(p["span"]["quote_sha256"]) == 64 and p["span"]["char_end"] > p["span"]["char_start"]


def test_known_documents_when_cached():
    rows = VP.load()
    be = next(r for (s, _), r in rows.items() if s == "p3" and r["affair_id"] == 271519 and r["role"] == "answer")
    assert [(p["kind"], p["page_from"], p["page_to"]) for p in be["parts"] if p["kind"] == "annex"] == [
        ("annex", 4, 4), ("annex", 5, 5), ("annex", 6, 6), ("annex", 7, 7)]
    zh = next(r for (s, _), r in rows.items() if s == "p3" and r["affair_id"] == 250883 and r["role"] == "answer")
    assert {p["kind"] for p in zh["parts"]} == {"budget_table"}
    if not (PDF_CACHE / f"{be['sha256']}.pdf").exists():
        pytest.skip("PDF not cached")
    from gegenprobe.schema.v0_2_roles import pages_of
    det = P.detect_pdf(PDF_CACHE / f"{be['sha256']}.pdf", pages_of(be["sha256"])[0])
    assert P.schema_parts(det) == [{k: p[k] for k in ("kind", "page_from", "page_to", "label")} for p in be["parts"]]


# ----------------------------------------------------------------------------------------------------------- overlay
def test_overlay_changes_nothing_else(base, over):
    over_meta = over
    over = VP.render(meta=False)  # the OPD-metadata overlay comes last; tests/test_schema_v0_2_meta.py undoes it
    for k in VP.CONVERTER_SETS:
        got = [QA.strip_qa(VP.strip_parts(json.loads(x))) for x in over[f"{k}_records.jsonl"].splitlines()]
        # after the parts, the Q/A pairing (gegenprobe.schema.v0_2_qa, undone by strip_qa) and the role-consistency
        # repair (gegenprobe.schema.role_consistency) are the only other changes
        assert got == [RC.harmonise(json.loads(x))[0] for x in base[f"{k}_records.jsonl"].splitlines()], k
    fed_in = [RC.harmonise(json.loads(x))[0] for x in VP.FED_IN.read_text(encoding="utf-8").splitlines()]
    assert [VP.strip_parts(json.loads(x)) for x in over[VP.FED_OUT].splitlines()] == fed_in
    b, o = json.loads(base["validation_all.json"]), json.loads(over_meta["validation_all.json"])
    for k in ("n_affairs", "n_valid", "n_invalid", "n_parliaments", "converter_made", "product_records", "samples"):
        assert b[k] == o[k], k


def test_every_examined_document_has_parts_or_a_reason(over, val):
    m = schema_module()
    for k in VP.CONVERTER_SETS + ("fed",):
        name = VP.FED_OUT if k == "fed" else f"{k}_records.jsonl"
        for line in over[name].splitlines():
            rec = json.loads(line)
            m.validate_affair(rec)
            for i, d in enumerate(rec["documents"]):
                r = rec["empty_reasons"].get(f"documents.{i}.parts")
                assert bool(d["parts"]) != bool(r), (k, rec["ref"], i)
                if r:
                    assert r["reason"] == "none_printed" and r["doc"] == d["doc_id"], r
                    assert "does not detect document parts" not in r["evidence"]
    dp = val["document_parts"]
    assert dp["converter_made"]["documents_examined"] == dp["converter_made"]["n_documents"] == 210
    assert dp["fed"]["documents_examined"] == 30 and dp["fed"]["n_valid"] == 15


def test_counts_match_the_records(over, val):
    dp = val["document_parts"]
    total = 0
    for k in VP.CONVERTER_SETS:
        recs = [json.loads(x) for x in over[f"{k}_records.jsonl"].splitlines()]
        carrying = sum(any(d["parts"] for d in r["documents"]) for r in recs)
        assert dp["sets"][k]["records_carrying"]["any"] == carrying
        for kind in VP.KINDS:
            n = sum(any(p["kind"] == kind for d in r["documents"] for p in d["parts"]) for r in recs)
            assert dp["sets"][k]["records_carrying"][kind] == n, (k, kind)
        total += carrying
    assert dp["converter_made"]["records_carrying"]["any"] == total
    # the converter's records carry parts (0 of 105 before)
    assert total >= 50 and all(dp["converter_made"]["records_carrying"][k] > 0 for k in VP.KINDS)


def test_samples_carry_the_overlay(over, val):
    for p in val["samples"]:
        rec = json.loads((OUT.parents[2] / p).read_text(encoding="utf-8"))
        assert not any("does not detect document parts" in r["evidence"] for r in rec["empty_reasons"].values())
