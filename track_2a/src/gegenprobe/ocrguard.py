"""OCR fails loudly: a scan whose OCR did not run is a typed failure (`ocr_failed`), never a page of empty text.

gegenprobe/pdftext.py is locked (LOCK2-5). Its `_ocr_pages` ignores tesseract's exit code, so a tesseract without the
deu/fra/ita language data returns exit 1 and empty pages; `extract` then caches those empty pages under a tag that still
says `tesseract-<ver>-deu+fra+ita`, and every scan downstream becomes a typed null that looks like a real reading
(round-13 juror J5). This module fixes that at runtime WITHOUT editing the locked file, the same way hardening.py adds
timeouts (`patch(pdftext)`; idempotent):

  language data checked up front   before OCR, `tesseract --list-langs` must list every requested language (deu, fra,
                                   ita by default); otherwise pdftext.FetchError("ocr_failed", "...missing: deu ...")
  pinned models                    each language file's sha256 is compared with TESSDATA_SHA256 (tessdata_fast at
                                   TESSDATA_COMMIT, the models the OCR numbers were measured with). A difference is
                                   recorded in the result (`tessdata.pinned` false); with GP_OCR_REQUIRE_PINNED=1 (set in
                                   the Docker image, which ships the pinned files) it is an `ocr_failed` instead
  exit code checked                a non-zero tesseract exit on any page raises `ocr_failed` with tesseract's message
  no empty OCR                     OCR that recognises no character on any page raises `ocr_failed`
  never cached on failure          the locked extract writes its cache only after `_ocr_pages` returns, so a failure
                                   leaves no cache file; a cached OCR result with no text on any page (written before
                                   this guard) is deleted and redone; one recorded with other models is redone too.
                                   A cached result with text is still served where OCR cannot run (reading a cache needs
                                   no OCR); under GP_OCR_REQUIRE_PINNED=1 only one recorded with the pinned models is.
  tesseract absent                 OCR requested on an image-only PDF without tesseract raises `ocr_failed` instead of
                                   returning the empty text layer

`ocr_failed` is a pdftext.FetchError kind, so the convert CLI writes a typed failure row (convert/output.py FAILURE_KINDS)
and every caller that already handles FetchError (text_timeout, too_large) handles it. A successful OCR result is the
same dict as before plus `tessdata` = {"dir", "sha256": {lang: sha}, "pinned": bool}; the `extractor` tag is unchanged.

Installed in every process: src/sitecustomize.py patches gegenprobe.pdftext the moment it is imported (src/ is on
PYTHONPATH for make run, Docker, CI and the nightly units), and `ensure()` is called by the unlocked entry points
(gegenprobe.run, python -m gegenprobe, eval/rederive.py, monitor/nightly.py) for installs without sitecustomize.

`status(langs)` answers "can OCR run here, and with which models" without OCRing anything (used by eval/rederive.py and
`python -m gegenprobe.ocrguard`).

Stdlib only and free of package-relative imports: sitecustomize loads this file by path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIND = "ocr_failed"
_MARK = "_gegenprobe_ocrguard"
DEFAULT_LANGS = "deu+fra+ita"
# The OCR numbers (docs/repair.md, P1/P2 scanned strata) were measured with Tesseract 5.5.3 and these tessdata_fast models.
TESSDATA_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
TESSDATA_SHA256 = {
    "deu": "19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d",
    "fra": "ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca",
    "ita": "b8f89e1e785118dac4d51ae042c029a64edb5c3ee42ef73027a6d412748d8827",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}
_sha_cache: dict[tuple, str] = {}


def _run(args, **kw):
    """subprocess.run through gegenprobe.pdftext's (hardened, time-limited) subprocess when it is loaded."""
    sp = getattr(sys.modules.get("gegenprobe.pdftext"), "subprocess", None) or subprocess
    return sp.run(args, **kw)


def _sha256(p: Path) -> str:
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime_ns)
    if key not in _sha_cache:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while b := f.read(1 << 20):
                h.update(b)
        _sha_cache[key] = h.hexdigest()
    return _sha_cache[key]


