"""POST HOC (12 Oct 2026; proposed in review; not pre-registered): does the closed reader's margin rank its wrong values
first better than ranking signals that need no model? On P1, P2 and P6 (the held-out sets of eval.closed_vs_free), on
exactly the values the closed reader returns. No model call, no network, no document text: committed results files and
document metadata (data/*/..._docs.jsonl: extractor, page and character counts, OPD's document type) only. No registered
decision depends on this file.

    PYTHONPATH=src:. python -m eval.margin_vs_nomodel   -> results/eval/margin_vs_nomodel.json

The margin (eval.closed_vs_free._ranking, reproduced here): P1 and P2 the pointer's null margin, P6 reader v2's presence
margin; higher = closer to null = more doubtful. Its AUROC for "this returned value is wrong" (strict outcome,
eval.posthoc_r6._ok) is the number this file compares (P1 0.732, P2 0.896, P6 0.713 in results/eval/closed_vs_free.json).

No-model signals, each with its direction fixed before scoring (higher = more doubtful) and computed on the same rows:
  n_candidates        distinct dates printed in the document (the closed reader's candidate set; doc_dates)
  ocr                 the text came from OCR (extractor tesseract; only P1 has OCR documents)
  rules_no_value      the registered rules returned no value for the document (abstain or typed null)
  rules_unconfirmed   the rules did not return the same date as the reader (no value, or a different one)
  later_dates         how many distinct printed dates are later than the returned date (0 = it is the latest)
  days_before_latest  days between the returned date and the latest printed date
  intervention_typed  OPD types the document as an intervention, not an answer
  chars, pages        document length (characters of extracted text; pages)
  rules_unconfirmed_then_n_candidates   rules_unconfirmed, ties broken by n_candidates (fixed combination)
later_dates and days_before_latest read the returned date (not the margin): they are what a reviewer sees next to it.

Per signal: AUROC (Mann-Whitney, ties half) for wrong vs right; a document-level percentile bootstrap 95% interval
(resampling the returned values with replacement, B = 10,000, seed 20261011; resamples with no wrong or no right value
dropped and counted); the paired bootstrap interval of margin AUROC minus signal AUROC on the same resamples; and,
flagged as optimistic, the AUROC in the better of the two directions. The best no-model signal per set is the one with
the highest fixed-direction AUROC, chosen on the same rows (so it favours the baseline). Everything is computed twice:
on all values the reader returns (the rows of closed_vs_free) and on the `residue`, the documents where the registered
rules return no value (the documents the deployed cascade sends to the reader, and so the queue the margin orders).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys

import numpy as np

from eval import closed_vs_free as CF
from eval import posthoc_r6 as R6
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import auroc

OUT = RESULTS / "eval" / "margin_vs_nomodel.json"
LABEL = ("POST HOC (12 Oct 2026; proposed in review; not pre-registered): the closed reader's margin vs no-model ranking "
         "signals for flagging its wrong values (P1, P2, P6), from committed results and document metadata; no "
         "registered decision depends on this file")
DOCS = {"P1": DATA / "gold" / "heldout_docs.jsonl", "P2": DATA / "gold2" / "p2_docs.jsonl",
        "P6": DATA / "p6" / "p6_docs.jsonl"}
B_BOOT = 10_000
SEED = 20261011
SIGNALS = ("n_candidates", "ocr", "rules_no_value", "rules_unconfirmed", "later_dates", "days_before_latest",
           "intervention_typed", "chars", "pages", "rules_unconfirmed_then_n_candidates")


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days


def value_rows(split: str) -> tuple[list[dict], str]:
    """The closed reader's returned values with a finite margin (eval.closed_vs_free._ranking's rows), with every signal."""
    rows, cfg = CF._rows(split)
    arm = cfg["closed"]
    meta = {d["doc_id"]: d for d in _jsonl(DOCS[split])}
    if split == "P6":
        status = {r["doc_id"]: r["rules_status"] for r in rows}
    else:
        res = json.loads(CF.RES[split].read_text(encoding="utf-8"))
        status = {d["doc_id"]: d["rules"]["status"] for d in res["per_doc"]}
    out = []
    for r in rows:
        v, m = r[arm], r["margin_closed"]
        if v is None or m is None or not math.isfinite(m):
            continue
        d = meta[r["doc_id"]]
        printed = sorted(set(r["doc_dates"]))
        later = [x for x in printed if x > v]
        unconf = float(r["rules"] != v)
        sig = dict(n_candidates=float(len(printed)), ocr=float(d["extractor"].startswith("tesseract")),
                   rules_no_value=float(status[r["doc_id"]] != "value"), rules_unconfirmed=unconf,
                   later_dates=float(len(later)), days_before_latest=float(_days(printed[-1], v)) if later else 0.0,
                   intervention_typed=float(d["dtype"] != "answer"), chars=float(d["chars"]), pages=float(d["pages"]),
                   rules_unconfirmed_then_n_candidates=unconf * 1000.0 + len(printed))
        out.append(dict(doc_id=r["doc_id"], body=r["body"], wrong=not R6._ok(v, r), margin=float(m), **sig))
    return out, arm


def _kernel(s: np.ndarray, y: np.ndarray) -> np.ndarray:
    """K[i, j] = [y_i wrong][y_j right] * (1 if s_i > s_j, 1/2 if equal): AUROC numerator for any resample counts."""
    gt = (s[:, None] > s[None, :]).astype(float) + 0.5 * (s[:, None] == s[None, :])
    return gt * (y[:, None] == 1) * (y[None, :] == 0)


def _boot_aurocs(scores: dict[str, np.ndarray], y: np.ndarray) -> tuple[dict[str, np.ndarray], int]:
    n = len(y)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, n, size=(B_BOOT, n))
    c = np.zeros((B_BOOT, n))
    np.add.at(c, (np.repeat(np.arange(B_BOOT), n), idx.ravel()), 1.0)
    npos, nneg = c @ y, c @ (1 - y)
    ok = (npos > 0) & (nneg > 0)
    out = {}
    for k, s in scores.items():
        num = ((c @ _kernel(s, y)) * c).sum(axis=1)
        out[k] = num[ok] / (npos[ok] * nneg[ok])
    return out, int((~ok).sum())


def _ci(x: np.ndarray) -> list[float]:
    return [round(float(np.percentile(x, 2.5)), 3), round(float(np.percentile(x, 97.5)), 3)]


def block(vr: list[dict], arm: str) -> dict:
    y = np.array([float(r["wrong"]) for r in vr])
    scores = {k: np.array([r[k] for r in vr]) for k in ("margin",) + SIGNALS}
    boot, dropped = _boot_aurocs(scores, y)
    pt = {k: auroc([r[k] for r in vr if r["wrong"]], [r[k] for r in vr if not r["wrong"]]) for k in scores}
    sig = {}
    for k in SIGNALS:
        distinct = len(set(scores[k].tolist()))
        d = boot["margin"] - boot[k]
        sig[k] = dict(auroc=round(pt[k], 3), ci95=_ci(boot[k]), distinct_values=distinct,
                      auroc_better_direction_optimistic=round(max(pt[k], 1 - pt[k]), 3),
                      margin_minus_signal=round(pt["margin"] - pt[k], 3), margin_minus_signal_ci95=_ci(d),
                      margin_better_interval_excludes_0=bool(np.percentile(d, 2.5) > 0))
    best = max(SIGNALS, key=lambda k: (pt[k], k))
    wrong = int(y.sum())
    return dict(arm=arm, values=len(vr), wrong=wrong, right=len(vr) - wrong,
                margin=dict(auroc=round(pt["margin"], 3), ci95=_ci(boot["margin"])),
                signals=sig, best_nomodel_signal=dict(name=best, auroc=round(pt[best], 3), ci95=sig[best]["ci95"],
                                                      margin_minus_best=sig[best]["margin_minus_signal"],
                                                      margin_minus_best_ci95=sig[best]["margin_minus_signal_ci95"],
                                                      margin_better_interval_excludes_0=sig[best][
                                                          "margin_better_interval_excludes_0"]),
                bootstrap=dict(b=B_BOOT, seed=SEED, resamples_dropped=dropped, unit="returned value (document)"))


def split_block(split: str) -> dict:
    vr, arm = value_rows(split)
    residue = [r for r in vr if r["rules_no_value"]]
    return dict(**block(vr, arm), residue=dict(
        note="only the documents where the registered rules return no value: the ones the deployed cascade (rules "
             "first) routes to the reader, so the review queue the margin orders in practice; rules_no_value and "
             "rules_unconfirmed are constant here", **block(residue, arm)))


def compute() -> dict:
    sets = {s: split_block(s) for s in ("P1", "P2", "P6")}
    cvf = json.loads((RESULTS / "eval" / "closed_vs_free.json").read_text(encoding="utf-8"))
    match = {s: sets[s]["margin"]["auroc"] == cvf["display"]["margin_auroc_wrong_values"][s] for s in sets}
    beats = {s: [k for k, v in sets[s]["signals"].items() if v["margin_better_interval_excludes_0"]] for s in sets}
    res = {s: sets[s]["residue"] for s in sets}
    return dict(
        label=LABEL, proposed_by="proposed in review (round-20 skeptical-ML review); signals chosen and computed by the team",
        method=__doc__.split("No-model signals,")[0].split("    PYTHONPATH")[0].strip(),
        signals_defined=__doc__.split("No-model signals,")[1].split("Per signal:")[0].strip(),
        statistics=__doc__.split("Per signal:")[1].strip(),
        sets=sets, margin_matches_closed_vs_free=match,
        display=dict(
            margin_auroc={s: sets[s]["margin"]["auroc"] for s in sets},
            margin_ci95={s: sets[s]["margin"]["ci95"] for s in sets},
            best_nomodel={s: f"{sets[s]['best_nomodel_signal']['name']} {sets[s]['best_nomodel_signal']['auroc']:.3f}"
                          for s in sets},
            best_nomodel_ci95={s: sets[s]["best_nomodel_signal"]["ci95"] for s in sets},
            margin_minus_best_ci95={s: sets[s]["best_nomodel_signal"]["margin_minus_best_ci95"] for s in sets},
            margin_beats_signal_interval_excludes_0=beats,
            residue_values={s: f"{res[s]['values']} ({res[s]['wrong']} wrong)" for s in sets},
            residue_margin_auroc={s: res[s]["margin"]["auroc"] for s in sets},
            residue_margin_ci95={s: res[s]["margin"]["ci95"] for s in sets},
            residue_best_nomodel={s: f"{res[s]['best_nomodel_signal']['name']} {res[s]['best_nomodel_signal']['auroc']:.3f}"
                                  for s in sets},
            residue_margin_minus_best_ci95={s: res[s]["best_nomodel_signal"]["margin_minus_best_ci95"] for s in sets}),
    )


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
