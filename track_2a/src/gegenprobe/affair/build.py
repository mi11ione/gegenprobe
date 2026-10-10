"""Run the arms for one affair and assemble a validated schema_v0_1.Affair.

Arms (eval/prereg3):
  M   OPD metadata only
  R   rules on the affair's documents only (no metadata)
  C   default, unattended: metadata first, rules fill what metadata lacks; the answer date follows the frozen P1 cascade
      (OPD's answer-event date only where the answer document prints it, else the rules)
  CA  C plus the Apertus closed-set pointer on the fields C leaves open — review suggestions, scored as if all were accepted
The Affair instance is built from C; pointer suggestions travel next to it (never inside a field), flagged needs_review.
"""

from __future__ import annotations

import datetime as dt

from .. import pdftext
from ..schema import schema_v0_1 as S
from . import extract as X

SCORED = (
    "number",
    "affair_type",
    "submitter",
    "co_signatories",
    "addressed_body",
    "submitted",
    "answer_date",
    "decision_number",
    "recommendation",
    "related_affairs",
)
LEVEL = {"canton": "cantonal", "commune": "communal", "federal": "federal"}


def texts(entry: dict) -> dict[str, tuple[str, list[str], dict]]:
    """role -> (doc_id, pages, doc entry), text from the sha256-verified PDF cache."""
    out = {}
    for d in entry["docs"]:
        t = pdftext.extract(d["sha256"], ocr=bool(d.get("image_only")))
        out[d["role"]] = (f"opd:{d['doc_id']}", t["pages"], d)
    return out


def _flat(rec):
    if isinstance(rec, list):
        return [r["value"] for r in rec if r.get("value") is not None]
    if rec is None:
        return None
    return rec.get("value") if isinstance(rec, dict) else rec


def run_affair(entry: dict, meta: dict, names: list, link_status: str | None, backend=None, theta_answer: float | None = None):
    tx = texts(entry)
    dq, pq, _ = tx.get("question", (None, None, None))
    da, pa, _ = tx.get("answer", (None, None, None))
    mo = X.from_metadata(meta, link_status)
    ans_events = [mo["answer_event"]["value"]] if mo["answer_event"].get("value") else []
    atype = mo["affair_type"].get("value")
    r_doc = X.rule_fields(pq, pa, dq, da, mo, entry["body"], names, atype, [])
    r_cas = X.rule_fields(pq, pa, dq, da, mo, entry["body"], names, atype, ans_events)

    M = {k: _flat(mo.get(k)) for k in SCORED if k in mo}
    M.update(answer_date=_flat(mo["answer_event"]), addressed_body=None, decision_number=None, related_affairs=[])
    R = {k: _flat(r_doc.get(k)) for k in SCORED}
    R["co_signatories"] = []
    C_rec = {}
    for k in SCORED:
        if k in ("answer_date", "decision_number", "related_affairs", "addressed_body"):
            C_rec[k] = r_cas.get(k)
        elif k == "co_signatories":
            C_rec[k] = mo.get("co_signatories", [])
        else:
            mv = mo.get(k)
            C_rec[k] = mv if (isinstance(mv, dict) and mv.get("value") is not None) else r_cas.get(k)
    C = {k: _flat(v) for k, v in C_rec.items()}
    sugg = {}
    if backend is not None:
        open_f = {
            k
            for k in ("submitter", "submitted", "addressed_body", "affair_type", "answer_date", "recommendation")
            if _open(C_rec.get(k))
        }
        sugg = X.pointer_fields(backend, pq, pa, dq, da, entry.get("lang") or "de", names, open_f, theta_answer)
    CA = dict(C, **{k: v["value"] for k, v in sugg.items()})
    affair = assemble(entry, meta, mo, C_rec, tx)
    return dict(
        affair_id=entry["affair_id"],
        arms=dict(M=M, R=R, C=C, CA=CA) if backend is not None else dict(M=M, R=R, C=C),
        suggestions={k: {kk: vv for kk, vv in v.items()} for k, v in sugg.items()},
        needs_review=bool(sugg),
        affair=affair.model_dump(mode="json", exclude_none=True),
    )


def _open(rec) -> bool:
    """A field is open for the pointer when nothing filled it and no rule closed it (not_applicable, oral, …)."""
    if rec is None:
        return True
    if rec.get("value") is not None:
        return False
    if "residue" in rec:  # answer date: exactly the frozen P1 cascade's residue
        return rec["residue"]
    return rec.get("null_reason") in ("present_unanchored", "not_in_document", "not_in_corpus")


# ------------------------------------------------------------------------------------------------ schema assembly
_VALUED_KEYS = (
    "value",
    "role",
    "basis",
    "route",
    "doc",
    "page",
    "char_start",
    "char_end",
    "quote",
    "source",
    "model_build",
    "theta",
    "margin",
    "candidates",
    "rule",
)


