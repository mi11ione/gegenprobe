"""`python -m gegenprobe affair` when a source has gone: OPD's own copy stands in (sha256 checked against the sample in the
make run step), typed `source_gone` / `over_budget` SKIP instead of FAIL, the hard time budget (gegenprobe.deadline) and
the Q/A items the command now writes. Offline: no network, no model."""
import json
import time
import urllib.error

import pytest

from gegenprobe import affair_cli as AC
from gegenprobe import deadline as DL
from gegenprobe.convert import batch
from tests.test_affair_cli import _rows, no_parts, texts  # noqa: F401 - fixtures

COPY = "https://files.openparldata.ch/doc/BE/" + "c" * 64


def _http(url, code=404):
    return urllib.error.HTTPError(url, code, "Not Found", {}, None)


@pytest.fixture
def fetched(monkeypatch):
    """batch.get_document: the source answers 404, OPD's copy is a document (pdftext.extract stubbed)."""
    calls = []

    def get_document(url, timeout=60, tries=2):
        calls.append((url, timeout, tries))
        if url.startswith("https://files.openparldata.ch/doc/"):
            return "c" * 64, None
        raise _http(url)
    monkeypatch.setattr(batch, "get_document", get_document)
    from gegenprobe import pdftext
    monkeypatch.setattr(pdftext, "extract", lambda sha, path, ocr=True: dict(pages=["text " * 50], extractor="x",
                                                                                image_only=False))
    return calls


def test_gone_source_is_read_from_opds_copy(fetched):
    d = dict(id=502, b="BE", url="https://example.org/a.pdf", url_oparl=COPY, st="ok", n=10)
    e = AC.fetch_doc("answer", d, timeout=30, tries=2)
    assert e["fetched_from"] == "opd_copy" and e["copy_url"] == COPY and e["sha256"] == "c" * 64
    assert e["source_error"].startswith("http_error (HTTP 404")
    assert [c[0] for c in fetched] == [d["url"], COPY] and all(c[1:] == (30, 2) for c in fetched)


def test_no_copy_is_source_gone_for_a_gone_source_and_keeps_network_kinds(fetched, monkeypatch):
    monkeypatch.setattr(AC, "opd_copy_url", lambda d: None)
    with pytest.raises(AC.AffairError) as e:
        AC.fetch_doc("answer", dict(id=502, b="BE", url="https://example.org/a.pdf"))
    assert e.value.kind == "source_gone" and "OPD keeps no copy" in e.value.detail

    def unreachable(url, timeout=60, tries=2):
        raise urllib.error.URLError("DNS")
    monkeypatch.setattr(batch, "get_document", unreachable)
    with pytest.raises(AC.AffairError) as e:
        AC.fetch_doc("answer", dict(id=502, b="BE", url="https://example.org/a.pdf"))
    assert e.value.kind == "network_error"
    assert {"source_gone", "over_budget", "network_error"} <= set(AC.UNREACHABLE)


def test_a_copy_that_fails_too_is_source_gone(monkeypatch):
    monkeypatch.setattr(batch, "get_document", lambda url, timeout=60, tries=2: (_ for _ in ()).throw(_http(url, 410)))
    with pytest.raises(AC.AffairError) as e:
        AC.fetch_doc("question", dict(id=501, b="BE", url="https://example.org/q.pdf", url_oparl=COPY))
    assert e.value.kind == "source_gone" and "OPD's copy" in e.value.detail and "HTTP 410" in e.value.detail


def test_every_sample_document_has_an_expected_sha256():
    for _, s in AC._samples():
        assert set(AC.expected_sha(s)) == {d["doc_id"] for d in s["documents"]}


def test_copy_url_only_from_opds_file_host():
    assert AC.opd_copy_url(dict(url_oparl=COPY)) == COPY
    assert AC.opd_copy_url(dict(url_oparl="https://evil.example/doc/x", b=None, id=None)) is None


def _sample_run(sample_sha_ok: bool):
    def run(ids, **kw):
        out = []
        for _, s in AC._samples():
            want = AC.expected_sha(s)
            docs = [dict(role=d["role"], doc_id=int(d["doc_id"].split(":")[1]), sha256=want[d["doc_id"]],
                         fetched_from="opd_copy", copy_url=COPY, source_error="http_error (HTTP 404)")
                    for d in s["documents"]]
            if not sample_sha_ok:
                docs[0]["sha256"] = "f" * 64
            out.append(dict(opd_affair=s["ref"]["opd_id"], status="ok", record=s, needs_review=False,
                            sources=dict(documents=docs)))
        return out
    return run


def test_step_passes_on_matching_copies_and_skips_when_no_copy_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(AC, "run", _sample_run(True))
    r = AC.step(dict(online=True, out=tmp_path))
    assert r["status"] == "PASS", r["summary"]
    assert "from OPD's copy (source: http_error)" in r["summary"]
    monkeypatch.setattr(AC, "run", _sample_run(False))
    r = AC.step(dict(online=True, out=tmp_path))
    assert r["status"] == "SKIP", r["summary"]
    assert all(x["status"] == "source_gone" for x in r["affairs"]) and "differs from the committed sample" in json.dumps(r)


def test_run_budget_cuts_off_with_over_budget(texts, no_parts, monkeypatch):  # noqa: F811
    if not DL.armed():
        pytest.skip("SIGALRM not available here")
    rows = _rows()

    def slow(*a, **kw):
        try:  # an `except Exception` (as in net's retry loop) must not swallow the deadline
            time.sleep(5)
        except Exception:  # noqa: BLE001
            pass
        raise AssertionError("not interrupted")
    monkeypatch.setattr(AC, "build", slow)
    monkeypatch.setattr(AC, "load_rows", lambda p: rows)
    t = time.time()
    out = AC.run([990001, 990001], rows_file="x.json", budget_s=0.3)
    assert time.time() - t < 2
    assert [o["status"] for o in out] == ["over_budget", "over_budget"]


def test_deadline_is_not_an_exception_and_request_timeout_caps(monkeypatch):
    assert not issubclass(DL.DeadlineExceeded, Exception)
    monkeypatch.setenv("GP_REQUEST_TIMEOUT", "30")
    assert DL.request_timeout() == 30 and DL.request_timeout(12.5) == 12 and DL.request_timeout(0.2) == 1
    with pytest.raises(DL.DeadlineExceeded):
        with DL.deadline(0):
            pass


def test_the_record_carries_qa_items(texts, no_parts):  # noqa: F811
    rows = _rows()
    r = AC.build(990001, rows["affairs"][990001], rows["names"]["BE"], sources=rows["sources"])
    q = r["record"]["qa"][0]
    assert q["items"] and q["items"][0]["n"] == 1 and q["items"][0]["question"]["kind"] == "value"
    assert q["items"][0]["question"]["doc"] == "opd:501" and "qa.0.items" not in r["record"]["empty_reasons"]
    assert "Q/A pairing by gegenprobe.schema.v0_2_qa.with_qa" in r["record"]["extraction"]["notes"]


def test_compare_checks_qa_items_only_with_the_same_extractor():
    item = dict(n=1, question=dict(kind="value"), answer=dict(kind="value"))
    doc = dict(doc_id="opd:1", role="question", extractor="pdftotext-1")
    s = dict(qa=[dict(items=[item, item])], documents=[doc])
    one = dict(qa=[dict(items=[item])], documents=[doc])
    assert AC.compare(one, s)["checks"]["qa_items"] is False
    other = dict(one, documents=[dict(doc, extractor="pdftotext-2")])
    assert "qa_items" not in AC.compare(other, s)["checks"]
