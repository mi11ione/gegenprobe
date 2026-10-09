"""`make run` step 5: re-score every committed results/eval/*.json from its per-document rows and assert that the stored
scoreboard is exactly what eval/score.py computes; print a compact scoreboard (arm x cell).

Full check when a per-doc row carries `doc_dates` and `lenient` (misattributed vs fabricated, lenient scoring). Rows without
them (results written before eval/arms.py stored them) are checked on everything that does not need them: n, correct,
correct_null, false_null, invented = misattributed + fabricated, exact, invented_on_null, model_decided (strict only).
Held-out results are the headline; dev results are in-sample and labelled so.

    python -m eval.replay            (also used by gegenprobe.run as step 5)
"""
from __future__ import annotations

import json
import sys

from eval.score import summarise
from gegenprobe.paths import RESULTS

ROUTE = {"rules": "rule", "pointer": "apertus", "naive_plain": "apertus", "naive_null": "apertus"}
REDUCED = ["n", "correct", "correct_null", "false_null", "invented", "exact", "invented_on_null", "model_decided"]
FULL = REDUCED + ["misattributed", "fabricated"]


def _pred(arm: str, rec: dict | None):
    if rec is None:
        return None, None
    if arm == "rules":
        return (rec.get("value") if rec.get("status") == "value" else None), "rule"
    if arm.startswith("naive_"):
        v = rec.get("date")
        return (None if (v or "").startswith("unparseable") else v), "apertus"
    return rec.get("value"), rec.get("route", ROUTE.get(arm, "apertus"))


def rescore(res: dict) -> tuple[dict, list[str], bool]:
    """Return (recomputed arms, mismatches, full) for one results file."""
    full = all("doc_dates" in d and "lenient" in d for d in res["per_doc"])
    keys = FULL if full else REDUCED
    out, bad = {}, []
    for arm, stored in res["arms"].items():
        rows = []
        for d in res["per_doc"]:
            if arm not in d:
                continue
            pred, route = _pred(arm, d[arm])
            rows.append(dict(cell=d["cell"], gold=d["gold"], pred=pred, route=route, lenient=d.get("lenient") or [],
                             doc_dates=d.get("doc_dates") or ([pred] if pred else [])))
        mine = {"strict": summarise(rows, True)}
        if full:
            mine["lenient"] = summarise(rows, False)
        out[arm] = mine
        for mode, cells in mine.items():
            for cell, m in cells.items():
                s = stored[mode].get(cell)
                if s is None:
                    bad.append(f"{arm}/{mode}/{cell}: missing in stored scoreboard")
                    continue
                for k in keys:
                    if m[k] != s[k]:
                        bad.append(f"{arm}/{mode}/{cell}/{k}: stored {s[k]} != recomputed {m[k]}")
    return out, bad, full


def _ci(x) -> str:
    return f"[{100 * x[0]:.0f}, {100 * x[1]:.0f}]"


def board(res: dict) -> list[str]:
    lines = [f"{res['split']} | build {res['build']} | θ {res.get('theta')} | n_docs {res['n_docs']}"]
    lines.append(f"  {'arm':<12} {'cell':<15} {'n':>4} {'exact':>11} {'95% CI':>10} {'invented':>8} {'on null':>8} "
                 f"{'corr null':>9} {'false null':>10}")
    for arm, v in res["arms"].items():
        for cell, s in v["strict"].items():
            lines.append(f"  {arm:<12} {cell:<15} {s['n']:>4} {s['exact']:>5}/{s['n']:<5} {_ci(s['exact_ci']):>10} "
                         f"{s['invented']:>8} {s['invented_on_null']:>4}/{s['n_gold_null']:<3} {s['correct_null']:>9} "
                         f"{s['false_null']:>10}")
    return lines


def main(ctx: dict | None = None) -> dict:
    files = sorted((RESULTS / "eval").glob("*.json"))
    if not files:
        return dict(status="PASS", summary="no evaluation results committed yet")
    bad, report, heldout, partial = [], [], 0, []
    for f in files:
        res = json.loads(f.read_text())
        _, b, full = rescore(res)
        bad += [f"{f.name}: {x}" for x in b]
        if not full:
            partial.append(f.name)
        heldout += res["split"] == "heldout"
        report += board(res)
    print("\n".join(report))
    summary = (f"{len(files)} result files re-scored ({heldout} held-out), {len(bad)} mismatches"
               + (f"; reduced check (no doc_dates/lenient in rows) for {', '.join(partial)}" if partial else "")
               + ("" if heldout else "; no held-out results yet"))
    return dict(status="FAIL" if bad else "PASS", summary=summary, mismatches=bad[:50], scoreboard=report)


if __name__ == "__main__":
    r = main({})
    print(r["status"], r["summary"])
    sys.exit(1 if r["status"] == "FAIL" else 0)
