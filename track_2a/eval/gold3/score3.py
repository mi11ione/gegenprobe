"""P3 per-field scoring (eval/prereg3). Gold = what the affair's documents print (eval/gold3/GUIDE.md).

Single-valued fields, per arm:
  correct        gold has a value and the prediction matches it (normalised; dates: ISO or a lenient alternative)
  missed         gold has a value, prediction null
  wrong          gold has a value, prediction differs
  null_ok        gold null, prediction null
  unprinted      gold null, prediction has a value. For metadata-route values this is not an error by itself (OPD may know
                 what the documents do not print); it is reported separately and never counted as correct.
  value accuracy = correct / (correct + missed + wrong)  — on affairs whose documents print the field (Wilson 95% CI)
Set-valued fields (co_signatories, related_affairs): micro precision / recall over normalised items.
Names match on surname plus the first-name initial when both sides carry a first name.
"""

from __future__ import annotations

import collections
import re
import unicodedata

from gegenprobe.stats import wilson

SINGLE = ("number", "affair_type", "submitter", "addressed_body", "submitted", "answer_date", "decision_number", "recommendation")
SETS = ("co_signatories", "related_affairs")
REC_NULL = {None, "none", "not_applicable"}


def fold(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)).lower().strip()


def norm_num(s) -> str:
    return re.sub(r"[\s_.\-/]+", "", fold(s))


def name_key(s) -> tuple[str, str]:
    toks = [t for t in re.split(r"[\s,]+", fold(s)) if t]
    if not toks:
        return ("", "")
    return (toks[-1], toks[0][0] if len(toks) > 1 else "")


def same(field: str, pred, gold, lenient=()) -> bool:
    if field == "submitter":
        p, g = name_key(pred), name_key(gold)
        return p[0] == g[0] and (not p[1] or not g[1] or p[1] == g[1])
    if field in ("number", "decision_number"):
        return norm_num(pred) == norm_num(gold)
    if field in ("submitted", "answer_date"):
        return str(pred)[:10] == str(gold)[:10] or str(pred)[:10] in {str(x)[:10] for x in lenient or ()}
    return fold(pred) == fold(gold)


def gold_value(field: str, g: dict):
    v = g.get(field)
    if field == "recommendation" and v in REC_NULL:
        return None
    return v


def score_all(per_affair: list[dict], gold: dict[int, dict], entries: dict[int, dict]) -> dict:
    arms = sorted({a for p in per_affair for a in p["arms"]})
    fields, sets_ = {}, {}
    for f in SINGLE:
        fields[f] = {}
        for arm in arms:
            c = collections.Counter()
            for p in per_affair:
                g = gold.get(p["affair_id"])
                if g is None:
                    continue
                gv, pv = gold_value(f, g), p["arms"][arm].get(f)
                if f == "recommendation" and pv in REC_NULL:
                    pv = None
                if gv is None:
                    c["null_ok" if pv is None else "unprinted"] += 1
                elif pv is None:
                    c["missed"] += 1
                else:
                    c["correct" if same(f, pv, gv, g.get(f + "_lenient") or ()) else "wrong"] += 1
            n = c["correct"] + c["missed"] + c["wrong"]
            fields[f][arm] = dict(c, n=n, accuracy=c["correct"] / n if n else None, accuracy_ci=list(wilson(c["correct"], n)))
    for f in SETS:
        sets_[f] = {}
        for arm in arms:
            tp = fp = fn = 0
            for p in per_affair:
                g = gold.get(p["affair_id"])
                if g is None:
                    continue
                key = name_key if f == "co_signatories" else norm_num
                gs = {key(x) if f != "co_signatories" else name_key(x)[0] for x in g.get(f) or []}
                ps = {key(x) if f != "co_signatories" else name_key(x)[0] for x in p["arms"][arm].get(f) or []}
                tp += len(gs & ps)
                fp += len(ps - gs)
                fn += len(gs - ps)
            sets_[f][arm] = dict(
                tp=tp, fp=fp, fn=fn, precision=tp / (tp + fp) if tp + fp else None, recall=tp / (tp + fn) if tp + fn else None
            )
    # seen vs unseen parliaments (by the rules), per field, arm C and CA
    split = {}
    for seen in (True, False):
        sub = [p for p in per_affair if entries[p["affair_id"]]["seen_by_rules"] == seen]
        split["seen" if seen else "unseen"] = {f: {arm: _acc(sub, gold, f, arm) for arm in arms} for f in SINGLE}
    return dict(arms=arms, fields=fields, sets=sets_, by_rules_coverage=split, n_gold=len(gold))


def _acc(sub, gold, f, arm):
    k = n = 0
    for p in sub:
        g = gold.get(p["affair_id"])
        gv = gold_value(f, g) if g else None
        if gv is None:
            continue
        n += 1
        pv = p["arms"][arm].get(f)
        if f == "recommendation" and pv in REC_NULL:
            pv = None
        k += pv is not None and same(f, pv, gv, g.get(f + "_lenient") or ())
    return dict(correct=k, n=n)
