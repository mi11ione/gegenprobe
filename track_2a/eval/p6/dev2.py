"""DEV2: a development set (not a test) of ~40 fresh documents from parliaments that are in no existing set, used only to
choose the pointer-v2 configuration before P6 is registered. Its bodies are excluded from P6 (eval/p6/sample.py).

    python -m eval.p6.dev2 draw        network: polite PDF fetches -> data/p6/dev2_docs.jsonl (+ fetch log); no text
    python -m eval.p6.dev2 packets     -> .work/p6dev/packets/<doc_id>.txt + index.json (never committed)
    python -m eval.p6.dev2 verify A1|A2|A3 / selfcheck <A> <doc_id> / a3packets / merge
                                       labels -> data/p6/dev2_labels.jsonl (guide: eval/gold2/GUIDE.md, unchanged)
"""

from __future__ import annotations

import collections
import json
import sys

from eval.p6 import common as C
from gegenprobe import pdftext
from gegenprobe.paths import DATA, WORK
from gegenprobe.stats import cohen_kappa

SEED = 20261012
BAND = (2000, 12000)
DOCS = DATA / "p6" / "dev2_docs.jsonl"
LOG = DATA / "p6" / "dev2_fetch_log.jsonl"
LABELS = DATA / "p6" / "dev2_labels.jsonl"
W = WORK / "p6dev"
# (cell, body, dtype, n): bodies in no existing set; none of them may appear in P6. Hosts that did not answer from this
# machine on 10 Oct 2026 (connection timeouts: ur.ch, olten.ch, horw.ch, langenthal.ch and other i-web.ch sites; Kriens,
# Arbon, Locarno and AG disallow their document paths in robots.txt; Sierre's answers return 404) are not used. Two
# earlier draws with those bodies (17 and 20 documents, no label, no model call) were discarded.
QUOTAS = [
    ("de_commune", "121", "answer", 6),  # Wetzikon
    ("de_commune", "121", "intervention", 4),
    ("de_commune", "4671", "answer", 6),  # Kreuzlingen
    ("de_commune", "4671", "intervention", 2),
    ("fr_commune", "6025", "answer", 4),  # Vétroz
    ("fr_commune", "6025", "intervention", 3),
    ("fr_commune", "5938", "intervention", 4),  # Yverdon-les-Bains
    ("fr_commune", "6136", "intervention", 2),  # Martigny
]
BODIES = sorted({q[1] for q in QUOTAS})


def draw() -> None:
    if DOCS.exists():
        raise SystemExit(f"{DOCS} exists")
    x_docs, x_affs, x_bodies = C.exclusions()
    clash = set(BODIES) & x_bodies
    assert not clash, f"DEV2 bodies already in an existing set: {clash}"
    got, log = C.draw(QUOTAS, SEED, "p6dev2", BAND, x_docs, x_affs)
    C.write_jsonl(DOCS, got)
    C.write_jsonl(LOG, log)
    print(collections.Counter((r["body"], r["dtype"]) for r in got), "total", len(got))
    print("shortfalls", [x for x in log if "shortfall" in x])


def load() -> list[dict]:
    """Documents with page texts (and labels once merged), in the layout eval.arms.load_split returns."""
    labels = {r["doc_id"]: r for r in C._jsonl(LABELS)}
    out = []
    for d in C._jsonl(DOCS):
        t = pdftext.extract(d["sha256"])
        out.append(dict(doc_id=d["doc_id"], cell=d["cell"], body=d["body"], lang=d.get("lang"), pages=t["pages"],
                        image_only=t["image_only"], affair_type=d.get("affair_type"), sha256=d["sha256"],
                        label=labels.get(d["doc_id"])))
    return out


def date_key(a: dict) -> tuple:
    return (a["answer_date"],)


def merge() -> dict:
    A = C.bind_annotation(DOCS, W)
    a1, a2, a3 = A.load("A1"), A.load("A2"), A.load("A3")
    docs = {d["doc_id"]: d for d in C._jsonl(DOCS)}
    ids = sorted(set(a1) & set(a2))
    agree = {}
    for f in ("answer_present", "answer_date"):
        x, y = [str(a1[i][f]) for i in ids], [str(a2[i][f]) for i in ids]
        agree[f] = dict(raw=sum(p == q for p, q in zip(x, y)), n=len(ids), kappa=cohen_kappa(x, y))
    rows, missing = [], []
    for i in ids:
        if date_key(a1[i]) == date_key(a2[i]):
            lab, src = a1[i], "A1=A2"
        elif i in a3:
            lab, src = a3[i], "A3"
        else:
            missing.append(i)
            continue
        len_ = sorted(set((a1[i].get("answer_date_lenient") or []) + (a2[i].get("answer_date_lenient") or []))
                      | ({a1[i]["answer_date"], a2[i]["answer_date"]} - {None, lab["answer_date"]}))
        rows.append(dict(doc_id=i, source="p6dev2", cell=docs[i]["cell"], dtype=docs[i]["dtype"], body=docs[i]["body"],
                         labeller=f"claude-agents:{src}", answer_present=lab["answer_present"], answer_date=lab["answer_date"],
                         role=lab.get("role"), answer_date_page=lab.get("answer_date_page"),
                         answer_date_quote=(lab.get("answer_date_quote") or "")[:200],
                         answer_date_lenient=[x for x in len_ if x], decision_number=lab.get("decision_number")))
    if missing:
        raise SystemExit(f"tie-break missing for {missing}")
    C.write_jsonl(LABELS, rows)
    res = dict(n=len(rows), agreement=agree, decided_by_A3=sum(r["labeller"].endswith("A3") for r in rows))
    (DATA / "p6" / "dev2_agreement.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "draw":
        draw()
    else:
        A = C.bind_annotation(DOCS, W)
        if cmd == "packets":
            A.packets()
        elif cmd == "verify":
            sys.exit(A.verify(sys.argv[2]))
        elif cmd == "selfcheck":
            a = json.loads((A.ANN / sys.argv[2] / f"{sys.argv[3]}.json").read_text())
            e = A.check(a)
            print("OK" if not e else f"ERRORS: {e}")
            sys.exit(1 if e else 0)
        elif cmd == "a3packets":
            print(len(C.a3packets(A, SEED, date_key)), "tie-break packets")
        elif cmd == "merge":
            print(json.dumps(merge(), indent=1))
