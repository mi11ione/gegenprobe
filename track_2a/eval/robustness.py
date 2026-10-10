"""POST-HOC robustness of the frozen held-out result (not pre-registered; labelled as such in every output).
Reads only committed files: results/eval/heldout__<build>.json (per-document rows), data/gold/heldout_docs.jsonl,
data/gold/heldout_labels.jsonl and the raw blind annotations data/gold/annotations/{A1,A2,A3}.jsonl.

  agreement    recompute κ / raw agreement / A3 count from the raw annotations (must equal results/eval/gold_agreement.json)
               + how much of the recommendation disagreement is the none <-> not_applicable boundary
  robustness   always-null baseline, value recall, precision of Apertus-decided values, paired difference cascade - rules
               with a Newcombe (method 10) 95% CI and the minimum detectable effect, H1/H3 per document type, a
               document-type baseline, H3 without the OCR cell, sensitivity to contested labels

    python -m eval.robustness [agreement|robustness|all]
Writes results/eval/robustness_agreement.json and results/eval/robustness.json.
"""

from __future__ import annotations

import collections
import json
import math
import sys
from statistics import NormalDist

from eval.score import outcome
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import auroc, cohen_kappa, wilson

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
ANN = DATA / "gold" / "annotations"
OUT = RESULTS / "eval"
FR_IT_OCR = ("fr_canton", "fr_commune", "it_canton", "it_commune", "ocr_ti")
CONTESTED_OWN_BUSINESS = (28271, 862297, 300277)  # executive's own business, not an answer to a member affair (U3, A1 vs A2)
ARMS = ("rules", "pointer", "cascade", "naive_plain", "naive_null")
LABEL = "POST-HOC (not pre-registered): robustness of the frozen held-out result"


def _jsonl(p):
    return [json.loads(x) for x in open(p, encoding="utf-8")]


def load_ann() -> dict[str, dict[int, dict]]:
    return {a: {r["doc_id"]: r for r in _jsonl(ANN / f"{a}.jsonl")} for a in ("A1", "A2", "A3")}


# ---------------------------------------------------------------- agreement (reproduces eval/gold/annotate.merge)
def agreement() -> dict:
    A = load_ann()
    a1, a2, a3 = A["A1"], A["A2"], A["A3"]
    ids = sorted(set(a1) & set(a2))
    out = {}
    for f in ("answer_present", "answer_date", "recommendation"):
        x, y = [str(a1[i][f]) for i in ids], [str(a2[i][f]) for i in ids]
        out[f] = dict(raw=sum(p == q for p, q in zip(x, y)), n=len(ids), kappa=cohen_kappa(x, y))
    disagree = [
        i for i in ids if (a1[i]["answer_date"], a1[i]["recommendation"]) != (a2[i]["answer_date"], a2[i]["recommendation"])
    ]
    rec_dis = [i for i in ids if a1[i]["recommendation"] != a2[i]["recommendation"]]
    boundary = [i for i in rec_dis if {a1[i]["recommendation"], a2[i]["recommendation"]} == {"none", "not_applicable"}]
    date_dis = [i for i in ids if a1[i]["answer_date"] != a2[i]["answer_date"]]
    ref = json.loads((OUT / "gold_agreement.json").read_text())
    same = all(
        abs(out[f]["kappa"] - ref["agreement"][f]["kappa"]) < 1e-12 and out[f]["raw"] == ref["agreement"][f]["raw"] for f in out
    ) and len(disagree) == ref["decided_by_A3"] == len(a3)
    res = dict(
        source="data/gold/annotations/{A1,A2,A3}.jsonl (raw blind annotations; quotes <= 200 chars, notes are annotator text)",
        agreement=out,
        n_disagreements_sent_to_A3=len(disagree),
        n_A3_labels=len(a3),
        reproduces_gold_agreement_json=same,
        recommendation_disagreements=len(rec_dis),
        recommendation_disagreements_none_vs_not_applicable=len(boundary),
        recommendation_boundary_share=len(boundary) / len(rec_dis) if rec_dis else None,
        answer_date_disagreements=len(date_dis),
        answer_date_disagreement_ids=date_dis,
        a3_picked_label_of_A1=sum(
            a3[i]["answer_date"] == a1[i]["answer_date"] and a3[i]["recommendation"] == a1[i]["recommendation"] for i in a3
        ),
        a3_picked_label_of_A2=sum(
            a3[i]["answer_date"] == a2[i]["answer_date"] and a3[i]["recommendation"] == a2[i]["recommendation"] for i in a3
        ),
        note="A3 saw both labels as X (=A1) and Y (=A2) in a fixed order; the order was not randomised (DEVIATIONS D4).",
    )
    (OUT / "robustness_agreement.json").write_text(json.dumps(res, indent=1))
    return res


