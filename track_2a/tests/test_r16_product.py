"""Round 16 product fixes (no network, no model):
  * author-role consistency in the v0.2 records (gegenprobe.schema.role_consistency; J1: a group sole_author next to
    joint authors on one affair);
  * `python -m gegenprobe affair --roles apertus`: the frozen P10 reader as an opt-in review route, with a fake backend;
  * `convert` emits opd_text_span by default where OPD's stored text exists (gegenprobe.convert.opd_store);
  * the local 8B path: weights re-hashed at every load, sandboxed chat template, operator file, GP_USER_AGENT
    (gegenprobe.gguf_guard)."""
import copy
import gzip
import hashlib
import io
import json
import sys
import types

import pytest

from gegenprobe import affair_cli as AC
from gegenprobe import gguf_guard, llm
from gegenprobe.convert import batch, opd_store, roles_pointer, roles_review
from gegenprobe.schema import role_consistency as RC
from gegenprobe.schema import v0_2_roles
from gegenprobe.schema.p8_v0_2 import OUT, schema_module

from tests.test_affair_cli import _rows, no_parts, texts  # noqa: F401  (fixtures)


# ------------------------------------------------------------------------------------------------ role consistency
def _a(role, kind="person", value="X"):
    return dict(role=role, kind=kind, name=dict(kind="value", value=value))


def test_rules_r1_to_r4():
    assert RC.violations([_a("sole_author")]) == []
    assert RC.violations([_a("sole_author", "parliamentary_group"), _a("first_signatory"), _a("co_signatory")]) == []
    assert RC.violations([_a("first_signatory")]) == []  # "X et consorts": GUIDE_P8, 9 of P8's 66 gold records
    assert RC.violations([_a("joint_author"), _a("joint_author")]) == []
    assert RC.violations([_a("sole_author"), _a("sole_author")])[0].startswith("R1")
    assert any(v.startswith("R2") for v in RC.violations([_a("sole_author", "parliamentary_group"), _a("joint_author"),
                                                          _a("joint_author")]))
    assert RC.violations([_a("sole_author"), _a("first_signatory")])[0].startswith("R3")
    assert RC.violations([_a("joint_author"), _a("joint_author"), _a("first_signatory")])[0].startswith("R4")
    assert RC.violations([_a("joint_author")])[0].startswith("R4")


def test_harmonise_makes_the_group_a_joint_author_and_nothing_else():
    acts = [_a("sole_author", "parliamentary_group", "Gruppo X"), _a("joint_author", value="A B"),
            _a("joint_author", value="C D"), _a("co_signatory", value="E F")]
    rec = dict(actors=acts, extraction=dict(notes="n"))
    out, ch = RC.harmonise(rec)
    assert [a["role"] for a in out["actors"]] == ["joint_author", "joint_author", "joint_author", "co_signatory"]
    assert ch == [dict(name="Gruppo X", kind="parliamentary_group", was="sole_author", now="joint_author")]
    assert out["extraction"]["notes"].startswith("n; author roles harmonised by gegenprobe.schema.role_consistency")
    assert rec["actors"][0]["role"] == "sole_author"  # input untouched
    assert [{k: v for k, v in a.items() if k != "role"} for a in out["actors"]] == \
        [{k: v for k, v in a.items() if k != "role"} for a in acts]
    same = dict(actors=[_a("sole_author", "parliamentary_group"), _a("spokesperson")], extraction={})
    assert RC.harmonise(same) == (same, [])


