"""POST HOC (11 Oct 2026; proposed in review; not pre-registered): positional no-model baselines for P10 and the closure
of P10's role set. No registered decision depends on this file; the four registered verdicts stand as LOCK10 fixed them.
No model call, no network, no text: committed files only (results/p10/p10_arms.jsonl, data/p10/p10_candidates.jsonl,
results/p10/p10_pointer.jsonl, data/p10/p10_gold.jsonl, data/p10/annotations/).

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.posthoc_baselines   -> results/p10/p10_posthoc_baselines.json

Why. The registered H3b baseline reads the shared candidates with a trivial role: one candidate -> sole author, several
-> every candidate joint author (eval/p10/arms.py `cand_joint_pairs`). For OPD's contributor list the registration also
scored the 'first_and_co' reading (`opd_pairs`: the first author-like contributor first signatory, the rest
co-signatories). A reviewer proposed applying that same registered reading to the code's candidates, in document order.

Arms added here (each scored by the registered scorer, eval.p10.score: `affair_row`, `pooled`, greedy one-to-one match):
  cand_order       the registered OPD mapping `eval.p10.arms.opd_pairs(..., "first_and_co")` applied to the committed
                   candidates in their committed order (document order: question before answer, page, character):
                   one candidate -> sole_author; several -> the first first_signatory, the rest co_signatory.
  cand_order_fc    the variant without the sole-author case: the first candidate is always first_signatory, the rest
                   co_signatory (one candidate -> first_signatory).
  cand_order_pers  cand_order on person candidates only (groups dropped when a person exists); the reviewer's second row.
  pointer_order    composition, reported but not promoted: the people the Apertus pointer printed (its author / not-author
                   decision, results/p10/p10_pointer.jsonl) re-roled by document order with the same `opd_pairs` mapping.
Comparisons (primary cell, as the registered family): pooled precision / recall / F1, affairs exact, per parliament;
per-affair wins / losses / ties of the pointer against each arm (matched pairs; and per-affair F1), and of pointer_order
against cand_order (what the author / not-author decision adds under the same role rule); paired
parliament-cluster bootstrap of the pointer-minus-arm differences in precision, recall and F1 (the registered resampling:
`eval.p10.score.bootstrap`'s procedure, seed SEED_BOOT, N_BOOT = 10,000 resamples), with the one-sided p of the registered
form (1 + #{diff <= 0}) / (B + 1) for "first arm ahead" (p_first_ahead) and the mirror p (p_arm_ahead). `display` holds
the differences in percentage points for the documents.

Role set (also post hoc, proposed in review): how many people of the merged gold, and of each annotator's file, carry
the guide's open `other` role (eval/p10/GUIDE_P10.md: "a role ... that fits none of the above") and the unused
`supporter` role; the open `other_body` kind likewise.
"""

from __future__ import annotations

import collections
import json
import random
import sys

from eval.p10 import arms as A
from eval.p10 import common as C
from eval.p10 import score as S

LABEL = ("POST HOC (11 Oct 2026; proposed in review; not pre-registered): no registered decision depends on this file; "
         "P10's registered verdicts (H1, H2, H3b confirmed; H3a not confirmed) are unchanged")
OUT = C.R10 / "p10_posthoc_baselines.json"
NEW_ARMS = ("cand_order", "cand_order_fc", "cand_order_pers", "pointer_order")
COMPARE = ("cand_order", "cand_order_fc", "cand_order_pers", "pointer_order", "opd_first", "cand_joint", "rules")


def _pos(c: dict) -> tuple:
    return (0 if c["doc"] == "question" else 1, c["page"], c["char_start"])


def as_opd_meta(names: list[str]) -> dict:
    """Names in order as an OPD contributor list of author-like contributors (the input `opd_pairs` reads)."""
    return {"contributors": [{"type": "person", "fullname": n, "role_harmonized": "author"} for n in names]}


def order_pairs(names: list[str]) -> list[tuple[str, str]]:
    """The registered OPD 'first_and_co' mapping applied to `names` in the order given."""
    return [tuple(x) for x in A.opd_pairs(as_opd_meta(names), "first_and_co")] if names else []


def order_pairs_fc(names: list[str]) -> list[tuple[str, str]]:
    if not names:
        return []
    return [(names[0], "first_signatory")] + [(n, "co_signatory") for n in names[1:]]


def cand_names(cands: list[dict], persons_only: bool = False) -> list[str]:
    cs = sorted(cands, key=_pos)
    if persons_only:
        cs = [c for c in cs if c["kind"] == "person"] or cs
    return [c["value"] for c in cs]


