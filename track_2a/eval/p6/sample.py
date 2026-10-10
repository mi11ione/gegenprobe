"""P6 sample (eval/prereg7/PREREG7.md): fresh documents from parliaments that are in no existing set (P1 dev/held-out and
every dev-id source, P2, P3, P3b, P4, U2's P5 sets, and DEV2). Model-free. Run only AFTER the LOCK7 commit.

    python -m eval.p6.sample draw      network: polite PDF fetches -> data/p6/p6_docs.jsonl + data/p6/p6_fetch_log.jsonl
    python -m eval.p6.sample packets   -> .work/p6/packets/<doc_id>.txt + index.json (never committed)
    python -m eval.p6.sample verify A1|A2|A3 / selfcheck <A> <doc_id> / a3packets / merge   (labels: data/p6/p6_labels.jsonl)

Strata come from the OPD metadata only (eval/p6/common.doctype6 on the document name); the label is the annotators'.
"""

from __future__ import annotations

import collections
import json
import sys

from eval.p6 import common as C
from eval.p6 import dev2
from gegenprobe.paths import DATA, WORK
from gegenprobe.stats import cohen_kappa

SEED = 20261013
BAND = (2000, 12000)
DOCS = DATA / "p6" / "p6_docs.jsonl"
LOG = DATA / "p6" / "p6_fetch_log.jsonl"
LABELS = DATA / "p6" / "p6_labels.jsonl"
W = WORK / "p6"
# (cell, body, dtype, n) exactly as PREREG7: 9 bodies, 77 documents. Riehen (2703) was planned and removed before LOCK7
# because U2's P5 test uses it; its 9 documents are redistributed to ZG, Zug city, Wil, Lyss and Neuhausen (no other unseen
# parliament with answer documents was reachable from this machine on 10 Oct 2026; PREREG7 lists the probe).
QUOTAS = [
    ("de_canton", "ZG", "answer", 8),
    ("de_canton", "ZG", "intervention", 7),
    ("de_commune", "1711", "answer", 4),  # Zug city
    ("de_commune", "1711", "intervention", 4),
    ("de_commune", "3427", "answer", 5),  # Wil SG
    ("de_commune", "3427", "intervention", 4),
    ("de_commune", "306", "answer", 5),  # Lyss
    ("de_commune", "306", "intervention", 3),
    ("de_commune", "2937", "answer", 5),  # Neuhausen am Rheinfall
    ("de_commune", "2937", "intervention", 4),
    ("de_commune", "581", "answer", 3),  # Interlaken
    ("de_commune", "581", "intervention", 3),
    ("fr_commune", "6023", "answer", 5),  # Conthey
    ("fr_commune", "6023", "intervention", 4),
    ("fr_commune", "6458", "answer", 5),  # Neuchâtel city
    ("fr_commune", "6037", "answer", 4),  # Val de Bagnes
    ("fr_commune", "6037", "intervention", 4),
]
# U2's P5 test bodies (data/gold6/p5_affairs.jsonl): never in P6, in addition to every P5/P5-dev affair and document
P5_BODIES = {"2703", "BL", "SH", "1061", "293", "5586", "VS", "6152", "5192", "GR"}
BODIES = sorted({q[1] for q in QUOTAS})


def draw() -> None:
    if DOCS.exists():
        raise SystemExit(f"{DOCS} exists")
    if LABELS.exists():
        raise SystemExit("P6 labels exist before the draw")
    x_docs, x_affs, x_bodies = C.exclusions(extra=[dev2.DOCS])
    clash = set(BODIES) & (x_bodies | P5_BODIES)
    assert not clash, f"P6 bodies already in an existing set: {clash}"
    assert (C.DATA / "gold6" / "p5_affairs.jsonl").exists(), "P5 affair list missing: exclusions would be incomplete"
    got, log = C.draw(QUOTAS, SEED, "p6", BAND, x_docs, x_affs)
    C.write_jsonl(DOCS, got)
    C.write_jsonl(LOG, log)
    print(collections.Counter((r["body"], r["dtype"]) for r in got), "total", len(got))
    print("shortfalls", [x for x in log if "shortfall" in x])


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
        rows.append(dict(doc_id=i, source="p6", cell=docs[i]["cell"], dtype=docs[i]["dtype"], body=docs[i]["body"],
                         labeller=f"claude-agents:{src}", answer_present=lab["answer_present"], answer_date=lab["answer_date"],
                         role=lab.get("role"), answer_date_page=lab.get("answer_date_page"),
                         answer_date_quote=(lab.get("answer_date_quote") or "")[:200],
                         answer_date_lenient=[x for x in len_ if x], decision_number=lab.get("decision_number")))
    if missing:
        raise SystemExit(f"tie-break missing for {missing}")
    if set(docs) - {r["doc_id"] for r in rows}:
        raise SystemExit(f"unlabelled P6 documents: {sorted(set(docs) - {r['doc_id'] for r in rows})}")
    C.write_jsonl(LABELS, rows)
    res = dict(n=len(rows), agreement=agree, decided_by_A3=sum(r["labeller"].endswith("A3") for r in rows),
               a3_order_randomised=True)
    (DATA / "p6" / "p6_agreement.json").write_text(json.dumps(res, indent=1))
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