def _records(name):
    return [json.loads(x) for x in (OUT / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def test_committed_records_are_role_consistent():
    for name in ("p3_records.jsonl", "p3b_records.jsonl", "p5_records.jsonl", "fed_records.jsonl", "p8_records.jsonl"):
        assert RC.check_records(_records(name))["n_violating"] == 0, name
    for p in sorted((OUT / "samples").glob("*.json")):
        assert RC.violations(json.loads(p.read_text(encoding="utf-8"))["actors"]) == [], p.name
    p8_first_alone = sum(1 for r in _records("p8_records.jsonl")
                         if {a["role"] for a in r["actors"]} == {"first_signatory"})
    assert p8_first_alone == 8  # why "a first_signatory needs a co_signatory or a group" is not a rule
    assert sum(1 for r in _records("p8_records.jsonl") if any(a["role"] == "first_signatory" for a in r["actors"])
               and not any(a["role"] in ("co_signatory",) or a["kind"] != "person" for a in r["actors"])) == 9


def test_lugano_sample_no_longer_mixes_sole_and_joint():
    rec = json.loads((OUT / "samples" / "p5_5192_28156.json").read_text(encoding="utf-8"))
    schema_module().validate_affair(rec)
    roles = [(a["kind"], a["role"]) for a in rec["actors"]]
    assert roles[0] == ("parliamentary_group", "joint_author") and "sole_author" not in {r for _, r in roles}
    assert sum(r == "joint_author" for _, r in roles) == 6
    assert "role_consistency" in rec["extraction"]["notes"]


def test_validation_block_lists_the_changed_records():
    rc = json.loads((OUT / "validation_all.json").read_text(encoding="utf-8"))["role_consistency"]
    assert rc["n_records_changed"] == 2 and sorted(rc["changed"]) == ["p3b:293:106111", "p5:5192:28156"]
    assert all(v["n_violating"] == 0 for v in rc["checked"].values())
    assert set(rc["checked"]) == {"p3", "p3b", "p5", "fed", "p8"}


def test_check_cli(tmp_path, capsys):
    assert RC.main([str(OUT / "samples" / "p5_5192_28156.json")]) == 0
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(dict(record=dict(actors=[_a("sole_author"), _a("joint_author"), _a("joint_author")])))
                   + "\n" + json.dumps(dict(actors=[])) + "\n")
    assert RC.main([str(bad)]) == 1
    assert "R2" in capsys.readouterr().out


def test_affair_command_harmonises_roles(texts, no_parts, monkeypatch):  # noqa: F811
    orig = v0_2_roles.extract_row

    def group_over_signatures(set_name, entry):
        x = orig(set_name, entry)
        base = x["actors"][0]["name"]
        x["actors"] = [dict(role="sole_author", kind="parliamentary_group", name=dict(base, value="SVP-Fraktion")),
                       dict(role="joint_author", kind="person", name=dict(base)),
                       dict(role="joint_author", kind="person", name=dict(base, value="Anna Gerber"))]
        return x
    monkeypatch.setattr(v0_2_roles, "extract_row", group_over_signatures)
    rows = _rows()
    r = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"], sources=rows["sources"])
    assert r["status"] == "ok"
    printed = [(a["kind"], a["role"]) for a in r["record"]["actors"] if a["name"].get("route") == "rule"]
    assert ("parliamentary_group", "joint_author") in printed and ("parliamentary_group", "sole_author") not in printed
    assert not any(x["field"] == "actors" for x in r["review"])


# ------------------------------------------------------------------------------------------------ --roles apertus
class FakeBackend:
    """Exact forced choice like the GGUF backend: P(true) from `author` / `first`, by the prefix asked."""
    kind = "fake"
    build = "fake:test"

    def __init__(self, author=True, first=False):
        self.author, self.first, self.calls = author, first, 0
        self.served = set()

    def score(self, user, prefix, conts):
        self.calls += 1
        yes = self.author if any(prefix == p["de"] for k, p in roles_pointer.BOOL_PREFIX.items() if "author" in k) \
            else self.first
        return [0.0, -12.0] if yes else [-12.0, 0.0]


def test_default_runs_no_model(texts, no_parts, monkeypatch):  # noqa: F811
    monkeypatch.setattr(batch, "make_backend", lambda spec: pytest.fail("no backend without --roles apertus"))
    rows = _rows()
    r = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"], sources=rows["sources"])
    assert r["sources"]["roles"] == "rules" and "actors" not in r["suggestions"]


def test_roles_apertus_suggests_never_applies(texts, no_parts):  # noqa: F811
    rows = _rows()
    plain = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"], sources=rows["sources"])
    be = FakeBackend(author=True)
    r = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"], sources=rows["sources"], roles="apertus",
                 role_backend=be)
    assert be.calls > 0 and r["record"]["actors"] == plain["record"]["actors"]  # the rules' roles stay
    s = r["suggestions"]["actors"]
    assert s["source"] == "apertus" and s["applied"] is False and s["review"] is True and s["fallback"] == "none"
    assert all(x["route"] != roles_review.ROUTE_OPD for x in s["actors"])
    assert s["actors"] and all(x["review"] is True and x["route"] == roles_review.ROUTE_MODEL for x in s["actors"])
    ruchti = next(x for x in s["actors"] if "Ruchti" in x["name"]["value"])
    assert ruchti["name"]["doc"] in ("opd:501", "opd:502") and ruchti["name"]["char_end"] > ruchti["name"]["char_start"]
    assert ruchti["rules_role"] is not None and isinstance(ruchti["agrees_with_rules"], bool)
    assert s["same_build_as_p10"] is False and "exploratory" in s["review_reason"]
    assert s["config"]["file"] == "data/p10/p10_config.json" and s["pointer_version"] == roles_pointer.POINTER_VERSION
    assert r["needs_review"] is True and any(x["field"] == "actors" for x in r["review"])
    assert r["sources"]["roles"] == "apertus"


