"""Map our provenance spans (page + characters in our pdftotext/tesseract text) onto OPD's stored document text (the
`text` field of the docs export, extracted by OPD with Tika/PDFBox), so that a value can be highlighted in OPD's own
workbench without re-extracting the PDF.

Method, deterministic: both texts are compared whitespace-normalised. The value's anchor context (the phrase before the
date through the date) is searched first, because it is far more specific than the date alone; the quote is then located
inside the matched context. A match must be unique; several equally good matches are reported as `ambiguous` (with the
candidate offsets), none as `not_found`. Offsets are character offsets into OPD's text as stored (not normalised).

    from gegenprobe.convert.opdtext import align
    align(opd_text, quote="28. August 2024", context="RRB-Nr.: 879/2024 vom 28. August 2024")
      -> {"status": "unique", "char_start": 412, "char_end": 427, "matched_on": "context"}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WS = re.compile(r"\s+")


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """Whitespace-collapsed text and, for each of its characters, the index in the original text."""
    out, idx = [], []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space and out:
                out.append(" ")
                idx.append(i)
            prev_space = True
        else:
            out.append(ch)
            idx.append(i)
            prev_space = False
    return "".join(out), idx


def _find_all(hay: str, needle: str) -> list[int]:
    res, i = [], hay.find(needle)
    while i >= 0:
        res.append(i)
        i = hay.find(needle, i + 1)
    return res


def load(path: str) -> str:
    """Plain text, or a docs-export JSON row (or a JSON object) with a 'text' field."""
    raw = Path(path).read_text(encoding="utf-8")
    s = raw.lstrip()
    if s.startswith("{"):
        return json.loads(s.splitlines()[0] if "\n" in s and not s.rstrip().endswith("}") else s)["text"] or ""
    return raw


def align(opd_text: str, quote: str, context: str | None = None) -> dict:
    if not opd_text or not quote:
        return dict(status="not_found", reason="empty text or quote")
    hay, idx = _norm_with_map(opd_text)
    q = WS.sub(" ", quote).strip()
    ctx = WS.sub(" ", (context or "").lstrip("…")).strip()
    if ctx and q in ctx:
        end = ctx.rfind(q) + len(q)
        for width in (len(ctx[:end]), 80, 50):  # the longest unique tail of the context that ends with the quote
            probe = ctx[:end][-width:].strip()
            hits = _find_all(hay, probe)
            if len(hits) == 1:
                s = hits[0] + len(probe) - len(q)
                return dict(status="unique", char_start=idx[s], char_end=idx[s + len(q) - 1] + 1, matched_on="context",
                            quote=opd_text[idx[s]: idx[s + len(q) - 1] + 1])
    hits = _find_all(hay, q)
    if len(hits) == 1:
        s = hits[0]
        return dict(status="unique", char_start=idx[s], char_end=idx[s + len(q) - 1] + 1, matched_on="quote",
                    quote=opd_text[idx[s]: idx[s + len(q) - 1] + 1])
    if hits:
        return dict(status="ambiguous", occurrences=[[idx[s], idx[s + len(q) - 1] + 1] for s in hits[:10]],
                    reason=f"{len(hits)} occurrences of the quote and no unique context")
    return dict(status="not_found", reason="quote not in OPD's text (different extraction, OCR, or not stored)")


def annotate(row: dict, opd_text: str) -> dict:
    """Add `opd_text_span` to every field value and suggestion of an output row (in place); returns a summary."""
    summary = {}
    for name, f in (row.get("fields") or {}).items():
        if f and f.get("value") is not None and f.get("quote"):
            f["opd_text_span"] = align(opd_text, f["quote"], f.get("context"))
            summary[name] = f["opd_text_span"]["status"]
    s = row.get("review_suggestion")
    if s and s.get("quote"):
        s["opd_text_span"] = align(opd_text, s["quote"], s.get("context"))
        summary["review_suggestion"] = s["opd_text_span"]["status"]
    return summary
