"""POST-HOC trivial baselines (not pre-registered; labelled as such in every output), asked for by the round-2 jury.

dates   P1 held-out and P2: (a) latest printed date in the document; (b) the same, but null for documents OPD types as a
        member's text (dtype 'intervention'); (c) latest printed date only on documents typed as answers; compared
        with the registered arms on exact, value recall, values on gold-null
p3      P3: a constant baseline per field (the most frequent gold value), scored like arm C; P3-H3 recomputed without
        addressed body (a near-constant field: every gold value is 'executive')

  python -m eval.baselines   -> results/eval/baselines_dates.json, results/eval3/baselines_p3.json
"""

from __future__ import annotations

import collections
import json

from eval.gold3.score3 import REC_NULL, SINGLE, gold_value, same
from eval.score import outcome
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import wilson

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
LABEL = "POST-HOC (not pre-registered): trivial baselines asked for by the round-2 jury"


def _score(rows: list[dict]) -> dict:
    c = collections.Counter()
    for r in rows:
        c[outcome(r["pred"], r["gold"], set(r["doc_dates"]), r.get("lenient"), True)] += 1
    n = len(rows)
    nv = sum(r["gold"] is not None for r in rows)
    nn = n - nv
    exact = c["correct"] + c["correct_null"]
    on_null = sum(r["pred"] is not None for r in rows if r["gold"] is None)
    return dict(
        n=n,
        exact=exact,
        exact_ci=list(wilson(exact, n)),
        value_recall=[c["correct"], nv],
        values_on_gold_null=[on_null, nn],
        misattributed=c["misattributed"],
        fabricated=c["fabricated"],
        false_null=c["false_null"],
    )


def dates() -> dict:
    out = dict(label=LABEL)
    for name, res_path, docs_path in (
        ("P1_heldout", RESULTS / "eval" / f"heldout__{BUILD}.json", DATA / "gold" / "heldout_docs.jsonl"),
        ("P2_unseen", RESULTS / "eval2" / f"p2__{BUILD}.json", DATA / "gold2" / "p2_docs.jsonl"),
    ):
        res = json.loads(res_path.read_text())
        dtype = {d["doc_id"]: d["dtype"] for d in map(json.loads, open(docs_path))}
        arms: dict[str, list] = collections.defaultdict(list)
        for r in res["per_doc"]:
            base = dict(gold=r["gold"], lenient=r.get("lenient") or [], doc_dates=r.get("doc_dates") or [])
            latest = max(base["doc_dates"]) if base["doc_dates"] else None
            arms["latest_printed_date"].append(dict(base, pred=latest))
            arms["latest_date_gated_by_doc_type"].append(
                dict(base, pred=None if dtype[r["doc_id"]] == "intervention" else latest)
            )
            arms["latest_date_on_answer_docs_only"].append(dict(base, pred=latest if dtype[r["doc_id"]] == "answer" else None))
            for arm in ("rules", "pointer", "cascade"):
                arms[arm].append(dict(base, pred=r[arm].get("value")))
            nd = (r.get("naive_null") or {}).get("date")
            arms["naive_null"].append(dict(base, pred=None if (nd or "").startswith("unparseable") else nd))
        out[name] = {a: _score(v) for a, v in arms.items()}
        out[name]["always_null"] = _score([dict(x, pred=None) for x in arms["rules"]])
    # registered P1-H3 population (1,000-2,000 estimated tokens), recomputed for the D4 correction
    from gegenprobe.stats import auroc

    docs = {d["doc_id"]: d for d in map(json.loads, open(DATA / "gold" / "heldout_docs.jsonl"))}
    p1 = json.loads((RESULTS / "eval" / f"heldout__{BUILD}.json").read_text())["per_doc"]
    sel = [x for x in p1 if 1000 <= docs[x["doc_id"]]["tokens_est"] <= 2000 and x["pointer"].get("n_cands")]
    pos = [x["pointer"]["margin"] for x in sel if x["gold"] is None]
    neg = [x["pointer"]["margin"] for x in sel if x["gold"] is not None]
    out["P1_H3_length_matched"] = dict(auroc=auroc(pos, neg), n_null=len(pos), n_value=len(neg), tokens=[1000, 2000])
    p = RESULTS / "eval" / "baselines_dates.json"
    p.write_text(json.dumps(out, indent=1))
    return out


