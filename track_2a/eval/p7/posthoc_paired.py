"""POST HOC (12 Oct 2026; proposed in review; not pre-registered): P7's Apertus promotions and the no-model exact-date
match, PAIRED on the same annotated rows. No model call, no network, no text: the committed P7 copies only (the loader of
eval.p7.posthoc_overlap). No registered decision depends on this file.

    PYTHONPATH=src:. python -m eval.p7.posthoc_paired   -> results/p7/p7_paired.json

Arms: `p7` = Apertus promotes the row and writes `p7_date`; `trivial` = some printed date equals an OPD answer event, and
writes the first such date (`trivial_date`). A promotion is "correctly dated" when the arm's written date is one of the
gold answer dates of a row the annotators call an answer (the "date hit" of eval.p7.posthoc_overlap); a row an arm does
not promote counts as not correctly dated for that arm.

What this file reports (all on the 190 annotated rows of the 478-row test frame):
  * shared rows (both arms promote): date hits per arm, discordant pairs, exact McNemar (two-sided);
  * every annotated row either arm promotes (the union): correctly dated promotions per arm (the yield), discordant
    pairs, exact McNemar; split into shared / Apertus-only / no-model-only;
  * precision (date hits / promotions) per arm, unweighted, and where the precision difference comes from;
  * the stratum-weighted frame estimate of correctly dated promotions per arm (weights N/n per sampling stratum, from
    results/p7/p7_posthoc_r8.json), with a stratified percentile bootstrap of the difference (B = 10,000, seed 20261011).
"""

from __future__ import annotations

import json
import math
import sys

import numpy as np

from eval.p7 import posthoc_overlap as OV
from gegenprobe.paths import RESULTS

OUT = RESULTS / "p7" / "p7_paired.json"
LABEL = ("POST HOC (12 Oct 2026; proposed in review; not pre-registered): P7 Apertus promotions vs the no-model exact-date "
         "match, paired on the same annotated rows, from committed copies; no registered decision depends on this file")
B_BOOT = 10_000
SEED = 20261011


