"""User-facing output of `python -m gegenprobe convert` (one PDF) and `--batch` (one JSONL row per input).

Every row has the same top level:

  {"status": "ok" | <failure kind>, "input": {...what was asked...}, "mode", "language",
   "doc_role": {"value": "answer" | "question" | "other", "basis": "..."},
   "fields": {"answer_date": {...}, "recommendation": {...}},      # flat, reviewer-friendly view of the record
   "needs_review": bool, "review_suggestion": {...} | null,
   "record": <schema v0.1 DocExtraction>}                           # the validated object, unchanged

Failure rows carry {"status": kind, "reason": "...", "input": {...}} and nothing else. Kinds:
  robots_disallowed  the host's robots.txt forbids fetching this URL (we never fetch it)
  http_error         the server answered with an HTTP error (404, 403, 500, ...)
  timeout            no answer in time (after the polite retries)
  network_error      DNS / connection failure
  not_a_pdf          the URL returned an HTML page (a viewer or a dead-link landing page) or bytes without a PDF header
  sha_mismatch       the document changed at the source (expected sha256 given)
  file_not_found     a local path that does not exist
  text_failed        the PDF could not be read and OCR produced no text
"""
from __future__ import annotations

import re
import socket
import urllib.error

from .. import net, pdftext
from . import rules

FAILURE_KINDS = ("robots_disallowed", "http_error", "timeout", "network_error", "not_a_pdf", "sha_mismatch",
                 "file_not_found", "text_failed")


def classify(exc: BaseException) -> tuple[str, str]:
    """Map an exception raised while getting a document to (kind, one-line reason)."""
    if isinstance(exc, net.Disallowed):
        return "robots_disallowed", f"robots.txt of the host forbids {exc}"
    if isinstance(exc, pdftext.FetchError):
        return exc.kind, exc.detail
    if isinstance(exc, urllib.error.HTTPError):
        return "http_error", f"HTTP {exc.code} {exc.reason} for {exc.url}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", str(exc) or "timed out"
    if isinstance(exc, urllib.error.URLError):
        r = exc.reason
        if isinstance(r, (TimeoutError, socket.timeout)):
            return "timeout", str(r) or "timed out"
        return "network_error", str(r)
    if isinstance(exc, FileNotFoundError):
        return "file_not_found", str(exc)
    return "network_error", f"{type(exc).__name__}: {exc}"


def anchor_context(pages: list[str], page: int, start: int, end: int, before: int = 140, limit: int = 200) -> str:
    """The text a reviewer needs to see why a value was taken: up to `before` characters ahead of the span (where the
    anchor phrase sits, e.g. 'Regierungsratsbeschluss vom', 'Réponse du Conseil d'Etat') through the end of the date's
    line, whitespace collapsed, at most `limit` characters, the span itself always included."""
    t = pages[page - 1]
    le = t.find("\n", end)
    le = len(t) if le < 0 else le
    lo = max(0, start - before)
    text = re.sub(r"\s+", " ", t[lo:le]).strip()
    if len(text) > limit:
        span_txt = re.sub(r"\s+", " ", t[start:end]).strip()
        i = text.find(span_txt)
        keep_from = max(0, min(i, len(text) - limit)) if i >= 0 else len(text) - limit
        text = text[keep_from:keep_from + limit]
        lo = -1
    return ("…" if lo > 0 or lo == -1 else "") + text


def doc_role(pages: list[str], answer_rec: dict) -> dict:
    """Guess what kind of document this is, with the evidence used. Not a model; a rule over the frozen anchors."""
    full = "\n".join(pages)
    head = full[: rules.HEAD_CHARS]
    if answer_rec.get("value") and answer_rec.get("route") in ("rule", "metadata"):
        return dict(value="answer", basis=f"executive answer/decision date found by rule {answer_rec.get('rule')}")
    h = rules.ANSWER_HEADING.search(head)
    if h:
        return dict(value="answer", basis=f"answer heading '{h.group(0).strip()[:60]}'")
    if rules.BE_EMPTY.search(head):
        return dict(value="question", basis="empty answer template (no executive answer yet)")
    s = rules.SUBMISSION.search(head)
    if s:
        return dict(value="question", basis=f"submission marker '{s.group(0).strip()}' and no answer heading")
    return dict(value="other", basis="no answer heading, decision anchor or submission marker in the first page(s)")


def flat_field(rec_field: dict | None, record_field: dict | None, pages: list[str]) -> dict | None:
    """Reviewer view of one field: value or null reason, where it is printed, which rule/model decided, and why."""
    if rec_field is None:
        return None
    out = dict(value=rec_field.get("value"), route=(record_field or {}).get("route", rec_field.get("route")))
    if rec_field.get("value") is None:
        out["null_reason"] = rec_field.get("null_reason")
        out["evidence"] = (record_field or {}).get("evidence")
        return out
    if rec_field.get("role"):
        out["role"] = (record_field or {}).get("role", rec_field.get("role"))
    if rec_field.get("rule"):
        out["rule_id"] = rec_field["rule"]
    if rec_field.get("number"):
        out["decision_number"] = rec_field["number"]
    if rec_field.get("page") is not None:
        p, s, e = rec_field["page"], rec_field["char_start"], rec_field["char_end"]
        out.update(page=p, char_start=s, char_end=e, quote=pages[p - 1][s:e] if pages else rec_field.get("quote"),
                   context=anchor_context(pages, p, s, e) if pages else rec_field.get("quote"))
    for k in ("margin", "theta", "model_build"):
        if rec_field.get(k) is not None:
            out[k] = rec_field[k]
    return out


def failure_row(kind: str, reason: str, inp: dict) -> dict:
    assert kind in FAILURE_KINDS, kind
    return dict(status=kind, reason=reason, input=inp)
