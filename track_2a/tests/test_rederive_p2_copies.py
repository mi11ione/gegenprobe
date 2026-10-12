"""P2 re-derivation in `make run` (eval.replay_all.rederive_apertus): failing sources are read from OPD's own copy
(data/rederive/p2_opd_copies.json), accepted only with the committed sha256, and the coverage phrase accounts for every
document. Offline: fetches are stubbed, nothing leaves the machine."""
import json

import pytest

from eval import rederive_copies, replay_all
from gegenprobe import net, pdftext


def test_every_p2_document_has_a_copy_entry():
    assert rederive_copies.check() == []
    m = json.loads(rederive_copies.MAP.read_text(encoding="utf-8"))
    assert m["n_docs"] == 62 and m["n_with_copy"] == len(rederive_copies.load()) == 62
    assert all(u.startswith(rederive_copies.OPD_COPY_PREFIX) for u in rederive_copies.load().values())


def test_budget_split_defaults_and_override(monkeypatch):
    monkeypatch.delenv("GP_REDERIVE_APERTUS_BUDGET", raising=False)
    monkeypatch.delenv("GP_REDERIVE_APERTUS_BUDGET_P2", raising=False)
    assert replay_all.budget_split() == {"P1": 180.0, "P2": 240.0}
    assert replay_all.budget_split(5) == {"P1": 5, "P2": 5}


@pytest.fixture
def stub(tmp_path, monkeypatch):
    """pdftext.fetch_pdf stubbed: the source host 'dead.example' fails robots.txt; OPD's copy returns `copy_sha`."""
    import gegenprobe.paths as paths
    monkeypatch.setattr(paths, "PDF_CACHE", tmp_path)
    calls = []

    def fetch(url, expect_sha256=None, timeout=180, tries=5):
        calls.append(url)
        if "dead.example" in url:
            raise net.Disallowed(f"{url} (robots.txt unreachable (HTTP 503), fail-closed)", kind="robots_unreachable")
        got = stub.copy_sha
        if expect_sha256 and got != expect_sha256:
            raise pdftext.FetchError("sha_mismatch", f"{url}: got {got}, expected {expect_sha256}")
        return got, tmp_path / f"{got}.pdf"
    monkeypatch.setattr(pdftext, "fetch_pdf", fetch)
    stub.calls = calls
    return stub


def _doc(i, sha="a" * 64):
    return dict(doc_id=i, url=f"https://dead.example/doc/{i}", sha256=sha)


def test_failing_source_is_read_from_opd_copy_once_per_host(stub):
    stub.copy_sha = "a" * 64
    copies, failed = {1: "https://files.openparldata.ch/doc/VD/x1", 2: "https://files.openparldata.ch/doc/VD/x2"}, {}
    assert replay_all.fetch_verified(_doc(1), 60, copies, failed)[2] == "opd_copy"
    assert failed == {"dead.example": "robots_unreachable"}
    assert replay_all.fetch_verified(_doc(2), 60, copies, failed)[2] == "opd_copy"
    # the failed host is not asked again: source once, then copy, copy
    assert stub.calls == ["https://dead.example/doc/1", copies[1], copies[2]]


def test_copy_with_another_sha256_is_refused(stub):
    stub.copy_sha = "b" * 64
    with pytest.raises(pdftext.FetchError) as e:
        replay_all.fetch_verified(_doc(1), 60, {1: "https://files.openparldata.ch/doc/VD/x1"}, {})
    assert e.value.kind == "copy_sha_mismatch"


def test_no_copy_keeps_the_source_kind(stub):
    with pytest.raises(pdftext.FetchError) as e:
        replay_all.fetch_verified(_doc(3), 60, {}, {})
    assert e.value.kind == "robots_unreachable"


def test_coverage_phrase_accounts_for_every_document():
    s = dict(n=62, rederived=29, match=29, unreachable=9, not_reached_budget=24, read_via={"source": 21, "opd_copy": 8},
             unreachable_kinds={"robots_unreachable": 8, "timeout": 1})
    assert replay_all.coverage_phrase("P2 unseen", s) == (
        "P2 unseen re-derived 29/62, 29 match (29 read: 21 from the source, 8 from OPD's copy, sha256-checked); "
        "not re-derived: 9 unreachable (robots_unreachable 8, timeout 1), 24 over budget")
    assert sum(s.get(k, 0) for k in ("rederived", "cache_miss", "unreachable", "not_reached_budget")) == s["n"]