def status(langs: str = DEFAULT_LANGS) -> dict:
    """{"ok", "reason", "tesseract", "dir", "available", "missing", "sha256", "pinned", "unpinned"} for these languages.
    ok is False when tesseract is absent or a language is missing (or, under GP_OCR_REQUIRE_PINNED=1, a model differs
    from TESSDATA_SHA256). Never raises."""
    want = [x for x in langs.split("+") if x]
    r = dict(ok=False, reason="", tesseract=None, dir=None, available=[], missing=want, sha256={}, pinned=None,
             unpinned=[], require_pinned=os.environ.get("GP_OCR_REQUIRE_PINNED") == "1")
    exe = shutil.which("tesseract")
    if not exe:
        r["reason"] = "tesseract is not installed"
        return r
    try:
        v = _run([exe, "--version"], capture_output=True, text=True)
        m = re.search(r"tesseract v?([\d.]+)", (v.stdout or "") + (v.stderr or ""))
        r["tesseract"] = m.group(1) if m else "unknown"
        o = _run([exe, "--list-langs"], capture_output=True, text=True)
    except Exception as e:  # noqa: BLE001  (a broken binary is a reason, not a crash)
        r["reason"] = f"tesseract could not be run: {type(e).__name__}: {e}"
        return r
    out = (o.stdout or "") + "\n" + (o.stderr or "")
    m = re.search(r'languages in "([^"]+)"', out)
    r["dir"] = m.group(1).rstrip("/") if m else os.environ.get("TESSDATA_PREFIX")
    r["available"] = sorted({ln.strip() for ln in (o.stdout or "").splitlines()[1:] if re.fullmatch(r"[\w-]+", ln.strip())})
    r["missing"] = [x for x in want if x not in r["available"]]
    if r["missing"]:
        r["reason"] = (f"tesseract {r['tesseract']} has no language data for {'+'.join(r['missing'])} "
                       f"(looked in {r['dir']}); install tessdata_fast {', '.join(r['missing'])} and set TESSDATA_PREFIX "
                       "(docs/runbook.md, OCR)")
        return r
    for x in want:
        f = Path(r["dir"] or "") / f"{x}.traineddata"
        if f.is_file():
            r["sha256"][x] = _sha256(f)
    r["unpinned"] = [x for x in want if x in TESSDATA_SHA256 and r["sha256"].get(x) != TESSDATA_SHA256[x]]
    r["pinned"] = not r["unpinned"]
    if r["unpinned"] and r["require_pinned"]:
        r["reason"] = (f"language data for {'+'.join(r['unpinned'])} in {r['dir']} differs from the measured "
                       f"tessdata_fast@{TESSDATA_COMMIT[:7]} models (TESSDATA_SHA256) and GP_OCR_REQUIRE_PINNED=1")
        return r
    r["ok"] = True
    return r


_memo: dict[tuple, dict] = {}


def _status_memo(langs: str) -> dict:
    """status() once per process and configuration (tesseract path, TESSDATA_PREFIX, GP_OCR_REQUIRE_PINNED, langs)."""
    key = (langs, shutil.which("tesseract"), os.environ.get("TESSDATA_PREFIX"), os.environ.get("GP_OCR_REQUIRE_PINNED"))
    if key not in _memo:
        _memo[key] = status(langs)
    return _memo[key]


def _fail(pdftext, detail: str):
    return pdftext.FetchError(KIND, detail)


def _cache_usable(td: dict | None, st: dict) -> bool:
    """A cached OCR result with text is served when it was made with the models installed now, or when it predates the
    guard (no `tessdata` record) or OCR cannot run here (reading a cache needs no OCR). Under GP_OCR_REQUIRE_PINNED=1
    only a result recorded with the pinned models is served."""
    if st.get("require_pinned"):
        return bool(td and td.get("pinned"))
    if td is None or not st["ok"]:
        return True
    return td.get("sha256") == st["sha256"]


def _has_text(d: dict) -> bool:
    return any(p.strip() for p in d.get("pages") or [])


