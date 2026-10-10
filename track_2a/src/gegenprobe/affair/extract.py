"""Whole-affair extraction: every schema field from (i) OPD metadata, (ii) deterministic rules on the affair's documents,
(iii) the Apertus closed-set pointer on what is still open — the same principle as the answer-date converter.

A field record is a plain dict, either
  value: {value, route, basis, source | (doc, page, char_start, char_end, quote), rule?, model_build?, theta?, margin?,
          candidates?}
  null:  {value: None, null_reason, route, evidence, doc?}
`affair.build` turns records into a validated schema_v0_1.Affair.

Closed sets for the pointer (never free generation):
  submitter       names of the body's office holders known to OPD (contributors export) whose surname is printed in the
                  question document, + null
  submitted       dates printed in the question document, + null
  addressed_body  executive | parliament | committee | administration, + null
  affair_type     motion | postulate | interpellation | question | resolution, + null
  answer_date     dates printed in the answer document, + null (the frozen P1 pointer)
  recommendation  accept | reject | convert, + null (the frozen P1 pointer)
"""

from __future__ import annotations

import json
import re
import unicodedata

from ..census import defs
from ..convert import cascade, lattice, pointer, rules
from ..paths import DATA, PROMPTS

FIELDS = (
    "number",
    "affair_type",
    "title",
    "submitter",
    "co_signatories",
    "addressed_body",
    "submitted",
    "answer_date",
    "decision_number",
    "recommendation",
    "procedural_state",
    "decision",
    "related_affairs",
    "answer_link_status",
)

# ------------------------------------------------------------------------------------------------ metadata vocabularies
_TYPES = json.loads((DATA / "schema" / "affair_types.json").read_text())
TYPE_BY_EN = {t["labels"]["en"].lower(): t["key"] for t in _TYPES}
TYPE_BY_EN.update({"question time": "question_time"})
EVENT_MAP = {e["opd_id"]: e["maps_to"] for e in json.loads((DATA / "schema" / "opd_event_titles.json").read_text())}
SUBMITTED_HIDS = (1, 56, 67)
BE_LOAD_DATE = "2024-10-28"  # OPD load timestamp in BE begin_date (OPD confirmed; repair_BE_begin_date)


def _null(reason: str, route: str, evidence: str, **kw) -> dict:
    return dict(value=None, null_reason=reason, route=route, evidence=evidence, **kw)


def _meta(value, source: str, **kw) -> dict:
    return dict(value=value, route="metadata", basis="metadata", source=source, **kw)


def _span(value, doc: str, page: int, s: int, e: int, text: str, basis: str = "extracted", route: str = "rule", **kw) -> dict:
    return dict(value=value, route=route, basis=basis, doc=doc, page=page, char_start=s, char_end=e, quote=text[s:e][:400], **kw)


