"""`python -m gegenprobe affair` (gegenprobe/affair_cli.py), offline: OPD rows from fixtures (local exports, a
GP_EXPORTS_DIR mirror, a saved slice), documents replaced by cached synthetic texts. No network, no model."""
import gzip
import json
import sys
import types

import pytest

import gegenprobe.convert as convert_pkg
from gegenprobe import affair_cli as AC
from gegenprobe import net, pdftext
from gegenprobe.schema import v0_2_roles
from gegenprobe.schema.p8_v0_2 import schema_module

AFFAIR = {
    "id": 990001, "body_key": "BE", "number": "2021.RRGR.388", "external_id": "x", "title_de": "Nachhaltige Waldpflege",
    "title_fr": None, "title_it": None, "type_name_de": "Interpellation", "type_name_fr": None, "type_name_it": None,
    "type_harmonized_en": "Interpellation", "type_harmonized_id": 8, "state_name_de": None, "state_name_fr": None,
    "state_name_harmonized_id": None, "begin_date": "2021-12-08T00:00:00", "end_date": None,
}
EVENTS = [
    {"id": 10, "affair_id": 990001, "body_key": "BE", "date": "2021-12-08T00:00:00", "title_de": "Eingereicht",
     "title_fr": None, "title_it": None, "title_harmonized_id": 1, "actor_de": None, "position": 1},
    {"id": 11, "affair_id": 990001, "body_key": "BE", "date": "2022-05-18T00:00:00", "title_de": "Beantwortet",
     "title_fr": None, "title_it": None, "title_harmonized_id": 6, "actor_de": "Regierung", "position": 2},
]
CONTRIBUTORS = [
    {"id": 5, "affair_id": 990001, "body_key": "BE", "person_id": 7, "group_id": None, "type": "person",
     "fullname": "Ruchti Fritz", "firstname": "Fritz", "lastname": "Ruchti", "role_de": "Urheber", "role_fr": None,
     "role_it": None, "role_harmonized": "author", "party_harmonized_de": "SVP", "position": 1},
    {"id": 6, "affair_id": 1234, "body_key": "BE", "person_id": 8, "group_id": None, "type": "person",
     "fullname": "Gerber Anna", "firstname": "Anna", "lastname": "Gerber", "role_harmonized": "author", "position": 1},
]
# OPD docs export rows (with text) and their census.scan metadata rows
DOC_ROWS = [
    {"id": 501, "body_key": "BE", "affair_id": 990001, "name": "Vorstoss-de", "language": "de",
     "url": "https://example.org/q.pdf", "text": "Interpellation " + "Wald " * 600},
    {"id": 502, "body_key": "BE", "affair_id": 990001, "name": "RRB-18.05.2022-de", "language": "de",
     "url": "https://example.org/a.pdf", "text": "Antwort des Regierungsrates " + "Wald " * 600},
    {"id": 503, "body_key": "BE", "affair_id": 990001, "name": "Vortrag", "language": "de",
     "url": "https://example.org/r.pdf", "text": "Vortrag " * 600},
]
PARA = ("Der Wald im Kanton Bern ist für die Bevölkerung und die Natur von grosser Bedeutung, und die Bewirtschaftung "
        "muss deshalb nachhaltig sein. Wir bitten den Regierungsrat, die folgenden Fragen zu beantworten.\n\n")
Q = [f"Interpellation 2021.RRGR.388\nEingereicht von: Fritz Ruchti (SVP)\nEingereicht am: 8. Dezember 2021\n\n{PARA}"
     "1. Wie wird der Wald gepflegt?\n"]
A = [f"Antwort des Regierungsrates\nRRB-Nr.: 879/2022 vom 18. Mai 2022\nGeschäftsnummer: 2021.RRGR.388\n\n{PARA}"
     "Der Regierungsrat beantwortet die Interpellation wie folgt.\n"]
SHA = {"question": "1" * 64, "answer": "2" * 64}


