"""POST HOC (12 Oct 2026; proposed in review; not pre-registered): the closed-set reader against a free prompt that may
answer null, on P1, P2 and P6, and what the closed design buys and what it does not. No registered decision depends on
this file (P6-H1, v2 vs the free null-allowed prompt, is the one registered comparison of this kind; it did not hold).
No model call, no network: committed results files only.

Arms (registered runs, scored with the frozen strict outcome, eval.score.outcome via eval.posthoc_r6._ok):
  closed   P1 and P2: the Apertus pointer (θ = 10.40) and the cascade (rules, then the pointer); P6: reader v2 and its
           cascade (the registered P6 arms).
  free     the free prompt with null allowed ("naive, null-allowed"): P1 and P2 with the registered parser (as in the
           results files) and, from results/eval/posthoc_r3_paired.json, with the corrected parser (D2-4); P6's
           `free_null` (registered H1 comparator, corrected parser).

What this file measures:
  * accuracy: exact (correct value or correct null), answer dates found, answerless documents dated, and the paired
    difference (exact McNemar; parliament-cluster percentile bootstrap, eval.posthoc_r6.doc_level_block, B = 10,000,
    seed 20261011);
  * provenance: values among the printed dates (the dates the frozen lattice reads; a correct value outside them is not
    counted there and not as printed nowhere), values printed
    nowhere, and for the free prompt how many of its values come with a quote that occurs verbatim in the text and
    contains the date (eval.posthoc_r3 quote check; the closed arms' values are lattice candidates, so each has a page
    and a character span by construction, `convert/pointer.locate`);
  * review ranking: the closed reader's margin as an ordering of its suggested values for review. AUROC of the margin
    for "this value is wrong" among the values the reader returns (higher margin = closer to null), and how many of the
    wrong values sit in the first quarter of a queue sorted by margin; next to it the free prompt's only signal, its
    quote check (a yes/no flag, as AUROC), and the registered null-vs-value margin AUROCs (P1-H3, P2-H4, P6-S4).

    PYTHONPATH=src:. python -m eval.closed_vs_free   -> results/eval/closed_vs_free.json
"""

from __future__ import annotations

import json
import math
import sys

from eval import posthoc_r6 as R6
from gegenprobe.paths import RESULTS
from gegenprobe.stats import auroc

OUT = RESULTS / "eval" / "closed_vs_free.json"
BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
LABEL = ("POST HOC (12 Oct 2026; proposed in review; not pre-registered): closed-set reader vs a free prompt with null "
         "allowed (P1, P2, P6) from committed results; what the closed design buys (provenance, a review ranking) and "
         "what it does not (accuracy); no registered decision depends on this file")
RES = {"P1": RESULTS / "eval" / f"heldout__{BUILD}.json", "P2": RESULTS / "eval2" / f"p2__{BUILD}.json",
       "P6": RESULTS / "p6" / f"p6__{BUILD}.json"}


def _r(x: float, nd: int = 3) -> float:
    return round(x, nd)


def _rows(split: str) -> tuple[list[dict], dict]:
    """Rows with the arm predictions, the margin of the closed reader and the free prompt's receipt flag."""
    res = json.loads(RES[split].read_text())
    per = {d["doc_id"]: d for d in res["per_doc"]}
    if split == "P6":
        rows = R6._p6_rows()
        for r in rows:
            d = per[r["doc_id"]]
            r["margin_closed"] = r["presence_margin"]
            r["free_receipt_ok"] = (d.get("free_null") or {}).get("receipt_ok")
        theta = res["v2_config"]["theta_presence"]
        return rows, dict(closed="v2", cascade="cascade_v2", free="free_null", theta=theta,
                          margin="v2 presence margin (answer present vs not), gate θ_presence")
    rows = R6._p12_rows(split)
    for r in rows:
        d = per[r["doc_id"]]
        r["margin_closed"] = d["pointer"].get("margin") if d["pointer"].get("n_cands") else None
        r["free_receipt_ok"] = (d.get("naive_null") or {}).get("receipt_ok")
    return rows, dict(closed="pointer", cascade="cascade", free="naive_null", theta=res["theta"],
                      margin="pointer null margin lp(null) - logsumexp(lp(dates)), θ = 10.40")


