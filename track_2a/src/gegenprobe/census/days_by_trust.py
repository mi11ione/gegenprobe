"""Answer times split by what OPD's 'answer' date is (date-trust tier) and by intervention type, from the research dataset.

The cross-parliament median in results/census/question.json (`national.median_days`) pools every dated answer: decision
dates (verified tier), weekly-sitting dates, mixed and diffuse (publication-like) dates, same-day artefacts (the 'answer'
event is the submission date) and every intervention type (motions, postulates, question time …). This file shows what
that pooled number is made of, so a sentence about answer times can name its date role and type.

    python -m gegenprobe.census.days_by_trust   -> results/census/answer_days_by_trust.json

Input: results/census/interventions.tsv.gz (`days_to_answer`, census rule; `date_trust`, `type`). Same durations as
question.json (90,556 on the 2026-10-06 snapshot; asserted). Medians shown where n >= 10.
"""

from __future__ import annotations

import collections
import json
import statistics

from . import interventions as iv
from .funnel import OUT

TIERS = ("verified", "sitting_day", "mixed", "diffuse", "same_day", "too_few")
MIN_N = 10
DECISION_LIKE = ("verified", "sitting_day")


def _stat(v: list[int]) -> dict:
    q = statistics.quantiles(v, n=4) if len(v) >= 4 else [None, None, None]
    return dict(n=len(v), median=statistics.median(v), q1=q[0], q3=q[2])


def compute(path=OUT / "interventions.tsv.gz") -> dict:
    rows = iv.load(path)
    by_tier, by_tier_type, by_type = (collections.defaultdict(list) for _ in range(3))
    bodies = collections.defaultdict(set)
    allv = []
    for r in rows:
        bodies[r["date_trust"]].add(r["body"])
        if r["days_to_answer"] == "":
            continue
        d = int(r["days_to_answer"])
        allv.append(d)
        by_tier[r["date_trust"]].append(d)
        by_tier_type[(r["date_trust"], r["type"])].append(d)
        by_type[r["type"]].append(d)
    q = json.loads((OUT / "question.json").read_text())["national"]
    assert len(allv) == q["n_durations"] and statistics.median(allv) == q["median_days"], "differs from question.json"
    not_same = [d for t, v in by_tier.items() if t != "same_day" for d in v]
    dec = [d for t in DECISION_LIKE for d in by_tier.get(t, [])]
    dec_type = collections.defaultdict(list)
    for (t, ty), v in by_tier_type.items():
        if t in DECISION_LIKE:
            dec_type[ty] += v
    tiers = {t: dict(_stat(by_tier[t]), bodies=len(bodies[t]),
                     by_type={ty: _stat(v) for (tt, ty), v in sorted(by_tier_type.items()) if tt == t and len(v) >= MIN_N})
             for t in TIERS if by_tier.get(t)}
    return dict(
        label="Answer times by date-trust tier (what OPD's 'answer' date is) and intervention type; days from submission to "
              "the first written-answer event (census rule), from results/census/interventions.tsv.gz",
        tier_definition="results/census/date_trust.json `definition`: verified = OPD's answer date is the government's "
                        "decision date (Bern: printed RRB date; Ticino: publisher's answer title); sitting_day = >= 80% of "
                        "answer dates on one weekday (a weekly government sitting, i.e. a decision date); mixed 50-80%; "
                        "diffuse < 50% (likely publication or registration dates); same_day = the 'answer' event mostly "
                        "equals the submission date; too_few = < 20 dated answers",
        pooled=dict(_stat(allv), note="question.json national.median_days: pools every date role and type"),
        pooled_excluding_same_day=_stat(not_same),
        decision_like=dict(_stat(dec), tiers=list(DECISION_LIKE), bodies=len(bodies["verified"] | bodies["sitting_day"]),
                           by_type={ty: _stat(v) for ty, v in sorted(dec_type.items()) if len(v) >= MIN_N},
                           note="verified decision dates plus weekly-sitting dates (inferred decision dates, not verified)"),
        tiers=tiers,
        by_type_pooled={ty: _stat(v) for ty, v in sorted(by_type.items()) if len(v) >= MIN_N},
        min_n=MIN_N,
        caveat="Not a ranking and not one quantity: a median over several parliaments mixes procedures and deadlines even "
               "within one tier and one type; compare a parliament with itself over time.",
    )


def main() -> dict:
    r = compute()
    (OUT / "answer_days_by_trust.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    return r


if __name__ == "__main__":
    r = main()
    print("pooled", r["pooled"]["median"], "n", r["pooled"]["n"], "| decision-like", r["decision_like"]["median"],
          "n", r["decision_like"]["n"])
    for t, v in r["tiers"].items():
        print(f"{t:12s} bodies {v['bodies']:3d} n {v['n']:6,d} median {v['median']}")