def test_roles_apertus_abstains_without_fallback_by_default(texts, no_parts):  # noqa: F811
    rows = _rows()
    r = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"], sources=rows["sources"], roles="apertus",
                 role_backend=FakeBackend(author=False))
    s = r["suggestions"]["actors"]
    assert s["fallback"] == "none" and s["source"] == "none" and s["actors"] == []
    assert "--roles-fallback opd" in s["review_reason"] and r["sources"]["roles_fallback"] == "none"


def test_roles_apertus_falls_back_to_opd_only_when_asked(texts, no_parts):  # noqa: F811
    rows = _rows()
    r = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"], sources=rows["sources"], roles="apertus",
                 role_backend=FakeBackend(author=False), roles_fallback="opd")
    s = r["suggestions"]["actors"]
    assert s["fallback"] == "opd"
    assert s["source"] == "opd_contributors"
    assert s["actors"] == [dict(role="sole_author", kind="person", route="opd_contributors", review=True,
                                name=dict(value="Fritz Ruchti", located=False), rules_role=s["actors"][0]["rules_role"],
                                agrees_with_rules=s["actors"][0]["agrees_with_rules"])]
    assert "abstained" in s["review_reason"]


def test_roles_apertus_cli(texts, no_parts, tmp_path, monkeypatch, capsys):  # noqa: F811
    seen = []
    monkeypatch.setattr(batch, "make_backend", lambda spec: seen.append(spec) or FakeBackend())
    f = tmp_path / "rows.json"
    AC.save_rows(_rows(), f)
    assert AC.main(["--opd-affair", "990001", "--rows", str(f), "--roles", "apertus", "--backend", "gguf"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert seen == ["gguf"] and out["suggestions"]["actors"]["route"] == "--roles apertus"
    assert out["suggestions"]["actors"]["fallback"] == "none"
    monkeypatch.setattr(batch, "make_backend", lambda spec: FakeBackend(author=False))
    assert AC.main(["--opd-affair", "990001", "--rows", str(f), "--roles", "apertus", "--roles-fallback", "opd"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["suggestions"]["actors"]["source"] == "opd_contributors"
    assert AC.main(["--opd-affair", "990001", "--rows", str(f), "--roles-fallback", "opd"]) == 2  # needs --roles apertus
    with pytest.raises(ValueError):
        roles_review.read({}, {"docs": []}, None, [], FakeBackend(), fallback="list")
    with pytest.raises(ValueError):
        roles_review.read({}, {"docs": []}, None, [], None)


# ------------------------------------------------------------------------------------------------ OPD text spans
OPD_TEXT = "Regierungsrat\n\nRRB-Nr.:  879/2024 vom 28. August 2024\nBetreff: Wald"


def _row(doc_id="404590", body="BE"):
    return dict(status="ok", input=dict(source="x.pdf", opd_doc_id=doc_id, body=body),
                fields=dict(answer_date=dict(value="2024-08-28", quote="28. August 2024",
                                             context="RRB-Nr.: 879/2024 vom 28. August 2024")),
                needs_review=False, review_reasons=[], rules_coverage=dict(status="covered", body=body))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(opd_store, "CACHE", tmp_path / "opd_texts")
    monkeypatch.setattr(opd_store, "SNAPSHOTS", tmp_path / "snap")
    monkeypatch.delenv("GP_OPD_TEXT", raising=False)
    monkeypatch.delenv("GP_EXPORTS_DIR", raising=False)
    return tmp_path


def _gz(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_find_from_snapshot_mirror_and_cache(store, monkeypatch):
    _gz(store / "snap" / "BE.jsonl.gz", [dict(id=1, affair_id=9, text="a"), dict(id=404590, affair_id=9, text=OPD_TEXT)])
    got = opd_store.find("404590", "BE")
    assert got["status"] == "found" and got["text"] == OPD_TEXT and got["source"] == "snapshot:BE.jsonl.gz"
    _gz(store / "ex" / "docs" / "docs_ZH.ndjson.gz", [dict(id=7, text=""), dict(id=8, text="Zürich Text")])
    monkeypatch.setenv("GP_EXPORTS_DIR", str(store / "ex"))
    assert opd_store.find("opd:8", "ZH", "local")["status"] == "found"
    assert (store / "opd_texts" / "8.json").exists()  # cached: found again without the export
    monkeypatch.delenv("GP_EXPORTS_DIR")
    assert opd_store.find(8, "ZH", "local")["source"].startswith("cache:export:docs_ZH")
    assert opd_store.find(7, "ZH", "local")["status"] == "not_found"  # local: no network, no mirror
    _gz(store / "snap" / "ZH.jsonl.gz", [dict(id=7, text="  ")])
    assert opd_store.find(7, "ZH")["status"] == "not_stored"
    assert opd_store.find(7, "ZH", "off")["status"] == "off"
    assert opd_store.find(None, "ZH")["status"] == "no_opd_doc_id"


def test_find_unreachable_export_is_a_reason_not_an_error(store, monkeypatch):
    from gegenprobe import net

    def down(url):
        raise net.Disallowed("robots", kind="robots_unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(net, "stream_ndjson_gz", down)
    got = opd_store.find(5, "BE")
    assert got["status"] == "unavailable" and "for BE could not be read" in got["reason"]


def test_convert_emits_opd_text_span_by_default(store, monkeypatch, capsys):
    from gegenprobe.__main__ import main

    _gz(store / "snap" / "BE.jsonl.gz", [dict(id=404590, affair_id=9, text=OPD_TEXT)])
    monkeypatch.setattr(batch, "convert_one", lambda src, inp, **kw: _row())
    assert main(["convert", "x.pdf", "--opd-doc-id", "404590", "--body", "BE"]) == 0
    row = json.loads(capsys.readouterr().out)
    span = row["fields"]["answer_date"]["opd_text_span"]
    assert span["status"] == "unique" and OPD_TEXT[span["char_start"]:span["char_end"]] == "28. August 2024"
    assert row["opd_text_alignment"] == {"answer_date": "unique"}
    assert row["opd_text_source"]["sha256"] == hashlib.sha256(OPD_TEXT.encode()).hexdigest()
    assert OPD_TEXT not in json.dumps(row)  # OPD's text itself is never written into the row
    assert main(["convert", "x.pdf", "--opd-doc-id", "404590", "--body", "BE", "--no-opd-text"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert "opd_text_span" not in row["fields"]["answer_date"] and "opd_text_alignment" not in row


def test_convert_without_stored_text_says_so(store, monkeypatch, capsys):
    from gegenprobe.__main__ import main

    monkeypatch.setenv("GP_OPD_TEXT", "local")
    monkeypatch.setattr(batch, "convert_one", lambda src, inp, **kw: _row("77"))
    assert main(["convert", "x.pdf", "--opd-doc-id", "77", "--body", "BE"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["opd_text_alignment"]["status"] == "no_opd_text" and "opd_text_span" not in row["fields"]["answer_date"]


def test_batch_rows_get_spans_and_convert_one_is_restored(store, monkeypatch, tmp_path):
    from gegenprobe.__main__ import main

    _gz(store / "snap" / "BE.jsonl.gz", [dict(id=404590, affair_id=9, text=OPD_TEXT)])
    fake = lambda src, inp, **kw: dict(_row(inp.get("opd_doc_id")), input=dict(inp, source=src))  # noqa: E731
    monkeypatch.setattr(batch, "convert_one", fake)
    tsv = tmp_path / "in.tsv"
    tsv.write_text("url\topd_doc_id\tbody\nhttps://x.ch/1.pdf\t404590\tBE\n")
    out = tmp_path / "out.jsonl"
    assert main(["convert", "--batch", str(tsv), "--out", str(out)]) == 0
    row = json.loads(out.read_text().splitlines()[0])
    assert row["fields"]["answer_date"]["opd_text_span"]["status"] == "unique"
    assert batch.convert_one is fake


# ------------------------------------------------------------------------------------------------ local 8B path
def test_targets_patched():
    gguf_guard.ensure()
    assert gguf_guard.status() == {n: True for n in gguf_guard.TARGETS}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_model_requests_carry_gp_user_agent(monkeypatch):
    import urllib.request

    gguf_guard.ensure()
    monkeypatch.setenv("GP_USER_AGENT", "opd-gegenprobe/0.1 (+https://example.org/contact)")
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append(req.get_header("User-agent"))
        return _Resp(json.dumps(dict(model="m", choices=[dict(message=dict(content="ok"), finish_reason="stop")]))
                     .encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    be = llm.OpenAICompat(base_url="http://127.0.0.1:9", api_key="k", model="m")
    be._post(dict(model="m", temperature=0, max_tokens=1, messages=[]))
    roles_pointer._post_openai(be, dict(model="m", messages=[]))
    assert sent == ["opd-gegenprobe/0.1 (+https://example.org/contact)"] * 2


def test_fetch_gguf_download_carries_gp_user_agent(monkeypatch, tmp_path):
    import urllib.request

    gguf_guard.ensure()
    from gegenprobe import paths
    monkeypatch.setattr(paths, "WORK", tmp_path)
    monkeypatch.setenv("GP_USER_AGENT", "opd-gegenprobe/0.1")
    sent = []

    def stop(req, timeout=None):
        sent.append((req.full_url, req.get_header("User-agent")))
        raise RuntimeError("stop")
    monkeypatch.setattr(urllib.request, "urlopen", stop)
    orig = getattr(llm.fetch_gguf, "__wrapped__", llm.fetch_gguf)
    with pytest.raises(RuntimeError, match="stop"):
        orig("apertus-v1.5-8b-text-q4_k_m")
    assert sent == [(llm.GGUF_PINS["apertus-v1.5-8b-text-q4_k_m"]["url"], "opd-gegenprobe/0.1")]


@pytest.fixture
def weights(tmp_path, monkeypatch):
    f = tmp_path / "tiny.gguf"
    f.write_bytes(b"GGUF" + bytes(range(256)) * 64)
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    monkeypatch.setitem(llm.GGUF_PINS, "tiny-test", dict(url="https://example.org/tiny.gguf", sha256=sha,
                                                          size=f.stat().st_size))
    monkeypatch.delenv("GP_GGUF_FILE", raising=False)
    monkeypatch.delenv("GP_GGUF_SHA256", raising=False)
    gguf_guard.ensure()
    return f, sha


def _fake_llama(monkeypatch, template, loads):
    m = types.ModuleType("llama_cpp")

    class Llama:
        def __init__(self, model_path, **kw):
            loads.append((model_path, kw))
            self.metadata = {"tokenizer.chat_template": template}
    m.Llama = Llama
    monkeypatch.setitem(sys.modules, "llama_cpp", m)


TEMPLATE = ("{%- set ns = namespace(n=0) -%}{{ bos_token }}{% for m in messages %}{% set ns.n = ns.n + 1 %}<|{{ m['role'] }}"
            "_start|>{{ m['content'] | trim }}<|{{ m['role'] }}_end|>{% endfor %}{% if add_generation_prompt %}"
            "<|assistant_start|>{% endif %}")


def test_weights_hashed_at_every_load_and_template_sandboxed(weights, monkeypatch):
    from jinja2 import Environment
    from jinja2.exceptions import SecurityError

    from gegenprobe.gguf_fast import GGUFFast

    f, sha = weights
    loads, hashed = [], []
    orig = gguf_guard.sha256_file
    for cls in (llm.GGUF, GGUFFast):  # the guard copy that patched the class (sitecustomize's or the package's)
        monkeypatch.setitem(cls._load.__globals__, "sha256_file", lambda p: hashed.append(p) or orig(p))
    _fake_llama(monkeypatch, TEMPLATE, loads)
    for cls in (llm.GGUF, GGUFFast):
        g = cls("tiny-test", path=str(f))
        g._load()
        assert g.weights_sha256 == sha
        msg = "Interpellation  {{ 7*7 }}"
        assert g.render(msg) == Environment().from_string(TEMPLATE).render(
            messages=[{"role": "user", "content": msg}], add_generation_prompt=True, enable_thinking=False,
            bos_token="<s>")
    assert len(hashed) == 2 and loads[0][1]["logits_all"] is True and loads[1][1]["logits_all"] is False
    evil = "{{ ''.__class__.__mro__[1].__subclasses__() }}"
    _fake_llama(monkeypatch, evil, loads)
    g = llm.GGUF("tiny-test", path=str(f))
    g._load()
    with pytest.raises(SecurityError):
        g.render("x")


def test_wrong_or_unpinned_weights_are_refused(weights, monkeypatch, tmp_path):
    f, sha = weights
    loads = []
    _fake_llama(monkeypatch, TEMPLATE, loads)
    other = tmp_path / "other.gguf"
    other.write_bytes(b"GGUF tampered")
    with pytest.raises(RuntimeError, match="expected"):
        llm.GGUF("tiny-test", path=str(other))._load()
    with pytest.raises(RuntimeError, match="no sha256 pin"):
        llm.GGUF("not-pinned", path=str(f))._load()
    assert loads == []


def test_operator_file(weights, monkeypatch, tmp_path):
    f, sha = weights
    loads = []
    _fake_llama(monkeypatch, TEMPLATE, loads)
    own = tmp_path / "apertus-8b-q5_k_m.gguf"
    own.write_bytes(b"GGUF operator quantised")
    own_sha = hashlib.sha256(own.read_bytes()).hexdigest()
    monkeypatch.setenv("GP_GGUF_FILE", str(own))
    monkeypatch.setenv("GP_GGUF_SHA256", own_sha.upper())
    g = llm.GGUF()
    assert g.path == str(own) and g.build == f"gguf:apertus-8b-q5_k_m@{own_sha[:12]}" and g.cache.dir.name.startswith(
        "gguf_apertus-8b-q5_k_m")
    g._load()
    assert loads[-1][0] == str(own) and g.weights_sha256 == own_sha
    monkeypatch.setenv("GP_GGUF_SHA256", sha)  # the pinned weights, stored elsewhere: the pinned build
    monkeypatch.setenv("GP_GGUF_FILE", str(f))
    assert llm.GGUF().build == "gguf:tiny-test"
    monkeypatch.setenv("GP_GGUF_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="expected"):
        llm.GGUF()._load()
    monkeypatch.delenv("GP_GGUF_SHA256")
    with pytest.raises(ValueError, match="go together"):
        llm.GGUF()
    monkeypatch.setenv("GP_GGUF_SHA256", "abc")
    with pytest.raises(ValueError, match="64 hexadecimal"):
        llm.GGUF()


def test_sandbox_keeps_the_frozen_render():
    """The plain and the sandboxed environment render the same prompt (the pinned file's own template was checked the
    same way when this module was written; see gguf_guard's docstring)."""
    from jinja2 import Environment

    kw = dict(messages=[{"role": "user", "content": "é « » {% raw %}"}], add_generation_prompt=True,
              enable_thinking=False, bos_token="<s>")
    assert gguf_guard.sandboxed_template(TEMPLATE).render(**copy.deepcopy(kw)) == \
        Environment().from_string(TEMPLATE).render(**kw)
