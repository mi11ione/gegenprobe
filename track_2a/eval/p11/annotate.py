"""P11 gold labels (eval/p11/PROTOCOL.md §5): blind agent annotators label each packet with the cell's guide; code checks
every label against the closed vocabularies and every quote verbatim (whitespace-insensitive) on the page it names; a
third annotator decides the fields whose disagreement key differs, seeing both labels as X/Y in seeded random order.

    python -m eval.p11.annotate selfcheck <A> <id>      one file (annotators run this after writing it; IT-/NI- ids)
    python -m eval.p11.annotate verify <cell> <A>       every file of one annotator (A1, A2; A3 = tie-break files)
    python -m eval.p11.annotate disagreements <cell>    -> WORK/p11/disagreements_<cell>.json {id: [fields]}
    python -m eval.p11.annotate a3packets <cell>        -> WORK/p11/a3/<id>.json (+ WORK/p11/a3_order_<cell>.json)
    python -m eval.p11.annotate merge <cell>            -> data/p11/p11_<cell>_gold.jsonl, data/p11/annotations/,
                                                           data/p11/p11_<cell>_key.jsonl, results/p11/p11_<cell>_agreement.json
<cell> is `it` or `ni`.

IT (GUIDE_P11_IT.md): the federal cell's label format and checks, unchanged (eval/fed/annotate.py, frozen by LOCKFED:
P8's closed vocabularies and quote check for question_doc, answer_doc, people, function, instrument_named, languages;
P1's answer-date check), pointed at the P11 packets. Fields and disagreement keys: answer_date (the printed date or null,
P1's key), people (P10's key: the two (name, role) lists match one-to-one, eval/p10/score.py `match`; or P8's derived
submitter category differs), type and language (P8's derived categories, with OPD's metadata, which the annotators never
see).
NI (GUIDE_P11_NI.md): per field of schema v0.2's 17-field skeleton a verdict (fits / new_role / not_printed /
not_applicable / cannot_tell), with the existing role it fits or a short label of the new role, and the printed evidence;
plus what the affair is (affair_kind) and what each document is (documents, schema v0.1's document roles). Disagreement
key per field: the verdict; affair_kind: its value.
Committed files carry no document text: every quote is replaced by its sha256 and the resolved span; notes stay in WORK.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys

from eval.fed import annotate as FA  # noqa: I001 (imported before the P8 paths are pointed at P11's files)
from eval.p8 import annotate as A8
from eval.p8 import common as C8
from eval.p8 import derive as Dv
from eval.p10.score import match
from eval.p11 import common as C
from eval.p11 import packets as P
from gegenprobe.stats import cohen_kappa

# the frozen P8 and federal helpers read packets and date lists through eval.p8.common: point them at P11's files
C8.PACK, C8.DATELISTS = C.PACK, C.DATELISTS

# ------------------------------------------------------------------------------------------------ IT
IT_FIELDS = ("answer_date", "people", "type", "language")
IT_PARTS = {"answer_date": FA.AD_PARTS, "people": ("people",), "type": ("function", "instrument_named"),
            "language": ("languages",)}

# ------------------------------------------------------------------------------------------------ NI
NI_FIELDS = ("date_submission", "date_decision", "date_dispatch", "qa_pairing", "related_affairs", "documents_usable_text",
             "answer_link_status", "date_answer", "procedural_history", "type", "procedural_state", "decision_outcome",
             "submitter", "co_signatories", "addressed_body", "government_recommendation", "language")
# the existing roles of each field (GUIDE_P11_NI.md §3); `other` is never a role here: a value no listed role fits is a
# new role, which is what the cell measures
NI_ROLES = {
    "date_submission": ("signed", "lodged", "session_lodged", "cited"),
    "date_decision": ("decision",),
    "date_dispatch": ("dispatch",),
    "qa_pairing": ("question_answer",),
    "related_affairs": ("answers", "answered_by", "follows_up", "replaces", "replaced_by", "joined_with", "same_subject",
                        "cites", "implements", "counter_proposal_to"),
    "documents_usable_text": ("usable",),
    "answer_link_status": ("attached", "oral"),
    "date_answer": ("decision", "dispatch"),
    "procedural_history": ("submitted", "signed", "lodged", "received", "announced", "answer_decided",
                           "answer_dispatched", "answered", "scheduled", "debated", "referred_to_committee", "decided",
                           "closed", "withdrawn", "published", "entry_into_force", "deadline", "referendum_deadline",
                           "popular_vote", "later_step"),
    "type": ("mandate", "examine_report", "questions", "direct_decision"),
    "procedural_state": ("submitted", "pending_answer", "answered", "scheduled", "in_committee", "debated", "referred",
                         "decided", "closed", "withdrawn", "lapsed"),
    "decision_outcome": ("adopted", "rejected", "referred", "converted_to_postulate", "partially_adopted", "written_off",
                         "not_written_off", "acknowledged", "withdrawn", "lapsed", "returned", "no_decision", "pending"),
    "submitter": ("sole_author", "first_signatory", "joint_author", "spokesperson"),
    "co_signatories": ("co_signatory", "supporter", "joint_author", "spokesperson"),
    "addressed_body": ("executive", "executive_member_or_department", "parliament", "committee", "administration"),
    "government_recommendation": ("on_referral", "on_fulfilment"),
    "language": ("text_language",),
}
VERDICTS = ("fits", "new_role", "not_printed", "not_applicable", "cannot_tell")
AFFAIR_KIND = ("government_business", "parliamentary_initiative", "intervention", "other", "unclear")
DOC_KINDS = ("question", "answer", "decision", "message", "report", "minutes", "agenda", "annex", "publication",
             "placeholder", "other")  # schema v0.1 DocRole
NOQUOTE = {"documents_usable_text", "answer_link_status", "language"}  # evidence is the document itself; quote optional
NI_KEYS = ("id", "affair_kind", "documents", "fields", "notes")
FIELD_KEYS = ("verdict", "role", "new_role", "doc", "page", "quote")
NEW_ROLE_MAX = 80


def cell_of(pid: str) -> str:
    if pid.startswith("IT-"):
        return "it"
    if pid.startswith("NI-"):
        return "ni"
    raise SystemExit(f"{pid}: not a P11 packet id")


# ------------------------------------------------------------------------------------------------ NI checks
def check_ni_field(f: str, v, pages: dict) -> list[str]:
    if not isinstance(v, dict) or set(v) != set(FIELD_KEYS):
        return [f"fields.{f}: must be an object with exactly the keys {FIELD_KEYS}"]
    e = []
    vd = v.get("verdict")
    if vd not in VERDICTS:
        return [f"fields.{f}.verdict must be one of {VERDICTS}"]
    if vd == "fits":
        if v.get("role") not in NI_ROLES[f]:
            e.append(f"fields.{f}.role must be one of {NI_ROLES[f]} when the verdict is 'fits'")
        if v.get("new_role") is not None:
            e.append(f"fields.{f}.new_role must be null unless the verdict is 'new_role'")
    elif vd == "new_role":
        nr = v.get("new_role")
        if not (isinstance(nr, str) and nr.strip() and len(nr) <= NEW_ROLE_MAX):
            e.append(f"fields.{f}.new_role must be a short label (1-{NEW_ROLE_MAX} characters) when the verdict is "
                     "'new_role'")
        if v.get("role") is not None:
            e.append(f"fields.{f}.role must be null when the verdict is 'new_role'")
    else:
        for k in ("role", "new_role", "doc", "page", "quote"):
            if v.get(k) is not None:
                e.append(f"fields.{f}.{k} must be null when the verdict is {vd!r}")
        return e
    if f in NOQUOTE and v.get("quote") is None:
        if v.get("doc") is not None and v["doc"] not in pages:
            e.append(f"fields.{f}.doc {v['doc']!r} is not a document of this packet")
        return e
    _, err = A8.resolve(v, pages)
    if err:
        e.append(f"fields.{f}: {err}")
    return e


def check_ni_parts(a: dict, pid: str, parts: tuple[str, ...]) -> list[str]:
    """Errors of the named parts of an NI label: field names, 'affair_kind', 'documents'."""
    pages = P.packet_pages(pid)
    e = []
    if "affair_kind" in parts:
        v = a.get("affair_kind")
        if not isinstance(v, dict) or v.get("value") not in AFFAIR_KIND:
            e.append(f"affair_kind.value must be one of {AFFAIR_KIND}")
        elif v["value"] != "unclear":
            _, err = A8.resolve(v, pages)
            if err:
                e.append(f"affair_kind: {err}")
    if "documents" in parts:
        v = a.get("documents")
        if not (isinstance(v, dict) and set(v) == set(pages) and all(x in DOC_KINDS for x in v.values())):
            e.append(f"documents must map exactly the packet's documents {sorted(pages)} to one of {DOC_KINDS}")
    fs = a.get("fields") if isinstance(a.get("fields"), dict) else {}
    for f in parts:
        if f in NI_ROLES:
            if f not in fs:
                e.append(f"fields.{f} missing")
            else:
                e += check_ni_field(f, fs[f], pages)
    return e


def check_ni(a: dict, pid: str) -> list[str]:
    e = []
    extra, missing = set(a) - set(NI_KEYS), set(NI_KEYS) - set(a)
    if extra or missing:
        e.append(f"keys: missing {sorted(missing)}, unexpected {sorted(extra)}")
    if a.get("id") != pid:
        e.append(f"id must be {pid!r}")
    fs = a.get("fields")
    if not isinstance(fs, dict) or set(fs) != set(NI_FIELDS):
        e.append(f"fields must have exactly the 17 keys {NI_FIELDS}")
    return e + check_ni_parts(a, pid, ("affair_kind", "documents") + NI_FIELDS)


def check_ni_a3(a: dict, pid: str, disputed: list[str]) -> list[str]:
    want = {"id", "notes", "fields"} | ({"affair_kind"} if "affair_kind" in disputed else set())
    e = []
    if set(a) != want:
        e.append(f"keys must be exactly {sorted(want)}")
    fs = [f for f in disputed if f in NI_ROLES]
    if not isinstance(a.get("fields"), dict) or set(a["fields"]) != set(fs):
        e.append(f"fields must have exactly the keys {fs}")
    return e + check_ni_parts(a, pid, tuple(disputed))


# ------------------------------------------------------------------------------------------------ files
def ann_dir(A: str):
    return C.ANN / A


def load(A: str, cell: str) -> dict[str, dict]:
    d = ann_dir(A)
    pre = C.PREFIX[cell]
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob(f"{pre}-*.json"))} if d.exists() \
        else {}


def dis_path(cell: str):
    return C.W11 / f"disagreements_{cell}.json"


def _disputed(cell: str) -> dict[str, list[str]]:
    p = dis_path(cell)
    return json.loads(p.read_text()) if p.exists() else {}


def check_file(A: str, pid: str, lab: dict) -> list[str]:
    cell = cell_of(pid)
    if A == "A3":
        dis = _disputed(cell).get(pid)
        if dis is None:
            return [f"{pid} is not a tie-break packet"]
        if cell == "it":
            return FA.check_parts(lab, pid, tuple(sorted({p for f in dis for p in IT_PARTS[f]})))
        return check_ni_a3(lab, pid, dis)
    return FA.check(lab, pid) if cell == "it" else check_ni(lab, pid)


def verify(cell: str, A: str) -> int:
    key, labs, bad = P.load_key(cell), load(A, cell), 0
    todo = sorted(_disputed(cell)) if A == "A3" else sorted(key)
    for pid in todo:
        if pid not in labs:
            print(f"{pid}: missing")
            bad += 1
            continue
        e = check_file(A, pid, labs[pid])
        if e:
            bad += 1
            print(pid, e)
    print(f"{cell} {A}: {len(labs)} files, {bad} with problems")
    return 1 if bad else 0


# ------------------------------------------------------------------------------------------------ IT derivation
def entry_of(k: dict) -> dict:
    """The P8 derivation's view of one IT affair: OPD's type (by the type rule) and OPD's language tag of each document."""
    return dict(affair_type=k["affair_type"], docs=[dict(role=r, opd_lang=v.get("opd_lang")) for r, v in k["docs"].items()])


