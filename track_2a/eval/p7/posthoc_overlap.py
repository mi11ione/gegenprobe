"""POST HOC (11 Oct 2026; proposed in review; not pre-registered): P7's Apertus promotions next to the no-model exact-date
match on the test frame, recounted from the committed copies only, and checked against results/p7/p7_posthoc_r8.json.
No model call, no network, no text. No registered decision depends on this file.

    PYTHONPATH=src:. .venv/bin/python -m eval.p7.posthoc_overlap   -> results/p7/p7_posthoc_overlap.json

Inputs (all committed): data/p7/test_decisions.jsonl (the 478 test-frame rows with each arm's decision: `p7` = Apertus
promotes, `trivial` = some printed date equals an OPD answer event), data/p7/rule_any_outcomes.jsonl (scope frame: the
first printed date equal to an OPD answer event, `trivial_date`), data/p7/test_key.jsonl and
data/p7/test_annotations/gold.jsonl (the 190 annotated rows and their merged gold), data/p7/date_rule_outcomes.jsonl (the
adapters' date rule on every gold date: the registered `correct_dated`).

Counts per arm on the frame (promoted rows, overlap) and on the annotated rows (is an answer; the written date is one of
the gold answer dates, "date hit"; some gold date passes the adapters' rule, the registered correct_dated), unweighted;
the stratum-weighted precisions are quoted from results/p7/p7_posthoc_r8.json (`ablation.arms`), whose recomputation
from the same copies `python -m eval.p7.offline check` byte-compares.
"""

from __future__ import annotations

import json
import sys

from gegenprobe.paths import DATA, RESULTS

LABEL = ("POST HOC (11 Oct 2026; proposed in review; not pre-registered): counts from committed P7 copies; no registered "
         "decision depends on this file")
P7 = DATA / "p7"
OUT = RESULTS / "p7" / "p7_posthoc_overlap.json"
R8 = RESULTS / "p7" / "p7_posthoc_r8.json"


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def load() -> tuple[list[dict], list[dict]]:
    """(frame rows, annotated rows): decisions joined with the trivial date, the key, the gold and the date rule."""
    dec = _jsonl(P7 / "test_decisions.jsonl")
    tri = {(r["body"], r["affair_id"]): r["trivial_date"] for r in _jsonl(P7 / "rule_any_outcomes.jsonl")
           if r["scope"] == "frame"}
    passes = {(r["body"], r["affair_id"], r["date"]): r["passes"] for r in _jsonl(P7 / "date_rule_outcomes.jsonl")}
    frame = [dict(d, trivial_date=tri[(d["body"], d["affair_id"])]) for d in dec]
    fk = {(f["body"], f["affair_id"]): f for f in frame}
    gold = {g["id"]: g for g in _jsonl(P7 / "test_annotations" / "gold.jsonl")}
    ann = []
    for k in _jsonl(P7 / "test_key.jsonl"):
        f, g = fk[(k["body"], k["affair_id"])], gold[k["id"]]
        yes = g["is_answer"] == "yes"
        ann.append(dict(f, id=k["id"], stratum=k["stratum"], gold=g["is_answer"], gold_dates=g["dates"], correct=yes,
                        correct_dated=yes and any(passes.get((k["body"], k["affair_id"], d)) for d in g["dates"])))
    return frame, ann


def _arm(rows: list[dict], arm: str, date_key: str) -> dict:
    a = [r for r in rows if r[arm]]
    return dict(promoted=len(a), is_answer=sum(r["correct"] for r in a), gold_no=sum(r["gold"] == "no" for r in a),
                date_hit=sum(bool(r[date_key]) and r[date_key] in r["gold_dates"] for r in a if r["correct"]),
                correct_dated=sum(r["correct_dated"] for r in a))