# ------------------------------------------------------------------------------------------------ (i) metadata
def from_metadata(m: dict, link_status: str | None) -> dict:
    a, evs, cons = m["affair"], m["events"], m["contributors"]
    src = f"opd:affairs/{a['id']}"
    out: dict = {}
    out["number"] = _meta(a["number"], src) if a.get("number") else _null("not_in_corpus", "metadata", "affair has no number")
    t = TYPE_BY_EN.get((a.get("type_harmonized_en") or "").lower())
    label = a.get("type_name_de") or a.get("type_name_fr") or a.get("type_name_it")
    out["affair_type"] = _meta(t, src, source_label=label) if t else _null("not_in_corpus", "metadata", "no harmonised type")
    out["title"] = {lg: a[f"title_{lg}"] for lg in ("de", "fr", "it") if a.get(f"title_{lg}")}
    authors = [c for c in cons if c.get("role_harmonized") == "author" and c.get("type") == "person" and c.get("fullname")]
    if authors:
        first = authors[0]
        out["submitter"] = _meta(_person(first), f"opd:contributors/{first['id']}", party=first.get("party_harmonized_de"))
        out["co_signatories"] = [_meta(_person(c), f"opd:contributors/{c['id']}") for c in authors[1:]]
    else:
        out["submitter"] = _null("not_in_corpus", "metadata", "no author in OPD contributors")
        out["co_signatories"] = []
    sub = sorted((e for e in evs if e.get("title_harmonized_id") in SUBMITTED_HIDS and e.get("date")), key=lambda e: e["date"])
    if sub:
        out["submitted"] = _meta(sub[0]["date"][:10], f"opd:events/{sub[0]['id']}")
    elif a.get("begin_date") and not (a["body_key"] == "BE" and a["begin_date"][:10] == BE_LOAD_DATE):
        out["submitted"] = _meta(a["begin_date"][:10], src + "#begin_date")
    else:
        out["submitted"] = _null("not_in_corpus", "metadata", "no submission event; begin_date absent or a load timestamp")
    ans = sorted(
        (e for e in evs if e.get("date") and defs.classify_event(defs.event_title(e), e.get("title_harmonized_id")) == "written"),
        key=lambda e: e["date"],
    )
    out["answer_event"] = (
        _meta(ans[0]["date"][:10], f"opd:events/{ans[0]['id']}")
        if ans
        else _null("not_in_corpus", "metadata", "no written-answer event")
    )
    rec = [e for e in evs if "recommendation" in EVENT_MAP.get(e.get("title_harmonized_id"), {})]
    out["recommendation"] = (
        _meta(EVENT_MAP[rec[-1]["title_harmonized_id"]]["recommendation"], f"opd:events/{rec[-1]['id']}")
        if rec
        else _null("not_in_corpus", "metadata", "no recommendation event")
    )
    st = [e for e in evs if "state" in EVENT_MAP.get(e.get("title_harmonized_id"), {})]
    out["procedural_state"] = (
        _meta(EVENT_MAP[st[-1]["title_harmonized_id"]]["state"], f"opd:events/{st[-1]['id']}")
        if st
        else _null("not_in_corpus", "metadata", "no harmonised state event")
    )
    dc = [e for e in evs if "decision" in EVENT_MAP.get(e.get("title_harmonized_id"), {})]
    out["decision"] = (
        _meta(EVENT_MAP[dc[-1]["title_harmonized_id"]]["decision"], f"opd:events/{dc[-1]['id']}")
        if dc
        else _null("not_in_corpus", "metadata", "no decision event")
    )
    out["answer_link_status"] = link_status or "not_applicable"
    return out


def _person(c: dict) -> str:
    f, n = (c.get("firstname") or "").strip(), (c.get("lastname") or "").strip()
    return f"{f} {n}".strip() if n else c["fullname"]


# ------------------------------------------------------------------------------------------------ (ii) rules on documents
def _fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).lower()


def _num_norm(s: str) -> str:
    return re.sub(r"[\s_.\-/]+", "", _fold(s or ""))