def it_context():
    return P.load_key("it"), {r["affair_id"]: r for r in C._jsonl(C.META)}


def pairs(label: dict) -> list[tuple[str, str]]:
    return [(p["name"], p["role"]) for p in label.get("people") or []]


def lists_agree(x: dict, y: dict) -> bool:
    px, py = pairs(x), pairs(y)
    return len(px) == len(py) and match(px, py)[0] == len(px)


def derive_it(label: dict, pid: str, ctx) -> dict[str, dict]:
    key, meta = ctx
    k = key[pid]
    e = entry_of(k)
    m = meta.get(k["affair_id"])
    v = label.get("answer_date")
    sub = Dv.submitter(label, m)
    return {"answer_date": dict(applicable=True, category=v if v is not None else "null", role=label.get("role"),
                                answer_present=label.get("answer_present")),
            "people": dict(applicable=True, category=sub["category"], pairs=pairs(label), submitter=sub),
            "type": Dv.type_(label, e), "language": Dv.language(label, e)}


def it_differs(f: str, a1: dict, a2: dict, d1: dict, d2: dict) -> bool:
    if f == "people":
        return not lists_agree(a1, a2) or Dv.key(d1[f]["submitter"]) != Dv.key(d2[f]["submitter"])
    return Dv.key(d1[f]) != Dv.key(d2[f])


