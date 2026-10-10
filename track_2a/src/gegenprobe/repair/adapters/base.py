"""Common interface of the per-parliament source adapters: candidates for an OPD affair -> document text -> checks.

An adapter answers one question per OPD affair: where is the government's written answer, and is the document found
really that answer? It never writes a value of its own; it proposes a typed repair row keyed on the OPD affair id.

  candidates(affair, opd_docs)  -> [Candidate]   where the answer may be: a document OPD already holds on the affair
                                                  (origin `opd_text`: OPD has its text; `opd_file`: OPD holds the file
                                                  but no usable text) or a document on the parliament's own site
                                                  (origin `source`); network errors propagate as typed failures
  text(candidate)               -> (text, meta)  inline text, or the file fetched politely (gegenprobe.net) and
                                                  extracted (pdftotext; tesseract deu+fra+ita for image-only scans)
  check(affair, candidate, text) -> checks       identity  the affair number (body-specific spellings) or the OPD title
                                                           is printed in the document
                                                 heading   the body's answer heading is printed
                                                 date      a date printed in the document equals one of OPD's
                                                           written-answer event dates (header date first, then any
                                                           date in the text), or follows it within the adapter's
                                                           documented window; where OPD's answer events carry no
                                                           date, the document's own date lies within a year after
                                                           OPD's submission event (`after_submission`, reported
                                                           separately); within DATE_NEAR days = `near` (review)

Outcome per affair (model-free, deterministic):
  verified  identity and heading and an equal date, and no document-type filter fires (filters.py)
                                                                            -> action of the route
  review    identity and heading, the date is near/absent/different; or identity and the source itself types the
            document as the answer (SG/SO `Antwort`, ZH step `Antwort Regierungsrat`) but no heading was matched
  failed    typed reason (no_candidate, not_found, robots_disallowed, http_error, not_a_pdf, empty_text, identity_fail,
            heading_fail, ...): no repair row, counted in the summary
  filters   (filters.py) a document that passes the checks but is typed by its own wording as something else (a deadline
            extension, a commission report, minutes that only refer to the answer, the member's text, another affair's
            answer, a reply to a council resolution) moves down to review or failed with that reason; checks carry
            `filter` and `filter_quote`

Actions:
  tag_answer   OPD already holds the answer, with text, on the affair; nothing marks it as the answer (generic name, no
               category), so the census and every user see a question without an answer. Fix: set its category.
  extract_tag  OPD holds the answer file on the affair, without usable text: extract (text layer or OCR) and tag it
  fetch        the parliament publishes the answer; OPD does not hold it: fetch and attach
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path

from ... import net, pdftext
from ...paths import WORK
from ..common import ANSWER_HEADING, parse_dates
from . import filters

ADIR = WORK / "adapters"
DATE_NEAR = 14  # days; a document date this close to OPD's event (but not equal) goes to review, never verified
QUOTE_MAX = 200
FILTER_RANK = {"verified": 0, "review": 1, "failed": 2}


@dataclasses.dataclass
class Candidate:
    url: str | None
    title: str = ""
    origin: str = "source"  # source | opd_text | opd_file
    opd_doc_id: int | None = None
    text: str | None = None  # inline text (OPD export text, or the source API's full text)
    source_typed_answer: bool = False  # the source's own metadata calls this document the answer
    uid: str | None = None  # the source's document id
    meta: dict = dataclasses.field(default_factory=dict)


class Failure(Exception):
    """A typed failure for one affair (reason is one of the documented failure kinds)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


# ---------------------------------------------------------------- text helpers
def norm(s: str) -> str:
    """Casefold, strip accents and soft hyphens, join hyphenated line breaks, collapse non-alphanumerics to one space."""
    s = s.replace("­", "").replace("\r", "")
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", " ", s.casefold()).strip()


STOP = set("der die das und oder des den dem ein eine einer eines fur fuer von vom zum zur mit auf aus bei nach uber ueber "
           "les la le des du de et ou en au aux pour par sur dans une un il lo gli della delle dei del di e o per con "
           "su nel nella".split())


