"""POST HOC (11 Oct 2026; proposed in review; not pre-registered): P8's registered decision rule recomputed only on the
affairs where the merged gold and the cross-vendor check (Qwen-SEA-LION-v4-32B-IT) derive the same category for the
field. Reported, never decisive: the registered verdicts in results/p8/p8_hypotheses.json stand. No model call, no
network, no text.

    PYTHONPATH=src:. .venv/bin/python -m eval.p8.qwen_sensitivity export   DEV ONLY: WORK/p8/ann/qwen.jsonl ->
                                                                           data/p8/annotations/QWEN.jsonl (parsed
                                                                           labels only: no raw reply, no notes)
    PYTHONPATH=src:. .venv/bin/python -m eval.p8.qwen_sensitivity          -> results/p8/p8_qwen_sensitivity.json

Why. Under the registered rule one deviating parliament makes a field non-shared (eval/prereg9/PREREG9.md §7), so
labels from a noisier coder raise the chance of a split: "the verdict also holds on Qwen's labels"
(results/p8/p8_posthoc.json, verdicts_on_qwen_labels) is weak corroboration of a split. Keeping only the affairs on
which both coders agree removes coder noise from the decision instead of adding it: a split that survives rests on
affairs two coders from different vendors label alike.

Agreement unit: per affair and field, the derived category key (eval.p8.derive.key; 'n/a' when not applicable),
gold vs Qwen's labels run through the same derivation (eval.p8.annotate.derive_one); an unparseable Qwen label
disagrees. Secondary: agreement only on whether the category is inside the field's shared-meaning set E. Each subset
goes through the registered tables (eval.p8.score.per_parliament, pooled) and decision (eval.p8.hypotheses9.verdict).
Inputs: data/p8/p8_gold.jsonl, data/p8/p8_key.jsonl, data/p8/p8_affairs.jsonl, data/p8/opd_meta_p8.jsonl,
data/p8/p8_datelists.jsonl, data/p8/annotations/QWEN.jsonl; the copy is checked against results/p8/p8_qwen.json
(per-field agreement counts must be equal).
"""

from __future__ import annotations

import json
import sys

from eval.p8 import annotate as A
from eval.p8 import common as C
from eval.p8 import hypotheses9 as H
from eval.p8 import score as S

LABEL = ("POST HOC (11 Oct 2026; proposed in review; not pre-registered): sensitivity of P8's verdicts to coder noise; "
         "never decisive; the registered verdicts stand")
QWEN_COMMITTED = C.ANN_COMMITTED / "QWEN.jsonl"
OUT = C.R8 / "p8_qwen_sensitivity.json"
WHY = ("Under P8's registered rule a single deviating parliament makes a field non-shared, so a noisier coder adds "
       "spurious deviations and can only push towards a split: agreement of the verdict on Qwen's labels cannot "
       "corroborate a split; restricting the test to affairs both coders label alike can.")


