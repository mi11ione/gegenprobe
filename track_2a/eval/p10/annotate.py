"""P10 gold (eval/prereg10/PREREG10.md §5): blind agent annotators list who lodged each intervention and in what role,
with eval/p10/GUIDE_P10.md (the P8 guide's authorship definitions, §2, verbatim); code checks every label against the
closed vocabularies and every quote verbatim (whitespace-insensitive) on the page it names; a third annotator decides the
packets whose two (name, role) lists differ, seeing both lists as X/Y in seeded random order.

    python -m eval.p10.annotate selfcheck <A> <id>     one file (annotators run this after writing it)
    python -m eval.p10.annotate verify <A>             every file of one annotator (A1, A2; A3 = tie-break files)
    python -m eval.p10.annotate disagreements          -> WORK/p10/disagreements.json [ids]
    python -m eval.p10.annotate a3packets              -> WORK/p10/a3/<id>.json (+ WORK/p10/a3_order.json)
    python -m eval.p10.annotate merge                  -> data/p10/p10_gold.jsonl, data/p10/annotations/*.jsonl,
                                                          data/p10/p10_key.jsonl, results/p10/p10_agreement.json

Annotator files: WORK/p10/ann/<A>/<id>.json. Two lists agree when every (name, role) pair of one matches a pair of the
other one-to-one (eval/p10/score.py `match`: same person by `convert.roles.same_person`, equal role) and both have the
same length. Gold per packet: A1's list where A1 and A2 agree, else A3's. Committed files carry no document text: every
quote is replaced by its sha256 and the resolved span (document, page, character offsets); annotators' notes stay in
WORK.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys

from eval.p8.annotate import resolve
from eval.p8.derive import toks
from eval.p10 import common as C
from eval.p10 import packets as P
from eval.p10.score import match

KEYS = ("id", "question_doc", "answer_doc", "people", "notes")
A3_KEYS = ("id", "people", "notes")


def check_people(a: dict, pid: str) -> list[str]:
    pages = P.packet_pages(pid)
    e: list[str] = []
    if not isinstance(a.get("people"), list):
        return ["people must be a list"]
    for i, p in enumerate(a["people"]):
        if not (isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"].strip()):
            e.append(f"people[{i}]: name")
            continue
        if p.get("kind") not in C.KINDS:
            e.append(f"people[{i}]: kind must be one of {C.KINDS}")
        if p.get("role") not in C.ROLES:
            e.append(f"people[{i}]: role must be one of {C.ROLES}")
        _, err = resolve(p, pages)
        if err:
            e.append(f"people[{i}]: {err}")
        last = (toks(p["name"]) or [""])[-1]
        if p.get("quote") and last and last not in toks(p["quote"]):
            e.append(f"people[{i}]: the quote does not contain the name's last word {last!r}")
    return e


def check(a: dict, pid: str, keys=KEYS) -> list[str]:
    e = []
    extra, missing = set(a) - set(keys), set(keys) - set(a)
    if extra or missing:
        e.append(f"keys: missing {sorted(missing)}, unexpected {sorted(extra)}")
    if a.get("id") != pid:
        e.append(f"id must be {pid!r}")
    if "question_doc" in keys and a.get("question_doc") not in C.QDOC:
        e.append(f"question_doc must be one of {C.QDOC}")
    if "answer_doc" in keys and a.get("answer_doc") not in C.ADOC:
        e.append(f"answer_doc must be one of {C.ADOC}")
    return e + check_people(a, pid)


def load(A: str) -> dict[str, dict]:
    d = C.ANN / A
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("P10-*.json"))} if d.exists() else {}


def verify(A: str) -> int:
    key = P.load_key()
    labs = load(A)
    ids = json.loads((C.W10 / "disagreements.json").read_text()) if A == "A3" else sorted(key)
    bad = 0
    for pid in ids:
        if pid not in labs:
            print(f"{pid}: missing")
            bad += 1
            continue
        e = check(labs[pid], pid, A3_KEYS if A == "A3" else KEYS)
        if e:
            bad += 1
            print(pid, e)
    print(f"{A}: {len(labs)} files, {bad} with problems")
    return 1 if bad else 0


def pairs(label: dict) -> list[tuple[str, str]]:
    return [(p["name"], p["role"]) for p in label.get("people") or []]


def agree(x: dict, y: dict) -> bool:
    px, py = pairs(x), pairs(y)
    return len(px) == len(py) and match(px, py)[0] == len(px)


def disagreements() -> list[str]:
    key = P.load_key()
    a1, a2 = load("A1"), load("A2")
    out = []
    for pid in sorted(key):
        if pid not in a1 or pid not in a2:
            raise SystemExit(f"{pid}: A1 or A2 label missing")
        if not agree(a1[pid], a2[pid]):
            out.append(pid)
    C.W10.mkdir(parents=True, exist_ok=True)
    (C.W10 / "disagreements.json").write_text(json.dumps(out, indent=1))
    return out


def a3packets() -> int:
    dis = disagreements()
    a1, a2 = load("A1"), load("A2")
    rnd = random.Random(C.SEED_A3)
    order = {}
    (C.W10 / "a3").mkdir(parents=True, exist_ok=True)
    for pid in dis:
        flip = rnd.random() < 0.5
        x, y = (a2[pid], a1[pid]) if flip else (a1[pid], a2[pid])
        order[pid] = "X=A2,Y=A1" if flip else "X=A1,Y=A2"
        (C.W10 / "a3" / f"{pid}.json").write_text(json.dumps(dict(
            id=pid, packet=str(C.PACK / f"{pid}.txt"), people_X=x.get("people"), people_Y=y.get("people")),
            ensure_ascii=False, indent=1))
    (C.W10 / "a3_order.json").write_text(json.dumps(order, indent=1))
    return len(dis)


def sanitize(label: dict, pid: str) -> dict:
    """The label without document text: quotes -> sha256 + resolved span; notes dropped."""
    pages = P.packet_pages(pid)
    out = {k: v for k, v in label.items() if k not in ("people", "notes")}
    out["people"] = []
    for p in label.get("people") or []:
        q = {k: v for k, v in p.items() if k != "quote"}
        span, _ = resolve(p, pages)
        q["span"] = span
        out["people"].append(q)
    return out


def merge() -> dict:
    key = P.load_key()
    a1, a2, a3 = load("A1"), load("A2"), load("A3")
    dis = json.loads((C.W10 / "disagreements.json").read_text()) if (C.W10 / "disagreements.json").exists() else None
    if dis != disagreements():
        raise SystemExit("disagreements.json is stale: run a3packets again")
    for A, labs in (("A1", a1), ("A2", a2)):
        for pid in key:
            if pid not in labs or check(labs[pid], pid):
                raise SystemExit(f"{A} {pid}: missing or failing the check")
    gold = []
    n12 = m12 = 0
    for pid in sorted(key):
        p1, p2 = pairs(a1[pid]), pairs(a2[pid])
        n12 += len(p1) + len(p2)
        m12 += 2 * match(p1, p2)[0]
        if pid in dis:
            if pid not in a3 or check(a3[pid], pid, A3_KEYS):
                raise SystemExit(f"A3 {pid}: tie-break label missing or failing the check")
            src, lab = "A3", a3[pid]
        else:
            src, lab = "A1=A2", a1[pid]
        k = key[pid]
        same_doc = a1[pid]["question_doc"] == a2[pid]["question_doc"]
        gold.append(dict(id=pid, affair_id=k["affair_id"], body=k["body"], stratum=k["stratum"], cell=k["cell"],
                         affair_type=k["affair_type"], source=src,
                         question_doc=a1[pid]["question_doc"] if same_doc else "disputed",
                         answer_doc=a1[pid]["answer_doc"] if a1[pid]["answer_doc"] == a2[pid]["answer_doc"] else "disputed",
                         people=sanitize(lab, pid)["people"]))
    C.D10.mkdir(parents=True, exist_ok=True)
    with open(C.GOLD, "w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    C.ANN_COMMITTED.mkdir(parents=True, exist_ok=True)
    for A, labs in (("A1", a1), ("A2", a2), ("A3", a3)):
        with open(C.ANN_COMMITTED / f"{A}.jsonl", "w", encoding="utf-8") as f:
            for pid in sorted(labs):
                f.write(json.dumps(sanitize(labs[pid], pid), ensure_ascii=False) + "\n")
    (C.ANN_COMMITTED / "a3_order.json").write_text((C.W10 / "a3_order.json").read_text()
                                                   if (C.W10 / "a3_order.json").exists() else "{}")
    (C.D10 / "p10_key.jsonl").write_text(C.KEY.read_text())
    res = dict(n=len(gold), packets_agreeing=len(gold) - len(dis), packets_to_a3=len(dis),
               pair_f1_A1_vs_A2=round(m12 / n12, 4) if n12 else None,
               gold_pairs=sum(len(g["people"]) for g in gold), a3_order_randomised=True,
               key_sha256=hashlib.sha256(C.KEY.read_bytes()).hexdigest())
    C.R10.mkdir(parents=True, exist_ok=True)
    (C.R10 / "p10_agreement.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selfcheck":
        A, pid = sys.argv[2], sys.argv[3]
        lab = json.loads((C.ANN / A / f"{pid}.json").read_text(encoding="utf-8"))
        err = check(lab, pid, A3_KEYS if A == "A3" else KEYS)
        print("OK" if not err else "ERRORS:\n- " + "\n- ".join(err))
        sys.exit(1 if err else 0)
    elif cmd == "verify":
        sys.exit(verify(sys.argv[2]))
    elif cmd == "disagreements":
        print(json.dumps(disagreements(), indent=1))
    elif cmd == "a3packets":
        print(a3packets(), "tie-break packets")
    elif cmd == "merge":
        print(json.dumps(merge(), indent=1))
    else:
        print(__doc__)
