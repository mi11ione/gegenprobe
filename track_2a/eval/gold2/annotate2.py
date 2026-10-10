"""P2 annotation: the frozen P1 protocol (eval/gold/annotate.py, LOCK 812030f) pointed at the P2 paths, plus one change
registered in PREREG2: the two labels shown to the tie-break annotator A3 are in a seeded random X/Y order.

  packets               .work/gold2/packets/<doc_id>.txt + index.json (page-delimited text, never committed)
  verify <A1|A2|A3>     schema, ISO dates, verbatim quote on the stated page (the P1 check function)
  selfcheck <A> <id>    one file (annotators run this)
  disagreements         -> .work/gold2/disagreements.json
  a3packets             -> .work/gold2/a3/<doc_id>.json with labels as X/Y in seeded random order; the order key stays in
                           .work/gold2/a3_order.json (A3 never sees it)
  merge                 -> data/gold2/p2_labels.jsonl, results/eval2/gold2_agreement.json
"""

from __future__ import annotations

import collections
import json
import random
import sys

from eval.gold import annotate as A
from gegenprobe.paths import DATA, RESULTS, WORK
from gegenprobe.stats import cohen_kappa

SEED = 20261011
G2 = WORK / "gold2"
A.G, A.PACK, A.ANN = G2, G2 / "packets", G2 / "ann"


def p2_docs() -> list[dict]:
    return [json.loads(line) for line in open(DATA / "gold2" / "p2_docs.jsonl")]


A.heldout_docs = p2_docs  # every frozen helper (packets, verify, check) now reads the P2 document list


def a3packets() -> list[int]:
    diff = A.disagreements()
    rnd = random.Random(SEED)
    order = {}
    (G2 / "a3").mkdir(parents=True, exist_ok=True)
    a1, a2 = A.load("A1"), A.load("A2")
    for i in diff:
        flip = rnd.random() < 0.5
        x, y = (a2[i], a1[i]) if flip else (a1[i], a2[i])
        order[i] = "X=A2,Y=A1" if flip else "X=A1,Y=A2"
        (G2 / "a3" / f"{i}.json").write_text(json.dumps(dict(doc_id=i, label_X=x, label_Y=y), ensure_ascii=False, indent=1))
    (G2 / "a3_order.json").write_text(json.dumps(order, indent=1))
    return diff


def merge() -> dict:
    docs = {d["doc_id"]: d for d in p2_docs()}
    a1, a2, a3 = A.load("A1"), A.load("A2"), A.load("A3")
    ids = sorted(set(a1) & set(a2))
    agree = {}
    for f in ("answer_present", "answer_date", "recommendation"):
        x, y = [str(a1[i][f]) for i in ids], [str(a2[i][f]) for i in ids]
        agree[f] = dict(raw=sum(p == q for p, q in zip(x, y)), n=len(ids), kappa=cohen_kappa(x, y))
    rows, missing = [], []
    for i in ids:
        if A.key(a1[i]) == A.key(a2[i]):
            lab, src = a1[i], "A1=A2"
        elif i in a3:
            lab, src = a3[i], "A3"
        else:
            missing.append(i)
            continue
        d = docs[i]
        len_ = sorted(
            set((a1[i].get("answer_date_lenient") or []) + (a2[i].get("answer_date_lenient") or []))
            | ({a1[i]["answer_date"], a2[i]["answer_date"]} - {None, lab["answer_date"]})
        )
        rows.append(
            dict(
                doc_id=i,
                source="heldout",
                cell=d["cell"],
                dtype=d["dtype"],
                body=d["body"],
                labeller=f"claude-agents:{src}",
                answer_present=lab["answer_present"],
                answer_date=lab["answer_date"],
                role=lab.get("role"),
                answer_date_page=lab.get("answer_date_page"),
                answer_date_quote=(lab.get("answer_date_quote") or "")[:200],
                answer_date_lenient=[x for x in len_ if x],
                decision_number=lab.get("decision_number"),
                recommendation=lab["recommendation"],
            )
        )
    if missing:
        raise SystemExit(f"tie-break missing for {missing}")
    (DATA / "gold2").mkdir(parents=True, exist_ok=True)
    with open(DATA / "gold2" / "p2_labels.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    oracle = A.opd_answer_dates({d["affair_id"] for d in docs.values() if d.get("affair_id")})
    ext, mism = collections.Counter(), []
    for r in rows:
        od = oracle.get(docs[r["doc_id"]].get("affair_id")) or []
        if r["answer_date"] and od:
            ok = r["answer_date"] in od
            ext["match" if ok else "mismatch"] += 1
            if not ok:
                mism.append(dict(doc_id=r["doc_id"], label=r["answer_date"], opd=od, quote=r["answer_date_quote"]))
        elif r["answer_date"]:
            ext["no_oracle"] += 1
    res = dict(
        n=len(rows),
        agreement=agree,
        decided_by_A3=sum(r["labeller"].endswith("A3") for r in rows),
        a3_order_randomised=True,
        oracle=dict(ext),
        oracle_mismatches=mism,
    )
    (RESULTS / "eval2").mkdir(parents=True, exist_ok=True)
    (RESULTS / "eval2" / "gold2_agreement.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "packets":
        A.packets()
    elif cmd == "verify":
        sys.exit(A.verify(sys.argv[2]))
    elif cmd == "selfcheck":
        a = json.loads((A.ANN / sys.argv[2] / f"{sys.argv[3]}.json").read_text())
        e = A.check(a)
        print("OK" if not e else f"ERRORS: {e}")
        sys.exit(1 if e else 0)
    elif cmd == "disagreements":
        A.disagreements()
    elif cmd == "a3packets":
        print(len(a3packets()), "tie-break packets")
    elif cmd == "merge":
        print(json.dumps({k: v for k, v in merge().items() if k != "oracle_mismatches"}, indent=1))
