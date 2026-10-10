"""θ for the Q/A pointer fields, fitted on the P5 dev labels only, from cached model scores (no new model call:
GP_OFFLINE=1). For each field, θ sweeps a grid; the objective is (correct pointer values - wrong pointer values) on the
dev residue (pair: answer spans matching gold minus non-matching suggestions; recommendation and submitter: correct minus
wrong decisions). θ = midpoint of the widest optimal interval (as convert.calibrate). Ties at the objective's maximum
across the whole grid -> θ = 0 (declared).

    GP_OFFLINE=1 python -m eval.gold6.tune6 <backend spec>   -> data/gold6/theta_p5dev.json
"""

from __future__ import annotations

import json
import os
import sys

from eval.arms import backend as make_backend
from eval.gold6 import common6 as C
from eval.gold6.annotate6 import _rows
from eval.gold6.run6 import labels
from eval.gold6.score6 import iou, name_match
from gegenprobe.qa import extract as X

GRID = [float(x) for x in range(-60, 21)]


def objective(field: str, theta: float, be, rows, gold) -> int:
    tot = 0
    for r in rows:
        g = gold[r["affair_id"]]
        tx = C.texts(r)
        R = X.extract(tx["question"], tx["answer"], r.get("lang") or "de", None)
        if field not in R["residue"]:
            continue
        RA = X.extract(tx["question"], tx["answer"], r.get("lang") or "de", be, {field: theta})
        if field == "pair":
            rv = {x["n"]: x["span"] for x in R["view"]["answers"]}
            gs = {x["n"]: x["span"] for x in g["answers"]}
            for x in RA["view"]["answers"]:
                if rv.get(x["n"]) is None and x["span"] is not None:
                    tot += 1 if (gs.get(x["n"]) and iou(gs[x["n"]], x["span"]) >= 0.5) else -1
        elif field == "recommendation":
            tot += 1 if RA["view"]["recommendation"] == g["recommendation"] else -1
        elif field == "submitter":
            s = RA["view"]["submitter"]
            ok = (s is None and g["submitter"] is None) or (s and name_match(g["submitter"], s["name"]))
            tot += 1 if ok else -1
    return tot


def main(spec: str) -> dict:
    assert os.environ.get("GP_OFFLINE") == "1", "tuning replays cached scores only (GP_OFFLINE=1)"
    be = make_backend(spec)
    rows, gold = _rows("p5dev"), labels("p5dev")
    out = {}
    for field in ("pair", "recommendation", "submitter"):
        vals = [objective(field, t, be, rows, gold) for t in GRID]
        best = max(vals)
        # widest run of consecutive grid points at the maximum
        runs, cur = [], []
        for t, v in zip(GRID, vals):
            if v == best:
                cur.append(t)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        w = max(runs, key=len)
        theta = 0.0 if len(w) == len(GRID) else (w[0] + w[-1]) / 2
        out[field] = dict(theta=theta, objective_max=best, optimal_interval=[w[0], w[-1]], curve=dict(zip(map(str, GRID), vals)))
    p = C.GOLD6 / "theta_p5dev.json"
    p.write_text(json.dumps(dict(build=be.build, fitted_on="p5dev", grid=[GRID[0], GRID[-1], 1.0], fields=out), indent=1))
    return out


if __name__ == "__main__":
    o = main(sys.argv[1])
    print({k: (v["theta"], v["objective_max"], v["optimal_interval"]) for k, v in o.items()})
