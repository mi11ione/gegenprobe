"""Display-ready numbers for the docs pass, derived only from committed files, so claims.tsv can trace them.

  * P10 sample against plan (results/p10/sample.json): primary affairs planned by the registered quotas and scored;
  * P10 concentration (results/p10/p10_scores.json, per parliament; post hoc): the pointer's gain in pairs over the
    rules, how much of it the two parliaments with the largest gains carry, and the primary cell without Neuchâtel
    (the parliament with the most gold pairs) for the pointer and OPD's contributor list (first author + co-signers);
  * the shipped review route (`gegenprobe affair --roles apertus`, src/gegenprobe/convert/roles_review.py; post hoc on
    the committed arms, results/p10/p10_arms.jsonl): the reader alone, and the reader with OPD's contributor list where
    it suggests no author (the opt-in `--roles-fallback opd`), scored with the frozen P10 scorer (eval.p10.score).

No network, no model.

    PYTHONPATH=src:. python -m report.r16_numbers   -> results/report/r16_numbers.json
"""
from __future__ import annotations

import json

from eval.p10.score import affair_row
from gegenprobe.paths import RESULTS

OUT = RESULTS / "report" / "r16_numbers.json"
COV = RESULTS / "convert" / "coverage_by_parliament.json"
DISPLAY = {"NE": "Neuchâtel"}  # the docs name a canton in its own language; the coverage file carries German names


def _j(*parts):
    return json.loads(RESULTS.joinpath(*parts).read_text(encoding="utf-8"))


def _f2(x: float) -> str:
    return f"{x:.2f}"


def p10_sample() -> dict:
    s = _j("p10", "sample.json")
    planned = sum(q[2] for q in s["quotas"] if q[3] == "primary")
    scored = _j("p10", "p10_scores.json")["n_primary"]
    return dict(planned_primary=planned, scored_primary=scored, short=planned - scored)


def p10_concentration() -> dict:
    tab = _j("p10", "p10_scores.json")["primary"]["table"]
    names = {r["body"]: DISPLAY.get(r["body"], r["name"]) for r in json.loads(COV.read_text(encoding="utf-8"))["rows"]}
    per = {k.split(":", 1)[1]: v for k, v in tab.items() if k.startswith("body:")}
    gain = {b: v["pointer"]["matched"] - v["rules"]["matched"] for b, v in per.items()}
    top = sorted(gain, key=lambda b: (-gain[b], b))[:2]
    allp = tab["all"]
    biggest = max(per, key=lambda b: (per[b]["pointer"]["pairs_gold"], b))
    big = per[biggest]
    gold_wo = allp["pointer"]["pairs_gold"] - big["pointer"]["pairs_gold"]
    return dict(
        gain_pairs=allp["pointer"]["matched"] - allp["rules"]["matched"],
        parliaments=len(per),
        top2=[dict(body=b, name=names.get(b, b), pointer=per[b]["pointer"]["matched"], rules=per[b]["rules"]["matched"],
                   gain=gain[b]) for b in top],
        top2_gain=sum(gain[b] for b in top),
        largest=dict(body=biggest, name=names.get(biggest, biggest), gold=big["pointer"]["pairs_gold"],
                     pointer=big["pointer"]["matched"], opd_first=big["opd_first"]["matched"]),
        without_largest=dict(gold=gold_wo, pointer=allp["pointer"]["matched"] - big["pointer"]["matched"],
                             opd_first=allp["opd_first"]["matched"] - big["opd_first"]["matched"]),
    )


def review_route() -> dict:
    rows = [json.loads(x) for x in RESULTS.joinpath("p10", "p10_arms.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()]
    rows = [r for r in rows if r["cell"] == "primary"]

    def pooled(rs):
        m = sum(r["m_role"] for r in rs)
        n = sum(r["n_pred"] for r in rs)
        g = sum(r["n_gold"] for r in rs)
        p, rc = (m / n if n else 0.0), m / g
        return dict(right=m, printed=n, gold=g, precision=_f2(p), recall=_f2(rc),
                    f1=_f2(2 * p * rc / (p + rc) if p + rc else 0.0))

    gold = [[tuple(x) for x in r["gold"]] for r in rows]
    alone = [affair_row([tuple(x) for x in r["pred"]["pointer"]], g) for r, g in zip(rows, gold)]
    fired = [not r["pred"]["pointer"] and bool(r["pred"]["opd_first"]) for r in rows]
    fb = [affair_row([tuple(x) for x in (r["pred"]["opd_first"] if f else r["pred"]["pointer"])], g)
          for r, g, f in zip(rows, gold, fired)]
    added = [b for b, f in zip(fb, fired) if f]
    return dict(affairs=len(rows), reader_alone=pooled(alone), with_opd_fallback=pooled(fb),
                fallback_fired=sum(fired), fallback_pairs_added=sum(b["n_pred"] for b in added),
                fallback_pairs_right=sum(b["m_role"] for b in added))


def main() -> int:
    out = dict(label="display numbers from committed files (report/r16_numbers.py); concentration and the "
                     "review route are post hoc",
               p10=dict(sample=p10_sample(), concentration=p10_concentration(), review_route=review_route()))
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
