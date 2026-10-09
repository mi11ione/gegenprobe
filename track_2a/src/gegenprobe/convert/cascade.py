"""Per-document cascade: (i) OPD metadata → (ii) frozen rules → (iii) Apertus closed-set pointer, only for the residue.

Every output value is a provenance record
  {value, role, page, char_start, char_end, quote, route ∈ {metadata, rule, apertus}, model_build, theta, margin, rule}
or a typed null
  {value: None, null_reason ∈ NULL_REASONS, route, ...}.
Document-level and affair-level are kept apart: the gold set and the evaluation score what THIS document says; OPD's
event date (route metadata) is attached as the affair-level value and is used for the document only when the same date is
printed in the document (then it gets that span).

`to_schema()` is the single adapter to the Pydantic schema (src/gegenprobe/schema/schema_v0_1.py).
"""

from __future__ import annotations

from . import lattice, pointer, rules

NULL_REASONS = (
    "not_in_corpus",
    "unlinked",
    "text_failed",
    "image_only",
    "oral",
    "present_unanchored",
    "not_applicable",
    "not_in_document",
)
# not_in_document: the document was read and the value is not in it (doc-level). The affair-level reasons
# (not_in_corpus / unlinked) need the census/repair join and are set there, not here.


def _value(v: str, role: str | None, span: dict | None, route: str, **kw) -> dict:
    out = dict(value=v, role=role, route=route, page=None, char_start=None, char_end=None, quote=None)
    if span:
        out.update({k: span.get(k) for k in ("page", "char_start", "char_end", "quote")})
        if "occurrence_rule" in span:
            out["occurrence_rule"] = span["occurrence_rule"]
    out.update(kw)
    return out


def _null(reason: str, route: str, **kw) -> dict:
    assert reason in NULL_REASONS, reason
    return dict(value=None, null_reason=reason, route=route, **kw)


def answer_date(doc: dict, backend=None, theta: float | None = None, use_metadata: bool = True, variant: str = "") -> dict:
    """doc: {pages, lang, image_only, extractor, opd_answer_dates? (list of ISO dates from OPD answer events)}"""
    pages = doc["pages"]
    r = rules.answer_date(pages, doc.get("image_only", False))
    doc_dates = lattice.dates(pages)
    # (i) metadata: OPD's answer event date, used for the document only if the document prints it at an answer anchor
    if use_metadata and doc.get("opd_answer_dates"):
        anch = rules.anchors(pages)
        for iso in doc["opd_answer_dates"]:
            span = pointer.locate(iso, doc_dates, pages, anch)
            if span and span["occurrence_rule"] in ("nearest_anchor", "only_occurrence") and r.get("value") in (None, iso):
                return _value(iso, r.get("role") or "decision", span, "metadata", rule="opd_event_date_in_document")
    # (ii) rules
    if r["status"] == "value":
        return _value(r["value"], r.get("role"), r.get("span"), "rule", rule=r["rule"], number=r.get("number"))
    if r["status"] == "null":
        return _null(r["null_reason"], "rule", rule=r["rule"])
    # (iii) pointer on the residue
    if backend is None or theta is None:
        return _null("present_unanchored" if doc_dates else "not_in_document", "rule", rule=r["rule"], residue=True)
    p = pointer.answer_date(backend, pages, doc.get("lang") or "de", theta, anchors=rules.anchors(pages), variant=variant)
    common = dict(
        model_build=p.model_build,
        theta=theta,
        margin=p.margin,
        prompt_id=p.prompt_id,
        truncated=p.truncated,
        rule=r["rule"],
        residue=True,
    )
    if p.value is None:
        return _null("not_in_document", "apertus", **common)
    return _value(p.value, None, p.span, "apertus", **common)


def convert(doc: dict, backend=None, thetas: dict | None = None, use_metadata: bool = True) -> dict:
    """All fields for one document. thetas: {"answer_date": θ, "recommendation": θ, "related_affair": θ} for this build."""
    thetas = thetas or {}
    out = dict(
        doc_id=doc.get("doc_id"),
        sha256=doc.get("sha256"),
        extractor=doc.get("extractor"),
        fields={"answer_date": answer_date(doc, backend, thetas.get("answer_date"), use_metadata)},
    )
    rec = rules.recommendation(doc["pages"], doc.get("affair_type"))
    if rec["status"] == "value":
        out["fields"]["recommendation"] = _value(rec["value"], None, rec["span"], "rule", rule=rec["rule"])
    elif rec["status"] == "null":
        out["fields"]["recommendation"] = _null(rec["null_reason"], "rule", rule=rec["rule"])
    elif backend is not None and "recommendation" in thetas:
        p = pointer.recommendation(backend, doc["pages"], doc.get("lang") or "de", thetas["recommendation"])
        out["fields"]["recommendation"] = (
            _null("not_in_document", "apertus", margin=p.margin, theta=p.theta, model_build=p.model_build)
            if p.value is None
            else _value(p.value, None, None, "apertus", margin=p.margin, theta=p.theta, model_build=p.model_build)
        )
    else:
        out["fields"]["recommendation"] = _null("present_unanchored", "rule", rule=rec["rule"], residue=True)
    if backend is not None and "related_affair" in thetas and doc.get("body"):
        p = pointer.related_affair(
            backend, doc["pages"], doc.get("lang") or "de", doc["body"], doc.get("affair_number"), thetas["related_affair"]
        )
        out["fields"]["related_affair"] = (
            _null("not_in_document", "apertus", margin=p.margin, theta=p.theta)
            if p.value is None
            else _value(p.value, None, p.span, "apertus", margin=p.margin, theta=p.theta, model_build=p.model_build)
        )
    return out


def to_schema(rec: dict):
    """Single adapter to the Pydantic model; imported lazily so the converter runs without the schema package."""
    try:
        from ..schema import schema_v0_1 as s  # noqa: F401
    except Exception:  # schema workstream not merged yet
        return rec
    if hasattr(s, "from_converter"):
        return s.from_converter(rec)
    return rec
