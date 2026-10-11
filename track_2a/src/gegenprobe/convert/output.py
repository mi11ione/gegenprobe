"""User-facing output of `python -m gegenprobe convert` (one PDF) and `--batch` (one JSONL row per input).

Every row has the same top level:

  {"status": "ok" | <failure kind>, "input": {...what was asked...}, "mode", "language",
   "doc_role": {"value": "answer" | "question" | "other", "basis": "..."},
   "fields": {"answer_date": {...}, "recommendation": {...}},      # flat, reviewer-friendly view of the record
   "needs_review": bool, "review_reasons": [{"field", "reason"}], "review_suggestion": {...} | null,
   "rules_coverage": {"body", "status": covered | not_covered | user_anchors | unknown, "note"},
   "record": <schema v0.1 DocExtraction>}                           # the validated object, unchanged

Failure rows carry {"status": kind, "reason": "...", "input": {...}} and nothing else. Kinds:
  robots_disallowed  the host's robots.txt disallows this path for our User-Agent (we never fetch it)
  robots_unreachable the host's robots.txt could not be read (5xx, 429, DNS, timeout): fail-closed per RFC 9309
                     §2.3.1.4; a 4xx on robots.txt (403, 404, ...) means "no restrictions" (§2.3.1.3) and is fetched
  robots_matcher_inactive  the RFC 9309 robots.txt matcher is not active in this process (installation problem), so
                     nothing is fetched (compliance/fetchguard.py)
  http_error         the server answered with an HTTP error (404, 403, 500, ...)
  timeout            no answer in time (after the polite retries)
  network_error      DNS / connection failure
  not_a_pdf          the URL returned an HTML page (a viewer or a dead-link landing page) or bytes without a PDF header
  sha_mismatch       the document changed at the source (expected sha256 given)
  file_not_found     a local path that does not exist
  text_failed        the PDF could not be read and OCR produced no text
  too_large          the PDF is above GP_MAX_PDF_MB (default 50) and was not read
  text_timeout       pdftotext / tesseract exceeded GP_SUBPROCESS_TIMEOUT
  ocr_failed         an image-only PDF could not be OCR'd: tesseract or its deu/fra/ita data missing, a tesseract error,
                     or no text recognised (gegenprobe/ocrguard.py); never a silent null, never cached
"""
from __future__ import annotations

import collections
import re
import socket
import urllib.error

from .. import net, pdftext
from gegenprobe.compliance import fetchguard
from . import lattice, pointer, precision, rules
from ..stats import wilson, wilson_pct

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

FAILURE_KINDS = ("robots_disallowed", "robots_unreachable", "robots_matcher_inactive", "http_error", "timeout",
                 "network_error", "not_a_pdf", "sha_mismatch", "file_not_found", "text_failed", "too_large", "text_timeout",
                 "ocr_failed")


def classify(exc: BaseException) -> tuple[str, str]:
    """Map an exception raised while getting a document to (kind, one-line reason)."""
    if isinstance(exc, net.Disallowed):
        if getattr(exc, "kind", None) == fetchguard.KIND:
            return fetchguard.KIND, str(exc)
        if getattr(exc, "kind", None) == "robots_unreachable":
            return "robots_unreachable", (f"robots.txt of the host could not be read, so nothing is fetched from it "
                                          f"(fail-closed, RFC 9309 2.3.1.4): {exc}")
        return "robots_disallowed", f"robots.txt of the host disallows this path for our User-Agent: {exc}"
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
    if answer_rec.get("value") and answer_rec.get("route") == "user_anchor":
        return dict(value="answer", basis=f"executive answer/decision date found by your anchor {answer_rec.get('rule')}")
    h = rules.ANSWER_HEADING.search(head)
    if h:
        return dict(value="answer", basis=f"answer heading '{h.group(0).strip()[:60]}'")
    if rules.BE_EMPTY.search(head):
        return dict(value="question", basis="empty answer template (no executive answer yet)")
    s = rules.SUBMISSION.search(head)
    if s:
        return dict(value="question", basis=f"submission marker '{s.group(0).strip()}' and no answer heading")
    return dict(value="other", basis="no answer heading, decision anchor or submission marker in the first page(s)")


def flat_field(rec_field: dict | None, record_field: dict | None, pages: list[str], field: str = "answer_date") -> dict | None:
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
        if out.get("route") in ("rule", "ocr+rule"):
            out["rule_precision"] = rule_precision_of(field, rec_field["rule"])
            out.update(rule_precision_stats(field, rec_field["rule"]))
    if rec_field.get("number"):
        out["decision_number"] = rec_field["number"]
    if rec_field.get("page") is not None:
        p, s, e = rec_field["page"], rec_field["char_start"], rec_field["char_end"]
        out.update(page=p, char_start=s, char_end=e, quote=pages[p - 1][s:e] if pages else rec_field.get("quote"),
                   context=anchor_context(pages, p, s, e) if pages else rec_field.get("quote"))
    for k in ("margin", "theta", "model_build", "anchor_file", "anchor_pattern", "qualifier"):
        if rec_field.get(k) is not None:
            out[k] = rec_field[k]
    return out