def ni_differs(f: str, a1: dict, a2: dict) -> bool:
    if f == "affair_kind":
        return (a1.get("affair_kind") or {}).get("value") != (a2.get("affair_kind") or {}).get("value")
    return a1["fields"][f]["verdict"] != a2["fields"][f]["verdict"]


def disagreements(cell: str) -> dict[str, list[str]]:
    key = P.load_key(cell)
    a1, a2 = load("A1", cell), load("A2", cell)
    ctx = it_context() if cell == "it" else None
    out = {}
    for pid in sorted(key):
        if pid not in a1 or pid not in a2:
            raise SystemExit(f"{pid}: A1 or A2 label missing")
        if cell == "it":
            d1, d2 = derive_it(a1[pid], pid, ctx), derive_it(a2[pid], pid, ctx)
            diff = [f for f in IT_FIELDS if it_differs(f, a1[pid], a2[pid], d1, d2)]
        else:
            diff = [f for f in ("affair_kind",) + NI_FIELDS if ni_differs(f, a1[pid], a2[pid])]
        if diff:
            out[pid] = diff
    C.W11.mkdir(parents=True, exist_ok=True)
    dis_path(cell).write_text(json.dumps(out, indent=1))
    return out


def _x(label: dict, cell: str, fields: list[str]) -> dict:
    if cell == "it":
        return {k: label.get(k) for k in sorted({p for f in fields for p in IT_PARTS[f]})}
    out = {"fields": {f: label["fields"][f] for f in fields if f in NI_ROLES}}
    if "affair_kind" in fields:
        out["affair_kind"] = label.get("affair_kind")
    return out


