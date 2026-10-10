"""Unlocked overlay on the frozen converter: what the user-facing CLI adds AFTER the pre-registered rules have decided.

The frozen modules (rules, cascade, pointer, lattice, calibrate) are locked by hash in eval/prereg*/LOCK* and are used
unchanged; the evaluation scripts call them directly, so nothing here changes a registered result. This module only
reads their output and the page texts, and

  coverage(body, anchors)          is this parliament one the frozen rules were written on (data/convert/rules_coverage.json)?
                                   If not, nulls the rules left open become `no_rules_for_body` and the row needs review
  qualify_recommendation(...)      a recommendation rule matched "accept"/"reject" but the sentence goes on with a
                                   qualifier: "accepter partiellement", "teilweise erheblich" -> `partial`; "im Sinne der
                                   Erwägungen", "mit geändertem Wortlaut", "Nichteintreten", ... -> value kept, needs review.
                                   The quote span is extended to include the qualifier
  heading_date(pages)              the rules found an answer heading but no anchored date ("heading_without_date"); a date
                                   printed right after the heading ("Antwort der Regierung vom 1. September 2026",
                                   "Réponse du Conseil d'Etat : 06.05.2025") is surfaced as the first candidate, marked
                                   `suggested_by_heading_proximity`, and the row needs review. The field is NOT filled
  load_anchors / apply_*_anchors   user anchors (--anchors FILE, JSON): per-body regexes for the answer date and
                                   recommendation phrases, tried only after the frozen rules returned null; values carry
                                   route `user_anchor`, page and span
  trace_answer_date / trace_recommendation
                                   --explain: which frozen rules were tried, in the frozen order, and why each did not decide
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..paths import DATA, PDF_CACHE, TEXT_CACHE, WORK
from . import lattice, rules

COVERAGE_FILE = DATA / "convert" / "rules_coverage.json"


# ---------------------------------------------------------------------------------------------------------- coverage
def covered_bodies() -> set[str]:
    try:
        return {str(b) for b in json.loads(COVERAGE_FILE.read_text())["bodies_with_rules"]}
    except (OSError, ValueError, KeyError):
        return set()


def _body_key(body) -> str | None:
    b = str(body).strip() if body not in (None, "") else ""
    return b or None


def coverage(body, anchors: dict | None = None) -> dict:
    """{body, status: covered | not_covered | user_anchors | unknown, note}. `user_anchors`: the frozen rules do not
    cover the body, but the --anchors file has entries for it."""
    b = _body_key(body)
    if b is None:
        return dict(body=None, status="unknown",
                    note="no --body given: whether the frozen rules know this layout was not checked")
    cov = covered_bodies()
    if b in cov or b.upper() in cov:
        return dict(body=b, status="covered", note="the frozen rules were written on documents of this parliament")
    if anchors and _body_specs(anchors, b, include_wildcard=False):
        return dict(body=b, status="user_anchors",
                    note=f"no frozen rules for {b}; your anchors from {anchors.get('file')} are tried after them")
    return dict(body=b, status="not_covered",
                note=f"no frozen rules for {b} (not in data/convert/rules_coverage.json): nulls are no_rules_for_body, "
                     "values need review; add --anchors or use review mode")


def coverage_warning(cov: dict) -> str | None:
    if cov["status"] == "not_covered":
        return (f"warning: body {cov['body']} is not in data/convert/rules_coverage.json; the frozen rules were never "
                "written for its layout. Rows are marked needs_review and open fields get null_reason no_rules_for_body. "
                "Add your own anchors (--anchors FILE, docs/convert-your-own.md) or use --mode review.")
    if cov["status"] == "user_anchors":
        return (f"note: body {cov['body']} is not in data/convert/rules_coverage.json; using your anchors "
                f"({cov['note'].split('from ', 1)[-1].split(' are')[0]}) after the frozen rules.")
    return None


# ---------------------------------------------------------------------------------------------- recommendation qualifiers
# unambiguous: the government recommends accepting (or rejecting) only part of the motion
PARTIAL_Q = re.compile(r"\b(?:teilweise(?:\s+erheblich)?|partiell|partiellement|en\s+partie|parzialmente|in\s+parte)\b", re.I)
# the value stands, but a reviewer must read the sentence: conditions, modified wording, per-point recommendations
REVIEW_Q = [
    (re.compile(r"im\s+Sinne\s+der\s+Erw[äa]gungen", re.I), "conditional ('im Sinne der Erwägungen')"),
    (re.compile(r"dans\s+le\s+sens\s+des\s+consid[ée]rants", re.I), "conditional ('dans le sens des considérants')"),
    (re.compile(r"nel\s+senso\s+dei\s+considerandi", re.I), "conditional ('nel senso dei considerandi')"),
    (re.compile(r"mit\s+ge[äa]ndertem\s+Wortlaut", re.I), "modified wording ('mit geändertem Wortlaut')"),
    (re.compile(r"(?:avec|sous)\s+(?:un|une|le|la)\s+(?:texte|libell[ée]|teneur)\s+modifi[ée]e?", re.I), "modified wording"),
    (re.compile(r"con\s+(?:un\s+)?testo\s+modificato", re.I), "modified wording ('con testo modificato')"),
    (re.compile(r"Nichteintreten", re.I), "'Nichteintreten' (not entering into the matter) in the same sentence"),
    (re.compile(r"sous\s+r[ée]serve|unter\s+(?:dem\s+)?Vorbehalt|con\s+riserva", re.I), "with a reservation"),
]
# Per-point recommendations ("Ziffer 2 der Motion abzulehnen", BE's "Annahme als Postulat / Ziffer 3: ...") are NOT flagged
# here: on the 3,398 cached documents a "Ziffer/point N" qualifier fired on 121 rule values, mostly the next table row of
# a covered body; `multiple_recommendations` already flags documents whose points get different labels.
SENTENCE_END = re.compile(r"[.;](?=\s|$)|:[ \t]*\n")
AFTER = 120  # characters after the rule's match that still count as the same sentence


def qualify_recommendation(pages: list[str], f: dict) -> dict | None:
    """f: the frozen recommendation value {value, page, char_start, char_end, rule}. Returns None when no qualifier is in
    the matched sentence, else {qualifier, value, char_end, needs_review, reason}."""
    if f.get("value") not in ("accept", "reject", "convert") or f.get("page") is None:
        return None
    t = pages[f["page"] - 1]
    s, e = f["char_start"], f["char_end"]
    m_end = SENTENCE_END.search(t, e, min(len(t), e + AFTER))
    hi = m_end.start() if m_end else min(len(t), e + AFTER)
    window = t[s:hi]
    p = PARTIAL_Q.search(window)
    others = [(m, why) for m, why in ((rx.search(window), why) for rx, why in REVIEW_Q) if m]
    if not p and not others:
        return None
    found = sorted(([p] if p else []) + [m for m, _ in others], key=lambda m: m.start())
    new_end = max(e, s + max(m.end() for m in found))
    if new_end - s > 400:  # the record's quote is capped at 400 characters: keep the rule's span, the qualifier has its own
        new_end = e

    def qual(m, effect):
        return dict(text=re.sub(r"\s+", " ", m.group(0)), page=f["page"], char_start=s + m.start(), char_end=s + m.end(),
                    effect=effect)
    if p and not others and f["value"] in ("accept", "reject"):
        return dict(qualifier=qual(p, "partial"), value="partial", char_end=new_end, needs_review=False, reason=None)
    why = [w for _, w in others]
    if p:
        why.insert(0, f"'{p.group(0)}' (partial) " + ("on a conversion" if f["value"] == "convert" else
                                                       "together with another qualifier"))
    return dict(qualifier=qual(found[0], "needs_review"), value=f["value"], char_end=new_end, needs_review=True,
                reason=f"the {f['value']} phrase is qualified: " + "; ".join(why))


# ---------------------------------------------------------------------------------------------- heading proximity
HEADING_WINDOW = 80
GAP_OK = re.compile(r"[^\n.;]{0,40}?[ \t]*(?:\n\s*)?")  # rest of the heading line (no sentence end), optional line break
# a heading that names the instrument ("Réponse à l'interpellation du 5.9.2025", "Beantwortung der Interpellation vom ...")
# is followed by the INSTRUMENT's date (submission), not the answer's: only headings naming the executive count
INSTRUMENT = re.compile(r"Interpellation|Anfrage|Frage|Motion|Postulat|question|r[ée]solution|interpellanza|"
                        r"interrogazione|mozione|postulato", re.I)


def heading_date(pages: list[str]) -> dict | None:
    """The first printed date right after an executive answer heading in the document head (the frozen rules' head
    window, rules.HEAD_CHARS). Right after = within HEADING_WINDOW characters, separated only by the rest of the heading
    line ('vom', ':', 'd'Etat :') and at most one line break; never a footer, edit or submission line, and never after a
    heading that names the instrument (its date is the instrument's)."""
    off = 0
    for pi, t in enumerate(pages, start=1):
        if off >= rules.HEAD_CHARS:
            break
        for h in rules.ANSWER_HEADING.finditer(t):
            if off + h.start() >= rules.HEAD_CHARS:
                break
            seg = t[h.end(): h.end() + HEADING_WINDOW]
            ds = lattice.dates([seg])
            if not ds:
                continue
            c = ds[0]
            if not GAP_OK.fullmatch(seg[: c["char_start"]]):
                continue
            s, e = h.end() + c["char_start"], h.end() + c["char_end"]
            ln = rules._line(t, s)
            if rules.FOOTER.search(ln) or rules.SUBMISSION.search(ln) or INSTRUMENT.search(t[h.start():s]):
                continue
            return dict(value=c["value"], page=pi, char_start=s, char_end=e, quote=t[s:e],
                        heading=re.sub(r"\s+", " ", t[h.start():s]).strip(" :\u2013\u2014-"),
                        gap=re.sub(r"\s+", " ", seg[: c["char_start"]]))
        off += len(t) + 1
    return None


# ---------------------------------------------------------------------------------------------- user anchors
REC_LABELS = ("accept", "reject", "convert", "partial", "accept_and_write_off")
ROLES = (None, "decision", "dispatch")
ANCHOR_AFTER = 80  # an answer-date anchor without a date group: the first date within this many characters after it


class AnchorError(SystemExit):
    """A malformed --anchors file: exits the CLI with the message (status 2 via __main__)."""


def _compile(pattern: str, where: str) -> re.Pattern:
    if not isinstance(pattern, str) or not pattern.strip():
        raise AnchorError(f"--anchors: {where}: 'pattern' must be a non-empty string")
    p = pattern.replace("{DATE}", rules.DATE, 1).replace("{DATE}", rules.DATE.replace("?P<date>", "?:"))
    try:
        return rules._ws(re.compile(p, re.I | re.M))
    except re.error as e:
        raise AnchorError(f"--anchors: {where}: invalid regular expression: {e}") from None


def load_anchors(path: str) -> dict:
    """Read and compile a user anchor file (JSON; docs/examples/anchors_SG.json):

      {"bodies": {"SG": {"answer_date":    [{"id": "...", "pattern": "Antwort der Regierung vom {DATE}", "role": "dispatch"}],
                         "recommendation": [{"id": "...", "pattern": "^\\s*Nichteintreten\\b", "label": "reject"}]},
                  "*":  {...}}}                       # "*": tried for every body

    `{DATE}` expands to the frozen rules' date expression with a named group `date` (or write your own `(?P<date>...)`).
    A recommendation pattern may mark the phrase itself with `(?P<phrase>...)`; the span is then that group.
    Patterns are case-insensitive and multi-line; a literal space matches any whitespace run (as in the frozen rules)."""
    p = Path(path)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AnchorError(f"--anchors: no such file: {path}") from None
    except ValueError as e:
        raise AnchorError(f"--anchors: {path} is not valid JSON: {e}") from None
    if not isinstance(d, dict) or not isinstance(d.get("bodies"), dict):
        raise AnchorError(f"--anchors: {path} needs an object {{\"bodies\": {{\"<body key>\": {{...}}}}}}")
    out = dict(file=str(path), bodies={})
    for body, spec in d["bodies"].items():
        if not isinstance(spec, dict) or set(spec) - {"answer_date", "recommendation", "note"}:
            raise AnchorError(f"--anchors: bodies.{body}: only 'answer_date', 'recommendation' (lists) and 'note' are allowed")
        comp = dict(answer_date=[], recommendation=[])
        for i, a in enumerate(spec.get("answer_date") or []):
            where = f"bodies.{body}.answer_date[{i}]"
            if not isinstance(a, dict):
                raise AnchorError(f"--anchors: {where} must be an object with 'pattern'")
            if a.get("role") not in ROLES:
                raise AnchorError(f"--anchors: {where}: role must be 'decision', 'dispatch' or absent")
            rx = _compile(a.get("pattern"), where)
            comp["answer_date"].append(dict(id=a.get("id") or f"{body}_date_{i}", rx=rx, pattern=a["pattern"],
                                            role=a.get("role"), has_date_group="date" in rx.groupindex))
        for i, a in enumerate(spec.get("recommendation") or []):
            where = f"bodies.{body}.recommendation[{i}]"
            if not isinstance(a, dict):
                raise AnchorError(f"--anchors: {where} must be an object with 'pattern' and 'label'")
            if a.get("label") not in REC_LABELS:
                raise AnchorError(f"--anchors: {where}: label must be one of {', '.join(REC_LABELS)}")
            comp["recommendation"].append(dict(id=a.get("id") or f"{body}_rec_{i}", rx=_compile(a.get("pattern"), where),
                                               pattern=a["pattern"], label=a["label"]))
        out["bodies"][str(body)] = comp
    return out


def _body_specs(anchors: dict | None, body, include_wildcard: bool = True) -> dict:
    """The anchors that apply to `body`: its own entry (key compared case-insensitively) then the '*' entry."""
    res = dict(answer_date=[], recommendation=[])
    if not anchors:
        return {}
    b = _body_key(body)
    keys = [k for k in anchors["bodies"] if b is not None and k.upper() == b.upper()]
    if include_wildcard and "*" in anchors["bodies"]:
        keys.append("*")
    for k in keys:
        for f in res:
            res[f] += anchors["bodies"][k][f]
    return res if any(res.values()) else {}


def anchors_for(anchors: dict | None, body) -> dict:
    return _body_specs(anchors, body)


def apply_date_anchors(pages: list[str], specs: list[dict], file: str | None = None) -> tuple[dict | None, list[dict]]:
    """First user anchor (file order; pages in order) that yields a date. -> (field dict | None, trace)."""
    trace = []
    for a in specs:
        why = "no match"
        for pi, t in enumerate(pages, start=1):
            for m in a["rx"].finditer(t):
                if a["has_date_group"] and m.group("date"):
                    ds = lattice.dates([m.group("date")])
                    if not ds:
                        why = f"matched on p{pi}, but the date group '{m.group('date')}' does not parse as a date"
                        continue
                    s, e = m.span("date")
                    review = False
                else:
                    seg = t[m.end(): m.end() + ANCHOR_AFTER]
                    ds = lattice.dates([seg])
                    if not ds:
                        why = f"matched on p{pi}, but no date within {ANCHOR_AFTER} characters after it"
                        continue
                    s, e = m.end() + ds[0]["char_start"], m.end() + ds[0]["char_end"]
                    review = True
                ln = rules._line(t, s)
                if rules.FOOTER.search(ln):
                    why = f"matched on p{pi}, but the date sits on a footer/edit line"
                    continue
                trace.append(dict(step=f"user anchor {a['id']}", result=f"fired: {ds[0]['value']} at p{pi}[{s}:{e}]"))
                out = dict(value=ds[0]["value"], role=a["role"], route="user_anchor", page=pi, char_start=s, char_end=e,
                           quote=t[s:e], rule=f"user_anchor:{a['id']}", anchor_file=file, anchor_pattern=a["pattern"],
                           needs_review=review)
                if review:
                    out["review_reason"] = (f"user anchor {a['id']} has no (?P<date>...) group / {{DATE}}: the first date "
                                            "after it was taken")
                return out, trace
        trace.append(dict(step=f"user anchor {a['id']}", result=why))
    return None, trace


def apply_rec_anchors(pages: list[str], specs: list[dict], file: str | None = None) -> tuple[dict | None, list[dict]]:
    """First user recommendation phrase that matches (file order). Needs review when phrases of different labels match."""
    trace, hits = [], []
    for a in specs:
        found = None
        for pi, t in enumerate(pages, start=1):
            m = a["rx"].search(t)
            if m and m.end() > m.start():
                found = (pi, m)
                break
        trace.append(dict(step=f"user anchor {a['id']} ({a['label']})",
                          result=f"matched at p{found[0]}[{found[1].start()}:{found[1].end()}]" if found else "no match"))
        if found:
            hits.append((a, found))
    if not hits:
        return None, trace
    a, (pi, m) = hits[0]
    labels = sorted({h[0]["label"] for h in hits})
    s, e = m.span("phrase") if "phrase" in m.re.groupindex and m.group("phrase") else m.span()
    out = dict(value=a["label"], role=None, route="user_anchor", page=pi, char_start=s, char_end=e,
               quote=pages[pi - 1][s:e], rule=f"user_anchor:{a['id']}", anchor_file=file,
               anchor_pattern=a["pattern"], needs_review=len(labels) > 1)
    if len(labels) > 1:
        out["review_reason"] = f"user anchors for different labels match: {', '.join(labels)}"
    trace.append(dict(step="user anchors", result=f"chose {a['id']} -> {a['label']}"))
    return out, trace


# ---------------------------------------------------------------------------------------------- --explain traces
def _hits(rx: re.Pattern, pages: list[str]):
    for pi, t in enumerate(pages, start=1):
        for m in rx.finditer(t):
            yield pi, t, m


def trace_answer_date(pages: list[str], image_only: bool = False) -> list[dict]:
    """Replays the frozen rules.answer_date order step by step and says why each step did not decide. Read-only: the
    decision is the frozen function's; tests check that the step marked `fired` is the rule it returned."""
    steps = []
    full = "\n".join(pages)
    if not full.strip():
        return [dict(step="empty_text", result="fired: no text (image_only/text_failed)")]
    if len(full.strip()) < 400 and rules.ORAL.search(full):
        return [dict(step="oral_stub", result="fired: short text that says the answer was oral")]
    steps.append(dict(step="oral_stub", result="not a short oral-answer stub"))
    for rid, rx in rules.DECISION:
        n = footer = bad = 0
        for pi, t, m in _hits(rx, pages):
            n += 1
            if rules.FOOTER.search(rules._line(t, m.start(rules._dgroup(m)))):
                footer += 1
                continue
            if rules._date_of(m):
                s, e = m.span(rules._dgroup(m))
                steps.append(dict(step=rid, result=f"fired: decision anchor at p{pi}[{s}:{e}]"))
                return steps
            bad += 1
        steps.append(dict(step=rid, result="no match" if not n else
                          f"{n} match(es), {footer} on footer/edit lines, {bad} with a date that does not parse"))
    for pi, _t, m in _hits(rules.SIGNATURE, pages):
        if rules._date_of(m):
            s, e = m.span("date")
            steps.append(dict(step="signature_block", result=f"fired: place-date above an executive signature at p{pi}[{s}:{e}]"))
            return steps
    steps.append(dict(step="signature_block", result="no place-date line directly above an executive signature block"))
    head = full[: rules.HEAD_CHARS]
    h = rules.ANSWER_HEADING.search(head)
    if rules.BE_EMPTY.search(head) and not h:
        steps.append(dict(step="be_empty_template", result="fired: empty 'RRB-Nr.: ... vom' answer template -> not_in_document"))
        return steps
    if not h:
        steps.append(dict(step="answer heading", result=f"no executive answer heading in the first {rules.HEAD_CHARS} "
                          "characters, so the dispatch rules (place-date, Date de dépôt, zugestellt am, ...) were not tried"))
        steps.append(dict(step="no_anchor", result="fired: abstain (residue)"))
        return steps
    steps.append(dict(step="answer heading", result=f"found '{h.group(0).strip()[:60]}': dispatch rules tried"))
    last = len(pages)
    tail_from = max(0, len(pages[-1]) - rules.TAIL_CHARS)
    cands = [(rid, rx, "head", 1, 0, rules.HEAD_CHARS) for rid, rx in rules.DISPATCH]
    cands.append(("date_line_above_heading", rules.DATE_LINE, "head", 1, max(0, h.start() - 200), h.start()))
    cands += [("place_date", rules.DISPATCH[2][1], "tail", last, tail_from, len(pages[-1])),
              ("le_date_line", rules.LE_DATE_LINE, "tail", last, tail_from, len(pages[-1]))]
    for rid, rx, where, pi, lo, hi in cands:
        n = skipped = 0
        t = pages[pi - 1]
        for m in rx.finditer(t, lo, min(hi, len(t))):
            n += 1
            ln = rules._line(t, m.start("date"))
            if rules.FOOTER.search(ln) or rules.SUBMISSION.search(ln):
                skipped += 1
                continue
            if rules._date_of(m):
                s, e = m.span("date")
                steps.append(dict(step=f"{rid}_{where}", result=f"fired: dispatch date at p{pi}[{s}:{e}]"))
                return steps
        scope = (f"page {pi} characters {lo}-{min(hi, len(t))}")
        steps.append(dict(step=f"{rid}_{where}", result=f"no match in {scope}" if not n else
                          f"{n} match(es) in {scope}, {skipped} on footer/submission lines"))
    steps.append(dict(step="heading_without_date", result="fired: abstain (heading found, no anchored date)"))
    return steps


def trace_recommendation(pages: list[str], affair_type: str | None = None) -> list[dict]:
    if affair_type in ("Interpellation", "Question", "Question time"):
        return [dict(step="affair_type", result=f"fired: not_applicable for {affair_type}")]
    steps = []
    for lab, rx in rules.REC:
        for pi, t in enumerate(pages, start=1):
            m = rx.search(t)
            if m:
                steps.append(dict(step=f"rec_{lab}", result=f"fired at p{pi}[{m.start()}:{m.end()}]"))
                return steps
        steps.append(dict(step=f"rec_{lab}", result="no phrase of this label (with the executive as subject)"))
    steps.append(dict(step="no_anchor", result="fired: abstain (residue)"))
    return steps


def cache_info() -> dict:
    import os
    return dict(work=str(WORK), pdf_cache=str(PDF_CACHE), text_cache=str(TEXT_CACHE),
                gp_work_set=bool(os.environ.get("GP_WORK")),
                note=("GP_WORK" if os.environ.get("GP_WORK") else
                      "default: the repository's .work/ (set GP_WORK to put the cache elsewhere)"))


def render_explain(ex: dict) -> str:
    """Human-readable --explain block (stderr)."""
    c = ex["cache"]
    lines = [f"cache: {c['work']}  ({c['note']})", f"  PDFs  {c['pdf_cache']}", f"  texts {c['text_cache']}"]
    cov = ex["rules_coverage"]
    lines.append(f"rules coverage: body={cov['body']} -> {cov['status']}: {cov['note']}")
    for name in ("answer_date", "recommendation"):
        if name not in ex:
            continue
        lines.append(f"{name}:")
        for s in ex[name]:
            lines.append(f"  {s['step']:<32} {s['result']}")
    return "\n".join(lines)