def pointer_names(res: dict) -> list[str]:
    """The pointer's printed people (its author decision), in document order of their located span."""
    acts = sorted(res["actors"], key=lambda x: _pos(x["name"]))
    return [x["name"]["value"] for x in acts]


def add_arms(rows: list[dict], cands: dict, ptr: dict) -> list[dict]:
    out = []
    for r in rows:
        cs = cands[r["affair_id"]]["candidates"]
        gold = [tuple(x) for x in r["gold"]]
        pn = pointer_names(ptr[r["affair_id"]]["result"]) if r["affair_id"] in ptr else []
        pred = dict(cand_order=order_pairs(cand_names(cs)), cand_order_fc=order_pairs_fc(cand_names(cs)),
                    cand_order_pers=order_pairs(cand_names(cs, True)), pointer_order=order_pairs(pn))
        rr = dict(r, pred=dict(r["pred"], **pred), arms=dict(r["arms"]))
        for k, v in pred.items():
            rr["arms"][k] = S.affair_row(v, gold)
        out.append(rr)
    return out


def _f1_aff(a: dict) -> float:
    p = a["m_role"] / a["n_pred"] if a["n_pred"] else 0.0
    r = a["m_role"] / a["n_gold"] if a["n_gold"] else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def paired(rows: list[dict], arm: str, seed: int, n_boot: int, first: str = "pointer") -> dict:
    """`first` (default: the pointer) against `arm`: per-affair wins/losses/ties and the paired parliament-cluster bootstrap."""
    w = dict(by_matched_pairs=collections.Counter(), by_affair_f1=collections.Counter())
    for r in rows:
        a, b = r["arms"][first], r["arms"][arm]
        d = a["m_role"] - b["m_role"]
        w["by_matched_pairs"]["first_ahead" if d > 0 else "arm_ahead" if d < 0 else "tie"] += 1
        e = _f1_aff(a) - _f1_aff(b)
        w["by_affair_f1"]["first_ahead" if e > 1e-12 else "arm_ahead" if e < -1e-12 else "tie"] += 1

    def diffs(rs):
        x, y = S.pooled(rs, first), S.pooled(rs, arm)
        return {k: (None if x[k] is None or y[k] is None else x[k] - y[k]) for k in ("precision", "recall", "f1")}

    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["body"], []).append(r)
    bodies = sorted(by)
    rnd = random.Random(seed)
    bs = {k: [] for k in ("precision", "recall", "f1")}
    for _ in range(n_boot):
        pick = [rnd.choice(bodies) for _ in bodies]
        d = diffs([r for b in pick for r in by[b]])
        for k, v in d.items():
            if v is not None:
                bs[k].append(v)
    obs = diffs(rows)
    boot = {}
    for k, xs in bs.items():
        boot[k] = dict(observed=obs[k], ci95=[S._pct(xs, 0.025), S._pct(xs, 0.975)], n=len(xs),
                       p_first_ahead=(1 + sum(x <= 0 for x in xs)) / (len(xs) + 1),
                       p_arm_ahead=(1 + sum(x >= 0 for x in xs)) / (len(xs) + 1))
    # gold pairs found by exactly one of the two (exact McNemar, two-sided)
    b = c = 0
    for r in rows:
        hp, ha = set(r["arms"][first]["gold_hit"]), set(r["arms"][arm]["gold_hit"])
        b += len(hp - ha)
        c += len(ha - hp)
    p2 = min(1.0, 2 * min(S.mcnemar_exact(b, c), S.mcnemar_exact(c, b)))
    return dict(first=first, arm=arm, affairs=len(rows), wins_losses_ties={k: dict(v) for k, v in w.items()},
                cluster_bootstrap_first_minus_arm=boot,
                gold_pairs_found_by_one=dict(first_only=b, arm_only=c, p_exact_two_sided=p2))


def _by_body(per_body: dict, a: str, b: str) -> dict:
    """Parliaments where `a` matches more / fewer / as many gold pairs as `b` (primary cell)."""
    out: dict[str, list[str]] = {"first_ahead": [], "arm_ahead": [], "tie": []}
    for body, v in per_body.items():
        d = v[a]["matched"] - v[b]["matched"]
        out["first_ahead" if d > 0 else "arm_ahead" if d < 0 else "tie"].append(body)
    return dict(first=a, arm=b, counts={k: len(v) for k, v in out.items()}, **out)