def a3packets(cell: str) -> int:
    dis = disagreements(cell)
    a1, a2 = load("A1", cell), load("A2", cell)
    rnd = random.Random(f"{C.SEED_A3}:{cell}")
    order = {}
    (C.W11 / "a3").mkdir(parents=True, exist_ok=True)
    for pid in sorted(dis):
        flip = rnd.random() < 0.5
        x, y = (a2[pid], a1[pid]) if flip else (a1[pid], a2[pid])
        order[pid] = "X=A2,Y=A1" if flip else "X=A1,Y=A2"
        parts = sorted({p for f in dis[pid] for p in IT_PARTS[f]}) if cell == "it" else dis[pid]
        (C.W11 / "a3" / f"{pid}.json").write_text(json.dumps(dict(
            id=pid, packet=str(C.PACK / f"{pid}.txt"), fields=dis[pid], parts=parts,
            label_X=_x(x, cell, dis[pid]), label_Y=_x(y, cell, dis[pid])), ensure_ascii=False, indent=1))
    (C.W11 / f"a3_order_{cell}.json").write_text(json.dumps(order, indent=1))
    return len(dis)


# ------------------------------------------------------------------------------------------------ merge
def sanitize(label: dict, pid: str) -> dict:
    """The label without document text: every quote -> its sha256 and resolved span; notes dropped."""
    if cell_of(pid) == "it":
        return FA.sanitize(label, pid)
    pages = P.packet_pages(pid)

    def s(obj):
        if isinstance(obj, dict):
            out = {k: s(v) for k, v in obj.items() if k not in ("quote", "notes")}
            if obj.get("quote"):
                span, _ = A8.resolve(obj, pages)
                out["span"] = span
            return out
        if isinstance(obj, list):
            return [s(v) for v in obj]
        return obj

    return s(label)


def _commit_annotations(cell: str, labs_by: dict) -> None:
    C.ANN_COMMITTED.mkdir(parents=True, exist_ok=True)
    for A, labs in labs_by.items():
        with open(C.ANN_COMMITTED / f"{cell}_{A}.jsonl", "w", encoding="utf-8") as f:
            for pid in sorted(labs):
                f.write(json.dumps(sanitize(labs[pid], pid), ensure_ascii=False) + "\n")
    order = C.W11 / f"a3_order_{cell}.json"
    (C.ANN_COMMITTED / f"{cell}_a3_order.json").write_text(order.read_text() if order.exists() else "{}")
    (C.D11 / f"p11_{cell}_key.jsonl").write_text(C.KEY[cell].read_text(encoding="utf-8"), encoding="utf-8")


