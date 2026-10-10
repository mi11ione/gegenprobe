"""P3b hypotheses and replication verdict (eval/prereg5/PREREG5.md). Model-free.

H1-H4 come from P3's own code, unchanged: `eval.gold3.hypotheses3.main` and the P3 views in `eval.baselines` (constant
baseline, set metrics with CIs, decision-number view) run on a staged copy of the P3b results file and labels laid out
under P3's file names (.work/gold5/stage_h/{eval3,gold3}/). The primary H3 rebinds `H3_FIELDS` to the five registered
fields (addressed_body excluded); the six-field H3 exactly as PREREG3 is the secondary. The only new logic is the
registered success criteria S1/S2 against the P3 reference below.

    python -m eval.gold5.hypotheses5 publicai_swiss-ai_apertus-v1.5-8b   -> results/eval5/hypotheses_p3b__<build>.json
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys

from eval import baselines
from eval.gold3 import hypotheses3 as h3
from eval.gold5.run_p3b import LABELS5, OUT5
from gegenprobe.paths import WORK
from gegenprobe.stats import wilson

STAGE = WORK / "gold5" / "stage_h"
H3_PRIMARY = ("submitter", "submitted", "affair_type", "answer_date", "recommendation")
# P3 reference, arm C (results/eval3/hypotheses3__publicai_swiss-ai_apertus-v1.5-8b.json; PREREG5 "Success criteria")
P3_REF = {
    "number": (21, 29),
    "affair_type": (27, 29),
    "submitter": (23, 29),
    "submitted": (15, 21),
    "answer_date": (22, 27),
    "decision_number": (0, 17),
    "recommendation": (1, 2),
    "addressed_body": (4, 28),
}
MIN_N = 10


@contextlib.contextmanager
def staged(build: str):
    """P3b results + labels under P3's names in a scratch root; P3 modules' RESULTS/DATA/BUILD point there meanwhile."""
    shutil.rmtree(STAGE, ignore_errors=True)
    (STAGE / "eval3").mkdir(parents=True)
    (STAGE / "gold3").mkdir(parents=True)
    shutil.copy(OUT5 / f"p3b__{build}.json", STAGE / "eval3" / f"p3__{build}.json")
    shutil.copy(LABELS5, STAGE / "gold3" / "p3_labels.jsonl")
    saved = (h3.RESULTS, h3.DATA, h3.H3_FIELDS, baselines.RESULTS, baselines.DATA, baselines.BUILD)
    h3.RESULTS = h3.DATA = baselines.RESULTS = baselines.DATA = STAGE
    baselines.BUILD = build
    try:
        yield
    finally:
        h3.RESULTS, h3.DATA, h3.H3_FIELDS, baselines.RESULTS, baselines.DATA, baselines.BUILD = saved


def criteria(primary_h3: dict, h1: dict) -> dict:
    rk, rn = primary_h3["recall"]
    if rn < MIN_N:
        s1 = dict(status="inconclusive (underpowered)", recall=[rk, rn], recall_ci=list(wilson(rk, rn)))
    else:
        lo = wilson(rk, rn)[0]
        s1 = dict(status="holds" if lo >= 0.50 else "fails", recall=[rk, rn], recall_ci=list(wilson(rk, rn)))
    fields = {}
    for f, (k3, n3) in P3_REF.items():
        k5, n5 = h1[f]["correct"], h1[f]["n"]
        lo3, hi3 = wilson(k3, n3)
        row = dict(p3=[k3, n3], p3_ci=[lo3, hi3], p3b=[k5, n5], p3b_ci=list(wilson(k5, n5)))
        if n3 >= MIN_N and n5 >= MIN_N and f != "addressed_body":
            est = k5 / n5
            row["vs_p3_ci"] = "below" if est < lo3 else "above" if est > hi3 else "within"
        else:
            row["vs_p3_ci"] = "not eligible"
        fields[f] = row
    eligible = [v for v in fields.values() if v["vs_p3_ci"] != "not eligible"]
    below = sum(v["vs_p3_ci"] == "below" for v in eligible)
    s2 = dict(
        status="holds" if eligible and below <= 1 else "fails" if eligible else "no eligible field",
        eligible=len(eligible),
        below=below,
        fields=fields,
    )
    h_s1, h_s2 = s1["status"] == "holds", s2["status"] == "holds"
    if h_s1 and h_s2:
        verdict = "replicated"
    elif s1["status"].startswith("inconclusive") and h_s2:
        verdict = "partially replicated (S1 inconclusive: underpowered; S2 holds)"
    elif h_s1 or h_s2:
        verdict = "partially replicated"
    else:
        verdict = "not replicated"
    return dict(S1=s1, S2=s2, verdict=verdict)


def main(build: str) -> dict:
    with staged(build):
        secondary = h3.main(build)  # six-field H3 exactly as PREREG3
        h3.H3_FIELDS = H3_PRIMARY
        primary = h3.main(build)
        base, extra = baselines.p3(), baselines.p3_extra()
    out = dict(
        build=build,
        prereg="eval/prereg5/PREREG5.md",
        n=primary["n"],
        H1=primary["H1"],
        H2=primary["H2"],
        H3_primary=dict(primary["H3"], fields=list(H3_PRIMARY)),
        H3_secondary_as_PREREG3=dict(secondary["H3"], fields=list(secondary["H3"]["per_field"])),
        H4=primary["H4"],
        sets=extra["sets"],
        decision_number=extra["decision_number_defect"],
        constant_baseline=dict(label="PRE-REGISTERED in PREREG5 (post-hoc in P3)", fields=base["fields"]),
    )
    out["replication"] = criteria(primary["H3"], primary["H1"])
    OUT5.mkdir(parents=True, exist_ok=True)
    (OUT5 / f"hypotheses_p3b__{build}.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    r = main(sys.argv[1])
    print(json.dumps(r["replication"], indent=1))
