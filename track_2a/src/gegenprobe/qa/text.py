"""Page-aware text helpers: one document = its cached pages; global offsets = pages joined with "\\n"
(`convert.pointer.doc_text`), so a span can cross pages and still map back to (page, char) on both ends."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch)).lower()


@dataclass
class Line:
    g0: int  # global start
    g1: int  # global end (exclusive, without the newline)
    text: str
    page: int


@dataclass
class Doc:
    role: str
    doc_id: str
    pages: list[str]
    text: str = ""
    starts: list[int] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)

    def __post_init__(self):
        self.text = "\n".join(self.pages)
        pos = 0
        for p in self.pages:
            self.starts.append(pos)
            pos += len(p) + 1
        for pi, p in enumerate(self.pages, 1):
            off = self.starts[pi - 1]
            for m in re.finditer(r"[^\n]*", p):
                if m.start() == m.end() and m.start() > 0 and p[m.start() - 1] != "\n":
                    continue
                self.lines.append(Line(off + m.start(), off + m.end(), m.group(0), pi))

    def loc(self, g: int) -> tuple[int, int]:
        """global offset -> (page, char)."""
        for pi in range(len(self.pages), 0, -1):
            if g >= self.starts[pi - 1]:
                return pi, min(g - self.starts[pi - 1], len(self.pages[pi - 1]))
        return 1, 0

    def span(self, g0: int, g1: int) -> dict:
        """Resolved span with page/char on both ends (the end page may differ from the start page)."""
        g0, g1 = self.trim(g0, g1)
        p0, c0 = self.loc(g0)
        p1, c1 = self.loc(g1)
        if c1 == 0 and p1 > p0:  # an end exactly at a page start belongs to the previous page's end
            p1, c1 = p1 - 1, len(self.pages[p1 - 2])
        return dict(doc=self.role, page=p0, char_start=c0, end_page=p1, char_end=c1, g_start=g0, g_end=g1)

    def trim(self, g0: int, g1: int) -> tuple[int, int]:
        while g0 < g1 and self.text[g0].isspace():
            g0 += 1
        while g1 > g0 and self.text[g1 - 1].isspace():
            g1 -= 1
        return g0, g1

    def line_at(self, g: int) -> int:
        lo, hi = 0, len(self.lines) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.lines[mid].g0 <= g:
                lo = mid
            else:
                hi = mid - 1
        return lo


# running headers/footers: a line that repeats on >= 2 pages at the top/bottom, or a bare page number
PAGE_NO = re.compile(r"^\s*(-?\s*\d{1,3}\s*-?|Seite\s+\d+(\s*(von|/)\s*\d+)?|page\s+\d+(\s*(sur|/)\s*\d+)?|"
                     r"pagina\s+\d+(\s*(di|/)\s*\d+)?|\d+\s*/\s*\d+)\s*$", re.I)


def boilerplate_lines(doc: Doc) -> set[int]:
    """Indices of lines that are running headers/footers (a line among the first/last 4 non-blank lines of a page whose
    digit-masked text recurs there on other pages) or bare page numbers."""
    out = set()
    edge: dict[int, list[int]] = {}
    for i, ln in enumerate(doc.lines):
        if ln.text.strip():
            edge.setdefault(ln.page, []).append(i)
    edge_ids = set()
    for ids in edge.values():
        edge_ids |= set(ids[:4]) | set(ids[-4:])
    if len(doc.pages) >= 2:
        cnt: dict[str, set] = {}
        for i in edge_ids:
            k = re.sub(r"\d+", "#", doc.lines[i].text.strip())
            cnt.setdefault(k, set()).add(doc.lines[i].page)
        for i in edge_ids:
            k = re.sub(r"\d+", "#", doc.lines[i].text.strip())
            if len(cnt[k]) >= 2 and len(k) < 120 and not MARKER_START.match(doc.lines[i].text.strip()):
                out.add(i)
    for i, ln in enumerate(doc.lines):
        if PAGE_NO.match(ln.text):
            out.add(i)
    return out


@dataclass
class Para:
    g0: int
    g1: int
    text: str
    first_line: int
    last_line: int


def paragraphs(doc: Doc, g0: int = 0, g1: int | None = None, skip: set[int] | None = None) -> list[Para]:
    """Paragraphs in [g0, g1): runs of non-blank lines, split at a blank line, or after a line that ends a sentence and
    is clearly shorter than the block's typical line (the last line of a paragraph), or before a line that starts with an
    item/heading marker."""
    g1 = len(doc.text) if g1 is None else g1
    skip = skip or set()
    lines = [(i, ln) for i, ln in enumerate(doc.lines) if ln.g1 > g0 and ln.g0 < g1 and i not in skip]
    widths = sorted(len(ln.text.rstrip()) for _, ln in lines if ln.text.strip())
    typical = widths[int(len(widths) * 0.8)] if widths else 80
    out, cur = [], []

    def flush():
        if cur:
            a, b = max(cur[0][1].g0, g0), min(cur[-1][1].g1, g1)
            a, b = doc.trim(a, b)
            if b > a:
                out.append(Para(a, b, doc.text[a:b], cur[0][0], cur[-1][0]))
        cur.clear()

    for i, ln in lines:
        t = ln.text.strip()
        if not t:
            flush()
            continue
        if cur and MARKER_START.match(t):
            flush()
        cur.append((i, ln))
        if re.search(r"[.:?!»“”\"]\s*$", t) and len(ln.text.rstrip()) < 0.75 * typical:
            flush()
    flush()
    return out


MARKER_START = re.compile(
    r"^(\d{1,2}\s*[.)](\s|$)|[a-h]\)\s|[-–•▪·]\s|(zu|ad|zur)\s+(frage\s+)?\d|frage\s+\d|question\s+\d|domanda\s+\d|"
    r"r[ée]ponse\s+(à\s+la\s+question\s+)?\d|risposta\s+(alla\s+domanda\s+)?\d)",
    re.I,
)


def strip_edges(doc: Doc, g0: int, g1: int, skip: set[int]) -> tuple[int, int]:
    """Trim whitespace, leading heading punctuation and boilerplate lines (running headers/footers) at both ends."""
    while True:
        g0, g1 = doc.trim(g0, g1)
        m = re.match(r"[\s:.)–\-]+", doc.text[g0:g1])
        if m and m.end() > 0:
            g0 += m.end()
            continue
        if g1 <= g0:
            return g0, g1
        i0, i1 = doc.line_at(g0), doc.line_at(g1 - 1)
        if i0 in skip and doc.lines[i0].g1 < g1:
            g0 = doc.lines[i0].g1
            continue
        if i1 in skip and doc.lines[i1].g0 > g0:
            g1 = doc.lines[i1].g0
            continue
        return g0, g1