def _subset(rows: list[dict], sel) -> dict:
    s = [r for r in rows if sel(r)]
    return dict(rows=len(s), is_answer=sum(r["correct"] for r in s), correct_dated=sum(r["correct_dated"] for r in s),
                p7_date_hit=sum(bool(r["p7_date"]) and r["p7_date"] in r["gold_dates"] for r in s),
                trivial_date_hit=sum(bool(r["trivial_date"]) and r["trivial_date"] in r["gold_dates"] for r in s))


def main() -> dict:
    frame, ann = load()
    both = lambda r: r["p7"] and r["trivial"]  # noqa: E731
    p7_only = lambda r: r["p7"] and not r["trivial"]  # noqa: E731
    tr_only = lambda r: r["trivial"] and not r["p7"]  # noqa: E731
    out = dict(
        label=LABEL, proposed_by="proposed in review (an external-style review of the submission); counted by the team",
        frame=dict(rows=len(frame), promoted=dict(p7=sum(r["p7"] for r in frame), trivial=sum(r["trivial"] for r in frame)),
                   overlap=dict(both=sum(map(both, frame)), p7_only=sum(map(p7_only, frame)),
                                trivial_only=sum(map(tr_only, frame)),
                                neither=sum(not r["p7"] and not r["trivial"] for r in frame))),
        annotated=dict(rows=len(ann), p7=_arm(ann, "p7", "p7_date"), trivial=_arm(ann, "trivial", "trivial_date"),
                       overlap=dict(both=_subset(ann, both), p7_only=_subset(ann, p7_only),
                                    trivial_only=_subset(ann, tr_only))))
    r8 = json.loads(R8.read_text())
    ab = r8["ablation"]["arms"]
    out["weighted_from_posthoc_r8"] = {a: dict(precision=ab[a]["precision"], precision_dated=ab[a]["precision_dated"],
                                               precision_date_hit=ab[a].get("precision_date_hit"))
                                       for a in ("p7", "trivial")}
    out["weighted_from_posthoc_r8"]["p7_minus_trivial_date_hit"] = r8["ablation"]["differences"]["p7_minus_trivial_date_hit"]
    dh = out["weighted_from_posthoc_r8"]["p7_minus_trivial_date_hit"]
    out["display"] = dict(date_hit_diff_pts=round(100 * dh["estimate"], 1),
                          date_hit_diff_ci_pts=[round(100 * v, 1) for v in dh["ci95"]])
    t = r8["trivial"]
    a7, at = out["annotated"]["p7"], out["annotated"]["trivial"]
    checks = {
        "promoted_in_frame": [out["frame"]["promoted"]["p7"], out["frame"]["promoted"]["trivial"]] == [
            t["promoted_in_frame"]["p7"], t["promoted_in_frame"]["trivial"]],
        "overlap_frame": {k: out["frame"]["overlap"][k] for k in ("both", "p7_only", "trivial_only")} == t["overlap_frame"],
        "overlap_annotated": {k: out["annotated"]["overlap"][k]["rows"] for k in ("both", "p7_only", "trivial_only")}
        == t["overlap_annotated"],
        "trivial_is_answer": [at["is_answer"], at["promoted"]] == t["annotated_is_answer"],
        "p7_is_answer": [a7["is_answer"], a7["promoted"]] == t["p7_annotated_is_answer"],
        "p7_date_hit": [a7["date_hit"], a7["promoted"]] == t["p7_date_hit"],
        "trivial_annotated_block": dict(n=at["promoted"], correct=at["is_answer"], correct_dated=at["correct_dated"],
                                        date_hit=at["date_hit"], gold_no=at["gold_no"]) == ab["trivial"]["annotated"],
        "p7_correct_dated": a7["correct_dated"] == ab["p7"]["annotated"]["correct_dated"],
    }
    out["matches_committed_posthoc_r8"] = checks
    out["all_match"] = all(checks.values())
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    r = main()
    print(json.dumps({k: r[k] for k in ("frame", "annotated", "matches_committed_posthoc_r8", "all_match")}, indent=1))
    sys.exit(0 if r["all_match"] else 1)
