"""Display-ready numbers for the precision pass, derived only from committed files, so claims.tsv can trace them:

  * P7's registered H1 interval in percent (results/p7/p7_hypotheses.json);
  * P8's chance of a false split (PREREG9 §7 operating characteristics, recomputed): if a fraction q of gold labels were
    wrong at random, a parliament with n = 6 determinable affairs deviates when more than one falls outside E
    (binomial), and a field with 11 such parliaments shows at least one deviating parliament with probability
    1 - (1 - p)^11; this is before the registered "systematic" condition (two affairs in the same named category),
    which lowers it further;
  * P8 on Qwen's labels (results/p8/p8_posthoc.json): how many parliaments deviate per field, next to the gold's;
  * fetching outside OPD (results/report/cost_end_to_end.json): 2.1 s per document for all 902,754 documents;
  * the nightly review load, an estimate: new answers per night = interventions whose OPD answer event falls in 2025
    (results/census/interventions.tsv.gz) / 365, and in 2025's busiest month / its days; times the held-out residue
    share (97/154) times the 8B's 179.6 s per document on 4 vCPUs (and USD 0.59 per 1,000 residue documents on the 70B).

    PYTHONPATH=src:. python -m report.r10_numbers   -> results/report/r10_numbers.json
"""
from __future__ import annotations

import calendar
import collections
import csv
import gzip
import json
import math

from gegenprobe.paths import RESULTS

OUT = RESULTS / "report" / "r10_numbers.json"
RESIDUE = (97, 154)  # held-out residue share (docs/runbook.md "Cost per 1,000 residue documents")
N_PARL, N_AFF = 11, 6
NAMES = {"VS": "Valais", "VD": "Vaud", "GR": "Graubünden", "FR": "Fribourg", "TG": "Thurgau", "351": "Bern city",
         "261": "Zürich city", "5586": "Lausanne", "6643": "Vernier", "5192": "Lugano", "5002": "Bellinzona"}


def p_deviate(q: float, n: int = N_AFF) -> float:
    """P(more than max(1, floor(0.1 n)) of n affairs fall outside E by label error alone)."""
    allowed = max(1, math.floor(0.10 * n))
    return 1 - sum(math.comb(n, k) * q ** k * (1 - q) ** (n - k) for k in range(allowed + 1))


def p8() -> dict:
    fs = {}
    for q in (0.02, 0.03, 0.05):
        p = p_deviate(q)
        fs[f"q{int(q * 100)}"] = dict(per_parliament=round(p, 4), per_field=round(1 - (1 - p) ** N_PARL, 4),
                                      per_parliament_pct=round(100 * p, 1),
                                      per_field_pct=round(100 * (1 - (1 - p) ** N_PARL), 1))
    hyp = json.loads((RESULTS / "p8" / "p8_hypotheses.json").read_text())["fields"]
    qw = json.loads((RESULTS / "p8" / "p8_posthoc.json").read_text())["verdicts_on_qwen_labels"]
    dev = {f: dict(gold=len(hyp[f]["deviating"]), qwen=len(qw[f]["deviating"]),
                   gold_names=[NAMES.get(b, b) for b in hyp[f]["deviating"]],
                   qwen_names=[NAMES.get(b, b) for b in qw[f]["deviating"]],
                   verdict_gold=hyp[f]["verdict"], verdict_qwen=qw[f]["verdict"]) for f in hyp}
    fr = hyp["language"]["per_parliament"]["FR"]
    return dict(false_split=fs, assumption=f"{N_PARL} evaluable parliaments with {N_AFF} determinable affairs each; "
                                           "labels wrong at random with probability q; before the systematic condition",
                deviating=dev, language_fribourg=dict(n=fr["n_det"], in_E=fr["n_E"], outside_E=fr["n_det"] - fr["n_E"]))


def ops() -> dict:
    c = json.loads((RESULTS / "report" / "cost_end_to_end.json").read_text())
    fetch_h = c["fetch_extract_check_s_per_doc"] * c["corpus_documents"] / 3600
    per_month = collections.Counter()
    with gzip.open(RESULTS / "census" / "interventions.tsv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["answer_date"].startswith("2025-"):
                per_month[r["answer_date"][:7]] += 1
    year = sum(per_month.values())
    busiest, n_busy = max(sorted(per_month.items()), key=lambda kv: kv[1])
    days = calendar.monthrange(2025, int(busiest[5:]))[1]
    share = RESIDUE[0] / RESIDUE[1]
    s8 = c["review_8b_wall_s_per_doc"]

    def night(per_day: float) -> dict:
        res = per_day * share
        return dict(answers_per_night=round(per_day, 1), residue_docs=round(res, 1),
                    h_8b=round(res * s8 / 3600, 2), min_8b=round(res * s8 / 60),
                    usd_70b=round(res * c["review_70b_usd_per_1000_residue_docs"] / 1000, 4))
    return dict(fetch_hours_outside_opd=round(fetch_h), fetch_s_per_doc=c["fetch_extract_check_s_per_doc"],
                corpus_documents=c["corpus_documents"], answers_2025=year, busiest_month=busiest,
                busiest_month_answers=n_busy, residue_share=round(share, 2),
                nightly_mean=night(year / 365), nightly_busiest=night(n_busy / days),
                label="estimate: OPD answer events per calendar day (2025) x held-out residue share x measured 8B time; "
                      "not measured on a real night")


def main() -> dict:
    h1 = json.loads((RESULTS / "p7" / "p7_hypotheses.json").read_text())["H1"]
    res = dict(note="derived from committed files only (report/r10_numbers.py); see the module docstring",
               p7=dict(h1_wilson_pct=[round(100 * v, 1) for v in h1["wilson95"]]), p8=p8(), ops=ops())
    OUT.write_text(json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
