"""Validator for schema v0.1 instances: schema validation, span re-check, typed-null consistency, behavioural harnesses."""
from __future__ import annotations

from pydantic import ValidationError

from ..schema.schema_v0_1 import Affair
from .consistency import Issue, check_affair
from .dates import find_dates, normalise_date
from .harness import distractor, run_suite, self_deletion
from .report import summarise, to_markdown
from .spans import SpanCheck, recheck, recheck_affair

__all__ = ["validate", "Issue", "check_affair", "find_dates", "normalise_date", "distractor", "run_suite", "self_deletion",
           "summarise", "to_markdown", "SpanCheck", "recheck", "recheck_affair"]


def validate(obj: dict, texts: dict[str, list[str]] | None = None) -> dict:
    """Full validation of one affair JSON object.
    Returns {"schema_ok", "errors", "issues", "spans"}; spans only when `texts` (doc_id -> pages) is given."""
    try:
        a = Affair.model_validate(obj)
    except ValidationError as e:
        return dict(schema_ok=False, errors=[f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()], issues=[],
                    spans=[])
    issues = [i.__dict__ for i in check_affair(a)]
    spans = [dict(path=p, ok=c.ok, code=c.code, detail=c.detail) for p, c in recheck_affair(a, texts)] if texts else []
    return dict(schema_ok=True, errors=[], issues=issues, spans=spans)
