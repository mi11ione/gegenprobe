"""P10 scoring and hypotheses (eval/prereg10/PREREG10.md §5-§6). Model-free; reads arm outputs and the gold, never text.

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.score     -> results/p10/p10_scores.json

Unit: a (name, role) pair of one affair. Gold pairs: the `people` of the merged gold (every role of the P8 guide,
`other` included). An arm's pairs: the actors it prints. A predicted pair matches a gold pair when the names are one
person (`convert.roles.same_person`: equal token sets, or one a subset of the other, accents and titles folded) and
the roles are equal; matching is greedy and one-to-one in printed order (the converter evaluation's rule,
eval/converter_roles.py). Per arm, pooled over affairs: pair precision = matched / predicted, pair recall = matched /
gold, F1; the same without the role (names); affairs whose predicted set equals the gold set. An arm that prints
nothing for an affair loses recall there and no precision.

Hypotheses (on the PRIMARY cell only; one-sided, alpha = 0.05, Holm over the family of four):
  H1  recall(pointer) > recall(rules)                         paired parliament-cluster bootstrap of the difference
  H2  precision(pointer) - precision(rules) > -NI_MARGIN      non-inferiority, paired bootstrap of the difference
  H3a F1(pointer) > max(F1(opd_first), F1(opd_joint))         the stronger OPD mapping in each resample (conservative)
  H3b F1(pointer) > F1(cand_joint)                            paired parliament-cluster bootstrap of the difference
Bootstrap: N_BOOT resamples of parliaments with replacement (seed SEED_BOOT); each resample pools the affairs of the
drawn parliaments; p = (1 + #{resampled statistic <= null value}) / (N_BOOT + 1). Reported with each: the observed
values, Wilson 95% intervals of pooled proportions, the bootstrap 95% interval, and for H1 the exact McNemar test on
gold pairs found by exactly one of the two arms (secondary, not decisive).
"""

from __future__ import annotations

import json
import math
import random
import sys

from gegenprobe.convert import roles as R
from gegenprobe.stats import wilson

ALPHA = 0.05
NI_MARGIN = 0.10  # H2: the pointer's pair precision may be at most 10 points below the rules' (non-inferiority)
MIN_AFFAIRS = 30  # stop rule: fewer scored affairs -> every hypothesis is reported as inconclusive (underpowered)
MIN_GOLD_PAIRS = 60
ARMS = ("pointer", "rules", "opd_first", "opd_joint", "cand_joint")
FAMILY = ("H1", "H2", "H3a", "H3b")


def match(pred: list[tuple[str, str]], gold: list[tuple[str, str]], with_role: bool = True) -> tuple[int, list[int]]:
    """(matches, indices of the gold pairs matched): greedy one-to-one in printed order."""
    used: list[int] = []
    for pn, pr in pred:
        for i, (gn, gr) in enumerate(gold):
            if i in used:
                continue
            if R.same_person(pn, gn) and (not with_role or pr == gr):
                used.append(i)
                break
    return len(used), used


def affair_row(pred: list[tuple[str, str]], gold: list[tuple[str, str]]) -> dict:
    m_role, hit = match(pred, gold)
    m_name, _ = match(pred, gold, with_role=False)
    return dict(n_pred=len(pred), n_gold=len(gold), m_role=m_role, m_name=m_name, gold_hit=hit,
                exact=m_role == len(pred) == len(gold))


def _ratio(k: int, n: int) -> float | None:
    return k / n if n else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None or p + r == 0:
        return 0.0 if (p is not None and r is not None) else None
    return 2 * p * r / (p + r)


def pooled(rows: list[dict], arm: str) -> dict:
    np_ = sum(r["arms"][arm]["n_pred"] for r in rows)
    ng = sum(r["arms"][arm]["n_gold"] for r in rows)
    mr = sum(r["arms"][arm]["m_role"] for r in rows)
    mn = sum(r["arms"][arm]["m_name"] for r in rows)
    p, rc = _ratio(mr, np_), _ratio(mr, ng)
    return dict(pairs_predicted=np_, pairs_gold=ng, matched=mr, precision=p, recall=rc, f1=_f1(p, rc),
                precision_wilson95=list(wilson(mr, np_)) if np_ else None,
                recall_wilson95=list(wilson(mr, ng)) if ng else None,
                names_precision=_ratio(mn, np_), names_recall=_ratio(mn, ng),
                affairs_exact=sum(r["arms"][arm]["exact"] for r in rows), affairs=len(rows),
                affairs_with_output=sum(r["arms"][arm]["n_pred"] > 0 for r in rows))


def stat(rows: list[dict], name: str) -> float | None:
    if name == "H1":
        a, b = pooled(rows, "pointer")["recall"], pooled(rows, "rules")["recall"]
        return None if a is None or b is None else a - b
    if name == "H2":
        a, b = pooled(rows, "pointer")["precision"], pooled(rows, "rules")["precision"]
        if a is None:
            return None
        return a - (b if b is not None else 0.0)  # rules that print nothing: compared with 0
    if name == "H3a":
        a = pooled(rows, "pointer")["f1"]
        bs = [pooled(rows, k)["f1"] for k in ("opd_first", "opd_joint")]
        return None if a is None or any(b is None for b in bs) else a - max(bs)
    if name == "H3b":
        a, b = pooled(rows, "pointer")["f1"], pooled(rows, "cand_joint")["f1"]
        return None if a is None or b is None else a - b
    raise KeyError(name)