TYPE_WORDS = [
    ("interpellation", r"\b(dringliche\s+)?interpellation\b|\binterpellanza\b"),
    ("motion", r"\b(dringliche\s+)?motion\b|\bmozione\b"),
    ("postulate", r"\bpostulat\b|\bpostulato\b"),
    (
        "question",
        r"\b(schriftliche|kleine)\s+anfrage\b|\banfrage\b|\bquestion\s+(écrite|ecrite)\b|\binterrogazione\b|"
        r"\bfragestunde\b|\bquestion\b",
    ),
    ("resolution", r"\br[ée]solution\b|\brisoluzione\b|\bresolution\b"),
]
TYPE_RX = [(k, re.compile(rx, re.I)) for k, rx in TYPE_WORDS]
ADDRESSED = [
    (
        "executive",
        re.compile(
            r"\b(an|à|au|al|alla)\s+(den|die|le|la|il)?\s*(Regierungsrat|Stadtrat|Gemeinderat|Conseil[- ]d.[ÉE]tat|"
            r"Conseil[- ]ex[ée]cutif|Conseil communal|Conseil administratif|Municipalit[ée]|Consiglio di Stato|"
            r"Municipio|Regierung|Bundesrat)\b",
            re.I,
        ),
    ),
    ("committee", re.compile(r"\b(an|à|al)\s+(die|la)?\s*(Kommission|commission|commissione)\b", re.I)),
    (
        "parliament",
        re.compile(
            r"\b(an|à|au|al)\s+(den|le|il)?\s*(Grossen Rat|Kantonsrat|Landrat|Gemeinderat|Grand Conseil|"
            r"Conseil municipal|Gran Consiglio|Consiglio comunale)\b",
            re.I,
        ),
    ),
]
SUBMIT_CUE = re.compile(
    r"Eingereicht\s+am|eingereicht\s+am|Eingang|d[ée]pos[ée]e?s?\s+le|Date\s+de\s+d[ée]p[ôo]t|"
    r"presentat[ao]\s+il|inoltrat[ao]\s+il|Datum\s*:",
    re.I,
)
AUTHOR_CUE = re.compile(
    r"eingereicht\s+von|Vorst[öo]sser|Interpellant|Motion[äa]r|Postulant|Urheber|Erstunterzeichn|"
    r"d[ée]pos[ée]e?\s+par|auteur|signataire|presentat[ao]\s+da|firmatari|di\s+[A-Z]",
    re.I,
)


