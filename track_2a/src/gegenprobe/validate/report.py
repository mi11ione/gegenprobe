"""Aggregate validation records into per-field pass/fail counts (JSON for claims, Markdown for the report)."""
from __future__ import annotations

import collections


def summarise(records: list[dict], key: str = "field", test_key: str = "test") -> dict:
    """records: [{field, test, result ∈ pass|fail|skipped, ...}] -> {field: {test: {pass, fail, skipped, n}}}."""
    agg: dict = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in records:
        agg[r[key]][r[test_key]][r["result"]] += 1
    out = {}
    for f, tests in sorted(agg.items()):
        out[f] = {}
        for t, c in sorted(tests.items()):
            out[f][t] = dict(passed=c["pass"], failed=c["fail"], skipped=c["skipped"], n=sum(c.values()))
    return out


def to_markdown(summary: dict) -> str:
    rows = ["| field | test | pass | fail | skipped |", "|---|---|---|---|---|"]
    for f, tests in summary.items():
        for t, c in tests.items():
            rows.append(f"| {f} | {t} | {c['passed']}/{c['passed'] + c['failed']} | {c['failed']} | {c['skipped']} |")
    return "\n".join(rows)


def span_records(affair_id: str, checks) -> list[dict]:
    """Turn spans.recheck_affair output into report records (field = path without list indices)."""
    import re
    out = []
    for path, c in checks:
        if c.code == "no_span":
            res = "skipped"
        else:
            res = "pass" if c.ok else "fail"
        out.append(dict(affair=affair_id, field=re.sub(r"\.\d+\.", ".*.", path), test="span_recheck", result=res, code=c.code))
    return out