NULL = {"H1": 0.0, "H2": -NI_MARGIN, "H3a": 0.0, "H3b": 0.0}


def bootstrap(rows: list[dict], seed: int, n_boot: int) -> dict[str, list[float]]:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["body"], []).append(r)
    bodies = sorted(by)
    rnd = random.Random(seed)
    out: dict[str, list[float]] = {h: [] for h in FAMILY}
    for _ in range(n_boot):
        pick = [rnd.choice(bodies) for _ in bodies]
        rs = [r for b in pick for r in by[b]]
        for h in FAMILY:
            v = stat(rs, h)
            if v is not None:
                out[h].append(v)
    return out


def _pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def mcnemar_exact(b: int, c: int) -> float:
    """One-sided exact McNemar p for b > c (b: found only by the first arm, c: only by the second)."""
    n = b + c
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(b, n + 1)) / 2 ** n


def holm(ps: dict[str, float], alpha: float = ALPHA) -> dict[str, dict]:
    order = sorted(ps, key=lambda h: ps[h])
    out, stop = {}, False
    m = len(order)
    adj_prev = 0.0
    for i, h in enumerate(order):
        adj = min(1.0, max(adj_prev, (m - i) * ps[h]))
        adj_prev = adj
        rej = (not stop) and ps[h] <= alpha / (m - i)
        if not rej:
            stop = True
        out[h] = dict(p=ps[h], p_holm=adj, threshold=alpha / (m - i), rejected=rej)
    return out


def hypotheses(rows: list[dict], seed: int, n_boot: int) -> dict:
    n_pairs = sum(r["arms"]["pointer"]["n_gold"] for r in rows)
    boot = bootstrap(rows, seed, n_boot)
    res, ps = {}, {}
    for h in FAMILY:
        obs = stat(rows, h)
        xs = boot[h]
        p = (1 + sum(x <= NULL[h] for x in xs)) / (len(xs) + 1)
        ps[h] = p
        res[h] = dict(observed=obs, null=NULL[h], boot_ci95=[_pct(xs, 0.025), _pct(xs, 0.975)], p_boot=p,
                      n_boot=len(xs))
    # H1 secondary: exact McNemar on gold pairs found by exactly one of pointer / rules
    b = c = 0
    for r in rows:
        hp, hr = set(r["arms"]["pointer"]["gold_hit"]), set(r["arms"]["rules"]["gold_hit"])
        b += len(hp - hr)
        c += len(hr - hp)
    res["H1"]["mcnemar_secondary"] = dict(pointer_only=b, rules_only=c, p_exact_one_sided=mcnemar_exact(b, c))
    hl = holm(ps)
    under = len(rows) < MIN_AFFAIRS or n_pairs < MIN_GOLD_PAIRS
    for h in FAMILY:
        res[h].update(hl[h])
        res[h]["verdict"] = ("inconclusive (stop rule: underpowered)" if under else
                             ("confirmed" if hl[h]["rejected"] else "not confirmed"))
    return dict(family=list(FAMILY), alpha=ALPHA, correction="Holm", underpowered=under, n_affairs=len(rows),
                n_gold_pairs=n_pairs, tests=res)


def table(rows: list[dict], arms=ARMS) -> dict:
    out = {"all": {a: pooled(rows, a) for a in arms}}
    for key in ("stratum", "body"):
        for v in sorted({r[key] for r in rows}):
            sub = [r for r in rows if r[key] == v]
            out[f"{key}:{v}"] = {a: pooled(sub, a) for a in arms}
    return out


def candidate_recall(rows: list[dict]) -> dict:
    ng = sum(r["cand"]["n_gold"] for r in rows)
    hit = sum(r["cand"]["hit"] for r in rows)
    return dict(gold_names=ng, found=hit, recall=_ratio(hit, ng), wilson95=list(wilson(hit, ng)) if ng else None,
                candidates=sum(r["cand"]["n_cands"] for r in rows),
                pointer_recall_given_candidate=_ratio(sum(r["arms"]["pointer"]["m_role"] for r in rows), hit))


def cand_row(cands: list[dict], gold: list[tuple[str, str]]) -> dict:
    names = list(dict.fromkeys(n for n, _ in gold))
    hit = sum(any(R.same_person(n, c["value"]) for c in cands) for n in names)
    return dict(n_gold=len(names), hit=hit, n_cands=len(cands))


def main() -> dict:
    from eval.p10 import common as C

    rows = [json.loads(x) for x in open(C.ARMS, encoding="utf-8") if x.strip()]
    prim = [r for r in rows if r["cell"] == "primary"]
    sec = [r for r in rows if r["cell"] != "primary"]
    out = dict(status="registered (eval/prereg10/LOCK10)", n_affairs=len(rows), n_primary=len(prim),
               primary=dict(table=table(prim), candidates=candidate_recall(prim),
                            hypotheses=hypotheses(prim, C.SEED_BOOT, C.N_BOOT)),
               secondary_it=dict(note="Lugano (5192): the rules arm is in-sample there (roles-2); outside the family",
                                 table=table(sec) if sec else None, candidates=candidate_recall(sec) if sec else None))
    C.SCORES.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    r = main()
    print(json.dumps({h: {k: r["primary"]["hypotheses"]["tests"][h][k] for k in ("observed", "p_boot", "p_holm", "verdict")}
                      for h in FAMILY}, indent=1))
    sys.exit(0)
