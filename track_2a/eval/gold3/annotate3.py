"""P3 gold labels: per-field labels of whole affairs from their documents only (eval/gold3/GUIDE.md), by two blind Claude-agent
annotators, a third on disagreeing fields only (X/Y order seeded random), every quote verified verbatim by code.

  packets                 .work/gold3/packets/<affair_id>.txt (question then answer document, page-delimited; never committed)
  verify <A1|A2|A3>       schema + verbatim quotes
  selfcheck <A> <id>      one file (annotators run this)
  disagreements           -> .work/gold3/disagreements.json  {affair_id: [fields]}
  a3packets               -> .work/gold3/a3/<affair_id>.json (both labels as X/Y, seeded random order; key kept apart)
  merge                   -> data/gold3/p3_labels.jsonl, data/gold3/annotations/*.jsonl, results/eval3/gold3_agreement.json
Disagreement keys (decided before any label): the single-valued fields below, with recommendation none ≡ not_applicable
and names compared by surname + first initial. Set fields (co_signatories, related_affairs) never trigger a tie-break:
the final set is what both annotators list; their Jaccard agreement is reported.
"""

from __future__ import annotations

import json
import random
import re
import sys

from eval.gold3.score3 import name_key, norm_num
from gegenprobe import pdftext
from gegenprobe.paths import DATA, RESULTS, WORK
from gegenprobe.stats import cohen_kappa

G = WORK / "gold3"
PACK, ANN = G / "packets", G / "ann"
GOLD3 = DATA / "gold3"
SEED = 20261013
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TYPES = {"interpellation", "motion", "postulate", "question", "resolution", "other", None}
ADDR = {"executive", "parliament", "committee", "administration", None}
REC = {"accept", "reject", "convert", "partial", "none", "not_applicable"}
PRESENT = {"yes", "no", "oral", "unclear"}
QUOTED = ("number", "submitter", "submitted", "answer_date")
KEYS = ("number", "affair_type", "submitter", "addressed_body", "submitted", "answer_present", "answer_date", "recommendation")


def affairs() -> list[dict]:
    return [json.loads(line) for line in open(GOLD3 / "p3_affairs.jsonl")]


def norm(s) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def packets() -> None:
    PACK.mkdir(parents=True, exist_ok=True)
    for a in affairs():
        parts = []
        for d in a["docs"]:
            t = pdftext.extract(d["sha256"], ocr=bool(d.get("image_only")))
            parts.append(
                f"=== DOCUMENT {d['role']} ===\n" + "".join(f"=== PAGE {i} ===\n{p}\n" for i, p in enumerate(t["pages"], 1))
            )
        (PACK / f"{a['affair_id']}.txt").write_text("\n".join(parts), encoding="utf-8")
    print(f"{len(affairs())} packets in {PACK}")


def _pages(affair_id: int) -> dict[str, list[str]]:
    txt = (PACK / f"{affair_id}.txt").read_text(encoding="utf-8")
    out = {}
    blocks = re.split(r"(?m)^=== DOCUMENT (question|answer) ===\n", txt)
    for role, body in zip(blocks[1::2], blocks[2::2]):
        out[role] = re.split(r"(?m)^=== PAGE \d+ ===\n", body)[1:]
    return out


def check(a: dict) -> list[str]:
    e = []
    if a.get("affair_type") not in TYPES:
        e.append("affair_type")
    if a.get("addressed_body") not in ADDR:
        e.append("addressed_body")
    if a.get("recommendation") not in REC:
        e.append("recommendation")
    if a.get("answer_present") not in PRESENT:
        e.append("answer_present")
    for f in ("submitted", "answer_date"):
        v = a.get(f)
        if v is not None and not ISO.match(str(v)):
            e.append(f"{f} format")
        for x in a.get(f + "_lenient") or []:
            if not ISO.match(str(x)):
                e.append(f"{f}_lenient format")
    if a.get("answer_date") is not None and a.get("role") not in ("decision", "dispatch"):
        e.append("role")
    for k in ("co_signatories", "related_affairs"):
        if not isinstance(a.get(k, []), list):
            e.append(k)
    pages = _pages(a["affair_id"])
    for f in QUOTED:
        if a.get(f) is None:
            continue
        doc, pg, q = a.get(f + "_doc"), a.get(f + "_page"), norm(a.get(f + "_quote"))
        if doc not in pages or not isinstance(pg, int) or not 1 <= pg <= len(pages[doc]):
            e.append(f"{f}_doc/{f}_page")
        elif not q or q not in norm(pages[doc][pg - 1]):
            e.append(f"{f}_quote not verbatim on page")
        elif len(q) > 200:
            e.append(f"{f}_quote > 200 chars")
    return e


def load(annotator: str) -> dict[int, dict]:
    return {
        int(json.loads(p.read_text())["affair_id"]): json.loads(p.read_text()) for p in sorted((ANN / annotator).glob("*.json"))
    }


