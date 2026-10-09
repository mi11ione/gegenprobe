"""Held-out gold labels without human judgement (docs/gold_protocol.md): two blind Claude-agent annotators, a third agent on
disagreements only, quotes verified by code, κ reported, OPD event dates used only as an external check.

  packets                 write .work/gold/packets/<doc_id>.txt (page-delimited text) + .work/gold/packets/index.json
  verify  <annotator>     check .work/gold/ann/<annotator>/<doc_id>.json against the packet: schema, ISO dates, verbatim quotes
  disagreements           list docs where A1 and A2 differ (input for A3) -> .work/gold/disagreements.json
  merge                   final labels -> data/gold/heldout_labels.jsonl; agreement -> results/eval/gold_agreement.json

Annotator output (one JSON per document):
  {"doc_id": int, "answer_present": "yes"|"no"|"oral"|"unclear",
   "answer_date": "YYYY-MM-DD"|null, "role": "decision"|"dispatch"|null,
   "answer_date_page": int|null, "answer_date_quote": str|null,
   "answer_date_lenient": ["YYYY-MM-DD", ...], "decision_number": str|null,
   "recommendation": "accept"|"reject"|"convert"|"partial"|"none"|"not_applicable",
   "recommendation_quote": str|null, "notes": str}
Only short quotes (<= 200 chars) leave .work; document texts never do.
"""
from __future__ import annotations

import collections
import json
import re
import sys

from gegenprobe import pdftext
from gegenprobe.paths import DATA, RESULTS, WORK
from gegenprobe.stats import cohen_kappa

