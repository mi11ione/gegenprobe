"""Scoring shared by every arm (rules / pointer / cascade / naive free generation), per cell, with Wilson 95% CIs.

Per value (answer date of one document) against the label:
  correct        prediction equals the gold date (strict) — `lenient` also accepts the labelled alternative dates
  correct_null   null and gold null
  false_null     null although the document carries the date
  misattributed  wrong date that occurs in the document (wrong role: submission, footer, cited law …)
  fabricated     wrong date that occurs nowhere in the document (only free generation can do this)
Headline rates: exact = (correct + correct_null) / n; invented = (misattributed + fabricated) / n;
invented_on_null = wrong values on documents whose gold is null; model_share = values decided by Apertus / all values.
"""

from __future__ import annotations

import collections

from gegenprobe.stats import wilson


def outcome(pred: str | None, gold: str | None, doc_dates: set[str], lenient: list | None = None, strict: bool = True) -> str:
    ok = ({gold} | (set() if strict else set(lenient or []))) if gold else set()
    if pred is None:
        return "correct_null" if gold is None else "false_null"
    if pred in ok:
        return "correct"
    return "misattributed" if pred in doc_dates else "fabricated"


KEYS = ["correct", "correct_null", "false_null", "misattributed", "fabricated"]


def summarise(rows: list[dict], strict: bool = True) -> dict:
    """rows: {cell, pred, gold, lenient, doc_dates, route?}. Returns per-cell and overall counts + rates with CIs."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["cell"]].append(r)
        by["ALL"].append(r)
    out = {}
    for cell, rs in sorted(by.items()):
        c = collections.Counter(outcome(r["pred"], r["gold"], set(r["doc_dates"]), r.get("lenient"), strict) for r in rs)
        n = len(rs)
        exact = c["correct"] + c["correct_null"]
        inv = c["misattributed"] + c["fabricated"]
        nulls = [r for r in rs if r["gold"] is None]
        inv_null = sum(r["pred"] is not None for r in nulls)
        model = sum(r.get("route") == "apertus" for r in rs)
        out[cell] = dict(
            n=n,
            **{k: c[k] for k in KEYS},
            exact=exact,
            exact_rate=exact / n if n else None,
            exact_ci=list(wilson(exact, n)),
            invented=inv,
            invented_ci=list(wilson(inv, n)),
            n_gold_null=len(nulls),
            invented_on_null=inv_null,
            invented_on_null_ci=list(wilson(inv_null, len(nulls))),
            n_gold_value=n - len(nulls),
            model_decided=model,
            model_share=model / n if n else None,
        )
    return out