def export() -> dict:
    """DEV ONLY: the parsed Qwen labels from WORK, without the raw reply and the notes (as data/p10/annotations/QWEN)."""
    rows = [json.loads(x) for x in (C.ANN / "qwen.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    with open(QWEN_COMMITTED, "w", encoding="utf-8") as f:
        for r in sorted(rows, key=lambda r: r["id"]):
            lab = r.get("label")
            lab = {k: v for k, v in lab.items() if k != "notes"} if lab else None
            f.write(json.dumps(dict(id=r["id"], valid=lab is not None, label=lab), ensure_ascii=False) + "\n")
    return dict(rows=len(rows), out=str(QWEN_COMMITTED))


def context():
    """eval.p8.annotate.context from the committed key (data/p8/p8_key.jsonl, identical to WORK's key)."""
    key = {r["id"]: r for r in C._jsonl(C.D8 / "p8_key.jsonl")}
    rows = {r["affair_id"]: r for r in C._jsonl(C.AFFAIRS)}
    meta = {r["affair_id"]: r for r in C._jsonl(C.META8)}
    dls = {r["id"]: {x["letter"]: x["date"] for x in r["dates"]} for r in C._jsonl(C.DATELISTS)}
    return key, rows, meta, dls


def qwen_fields(gold: list[dict]) -> dict[str, dict[str, dict]]:
    """{packet id: {field: derived result}} from Qwen's committed labels (an unparseable label -> category 'invalid')."""
    ctx = context()
    q = {r["id"]: r for r in C._jsonl(QWEN_COMMITTED)}
    bad = dict(applicable=True, category="invalid", layer=None, reason=None, secondary={})
    out = {}
    for g in gold:
        lab = (q.get(g["id"]) or {}).get("label")
        out[g["id"]] = {}
        for f in C.FIELDS:
            if not lab:
                out[g["id"]][f] = bad
                continue
            try:
                out[g["id"]][f] = A.derive_one({k: lab.get(k) for k in C.PARTS[f]}, g["id"], ctx)[f]
            except Exception:  # noqa: BLE001 - a malformed label part is a disagreement (as eval.p8.qwen9.score)
                out[g["id"]][f] = bad
    return out


def _key(res: dict) -> str:
    return res["category"] if res["applicable"] else "n/a"


def field_result(field: str, items: list[tuple[str, dict]]) -> dict:
    pp = S.per_parliament(items, field)
    v = H.verdict(field, pp, S.pooled(pp))
    return dict(affairs=len(items), verdict=v["verdict"], n_evaluable=v["n_evaluable"], deviating=v["deviating"],
                deviation_kind=v.get("deviation_kind"), pooled_share_E=v["pooled_share_E"],
                repeated_roles={b: x["repeated_roles"] for b, x in (v.get("roles_in_deviating") or {}).items()},
                reason=v.get("reason"))


def main() -> dict:
    gold = C._jsonl(C.GOLD)
    qf = qwen_fields(gold)
    reg = json.loads((C.R8 / "p8_hypotheses.json").read_text())["fields"]
    on_qwen = json.loads((C.R8 / "p8_posthoc.json").read_text())["verdicts_on_qwen_labels"]
    qcheck = json.loads((C.R8 / "p8_qwen.json").read_text())["fields"]
    fields, consistent = {}, {}
    for f in C.FIELDS:
        same = [g for g in gold if _key(g["fields"][f]) == _key(qf[g["id"]][f])]
        same_e = [g for g in gold if (_key(g["fields"][f]) in C.E[f]) == (_key(qf[g["id"]][f]) in C.E[f])]
        consistent[f] = len(same) == qcheck[f]["agree"] and len(same_e) == qcheck[f]["gold_in_E_vs_qwen_in_E"]
        r_same = field_result(f, [(g["body"], g["fields"][f]) for g in same])
        r_e = field_result(f, [(g["body"], g["fields"][f]) for g in same_e])
        fields[f] = dict(registered=reg[f]["verdict"], registered_deviating=reg[f]["deviating"],
                         agreed_A1_A2_only=reg[f]["verdict_agreed_only"], on_qwen_labels=on_qwen[f]["verdict"],
                         gold_and_qwen_agree=dict(r_same, holds=r_same["verdict"] == reg[f]["verdict"]),
                         gold_and_qwen_agree_on_E=dict(r_e, holds=r_e["verdict"] == reg[f]["verdict"]))
    holds = [f for f in C.FIELDS if fields[f]["gold_and_qwen_agree"]["holds"]]
    out = dict(label=LABEL, proposed_by="proposed in review (an external-style review of the submission); run by the team",
               why=WHY, n_affairs=len(gold), qwen_copy_matches_p8_qwen=consistent, fields=fields,
               summary=dict(fields=len(C.FIELDS), holds=holds, n_holds=len(holds),
                            changes={f: [fields[f]["registered"], fields[f]["gold_and_qwen_agree"]["verdict"]]
                                     for f in C.FIELDS if f not in holds},
                            holds_on_E_agreement=sum(fields[f]["gold_and_qwen_agree_on_E"]["holds"] for f in C.FIELDS)))
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["export"]:
        print(json.dumps(export(), indent=1))
        sys.exit(0)
    r = main()
    for f, v in r["fields"].items():
        a, e = v["gold_and_qwen_agree"], v["gold_and_qwen_agree_on_E"]
        print(f"{f:26} registered {v['registered']:14} agree({a['affairs']:2}) {a['verdict']:14} ev {a['n_evaluable']:2} "
              f"dev {a['deviating']}  | onE({e['affairs']:2}) {e['verdict']}")
    print(r["summary"], r["qwen_copy_matches_p8_qwen"])
    sys.exit(0 if all(r["qwen_copy_matches_p8_qwen"].values()) else 1)
