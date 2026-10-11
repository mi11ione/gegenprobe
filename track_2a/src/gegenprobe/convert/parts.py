"""Document parts by rule (no model): annexes, tables, images and scanned pages of one document, as schema `DocumentPart`s.

    python -m gegenprobe.convert.parts <file.pdf>      print the parts of one PDF as JSON (no network, no model)

What is detected (PARTS_VERSION), each with a page range and a typed `kind` of the schema's PartKind:
  * annex          an annex section: a line that is an annex heading (Anhang / Anhänge / Beilage / Anlage n / Annexe /
                   Annex / Allegato / Appendice / Appendix, with a number, or alone at the top of a page, or followed by
                   ':' and a title), running to the page before the next annex heading or to the end of the document;
                   and the pages that follow an attachment list ("Beilagen:", "Annexes :", "Allegati:") in the lower half
                   of a page when no annex heading follows. An attachment list on the last page names annexes that are
                   not in the document: it is reported as a signal (`attachment_lists`), never as a part.
  * table          a block of >= 3 rows in `pdftotext -layout` with >= 3 cells per row (cells separated by >= 2 spaces,
                   none of six or more words, at least one gap of >= 3 spaces: a justified sentence is not a row) and
                   >= 2 columns aligned (cell starts or ends within 2 characters) in at least half of the rows.
  * budget_table   such a table whose header names accounts, budget or accounts years (Konto, Budget, Voranschlag,
                   RE 2023, BU 2025, compte, preventivo, ...).
  * signature      (a) such a block whose cells are mostly person names (a list of signatories printed in columns);
                   (b) an embedded image of < 12% of the page in the lower 60% of the document's last page (a handwritten
                   signature or a seal set as a picture; the schema's `stamp` is not told apart from it).
  * image          (a) an embedded image covering >= 2% of the page, below the letterhead band (top 15%; a small image
                   starting in the top fifth is a logo) and above the footer band (bottom 8%), not repeated at the same
                   place on another page (logos, letterheads), and not in the signature block;
                   (b) scanned pages: an image covering >= 85% of the page at >= 100 ppi (consecutive pages merged; a scanner's
                   mixed-raster output keeps a 100 ppi page background under 200-300 ppi text masks; a 72 ppi page
                   background of a word-processor PDF is not a scan).
Table blocks of one page at most 4 lines apart with no blank or prose line between them are one table (a header
of wrapped cells, a total row).
The text of a table, an annex or an image is never extracted: a part carries its page range, and the detection record
carries the character span in the document's cached text (the text the record's other spans point into) and the sha256
of the text at the span where it can be located (tables and annex headings), so a reviewer can check it.

Known limits (by construction; the blind check in eval/parts measures them): tables drawn without aligned columns in the
layout text (wrapped cells, one cell per line) and tables inside a scanned page are missed; charts drawn as vector graphics
are not images to this detector; a table embedded as a picture is reported as an image.

Federal texts (OPD's texts export, HTML, no PDF) go through `detect_html`: <table> elements are tables, <img> elements
images, and the annex rules run on the plain text.
"""
from __future__ import annotations

import hashlib
import html as H
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

PARTS_VERSION = "parts-1"
DETECTOR = (f"{PARTS_VERSION} (annex headings and attachment lists; aligned-column tables in pdftotext -layout; embedded "
            "images >= 2% of a page outside the letterhead and footer bands; scanned pages >= 85% of a page at >= 100 ppi)")
TIMEOUT = 120

MIN_ROWS, MIN_CELLS, ALIGN_TOL = 3, 3, 2
IMG_MIN_AREA, SCAN_MIN_AREA, SCAN_MIN_PPI = 0.02, 0.85, 100  # MRC scans keep a 100 ppi page background
TOP_BAND, FOOT_BAND = 0.15, 0.92
LOGO_TOP, LOGO_MAX_AREA = 0.20, 0.05  # a small image starting in the top fifth of a page: a letterhead logo
SIG_TOP, SIG_MAX_AREA = 0.40, 0.12  # a small image in the lower 60% of the last page: the signature block
MERGE_GAP = 4  # table blocks of one page at most this many lines apart, with no blank or prose line between, are one table

