"""`python -m gegenprobe affair` writes the published record (gegenprobe/affair_product.py, R21): affair_cli's record plus
the post layers of `make schema-v02` (typed gaps, OPD metadata, answer-date roles), the extended `make run` comparison,
federal affairs from OPD's texts export (one committed federal slice, offline), and the P5 records made by the command.
No network, no model."""
import json

import pytest

from gegenprobe import affair_cli as AC
from gegenprobe import affair_product as P
from gegenprobe import net, run
from gegenprobe.paths import ROOT
from gegenprobe.schema.p8_v0_2 import OUT, schema_module

from tests.test_affair_cli import _rows, texts  # noqa: F401  (fixture: cached synthetic Bern texts)

FED_SLICE = ROOT / "data" / "affair_cli" / "opd_rows_fed_157601.json"
BODY_BE = {"id": 253, "body_key": "BE", "name": "Bern", "lang": "DE", "executive_name": "Regierungsrat des Kantons Bern",
           "executive_name_de": "Regierungsrat", "executive_name_fr": None, "executive_name_it": None,
           "executive_wikidata_id": None}


@pytest.fixture
def no_network(monkeypatch):
    def down(*a, **k):
        raise AssertionError("no request may leave the machine in this test")
    monkeypatch.setattr(net, "stream_ndjson_gz", down)
    monkeypatch.setattr(net, "get", down)
    monkeypatch.setattr(net, "open_url", down)


def test_command_record_carries_the_post_layers(texts, no_network, tmp_path):  # noqa: F811
    rows = _rows()
    rows["bodies"] = {"BE": BODY_BE}
    p = tmp_path / "rows.json"
    AC.save_rows(rows, p)
    r = P.run([990001], rows_file=str(p))[0]
    assert r["status"] == "ok", r
    rec = r["record"]
    schema_module().validate_affair(rec)
    q = rec["qa"][0]
    # OPD metadata layer: the answering body from OPD's bodies row (was the typed null not_extracted)
    assert q["answering_body"]["kind"] == "value" and q["answering_body"]["value"] == "Regierungsrat des Kantons Bern"
    assert q["answering_body"]["source"] == "opd:bodies/253#executive_name"
    # answer-date roles: every answer date carries a role (the RRB date is printed at a decision anchor)
    assert q["answer_date"]["kind"] == "value" and q["answer_date"]["role"] == "answer_decided"
    assert all(d["role"] != "answered" or "role answered" in (d.get("label") or "") for d in rec["dates"])
    # typed gaps: the co-signatory and addressed-body roles are typed, never silent
    roles = {a["role"] for a in rec["actors"]}
    assert {"co_signatory", "addressed_body"} <= roles
    assert r["sources"]["post_layers"] == list(P.LAYERS)
    assert any(c.get("layer") == "gegenprobe.schema.v0_2_meta" and c["field"] == "qa.0.answering_body"
               for c in r["changes"])


def test_layers_keep_affair_cli_values(texts, no_network):  # noqa: F811
    """The layers add and type; they never replace a value affair_cli wrote."""
    rows = _rows()
    row = rows["affairs"][990001]
    before = AC.build(990001, row, rows["names"]["BE"], sources=rows["sources"])["record"]
    after = P.build(990001, row, dict(rows, bodies={"BE": BODY_BE}), sources=rows["sources"])["record"]

    def values(o, path="", out=None):
        out = {} if out is None else out
        if isinstance(o, dict):
            if o.get("kind") == "value":
                out[path] = o.get("value")
            for k, v in o.items():
                values(v, f"{path}.{k}", out)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                values(v, f"{path}[{i}]", out)
        return out
    b, a = values(before), values(after)
    assert all(a.get(k) == v for k, v in b.items() if not k.startswith(".dates")), \
        [k for k, v in b.items() if a.get(k) != v]


def test_compare_checks_roles_answering_body_and_title():
    s = json.loads((OUT / "samples" / "p3_BE_39369.json").read_text(encoding="utf-8"))
    assert all(P.compare(s, s)["checks"].values())
    other = json.loads(json.dumps(s))
    other["qa"][0]["answering_body"] = dict(kind="null", null_reason="not_extracted", route="rule", evidence="x")
    other["qa"][0]["answer_date"].pop("role")
    other["actors"] = other["actors"][:2]
    c = P.compare(other, s)
    assert not c["checks"]["answering_body"] and not c["checks"]["date_roles"] and not c["checks"]["actor_roles"]
    assert c["checks"]["answer_date"], "the value alone (affair_cli's check) still matches"


def test_step_passes_on_the_samples_and_fails_on_a_record_without_layers(tmp_path, monkeypatch):
    samples = AC._samples()
    by_id = {s["ref"]["opd_id"]: s for _, s in samples}
    monkeypatch.setattr(P, "run", lambda ids, **kw: [dict(opd_affair=i, status="ok", record=by_id[i], needs_review=False)
                                                     for i in ids])
    r = P.step(dict(online=True, out=tmp_path))
    assert r["status"] == "PASS", r["summary"]
    assert "Regierungsrat des Kantons Bern" in r["summary"] and "4 actors" in r["summary"]
    bare = {i: json.loads(json.dumps(s)) for i, s in by_id.items()}
    for s in bare.values():
        s["qa"][0]["answering_body"] = dict(kind="null", null_reason="not_extracted", route="rule", evidence="x")
    monkeypatch.setattr(P, "run", lambda ids, **kw: [dict(opd_affair=i, status="ok", record=bare[i], needs_review=False)
                                                     for i in ids])
    r = P.step(dict(online=True, out=tmp_path))
    assert r["status"] == "FAIL" and "answering_body" in r["summary"]