def _mcnemar(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def _pstr(p: float) -> str:
    return f"{p:.2g}" if p >= 0.01 else f"{p:.1e}"


def _hit(r: dict, arm: str) -> bool:
    d = r["p7_date"] if arm == "p7" else r["trivial_date"]
    return bool(r[arm]) and bool(r["correct"]) and bool(d) and d in r["gold_dates"]


def _paired(rows: list[dict]) -> dict:
    a = sum(_hit(r, "p7") for r in rows)
    b = sum(_hit(r, "trivial") for r in rows)
    x = sum(_hit(r, "p7") and not _hit(r, "trivial") for r in rows)
    y = sum(_hit(r, "trivial") and not _hit(r, "p7") for r in rows)
    p = _mcnemar(x, y)
    return dict(rows=len(rows), p7_date_hit=a, trivial_date_hit=b, p7_only_hit=x, trivial_only_hit=y,
                both_hit=sum(_hit(r, "p7") and _hit(r, "trivial") for r in rows), p_mcnemar_exact=p, p_str=_pstr(p))


def compute() -> dict:
    _, ann = OV.load()
    r8 = json.loads(OV.R8.read_text(encoding="utf-8"))
    w = r8["weights"]
    both = [r for r in ann if r["p7"] and r["trivial"]]
    p7_only = [r for r in ann if r["p7"] and not r["trivial"]]
    tr_only = [r for r in ann if r["trivial"] and not r["p7"]]
    union = both + p7_only + tr_only
    prom = {a: [r for r in ann if r[a]] for a in ("p7", "trivial")}
    prec = {a: dict(promoted=len(prom[a]), date_hit=sum(_hit(r, a) for r in prom[a]),
                    correct_dated=sum(bool(r["correct_dated"]) for r in prom[a]),
                    precision_date_hit=round(sum(_hit(r, a) for r in prom[a]) / len(prom[a]), 4))
            for a in ("p7", "trivial")}

    # stratum-weighted frame estimate of correctly dated promotions, and its stratified bootstrap
    strata = sorted({r["stratum"] for r in ann})
    by = {s: [r for r in ann if r["stratum"] == s] for s in strata}
    hits = {s: np.array([[_hit(r, "p7"), _hit(r, "trivial")] for r in by[s]], dtype=float) for s in strata}
    est = {a: sum(w[s] * hits[s][:, j].sum() for s in strata) for j, a in enumerate(("p7", "trivial"))}
    rng = np.random.default_rng(SEED)
    boot = np.zeros((B_BOOT, 2))
    for s in strata:
        n = len(by[s])
        idx = rng.integers(0, n, size=(B_BOOT, n))
        boot += w[s] * hits[s][idx].sum(axis=1)
    diff = boot[:, 0] - boot[:, 1]
    ci = [float(np.percentile(diff, 2.5)), float(np.percentile(diff, 97.5))]
    ci_a = {a: [float(np.percentile(boot[:, j], 2.5)), float(np.percentile(boot[:, j], 97.5))]
            for j, a in enumerate(("p7", "trivial"))}

    sh, un = _paired(both), _paired(union)
    po, to = _paired(p7_only), _paired(tr_only)
    pw = r8["ablation"]["arms"]
    out = dict(
        label=LABEL,
        proposed_by="proposed in review (round-20 skeptical-ML review); counted by the team",
        method=__doc__.split("What this file reports")[1].split("\n", 1)[1].strip(),
        annotated_rows=len(ann), frame_rows=sum(r8["strata_N"].values()), strata_N=r8["strata_N"],
        strata_n=r8["strata_n"], weights=w,
        shared_rows=sh, union=dict(**un, split=dict(shared=sh, p7_only=po, trivial_only=to)),
        precision_unweighted=prec,
        precision_weighted_from_posthoc_r8={a: pw[a]["precision_date_hit"] for a in ("p7", "trivial")},
        weighted_frame_estimate=dict(
            correctly_dated_promotions={a: round(v, 2) for a, v in est.items()},
            ci95={a: [round(v, 2) for v in ci_a[a]] for a in ci_a},
            p7_minus_trivial=round(est["p7"] - est["trivial"], 2), p7_minus_trivial_ci95=[round(v, 2) for v in ci],
            interval_excludes_0=ci[0] > 0 or ci[1] < 0, b=B_BOOT, seed=SEED,
            frame_promoted=r8["trivial"]["promoted_in_frame"]),
        display=dict(
            shared=f"{sh['p7_date_hit']} vs {sh['trivial_date_hit']} of {sh['rows']}",
            shared_discordant=f"{sh['p7_only_hit']} vs {sh['trivial_only_hit']}", shared_p=sh["p_str"],
            yield_annotated=f"{un['p7_date_hit']} vs {un['trivial_date_hit']} of {un['rows']}",
            yield_discordant=f"{un['p7_only_hit']} vs {un['trivial_only_hit']}", yield_p=un["p_str"],
            p7_only=f"{po['p7_date_hit']}/{po['rows']}", trivial_only=f"{to['trivial_date_hit']}/{to['rows']}",
            precision=f"{prec['p7']['date_hit']}/{prec['p7']['promoted']} vs "
                      f"{prec['trivial']['date_hit']}/{prec['trivial']['promoted']}",
            weighted_yield=f"{est['p7']:.1f} vs {est['trivial']:.1f}",
            weighted_yield_diff_ci95=f"[{ci[0]:.1f}, {ci[1]:.1f}]"),
        reading=("On the rows both arms promote, Apertus and the no-model match write the gold answer date equally "
                 "often ({sh}). Apertus's higher precision comes from the rows it declines: the no-model match also "
                 "promotes {to_n} annotated rows Apertus does not, every one an answer, {to_h} of them correctly dated. "
                 "So the no-model match yields more correctly dated promotions ({yld}); Apertus's precision gain is "
                 "an abstention effect, not a better date.").format(
                     sh=f"{sh['p7_date_hit']} vs {sh['trivial_date_hit']} of {sh['rows']}", to_n=to["rows"],
                     to_h=to["trivial_date_hit"], yld=f"{un['p7_date_hit']} vs {un['trivial_date_hit']}"),
    )
    return out


def main(argv: list[str]) -> int:
    out = compute()
    blob = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == blob
        print(OUT.name, "matches" if same else "DIFFERS from a recompute")
        return 0 if same else 1
    OUT.write_text(blob, encoding="utf-8")
    print(json.dumps(out["display"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
