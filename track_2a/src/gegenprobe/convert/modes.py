"""Operating modes of the converter, decided by the pre-registered held-out result (Branch B, report §6).

  rules_only (DEFAULT)  OPD metadata + frozen rules. Unattended output; the residue stays a typed null. No model.
                        Held-out: 135/154 exact, values on 2 of 90 answerless documents, 0 fabricated.
  review                as rules_only, plus the Apertus closed-set pointer on the rules' residue. A pointer value is NOT
                        written into the field: it is attached as a `suggestion` with page, span, margin and θ and
                        `needs_review: true`, for OPD's existing manual-review step. Held-out, accepting every suggestion
                        would recover answer dates the rules miss (false nulls 15 -> 4) and add misattributions (values on
                        answerless documents 2 -> 7), which is why a reviewer accepts them, not the pipeline.

Wraps the frozen cascade (convert/cascade.py is pre-registration-locked and unchanged): the unattended field is always
the backend-free cascade result; the suggestion is the backend cascade result when its route is `apertus`.
"""
from __future__ import annotations

from . import cascade

MODES = ("rules_only", "review")
DEFAULT = "rules_only"


def answer_date(doc: dict, mode: str = DEFAULT, backend=None, theta: float | None = None, use_metadata: bool = True) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    rec = cascade.answer_date(doc, None, None, use_metadata=use_metadata)
    rec = dict(rec, mode=mode, needs_review=False)
    if mode == "review" and backend is not None and theta is not None and rec.get("residue"):
        s = cascade.answer_date(doc, backend, theta, use_metadata=use_metadata)
        if s.get("route") == "apertus" and s.get("value") is not None:
            rec["suggestion"] = {k: s.get(k) for k in ("value", "page", "char_start", "char_end", "quote", "margin", "theta",
                                                        "model_build", "prompt_id")}
            rec["needs_review"] = True
    return rec
