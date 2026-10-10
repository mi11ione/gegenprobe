"""Display-ready numbers for P3 (whole affairs, multi-field) and P4 (virtual affairs from meeting documents), derived only
from committed results files, so claims.tsv can trace every number the README, report, form notes and site print.

    python -m report.p34_numbers   -> results/report/p34_numbers.json
"""
from __future__ import annotations

import json

from gegenprobe.paths import DATA, RESULTS

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
FIELDS = ("number", "affair_type", "submitter", "addressed_body", "submitted", "answer_date", "decision_number",
          "recommendation")
ARMS = ("M", "R", "C", "CA")


def frac(k, n) -> str:
    return f"{k}/{n}"


def main() -> dict:
    p3 = json.loads((RESULTS / "eval3" / f"p3__{BUILD}.json").read_text())
    h3 = json.loads((RESULTS / "eval3" / f"hypotheses3__{BUILD}.json").read_text())
    a3 = json.loads((RESULTS / "eval3" / "gold3_agreement.json").read_text())
    aff = [json.loads(x) for x in open(DATA / "gold3" / "p3_affairs.jsonl")]
    out: dict = {}
    bodies_seen = sorted({a["body"] for a in aff if a["seen_by_rules"]})
    bodies_unseen = sorted({a["body"] for a in aff if not a["seen_by_rules"]})
    langs = {}
    for a in aff:
        langs[a["lang"]] = langs.get(a["lang"], 0) + 1
    fields = {}
    for f in FIELDS:
        row = {}
        for arm in ARMS:
            s = p3["scores"]["fields"][f].get(arm)
            if s and s.get("n"):
                row[arm] = frac(s.get("correct", 0), s["n"])
        h = h3["H1"][f]
        row["tier"] = h["tier"]
        row["ci_pct"] = [round(100 * h["ci"][0]), round(100 * h["ci"][1])]
        fields[f] = row
    raw = a3["agreement"]
    out["p3"] = dict(
        n_affairs=len(aff), n_pdfs=sum(len(a["docs"]) for a in aff), n_bodies=len(bodies_seen) + len(bodies_unseen),
        bodies_seen=len(bodies_seen), bodies_unseen=len(bodies_unseen), langs=langs, fields=fields,
        unattended=[f for f in FIELDS if h3["H1"][f]["tier"] == "extractable unattended"],
        partial=[f for f in FIELDS if h3["H1"][f]["tier"] == "partial"],
        h2={f: frac(v["agree"], v["n"]) for f, v in h3["H2"].items()},
        h3=dict(recall=frac(*h3["H3"]["recall"]), precision=frac(*h3["H3"]["precision"]),
                recall_lo_pct=round(100 * h3["H3"]["recall_ci"][0]), precision_lo_pct=round(100 * h3["H3"]["precision_ci"][0]),
                recall_holds=h3["H3"]["recall_holds"], precision_holds=h3["H3"]["precision_holds"], decision=h3["H3"]["decision"],
                addressed_found=frac(*h3["H3"]["per_field"]["addressed_body"]["recall"]),
                answer_found=frac(*h3["H3"]["per_field"]["answer_date"]["recall"])),
        min_raw_agree=min(v["raw"] for v in raw.values()), kappa1_fields=sorted(f for f, v in raw.items() if v["kappa"] == 1.0),
        tie_broken=a3["tie_broken_fields"],
        sets={f: dict(precision=round(v["C"]["precision"], 2) if v["C"]["precision"] is not None else None,
                      recall=round(v["C"]["recall"], 2)) for f, v in p3["scores"]["sets"].items()},
        theta_new=p3["theta_new_fields"],
    )
    sc = json.loads((RESULTS / "eval4" / f"p4_heldout__{BUILD}__score.json").read_text())
    h4 = json.loads((RESULTS / "eval4" / f"hypotheses4__{BUILD}.json").read_text())
    a4 = json.loads((RESULTS / "eval4" / "gold4_agreement.json").read_text())
    r, v = sc["arms"]["rules_only"], sc["arms"]["review"]
    out["p4"] = dict(
        meetings=a4["meetings"], items=sc["n_gold_items"], derived=r["segmentation_precision"][1],
        precision=frac(*r["segmentation_precision"][:2]), recall=frac(*r["segmentation_recall"][:2]),
        recall_pct=round(100 * r["segmentation_recall"][0] / r["segmentation_recall"][1], 1),
        titles=frac(*r["title_correct"][:2]), type_rules=frac(*r["type_accuracy"][:2]), type_review=frac(*v["type_accuracy"][:2]),
        decisions_rules=frac(*r["decision_recall"][:2]), decisions_review=frac(*v["decision_recall"][:2]),
        decision_correct_rules=frac(*r["decision_accuracy"][:2]),
        invented=frac(*r["invented_decisions"][:2]), dates=frac(h4["H4"]["correct"], h4["H4"]["n"]),
        h1=h4["H1"]["holds"], h2=h4["H2"]["holds"], h3=h4["H3"]["holds"], h4=h4["H4"]["holds"],
        h3_review_only=h4["H3"]["review_only"], h3_rules_only=h4["H3"]["rules_only"], h3_p=h4["H3"]["p"],
        kappa_type=round(a4["agreement"]["type"]["kappa"], 2), kappa_decision=round(a4["agreement"]["decision"]["kappa"], 2),
        tie_broken=a4["decided_by_A3"],
    )
    p = RESULTS / "report" / "p34_numbers.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