def rule_fields(
    pages_q: list[str] | None,
    pages_a: list[str] | None,
    doc_q: str | None,
    doc_a: str | None,
    meta_out: dict,
    body: str,
    names: list[tuple[str, str]],
    affair_type: str | None,
    answer_events: list[str],
) -> dict:
    out: dict = {}
    own = meta_out["number"]["value"] if meta_out["number"].get("value") else None
    docs = [(d, p) for d, p in ((doc_q, pages_q), (doc_a, pages_a)) if p]
    # number: the affair's own OPD number printed in either document
    out["number"] = _null("present_unanchored", "rule", "own OPD number not found printed")
    if own:
        key = _num_norm(own)
        for d, pages in docs:
            for pi, t in enumerate(pages, 1):
                for m in lattice.AFFAIR_SHAPES.finditer(t):
                    if _num_norm(m.group(0)) == key:
                        out["number"] = _span(own, d, pi, m.start(), m.end(), t, basis="normalised", rule="own_number_printed")
                        break
                if out["number"].get("value"):
                    break
            if out["number"].get("value"):
                break
    # affair type: first type word in the head of the question document
    out["affair_type"] = _null("present_unanchored", "rule", "no type word in the question head", doc=doc_q)
    if pages_q:
        head = pages_q[0][:1500]
        best = None
        for k, rx in TYPE_RX:
            m = rx.search(head)
            if m and (best is None or m.start() < best[1].start()):
                best = (k, m)
        if best:
            out["affair_type"] = _span(
                best[0], doc_q, 1, best[1].start(), best[1].end(), pages_q[0], basis="inferred", rule="type_word_head"
            )
    # submitter: a known office holder of the body printed after an author cue in the question document
    out["submitter"] = _null("present_unanchored", "rule", "no known name after an author cue", doc=doc_q)
    if pages_q:
        hit = _name_after_cue(pages_q, names)
        if hit:
            pi, s, e, full = hit
            out["submitter"] = _span(full, doc_q, pi, s, e, pages_q[pi - 1], basis="normalised", rule="name_after_author_cue")
    # addressed body
    out["addressed_body"] = _null("present_unanchored", "rule", "no addressee phrase", doc=doc_q)
    if pages_q:
        for k, rx in ADDRESSED:
            m = rx.search(pages_q[0][:3000])
            if m:
                out["addressed_body"] = _span(
                    k, doc_q, 1, m.start(), m.end(), pages_q[0], basis="inferred", rule=f"addressed_{k}"
                )
                break
    # submission date: a date within 80 chars after a submission cue in the question document
    out["submitted"] = _null("present_unanchored", "rule", "no date after a submission cue", doc=doc_q)
    if pages_q:
        for pi, t in enumerate(pages_q, 1):
            for c in SUBMIT_CUE.finditer(t):
                seg = t[c.end() : c.end() + 80]
                dm = lattice.DATE_RE.search(seg)
                iso = lattice._iso(dm) if dm else None
                if iso:
                    s = c.end() + dm.start()
                    out["submitted"] = _span(
                        iso, doc_q, pi, s, c.end() + dm.end(), t, basis="normalised", rule="date_after_submission_cue"
                    )
                    break
            if out["submitted"].get("value"):
                break
    # answer date + decision number: the frozen P1 cascade (rules only here) on the answer document
    if pages_a:
        r = cascade.answer_date(
            dict(pages=pages_a, image_only=False, opd_answer_dates=answer_events), None, None, use_metadata=bool(answer_events)
        )
        out["answer_date"] = _from_cascade(r, doc_a, pages_a)
        out["decision_number"] = r.get("number")
        rr = rules.recommendation(pages_a, _opd_type_name(affair_type))
        if rr["status"] == "value":
            sp = rr["span"]
            out["recommendation"] = _span(
                rr["value"],
                doc_a,
                sp["page"],
                sp["char_start"],
                sp["char_end"],
                pages_a[sp["page"] - 1],
                basis="inferred",
                rule=rr["rule"],
            )
        elif rr["status"] == "null":
            out["recommendation"] = _null(rr["null_reason"], "rule", rr["rule"], doc=doc_a)
        else:
            out["recommendation"] = _null("present_unanchored", "rule", rr["rule"], doc=doc_a)
    else:
        out["answer_date"] = _null("not_in_corpus", "metadata", "no answer document linked")
        out["decision_number"] = None
        out["recommendation"] = _null("not_in_corpus", "metadata", "no answer document linked")
    # related affairs: other OPD-known numbers printed in either document
    rel, seen_n = [], set()
    for d, pages in docs:
        for c in lattice.affair_numbers(pages, body):
            if own and _num_norm(c["value"]) == _num_norm(own) or c["value"] in seen_n:
                continue
            seen_n.add(c["value"])
            rel.append(
                _span(
                    c["value"],
                    d,
                    c["page"],
                    c["char_start"],
                    c["char_end"],
                    pages[c["page"] - 1],
                    basis="normalised",
                    rule="opd_number_printed",
                )
            )
    out["related_affairs"] = rel
    return out


def _opd_type_name(t: str | None) -> str | None:
    return {
        "interpellation": "Interpellation",
        "question": "Question",
        "question_time": "Question time",
        "motion": "Motion",
        "postulate": "Postulate",
    }.get(t or "")


def _from_cascade(r: dict, doc: str, pages: list[str]) -> dict:
    if r.get("value") is None:
        reason = r.get("null_reason") or "present_unanchored"
        route = r.get("route", "rule")
        if reason not in ("not_in_document", "present_unanchored", "oral", "not_applicable", "image_only", "text_failed"):
            reason = "present_unanchored"
        # residue = the frozen P1 cascade would hand this document to the pointer (rules abstained, not ruled out)
        return _null(
            reason,
            "rule" if route == "metadata" else route,
            r.get("rule") or "rules abstained",
            doc=doc,
            residue=bool(r.get("residue")),
        )
    if r.get("page") is None:
        return _null("present_unanchored", "rule", "value without span", doc=doc)
    route = "rule" if r["route"] == "metadata" else r["route"]
    return _span(
        r["value"],
        doc,
        r["page"],
        r["char_start"],
        r["char_end"],
        pages[r["page"] - 1],
        basis="normalised",
        route=route,
        rule=r.get("rule"),
    )


