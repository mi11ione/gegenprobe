"""Span re-check: a value with a span must be found in the cached text at exactly that span.

    recheck(valued, pages) -> SpanCheck(ok, code, detail)

codes
  ok                   quote == text[span] (whitespace-normalised) and the value is supported by that text
  no_span              metadata route: nothing to check (ok=True, counted separately)
  page_out_of_range    page < 1 or > len(pages)
  span_out_of_range    char_end beyond the page
  quote_mismatch       the stored quote is not the text at the span
  value_not_in_span    basis=extracted: value string absent; basis=normalised dates: no date in the span normalises to it
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .dates import find_dates


@dataclass(frozen=True)
class SpanCheck:
    ok: bool
    code: str
    detail: str = ""


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def recheck(v, pages: list[str]) -> SpanCheck:
    """`v` is a schema Valued (or any object with value/basis/route/page/char_start/char_end/quote)."""
    if v.page is None:
        return SpanCheck(True, "no_span")
    if not 1 <= v.page <= len(pages):
        return SpanCheck(False, "page_out_of_range", f"page {v.page} of {len(pages)}")
    text = pages[v.page - 1]
    if v.char_end > len(text):
        return SpanCheck(False, "span_out_of_range", f"char_end {v.char_end} > {len(text)}")
    at = text[v.char_start:v.char_end]
    if v.quote is not None and _ws(v.quote) != _ws(at):
        return SpanCheck(False, "quote_mismatch", f"quote {v.quote[:80]!r} != text {at[:80]!r}")
    val = v.value
    if isinstance(val, dt.date):
        iso = val.isoformat()
        if not any(d["iso"] == iso for d in find_dates(at)):
            return SpanCheck(False, "value_not_in_span", f"{iso} not in {at[:80]!r}")
    elif v.basis == "extracted" and _ws(str(val)) not in _ws(at):
        return SpanCheck(False, "value_not_in_span", f"{str(val)[:60]!r} not in {at[:80]!r}")
    # basis=inferred (enum labels): the span is the cited evidence; only its integrity (quote) is checkable
    return SpanCheck(True, "ok")


def recheck_affair(affair, texts: dict[str, list[str]]) -> list[tuple[str, SpanCheck]]:
    """Re-check every span-bearing field of an Affair; `texts` maps doc_id -> pages. Missing text -> code text_missing."""
    from ..schema.schema_v0_1 import iter_fields
    out = []
    for path, v in iter_fields(affair):
        if getattr(v, "kind", None) != "value":
            continue
        if v.page is None:
            out.append((path, SpanCheck(True, "no_span")))
        elif v.doc not in texts:
            out.append((path, SpanCheck(False, "text_missing", v.doc or "")))
        else:
            out.append((path, recheck(v, texts[v.doc])))
    return out