def verify(annotator: str) -> int:
    got = load(annotator)
    bad = {k: v for k, v in ((k, check(a)) for k, a in got.items()) if v}
    want = {a["affair_id"] for a in affairs()}
    missing = sorted(want - set(got)) if annotator != "A3" else []
    print(f"{annotator}: {len(got)} labelled, {len(bad)} with errors, {len(missing)} missing")
    for k, v in sorted(bad.items()):
        print(" ", k, v)
    return 1 if bad or missing else 0


def key(f: str, v):
    if f == "recommendation":
        return None if v in ("none", "not_applicable") else v
    if f == "submitter":
        return name_key(v) if v else None
    if f == "number":
        return norm_num(v) if v else None
    return v


def disagreements() -> dict[int, list[str]]:
    a1, a2 = load("A1"), load("A2")
    out = {i: [f for f in KEYS if key(f, a1[i].get(f)) != key(f, a2[i].get(f))] for i in sorted(set(a1) & set(a2))}
    out = {i: v for i, v in out.items() if v}
    (G / "disagreements.json").write_text(json.dumps(out, indent=1))
    print(f"{len(out)} affairs with a disagreeing field; fields: {sum(len(v) for v in out.values())}")
    return out


def a3packets() -> None:
    dis = json.loads((G / "disagreements.json").read_text())
    a1, a2 = load("A1"), load("A2")
    (G / "a3").mkdir(parents=True, exist_ok=True)
    order = {}
    for i, fields in dis.items():
        flip = random.Random(f"{SEED}:{i}").random() < 0.5
        x, y = (a2[int(i)], a1[int(i)]) if flip else (a1[int(i)], a2[int(i)])
        order[i] = "X=A2" if flip else "X=A1"
        (G / "a3" / f"{i}.json").write_text(
            json.dumps(dict(affair_id=int(i), disputed_fields=fields, label_X=x, label_Y=y), ensure_ascii=False, indent=1)
        )
    (G / "a3_order.json").write_text(json.dumps(order, indent=1))
    print(f"{len(dis)} tie-break packets")


def merge() -> None:
    a1, a2, a3 = load("A1"), load("A2"), load("A3")
    dis = json.loads((G / "disagreements.json").read_text()) if (G / "disagreements.json").exists() else {}
    ids = sorted(set(a1) & set(a2))
    agree = {}
    for f in KEYS:
        x, y = [str(key(f, a1[i].get(f))) for i in ids], [str(key(f, a2[i].get(f))) for i in ids]
        agree[f] = dict(raw=sum(p == q for p, q in zip(x, y)), n=len(ids), kappa=cohen_kappa(x, y))
    jac = {}
    for f in ("co_signatories", "related_affairs"):
        k = name_key if f == "co_signatories" else norm_num
        num = den = 0
        for i in ids:
            s1, s2 = {str(k(v)) for v in a1[i].get(f) or []}, {str(k(v)) for v in a2[i].get(f) or []}
            num += len(s1 & s2)
            den += len(s1 | s2)
        jac[f] = dict(intersection=num, union=den, jaccard=num / den if den else None)
    rows, missing = [], []
    for i in ids:
        lab = dict(a1[i])
        for f in dis.get(str(i), []):
            if i not in a3:
                missing.append(i)
                break
            for suffix in ("", "_quote", "_doc", "_page", "_lenient"):
                if f + suffix in a3[i]:
                    lab[f + suffix] = a3[i][f + suffix]
            if f == "answer_date":
                lab["role"] = a3[i].get("role")
        for f in ("co_signatories", "related_affairs"):
            k = name_key if f == "co_signatories" else norm_num
            keep2 = {str(k(v)) for v in a2[i].get(f) or []}
            lab[f] = [v for v in a1[i].get(f) or [] if str(k(v)) in keep2]
        lab["labeller"] = "claude-agents:" + ("A3 on " + ",".join(dis[str(i)]) if str(i) in dis else "A1=A2")
        for f in QUOTED:
            if lab.get(f + "_quote"):
                lab[f + "_quote"] = lab[f + "_quote"][:200]
        rows.append(lab)
    if missing:
        raise SystemExit(f"tie-break missing for {sorted(set(missing))}")
    with open(GOLD3 / "p3_labels.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (GOLD3 / "annotations").mkdir(exist_ok=True)
    for name, d in (("A1", a1), ("A2", a2), ("A3", a3)):
        with open(GOLD3 / "annotations" / f"{name}.jsonl", "w") as f:
            for v in d.values():
                f.write(json.dumps(v, ensure_ascii=False) + "\n")
    res = dict(
        n=len(rows),
        agreement=agree,
        set_agreement=jac,
        tie_broken_affairs=len(dis),
        tie_broken_fields=sum(len(v) for v in dis.values()),
        a3_order_randomised=True,
    )
    out = RESULTS / "eval3" / "gold3_agreement.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "packets":
        packets()
    elif cmd == "verify":
        sys.exit(verify(sys.argv[2]))
    elif cmd == "selfcheck":
        a = json.loads((ANN / sys.argv[2] / f"{sys.argv[3]}.json").read_text())
        e = check(a)
        print("OK" if not e else f"ERRORS: {e}")
        sys.exit(1 if e else 0)
    elif cmd == "disagreements":
        disagreements()
    elif cmd == "a3packets":
        a3packets()
    elif cmd == "merge":
        merge()