# ---------------------------------------------------------------- statistics helpers
def pred(r: dict, arm: str):
    if arm.startswith("naive"):
        v = r[arm].get("date")
        return None if (v is None or str(v).startswith("unparseable")) else v
    return r[arm].get("value")


def oc(r: dict, arm: str, strict: bool = True) -> str:
    return outcome(pred(r, arm), r["gold"], set(r["doc_dates"]), r.get("lenient"), strict)


def correct(r: dict, arm: str) -> bool:
    return oc(r, arm) in ("correct", "correct_null")


def newcombe_paired(a: int, b: int, c: int, d: int, z: float = 1.959964) -> tuple[float, float, float]:
    """Difference p1 - p2 of paired proportions (p1 = (a+b)/n, p2 = (a+c)/n) with Newcombe's (1998) method 10 CI
    (Wilson score intervals for the margins combined with a continuity-corrected phi)."""
    n = a + b + c + d
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n, z)
    l2, u2 = wilson(a + c, n, z)
    den = math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    if den == 0:
        phi = 0.0
    else:
        num = a * d - b * c
        num = max(num - n / 2, 0) if num > 0 else num
        phi = num / den
    delta = p1 - p2
    lo = delta - math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    hi = delta + math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return delta, lo, hi


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def mde_paired(n: int, discordant_share: float, alpha: float = 0.05, power: float = 0.80) -> float | None:
    """Smallest true difference in correct-rate (as a fraction of all n documents) detectable by a two-sided McNemar test
    at the given discordance rate (Connor 1987 normal approximation: n = (z_a sqrt(pd) + z_b sqrt(pd - d^2))^2 / d^2)."""
    za, zb = NormalDist().inv_cdf(1 - alpha / 2), NormalDist().inv_cdf(power)
    pd = discordant_share
    if pd <= 0:
        return None
    for k in range(1, 10001):
        dlt = k / 10000
        if dlt * dlt >= pd:
            return None
        if (za * math.sqrt(pd) + zb * math.sqrt(pd - dlt * dlt)) ** 2 / (dlt * dlt) <= n:
            return dlt
    return None


def paired(rows: list[dict], arm1: str = "cascade", arm2: str = "rules") -> dict:
    a = b = c = d = 0
    for r in rows:
        x, y = correct(r, arm1), correct(r, arm2)
        a += x and y
        b += x and not y
        c += y and not x
        d += not x and not y
    n = len(rows)
    delta, lo, hi = newcombe_paired(a, b, c, d)
    return dict(
        n=n,
        both=a,
        only_first=b,
        only_second=c,
        neither=d,
        arms=[arm1, arm2],
        difference=delta,
        ci95=[lo, hi],
        p_mcnemar_exact=mcnemar_exact(b, c),
        discordant=b + c,
        mde_80pct_power=mde_paired(n, (b + c) / n) if n else None,
        note="difference = correct-rate(first) - correct-rate(second) over all n documents",
    )


def summarise_arm(rows: list[dict], arm: str) -> dict:
    c = collections.Counter(oc(r, arm) for r in rows)
    nulls = [r for r in rows if r["gold"] is None]
    vals = [r for r in rows if r["gold"] is not None]
    inv = sum(pred(r, arm) is not None for r in nulls)
    rec = sum(oc(r, arm) == "correct" for r in vals)
    return dict(
        n=len(rows),
        exact=c["correct"] + c["correct_null"],
        exact_ci=list(wilson(c["correct"] + c["correct_null"], len(rows))),
        n_gold_null=len(nulls),
        invented_on_null=inv,
        n_gold_value=len(vals),
        value_recall=rec,
        value_recall_ci=list(wilson(rec, len(vals))) if vals else None,
        misattributed=c["misattributed"],
        fabricated=c["fabricated"],
        false_null=c["false_null"],
    )