def _acc(rows: list[dict], arm: str) -> dict:
    nul = [r for r in rows if r["gold"] is None]
    ans = [r for r in rows if r["gold"] is not None]
    vals = [r for r in rows if r[arm] is not None]
    return dict(exact=[sum(R6._ok(r[arm], r) for r in rows), len(rows)],
                answer_dates_found=[sum(R6._ok(r[arm], r) for r in ans), len(ans)],
                answerless_dated=[sum(r[arm] is not None for r in nul), len(nul)],
                values=len(vals),
                values_among_printed_dates=sum(r[arm] in set(r["doc_dates"]) for r in vals),
                values_printed_nowhere=sum(r[arm] not in set(r["doc_dates"]) and not R6._ok(r[arm], r) for r in vals))


def _ranking(rows: list[dict], arm: str) -> dict:
    """The closed reader's margin as a review order over the values it returns; the free prompt's quote flag likewise."""
    vals = [r for r in rows if r[arm] is not None and r["margin_closed"] is not None
            and math.isfinite(r["margin_closed"])]
    wrong = [r["margin_closed"] for r in vals if not R6._ok(r[arm], r)]
    right = [r["margin_closed"] for r in vals if R6._ok(r[arm], r)]
    order = sorted(vals, key=lambda r: -r["margin_closed"])  # most doubtful first
    q = math.ceil(len(order) / 4)
    caught = sum(not R6._ok(r[arm], r) for r in order[:q])
    return dict(values=len(vals), wrong=len(wrong), right=len(right),
                auroc_margin_flags_wrong=_r(auroc(wrong, right)) if wrong and right else None,
                first_quarter_of_queue=q, wrong_in_first_quarter=caught)


def _free_flag(rows: list[dict], arm: str) -> dict:
    vals = [r for r in rows if r[arm] is not None and r["free_receipt_ok"] is not None]
    wrong = [0.0 if r["free_receipt_ok"] else 1.0 for r in vals if not R6._ok(r[arm], r)]
    right = [0.0 if r["free_receipt_ok"] else 1.0 for r in vals if R6._ok(r[arm], r)]
    return dict(values=len(vals), with_verified_quote=sum(bool(r["free_receipt_ok"]) for r in vals), wrong=len(wrong),
                wrong_with_verified_quote=sum(1 for w in wrong if w == 0.0),
                auroc_missing_quote_flags_wrong=_r(auroc(wrong, right)) if wrong and right else None)


def _registered_null_auroc(split: str) -> dict:
    if split == "P1":
        h = json.loads((RESULTS / "eval" / f"hypotheses__{BUILD}.json").read_text())["H3"]
        return dict(test="P1-H3 (registered)", auroc=_r(h["auroc"]), n_null=h["n_null"], n_value=h["n_value"])
    if split == "P2":
        h = json.loads((RESULTS / "eval2" / f"hypotheses2__{BUILD}.json").read_text())["subsets"]["all"]
        h = h.get("H4_auroc") or h["theta_10_40"]["H4_auroc"]
        return dict(test="P2-H4 (registered)", auroc=_r(h["auroc"]), n_null=h["n_null"], n_value=h["n_value"])
    h = json.loads((RESULTS / "p6" / f"hypotheses7__{BUILD}.json").read_text())["S4_presence_auroc"]
    return dict(test="P6-S4 (registered secondary)", auroc=_r(h["auroc"]), n_null=h["n_answerless"],
                n_value=h["n_answered"])


def _outward(ci: list[float], nd: int = 3) -> str:
    f = 10 ** nd
    return f"[{math.floor(ci[0] * f) / f:.{nd}f}, {math.ceil(ci[1] * f) / f:.{nd}f}]"


def split_block(split: str) -> dict:
    rows, cfg = _rows(split)
    c, k, f = cfg["closed"], cfg["cascade"], cfg["free"]
    blk = R6.doc_level_block(rows, [c, k, f], [(c, f), (k, f)])
    paired = {}
    for name, v in blk["paired"].items():
        paired[name.replace(" vs ", "_vs_")] = dict(
            n=v["n"], closed_only=v["a_only"], free_only=v["b_only"], mcnemar_exact_p=v["mcnemar_exact_p"],
            p_str=f"{v['mcnemar_exact_p']:.2f}", accuracy_difference=v["accuracy_difference"],
            cluster_bootstrap95=v["cluster_bootstrap95"], cluster95_str=_outward(v["cluster_bootstrap95"]),
            cluster_interval_excludes_0=v["cluster_interval_excludes_0"], n_parliaments=v["n_parliaments"])
    return dict(arms=dict(closed=c, cascade=k, free=f), margin=cfg["margin"], theta=cfg["theta"],
                accuracy={a: _acc(rows, a) for a in (c, k, f)}, paired=paired,
                review_ranking=dict(closed_margin=_ranking(rows, c), free_quote_flag=_free_flag(rows, f),
                                    registered_null_vs_value_auroc=_registered_null_auroc(split)))


