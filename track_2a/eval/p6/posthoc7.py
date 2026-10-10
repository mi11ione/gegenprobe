"""POST HOC (11 Oct 2026, after the P6 labels; not pre-registered): analyses of the P6 result that change no registered
decision.

  theta0   v2 with the presence gate at θ = 0 instead of the registered θ = −5.888 (fitted on P1 dev). DEV2 and P6 both showed
           the fitted θ stopping answered documents from new layouts. Same code, same prompts, same cache; documents the
           registered run stopped at the gate are run on (model calls through the gateway, tag 2a-p6).
  errors   every v2 error with the step that made it, and what the other arms returned on that document
  bodies   exact per parliament for every arm

    PYTHONPATH=src:. python -m eval.p6.posthoc7     -> results/p6/posthoc7.json
"""

from __future__ import annotations

import collections
import json

from eval import arms
from eval.p6 import hypotheses7 as H
from eval.p6 import run_p6
from eval.p6 import sample as S
from gegenprobe.convert import pointer_v2 as V
from gegenprobe.convert import rules
from gegenprobe.paths import RESULTS

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
SPEC = "gateway:swiss-ai/apertus-v1.5-8b:2a-p6:2.0"
LABEL = "POST HOC (11 Oct 2026, after the P6 labels; not pre-registered): no registered decision depends on this file"


def main() -> dict:
    res = json.loads((RESULTS / "p6" / f"p6__{BUILD}.json").read_text())
    labels = {r["doc_id"]: r for r in map(json.loads, open(S.LABELS))}
    rows = H.flatten(res, labels)
    by_id = {r["doc_id"]: r for r in rows}
    out = dict(label=LABEL)
    # theta0
    be = arms.backend(SPEC)
    cfg = run_p6.config()
    cfg0 = V.Config(gate=cfg.gate, theta_presence=0.0, pick=cfg.pick, gen_max_tokens=cfg.gen_max_tokens, name="v2-theta0")
    docs = {d["doc_id"]: d for d in run_p6.load()}
    v2_0 = {}
    for i, d in docs.items():
        r = V.answer_date(be, d["pages"], d["lg"], cfg0, anchors=rules.anchors(d["pages"]), seed=i % 100000)
        v2_0[i] = r.value
    rows0 = [dict(r, v2_theta0=v2_0[r["doc_id"]]) for r in rows]
    blk = H.arm_block(rows0, "v2_theta0")
    out["theta0"] = dict(
        v2_theta0=blk,
        v2_registered=H.arm_block(rows, "v2"),
        vs_free_null=H.paired(rows0, "v2_theta0", "free_null"),
        vs_free_guided=H.paired(rows0, "v2_theta0", "free_guided"),
        vs_v1=H.paired(rows0, "v2_theta0", "v1"),
        changed=[dict(doc_id=i, gold=by_id[i]["gold"], registered=by_id[i]["v2"], theta0=v2_0[i])
                 for i in sorted(v2_0) if v2_0[i] != by_id[i]["v2"]],
    )
    # errors
    errs = []
    for r in rows:
        if not H.ok(r["v2"], r):
            kind = "dated_answerless" if r["gold"] is None else ("missed" if r["v2"] is None else "wrong_date")
            errs.append(dict(doc_id=r["doc_id"], body=r["body"], dtype=r["dtype"], kind=kind, step=r["v2_stage"],
                             presence_margin=r["presence_margin"], gold=r["gold"],
                             **{a: r[a] for a in ("v2", "v1", "free_null", "free_guided", "rules")}))
    out["v2_errors"] = errs
    out["v2_errors_by_step"] = dict(collections.Counter(f"{e['step']}:{e['kind']}" for e in errs))
    # bodies
    arms_ = [a for a in H.ARMS if all(a in r for r in rows)]
    out["per_parliament"] = {b: {a: H.arm_block([r for r in rows if r["body"] == b], a)["exact"] for a in arms_}
                             for b in sorted({r["body"] for r in rows})}
    p = RESULTS / "p6" / "posthoc7.json"
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = main()
    print(json.dumps(dict(theta0={k: v for k, v in o["theta0"].items() if k != "v2_registered"},
                          errors=o["v2_errors_by_step"]), indent=1)[:3000])