def _name_after_cue(pages: list[str], names: list[tuple[str, str]]):
    """(page, start, end, 'First Last') of the first known name printed within 200 chars after an author cue."""
    by_last = {}
    for first, last in names:
        if len(last) >= 3:
            by_last.setdefault(_fold(last), []).append((first, last))
    for pi, t in enumerate(pages[:2], 1):
        for c in AUTHOR_CUE.finditer(t):
            seg = t[c.end() : c.end() + 200]
            for w in re.finditer(r"[A-ZÄÖÜÉÈÀÂÊÎÔÛÇ][\w'’\-]{2,}", seg):
                cands = by_last.get(_fold(w.group(0)))
                if not cands:
                    continue
                first, last = cands[0]
                for f2, l2 in cands:  # prefer the candidate whose first name is also printed nearby
                    if f2 and _fold(f2) in _fold(seg):
                        first, last = f2, l2
                        break
                s = c.end() + w.start()
                return pi, s, s + len(w.group(0)), f"{first} {last}".strip()
    return None


# ------------------------------------------------------------------------------------------------ (iii) Apertus pointer
PREFIX3 = {
    "submitter": {"de": '{"urheber":', "fr": '{"auteur":', "it": '{"autore":'},
    "submitted": {"de": '{"eingereicht":', "fr": '{"depose":', "it": '{"presentato":'},
    "addressed_body": {"de": '{"adressat":', "fr": '{"destinataire":', "it": '{"destinatario":'},
    "affair_type": {"de": '{"typ":', "fr": '{"type":', "it": '{"tipo":'},
}
ENUM3 = {
    "addressed_body": {
        "de": {"executive": "Regierung", "parliament": "Parlament", "committee": "Kommission", "administration": "Verwaltung"},
        "fr": {
            "executive": "gouvernement",
            "parliament": "parlement",
            "committee": "commission",
            "administration": "administration",
        },
        "it": {
            "executive": "governo",
            "parliament": "parlamento",
            "committee": "commissione",
            "administration": "amministrazione",
        },
    },
    "affair_type": {
        "de": {
            "interpellation": "Interpellation",
            "motion": "Motion",
            "postulate": "Postulat",
            "question": "Anfrage",
            "resolution": "Resolution",
        },
        "fr": {
            "interpellation": "interpellation",
            "motion": "motion",
            "postulate": "postulat",
            "question": "question",
            "resolution": "résolution",
        },
        "it": {
            "interpellation": "interpellanza",
            "motion": "mozione",
            "postulate": "postulato",
            "question": "interrogazione",
            "resolution": "risoluzione",
        },
    },
}
THETA3 = 0.0  # no dev labels exist for the new fields: θ = 0 declared in PREREG3 (as for the P1 recommendation pointer)


def _template(field: str, lang: str) -> tuple[str, str]:
    import hashlib

    lang = lang if lang in ("de", "fr", "it") else "de"
    t = (PROMPTS / lang / f"affair_{field}.txt").read_text(encoding="utf-8")
    return t, f"{lang}/affair_{field}.txt@{hashlib.sha256(t.encode()).hexdigest()[:12]}"


def _score(backend, field: str, lang: str, pages: list[str], conts: list[str]) -> tuple[list[float], float, str]:
    text, _, _ = pointer.doc_text(pages)
    tmpl, pid = _template(field, lang)
    lg = lang if lang in ("de", "fr", "it") else "de"
    lps = backend.score(tmpl.replace("{doc}", text), PREFIX3[field][lg], [pointer.NULL_CONT] + conts)
    return lps[1:], lps[0], pid


def _model(backend, theta, margin, n, pid) -> dict:
    return dict(model_build=getattr(backend, "build", "?"), theta=theta, margin=margin, candidates=n, prompt_id=pid)