def main() -> dict:
    sets = {s: split_block(s) for s in ("P1", "P2", "P6")}
    r3 = json.loads((RESULTS / "eval" / "posthoc_r3_paired.json").read_text())["splits"]
    reparsed = {}
    for s in ("P1", "P2"):
        v = r3[s]
        cmp = v["comparisons"]["pointer~naive_null_reparsed"]
        reparsed[s] = dict(pointer_exact=v["exact"]["pointer"], free_exact=v["exact"]["naive_null_reparsed"],
                           pointer_only=cmp["all"]["pointer_only"], free_only=cmp["all"]["naive_null_reparsed_only"],
                           p_str=cmp["all"]["p_str"], provenance_free=v["provenance"]["naive_null_reparsed"],
                           provenance_pointer=v["provenance"]["pointer"])
    p1, p2, p6 = (sets[s] for s in ("P1", "P2", "P6"))
    a1, a6 = p1["accuracy"], p6["accuracy"]
    out = dict(
        label=LABEL, method=__doc__.split("What this file measures:")[1].split("    PYTHONPATH")[0].strip(),
        sets=sets, corrected_parser=dict(note="free prompt re-parsed with the corrected date parser (D2-4), from "
                                         "results/eval/posthoc_r3_paired.json", **reparsed),
        display=dict(
            p1_exact=f"{a1['pointer']['exact'][0]}/154 vs {a1['naive_null']['exact'][0]}/154",
            p1_answerless_dated=f"{a1['pointer']['answerless_dated'][0]}/90 vs {a1['naive_null']['answerless_dated'][0]}/90",
            p1_p=p1["paired"]["pointer_vs_naive_null"]["p_str"],
            p2_exact_registered_parser=(f"{p2['accuracy']['pointer']['exact'][0]}/62 vs "
                                        f"{p2['accuracy']['naive_null']['exact'][0]}/62"),
            p2_exact_corrected_parser=f"{reparsed['P2']['pointer_exact'][0]}/62 vs {reparsed['P2']['free_exact'][0]}/62",
            p6_exact=f"{a6['v2']['exact'][0]}/68 vs {a6['free_null']['exact'][0]}/68",
            p6_p=p6["paired"]["v2_vs_free_null"]["p_str"],
            free_values_with_verified_quote_p1=(f"{reparsed['P1']['provenance_free']['quote_verbatim_and_contains_date']}"
                                                f"/{reparsed['P1']['provenance_free']['values']}"),
            free_values_with_verified_quote_p2=(f"{reparsed['P2']['provenance_free']['quote_verbatim_and_contains_date']}"
                                                f"/{reparsed['P2']['provenance_free']['values']}"),
            closed_values_printed_and_located=dict(
                P1=f"{a1['pointer']['values_among_printed_dates']}/{a1['pointer']['values']}",
                P2=f"{p2['accuracy']['pointer']['values_among_printed_dates']}/{p2['accuracy']['pointer']['values']}",
                P6=f"{a6['v2']['values_among_printed_dates']}/{a6['v2']['values']}"),
            margin_auroc_wrong_values={s: sets[s]["review_ranking"]["closed_margin"]["auroc_margin_flags_wrong"]
                                       for s in sets},
            free_quote_auroc_wrong_values={s: sets[s]["review_ranking"]["free_quote_flag"]
                                           ["auroc_missing_quote_flags_wrong"] for s in sets},
        ),
        reading=("Accuracy: the closed reader is not more accurate than the free prompt with null allowed on any of the "
                 "three sets (no paired difference is significant; on P1 and P6 the free prompt is ahead in point "
                 "estimate). What the closed design buys: every value it returns is a date printed in the document, "
                 "with page and span from the lattice, by construction; the free prompt's values are printed in the "
                 "document almost always too, but a checkable quote comes with only about half of them, and a "
                 "printed-date filter added after a free prompt would give the no-invention guarantee as well. The "
                 "margin orders the closed reader's values for review; the free prompt has only its quote flag."),
    )
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main()["display"], indent=1))
    sys.exit(0)