def title_match(text: str, title: str | None, window: int = 6000) -> tuple[bool, float]:
    """The OPD title is printed near the top: as one normalised string, or >= 80% of its content words (>= 4 letters,
    at least 3 of them) appear in the first `window` characters. Returns (match, share of words found)."""
    if not title:
        return False, 0.0
    t, head = norm(title), norm(text[:window])
    if len(t) >= 10 and len(t.split()) >= 2 and t in head:
        return True, 1.0
    words = [w for w in t.split() if len(w) >= 4 and w not in STOP]
    if len(words) < 3:
        return False, 0.0
    hw = set(head.split())
    share = sum(w in hw for w in words) / len(words)
    return share >= 0.8, round(share, 2)


def flatten(text: str) -> str:
    """Join words hyphenated across a line break ("Inter-\npellation") and collapse whitespace, so headings and numbers
    split by the PDF's line layout still match."""
    t = re.sub(r"(\w)[-\u00ad]\s*\n\s*(\w)", r"\1\2", text.replace("\r", ""))
    return re.sub(r"\s+", " ", t)


def html_text(b: bytes) -> str:
    s = b.decode("utf-8", "replace")
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(s)


def quote(text: str, start: int, end: int, pad: int = 60) -> str:
    q = re.sub(r"\s+", " ", text[max(0, start - pad):end + pad]).strip()
    return q[:QUOTE_MAX]


# ---------------------------------------------------------------- fetching (polite, cached by sha256 in WORK)
def fetch_text(url: str, body: str, ocr: bool = True, max_ocr_pages: int = 4) -> tuple[str, dict]:
    """Fetch a document and return (text, meta). PDFs go through pdftext (cached by sha256; OCR for image-only scans,
    first `max_ocr_pages` pages); HTML is stripped of tags. meta: sha256, extractor, bytes, content kind."""
    hit = url_cache_get(url)
    if hit:
        return hit
    from . import robots
    b = robots.get(url, timeout=120, tries=3)
    sha = hashlib.sha256(b).hexdigest()
    if b"%PDF" in b[:1024]:
        p = pdftext.PDF_CACHE / f"{sha}.pdf"
        if not p.exists():
            pdftext.PDF_CACHE.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
        d = pdftext.extract(sha, p, ocr=ocr, max_ocr_pages=max_ocr_pages)
        meta = dict(sha256=sha, extractor=d["extractor"], bytes=len(b), kind="pdf")
        url_cache_put(url, meta)
        return "\n".join(d["pages"]), meta
    head = b[:400].decode("utf-8", "replace").lower()
    if "<html" in head or "<!doctype" in head:
        RAW.mkdir(parents=True, exist_ok=True)
        (RAW / f"{sha}.html").write_bytes(b)
        meta = dict(sha256=sha, extractor="html", bytes=len(b), kind="html")
        url_cache_put(url, meta)
        return html_text(b), meta
    raise Failure("not_a_pdf", f"{url}: {len(b)} bytes, neither PDF nor HTML")


RAW = ADIR / "raw"
URL_CACHE = ADIR / "url_cache.jsonl"
_url_cache: dict[str, dict] | None = None


def _load_url_cache() -> dict[str, dict]:
    global _url_cache
    if _url_cache is None:
        _url_cache = {}
        if URL_CACHE.exists():
            for line in URL_CACHE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    _url_cache[r["url"]] = r["meta"]
    return _url_cache


def url_cache_put(url: str, meta: dict) -> None:
    _load_url_cache()[url] = meta
    URL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(URL_CACHE, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(url=url, meta=meta)) + "\n")


def url_cache_get(url: str) -> tuple[str, dict] | None:
    """A document fetched before (same URL): its text from the WORK caches, no request. None if not cached."""
    m = _load_url_cache().get(url)
    if not m:
        return None
    if m["kind"] == "pdf":
        p = pdftext.PDF_CACHE / f"{m['sha256']}.pdf"
        if not p.exists():
            return None
        d = pdftext.extract(m["sha256"], p, ocr=m["extractor"].startswith("tesseract"))
        return "\n".join(d["pages"]), dict(m, extractor=d["extractor"])
    p = RAW / f"{m['sha256']}.html"
    return (html_text(p.read_bytes()), m) if p.exists() else None