def date_candidates(pages: list[str], chosen: str | None = None, shares: dict | None = None, limit: int = 30) -> list[dict]:
    """The closed set a reviewer chooses from: every distinct date printed in the document (first occurrence, with page,
    span and 160 characters of context), whether it is inside the pointer's reading window, and, in review mode, the
    probability share Apertus gives it among {these dates, null}."""
    _, offs, _ = pointer.doc_text(pages)
    seen: dict[str, dict] = {}
    for c in lattice.dates(pages):
        v = c["value"]
        if v in seen:
            seen[v]["occurrences"] += 1
            continue
        seen[v] = dict(value=v, page=c["page"], char_start=c["char_start"], char_end=c["char_end"],
                       context=anchor_context(pages, c["page"], c["char_start"], c["char_end"], before=100, limit=160),
                       occurrences=1, in_pointer_window=pointer._visible(c, offs, pointer.CHAR_BUDGET))
    out = list(seen.values())[:limit]
    for d in out:
        if chosen and d["value"] == chosen:
            d["chosen"] = True
        if shares is not None:
            d["share"] = round(shares.get(d["value"], 0.0), 4)
    return out


def pointer_shares(p) -> dict:
    """{date: probability share, None: null share} from a PointerResult (softmax over null + candidates)."""
    import math
    if not p.candidates:
        return {}
    lps = [p.lp_null] + [lp for _, lp in p.candidates]
    m = max(lps)
    z = sum(math.exp(x - m) for x in lps)
    out = {v: math.exp(lp - m) / z for v, lp in p.candidates}
    out[None] = math.exp(p.lp_null - m) / z
    return out


SMALL_SAMPLE = 10  # below this many held-out firings a rule's precision is flagged as a small sample


def rule_precision_of(field: str, rule_id: str | None) -> str | None:
    """'3/5 correct on held-out documents (P1+P2), Wilson 95% [23.1, 88.2]' (plus '; small sample, n < 10' when the rule
    fired fewer than 10 times there), or a 'not measured' note if the rule never fired on the held-out sets."""
    if not rule_id:
        return None
    r = precision.committed_rule_precision().get(field, {}).get(rule_id)
    if not r:
        return "not measured (rule did not fire on held-out sets)"
    lo, hi = wilson_pct(int(r["correct"]), int(r["n"]))
    small = f"; small sample, n < {SMALL_SAMPLE}" if int(r["n"]) < SMALL_SAMPLE else ""
    return f"{r['shown']} correct on held-out documents (P1+P2), Wilson 95% [{_pct(lo)}, {_pct(hi)}]{small}"


def rule_precision_stats(field: str, rule_id: str | None) -> dict:
    """Machine-readable companion of rule_precision_of: {rule_precision_n, rule_precision_ci (Wilson 95%, fractions),
    rule_precision_small_sample (n < 10)}; {} when the rule was not measured."""
    r = precision.committed_rule_precision().get(field, {}).get(rule_id) if rule_id else None
    if not r:
        return {}
    lo, hi = wilson(int(r["correct"]), int(r["n"]))
    return dict(rule_precision_n=int(r["n"]), rule_precision_ci=[round(lo, 3), round(hi, 3)],
                rule_precision_small_sample=int(r["n"]) < SMALL_SAMPLE)


def _pct(v: float) -> str:
    return "100" if v == 100 else f"{v:.1f}"


def band_info(margin: float | None, theta: float | None) -> dict | None:
    b = precision.band(margin, theta)
    if b is None:
        return None
    r = precision.committed_band_precision().get(b)
    label = {"strong": "strong: the model clearly preferred this printed date over null",
             "weak": "weak: the model leaned toward null but stayed under θ"}[b]
    return dict(band=b, meaning=label, measured=(f"{r['shown']} suggestions in this band were correct (P1+P2, post-hoc)"
                                                 if r else None))


def recommendation_phrases(pages: list[str]) -> dict:
    """How many recommendation phrases the rules see, and for which labels (a document can recommend differently per
    point: 'propose le rejet du premier point' and 'l'adoption des points 2 et 3')."""
    labels = collections.Counter()
    for lab, rx in rules.REC:
        for t in pages:
            labels[lab] += len(rx.findall(t))
    found = {k: v for k, v in labels.items() if v}
    return dict(labels=found, multiple=len(found) > 1)


def failure_row(kind: str, reason: str, inp: dict) -> dict:
    assert kind in FAILURE_KINDS, kind
    return dict(status=kind, reason=reason, input=inp)