def test_run_py_uses_the_layered_step():
    assert ("affair_cli", "gegenprobe.affair_product", "step") in run.STEPS


def test_committed_samples_slice_has_what_the_layers_need():
    rows = AC.load_rows(AC.SAMPLE_ROWS)
    assert {"BE", "5192", "6643"} <= set(rows["bodies"])
    evs = [e for a in rows["affairs"].values() for e in a["events"]]
    assert evs and all("actor_fr" in e and "actor_it" in e for e in evs)


# ------------------------------------------------------------------------------------------------ federal
def test_federal_affair_from_the_texts_export_offline(no_network):
    """Federal affair 157601 (one of the federal cell's 15) from the committed slice (OPD rows + its texts_CHE rows): the
    command builds the federal cell's record, equal to the committed one on every comparable field."""
    r = P.run([157601], rows_file=str(FED_SLICE))[0]
    assert r["status"] == "ok", r
    rec = r["record"]
    schema_module().validate_affair(rec)
    fed = {json.loads(x)["ref"]["opd_id"]: json.loads(x)
           for x in (OUT / "fed_records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
    c = P.compare(rec, fed[157601])
    assert all(c["checks"].values()), c["detail"]
    assert c["equal"] == c["compared"] and c["compared"] > 50, c["differ"]
    docs = r["sources"]["documents"]
    assert [d["doc_id"] for d in docs] == ["opd-texts:159677", "opd-texts:159676"]
    drawn = next(json.loads(x) for x in (ROOT / "data" / "fed" / "fed_affairs.jsonl").read_text().splitlines()
                 if json.loads(x)["affair_id"] == 157601)
    assert docs[1]["sha256"] == drawn["sha"]["answer"] and docs[0]["sha256"] == drawn["sha"]["member"]
    assert rec["qa"][0]["answering_body"]["value"]


def test_federal_affair_without_an_answer_row_is_no_documents(no_network):
    rows = AC.load_rows(FED_SLICE)
    row = rows["affairs"][157601]
    trows = [t for t in rows["texts"]["157601"] if "Antwort" not in str(t.get("type_de"))]
    with pytest.raises(AC.AffairError) as e:
        P.fed_build(157601, row, rows["names"]["CHE"], trows, bodies=rows["bodies"])
    assert e.value.kind == "no_documents" and "texts" in e.value.detail


def test_federal_slot_rule_is_the_federal_cells():
    rows = AC.load_rows(FED_SLICE)
    _, slot, note = P.fed_choice(157601, rows["texts"]["157601"])
    assert slot == "de" and note is None  # the federal cell drew this affair in its de stratum


# ------------------------------------------------------------------------------------------------ P5
def test_p5_records_are_the_commands():
    ids = [e["affair_id"] for e in P.p5_inputs()]
    base = [json.loads(x) for x in P.P5_OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert [b["opd_affair"] for b in base] == ids and all(b["status"] == "ok" for b in base)
    for e, b in zip(P.p5_inputs(), base):
        assert {f"opd:{d['doc_id']}" for d in e["docs"]} == {d["doc_id"] for d in b["record"]["documents"]}
        assert {d["sha256"] for d in e["docs"]} == {d["sha256"] for d in b["sources"]["documents"]}
    pub = [json.loads(x) for x in (OUT / "p5_records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(pub) == 40 and all(r["extraction"]["converter_version"] == "gegenprobe-0.1.0+affair" for r in pub)
    assert all(r.get("title") for r in pub), "every P5 record carries OPD's title"
    val = json.loads((OUT / "validation_all.json").read_text(encoding="utf-8"))
    assert "affair_product" in val["sources"]["p5"] and val["product_records"]["n_affairs"] == 105


def test_lugano_sample_is_the_command_record():
    s = json.loads((OUT / "samples" / "p5_5192_28156.json").read_text(encoding="utf-8"))
    assert s["title"] and s["qa"][0]["answer_date"]["value"] == "2016-07-07"
    assert s["qa"][0]["answer_date"]["rule"] == "it_ris_label"


def test_p5_check_skips_or_passes():
    assert P.p5_check()["status"] in ("PASS", "SKIP")


# ------------------------------------------------------------------------------------------------ Docker replay note
def test_expected_cache_misses_by_poppler():
    assert run.expected_misses("26.02.0")["p1"] == 0
    e = run.expected_misses("22.12.0")
    assert (e["p1"], e["p2"]) == (25, 5) and e["source"].startswith("CI run ")
    note = run.expected_note(e)
    assert "P1 25, P2 5 cache misses" in note and "26.02.0" in note
    assert run.expected_misses("1.0.0")["p1"] is None
    r = dict(online=True, steps={"rederive_apertus": dict(status="WARN", coverage={
        "P1 held-out": dict(n=154, rederived=129, match=129, cache_miss=25)})})
    assert run.coverage_line(r, e).endswith(note)
    assert run.coverage_line(r) == ("Apertus replay: P1 129/154 decisions re-derived from the model cache, 129 match "
                                    "(25 cache misses)")