def pointer_fields(
    backend,
    pages_q: list[str] | None,
    pages_a: list[str] | None,
    doc_q: str | None,
    doc_a: str | None,
    lang: str,
    names: list[tuple[str, str]],
    open_fields: set[str],
    theta_answer: float,
) -> dict:
    """Pointer suggestions for the fields still open after metadata and rules. Never written into a field by itself."""
    out: dict = {}
    lg = lang if lang in ("de", "fr", "it") else "de"
    if pages_q and "submitter" in open_fields:
        text = _fold("\n".join(pages_q)[: pointer.CHAR_BUDGET])
        cands = sorted(
            {f"{f} {n}".strip() for f, n in names if len(n) >= 3 and re.search(r"\b" + re.escape(_fold(n)) + r"\b", text)}
        )
        if cands:
            lps, lpn, pid = _score(backend, "submitter", lg, pages_q, [f' "{c}"' for c in cands])
            i, margin = pointer.decide(lpn, lps, THETA3)
            if i is not None:
                v = cands[i]
                sp = _locate_name(pages_q, v)
                out["submitter"] = (
                    _span(v, doc_q, *sp, basis="normalised", route="apertus", **_model(backend, THETA3, margin, len(cands), pid))
                    if sp
                    else None
                )
    if pages_q and "submitted" in open_fields:
        text, offs, _ = pointer.doc_text(pages_q)
        cands = [c for c in lattice.dates(pages_q) if pointer._visible(c, offs, pointer.CHAR_BUDGET)]
        values = lattice.distinct_dates(cands)
        if values:
            lps, lpn, pid = _score(backend, "submitted", lg, pages_q, [f' "{pointer.ddmmyyyy(v)}"' for v in values])
            i, margin = pointer.decide(lpn, lps, THETA3)
            if i is not None:
                c = next(c for c in cands if c["value"] == values[i])
                out["submitted"] = _span(
                    values[i],
                    doc_q,
                    c["page"],
                    c["char_start"],
                    c["char_end"],
                    pages_q[c["page"] - 1],
                    basis="normalised",
                    route="apertus",
                    **_model(backend, THETA3, margin, len(values), pid),
                )
    for field in ("addressed_body", "affair_type"):
        if pages_q and field in open_fields:
            labels = ENUM3[field][lg]
            keys = list(labels)
            lps, lpn, pid = _score(backend, field, lg, pages_q, [f' "{labels[k]}"' for k in keys])
            i, margin = pointer.decide(lpn, lps, THETA3)
            if i is not None:
                out[field] = dict(
                    value=keys[i], route="apertus", basis="inferred", doc=doc_q, **_model(backend, THETA3, margin, len(keys), pid)
                )
    if pages_a and "answer_date" in open_fields:
        p = pointer.answer_date(backend, pages_a, lg, theta_answer, anchors=rules.anchors(pages_a))
        if p.value and p.span:
            out["answer_date"] = _span(
                p.value,
                doc_a,
                p.span["page"],
                p.span["char_start"],
                p.span["char_end"],
                pages_a[p.span["page"] - 1],
                basis="normalised",
                route="apertus",
                **_model(backend, theta_answer, p.margin, len(p.candidates), p.prompt_id),
            )
    if pages_a and "recommendation" in open_fields:
        p = pointer.recommendation(backend, pages_a, lg, 0.0)
        if p.value:
            out["recommendation"] = dict(
                value=p.value,
                route="apertus",
                basis="inferred",
                doc=doc_a,
                **_model(backend, 0.0, p.margin, len(p.candidates), p.prompt_id),
            )
    return {k: v for k, v in out.items() if v}


def _locate_name(pages: list[str], full: str):
    last = full.split()[-1]
    for pi, t in enumerate(pages, 1):
        m = re.search(r"\b" + re.escape(last) + r"\b", t)
        if m:
            return pi, m.start(), m.end(), t
    return None
