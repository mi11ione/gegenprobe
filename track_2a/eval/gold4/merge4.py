"""P4 labels: two blind annotators per meeting (A1, A2), a third (A3) on disputed items only, in seeded random X/Y order.

  disagreements          -> .work/gold4/a3/<meeting>.json  (disputed items with both labels as X/Y; order key kept apart)
  merge                  -> data/gold4/p4_heldout_labels.jsonl, data/gold4/annotations/{A1,A2,A3}.jsonl,
                            results/eval4/gold4_agreement.json

Items are aligned by the agenda number `no`. An item is disputed when the annotators differ on `type` or `decision`, or
when only one of them lists it. Agreed items take A1's label (the two are equal on everything scored).
"""
from __future__ import annotations

import json
import random
import sys

from gegenprobe.paths import DATA, RESULTS, WORK
from gegenprobe.stats import cohen_kappa

G = WORK / "gold4"
ANN = G / "ann"
SEED = 20261014


def load(a: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted((ANN / a).glob("*.json"))}


def items(m: dict) -> dict[str, dict]:
    return {str(it["no"]).strip(): it for it in m.get("items", [])}


def key(it: dict | None):
    return None if it is None else (it.get("type"), it.get("decision"))


def disputed() -> dict[str, list[str]]:
    a1, a2 = load("A1"), load("A2")
    out = {}
    for mid in sorted(set(a1) & set(a2)):
        i1, i2 = items(a1[mid]), items(a2[mid])
        d = [n for n in sorted(set(i1) | set(i2), key=lambda s: [int(x) if x.isdigit() else x for x in s.split(".")])
             if key(i1.get(n)) != key(i2.get(n))]
        if d:
            out[mid] = d
    return out


def disagreements() -> None:
    a1, a2 = load("A1"), load("A2")
    rng = random.Random(SEED)
    (G / "a3").mkdir(parents=True, exist_ok=True)
    order = {}
    for mid, nos in disputed().items():
        i1, i2 = items(a1[mid]), items(a2[mid])
        rows = []
        for n in nos:
            pair = [("A1", i1.get(n)), ("A2", i2.get(n))]
            rng.shuffle(pair)
            order[f"{mid}:{n}"] = [p[0] for p in pair]
            rows.append(dict(no=n, label_X=pair[0][1], label_Y=pair[1][1]))
        (G / "a3" / f"{mid}.json").write_text(json.dumps(dict(meeting=mid, disputed=rows), ensure_ascii=False, indent=1))
    (G / "a3_order.json").write_text(json.dumps(order, indent=1))
    print(f"{sum(len(v) for v in disputed().values())} disputed items in {len(order and disputed())} meetings")


def merge() -> None:
    a1, a2, a3 = load("A1"), load("A2"), load("A3")
    rows, kt, kd, by_a3 = [], ([], []), ([], []), 0
    missing = []
    for mid in sorted(set(a1) & set(a2)):
        i1, i2 = items(a1[mid]), items(a2[mid])
        i3 = items(a3[mid]) if mid in a3 else {}
        for n in sorted(set(i1) | set(i2), key=lambda s: [int(x) if x.isdigit() else x for x in s.split(".")]):
            x, y = i1.get(n), i2.get(n)
            if x and y:
                kt[0].append(str(x.get("type")))
                kt[1].append(str(y.get("type")))
                kd[0].append(str(x.get("decision")))
                kd[1].append(str(y.get("decision")))
            if key(x) == key(y):
                lab, src = x, "A1=A2"
            elif n in i3:
                lab, src = i3[n], "A3"
                by_a3 += 1
            else:
                missing.append(f"{mid}:{n}")
                continue
            if lab is None or lab.get("drop"):
                continue  # A3 decided the item does not exist in the agenda
            rows.append(dict(meeting=mid, no=n, title_quote=lab.get("title_quote"), type=lab.get("type"),
                             decision=lab.get("decision"), decision_page=lab.get("decision_page"),
                             decision_quote=(lab.get("decision_quote") or None), labeller=f"claude-agents:{src}"))
    if missing:
        raise SystemExit(f"tie-break missing for {missing}")
    with open(DATA / "gold4" / "p4_heldout_labels.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (DATA / "gold4" / "annotations").mkdir(parents=True, exist_ok=True)
    for a, d in (("A1", a1), ("A2", a2), ("A3", a3)):
        with open(DATA / "gold4" / "annotations" / f"{a}.jsonl", "w") as f:
            for mid, m in sorted(d.items()):
                f.write(json.dumps(dict(m, meeting=mid), ensure_ascii=False) + "\n")
    res = dict(n_items=len(rows), meetings=len(set(a1) & set(a2)), decided_by_A3=by_a3, a3_order_randomised=True,
               agreement=dict(type=dict(raw=sum(p == q for p, q in zip(*kt)), n=len(kt[0]), kappa=cohen_kappa(*kt)),
                              decision=dict(raw=sum(p == q for p, q in zip(*kd)), n=len(kd[0]), kappa=cohen_kappa(*kd))))
    (RESULTS / "eval4").mkdir(parents=True, exist_ok=True)
    (RESULTS / "eval4" / "gold4_agreement.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"disagreements": disagreements, "merge": merge}[sys.argv[1]]()
