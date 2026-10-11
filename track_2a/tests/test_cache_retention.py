"""GP_CACHE_MAX_AGE_DAYS (gegenprobe/cache_retention.py), `make ocr-models` (gegenprobe/ocr_models.py) and their wiring
into the nightly job and the Makefile. Temporary directories only; no download."""
import os
import time
from pathlib import Path

import pytest

from gegenprobe import cache_retention as CR
from gegenprobe import ocr_models as OM
from gegenprobe import ocrguard, paths

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400


def _file(p: Path, age_days: float, size: int = 10) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    t = time.time() - age_days * DAY
    os.utime(p, (t, t))
    return p


@pytest.fixture
def work(tmp_path, monkeypatch):
    pdf, text = tmp_path / "work" / "pdf", tmp_path / "work" / "text"
    monkeypatch.setattr(paths, "PDF_CACHE", pdf)
    monkeypatch.setattr(paths, "TEXT_CACHE", text)
    monkeypatch.delenv(CR.ENV, raising=False)
    f = dict(
        old_pdf=_file(pdf / f"{'a' * 64}.pdf", 31),
        new_pdf=_file(pdf / f"{'b' * 64}.pdf", 29),
        old_text=_file(text / f"{'a' * 64}.pdftotext-26.02.0.json", 40),
        old_ocr=_file(text / f"{'c' * 64}.tesseract-5.5.3-deu+fra+ita.json", 45),
        new_text=_file(text / f"{'b' * 64}.pdftotext-26.02.0.json", 1),
        other=_file(pdf / "notes.txt", 400),               # not a cache file name: never touched
        partial=_file(pdf / f"{'d' * 64}.pdf.part", 400),
        model=_file(tmp_path / "work" / "models" / "apertus.gguf", 400),
        state=_file(tmp_path / "work" / "nightly" / "state.json", 400),
    )
    return f


def test_default_30_days_deletes_only_old_cache_files(work):
    r = CR.enforce()
    assert r["max_age_days"] == 30 and r["deleted"] == 3 and r["kept"] == 2 and not r["errors"]
    gone = {k for k, p in work.items() if not p.exists()}
    assert gone == {"old_pdf", "old_text", "old_ocr"}
    assert r["bytes"] == 30


def test_setting_and_dry_run(work, monkeypatch):
    monkeypatch.setenv(CR.ENV, "35")
    r = CR.enforce(dry_run=True)
    assert r["max_age_days"] == 35 and r["deleted"] == 2 and r["dry_run"]
    assert all(p.exists() for p in work.values())  # dry run deletes nothing
    assert "would delete 2 files" in CR.summary(r)


def test_zero_disables_expiry(work, monkeypatch):
    monkeypatch.setenv(CR.ENV, "0")
    r = CR.enforce()
    assert r["disabled"] and r["deleted"] == 0 and all(p.exists() for p in work.values())
    assert "disabled" in CR.summary(r)


@pytest.mark.parametrize("bad", ["-1", "30d", "1.5"])
def test_malformed_setting_is_refused(work, monkeypatch, bad):
    monkeypatch.setenv(CR.ENV, bad)
    with pytest.raises(ValueError):
        CR.max_age_days()
    assert CR.main([]) == 2
    assert all(p.exists() for p in work.values())


def test_symlink_is_not_followed(work, tmp_path):
    target = _file(tmp_path / "elsewhere" / "keep.pdf", 400)
    link = paths.PDF_CACHE / f"{'e' * 64}.pdf"
    link.symlink_to(target)
    t = time.time() - 400 * DAY
    os.utime(link, (t, t), follow_symlinks=False)
    CR.enforce()
    assert target.exists() and link.is_symlink()


def test_refuses_committed_directories(monkeypatch):
    monkeypatch.setattr(paths, "PDF_CACHE", paths.DATA / "model_cache")
    with pytest.raises(ValueError, match="data/ or results/"):
        CR.enforce(days=30)


def test_cli(work, capsys):
    assert CR.main(["--max-age-days", "30", "--dry-run"]) == 0
    assert "would delete 3 files" in capsys.readouterr().out
    assert CR.main(["--max-age-days", "30"]) == 0
    assert not work["old_pdf"].exists() and work["new_pdf"].exists()


def test_nightly_enforces_it_on_network_nights():
    src = (ROOT / "src" / "gegenprobe" / "monitor" / "nightly.py").read_text()
    net_branch = src[src.index("        bad = fetchguard.ua_problem(ua[\"value\"])"):src.index("    transfer, idx = 0, None")]
    assert "cache_retention.enforce()" in net_branch  # before the night's first request
    assert "cache_retention=retention" in src  # reported in run.json


def test_make_targets():
    mk = (ROOT / "Makefile").read_text()
    assert "\ncache-clean:" in mk and "gegenprobe.cache_retention" in mk
    assert "\nocr-models:" in mk and "gegenprobe.ocr_models" in mk


# ------------------------------------------------------------------------------------------------ make ocr-models
def test_ocr_models_installs_missing_verifies_and_prints_export(tmp_path, monkeypatch, capsys):
    calls = []
    pinned = {lang: f"{lang}-bytes".encode() for lang in OM.LANGS}
    monkeypatch.setattr(ocrguard, "TESSDATA_SHA256", {k: __import__("hashlib").sha256(v).hexdigest()
                                                      for k, v in pinned.items()})
    (tmp_path / "deu.traineddata").write_bytes(pinned["deu"])  # already there with the pinned sha256: kept

    def installer(dest, langs=()):
        calls.append(tuple(langs))
        for lang in langs:
            Path(dest, f"{lang}.traineddata").write_bytes(pinned[lang])
        return [f"{lang} ok" for lang in langs]
    seen = {}

    def status(langs):
        seen.update(prefix=os.environ.get("TESSDATA_PREFIX"), pinned=os.environ.get("GP_OCR_REQUIRE_PINNED"))
        return dict(ok=True, tesseract="5.5.3", reason="")
    monkeypatch.setattr(ocrguard, "install_pinned", installer)
    monkeypatch.setattr(ocrguard, "status", status)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    assert OM.main([str(tmp_path)]) == 0
    assert calls == [("fra", "ita", "eng")]  # nothing re-downloaded that is already pinned
    assert seen == dict(prefix=str(tmp_path.resolve()), pinned="1")
    assert "TESSDATA_PREFIX" not in os.environ  # restored
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == f"export TESSDATA_PREFIX={tmp_path.resolve()}"
    calls.clear()
    assert OM.main([str(tmp_path)]) == 0 and calls == []  # second run: all pinned, no download


def test_ocr_models_fails_when_tesseract_cannot_use_them(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ocrguard, "TESSDATA_SHA256", {k: "0" * 64 for k in OM.LANGS})
    monkeypatch.setattr(ocrguard, "install_pinned", lambda dest, langs=(): [])
    assert OM.main([str(tmp_path)]) == 1  # files missing after the installer: sha256 check fails
    assert "sha256 differs" in capsys.readouterr().err
    monkeypatch.setattr(OM, "verified", lambda dest, langs=OM.LANGS: {x: True for x in langs})
    monkeypatch.setattr(ocrguard, "status", lambda langs: dict(ok=False, reason="tesseract is not installed"))
    assert OM.main([str(tmp_path)]) == 1
    assert "tesseract is not installed" in capsys.readouterr().err
