"""PDF -> per-page text with stable character offsets. Shared by repair (verification), convert and the gold set.

A document is cached as WORK/pdf/<sha256>.pdf and its text as WORK/text/<sha256>.<extractor>.json:
  {"sha256":..., "extractor": "pdftotext-<poppler version>" | "tesseract-<ver>-<langs>", "pages": ["...", ...]}
Provenance spans are (page, char_start, char_end) into pages[page-1]. Full texts are never committed; only ids, URLs,
hashes and short quotes leave WORK.

Image-only PDFs (no text layer) are OCR'd with tesseract (deu+fra+ita) when `ocr=True`; the result says so in
`extractor`, so downstream code can type the value route as OCR.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from . import net
from .paths import PDF_CACHE, TEXT_CACHE

MIN_CHARS_PER_PAGE = 30  # below this on every page the PDF is treated as image-only


@lru_cache(maxsize=1)
def poppler_version() -> str:
    out = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True)
    m = re.search(r"version ([\d.]+)", out.stderr + out.stdout)
    return m.group(1) if m else "unknown"


@lru_cache(maxsize=1)
def tesseract_version() -> str:
    if not shutil.which("tesseract"):
        return "absent"
    out = subprocess.run(["tesseract", "--version"], capture_output=True, text=True)
    m = re.search(r"tesseract v?([\d.]+)", out.stdout + out.stderr)
    return m.group(1) if m else "unknown"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fetch_pdf(url: str, expect_sha256: str | None = None) -> tuple[str, Path]:
    """Download (politely) unless cached; return (sha256, path). If expect_sha256 is given and cached, no network."""
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    if expect_sha256:
        p = PDF_CACHE / f"{expect_sha256}.pdf"
        if p.exists():
            return expect_sha256, p
    b = net.get(url, timeout=180)
    if b"%PDF" not in b[:1024]:   # some servers prepend whitespace (Zürich city); HTML error pages have no marker
        raise ValueError(f"not a PDF: {url}")
    h = sha256_bytes(b)
    if expect_sha256 and h != expect_sha256:
        raise ValueError(f"sha256 mismatch for {url}: {h} != {expect_sha256}")
    p = PDF_CACHE / f"{h}.pdf"
    if not p.exists():
        p.write_bytes(b)
    return h, p


def _pdftotext_pages(path: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, check=True)
    txt = out.stdout.decode("utf-8", "replace")
    pages = txt.split("\f")
    if pages and pages[-1].strip() == "":
        pages = pages[:-1]
    return pages


def _ocr_pages(path: Path, langs: str = "deu+fra+ita", dpi: int = 200, max_pages: int | None = None) -> list[str]:
    pages = []
    with tempfile.TemporaryDirectory() as td:
        args = ["pdftoppm", "-r", str(dpi), "-gray", "-png"]
        if max_pages:
            args += ["-l", str(max_pages)]
        subprocess.run(args + [str(path), f"{td}/p"], check=True, capture_output=True)
        for img in sorted(Path(td).glob("p-*.png"), key=lambda p: int(p.stem.split("-")[-1])):
            o = subprocess.run(["tesseract", str(img), "-", "-l", langs], capture_output=True)
            pages.append(o.stdout.decode("utf-8", "replace"))
    return pages


def extract(sha: str, path: Path | None = None, ocr: bool = True, langs: str = "deu+fra+ita",
            max_ocr_pages: int | None = None) -> dict:
    """Return {"sha256", "extractor", "pages", "image_only"} (cached)."""
    TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    path = path or PDF_CACHE / f"{sha}.pdf"
    tag = f"pdftotext-{poppler_version()}"
    cp = TEXT_CACHE / f"{sha}.{tag}.json"
    if cp.exists():
        d = json.loads(cp.read_text())
    else:
        pages = _pdftotext_pages(path)
        d = dict(sha256=sha, extractor=tag, pages=pages,
                 image_only=all(len(p.strip()) < MIN_CHARS_PER_PAGE for p in pages))
        cp.write_text(json.dumps(d, ensure_ascii=False))
    if d["image_only"] and ocr and tesseract_version() != "absent":
        otag = f"tesseract-{tesseract_version()}-{langs}"
        op = TEXT_CACHE / f"{sha}.{otag}.json"
        if op.exists():
            return json.loads(op.read_text())
        pages = _ocr_pages(path, langs=langs, max_pages=max_ocr_pages)
        d = dict(sha256=sha, extractor=otag, pages=pages, image_only=True)
        op.write_text(json.dumps(d, ensure_ascii=False))
    return d


def span_text(doc: dict, page: int, start: int, end: int) -> str:
    return doc["pages"][page - 1][start:end]
