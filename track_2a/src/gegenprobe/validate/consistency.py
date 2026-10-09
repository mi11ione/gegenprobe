"""Affair-level consistency checks that a single field cannot see (field-level rules live in the Pydantic validators).

    check_affair(affair) -> list[Issue]     empty list = consistent

Rules
  N1  null_reason=image_only must point at a document with image_only=True (when `doc` is given)
  N2  route ocr+* must point at a document whose extractor is tesseract-*
  N3  a span route must point at a document that is not image_only unless the route is ocr+*
  N4  answer_link_status must agree with the QA pairs: 'attached' needs an answer_doc or answer_text_ref; 'oral' needs every
      answer_date to be a TypedNull(oral); 'absent' must not have an answer_doc
  N5  government_recommendation is not_applicable (value or typed null) for interpellations, questions and question time
  N6  every Apertus-routed value/null in one affair uses a single (model_build, theta) per field family (a field's θ is per build)
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schema.schema_v0_1 import MODEL_ROUTES, Affair, iter_fields

NO_RECOMMENDATION_TYPES = {"interpellation", "question", "question_time"}


@dataclass(frozen=True)
class Issue:
    rule: str
    path: str
    detail: str


def _all_fields(a: Affair):
    yield from iter_fields(a)


def check_affair(a: Affair) -> list[Issue]:
    docs = {d.doc_id: d for d in a.documents}
    out: list[Issue] = []
    builds: dict[str, set] = {}
    for path, v in _all_fields(a):
        d = docs.get(getattr(v, "doc", None) or "")
        if v.kind == "null" and v.null_reason == "image_only" and d is not None and not d.image_only:
            out.append(Issue("N1", path, f"{d.doc_id} is not image_only"))
        if v.route.startswith("ocr+") and d is not None and not (d.extractor or "").startswith("tesseract"):
            out.append(Issue("N2", path, f"{d.doc_id} extractor={d.extractor}"))
        if v.kind == "value" and v.route in ("rule", "apertus") and d is not None and d.image_only:
            out.append(Issue("N3", path, f"{d.doc_id} is image_only but route={v.route}"))
        if v.route in MODEL_ROUTES:
            fam = (
                path.split(".")[0]
                if not path.startswith(("dates", "qa", "actors"))
                else path.split(".")[0] + "." + path.split(".")[-1]
            )
            builds.setdefault(fam, set()).add((v.model_build, v.theta))
    for fam, s in builds.items():
        if len(s) > 1:
            out.append(Issue("N6", fam, f"several (build, theta) pairs: {sorted(s, key=str)}"))
    st = a.answer_link_status
    if st == "attached" and a.qa and not any(q.answer_doc or q.answer_text_ref for q in a.qa):
        out.append(Issue("N4", "answer_link_status", "attached but no QA pair has an answer_doc/answer_text_ref"))
    if st == "oral":
        for i, q in enumerate(a.qa):
            if not (q.answer_date.kind == "null" and q.answer_date.null_reason == "oral"):
                out.append(Issue("N4", f"qa.{i}.answer_date", "link status oral but answer_date is not TypedNull(oral)"))
    if st == "absent":
        for i, q in enumerate(a.qa):
            if q.answer_doc:
                out.append(Issue("N4", f"qa.{i}.answer_doc", "link status absent but an answer_doc is set"))
    gr = a.government_recommendation
    if a.type.harmonised in NO_RECOMMENDATION_TYPES:
        ok = (gr.kind == "value" and gr.value == "not_applicable") or (gr.kind == "null" and gr.null_reason == "not_applicable")
        if not ok:
            out.append(Issue("N5", "government_recommendation", f"type {a.type.harmonised} takes no recommendation"))
    return out
