"""Federal cell gold labels (eval/fed/PROTOCOL.md §5): the P8 annotation tooling (eval/p8/annotate.py, frozen by LOCK9)
pointed at the federal packets, as eval/gold2/annotate2.py points the P1 tooling at P2; the answer-date part is checked
by the P1 rules (eval/gold/annotate.py `check`: ISO date, role decision|dispatch, verbatim quote on the stated page,
<= 200 characters), with the quote resolved on the answer document by P8's resolver.

    python -m eval.fed.annotate selfcheck <A> <id>     one file (annotators run this after writing it)
    python -m eval.fed.annotate verify <A>             every file of one annotator (A1, A2; A3 = tie-break files)
    python -m eval.fed.annotate disagreements          -> WORK/fed/disagreements.json {id: [fields]}
    python -m eval.fed.annotate a3packets              -> WORK/fed/a3/<id>.json (+ WORK/fed/a3_order.json)
    python -m eval.fed.annotate merge                  -> data/fed/fed_gold.jsonl, data/fed/annotations/*.jsonl,
                                                          data/fed/fed_key.jsonl, results/fed/fed_agreement.json

Fields and their disagreement keys: answer_date (the printed date or null, P1's key), submitter, type, language (P8's
derived category, computed with OPD's metadata, which the annotators never see). Committed files carry no text: every
quote is replaced by its sha256 and the resolved span; notes stay in WORK.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys

from eval.fed import common as C
from eval.p8 import annotate as A8
from eval.p8 import common as C8
from eval.p8 import derive as Dv
from eval.p8 import packets as P8P
from gegenprobe.stats import cohen_kappa

# the frozen P8 helpers read their packets and date lists through eval.p8.common: point them at the federal files
C8.PACK, C8.DATELISTS = C.PACK, C.DATELISTS

KEYS = ("id", "question_doc", "answer_doc", "people", "function", "instrument_named", "languages", "answer_present",
        "answer_date", "role", "answer_date_page", "answer_date_quote", "answer_date_lenient", "notes")
P8_PARTS = ("question_doc", "answer_doc", "people", "function", "instrument_named", "languages")
AD_PARTS = ("answer_present", "answer_date", "role", "answer_date_page", "answer_date_quote", "answer_date_lenient")
FIELDS = ("answer_date", "submitter", "type", "language")
PARTS = {"answer_date": AD_PARTS, "submitter": ("people",), "type": ("function", "instrument_named"),
         "language": ("languages",)}
PRESENT = ("yes", "no", "oral", "unclear")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------------------------------------ checks
def check_answer_date(a: dict, pid: str) -> list[str]:
    """P1's rules for the answer-date part (eval/gold/annotate.py `check`), on the packet's answer document."""
    e = []
    if a.get("answer_present") not in PRESENT:
        e.append(f"answer_present must be one of {PRESENT}")
    v = a.get("answer_date")
    if v is not None:
        if a.get("answer_present") != "yes":
            e.append("answer_date must be null unless answer_present is 'yes'")
        if not ISO.match(str(v)):
            e.append("answer_date must be YYYY-MM-DD")
        if a.get("role") not in ("decision", "dispatch"):
            e.append("role must be 'decision' or 'dispatch' when an answer date is given")
        span, err = A8.resolve(dict(doc="answer", page=a.get("answer_date_page"), quote=a.get("answer_date_quote")),
                               P8P.packet_pages(pid))
        if err:
            e.append(f"answer_date: {err}")
    else:
        for k in ("role", "answer_date_page", "answer_date_quote"):
            if a.get(k) is not None:
                e.append(f"{k} must be null when answer_date is null")
    if not isinstance(a.get("answer_date_lenient"), list) or not all(ISO.match(str(x)) for x in a["answer_date_lenient"]):
        e.append("answer_date_lenient must be a list of YYYY-MM-DD")
    return e


def check_parts(a: dict, pid: str, parts: tuple[str, ...]) -> list[str]:
    e = A8.check_parts(a, pid, tuple(p for p in parts if p in P8_PARTS))
    if any(p in AD_PARTS for p in parts):
        e += check_answer_date(a, pid)
    return e


def check(a: dict, pid: str) -> list[str]:
    e = []
    extra, missing = set(a) - set(KEYS), set(KEYS) - set(a)
    if extra or missing:
        e.append(f"keys: missing {sorted(missing)}, unexpected {sorted(extra)}")
    if a.get("id") != pid:
        e.append(f"id must be {pid!r}")
    return e + check_parts(a, pid, P8_PARTS + AD_PARTS)


def ann_dir(A: str):
    return C.ANN / A


def load(A: str) -> dict[str, dict]:
    d = ann_dir(A)
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("FED-*.json"))} if d.exists() else {}


def load_key() -> dict[str, dict]:
    return {r["id"]: r for r in C8._jsonl(C.KEY)}


def _disputed() -> dict[str, list[str]]:
    p = C.WF / "disagreements.json"
    return json.loads(p.read_text()) if p.exists() else {}


def verify(A: str) -> int:
    key, labs, bad = load_key(), load(A), 0
    todo = {pid: tuple(sorted({p for f in fs for p in PARTS[f]})) for pid, fs in _disputed().items()} if A == "A3" \
        else {pid: None for pid in key}
    for pid in sorted(todo):
        if pid not in labs:
            print(f"{pid}: missing")
            bad += 1
            continue
        e = check_parts(labs[pid], pid, todo[pid]) if A == "A3" else check(labs[pid], pid)
        if e:
            bad += 1
            print(pid, e)
    print(f"{A}: {len(labs)} files, {bad} with problems")
    return 1 if bad else 0


# ------------------------------------------------------------------------------------------------ derived categories
def entry_of(k: dict) -> dict:
    """The P8 derivation's view of one federal affair: OPD's harmonised type, and as OPD's language tag of each document
    the language slot the texts come from (the slot is how OPD labels a federal text's language)."""
    return dict(affair_type=k["affair_type"], docs=[dict(role="question", opd_lang=k["stratum"]),
                                                    dict(role="answer", opd_lang=k["stratum"])])


def context():
    key = load_key()
    meta = {r["affair_id"]: r for r in C8._jsonl(C.META)}
    return key, meta


def derive_one(label: dict, pid: str, ctx) -> dict[str, dict]:
    key, meta = ctx
    k = key[pid]
    m = meta.get(k["affair_id"])
    e = entry_of(k)
    v = label.get("answer_date")
    return {"answer_date": dict(applicable=True, category=v if v is not None else "null", role=label.get("role"),
                                answer_present=label.get("answer_present")),
            "submitter": Dv.submitter(label, m), "type": Dv.type_(label, e), "language": Dv.language(label, e)}


def fkey(res: dict) -> str:
    return Dv.key(res)


def disagreements() -> dict[str, list[str]]:
    ctx = context()
    a1, a2 = load("A1"), load("A2")
    out = {}
    for pid in sorted(ctx[0]):
        if pid not in a1 or pid not in a2:
            raise SystemExit(f"{pid}: A1 or A2 label missing")
        d1, d2 = derive_one(a1[pid], pid, ctx), derive_one(a2[pid], pid, ctx)
        diff = [f for f in FIELDS if fkey(d1[f]) != fkey(d2[f])]
        if diff:
            out[pid] = diff
    C.WF.mkdir(parents=True, exist_ok=True)
    (C.WF / "disagreements.json").write_text(json.dumps(out, indent=1))
    return out


def a3packets() -> int:
    dis = disagreements()
    a1, a2 = load("A1"), load("A2")
    rnd = random.Random(C.SEED_A3)
    order = {}
    (C.WF / "a3").mkdir(parents=True, exist_ok=True)
    for pid in sorted(dis):
        parts = sorted({p for f in dis[pid] for p in PARTS[f]})
        flip = rnd.random() < 0.5
        x, y = (a2[pid], a1[pid]) if flip else (a1[pid], a2[pid])
        order[pid] = "X=A2,Y=A1" if flip else "X=A1,Y=A2"
        (C.WF / "a3" / f"{pid}.json").write_text(json.dumps(dict(
            id=pid, packet=str(C.PACK / f"{pid}.txt"), fields=dis[pid], parts=parts,
            label_X={k: x.get(k) for k in parts}, label_Y={k: y.get(k) for k in parts}), ensure_ascii=False, indent=1))
    (C.WF / "a3_order.json").write_text(json.dumps(order, indent=1))
    return len(dis)


# ------------------------------------------------------------------------------------------------ merge
def sanitize(label: dict, pid: str) -> dict:
    """The label without text: P8's sanitiser, and the answer-date quote replaced by its sha256 and resolved span."""
    out = A8.sanitize({k: v for k, v in label.items() if k != "answer_date_quote"}, pid)
    q = label.get("answer_date_quote")
    if q:
        span, _ = A8.resolve(dict(doc="answer", page=label.get("answer_date_page"), quote=q), P8P.packet_pages(pid))
        out["answer_date_span"] = span
    return out


def merge() -> dict:
    ctx = context()
    key = ctx[0]
    a1, a2, a3 = load("A1"), load("A2"), load("A3")
    dis = _disputed()
    if dis != disagreements():
        raise SystemExit("disagreements.json is stale: run a3packets again")
    for A, labs in (("A1", a1), ("A2", a2)):
        for pid in key:
            if pid not in labs or check(labs[pid], pid):
                raise SystemExit(f"{A} {pid}: missing or failing the check")
    gold, agree = [], {f: dict(x=[], y=[]) for f in FIELDS}
    for pid in sorted(key):
        d1, d2 = derive_one(a1[pid], pid, ctx), derive_one(a2[pid], pid, ctx)
        fields, parts = {}, {}
        for f in FIELDS:
            agree[f]["x"].append(fkey(d1[f]))
            agree[f]["y"].append(fkey(d2[f]))
            if f in dis.get(pid, []):
                if pid not in a3 or check_parts(a3[pid], pid, PARTS[f]):
                    raise SystemExit(f"A3 {pid}: tie-break label for {f} missing or failing the check")
                src, lab = "A3", a3[pid]
            else:
                src, lab = "A1=A2", a1[pid]
            sub = {k: lab.get(k) for k in PARTS[f]}
            fields[f] = dict(source=src, **derive_one(sub, pid, ctx)[f])
            if f == "answer_date":
                g = sub.get("answer_date")
                fields[f]["lenient"] = sorted(
                    {x for x in (a1[pid].get("answer_date_lenient") or []) + (a2[pid].get("answer_date_lenient") or [])}
                    | ({a1[pid]["answer_date"], a2[pid]["answer_date"]} - {None, g}))
            parts[f] = sanitize(sub, pid)
        k = key[pid]
        gold.append(dict(id=pid, affair_id=k["affair_id"], stratum=k["stratum"], group=k["group"], cell=k["cell"],
                         affair_type=k["affair_type"],
                         question_doc=a1[pid]["question_doc"] if a1[pid]["question_doc"] == a2[pid]["question_doc"]
                         else "disputed",
                         answer_doc=a1[pid]["answer_doc"] if a1[pid]["answer_doc"] == a2[pid]["answer_doc"] else "disputed",
                         fields=fields, parts=parts))
    C.DF.mkdir(parents=True, exist_ok=True)
    with open(C.GOLD, "w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    C.ANN_COMMITTED.mkdir(parents=True, exist_ok=True)
    for A, labs in (("A1", a1), ("A2", a2), ("A3", a3)):
        with open(C.ANN_COMMITTED / f"{A}.jsonl", "w", encoding="utf-8") as f:
            for pid in sorted(labs):
                f.write(json.dumps(sanitize(labs[pid], pid), ensure_ascii=False) + "\n")
    order = C.WF / "a3_order.json"
    (C.ANN_COMMITTED / "a3_order.json").write_text(order.read_text() if order.exists() else "{}")
    (C.DF / "fed_key.jsonl").write_text(C.KEY.read_text())
    res = dict(n=len(gold), disputed_packets=len(dis), disputed_fields=sum(len(v) for v in dis.values()),
               fields={f: dict(raw=sum(x == y for x, y in zip(v["x"], v["y"])), n=len(v["x"]),
                               kappa=round(cohen_kappa(v["x"], v["y"]), 3),
                               decided_by_A3=sum(f in dis.get(pid, []) for pid in key))
                       for f, v in agree.items()},
               a3_order_randomised=True,
               key_sha256=hashlib.sha256(C.KEY.read_bytes()).hexdigest())
    C.RF.mkdir(parents=True, exist_ok=True)
    (C.RF / "fed_agreement.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selfcheck":
        A, pid = sys.argv[2], sys.argv[3]
        lab = json.loads((ann_dir(A) / f"{pid}.json").read_text(encoding="utf-8"))
        if A == "A3":
            err = check_parts(lab, pid, tuple(sorted({p for f in _disputed().get(pid, []) for p in PARTS[f]})))
        else:
            err = check(lab, pid)
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