def failure_reason(e: Exception) -> str:
    if isinstance(e, Failure):
        return e.reason
    if isinstance(e, net.Disallowed):
        return e.kind
    k = getattr(e, "kind", None)
    if k:
        return k
    n = type(e).__name__
    if n == "HTTPError":
        return f"http_{getattr(e, 'code', 'error')}"
    if n in ("TimeoutError", "TimeBudgetExceeded") or "timed out" in str(e):
        return "timeout"
    if n in ("URLError", "ConnectionError", "RemoteDisconnected", "IncompleteRead", "ConnectionResetError"):
        return "network_error"
    return f"error_{n}"


TRANSIENT = ("timeout", "network_error", "http_429", "http_500", "http_502", "http_503", "http_504", "robots_unreachable")


# ---------------------------------------------------------------- the adapter
class Adapter:
    body: str = ""
    label: str = ""
    route: str = ""  # one line: how the answer is found
    action: str = "fetch"  # route action when the document comes from the parliament's site
    hosts: tuple[str, ...] = ()
    heading: re.Pattern = ANSWER_HEADING
    header_date: re.Pattern | None = None  # group(1): the document's own answer/decision date, searched first
    header_window: int = 3000
    # the place-date line of a letter or a signed answer ("Delémont, le 25 août 2020", "Locarno, 18 ottobre 2012"),
    # searched in the last 2,500 characters when the header has no date
    tail_date: re.Pattern | None = re.compile(
        r"\b[A-ZÄÖÜ][\w\-éèô.]+(?: [A-Z][\w\-éè]+)?, (?:le |den |il |am )?(\d{1,2}(?:er|°)?\.?\s*(?:\d{1,2}\.\s*|"
        r"[A-Za-zéèûäöü]+\s+)\d{4})")
    _submit: list[str] = []
    ocr: bool = True
    date_window: tuple[int, int] = (0, 0)  # accepted (event - document date) in days; (0, 0) = equal dates only
    # the parliament's affair-number shape as printed in a document header (group 1 = the number), for the wrong-affair
    # cross-check (filters.wrong_affair); None = no cross-check
    number_shape: re.Pattern | None = None

    # --- to implement
    def candidates(self, x: dict, opd: list[dict]) -> list[Candidate]:
        raise NotImplementedError

    def number_patterns(self, number: str) -> list[str]:
        """Regexes for the ways this parliament prints the affair number (default: the number as stored)."""
        return [re.escape(number)]

    # --- shared
    def text(self, c: Candidate) -> tuple[str, dict]:
        if c.text is not None and len(c.text.strip()) >= 200:
            return c.text, dict(extractor="opd_export" if c.origin != "source" else "source_api", chars=len(c.text),
                                sha256=hashlib.sha256(c.text.encode()).hexdigest() if c.origin == "source" else None)
        if not c.url:
            raise Failure("empty_text", "no text and no URL")
        t, m = fetch_text(c.url, self.body, ocr=self.ocr)
        if len(t.strip()) < 200:
            raise Failure("empty_text", f"{len(t.strip())} chars after extraction ({m['extractor']})")
        m["chars"] = len(t)
        return t, m

    def identity(self, text: str, x: dict) -> tuple[bool, str]:
        flat = re.sub(r"[ \t ]+", " ", text)
        for p in self.number_patterns(x["number"] or ""):
            if p and re.search(r"(?<![\w/.])" + p + r"(?![\w/]|\.\d)", flat):
                return True, "number"
        ok, share = title_match(text, x.get("title"))
        if ok:
            return True, f"title({share})"
        return False, f"none(title {share})"

    def doc_date(self, text: str, c: Candidate) -> str | None:
        if c.meta.get("doc_date"):
            return c.meta["doc_date"]
        for rx, part in ((self.header_date, text[: self.header_window]), (self.tail_date, text[-2500:])):
            if rx is None:
                continue
            m = rx.search(part)
            if m:
                ds = parse_dates(m.group(1) if m.groups() else m.group(0))
                if ds:
                    return ds[0][0]
        return None

    def date_check(self, text: str, dd: str | None, ev: list[str], gov: list[str] | None = None
                   ) -> tuple[str, bool | None, bool | None]:
        """(label, date_eq_event, date_ok). eq: the document's own date equals an OPD answer event; window: the event
        follows the document's date by date_window days (the parliament records receipt/publication after the decision;
        a documented per-body rule); anywhere: some printed date equals an event; latest_in_window: no header date, the
        latest printed date not after the event lies in the window. Anything else is near (<= DATE_NEAR days: review)
        or differs."""
        if not ev:
            sub = sorted(self._submit or [])
            if dd and sub:
                k = (dt.date.fromisoformat(dd) - dt.date.fromisoformat(sub[0])).days
                if 0 <= k <= 366:
                    return f"after_submission(+{k}d)", None, True
            return "no_event", None, None
        evd = [dt.date.fromisoformat(e) for e in ev]
        lo, hi = self.date_window
        if dd:
            d0 = dt.date.fromisoformat(dd)
            deltas = sorted(((e - d0).days for e in evd), key=abs)
            delta = deltas[0]
            if delta == 0:
                return "eq", True, True
            if gov and dd in gov:
                return "eq_gov", True, True
            inwin = [x for x in deltas if lo <= x <= hi]
            if inwin:
                return f"window(+{inwin[0]}d)", False, True
        printed = parse_dates(text)
        if any(d in ev for d, _, _ in printed):
            return "anywhere", True, True
        if not dd and hi > 0:
            ps = sorted({dt.date.fromisoformat(d) for d, _, _ in printed})
            for e in evd:
                before = [p for p in ps if p <= e]
                if before and lo <= (e - before[-1]).days <= hi:
                    return f"latest_in_window(+{(e - before[-1]).days}d)", False, True
        if dd:
            return (f"near({delta}d)" if abs(delta) <= DATE_NEAR else f"differs({delta}d)"), False, False
        return "none", False, False

    def check(self, x: dict, c: Candidate, text: str) -> dict:
        ft = flatten(text)
        idn, how = self.identity(ft, x)
        if not idn and c.meta.get("source_identity"):  # the source's own metadata ties this document to the number
            idn, how = True, c.meta["source_identity"]
        h = self.heading.search(ft)
        ev = x.get("answer_dates") or []
        dd = self.doc_date(text, c)
        self._submit = x.get("submit_dates") or []
        match, date_eq, date_ok = self.date_check(text, dd, ev, x.get("gov_dates"))
        heading = bool(h)
        if idn and heading and date_ok:
            outcome = "verified"
        elif idn and (heading or c.source_typed_answer):
            outcome = "review"
        else:
            outcome = "failed"
        reason = None
        if outcome != "verified":
            reason = ("identity_fail" if not idn else "heading_fail" if not heading
                      else "no_answer_event" if not ev else "date_mismatch")
        hit = filters.screen(ft, c.title, x, self.heading, self.number_shape,
                             [p for p in self.number_patterns(x.get("number") or "") if p])
        if hit and outcome != "failed":  # a filter only moves a row down, and its reason replaces the check's
            outcome = hit.outcome if FILTER_RANK[hit.outcome] > FILTER_RANK[outcome] else outcome
            reason = hit.reason
        out = dict(identity=idn, identity_by=how, heading=heading,
                   heading_quote=quote(ft, h.start(), h.end()) if h else None, doc_date=dd, answer_events=ev,
                   gov_events=x.get("gov_dates") or [], date_match=match, date_eq_event=date_eq, date_ok=date_ok,
                   outcome=outcome, reason=reason)
        if hit:  # also on rows that failed anyway (their reason stays the check's)
            out.update(filter=hit.reason, filter_quote=hit.quote)
        return out


def excerpt_path(body: str, affair_id: int) -> Path:
    return ADIR / "excerpts" / body / f"{affair_id}.txt"


def save_excerpt(body: str, affair_id: int, text: str, header: dict) -> Path:
    """The extracted text a blind auditor reads (WORK only, never committed)."""
    p = excerpt_path(body, affair_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(header, ensure_ascii=False) + "\n\n" + text, encoding="utf-8")
    return p
