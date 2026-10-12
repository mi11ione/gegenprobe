"""Adapter canaries (repair/adapters/canary.py): offline, with fixture texts; no network."""
import hashlib
import json

from gegenprobe.repair.adapters import canary, registry, zurich_city
from tests.test_adapters import CITY_ANSWER, affair


def _cfg(text_sha: str) -> dict:
    x = affair(body="261")
    return dict(canaries=[dict(source="www.example.org", body="261", affair_id=1, affair_number="2019/375",
                               action="fetch", tier="exact_doc_date", source_url="https://www.example.org/a.pdf",
                               candidate=dict(title="a", uid=None, origin="source", opd_doc_id=None,
                                              source_typed_answer=False, meta={}),
                               text_sha256=text_sha, affair={k: x.get(k) for k in canary.AFFAIR_KEYS}, opd_docs=[])],
                counted_by_body={"261": 10})


def _run(tmp_path, monkeypatch, text: str, sha: str):
    monkeypatch.setattr(registry, "get", lambda body: zurich_city.ZurichCity())
    fx = tmp_path / "fx"
    fx.mkdir(exist_ok=True)
    (fx / "261_1.txt").write_text(text, encoding="utf-8")
    return canary.run_all(fixtures=fx, cfg=_cfg(sha), state_dir=tmp_path / "state")


def test_canary_verifies_on_the_committed_text(tmp_path, monkeypatch):
    sha = hashlib.sha256(CITY_ANSWER.encode()).hexdigest()
    res = _run(tmp_path, monkeypatch, CITY_ANSWER, sha)
    r = res["results"][0]
    assert (r["outcome"], r["tier"], r["counted"], r["same_text"]) == ("verified", "exact_doc_date", True, True)
    assert res["verified"] == res["expected"] == 1
    assert not [a for a in res["alerts"] if a["kind"].startswith("adapter_canary")]
    # the re-check never writes over the committed run's excerpts
    assert (tmp_path / "state" / "state.json").exists()


def test_canary_alerts_when_the_source_breaks_or_changes(tmp_path, monkeypatch):
    sha = hashlib.sha256(CITY_ANSWER.encode()).hexdigest()
    moved = CITY_ANSWER.replace("27. November", "2. Dezember")  # date no longer equals OPD's event
    res = _run(tmp_path, monkeypatch, moved, sha)
    kinds = [a["kind"] for a in res["alerts"]]
    assert "adapter_canary_failed" in kinds and res["verified"] == 0
    res = _run(tmp_path, monkeypatch, CITY_ANSWER + "\nNachtrag", sha)  # still verifies, text changed
    assert [a["kind"] for a in res["alerts"] if a["kind"].startswith("adapter_canary")] == ["adapter_canary_text_changed"]
    (tmp_path / "fx" / "261_1.txt").unlink()
    res = canary.run_all(fixtures=tmp_path / "fx", cfg=_cfg(sha), state_dir=tmp_path / "state")
    assert res["results"][0]["reason"] == "not_found" and res["alerts"][0]["kind"] == "adapter_canary_failed"


def test_counted_drop_alert_threshold():
    al = canary.alerts([], {"ZH": 2172, "SG": 1012, "LU": 104}, {"ZH": 2100, "SG": 1010, "LU": 98})
    assert [(a["kind"], a["body"]) for a in al] == [("adapter_counted_drop", "LU"), ("adapter_counted_drop", "ZH")]


def test_committed_canaries_are_counted_rows_of_the_committed_lists():
    cfg = canary.load()
    assert canary.check(cfg) == []
    srcs = {c["source"] for c in cfg["canaries"]}
    assert {"parlzhcdws.cmicloud.ch", "www.ratsinfo.sg.ch", "ratsinfo.so.ch", "parlement.vs.ch", "www.lu.ch",
            "www.aarau.ch", "files.openparldata.ch"} == srcs
    assert all(json.dumps(c["affair"]) and c["text_sha256"] for c in cfg["canaries"])


def test_text_differing_only_by_extractor_is_not_an_alert(tmp_path, monkeypatch):
    """Same document bytes as the baseline, another extractor (the Docker image's tesseract / poppler): no alert; other
    bytes, or the same extractor, still alert adapter_canary_text_changed."""
    sha = hashlib.sha256(CITY_ANSWER.encode()).hexdigest()
    changed = CITY_ANSWER + "\nNachtrag"
    cfg = _cfg(sha)
    file_sha = hashlib.sha256(changed.encode()).hexdigest()  # the fixture's "file" hash is its text's
    monkeypatch.setattr(registry, "get", lambda body: zurich_city.ZurichCity())
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "261_1.txt").write_text(changed, encoding="utf-8")
    cfg["canaries"][0]["baseline"] = dict(file_sha256=file_sha, extractor="tesseract-5.5.3-deu+fra+ita")
    res = canary.run_all(fixtures=fx, cfg=cfg, state_dir=tmp_path / "s1")
    r = res["results"][0]
    assert (r["same_text"], r["extractor"], r["text_differs_by_extractor"]) == (False, "fixture", True)
    assert not [a for a in res["alerts"] if a["kind"].startswith("adapter_canary")]
    cfg["canaries"][0]["baseline"] = dict(file_sha256="0" * 64, extractor="tesseract-5.5.3-deu+fra+ita")  # re-published
    res = canary.run_all(fixtures=fx, cfg=cfg, state_dir=tmp_path / "s2")
    assert [a["kind"] for a in res["alerts"] if a["kind"].startswith("adapter_canary")] == ["adapter_canary_text_changed"]
    cfg["canaries"][0]["baseline"] = dict(file_sha256=file_sha, extractor="fixture")  # same extractor, other text
    res = canary.run_all(fixtures=fx, cfg=cfg, state_dir=tmp_path / "s3")
    assert [a["kind"] for a in res["alerts"] if a["kind"].startswith("adapter_canary")] == ["adapter_canary_text_changed"]


def test_committed_canaries_carry_a_baseline():
    cfg = canary.load()
    assert all(c["baseline"]["file_sha256"] and c["baseline"]["extractor"] for c in cfg["canaries"])
    ocr = {c["affair_number"] for c in cfg["canaries"] if c["baseline"]["extractor"].startswith("tesseract")}
    assert ocr == {"IR 2008.0022", "2020.06.206"}  # the two canaries the Docker nights flagged
