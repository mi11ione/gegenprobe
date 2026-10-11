"""Display-ready numbers for the round-14 docs pass, derived only from committed files, so claims.tsv can trace them:

  * the 92.3% split by how its repairs are checked (results/report/r9_numbers.json, r7docs_numbers.json): the share of
    the 91,268 interventions with a recorded government answer that have answer text once the row-checked repairs are
    applied (attached today + the 9,089 repairs checked row by row), and the points the 592 agenda joins (OPD's own
    agenda link, not sample-checked) and the 39 Bern rows in review add;
  * P1's model-free cascade (post hoc): the frozen rules decide where they return a value or a typed null; where they
    abstain, the latest printed date on documents OPD types as answers (null on the member's text), the same definition
    as P6's model-free cascade (eval/posthoc_r6.py). Scored with eval.score.outcome on the committed P1 predictions
    (results/eval/heldout__<build>.json), next to the registered Apertus cascade (rules, then the pointer), with the
    paired discordant counts and an exact two-sided McNemar p;
  * answer times (results/findings/answer_times.json): OPD's plain medians and the answer documents' medians in the two
    parliaments where OPD's "answer" event is mostly the submission date (date trust `same_day`: Kriens, Valais).

    PYTHONPATH=src:. python -m report.r14_numbers   -> results/report/r14_numbers.json
"""
from __future__ import annotations

import collections
import json
from math import comb

from eval.score import outcome
from gegenprobe.paths import DATA, RESULTS

OUT = RESULTS / "report" / "r14_numbers.json"
BUILD = "publicai_swiss-ai_apertus-v1.5-8b"


def _j(*parts):
    return json.loads(RESULTS.joinpath(*parts).read_text(encoding="utf-8"))


def coverage_split() -> dict:
    c = _j("report", "r9_numbers.json")["coverage"]
    verified = _j("report", "r7docs_numbers.json")["repairs"]["verified"]
    review = c["after_hash_review"] + (c["repaired"] - verified - c["agenda"] - c["after_hash_review"])
    assert verified + c["agenda"] + review == c["repaired"], "9,720 = checked + agenda joins + review rows"
    w = c["written"]
    checked = (c["attached"] + verified) / w
    total = (c["attached"] + c["repaired"]) / w
    checked_s, total_s = f"{100 * checked:.1f}%", f"{100 * total:.1f}%"
    assert total_s == c["share"]["all"], (total_s, c["share"]["all"])
    points = round(100 * total, 1) - round(100 * checked, 1)
    return dict(written=w, attached=c["attached"], repaired=c["repaired"], row_checked=verified, agenda=c["agenda"],
                review=review, share_row_checked=checked_s, share_all=total_s,
                points_unchecked=f"{points:.1f}",
                note="points_unchecked = the rounded total minus the rounded row-checked share, so the two printed parts "
                     "add up to the printed 92.3%")


def _mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def _wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return c - h, c + h


def p1_model_free_cascade() -> dict:
    res = _j("eval", f"heldout__{BUILD}.json")["per_doc"]
    dtype = {d["doc_id"]: d["dtype"] for d in map(json.loads, open(DATA / "gold" / "heldout_docs.jsonl", encoding="utf-8"))}
    arms = collections.defaultdict(list)
    for r in res:
        dd = r.get("doc_dates") or []
        latest = (max(dd) if dd else None) if dtype[r["doc_id"]] == "answer" else None
        s = r["rules"].get("status")
        arms["model_free_cascade"].append((r, r["rules"].get("value") if s in ("value", "null") else latest))
        arms["apertus_cascade"].append((r, r["cascade"].get("value")))
        arms["rules"].append((r, r["rules"].get("value")))
    out, right = {}, {}
    for a, rows in arms.items():
        oc = [outcome(p, r["gold"], set(r.get("doc_dates") or []), r.get("lenient") or [], True) for r, p in rows]
        c = collections.Counter(oc)
        right[a] = [o in ("correct", "correct_null") for o in oc]
        nv = sum(r["gold"] is not None for r, _ in rows)
        out[a] = dict(n=len(rows), exact=c["correct"] + c["correct_null"], found=[c["correct"], nv],
                      answerless_dated=[sum(p is not None for r, p in rows if r["gold"] is None), len(rows) - nv],
                      wrong_printed=c["misattributed"], printed_nowhere=c["fabricated"])
    k, n = out["model_free_cascade"]["exact"], out["model_free_cascade"]["n"]
    lo, hi = _wilson(k, n)
    out["model_free_cascade"]["exact_ci_display"] = f"[{100 * lo:.1f}, {100 * hi:.1f}]"
    b = sum(x and not y for x, y in zip(right["apertus_cascade"], right["model_free_cascade"]))
    c = sum(y and not x for x, y in zip(right["apertus_cascade"], right["model_free_cascade"]))
    return dict(label="POST HOC (not pre-registered): P1 model-free cascade, defined as P6's (eval/posthoc_r6.py)",
                arms=out, paired=dict(apertus_only_right=b, model_free_only_right=c,
                                      mcnemar_exact_p=round(_mcnemar_exact(b, c), 3)))


def answer_times() -> dict:
    d = _j("findings", "answer_times.json")
    per = d["per_parliament"]
    same_day = {b: v for b, v in per.items() if v.get("in_ranking") and v.get("date_trust") == "same_day"}
    out = {}
    for b, v in sorted(same_day.items()):
        out[b] = dict(name=v["name"], opd_plain_median=v["opd_plain"]["median"], opd_plain_n=v["opd_plain"]["n"],
                      document_median=v["adapter"]["median"], document_n=v["adapter"]["n"],
                      same_day_share=v["same_day_share"])
    rk = d["ranking"]
    return dict(same_day_parliaments=out, names=" and ".join(v["name"] for v in out.values()),
                rho_plain=rk["spearman_opd_plain_vs_adapter"]["rho"],
                rho_plain_without_same_day=rk["spearman_opd_plain_vs_adapter_without_same_day"]["rho"],
                rho_same_affairs=rk["spearman_opd_same_affairs_vs_adapter"]["rho"],
                rho_plain_vs_same_affairs=rk["spearman_opd_plain_vs_opd_same_affairs"]["rho"],
                ranked=rk["parliaments"])


def main() -> int:
    out = dict(label="round-14 display numbers from committed files (report/r14_numbers.py)",
               coverage=coverage_split(), p1_model_free_cascade=p1_model_free_cascade(), answer_times=answer_times())
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