_KW = (r"Anh[aä]ng|Anh[aä]nge|Beilagen?|Anlagen?|Annexes?|Annex|Allegat[oi]|Appendices?|Appendice|Appendix")
_NUM = r"(?:Nr\.?\s*|n[°o]\.?\s*)?(?:\d{1,2}(?:\.\d{1,2})?|[IVX]{1,4}|[A-H])"
# a heading: keyword + number (+ optional ':'/'-' and a title), or keyword + ':' + title, or the keyword alone
HEADING = re.compile(rf"^(?P<kw>{_KW})(?:\s+(?P<num>{_NUM}))?\s*(?:(?P<sep>[:.–—-])\s*(?P<title>.{{0,160}}))?$")
# an attachment list: the keyword (no number) and a colon, then items on the same line or the next lines
ATTACH = re.compile(r"^(?P<kw>Beilagen?|Anlagen?|Anh[aä]nge|Annexes?|Allegat[oi]|Pi[eè]ces?\s+jointes?|Appendices?)"
                    r"\s*:\s*(?P<rest>.*)$")
BARE_OK = re.compile(r"^(Anh[aä]ng|Anh[aä]nge|Annexes?|Annex|Allegat[oi]|Appendice|Appendix|Beilagen?)$")
# in-text references to annexes (signals for the sanity check; never parts)
REFERENCE = re.compile(
    r"(?i)\b(?:siehe|vgl\.?|gem[aä]ss|laut|in|im|den|der|voir|cf\.?|en|dans\s+l['’]|cfr\.?|vedi|nell['’]|nel|in)\s+"
    r"(?:den\s+|der\s+)?(?:Anh[aä]ng(?:en|e)?|Beilagen?|annexes?|allegat[oi])\b|\b(?:beiliegend|ci-joint|ci-jointe?s?|"
    r"en\s+annexe|in\s+allegato|als\s+Beilage|im\s+Anhang)\b")
BUDGET = re.compile(r"(?i)\b(Konto|Budget|Voranschlag|Rechnung\s+\d{4}|Finanzplan|Kredit|(?:RE|BU|VA|R|B)\s?\d{2,4}|"
                    r"compte|comptes|preventivo|consuntivo|conto)\b")
NAME = re.compile(r"^[A-ZÀ-Ý][\w'’.\-]+(?:[ -][A-ZÀ-Ý][\w'’.\-]+){1,3}$")
_CELL = re.compile(r"\S+(?: \S+)*")  # cells of a layout line: runs separated by >= 2 spaces


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _run(args: list[str], text: bool = True) -> str:
    out = subprocess.run(args, capture_output=True, timeout=TIMEOUT, check=False)
    return out.stdout.decode("utf-8", "replace") if text else out.stdout


# ----------------------------------------------------------------------------------------------------------- tables
def _prose(cell: str) -> bool:
    """Six or more words, at least five of them starting with a letter: a sentence, not a table cell (a run of numbers
    set one space apart is not prose)."""
    toks = cell.split()
    return len(toks) >= 6 and sum(t[:1].isalpha() for t in toks) >= 5


def _cells(line: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in _CELL.finditer(line)]


