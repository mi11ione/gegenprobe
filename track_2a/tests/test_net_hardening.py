"""Timeouts, size caps and the GGUF re-check applied around the locked pdftext.py / llm.py (gegenprobe/hardening.py)."""
import hashlib
import time

import pytest

from gegenprobe import hardening, llm, pdftext


def test_hardening_is_installed_on_import():
    assert isinstance(pdftext.subprocess, hardening._SubprocessProxy)
    assert isinstance(pdftext.net, hardening._NetProxy)
    assert hasattr(llm.fetch_gguf, "__wrapped__")
    assert pdftext.subprocess.PIPE == __import__("subprocess").PIPE  # everything else passes through


def test_subprocess_timeout_becomes_a_typed_failure(monkeypatch):
    monkeypatch.setenv("GP_SUBPROCESS_TIMEOUT", "1")
    t = time.time()
    with pytest.raises(pdftext.FetchError) as e:
        pdftext.subprocess.run(["sleep", "5"], capture_output=True)
    assert e.value.kind == "text_timeout" and "sleep" in e.value.detail and time.time() - t < 4


def test_pdf_download_cap_is_a_typed_failure(monkeypatch, tmp_path):
    p = tmp_path / "huge.pdf"
    p.write_bytes(b"%PDF-" + b"0" * (1024 * 1024 + 10))
    monkeypatch.setenv("GP_MAX_PDF_MB", "1")
    with pytest.raises(pdftext.FetchError) as e:
        pdftext.net.get(p.as_uri())
    assert e.value.kind == "too_large"
    monkeypatch.setenv("GP_MAX_PDF_MB", "2")
    assert pdftext.net.get(p.as_uri()).startswith(b"%PDF-")


def test_time_budget():
    with pytest.raises(hardening.TimeBudgetExceeded):
        with hardening.time_budget(0.2):
            time.sleep(2)
    with hardening.time_budget(5):
        pass


def test_cached_gguf_is_rehashed_once_and_refused_on_mismatch(monkeypatch, tmp_path):
    f = tmp_path / "m.gguf"
    f.write_bytes(b"model bytes")
    good = hashlib.sha256(b"model bytes").hexdigest()
    calls = []

    def orig(name):
        calls.append(name)
        return f

    fetch = hardening._verified_gguf(orig)
    monkeypatch.setitem(llm.GGUF_PINS, "test-model", dict(sha256=good))
    assert fetch("test-model") == f and (tmp_path / "m.gguf.verified").exists()
    assert fetch("test-model") == f  # second call: marker hit
    f.write_bytes(b"tampered!!!")  # different content, same size
    monkeypatch.setitem(llm.GGUF_PINS, "test-model", dict(sha256=good))
    (tmp_path / "m.gguf.verified").write_text("stale")
    with pytest.raises(RuntimeError, match="pinned sha256"):
        fetch("test-model")
    assert not f.exists()