def _agreement(agree: dict, dis: dict, key: dict) -> dict:
    return {f: dict(raw=sum(x == y for x, y in zip(v["x"], v["y"])), n=len(v["x"]),
                    kappa=round(cohen_kappa(v["x"], v["y"]), 3),
                    decided_by_A3=sum(f in dis.get(pid, []) for pid in key)) for f, v in agree.items()}


def merge_it() -> dict:
    ctx = it_context()
    key = ctx[0]
    a1, a2, a3 = load("A1", "it"), load("A2", "it"), load("A3", "it")
    dis = _disputed("it")
    if dis != disagreements("it"):
        raise SystemExit("disagreements_it.json is stale: run a3packets it again")
    for A, labs in (("A1", a1), ("A2", a2)):
        for pid in key:
            if pid not in labs or FA.check(labs[pid], pid):
                raise SystemExit(f"{A} {pid}: missing or failing the check")
    gold, agree = [], {f: dict(x=[], y=[]) for f in IT_FIELDS}
    n12 = m12 = 0
    for pid in sorted(key):
        d1, d2 = derive_it(a1[pid], pid, ctx), derive_it(a2[pid], pid, ctx)
        p1, p2 = pairs(a1[pid]), pairs(a2[pid])
        n12 += len(p1) + len(p2)
        m12 += 2 * match(p1, p2)[0]
        fields, parts = {}, {}
        for f in IT_FIELDS:
            agree[f]["x"].append(Dv.key(d1[f]) if f != "people" else json.dumps(sorted(p1)))
            agree[f]["y"].append(Dv.key(d2[f]) if f != "people" else json.dumps(sorted(p2)))
            if f in dis.get(pid, []):
                if pid not in a3 or FA.check_parts(a3[pid], pid, IT_PARTS[f]):
                    raise SystemExit(f"A3 {pid}: tie-break label for {f} missing or failing the check")
                src, lab = "A3", a3[pid]
            else:
                src, lab = "A1=A2", a1[pid]
            sub = {k: lab.get(k) for k in IT_PARTS[f]}
            d = derive_it(sub, pid, ctx)[f]
            fields[f] = dict(source=src, **{k: v for k, v in d.items() if k != "pairs"})
            if f == "people":
                fields[f]["pairs"] = [list(x) for x in pairs(sub)]
            if f == "answer_date":
                g = sub.get("answer_date")
                fields[f]["lenient"] = sorted(
                    {x for x in (a1[pid].get("answer_date_lenient") or []) + (a2[pid].get("answer_date_lenient") or [])}
                    | ({a1[pid]["answer_date"], a2[pid]["answer_date"]} - {None, g}))
            parts[f] = FA.sanitize(sub, pid)
        k = key[pid]
        gold.append(dict(id=pid, affair_id=k["affair_id"], body=k["body"], stratum=k["stratum"],
                         affair_type=k["affair_type"], group=k["group"], type_source=k["type_source"], fill=k["fill"],
                         question_doc=a1[pid]["question_doc"] if a1[pid]["question_doc"] == a2[pid]["question_doc"]
                         else "disputed",
                         answer_doc=a1[pid]["answer_doc"] if a1[pid]["answer_doc"] == a2[pid]["answer_doc"] else "disputed",
                         fields=fields, parts=parts))
    C.D11.mkdir(parents=True, exist_ok=True)
    with open(C.GOLD["it"], "w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    _commit_annotations("it", {"A1": a1, "A2": a2, "A3": a3})
    res = dict(label="EXPLORATORY P11 IT cell", n=len(gold), disputed_packets=len(dis),
               disputed_fields=sum(len(v) for v in dis.values()), fields=_agreement(agree, dis, key),
               people_pair_f1_A1_vs_A2=round(m12 / n12, 4) if n12 else None, a3_order_randomised=True,
               key_sha256=hashlib.sha256(C.KEY["it"].read_bytes()).hexdigest())
    C.R11.mkdir(parents=True, exist_ok=True)
    (C.R11 / "p11_it_agreement.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


def merge_ni() -> dict:
    key = P.load_key("ni")
    a1, a2, a3 = load("A1", "ni"), load("A2", "ni"), load("A3", "ni")
    dis = _disputed("ni")
    if dis != disagreements("ni"):
        raise SystemExit("disagreements_ni.json is stale: run a3packets ni again")
    for A, labs in (("A1", a1), ("A2", a2)):
        for pid in key:
            if pid not in labs or check_ni(labs[pid], pid):
                raise SystemExit(f"{A} {pid}: missing or failing the check")
    for pid, fs in dis.items():
        if pid not in a3 or check_ni_a3(a3[pid], pid, fs):
            raise SystemExit(f"A3 {pid}: tie-break label missing or failing the check")
    gold = []
    agree = {f: dict(x=[], y=[]) for f in ("affair_kind",) + NI_FIELDS}
    role_agree = {f: [0, 0] for f in NI_FIELDS}  # [both fits with the same role, both fits]
    for pid in sorted(key):
        x, y = a1[pid], a2[pid]
        agree["affair_kind"]["x"].append(x["affair_kind"]["value"])
        agree["affair_kind"]["y"].append(y["affair_kind"]["value"])
        if "affair_kind" in dis.get(pid, []):
            ak = dict(source="A3", **sanitize(a3[pid]["affair_kind"], pid))
        else:
            ak = dict(source="A1=A2", **sanitize(x["affair_kind"], pid))
        fields = {}
        for f in NI_FIELDS:
            v1, v2 = x["fields"][f], y["fields"][f]
            agree[f]["x"].append(v1["verdict"])
            agree[f]["y"].append(v2["verdict"])
            if v1["verdict"] == v2["verdict"] == "fits":
                role_agree[f][1] += 1
                role_agree[f][0] += v1["role"] == v2["role"]
            if f in dis.get(pid, []):
                v, src, labels = a3[pid]["fields"][f], "A3", [a3[pid]["fields"][f].get("new_role")]
            else:
                v, src, labels = v1, "A1=A2", [v1.get("new_role"), v2.get("new_role")]
            fields[f] = dict(source=src, verdict=v["verdict"], role=v.get("role"),
                             roles_A1_A2=[v1.get("role"), v2.get("role")] if src == "A1=A2" else None,
                             new_role_labels=[s for s in labels if s] if v["verdict"] == "new_role" else [],
                             evidence=sanitize({k: v.get(k) for k in ("doc", "page", "quote")}, pid))
        k = key[pid]
        docs = {d: (x["documents"][d] if x["documents"][d] == y["documents"][d] else "disputed") for d in x["documents"]}
        gold.append(dict(id=pid, affair_id=k["affair_id"], body=k["body"], stratum=k["stratum"], ni_type=k["ni_type"],
                         lang=k["lang"], affair_type=k["affair_type"], type_source=k["type_source"], affair_kind=ak,
                         documents=docs, fields=fields))
    C.D11.mkdir(parents=True, exist_ok=True)
    with open(C.GOLD["ni"], "w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    _commit_annotations("ni", {"A1": a1, "A2": a2, "A3": a3})
    res = dict(label="EXPLORATORY P11 NI cell", n=len(gold), disputed_packets=len(dis),
               disputed_fields=sum(len(v) for v in dis.values()), fields=_agreement(agree, dis, key),
               role_agreement_when_both_fit={f: dict(same_role=v[0], both_fit=v[1]) for f, v in role_agree.items()},
               a3_order_randomised=True, key_sha256=hashlib.sha256(C.KEY["ni"].read_bytes()).hexdigest())
    C.R11.mkdir(parents=True, exist_ok=True)
    (C.R11 / "p11_ni_agreement.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selfcheck":
        A, pid = sys.argv[2], sys.argv[3]
        lab = json.loads((ann_dir(A) / f"{pid}.json").read_text(encoding="utf-8"))
        err = check_file(A, pid, lab)
        print("OK" if not err else "ERRORS:\n- " + "\n- ".join(err))
        sys.exit(1 if err else 0)
    elif cmd == "verify":
        sys.exit(verify(sys.argv[2], sys.argv[3]))
    elif cmd == "disagreements":
        print(json.dumps(disagreements(sys.argv[2]), indent=1))
    elif cmd == "a3packets":
        print(a3packets(sys.argv[2]), "tie-break packets")
    elif cmd == "merge":
        print(json.dumps(merge_it() if sys.argv[2] == "it" else merge_ni(), indent=1))
    else:
        print(__doc__)