def p3() -> dict:
    res = json.loads((RESULTS / "eval3" / f"p3__{BUILD}.json").read_text())
    gold = {g["affair_id"]: g for g in map(json.loads, open(DATA / "gold3" / "p3_labels.jsonl"))}
    rows = [p for p in res["per_affair"] if p["affair_id"] in gold]
    out = dict(label=LABEL, fields={})
    for f in SINGLE:
        vals = [gold_value(f, gold[p["affair_id"]]) for p in rows]
        present = [v for v in vals if v is not None]
        if not present:
            continue
        const = collections.Counter(present).most_common(1)[0][0]
        k = sum(same(f, const, gv, gold[p["affair_id"]].get(f + "_lenient") or ()) for p, gv in zip(rows, vals) if gv is not None)
        c_arm = res["scores"]["fields"][f]["C"]
        ca_arm = res["scores"]["fields"][f]["CA"]
        out["fields"][f] = dict(
            constant=const,
            constant_correct=[k, len(present)],
            n_distinct_gold=len(set(map(str, present))),
            C=[c_arm.get("correct", 0), c_arm["n"]],
            CA=[ca_arm.get("correct", 0), ca_arm["n"]],
        )
    # P3-H3 recomputed without addressed body (same definition as eval/gold3/hypotheses3.py)
    h3 = json.loads((RESULTS / "eval3" / f"hypotheses3__{BUILD}.json").read_text())["H3"]["per_field"]
    rk = sum(v["recall"][0] for f, v in h3.items() if f != "addressed_body")
    rn = sum(v["recall"][1] for f, v in h3.items() if f != "addressed_body")
    pk = sum(v["precision"][0] for f, v in h3.items() if f != "addressed_body")
    pn = sum(v["precision"][1] for f, v in h3.items() if f != "addressed_body")
    out["H3_without_addressed_body"] = dict(
        recall=[rk, rn], recall_ci=list(wilson(rk, rn)), precision=[pk, pn], precision_ci=list(wilson(pk, pn))
    )
    p = RESULTS / "eval3" / "baselines_p3.json"
    p.write_text(json.dumps(out, indent=1))
    return out


def p3_extra() -> dict:
    """REGISTERED set metrics (PREREG3 'Sets: micro precision / recall', not reported before) and the post-hoc view of the
    arm-C decision-number defect (DEVIATIONS3 D3-1)."""
    r = json.loads((RESULTS / "eval3" / f"p3__{BUILD}.json").read_text())
    out = dict(
        label="REGISTERED set metrics (PREREG3), previously unreported; plus POST-HOC decision-number defect view", sets={}
    )
    for f, arms in r["scores"]["sets"].items():
        out["sets"][f] = {}
        for a, v in arms.items():
            tp, fp, fn = v["tp"], v["fp"], v["fn"]
            out["sets"][f][a] = dict(
                tp=tp,
                fp=fp,
                fn=fn,
                precision=[tp, tp + fp],
                precision_ci=list(wilson(tp, tp + fp)) if tp + fp else None,
                recall=[tp, tp + fn],
                recall_ci=list(wilson(tp, tp + fn)),
            )
    fr = r["scores"]["fields"]["decision_number"]
    out["decision_number_defect"] = dict(
        registered_C=[fr["C"].get("correct", 0), fr["C"]["n"]],
        registered_R=[fr["R"].get("correct", 0), fr["R"]["n"]],
        post_hoc_C_with_rule_number=[fr["R"].get("correct", 0), fr["R"]["n"]],
        label="POST-HOC: arm C loses the decision number when the frozen P1 cascade returns through its metadata branch "
        "(opd_event_date_in_document), which does not carry the rule's `number`; taking the rule's number (as arm R) "
        "gives the post-hoc figure",
    )
    (RESULTS / "eval3" / "p3_extra.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    d, q, _x = dates(), p3(), p3_extra()
    for name in ("P1_heldout", "P2_unseen"):
        for a, s in d[name].items():
            print(
                name,
                f"{a:32s}",
                "exact",
                s["exact"],
                "/",
                s["n"],
                "recall",
                s["value_recall"],
                "on_null",
                s["values_on_gold_null"],
                "mis",
                s["misattributed"],
            )
    for f, v in q["fields"].items():
        print("P3", f, v)
    print("P3-H3 w/o addressed body", q["H3_without_addressed_body"])
    _ = REC_NULL