def _gz(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


@pytest.fixture
def texts(tmp_path, monkeypatch):
    """Cached synthetic texts for the two documents; fetch_doc returns them without any request."""
    tc, pc = tmp_path / "text", tmp_path / "pdf"
    tc.mkdir()
    pc.mkdir()
    monkeypatch.setattr(pdftext, "TEXT_CACHE", tc)
    monkeypatch.setattr(pdftext, "PDF_CACHE", pc)
    monkeypatch.setattr(pdftext, "poppler_version", lambda: "test")
    monkeypatch.setattr(v0_2_roles, "TEXT_CACHE", tc)
    monkeypatch.setattr(AC, "PDF_CACHE", pc)
    for role, pages in (("question", Q), ("answer", A)):
        (tc / f"{SHA[role]}.pdftotext-test.json").write_text(json.dumps(
            dict(sha256=SHA[role], extractor="pdftotext-test", pages=pages, image_only=False)))

    def fake_fetch(role, d, timeout=60, tries=2):
        return dict(role=role, doc_id=d["id"], name=d.get("name"), url=d["url"], opd_text_status=d.get("st"),
                    opd_chars=d.get("n"), sha256=SHA[role], pages=1, chars=100, extractor="pdftotext-test",
                    image_only=False)
    monkeypatch.setattr(AC, "fetch_doc", fake_fetch)
    return tc


@pytest.fixture
def no_parts(monkeypatch):
    monkeypatch.delattr(convert_pkg, "parts", raising=False)
    monkeypatch.setitem(sys.modules, "gegenprobe.convert.parts", None)


def _fake_parts(monkeypatch, detect_pdf):
    m = types.ModuleType("gegenprobe.convert.parts")
    m.PARTS_VERSION = "parts-test"
    m.detect_pdf = detect_pdf
    m.schema_parts = lambda det: [dict(kind=p["kind"], page_from=p["page_from"], page_to=p["page_to"],
                                       label=p["label"][:200]) for p in det["parts"]]
    monkeypatch.setitem(sys.modules, "gegenprobe.convert.parts", m)
    monkeypatch.setattr(convert_pkg, "parts", m, raising=False)


def _rows():
    scan_rows = [dict(id=d["id"], b="BE", a=990001, name=d["name"], cat=None, ch=None, lang="de", url=d["url"], st="ok",
                      n=len(d["text"]), fl=[]) for d in DOC_ROWS]
    return dict(affairs={990001: dict(affair=AFFAIR, events=[{k: e[k] for k in e if k not in ("affair_id", "body_key")}
                                                            for e in EVENTS],
                                      contributors=[c for c in CONTRIBUTORS if c["affair_id"] == 990001],
                                      docs=scan_rows)},
                names={"BE": [("Fritz", "Ruchti"), ("Anna", "Gerber")]}, sources={"single_exports": {"source": "test"}})


def _nulls(o, out):
    if isinstance(o, dict):
        if o.get("kind") == "null":
            out.append(o)
        for v in o.values():
            _nulls(v, out)
    elif isinstance(o, list):
        for v in o:
            _nulls(v, out)
    return out


def test_record_validates_with_typed_nulls_and_no_parts_module(texts, no_parts):
    rows = _rows()
    r = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"], sources=rows["sources"])
    assert r["status"] == "ok" and r["schema_version"] == "0.2.0"
    rec = r["record"]
    v = schema_module().validate_affair(rec)  # the v0.2 model accepts it as printed
    assert rec["schema_version"] == "0.2.0" and rec["ref"] == {"body_key": "BE", "number": "2021.RRGR.388",
                                                               "opd_id": 990001, "virtual": False}
    assert [d["doc_id"] for d in rec["documents"]] == ["opd:501", "opd:502"]  # the Vortrag is not paired
    assert all(d["sha256"] in SHA.values() for d in rec["documents"])
    qa = rec["qa"][0]
    assert qa["answer_date"]["value"] == "2022-05-18" and qa["answer_date"]["doc"] == "opd:502"
    assert qa["answering_body"] == {"kind": "null", "null_reason": "not_extracted", "route": "rule",
                                    "evidence": "the answering body is not extracted by converter gegenprobe-0.1.0+affair"}
    assert rec["decision"]["null_reason"] == "not_applicable"  # interpellation: affair_post.finalize
    nulls = _nulls(rec, [])
    assert nulls and all(n.get("null_reason") and n.get("route") and n.get("evidence") for n in nulls)
    assert set(schema_module().empty_fields(v)) == set(rec["empty_reasons"])  # every empty list typed
    for i in range(2):
        assert rec["empty_reasons"][f"documents.{i}.parts"]["reason"] == "not_extracted"
        assert rec["empty_reasons"][f"documents.{i}.parts"]["evidence"].startswith(AC.PARTS_NOT_EXTRACTED)
    assert rec["body"]["name"] == "Bern" and rec["body"]["languages"] == ["de", "fr"]
    assert rec["type"] == {**rec["type"], "harmonised": "interpellation", "opd_harmonised_id": 8}
    assert "gegenprobe.affair_cli (rules_only)" in rec["extraction"]["notes"]
    assert r["needs_review"] is False and r["suggestions"] == {} and r["sources"]["answer_link_status"] == "attached"


def test_parts_hook_present(texts, monkeypatch):
    calls = []

    def detect_pdf(pdf, pages, image_only=False, ocr=False):
        calls.append((pdf.name, image_only, ocr))
        table = dict(kind="table", page_from=1, page_to=1, label="table: 3 rows x 3 columns")
        parts = [table] if pages[0].startswith("Antwort") else []
        return dict(detector="parts-test", parts=parts)
    _fake_parts(monkeypatch, detect_pdf)
    rows = _rows()
    rec = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"])["record"]
    schema_module().validate_affair(rec)
    assert len(calls) == 2
    assert rec["documents"][1]["parts"] == [dict(kind="table", page_from=1, page_to=1, label="table: 3 rows x 3 columns")]
    er = rec["empty_reasons"]
    assert "documents.1.parts" not in er
    assert er["documents.0.parts"]["reason"] == "none_printed" and er["documents.0.parts"]["doc"] == "opd:501"
    assert "parts-test" in er["documents.0.parts"]["evidence"]
    assert "document parts: 1 by gegenprobe.convert.parts parts-test" in rec["extraction"]["notes"]


def test_parts_hook_that_raises_is_typed_not_fatal(texts, monkeypatch):
    def boom(pdf, pages, image_only=False, ocr=False):
        raise RuntimeError("layout failed")
    _fake_parts(monkeypatch, boom)
    rows = _rows()
    rec = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"])["record"]
    er = rec["empty_reasons"]["documents.0.parts"]
    assert er["reason"] == "not_extracted" and "raised RuntimeError: layout failed" in er["evidence"]


def test_detect_parts_absent(no_parts):
    assert AC.detect_parts(["x"], None) == (None, AC.PARTS_NOT_EXTRACTED)


def test_question_type_from_opd_name(texts, no_parts):
    rows = _rows()
    row = rows["affairs"][990001]
    row["affair"] = dict(AFFAIR, type_harmonized_en="Question", type_harmonized_id=12, type_name_de="Schriftliche Anfrage")
    r = AC.build(990001, row, rows["names"]["BE"])
    assert r["record"]["type"]["harmonised"] == "question"
    assert r["changes"][0]["field"] == "type.harmonised" and r["record"]["decision"]["null_reason"] == "not_applicable"


def test_typed_failures(texts, no_parts, monkeypatch):
    rows = _rows()
    with pytest.raises(AC.AffairError) as e:
        AC.build(5, dict(affair=None), [])
    assert e.value.kind == "affair_not_found"
    row = dict(rows["affairs"][990001], docs=[d for d in rows["affairs"][990001]["docs"] if d["id"] == 503])
    with pytest.raises(AC.AffairError) as e:
        AC.build(990001, row, [])
    assert e.value.kind == "no_documents"
    with pytest.raises(AC.AffairError) as e:
        AC.build(990001, rows["affairs"][990001], [], question_doc=777)
    assert e.value.kind == "document_not_in_affair"


def test_fetch_failure_is_typed(monkeypatch):
    from gegenprobe.convert import batch

    def disallowed(url, timeout=60, tries=2):
        raise net.Disallowed(f"{url} (robots.txt disallows this path)", kind="robots_disallowed")
    monkeypatch.setattr(batch, "get_document", disallowed)
    with pytest.raises(AC.AffairError) as e:
        AC.fetch_doc("answer", dict(id=502, url="https://example.org/a.pdf"))
    assert e.value.kind == "robots_disallowed" and "opd:502" in e.value.detail


def test_invalid_record_is_a_typed_failure(texts, no_parts, monkeypatch):
    from gegenprobe.schema import v0_2_all

    real = v0_2_all.with_roles

    def broken(rec, roles, overrides=None):
        out = real(rec, roles, overrides)
        out["empty_reasons"].pop("qa.0.items", None)
        return out
    monkeypatch.setattr(v0_2_all, "with_roles", broken)
    rows = _rows()
    with pytest.raises(AC.AffairError) as e:
        AC.build(990001, rows["affairs"][990001], [])
    assert e.value.kind == "invalid_record"


def test_cli_exit_codes_with_saved_rows(texts, no_parts, tmp_path, capsys):
    f = tmp_path / "rows.json"
    AC.save_rows(_rows(), f)
    assert AC.main(["--opd-affair", "990001", "--rows", str(f), "--schema", "v0.2", "--record-only"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["schema_version"] == "0.2.0" and rec["ref"]["opd_id"] == 990001
    assert AC.main(["--opd-affair", "990001", "--opd-affair", "4", "--rows", str(f)]) == 2
    out = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [x["status"] for x in out] == ["ok", "affair_not_found"]
    assert out[0]["sources"]["slice"].endswith("rows.json")


def test_main_cli_registers_affair(texts, no_parts, tmp_path, capsys):
    from gegenprobe.__main__ import main

    f = tmp_path / "rows.json"
    AC.save_rows(_rows(), f)
    assert main(["affair", "--opd-affair", "990001", "--rows", str(f), "--record-only"]) == 0
    assert json.loads(capsys.readouterr().out)["ref"]["opd_id"] == 990001


def test_read_rows_local_exports(tmp_path, monkeypatch):
    raw, meta = tmp_path / "opd", tmp_path / "docs_meta"
    _gz(raw / "affairs.ndjson.gz", [dict(AFFAIR, id=1), AFFAIR])
    _gz(raw / "events.ndjson.gz", EVENTS + [dict(EVENTS[0], id=99, affair_id=1)])
    _gz(raw / "contributors.ndjson.gz", CONTRIBUTORS)
    (raw / "index.json").write_text(json.dumps({"generated_at": "2026-10-11T04:33:46Z"}))
    _gz(meta / "partA" / "docs_meta.jsonl.gz",
        [dict(id=d["id"], b="BE", a=d["affair_id"], name=d["name"], url=d["url"], st="ok", n=3000) for d in DOC_ROWS]
        + [dict(id=9, b="BE", a=1, name="x", url="u", st="ok", n=1)])
    monkeypatch.setattr(AC, "OPD_RAW", raw)
    monkeypatch.setattr(AC, "DOCS_META", meta)
    r = AC.read_rows([990001], "auto")
    a = r["affairs"][990001]
    assert a["affair"]["number"] == "2021.RRGR.388" and [e["id"] for e in a["events"]] == [10, 11]
    assert [c["id"] for c in a["contributors"]] == [5] and [d["id"] for d in a["docs"]] == [501, 502, 503]
    assert r["names"]["BE"] == [("Anna", "Gerber"), ("Fritz", "Ruchti")]  # the body's office holders, not only authors
    assert r["sources"]["single_exports"] == {"source": "local", "location": "GP_OPD_RAW",
                                              "generated_at": "2026-10-11T04:33:46Z"}


def test_read_rows_from_exports_mirror(tmp_path, monkeypatch):
    """--source exports through GP_EXPORTS_DIR (net.local_exports): the docs export rows go through census.scan."""
    ex = tmp_path / "exports"
    _gz(ex / "affairs.ndjson.gz", [AFFAIR])
    _gz(ex / "events.ndjson.gz", EVENTS)
    _gz(ex / "contributors.ndjson.gz", CONTRIBUTORS)
    _gz(ex / "docs" / "docs_BE.ndjson.gz", DOC_ROWS + [dict(DOC_ROWS[0], id=600, affair_id=5)])
    (ex / "index.json").write_text(json.dumps({"generated_at": "2026-10-11T04:33:46Z", "files": []}))
    monkeypatch.setenv("GP_EXPORTS_DIR", str(ex))
    r = AC.read_rows([990001], "exports")
    docs = r["affairs"][990001]["docs"]
    assert [d["id"] for d in docs] == [501, 502, 503] and docs[0]["st"] == "ok" and docs[0]["n"] > 1500
    assert "text" not in docs[0]
    assert r["sources"]["docs"]["location"].startswith("GP_EXPORTS_DIR")
    picked = AC.pick_docs(docs, "Interpellation")
    assert picked["question"]["id"] == 501 and picked["answer"]["id"] == 502


def test_exports_unreachable_is_typed(monkeypatch):
    def down(url):
        raise net.Disallowed(f"{url} (robots.txt unreachable, fail-closed)", kind="robots_unreachable")
        yield  # pragma: no cover
    monkeypatch.setattr(net, "stream_ndjson_gz", down)
    monkeypatch.setattr(AC, "_index", lambda source: {})
    out = AC.run([990001], source="exports")
    assert out == [dict(opd_affair=990001, status="exports_robots_unreachable", reason=out[0]["reason"])]
    assert "affairs export" in out[0]["reason"]


def test_pick_docs_prefers_p3_band_then_lowest_id():
    rows = [dict(id=3, name="Vorstoss-de", url="u", st="ok", n=3000), dict(id=2, name="Vorstoss-de", url="u", st="ok", n=10),
            dict(id=7, name="RRB-1.1.2022-de", url="u", st="null", n=0), dict(id=8, name="RRB-1.1.2022-fr", url="u",
                                                                             st="ok", n=4000)]
    p = AC.pick_docs(rows, "Interpellation")
    assert p["question"]["id"] == 3 and p["answer"]["id"] == 8
    assert AC.pick_docs(rows, "Interpellation", answer_doc=7)["answer"]["id"] == 7


def test_link_status():
    assert AC.link_status(dict(events=[]), {"answer": dict(st="ok", n=900)}) == "attached"
    assert AC.link_status(dict(events=[]), {"answer": dict(st="null", n=0)}) == "image_only"
    assert AC.link_status(dict(events=EVENTS), {}) == "absent"
    assert AC.link_status(dict(events=EVENTS[:1]), {}) == "not_applicable"


def test_compare_keys_actors_and_dates_by_role_and_value():
    a = dict(dates=[dict(role="submitted", date=dict(kind="value", value="2021-01-01")),
                    dict(role="lodged", date=dict(kind="value", value="2021-01-02", rule="r1"))])
    b = dict(dates=[dict(role="lodged", date=dict(kind="value", value="2021-01-02", rule="r1"))])
    c = AC.compare(a, b)
    assert c["differ"] == [] and c["equal"] == c["compared"] == 4


def test_step_skips_offline(tmp_path):
    r = AC.step(dict(online=False, out=tmp_path))
    assert r["status"] == "SKIP" and "offline" in r["summary"]


def test_step_skips_when_no_source_is_reachable(tmp_path, monkeypatch):
    monkeypatch.setattr(AC, "run", lambda ids, **kw: [dict(opd_affair=i, status="network_error", reason="DNS") for i in ids])
    r = AC.step(dict(online=True, out=tmp_path))
    assert r["status"] == "SKIP" and "no source reachable" in r["summary"]


def test_step_fails_on_an_invalid_record(tmp_path, monkeypatch):
    monkeypatch.setattr(AC, "run", lambda ids, **kw: [dict(opd_affair=i, status="invalid_record", reason="x") for i in ids])
    assert AC.step(dict(online=True, out=tmp_path))["status"] == "FAIL"


def test_step_passes_on_the_committed_samples_offline_replay(tmp_path, monkeypatch):
    """The comparison half of the step: each committed sample, fed back as the command's record, passes its checks."""
    samples = AC._samples()
    assert {s["ref"]["body_key"] for _, s in samples} == {"BE", "6643", "5192"}
    by_id = {s["ref"]["opd_id"]: s for _, s in samples}
    monkeypatch.setattr(AC, "run", lambda ids, **kw: [dict(opd_affair=i, status="ok", record=by_id[i], needs_review=False)
                                                      for i in ids])
    r = AC.step(dict(online=True, out=tmp_path))
    assert r["status"] == "PASS", r["summary"]
    assert len(list((tmp_path / "affair_cli").glob("*.json"))) == 3


def test_committed_slice_covers_the_samples():
    rows = AC.load_rows(AC.SAMPLE_ROWS)
    for _, s in AC._samples():
        a = rows["affairs"][s["ref"]["opd_id"]]
        assert a["affair"]["body_key"] == s["ref"]["body_key"] and a["docs"]
        picked = AC.pick_docs(a["docs"], a["affair"]["type_harmonized_en"])
        assert {f"opd:{d['id']}" for d in picked.values()} == {d["doc_id"] for d in s["documents"]}
    assert "text" not in json.dumps(rows["affairs"]) or all("text" not in d for a in rows["affairs"].values()
                                                            for d in a["docs"])