def _v(cls, rec: dict | None, role: str | None = None, missing: tuple = ("present_unanchored", "rule", "not extracted")):
    if rec is None or rec.get("value") is None:
        if rec is None:
            reason, route, ev = missing
            return S.TypedNull(null_reason=reason, route=route, evidence=ev, role=role)
        kw = {k: rec.get(k) for k in ("doc", "model_build", "theta", "margin") if rec.get(k) is not None}  # drops `residue`
        return S.TypedNull(null_reason=rec["null_reason"], route=rec["route"], evidence=rec["evidence"], role=role, **kw)
    kw = {k: rec.get(k) for k in _VALUED_KEYS if rec.get(k) is not None}
    if role:
        kw["role"] = role
    return cls(**kw)


def assemble(entry: dict, meta: dict, mo: dict, C: dict, tx: dict) -> S.Affair:
    a = meta["affair"]
    docs = [
        S.Document(
            doc_id=doc_id,
            source="opd",
            url=d["url"],
            role="question" if role == "question" else "answer",
            language=entry.get("lang"),
            n_pages=len(pages),
            extractor=d.get("extractor"),
            image_only=bool(d.get("image_only")),
        )
        for role, (doc_id, pages, d) in tx.items()
    ]
    ids = {d.doc_id for d in docs}

    def keep(rec):  # a field may only point at documents of this affair
        if isinstance(rec, dict) and rec.get("doc") and rec["doc"] not in ids:
            return None
        return rec

    actors = []
    if C.get("submitter") is not None:
        actors.append(S.Actor(role="submitter", kind="person", name=_v(S.TextValue, keep(C["submitter"]))))
    for c in C.get("co_signatories") or []:
        actors.append(S.Actor(role="co_signatory", kind="person", name=_v(S.TextValue, c)))
    ab = keep(C.get("addressed_body"))
    if ab and ab.get("value"):
        kind = {"executive": "executive", "parliament": "parliament", "committee": "committee"}.get(ab["value"], "other")
        actors.append(S.Actor(role="addressed_body", kind=kind, name=_v(S.TextValue, dict(ab, value=ab["quote"]))))
    dates = [S.DatedEvent(role="submitted", date=_v(S.DateValue, keep(C.get("submitted"))))]
    if mo["answer_event"].get("value"):
        dates.append(S.DatedEvent(role="answered", date=_v(S.DateValue, mo["answer_event"]), label="OPD answer event"))
    ad = keep(C.get("answer_date"))
    ans_val = _v(S.DateValue, ad, missing=("not_in_corpus", "metadata", "no answer document"))
    if isinstance(ans_val, S.DateValue) and C.get("decision_number"):
        ans_val.decision_number = C["decision_number"]
    qa = [
        S.QAPair(
            question_doc=tx["question"][0] if "question" in tx else None,
            answer_doc=tx["answer"][0] if "answer" in tx else None,
            link_status=mo["answer_link_status"],
            answering_body=S.TypedNull(null_reason="present_unanchored", route="rule", evidence="not extracted in P3"),
            answer_date=ans_val,
            answer_identifier=S.TypedNull(
                null_reason="present_unanchored", route="rule", evidence="decision number carried on answer_date.decision_number"
            ),
        )
    ]
    related = [
        S.RelatedAffair(
            relation="cites", ref=S.AffairRef(body_key=entry["body"], number=r["value"]), evidence=_v(S.TextValue, keep(r))
        )
        for r in C.get("related_affairs") or []
        if keep(r)
    ]
    t = mo["affair_type"]
    atype = S.AffairTypeV(harmonised=t["value"] if t.get("value") else "unknown", source_label=t.get("source_label"))
    return S.Affair(
        ref=S.AffairRef(body_key=entry["body"], number=a.get("number"), opd_id=a["id"]),
        body=S.Body(
            key=entry["body"],
            level=LEVEL.get(entry.get("level"), "cantonal"),
            languages=[entry["lang"]] if entry.get("lang") in ("de", "fr", "it") else [],
        ),
        type=atype,
        title={k: v for k, v in mo["title"].items()},
        languages=[entry["lang"]] if entry.get("lang") in ("de", "fr", "it") else [],
        actors=actors,
        dates=dates,
        procedural_state=_v(S.ProceduralStateValue, mo["procedural_state"]),
        decision=_v(S.DecisionValue, mo["decision"]),
        government_recommendation=_v(
            S.GovRecommendationValue, keep(C.get("recommendation")), missing=("not_in_corpus", "metadata", "no answer document")
        ),
        qa=qa,
        answer_link_status=mo["answer_link_status"],
        related_affairs=related,
        documents=docs,
        extraction=S.ExtractionRun(converter_version="gegenprobe-0.1.0+affair", created=dt.datetime.now(dt.timezone.utc)),
    )