def role_set() -> dict:
    gold = C._jsonl(C.GOLD)
    people = [p for g in gold for p in g["people"]]
    out = dict(gold=dict(affairs=len(gold), parliaments=len({g["body"] for g in gold}), people=len(people),
                         roles=dict(collections.Counter(p["role"] for p in people).most_common()),
                         kinds=dict(collections.Counter(p["kind"] for p in people).most_common()),
                         other_role=sum(p["role"] == "other" for p in people),
                         supporter_role=sum(p["role"] == "supporter" for p in people),
                         other_body_kind=sum(p["kind"] == "other_body" for p in people),
                         roles_used=sorted({p["role"] for p in people}),
                         roles_offered=list(C.ROLES)))
    ann = {}
    for f in sorted(C.ANN_COMMITTED.glob("*.jsonl")):
        rs = C._jsonl(f)
        ps = [p for r in rs for p in r.get("people") or []]
        ann[f.stem] = dict(packets=len(rs), people=len(ps), other_role=sum(p.get("role") == "other" for p in ps),
                           supporter_role=sum(p.get("role") == "supporter" for p in ps),
                           roles_outside_vocabulary=sum(p.get("role") not in C.ROLES for p in ps))
    out["annotators"] = ann
    return out


def main() -> dict:
    rows = C._jsonl(C.ARMS)
    cands = {r["affair_id"]: r for r in C._jsonl(C.CANDS10)}
    ptr = {r["affair_id"]: r for r in C._jsonl(C.R10 / "p10_pointer.jsonl")}
    rows = add_arms(rows, cands, ptr)
    prim = [r for r in rows if r["cell"] == "primary"]
    sec = [r for r in rows if r["cell"] != "primary"]
    arms = ("pointer",) + COMPARE
    per_body = {b: {a: S.pooled([r for r in prim if r["body"] == b], a) for a in arms}
                for b in sorted({r["body"] for r in prim})}
    out = dict(
        label=LABEL, proposed_by="proposed in review (an external-style review of the submission); run by the team",
        mapping="eval.p10.arms.opd_pairs(..., 'first_and_co') on the candidates in document order; not tuned on the gold",
        seed=C.SEED_BOOT, n_boot=C.N_BOOT,
        primary=dict(affairs=len(prim), gold_pairs=sum(r["arms"]["pointer"]["n_gold"] for r in prim),
                     arms={a: S.pooled(prim, a) for a in arms},
                     per_parliament=per_body,
                     paired={a: paired(prim, a, C.SEED_BOOT, C.N_BOOT) for a in COMPARE},
                     # what Apertus's author / not-author decision adds when document order assigns the roles
                     author_filter=paired(prim, "cand_order", C.SEED_BOOT, C.N_BOOT, first="pointer_order")),
        secondary_it=dict(affairs=len(sec), arms={a: S.pooled(sec, a) for a in arms}),
        role_set=role_set())
    pa = out["primary"]["arms"]
    out["summary"] = dict(
        pointer=[pa["pointer"]["matched"], pa["pointer"]["pairs_predicted"]],
        cand_order=[pa["cand_order"]["matched"], pa["cand_order"]["pairs_predicted"]],
        pointer_ahead_on={k: pa["pointer"][k] > pa["cand_order"][k] for k in ("precision", "recall", "f1")},
        parliaments_by_matched_pairs=_by_body(per_body, "pointer", "cand_order"))

    def pts(x):
        return round(100 * x, 1)

    disp = {}
    for name, blk in (("pointer_vs_cand_order", out["primary"]["paired"]["cand_order"]),
                      ("pointer_vs_pointer_order", out["primary"]["paired"]["pointer_order"]),
                      ("author_filter", out["primary"]["author_filter"])):
        bt = blk["cluster_bootstrap_first_minus_arm"]
        disp[name] = {k: dict(pts=pts(bt[k]["observed"]), ci_pts=[pts(v) for v in bt[k]["ci95"]],
                              p_first_ahead=f'{bt[k]["p_first_ahead"]:.3f}') for k in bt}
    out["display"] = disp
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    r = main()
    pa = r["primary"]["arms"]
    for a in ("pointer",) + COMPARE:
        x = pa[a]
        print(f"{a:16} {x['matched']:3}/{x['pairs_gold']} pred {x['pairs_predicted']:3} P {x['precision']:.3f} "
              f"R {x['recall']:.3f} F1 {x['f1']:.3f} exact {x['affairs_exact']}")
    for a, v in list(r["primary"]["paired"].items()) + [("author_filter", r["primary"]["author_filter"])]:
        bt = v["cluster_bootstrap_first_minus_arm"]
        print(a, v["wins_losses_ties"], {k: (round(bt[k]["observed"], 3), [round(z, 3) for z in bt[k]["ci95"]])
                                          for k in bt}, v["gold_pairs_found_by_one"])
    print(json.dumps(r["role_set"], indent=1))
    sys.exit(0)