def patch(pdftext) -> None:
    """Wrap pdftext._ocr_pages and pdftext.extract (idempotent)."""
    if getattr(pdftext.extract, _MARK, False):
        return
    orig_extract = pdftext.extract

    def _ocr_pages(path, langs: str = DEFAULT_LANGS, dpi: int = 200, max_pages: int | None = None) -> list[str]:
        pages = []
        with tempfile.TemporaryDirectory() as td:
            args = ["pdftoppm", "-r", str(dpi), "-gray", "-png"]
            if max_pages:
                args += ["-l", str(max_pages)]
            pdftext.subprocess.run(args + [str(path), f"{td}/p"], check=True, capture_output=True)
            imgs = sorted(Path(td).glob("p-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
            if not imgs:
                raise _fail(pdftext, f"pdftoppm rendered no page of {Path(path).name}")
            for i, img in enumerate(imgs, 1):
                o = pdftext.subprocess.run(["tesseract", str(img), "-", "-l", langs], capture_output=True)
                if o.returncode != 0:
                    err = o.stderr.decode("utf-8", "replace").strip().splitlines()
                    raise _fail(pdftext, f"tesseract -l {langs} exited {o.returncode} on page {i} of {Path(path).name}: "
                                         f"{' | '.join(err[-2:])[:300]}")
                pages.append(o.stdout.decode("utf-8", "replace"))
        if not any(p.strip() for p in pages):
            raise _fail(pdftext, f"tesseract -l {langs} recognised no text on any of {len(pages)} pages of "
                                 f"{Path(path).name}")
        return pages

    def extract(sha: str, path=None, ocr: bool = True, langs: str = DEFAULT_LANGS, max_ocr_pages: int | None = None):
        d = orig_extract(sha, path, ocr=False, langs=langs, max_ocr_pages=max_ocr_pages)
        if not (ocr and d["image_only"]):
            return d
        if pdftext.tesseract_version() == "absent":
            raise _fail(pdftext, f"{sha[:12]} is an image-only PDF and tesseract is not installed")
        op = Path(pdftext.TEXT_CACHE) / f"{sha}.tesseract-{pdftext.tesseract_version()}-{langs}.json"
        st = _status_memo(langs)
        if op.exists():
            try:
                c = json.loads(op.read_text())
            except ValueError:
                c = {}
            td = c.get("tessdata")
            if _has_text(c) and _cache_usable(td, st):
                return c
            if not _has_text(c) or st["ok"]:
                op.unlink()  # empty OCR cached before this guard, or recorded with other models: redo
        if not st["ok"]:
            raise _fail(pdftext, st["reason"])
        info = dict(dir=st["dir"], sha256=st["sha256"], pinned=st["pinned"])
        c = orig_extract(sha, path, ocr=True, langs=langs, max_ocr_pages=max_ocr_pages)  # raises before caching
        c["tessdata"] = info
        op.write_text(json.dumps(c, ensure_ascii=False))
        return c

    for f, o in ((_ocr_pages, pdftext._ocr_pages), (extract, orig_extract)):
        f.__wrapped__ = o
        f.__doc__ = (o.__doc__ or "") + " [ocrguard: OCR failures raise FetchError('ocr_failed')]"
        setattr(f, _MARK, True)
    pdftext._ocr_pages = _ocr_pages
    pdftext.extract = extract


def installed(pdftext) -> bool:
    return bool(getattr(pdftext.extract, _MARK, False) and getattr(pdftext._ocr_pages, _MARK, False))


def ensure() -> bool:
    """Patch gegenprobe.pdftext in this process if interpreter start did not (idempotent, never raises)."""
    try:
        from gegenprobe import pdftext
        from gegenprobe.compliance import fetchguard

        fetchguard.ensure()  # pdftext fetches through gegenprobe.net: never without the RFC 9309 matcher
        patch(pdftext)
        return installed(pdftext)
    except Exception as e:  # noqa: BLE001
        print(f"[gegenprobe] OCR guard NOT installed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def install_pinned(dest: str, langs=("deu", "fra", "ita", "eng"), timeout: int = 120) -> list[str]:
    """Download the measured tessdata_fast models (TESSDATA_COMMIT) into `dest` and verify each sha256 against
    TESSDATA_SHA256; raise on any mismatch, writing nothing for that file. Build-time only (Dockerfile): a dependency
    download from GitHub like pip's, not a document fetch, so it does not go through gegenprobe.net."""
    import urllib.request

    os.makedirs(dest, exist_ok=True)
    done = []
    for lang in langs:
        url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{TESSDATA_COMMIT}/{lang}.traineddata"
        req = urllib.request.Request(url, headers={"User-Agent": os.environ.get("GP_USER_AGENT", "hackapertus-research/0.1")})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
        got = hashlib.sha256(b).hexdigest()
        if got != TESSDATA_SHA256[lang]:
            raise SystemExit(f"{lang}.traineddata from {url}: sha256 {got}, expected {TESSDATA_SHA256[lang]}")
        Path(dest, f"{lang}.traineddata").write_bytes(b)
        done.append(f"tessdata_fast@{TESSDATA_COMMIT[:7]} {lang}.traineddata {len(b)} bytes, sha256 ok")
    return done


if __name__ == "__main__":
    # python -m gegenprobe.ocrguard [langs]             can OCR run here, with the measured models? (exit 1 if not)
    # python -m gegenprobe.ocrguard install-pinned DIR  download + verify the measured models into DIR (Dockerfile)
    if len(sys.argv) > 2 and sys.argv[1] == "install-pinned":
        print("\n".join(install_pinned(sys.argv[2])))
        sys.exit(0)
    s = status(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LANGS)
    print(json.dumps(s, indent=1))
    sys.exit(0 if s["ok"] else 1)