def _aligned_columns(rows: list[list[tuple[int, int, str]]]) -> int:
    """Columns (beyond each row's first cell) whose starts or ends line up within ALIGN_TOL in at least half the rows."""
    need = max(2, (len(rows) + 1) // 2)
    seen: list[tuple[str, int]] = []
    n = 0
    for edge in ("start", "end"):
        pos = sorted(c[0] if edge == "start" else c[1] for r in rows for c in r[1:])
        i = 0
        while i < len(pos):
            j = i
            while j + 1 < len(pos) and pos[j + 1] - pos[i] <= 2 * ALIGN_TOL:
                j += 1
            centre = pos[(i + j) // 2]
            hit = sum(any(abs((c[0] if edge == "start" else c[1]) - centre) <= ALIGN_TOL for c in r[1:]) for r in rows)
            if hit >= need and not any(abs(centre - p) <= ALIGN_TOL + 1 for e, p in seen if e != edge):
                n += 1
                seen.append((edge, centre))
            i = j + 1
    return n


def table_blocks(layout_page: str) -> list[dict]:
    """Aligned-column blocks of one page of `pdftotext -layout` text: line range, rows, columns, cells of the first/last row."""
    lines = layout_page.split("\n")
    blocks, cur, gap = [], [], 0

    def close():
        if len(cur) >= MIN_ROWS:
            rows = [c for _, c in cur]
            if _aligned_columns(rows) >= 2:
                blocks.append(dict(line_from=cur[0][0], line_to=cur[-1][0], rows=len(cur),
                                   columns=max(len(r) for r in rows), cells=rows))

    for i, ln in enumerate(lines):
        c = _cells(ln)
        if len(c) >= MIN_CELLS and not any(_prose(x[2]) for x in c) and max(
                b[0] - a[1] for a, b in zip(c, c[1:])) >= 3:
            cur.append((i, c))
            gap = 0
        elif cur and gap < 1:
            gap += 1  # one wrapped or blank line inside a table
        else:
            close()
            cur, gap = [], 0
    close()
    merged: list[dict] = []
    def joinable(a: dict, b: dict) -> bool:
        between = lines[a["line_to"] + 1: b["line_from"]]
        return (b["line_from"] - a["line_to"] <= MERGE_GAP and all(x.strip() for x in between)
                and not any(_prose(c[2]) for x in between for c in _cells(x)))

    for b in blocks:
        if merged and joinable(merged[-1], b):
            m = merged[-1]
            m.update(line_to=b["line_to"], rows=m["rows"] + b["rows"], columns=max(m["columns"], b["columns"]),
                     cells=m["cells"] + b["cells"])
        else:
            merged.append(b)
    return merged


def _kind_of_block(b: dict, lines: list[str]) -> str:
    cells = [c[2] for r in b["cells"] for c in r]
    digits = sum(any(ch.isdigit() for ch in x) for x in cells)
    if cells and digits <= 0.1 * len(cells) and sum(bool(NAME.match(x)) for x in cells) >= 0.6 * len(cells):
        return "signature"
    head = " ".join(lines[max(0, b["line_from"] - 2): b["line_from"] + 2])
    if BUDGET.search(head) and sum(any(ch.isdigit() for ch in x) for x in cells) >= len(cells) / 3:
        return "budget_table"
    return "table"


def _phrase(s: str) -> re.Pattern | None:
    toks = s.split()
    return re.compile(r"\s+".join(map(re.escape, toks))) if toks else None


def locate(page_text: str, first: str, last: str, approx_len: int, start: int = 0,
           first_row: str | None = None) -> tuple[int, int] | None:
    """Character span in the cached page text from the block's first cell (its whole first row when the text keeps it on
    one line) to its last cell, searched from `start` (the end of the page's previous table), when both are found in
    order and the span is not implausibly long; None otherwise (the part then points to the page only)."""
    a, b = _phrase(first), _phrase(last)
    if a is None or b is None:
        return None
    m = (_phrase(first_row).search(page_text, start) if first_row else None) or a.search(page_text, start)
    if not m:
        return None
    ends = [x.end() for x in b.finditer(page_text, m.start())]
    ends = [e for e in ends if e - m.start() <= 3 * approx_len + 200]
    if not ends:
        return None
    return m.start(), ends[-1]


# ----------------------------------------------------------------------------------------------------------- annexes
def _lines_with_offsets(page: str) -> list[tuple[int, str]]:
    out, pos = [], 0
    for ln in page.split("\n"):
        out.append((pos, ln))
        pos += len(ln) + 1
    return out


def annex_signals(pages: list[str]) -> dict:
    """Annex headings, attachment lists and in-text references in the cached page texts (1-based pages)."""
    heads, lists, refs = [], [], []
    for p, text in enumerate(pages, 1):
        lines = _lines_with_offsets(text)
        nonempty = [i for i, (_, ln) in enumerate(lines) if ln.strip()]
        top = set(nonempty[:5])
        half = nonempty[len(nonempty) // 2] if nonempty else 0
        cands = []
        for i, (off, ln) in enumerate(lines):
            s = ln.strip()
            if not s or len(s) > 170:
                continue
            lead = off + len(ln) - len(ln.lstrip())
            m = HEADING.match(s)
            a = ATTACH.match(s)
            if m and m.group("kw").lower().startswith("anlage") and not m.group("num"):
                m = None  # "Anlage(n)" alone is too often a word ("installation"): only "Anlage 1"
            if m and not m.group("num"):
                if m.group("sep") == ":" and m.group("title"):
                    m = None  # keyword + ':' + text without a number is an attachment list ("Beilage: Bericht")
                elif not (BARE_OK.match(m.group("kw")) and (m.group("sep") is None or not m.group("title")) and i in top):
                    m = None
            if m and m.group("title") and m.group("title")[:1].islower():
                m = None  # "Anhang 2 zur Verordnung ..." inside a sentence
            if m:
                label = f"{m.group('kw')} {m.group('num')}".strip() if m.group("num") else m.group("kw")
                cands.append(dict(page=p, line=i, char_start=lead, char_end=lead + len(s), label=label,
                                  quote_sha256=sha(s), at_top=i in top))
            elif a:
                lists.append(dict(page=p, line=i, char_start=lead, char_end=lead + len(s), keyword=a.group("kw"),
                                  lower_half=i >= half, quote_sha256=sha(s)))
        # several numbered "headings" within a few lines of each other are the items of a list, not headings
        for c in cands:
            near = [d for d in cands if d is not c and abs(d["line"] - c["line"]) <= 4]
            if near and not c["at_top"]:
                lists.append(dict(page=p, line=c["line"], char_start=c["char_start"], char_end=c["char_end"],
                                  keyword=c["label"], lower_half=c["line"] >= half, quote_sha256=c["quote_sha256"]))
            else:
                heads.append(c)
        for m in REFERENCE.finditer(text):
            refs.append(dict(page=p, char_start=m.start(), char_end=m.end()))
    return dict(headings=heads, attachment_lists=lists, references=refs)


def annex_parts(sig: dict, n_pages: int) -> list[dict]:
    heads = sorted(sig["headings"], key=lambda h: (h["page"], h["line"]))
    parts = []
    for i, h in enumerate(heads):
        if i + 1 < len(heads):
            nxt = heads[i + 1]
            to = max(h["page"], nxt["page"] - 1 if nxt["at_top"] else nxt["page"])
        else:
            to = n_pages
        parts.append(dict(kind="annex", page_from=h["page"], page_to=max(h["page"], to), subtype="heading",
                          rule=f"{PARTS_VERSION}:annex-heading",
                          label=f"annex '{h['label']}' (heading p. {h['page']}, chars {h['char_start']}-{h['char_end']})",
                          span=dict(page=h["page"], char_start=h["char_start"], char_end=h["char_end"],
                                    quote_sha256=h["quote_sha256"])))
    if not heads:
        lists = [x for x in sig["attachment_lists"] if x["lower_half"] and x["page"] < n_pages]
        if lists:
            x = lists[-1]
            parts.append(dict(kind="annex", page_from=x["page"] + 1, page_to=n_pages, subtype="after_attachment_list",
                              rule=f"{PARTS_VERSION}:after-attachment-list",
                              label=(f"pages after the attachment list '{x['keyword']}:' (p. {x['page']}, chars "
                                     f"{x['char_start']}-{x['char_end']})"),
                              span=dict(page=x["page"], char_start=x["char_start"], char_end=x["char_end"],
                                        quote_sha256=x["quote_sha256"])))
    return parts


# ----------------------------------------------------------------------------------------------------------- images
def image_list(pdf: Path) -> list[dict]:
    """`pdfimages -list`: page, type, pixel size and ppi of every image (smasks and stencils dropped)."""
    rows = []
    for ln in _run(["pdfimages", "-list", str(pdf)]).splitlines()[2:]:
        c = ln.split()
        if len(c) < 14 or c[2] != "image":
            continue
        try:
            rows.append(dict(page=int(c[0]), w=int(c[3]), h=int(c[4]), object=c[10], xppi=float(c[12]), yppi=float(c[13])))
        except ValueError:
            continue
    return rows


def page_sizes(pdf: Path) -> dict[int, tuple[float, float]]:
    info = _run(["pdfinfo", "-f", "1", "-l", "9999", str(pdf)])
    return {int(m.group(1)): (float(m.group(2)), float(m.group(3)))
            for m in re.finditer(r"Page\s+(\d+) size:\s+([\d.]+) x ([\d.]+)", info)}


def placed_images(pdf: Path) -> list[dict]:
    """Where each image sits on its page (`pdftohtml -xml`): page, top/left/width/height as fractions of the page."""
    out = []
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftohtml", "-xml", "-q", "-nodrm", "-fmt", "jpg", str(pdf), f"{td}/x"], capture_output=True,
                       timeout=TIMEOUT, check=False)
        x = Path(td) / "x.xml"
        if not x.exists():
            return out
        try:
            root = ET.fromstring(x.read_bytes().decode("utf-8", "replace").encode("utf-8"))
        except ET.ParseError:
            # pdftohtml writes the page text unescaped at times; keep the page and image elements only
            s = x.read_text(encoding="utf-8", errors="replace")
            keep = re.findall(r"<page [^>]*>|</page>|<image [^>]*/>", s)
            root = ET.fromstring("<pdf2xml>" + "".join(keep) + "</pdf2xml>")
        for pg in root.iter("page"):
            pw, ph = float(pg.get("width")), float(pg.get("height"))
            for im in pg.iter("image"):
                t, le, w, h = (float(im.get(k)) for k in ("top", "left", "width", "height"))
                out.append(dict(page=int(pg.get("number")), top=t / ph, left=le / pw, width=w / pw, height=h / ph))
    return out


def image_parts(pdf: Path, image_only: bool = False, ocr: bool = False) -> tuple[list[dict], dict]:
    sizes = page_sizes(pdf)
    last = max(sizes) if sizes else 1
    scans: dict[int, float] = {}
    for r in image_list(pdf):
        pw, ph = sizes.get(r["page"], (595.0, 842.0))
        if r["xppi"] <= 0 or r["yppi"] <= 0:
            continue
        area = (r["w"] / r["xppi"] * 72) * (r["h"] / r["yppi"] * 72) / (pw * ph)
        if area >= SCAN_MIN_AREA and min(r["xppi"], r["yppi"]) >= SCAN_MIN_PPI:
            scans[r["page"]] = max(scans.get(r["page"], 0), min(r["xppi"], r["yppi"]))
    placed = placed_images(pdf)
    key = lambda im: (round(im["top"], 2), round(im["left"], 2), round(im["width"], 2), round(im["height"], 2))  # noqa: E731
    pages_at = {}
    for im in placed:
        pages_at.setdefault(key(im), set()).add(im["page"])
    figs = []
    for im in placed:
        area = im["width"] * im["height"]
        if not (IMG_MIN_AREA <= area < SCAN_MIN_AREA):
            continue
        if im["top"] + im["height"] <= TOP_BAND or im["top"] >= FOOT_BAND:
            continue  # letterhead or footer band
        if len(pages_at[key(im)]) > 1:
            continue  # the same image at the same place on several pages: a logo or a page decoration
        if im["top"] < LOGO_TOP and area < LOGO_MAX_AREA:
            continue  # a small image at the top of the page: a letterhead logo
        figs.append((im, area))
    parts = []
    for im, area in sorted(figs, key=lambda x: (x[0]["page"], x[0]["top"])):
        where = f"{area:.0%} of the page (top {im['top']:.0%}, left {im['left']:.0%})"
        if im["page"] == last and im["top"] >= SIG_TOP and area < SIG_MAX_AREA:
            parts.append(dict(kind="signature", page_from=im["page"], page_to=im["page"], subtype="signature_block",
                              rule=f"{PARTS_VERSION}:signature-block-image",
                              label=f"image in the signature block of the last page, {where}: a signature or a seal",
                              span=None))
            continue
        parts.append(dict(kind="image", page_from=im["page"], page_to=im["page"], subtype="embedded",
                          rule=f"{PARTS_VERSION}:embedded-image",
                          label=f"embedded image, {where}: a photo, map, chart, diagram, seal or a table set as a picture",
                          span=None))
    run: list[int] = []
    for p in sorted(scans) + [None]:
        if run and (p is None or p != run[-1] + 1):
            how = "text by OCR" if ocr else ("no text layer" if image_only else "text from the PDF's text layer")
            ppi = int(min(scans[q] for q in run))
            parts.append(dict(kind="image", page_from=run[0], page_to=run[-1], subtype="scanned_page",
                              rule=f"{PARTS_VERSION}:scanned-page",
                              label=(f"scanned page{'s' if len(run) > 1 else ''}: the whole page is an image "
                                     f"(>= {ppi} ppi); {how}"),
                              span=None))
            run = []
        if p is not None:
            run.append(p)
    return parts, dict(scanned_pages=sorted(scans), n_images=len(placed), n_embedded=len(figs))


# ----------------------------------------------------------------------------------------------------------- one PDF
MIN_CHARS_PER_PAGE = 30  # gegenprobe.pdftext's image-only threshold (that module is not imported: this one never fetches)


def text_pages(pdf: Path) -> list[str]:
    """The page texts the converter's spans point into: `pdftotext -enc UTF-8` split at form feeds, as gegenprobe.pdftext
    does (a trailing empty page dropped)."""
    pages = _run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"]).split("\f")
    if pages and pages[-1].strip() == "":
        pages = pages[:-1]
    return pages


def layout_pages(pdf: Path) -> list[str]:
    pages = _run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"]).split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def table_parts(layout: list[str], pages: list[str]) -> list[dict]:
    parts = []
    for p, lp in enumerate(layout, 1):
        lines = lp.split("\n")
        after = 0
        for b in table_blocks(lp):
            kind = _kind_of_block(b, lines)
            text = pages[p - 1] if p - 1 < len(pages) else ""
            approx = sum(len(lines[i].strip()) for i in range(b["line_from"], b["line_to"] + 1))
            sp = locate(text, b["cells"][0][0][2], b["cells"][-1][-1][2], approx, after,
                        " ".join(c[2] for c in b["cells"][0]))
            if sp:
                after = sp[1]
            span = dict(page=p, char_start=sp[0], char_end=sp[1], quote_sha256=sha(text[sp[0]:sp[1]])) if sp else None
            what = {"signature": "list of signatories in columns", "budget_table": "budget table"}.get(kind, "table")
            where = f"chars {sp[0]}-{sp[1]}" if sp else f"layout lines {b['line_from'] + 1}-{b['line_to'] + 1}"
            parts.append(dict(kind=kind, page_from=p, page_to=p, subtype="aligned_columns",
                              rule=f"{PARTS_VERSION}:{kind.replace('_', '-')}-layout",
                              label=f"{what}: {b['rows']} rows x {b['columns']} columns (p. {p}, {where})",
                              span=span, rows=b["rows"], columns=b["columns"]))
    return parts


def detect_pdf(pdf: Path, pages: list[str], image_only: bool = False, ocr: bool = False) -> dict:
    """The parts of one PDF. `pages` is the cached text the record's spans point into (pdftotext, or OCR for an
    image-only document); tables are found in `pdftotext -layout` and located back in `pages`."""
    n = len(pages)
    sig = annex_signals(pages)
    layout = layout_pages(pdf)
    imgs, isig = image_parts(pdf, image_only=image_only, ocr=ocr)
    parts = annex_parts(sig, n) + table_parts(layout, pages) + imgs
    parts.sort(key=lambda x: (x["page_from"], x["page_to"], x["kind"]))
    return dict(detector=PARTS_VERSION, n_pages=n, parts=parts,
                signals=dict(annex_headings=len(sig["headings"]), attachment_lists=[_pub(x) for x in sig["attachment_lists"]],
                             annex_references=[_pub(x) for x in sig["references"]], **isig))


def _pub(x: dict) -> dict:
    return {k: v for k, v in x.items() if k in ("page", "char_start", "char_end", "keyword", "quote_sha256", "lower_half")}


# ----------------------------------------------------------------------------------------------------------- HTML
_TABLE = re.compile(r"(?is)<table\b.*?</table>")
_IMG = re.compile(r"(?is)<img\b[^>]*>")


def detect_html(pages_html: list[str | None], pages: list[str]) -> dict:
    """The parts of one HTML text (OPD's texts export), page by page: `pages_html[i]` is the stored HTML behind the plain
    text `pages[i]` (None for a page without HTML, e.g. a title)."""
    sig = annex_signals(pages)
    parts = annex_parts(sig, len(pages))
    for p, h in enumerate(pages_html, 1):
        if not h:
            continue
        for t in _TABLE.findall(h):
            rows = len(re.findall(r"(?i)<tr\b", t))
            cols = max((len(re.findall(r"(?i)<t[dh]\b", r)) for r in re.split(r"(?i)<tr\b", t)[1:]), default=0)
            parts.append(dict(kind="table", page_from=p, page_to=p, subtype="html_table", rule=f"{PARTS_VERSION}:html-table",
                              label=f"table: {rows} rows x {cols} columns (<table> element of the stored HTML, p. {p})",
                              span=None, rows=rows, columns=cols))
        for im in _IMG.findall(h):
            src = re.search(r"(?i)src\s*=\s*['\"]([^'\"]{0,80})", im)
            parts.append(dict(kind="image", page_from=p, page_to=p, subtype="html_img", rule=f"{PARTS_VERSION}:html-img",
                              label=f"image (<img> element of the stored HTML, p. {p})", span=None,
                              src_sha256=sha(H.unescape(src.group(1))) if src else None))
    parts.sort(key=lambda x: (x["page_from"], x["page_to"], x["kind"]))
    return dict(detector=PARTS_VERSION, n_pages=len(pages), parts=parts,
                signals=dict(annex_headings=len(sig["headings"]), attachment_lists=[_pub(x) for x in sig["attachment_lists"]],
                             annex_references=[_pub(x) for x in sig["references"]]))


def schema_parts(det: dict) -> list[dict]:
    """The detection as schema `DocumentPart`s (kind, page_from, page_to, label <= 200 chars)."""
    return [dict(kind=p["kind"], page_from=p["page_from"], page_to=p["page_to"], label=p["label"][:200]) for p in det["parts"]]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    pdf = Path(argv[0])
    pages = text_pages(pdf)
    det = detect_pdf(pdf, pages, image_only=all(len(p.strip()) < MIN_CHARS_PER_PAGE for p in pages))
    print(json.dumps(dict(file=pdf.name, detector=DETECTOR, parts=schema_parts(det), detail=det), ensure_ascii=False,
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
