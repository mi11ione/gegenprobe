"""P7 post hoc, round 9 (11 Oct 2026; NOT registered, written after the P7 test gold was read; no model call, no registered
decision changes): a parliament-cluster interval for the date-choice gain that results/p7/p7_posthoc_r8.json reports with
the registered row-level (stratified) bootstrap only.

    PYTHONPATH=src:. python -m eval.p7.cluster_r9     -> results/p7/p7_cluster_r9.json

Same inputs, rows and estimators as eval.p7.posthoc_r8 (its frame_rows and cluster_vals are reused unchanged); the point
estimates are asserted equal to the round-8 file before anything is written. Statistics, on date-checked precision (the
registered correct_dated: the row is the executive's answer and a gold answer date passes the adapters' date rule):

  date_choice      p7 (Apertus yes/no gate + Apertus picks the printed date) minus gate_rule_any (the same gate, the
                   adapters' date rule accepting any printed date of the same closed set): what Apertus's date choice adds
  vs_no_model      p7 minus rule_any_view (no model at all: some printed date of the same closed set passes the rule)

Each with the row-level interval from the round-8 file and the parliament-cluster interval (parliaments resampled with
replacement, each with all its annotated rows and stratum weights; B = 10,000, seed 20261014, percentile 95%), plus the
estimate without Frauenfeld (4566, the parliament with most promotions).
"""

from __future__ import annotations

import json

from eval.p7 import hypotheses8 as H
from eval.p7 import posthoc_r8 as R
from eval.p7 import test as T
from gegenprobe.paths import RESULTS
from gegenprobe.repair.adapters import adjudicate as J

OUT = RESULTS / "p7" / "p7_cluster_r9.json"
R8 = RESULTS / "p7" / "p7_posthoc_r8.json"
LABEL = ("POST HOC (11 Oct 2026, round 9; not pre-registered): written after the P7 test gold was read; no model call; "
         "no registered decision depends on this file")


def rows() -> list[dict]:
    rs, _ = H.load()
    fr = {(f["body"], f["affair_id"]): f for f in R.frame_rows(J.load_config().theta_a)}
    key = {r["id"]: r for r in map(json.loads, (T.WORKDIR / "key.jsonl").read_text().splitlines())}
    for r in rs:
        k = key[r["id"]]
        f = fr[(k["body"], k["affair_id"])]
        for a in ("rule_any_view", "gate_rule_any"):
            r[a] = f[a]
    return rs


def pts(v):
    return None if v is None else round(100 * v, 1)


def block(rs: list[dict], base: str, r8_key: str, r8: dict) -> dict:
    stat = lambda xs: R._ratio(xs, "p7", "correct_dated") - R._ratio(xs, base, "correct_dated")  # noqa: E731
    est = stat(rs)
    r8d = r8["ablation"]["differences"][r8_key]
    assert R._r(est) == r8d["estimate"], (r8_key, est, r8d["estimate"])
    cv, undefined = R.cluster_vals(rs, stat)
    ci = R._pct(cv)
    nf = [r for r in rs if r["body"] != R.FRAUENFELD]
    return dict(
        p7=R._r(R._ratio(rs, "p7", "correct_dated")), baseline=R._r(R._ratio(rs, base, "correct_dated")),
        estimate=R._r(est), row_ci95=r8d["ci95"], cluster_ci95=ci, cluster_undefined_resamples=undefined,
        cluster_excludes_0=bool(cv) and ci[0] > 0,
        share_of_cluster_resamples_above_0=R._r(sum(v > 0 for v in cv) / len(cv)) if cv else None,
        without_frauenfeld=R._r(stat(nf)),
        display=dict(pts=pts(est), row_ci=[pts(v) for v in r8d["ci95"]], cluster_ci=[pts(v) for v in ci],
                     p7_pct=pts(R._ratio(rs, "p7", "correct_dated")), baseline_pct=pts(R._ratio(rs, base, "correct_dated")),
                     without_frauenfeld_pts=pts(stat(nf))))


def main() -> dict:
    r8 = json.loads(R8.read_text())
    rs = rows()
    res = dict(
        label=LABEL, method="parliaments (bodies) of the 190 annotated rows resampled with replacement, each with all its "
                            "annotated rows and their sampling-stratum weights; B = 10,000, seed 20261014, percentile 95% "
                            "(eval.p7.posthoc_r8.cluster_vals)",
        n_rows=len(rs), n_parliaments=len({r["body"] for r in rs}),
        date_choice=block(rs, "gate_rule_any", "p7_minus_gate_rule_any_precision_dated", r8),
        vs_no_model=block(rs, "rule_any_view", "p7_minus_rule_any_view_precision_dated", r8))
    OUT.write_text(json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