G = WORK / "gold"
PACK = G / "packets"
ANN = G / "ann"
REC = {"accept", "reject", "convert", "partial", "none", "not_applicable"}
PRESENT = {"yes", "no", "oral", "unclear"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def heldout_docs() -> list[dict]:
    return [json.loads(line) for line in open(DATA / "gold" / "heldout_docs.jsonl")]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def packets() -> None:
    PACK.mkdir(parents=True, exist_ok=True)
    idx = []
    for d in heldout_docs():
        t = pdftext.extract(d["sha256"], ocr=d.get("image_only", False))
        body = "".join(f"\n=== PAGE {i} ===\n{p}" for i, p in enumerate(t["pages"], 1))
        (PACK / f"{d['doc_id']}.txt").write_text(body.lstrip("\n"), encoding="utf-8")
        idx.append(dict(doc_id=d["doc_id"], pages=len(t["pages"]), chars=sum(map(len, t["pages"])), extractor=t["extractor"]))
    (PACK / "index.json").write_text(json.dumps(idx, indent=0))
    print(f"{len(idx)} packets in {PACK}")


def _pages(doc_id: int) -> list[str]:
    txt = (PACK / f"{doc_id}.txt").read_text(encoding="utf-8")
    return [p for p in re.split(r"(?:^|\n)=== PAGE \d+ ===\n", txt)][1:] if txt.startswith("=== PAGE") else [txt]


def check(a: dict) -> list[str]:
    errs = []
    if a.get("answer_present") not in PRESENT:
        errs.append("answer_present")
    if a.get("recommendation") not in REC:
        errs.append("recommendation")
    v = a.get("answer_date")
    if v is not None:
        if not ISO.match(str(v)):
            errs.append("answer_date format")
        if a.get("role") not in ("decision", "dispatch"):
            errs.append("role")
        pages = _pages(a["doc_id"])
        pg, q = a.get("answer_date_page"), norm(a.get("answer_date_quote"))
        if not isinstance(pg, int) or not 1 <= pg <= len(pages):
            errs.append("answer_date_page")
        elif not q or q not in norm(pages[pg - 1]):
            errs.append("answer_date_quote not verbatim on page")
        elif len(q) > 200:
            errs.append("quote > 200 chars")
    for x in a.get("answer_date_lenient") or []:
        if not ISO.match(str(x)):
            errs.append("lenient format")
    return errs


def load(annotator: str) -> dict[int, dict]:
    out = {}
    for f in sorted((ANN / annotator).glob("*.json")):
        a = json.loads(f.read_text())
        out[int(a["doc_id"])] = a
    return out


def verify(annotator: str) -> int:
    docs = heldout_docs()
    got = load(annotator)
    bad = {d: check(a) for d, a in got.items()}
    bad = {d: e for d, e in bad.items() if e}
    missing = [d["doc_id"] for d in docs if d["doc_id"] not in got]
    print(f"{annotator}: {len(got)}/{len(docs)} labelled, {len(bad)} with errors, {len(missing)} missing")
    for d, e in sorted(bad.items()):
        print(" ", d, e)
    (G / f"verify_{annotator}.json").write_text(json.dumps(dict(bad=bad, missing=missing), indent=1))
    return 1 if bad or missing else 0


def key(a: dict) -> tuple:
    """What must agree for a label to be accepted without the tie-break."""
    return (a["answer_date"], a["recommendation"])


def disagreements() -> list[int]:
    a1, a2 = load("A1"), load("A2")
    diff = [d for d in sorted(a1) if d in a2 and key(a1[d]) != key(a2[d])]
    (G / "disagreements.json").write_text(json.dumps(diff))
    print(f"{len(diff)} disagreements of {len(a1)}")
    return diff


def opd_answer_dates(affairs: set[int]) -> dict[int, list[str]]:
    """Affair id -> OPD written-answer event dates (structured oracle) from the vendored census events table, classified with
    the census definition (census.defs.classify_event)."""
    from gegenprobe.census import defs, tables
    out = collections.defaultdict(list)
    for e in tables.rows("events"):
        a = tables.i(e["affair"])
        if a in affairs and e["date"] and defs.classify_event(e["title"], tables.i(e["hid"])) == "written":
            out[a].append(e["date"][:10])
    return out


def merge() -> None:
    docs = {d["doc_id"]: d for d in heldout_docs()}
    a1, a2 = load("A1"), load("A2")
    a3 = load("A3")
    ids = sorted(set(a1) & set(a2))
    agree = {}
    for f in ("answer_present", "answer_date", "recommendation"):
        x, y = [str(a1[i][f]) for i in ids], [str(a2[i][f]) for i in ids]
        agree[f] = dict(raw=sum(p == q for p, q in zip(x, y)), n=len(ids), kappa=cohen_kappa(x, y))
    rows, by_a3, missing_a3 = [], 0, []
    for i in ids:
        if key(a1[i]) == key(a2[i]):
            lab = a1[i]
            src = "A1=A2"
        elif i in a3:
            lab, src = a3[i], "A3"
            by_a3 += 1
        else:
            missing_a3.append(i)
            continue
        d = docs[i]
        len_ = sorted(set((a1[i].get("answer_date_lenient") or []) + (a2[i].get("answer_date_lenient") or []))
                      | ({a1[i]["answer_date"], a2[i]["answer_date"]} - {None, lab["answer_date"]}))
        rows.append(dict(doc_id=i, source="heldout", cell=d["cell"], dtype=d["dtype"], labeller=f"claude-agents:{src}",
                         answer_present=lab["answer_present"], answer_date=lab["answer_date"], role=lab.get("role"),
                         answer_date_page=lab.get("answer_date_page"),
                         answer_date_quote=(lab.get("answer_date_quote") or "")[:200],
                         answer_date_lenient=[x for x in len_ if x], decision_number=lab.get("decision_number"),
                         recommendation=lab["recommendation"]))
    if missing_a3:
        raise SystemExit(f"tie-break missing for {missing_a3}")
    with open(DATA / "gold" / "heldout_labels.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # external check against OPD answer-event dates (structured oracle; never used to set labels)
    oracle = opd_answer_dates({d['affair_id'] for d in docs.values() if d.get('affair_id')})
    ext = collections.Counter()
    mism = []
    for r in rows:
        od = oracle.get(docs[r["doc_id"]]["affair_id"]) or []
        if r["answer_date"] and od:
            ok = r["answer_date"] in od
            ext["match" if ok else "mismatch"] += 1
            if not ok:
                mism.append(dict(doc_id=r["doc_id"], label=r["answer_date"], opd=od, quote=r["answer_date_quote"]))
        elif r["answer_date"]:
            ext["no_oracle"] += 1
    res = dict(n=len(rows), agreement=agree, decided_by_A3=by_a3, oracle=dict(ext), oracle_mismatches=mism)
    out = RESULTS / "eval" / "gold_agreement.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in res.items() if k != "oracle_mismatches"}, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "packets":
        packets()
    elif cmd == "verify":
        sys.exit(verify(sys.argv[2]))
    elif cmd == "disagreements":
        disagreements()
    elif cmd == "merge":
        merge()
