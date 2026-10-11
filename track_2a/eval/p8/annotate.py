"""P8 gold labels (eval/prereg9/PREREG9.md §5): blind agent annotators label each packet with eval/p8/GUIDE_P8.md; code
checks every label against the closed vocabularies and every quote verbatim (whitespace-insensitive) on the page it names;
a third annotator decides the fields whose derived category differs, seeing both labels as X/Y in seeded random order.

    python -m eval.p8.annotate selfcheck <A> <id>     one file (annotators run this after writing it)
    python -m eval.p8.annotate verify <A>             every file of one annotator (A1, A2; A3 = tie-break files)
    python -m eval.p8.annotate disagreements          -> WORK/p8/disagreements.json {id: [fields]}
    python -m eval.p8.annotate a3packets              -> WORK/p8/a3/<id>.json (+ WORK/p8/a3_order.json)
    python -m eval.p8.annotate merge                  -> data/p8/p8_gold.jsonl, data/p8/annotations/*.jsonl,
                                                         data/p8/p8_key.jsonl, results/p8/p8_agreement.json

Annotator files: WORK/p8/ann/<A>/<id>.json. The disagreement key of a field is its derived category (eval/p8/derive.py,
with OPD's metadata, which the annotators never see), or n/a. Committed files carry no document text: every quote is
replaced by its sha256 and the resolved span (document, page, character offsets); annotators' notes stay in WORK.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys

from eval.p8 import common as C
from eval.p8 import derive as Dv
from eval.p8 import packets as P
from gegenprobe.stats import cohen_kappa

KEYS = ("id", "question_doc", "answer_doc", "people", "dates", "extra_dates", "addressed_body", "function",
        "instrument_named", "languages", "recommendation", "notes")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------------------------------------ quotes
def _rx(quote: str) -> re.Pattern:
    toks = quote.split()
    return re.compile(r"\s*".join(re.escape(t) for t in toks)) if toks else re.compile(r"(?!)")


def find(text: str, quote: str) -> list[tuple[int, int]]:
    """Every (start, end) of `quote` in text, whitespace-insensitive (whitespace may also be absent between tokens)."""
    return [(m.start(), m.end()) for m in _rx(quote).finditer(text)]


def resolve(obj: dict, pages: dict[str, list[str]]) -> tuple[dict | None, str | None]:
    doc, pg, q = obj.get("doc"), obj.get("page"), obj.get("quote")
    if doc not in pages:
        return None, f"doc {doc!r}"
    if not (isinstance(pg, int) and 1 <= pg <= len(pages[doc])):
        return None, f"page {pg!r} of {len(pages[doc])}"
    if not isinstance(q, str) or not q.strip() or len(q) > 200:
        return None, "quote missing or longer than 200 characters"
    hits = find(pages[doc][pg - 1], q)
    if not hits:
        return None, f"quote not on {doc} page {pg}: {q[:60]!r}"
    return dict(doc=doc, page=pg, char_start=hits[0][0], char_end=hits[0][1],
                quote_sha256=hashlib.sha256(q.encode()).hexdigest()), None


# ------------------------------------------------------------------------------------------------ checks
def check_parts(a: dict, pid: str, parts: tuple[str, ...]) -> list[str]:
    """Errors of the named label parts of one file (an empty list = the parts pass)."""
    pages = P.packet_pages(pid)
    letters = P.load_datelists().get(pid, {})
    e: list[str] = []

    def quoted(name, obj, required=True):
        if not isinstance(obj, dict):
            e.append(f"{name}: not an object")
            return
        if obj.get("quote") is None and not required:
            return
        _, err = resolve(obj, pages)
        if err:
            e.append(f"{name}: {err}")

    if "question_doc" in parts and a.get("question_doc") not in C.QDOC:
        e.append(f"question_doc must be one of {C.QDOC}")
    if "answer_doc" in parts and a.get("answer_doc") not in C.ADOC:
        e.append(f"answer_doc must be one of {C.ADOC}")
    if "people" in parts:
        if not isinstance(a.get("people"), list):
            e.append("people must be a list")
        for i, p in enumerate(a.get("people") or []):
            if not (isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"].strip()):
                e.append(f"people[{i}]: name")
                continue
            if p.get("kind") not in C.KINDS:
                e.append(f"people[{i}]: kind must be one of {C.KINDS}")
            if p.get("role") not in C.ROLES:
                e.append(f"people[{i}]: role must be one of {C.ROLES}")
            quoted(f"people[{i}]", p)
            last = (Dv.toks(p["name"]) or [""])[-1]
            if p.get("quote") and last and last not in Dv.toks(p["quote"]):
                e.append(f"people[{i}]: the quote does not contain the name's last word {last!r}")
    if "dates" in parts:
        ds = a.get("dates")
        if not isinstance(ds, dict):
            e.append("dates must be an object {letter: [roles]}")
        else:
            for k, rs in ds.items():
                if k not in letters:
                    e.append(f"dates: {k} is not a letter of this packet's date list")
                if not (isinstance(rs, list) and rs and all(r in C.DATE_ROLES for r in rs)):
                    e.append(f"dates[{k}]: roles must be a non-empty list of {C.DATE_ROLES}")
    if "extra_dates" in parts:
        xs = a.get("extra_dates")
        if not isinstance(xs, list):
            e.append("extra_dates must be a list")
        for i, x in enumerate(xs or []):
            if not (isinstance(x, dict) and isinstance(x.get("date"), str) and ISO.match(x["date"])):
                e.append(f"extra_dates[{i}]: date must be YYYY-MM-DD")
                continue
            if x["date"] in letters.values():
                e.append(f"extra_dates[{i}]: {x['date']} is in the date list; give its letter in `dates` instead")
            if not (isinstance(x.get("roles"), list) and x["roles"] and all(r in C.DATE_ROLES for r in x["roles"])):
                e.append(f"extra_dates[{i}]: roles must be a non-empty list of {C.DATE_ROLES}")
            quoted(f"extra_dates[{i}]", x)
    if "addressed_body" in parts:
        v = a.get("addressed_body") or {}
        if v.get("value") not in C.ADDR:
            e.append(f"addressed_body.value must be one of {C.ADDR}")
        elif v["value"] != "none_printed":
            quoted("addressed_body", v)
    if "function" in parts:
        v = a.get("function") or {}
        if v.get("value") not in C.FUNCTION:
            e.append(f"function.value must be one of {C.FUNCTION}")
        elif v["value"] != "unclear":
            quoted("function", v)
    if "instrument_named" in parts:
        v = a.get("instrument_named") or {}
        if v.get("value") not in C.INSTRUMENT:
            e.append(f"instrument_named.value must be one of {C.INSTRUMENT}")
        elif v["value"] != "none":
            quoted("instrument_named", v)
    if "languages" in parts:
        v = a.get("languages")
        if not (isinstance(v, dict) and set(v) == {"question", "answer"}
                and all(isinstance(x, list) and all(y in C.LANGS for y in x) for x in v.values())):
            e.append(f"languages must be {{'question': [...], 'answer': [...]}} with codes from {C.LANGS}")
    if "recommendation" in parts:
        v = a.get("recommendation") or {}
        if v.get("act") not in C.REC_ACT:
            e.append(f"recommendation.act must be one of {C.REC_ACT}")
        if v.get("value") not in C.REC_VALUE:
            e.append(f"recommendation.value must be one of {C.REC_VALUE}")
        if v.get("fits") not in C.FITS:
            e.append(f"recommendation.fits must be one of {C.FITS}")
        if v.get("act") in ("on_referral", "on_fulfilment", "other"):
            quoted("recommendation", v)
    return e


def check(a: dict, pid: str) -> list[str]:
    e = []
    extra = set(a) - set(KEYS)
    missing = set(KEYS) - set(a)
    if extra or missing:
        e.append(f"keys: missing {sorted(missing)}, unexpected {sorted(extra)}")
    if a.get("id") != pid:
        e.append(f"id must be {pid!r}")
    return e + check_parts(a, pid, tuple(k for k in KEYS if k not in ("id", "notes")))


def ann_dir(A: str):
    return C.ANN / A


def load(A: str) -> dict[str, dict]:
    d = ann_dir(A)
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("P8-*.json"))} if d.exists() else {}


def verify(A: str) -> int:
    key = P.load_key()
    labs = load(A)
    bad = 0
    if A == "A3":
        dis = json.loads((C.W8 / "disagreements.json").read_text())
        for pid, fields in dis.items():
            if pid not in labs:
                print(f"{pid}: missing")
                bad += 1
                continue
            parts = tuple(sorted({p for f in fields for p in C.PARTS[f]}))
            e = check_parts(labs[pid], pid, parts)
            if e:
                bad += 1
                print(pid, e)
    else:
        for pid in sorted(key):
            if pid not in labs:
                print(f"{pid}: missing")
                bad += 1
                continue
            e = check(labs[pid], pid)
            if e:
                bad += 1
                print(pid, e)
    print(f"{A}: {len(labs)} files, {bad} with problems")
    return 1 if bad else 0


# ------------------------------------------------------------------------------------------------ derived categories
def context():
    key = P.load_key()
    rows = {r["affair_id"]: r for r in C._jsonl(C.AFFAIRS)}
    meta = {r["affair_id"]: r for r in C._jsonl(C.META8)}
    dls = P.load_datelists()
    return key, rows, meta, dls


def derive_one(label: dict, pid: str, ctx) -> dict[str, dict]:
    key, rows, meta, dls = ctx
    aff = key[pid]["affair_id"]
    return Dv.derive(label, rows[aff], meta.get(aff), dls.get(pid, {}))


def disagreements() -> dict[str, list[str]]:
    ctx = context()
    a1, a2 = load("A1"), load("A2")
    out = {}
    for pid in sorted(ctx[0]):
        if pid not in a1 or pid not in a2:
            raise SystemExit(f"{pid}: A1 or A2 label missing")
        d1, d2 = derive_one(a1[pid], pid, ctx), derive_one(a2[pid], pid, ctx)
        diff = [f for f in C.FIELDS if Dv.key(d1[f]) != Dv.key(d2[f])]
        if diff:
            out[pid] = diff
    C.W8.mkdir(parents=True, exist_ok=True)
    (C.W8 / "disagreements.json").write_text(json.dumps(out, indent=1))
    return out


def a3packets() -> int:
    dis = disagreements()
    a1, a2 = load("A1"), load("A2")
    rnd = random.Random(C.SEED_A3)
    order = {}
    (C.W8 / "a3").mkdir(parents=True, exist_ok=True)
    for pid in sorted(dis):
        parts = sorted({p for f in dis[pid] for p in C.PARTS[f]})
        flip = rnd.random() < 0.5
        x, y = (a2[pid], a1[pid]) if flip else (a1[pid], a2[pid])
        order[pid] = "X=A2,Y=A1" if flip else "X=A1,Y=A2"
        (C.W8 / "a3" / f"{pid}.json").write_text(json.dumps(dict(
            id=pid, packet=str(C.PACK / f"{pid}.txt"), fields=dis[pid], parts=parts,
            label_X={k: x.get(k) for k in parts}, label_Y={k: y.get(k) for k in parts}), ensure_ascii=False, indent=1))
    (C.W8 / "a3_order.json").write_text(json.dumps(order, indent=1))
    return len(dis)


# ------------------------------------------------------------------------------------------------ merge
def sanitize(label: dict, pid: str) -> dict:
    """The label without document text: quotes -> sha256 + resolved span; notes dropped."""
    pages = P.packet_pages(pid)

    def s(obj):
        if isinstance(obj, dict):
            out = {k: s(v) for k, v in obj.items() if k not in ("quote", "notes")}
            if obj.get("quote"):
                span, _ = resolve(obj, pages)
                out["span"] = span
            return out
        if isinstance(obj, list):
            return [s(v) for v in obj]
        return obj

    return s(label)


def merge() -> dict:
    ctx = context()
    key = ctx[0]
    a1, a2, a3 = load("A1"), load("A2"), load("A3")
    dis = json.loads((C.W8 / "disagreements.json").read_text()) if (C.W8 / "disagreements.json").exists() else {}
    if dis != disagreements():
        raise SystemExit("disagreements.json is stale: run a3packets again")
    for A, labs in (("A1", a1), ("A2", a2)):
        for pid in key:
            if pid not in labs or check(labs[pid], pid):
                raise SystemExit(f"{A} {pid}: missing or failing the check")
    gold, agree = [], {f: dict(x=[], y=[]) for f in C.FIELDS}
    for pid in sorted(key):
        d1, d2 = derive_one(a1[pid], pid, ctx), derive_one(a2[pid], pid, ctx)
        fields, parts = {}, {}
        for f in C.FIELDS:
            agree[f]["x"].append(Dv.key(d1[f]))
            agree[f]["y"].append(Dv.key(d2[f]))
            if f in dis.get(pid, []):
                if pid not in a3 or check_parts(a3[pid], pid, C.PARTS[f]):
                    raise SystemExit(f"A3 {pid}: tie-break label for {f} missing or failing the check")
                src, lab = "A3", a3[pid]
            else:
                src, lab = "A1=A2", a1[pid]
            sub = {k: lab.get(k) for k in C.PARTS[f]}
            fields[f] = dict(source=src, **derive_one(sub, pid, ctx)[f])
            parts[f] = sanitize(sub, pid)
        gold.append(dict(id=pid, affair_id=key[pid]["affair_id"], body=key[pid]["body"], cell=key[pid]["cell"],
                         affair_type=key[pid]["affair_type"], question_doc=a1[pid]["question_doc"]
                         if a1[pid]["question_doc"] == a2[pid]["question_doc"] else "disputed",
                         answer_doc=a1[pid]["answer_doc"] if a1[pid]["answer_doc"] == a2[pid]["answer_doc"] else "disputed",
                         fields=fields, parts=parts))
    C.D8.mkdir(parents=True, exist_ok=True)
    with open(C.GOLD, "w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    C.ANN_COMMITTED.mkdir(parents=True, exist_ok=True)
    for A, labs in (("A1", a1), ("A2", a2), ("A3", a3)):
        with open(C.ANN_COMMITTED / f"{A}.jsonl", "w", encoding="utf-8") as f:
            for pid in sorted(labs):
                f.write(json.dumps(sanitize(labs[pid], pid), ensure_ascii=False) + "\n")
    (C.ANN_COMMITTED / "a3_order.json").write_text((C.W8 / "a3_order.json").read_text() if (C.W8 / "a3_order.json").exists()
                                                   else "{}")
    (C.D8 / "p8_key.jsonl").write_text(C.KEY.read_text())
    res = dict(n=len(gold), disputed_packets=len(dis), disputed_fields=sum(len(v) for v in dis.values()),
               fields={f: dict(raw=sum(x == y for x, y in zip(v["x"], v["y"])), n=len(v["x"]),
                               kappa=round(cohen_kappa(v["x"], v["y"]), 3),
                               decided_by_A3=sum(f in dis.get(pid, []) for pid in key))
                       for f, v in agree.items()},
               a3_order_randomised=True)
    C.R8.mkdir(parents=True, exist_ok=True)
    (C.R8 / "p8_agreement.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selfcheck":
        A, pid = sys.argv[2], sys.argv[3]
        lab = json.loads((ann_dir(A) / f"{pid}.json").read_text(encoding="utf-8"))
        if A == "A3":
            dis = json.loads((C.W8 / "disagreements.json").read_text())
            err = check_parts(lab, pid, tuple(sorted({p for f in dis.get(pid, []) for p in C.PARTS[f]})))
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
