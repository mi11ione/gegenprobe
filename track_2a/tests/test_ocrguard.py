"""OCR fails loudly (gegenprobe/ocrguard.py, round-13 juror J5): a missing language pack, a non-zero tesseract exit or
an empty OCR result is FetchError('ocr_failed'), never a cached page of empty text; the language data is checked up
front, including the sha256 of the measured models. A fake `tesseract` on PATH stands in for the real one."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gegenprobe import ocrguard, pdftext

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("pdftoppm"), reason="poppler not installed")


def _blank_pdf() -> bytes:
    """A one-page PDF without a text layer (pdftotext finds nothing: image_only)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>",
            b"<< /Length 0 >>\nstream\n\nendstream"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake tesseract (version 5.5.3) whose languages, exit code and output come from files in tmp_path."""
    ocrguard.ensure()
    bin_, td = tmp_path / "bin", tmp_path / "tessdata"
    bin_.mkdir()
    td.mkdir()
    (bin_ / "tesseract").write_text(
        "#!/bin/sh\n"
        f'D="{tmp_path}"\n'
        'case "$1" in\n'
        '  --version) echo "tesseract 5.5.3"; exit 0;;\n'
        f'  --list-langs) echo "List of available languages in \\"{td}/\\" (9):"; cat "$D/langs"; exit 0;;\n'
        "esac\n"
        'cat "$D/out"; exit $(cat "$D/rc")\n')
    (bin_ / "tesseract").chmod(0o755)
    for k, v in dict(langs="deu\nfra\nita\neng\n", out="Risposta del Consiglio di Stato\n", rc="0").items():
        (tmp_path / k).write_text(v)
    for lang in ("deu", "fra", "ita"):
        (td / f"{lang}.traineddata").write_bytes(f"fake {lang}".encode())
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("TESSDATA_PREFIX", str(td))
    monkeypatch.delenv("GP_OCR_REQUIRE_PINNED", raising=False)
    monkeypatch.setattr(pdftext, "TEXT_CACHE", tmp_path / "text")
    for m in (ocrguard, sys.modules.get("_gegenprobe_ocrguard")):
        if m is not None:
            m._memo.clear()
    pdftext.tesseract_version.cache_clear()
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(_blank_pdf())
    sha = pdftext.sha256_bytes(pdf.read_bytes())
    yield dict(dir=tmp_path, td=td, pdf=pdf, sha=sha, cache=tmp_path / "text" / f"{sha}.tesseract-5.5.3-deu+fra+ita.json")
    pdftext.tesseract_version.cache_clear()


def test_installed_in_this_process():
    assert ocrguard.installed(pdftext)


def test_ocr_ok_is_cached_with_model_fingerprint(env):
    d = pdftext.extract(env["sha"], env["pdf"])
    assert d["image_only"] and d["extractor"] == "tesseract-5.5.3-deu+fra+ita" and "Risposta" in d["pages"][0]
    assert d["tessdata"]["pinned"] is False and set(d["tessdata"]["sha256"]) == {"deu", "fra", "ita"}
    assert json.loads(env["cache"].read_text())["pages"] == d["pages"]


def test_missing_language_pack_is_ocr_failed_and_nothing_cached(env):
    (env["dir"] / "langs").write_text("eng\nosd\n")  # e.g. Homebrew's tesseract without tesseract-lang
    with pytest.raises(pdftext.FetchError) as e:
        pdftext.extract(env["sha"], env["pdf"])
    assert e.value.kind == "ocr_failed" and "deu+fra+ita" in e.value.detail
    assert not env["cache"].exists()
    st = ocrguard.status()
    assert not st["ok"] and st["missing"] == ["deu", "fra", "ita"]


def test_cached_text_is_still_served_without_language_data(env):
    pdftext.extract(env["sha"], env["pdf"])
    (env["dir"] / "langs").write_text("eng\n")
    for m in (ocrguard, sys.modules.get("_gegenprobe_ocrguard")):
        if m is not None:
            m._memo.clear()
    assert "Risposta" in pdftext.extract(env["sha"], env["pdf"])["pages"][0]  # reading a cache needs no OCR


def test_nonzero_exit_is_ocr_failed_and_nothing_cached(env):
    (env["dir"] / "rc").write_text("1")
    (env["dir"] / "out").write_text("")
    with pytest.raises(pdftext.FetchError) as e:
        pdftext.extract(env["sha"], env["pdf"])
    assert e.value.kind == "ocr_failed" and "exited 1" in e.value.detail
    assert not env["cache"].exists()


def test_empty_ocr_is_ocr_failed(env):
    (env["dir"] / "out").write_text("  \n")
    with pytest.raises(pdftext.FetchError) as e:
        pdftext.extract(env["sha"], env["pdf"])
    assert e.value.kind == "ocr_failed" and "no text" in e.value.detail
    assert not env["cache"].exists()


def test_poisoned_cache_from_before_the_guard_is_redone(env):
    env["cache"].parent.mkdir(parents=True, exist_ok=True)
    env["cache"].write_text(json.dumps(dict(sha256=env["sha"], extractor="tesseract-5.5.3-deu+fra+ita", pages=[""],
                                            image_only=True)))
    d = pdftext.extract(env["sha"], env["pdf"])
    assert "Risposta" in d["pages"][0] and "Risposta" in env["cache"].read_text()


def test_cache_from_other_models_is_redone(env):
    pdftext.extract(env["sha"], env["pdf"])
    (env["td"] / "deu.traineddata").write_bytes(b"other deu model")
    (env["dir"] / "out").write_text("Antwort des Regierungsrates\n")
    for m in (ocrguard, sys.modules.get("_gegenprobe_ocrguard")):
        if m is not None:
            m._memo.clear()
    assert "Antwort" in pdftext.extract(env["sha"], env["pdf"])["pages"][0]


def test_tesseract_absent_is_ocr_failed(env, monkeypatch):
    monkeypatch.setenv("PATH", str(env["dir"] / "nothing"))
    monkeypatch.setattr(pdftext, "poppler_version", lambda: "test")
    monkeypatch.setattr(pdftext, "_pdftotext_pages", lambda p: [""])
    pdftext.tesseract_version.cache_clear()
    with pytest.raises(pdftext.FetchError) as e:
        pdftext.extract(env["sha"], env["pdf"])
    assert e.value.kind == "ocr_failed" and "not installed" in e.value.detail
    assert pdftext.extract(env["sha"], env["pdf"], ocr=False)["pages"] == [""]  # no OCR asked: the text layer as before


def test_unpinned_models_refused_when_pinning_required(env, monkeypatch):
    monkeypatch.setenv("GP_OCR_REQUIRE_PINNED", "1")
    with pytest.raises(pdftext.FetchError) as e:
        pdftext.extract(env["sha"], env["pdf"])
    assert e.value.kind == "ocr_failed" and "TESSDATA_SHA256" in e.value.detail


def test_pinned_models_match_the_measured_set(env, monkeypatch):
    """The real tessdata_fast files, where a developer has them (WORK/tessdata), hash to TESSDATA_SHA256."""
    real = Path(os.environ.get("GP_WORK", ROOT / ".work")) / "tessdata"
    if not (real / "deu.traineddata").exists():
        pytest.skip("no local tessdata_fast copy")
    monkeypatch.setenv("TESSDATA_PREFIX", str(real))
    for lang in ("deu", "fra", "ita"):
        shutil.copyfile(real / f"{lang}.traineddata", env["td"] / f"{lang}.traineddata")
    st = ocrguard.status()
    assert st["ok"] and st["pinned"] and st["sha256"] == {k: ocrguard.TESSDATA_SHA256[k] for k in ("deu", "fra", "ita")}


def test_convert_cli_types_the_failure():
    from gegenprobe.convert import output

    e = pdftext.FetchError("ocr_failed", "tesseract has no language data for deu")
    kind, reason = output.classify(e)
    assert output.failure_row(kind, reason, {})["status"] == "ocr_failed"


def test_dockerfile_pins_the_measured_models():
    """The image downloads exactly the measured tessdata_fast files and verifies each against TESSDATA_SHA256."""
    df = (ROOT / "Dockerfile").read_text()
    assert ocrguard.TESSDATA_COMMIT in df and "GP_OCR_REQUIRE_PINNED=1" in df
    assert "TESSDATA_PREFIX=/usr/local/share/tessdata-pinned" in df
    assert "ocrguard.py install-pinned \"$TESSDATA_PREFIX\"" in df  # the pins are ocrguard's own table, one source
    assert "tesseract-ocr-deu" not in df  # Debian's unpinned models are no longer installed
    assert set(ocrguard.TESSDATA_SHA256) == {"deu", "fra", "ita", "eng"}


def test_install_pinned_refuses_a_wrong_file(tmp_path, monkeypatch):
    import io
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: io.BytesIO(b"not the model"))
    with pytest.raises(SystemExit, match="sha256"):
        ocrguard.install_pinned(str(tmp_path), langs=("deu",))
    assert not (tmp_path / "deu.traineddata").exists()


def test_guard_is_booted_by_sitecustomize_in_a_fresh_interpreter():
    code = ("from gegenprobe import pdftext; import sys; "
            "print(getattr(pdftext.extract, '_gegenprobe_ocrguard', False), '_gegenprobe_ocrguard' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                         env=dict(os.environ, PYTHONPATH=f"{ROOT / 'src'}{os.pathsep}{ROOT}"))
    assert out.stdout.split() == ["True", "True"], out.stderr
