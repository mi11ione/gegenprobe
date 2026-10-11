"""P7 post-hoc descriptives (NOT registered; written after the test gold was read): context for H1-H4.

    PYTHONPATH=src:. python -m eval.p7.posthoc8     -> results/p7/p7_posthoc.json

  base_rate        weighted share of gold-yes (and of gold-yes with a gold date passing the date rule) over the test
                   frame: the precision of promoting every eligible review row
  annotated        per arm, the annotated rows it promotes and how many are gold yes / yes-and-dated (unweighted)
  gold_no          every gold-no packet: sampling stratum, review reason, m_yes, p7's decision, free, trivial
  auroc_m_yes      AUROC of the is_answer margin, gold yes vs not yes, over all 190 packets (unweighted)
  p7_date_classes  date classes of the p7 promotions in the sample; p7 rows whose gold dates do not pass the rule
  rest_decisions   why p7 did not promote the rows of the `rest` stratum
  earlier_audits   the whole-queue promotions (results/repair/adapters/p7/promoted.tsv) on review rows that earlier
                   blind audits judged: audit v3's 30 review decoys (Claude auditor) and the design audit's review rows
                   (blind Sonnet); these rows were outside P7 dev and test
"""

from __future__ import annotations

import collections
import csv
import json

from eval.p7 import hypotheses8 as H
from gegenprobe.paths import RESULTS
from gegenprobe.stats import auroc, wilson


def earlier_audits() -> dict:
    ad = RESULTS / "repair" / "adapters"
    prom = {(r["body"], int(r["affair_id"])) for r in csv.DictReader(open(ad / "p7" / "promoted.tsv", encoding="utf-8"),
                                                                       delimiter="\t")}
    review = set()
    for p in sorted(ad.glob("adapters_*.tsv")):
        b = p.stem[len("adapters_"):]
        review |= {(b, int(r["affair_id"])) for r in csv.DictReader(open(p, encoding="utf-8"), delimiter="\t")
                   if r["tier"] == "review"}
    key = [json.loads(x) for x in open(ad / "audit3" / "key.jsonl", encoding="utf-8")]
    ver = {v["id"]: v for v in map(json.loads, open(ad / "audit3" / "verdicts_claude.jsonl", encoding="utf-8"))}
    a3 = collections.Counter(f"{'promoted' if (k['body'], k['affair_id']) in prom else 'not_promoted'}/"
                             f"{ver[k['id']]['is_answer']}" for k in key if k["stratum"] == "decoy/review")
    des = collections.Counter()
    for v in map(json.loads, open(ad / "audit" / "design_audit_verdicts.jsonl", encoding="utf-8")):
        k = (str(v["body"]), int(v["affair_id"]))
        if k in review:
            des[f"{'promoted' if k in prom else 'not_promoted'}/{v['is_answer']}"] += 1
    return dict(audit3_review_decoys_claude=dict(sorted(a3.items())),
                design_audit_review_rows=dict(sorted(des.items())))


def main() -> dict:
    rows, smp = H.load()
    w = sum(r["w"] for r in rows)
    ann = {}
    for arm in ("p7", "free", "trivial"):
        a = [r for r in rows if r[arm]]
        k = sum(r["correct"] for r in a)
        ann[arm] = dict(n=len(a), correct=k, correct_dated=sum(r["correct_dated"] for r in a),
                        wilson95=[round(x, 4) for x in wilson(k, len(a))])
    res = dict(
        note="post hoc, not registered: written after the P7 test gold was read",
        packets=len(rows),
        gold_by_stratum={f"{s}/{g}": n for (s, g), n in sorted(collections.Counter(
            (r["stratum"], r["gold"]) for r in rows).items())},
        base_rate=dict(yes=round(sum(r["w"] for r in rows if r["correct"]) / w, 4),
                       yes_dated=round(sum(r["w"] for r in rows if r["correct_dated"]) / w, 4)),
        annotated=ann,
        gold_no=[dict(id=r["id"], stratum=r["stratum"], reason=r["reason"], m_yes=round(r["m_yes"], 2),
                      p7=r["p7_why"], free=r["free"], trivial=r["trivial"]) for r in rows if not r["correct"]],
        auroc_m_yes=round(auroc([r["m_yes"] for r in rows if r["correct"]],
                                [r["m_yes"] for r in rows if not r["correct"]]), 4),
        p7_date_classes=dict(collections.Counter((r["p7_class"] or "").split("(")[0] for r in rows
                                                 if r["stratum"] == "p7")),
        p7_not_dated=[dict(id=r["id"], reason=r["reason"], date_class=r["p7_class"]) for r in rows
                      if r["stratum"] == "p7" and not r["correct_dated"]],
        rest_decisions=dict(collections.Counter(r["p7_why"] for r in rows if r["stratum"] == "rest")),
    )
    res["earlier_audits"] = earlier_audits()
    (RESULTS / "p7" / "p7_posthoc.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