def robustness() -> dict:
    res = json.loads((OUT / f"heldout__{BUILD}.json").read_text())
    rows = res["per_doc"]
    docs = {d["doc_id"]: d for d in _jsonl(DATA / "gold" / "heldout_docs.jsonl")}
    labels = {d["doc_id"]: d for d in _jsonl(DATA / "gold" / "heldout_labels.jsonl")}
    for r in rows:
        r["dtype"] = docs[r["doc_id"]]["dtype"]
        r["labeller"] = labels[r["doc_id"]]["labeller"]
    n = len(rows)
    n_null = sum(r["gold"] is None for r in rows)
    out: dict = dict(label=LABEL, build=BUILD, theta=res["theta"], n=n)

    # baselines and recall / precision
    out["always_null_baseline"] = dict(
        exact=n_null, n=n, rate=n_null / n, ci95=list(wilson(n_null, n)), note="predict null for every document"
    )
    out["arms"] = {a: summarise_arm(rows, a) for a in ARMS}
    ap = [r for r in rows if r["cascade"].get("route") == "apertus" and r["cascade"].get("value") is not None]
    ap_ok = sum(oc(r, "cascade") == "correct" for r in ap)
    out["apertus_decided_values"] = dict(
        n=len(ap),
        correct=ap_ok,
        precision=ap_ok / len(ap) if ap else None,
        ci95=list(wilson(ap_ok, len(ap))),
        on_gold_null=sum(r["gold"] is None for r in ap),
        wrong_date_on_gold_value=sum(r["gold"] is not None and oc(r, "cascade") != "correct" for r in ap),
        note="cascade values whose route is apertus (review suggestions in the shipped review mode)",
    )
    rule_vals = [r for r in rows if r["cascade"].get("route") == "rule" and r["cascade"].get("value") is not None]
    rv_ok = sum(oc(r, "cascade") == "correct" for r in rule_vals)
    out["rule_decided_values"] = dict(
        n=len(rule_vals),
        correct=rv_ok,
        precision=rv_ok / len(rule_vals) if rule_vals else None,
        ci95=list(wilson(rv_ok, len(rule_vals))),
    )

    # paired difference, primary (FR+IT+OCR) and pooled, plus pointer vs rules
    out["paired"] = dict(
        primary_fr_it_ocr=paired([r for r in rows if r["cell"] in FR_IT_OCR]),
        pooled=paired(rows),
        pointer_vs_rules_pooled=paired(rows, "pointer", "rules"),
        cascade_vs_naive_null_pooled=paired(rows, "cascade", "naive_null"),
    )

    # H1 / H3 per document type
    by_t = collections.defaultdict(list)
    for r in rows:
        by_t[r["dtype"]].append(r)
    per_type = {}
    for t, rs in sorted(by_t.items()):
        nulls = [r for r in rs if r["gold"] is None]
        pos = [r["pointer"]["margin"] for r in rs if r["gold"] is None and r["pointer"].get("n_cands")]
        neg = [r["pointer"]["margin"] for r in rs if r["gold"] is not None and r["pointer"].get("n_cands")]
        per_type[t] = dict(
            n=len(rs),
            n_gold_null=len(nulls),
            n_gold_value=len(rs) - len(nulls),
            values_on_gold_null={a: sum(pred(r, a) is not None for r in nulls) for a in ("rules", "pointer", "cascade")},
            exact={a: sum(correct(r, a) for r in rs) for a in ARMS},
            h3_auroc=auroc(pos, neg) if pos and neg else None,
            h3_n_null=len(pos),
            h3_n_value=len(neg),
        )
    out["per_document_type"] = per_type
    pos = [
        r["pointer"]["margin"] for r in rows if r["gold"] is None and r["pointer"].get("n_cands") and r["dtype"] != "intervention"
    ]
    neg = [
        r["pointer"]["margin"]
        for r in rows
        if r["gold"] is not None and r["pointer"].get("n_cands") and r["dtype"] != "intervention"
    ]
    out["h3_excluding_interventions"] = dict(auroc=auroc(pos, neg), n_null=len(pos), n_value=len(neg))
    pos = [r["pointer"]["margin"] for r in rows if r["gold"] is None and r["pointer"].get("n_cands") and r["cell"] != "ocr_ti"]
    neg = [
        r["pointer"]["margin"] for r in rows if r["gold"] is not None and r["pointer"].get("n_cands") and r["cell"] != "ocr_ti"
    ]
    out["h3_excluding_ocr_cell"] = dict(
        auroc=auroc(pos, neg),
        n_null=len(pos),
        n_value=len(neg),
        note="the OCR cell is not length-matched (data/gold/README.md); PREREG H3 names the length-matched set",
    )
    # document-type baseline: answer presence from the document type alone; and dtype gate + rules
    score = [1.0 if r["dtype"] == "intervention" else 0.0 for r in rows]
    pos = [s for s, r in zip(score, rows) if r["gold"] is None]
    neg = [s for s, r in zip(score, rows) if r["gold"] is not None]
    gate = []
    for r in rows:
        p = None if r["dtype"] == "intervention" else pred(r, "rules")
        gate.append(outcome(p, r["gold"], set(r["doc_dates"]), r.get("lenient"), True) in ("correct", "correct_null"))
    out["document_type_baseline"] = dict(
        definition=(
            "document type from the sampler's frozen classifier of OPD name/category (eval/gold/doctype.py): "
            "'intervention' => no answer in the document"
        ),
        auroc_answerless_vs_answered=auroc(pos, neg),
        gate_plus_rules=dict(
            definition="predict null for interventions, the frozen rules otherwise",
            exact=sum(gate),
            n=n,
            ci95=list(wilson(sum(gate), n)),
        ),
        hard_nulls=sum(r["gold"] is None and r["dtype"] == "answer" for r in rows),
        note="hard null = an answer document with no printed answer date",
    )

    # post-hoc: Apertus suggestions only on answer documents (document type from the frozen sampler classifier), rules elsewhere
    gated = []
    for r in rows:
        arm = "cascade" if r["dtype"] == "answer" else "rules"
        gated.append(dict(r, gated=dict(value=pred(r, arm))))
    out["type_gated_cascade"] = dict(
        definition="cascade (rules + Apertus on the residue) on documents typed 'answer'; frozen rules elsewhere",
        note="POST-HOC hypothesis for the next pre-registration, not a result: the gate was chosen after seeing per-type errors",
        **{
            k: summarise_arm(gated, "gated")[k]
            for k in (
                "n",
                "exact",
                "exact_ci",
                "invented_on_null",
                "n_gold_null",
                "value_recall",
                "n_gold_value",
                "misattributed",
                "fabricated",
            )
        },
    )

    # sensitivity to contested labels
    def sub(rs, name):
        return dict(
            name=name,
            n=len(rs),
            arms={
                a: {
                    k: summarise_arm(rs, a)[k]
                    for k in ("exact", "invented_on_null", "n_gold_null", "value_recall", "n_gold_value")
                }
                for a in ARMS
            },
        )

    agreed = [r for r in rows if r["labeller"] == "claude-agents:A1=A2"]
    out["sensitivity"] = [
        sub(rows, "all 154 documents (frozen headline)"),
        sub(agreed, "A1 = A2 only (the 113 documents with no tie-break; identical to excluding the 41 A3 documents)"),
        sub(
            [r for r in rows if r["doc_id"] not in CONTESTED_OWN_BUSINESS],
            "excluding the 3 contested executive-own-business documents (28271, 862297, 300277)",
        ),
    ]
    p = OUT / "robustness.json"
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("agreement", "all"):
        a = agreement()
        print(
            "agreement reproduces gold_agreement.json:",
            a["reproduces_gold_agreement_json"],
            "| rec boundary",
            a["recommendation_disagreements_none_vs_not_applicable"],
            "/",
            a["recommendation_disagreements"],
        )
    if cmd in ("robustness", "all"):
        r = robustness()
        print(
            json.dumps(
                {
                    k: r[k]
                    for k in (
                        "always_null_baseline",
                        "apertus_decided_values",
                        "h3_excluding_interventions",
                        "h3_excluding_ocr_cell",
                    )
                },
                indent=1,
            )
        )
        print(json.dumps(r["paired"], indent=1)[:2500])
