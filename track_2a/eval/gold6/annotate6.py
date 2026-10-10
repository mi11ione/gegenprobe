"""P5 labels (dev and test): blind agent annotators label each affair from its packet with eval/gold6/GUIDE_P5.md; every
quote is resolved to a character span by code (whitespace-insensitive, otherwise verbatim); a third annotator decides
disputed fields only, seeing both labels as X/Y in seeded random order.

    python -m eval.gold6.annotate6 <split> selfcheck <A> <affair_id>   one file (annotators run this)
    python -m eval.gold6.annotate6 <split> verify <A>                  all files of one annotator
    python -m eval.gold6.annotate6 <split> disagreements               -> <work>/disagreements.json
    python -m eval.gold6.annotate6 <split> a3packets                   -> <work>/a3/<affair_id>.json (+ a3_order.json)
    python -m eval.gold6.annotate6 <split> merge                       -> data/gold6/<split>_labels.jsonl, annotations,
                                                                          results/eval6/<split>_agreement.json
split = p5dev (.work/p5dev) | p5 (.work/p5). Annotator files: <work>/ann/<A>/<affair_id>.json.

Resolved spans: {doc, page, char_start, end_page, char_end, g_start, g_end}; char offsets index pages[page-1] of the
cached text; g_* are offsets into the document's pages joined with "\\n" (as `convert.pointer.doc_text` joins them).
"""

from __future__ import annotations

import json
import random
import re
import sys

from eval.gold6 import common6 as C
from gegenprobe.paths import RESULTS, WORK

REC = ("accept", "reject", "partial", "convert", "none", "not_applicable")
QSTYLE = ("enumerated", "single", "running_text", "none")
ASTYLE = ("per_question", "global", "mixed", "no_answer")
KEYS = ("affair_id", "questions", "question_style", "answer_style", "answers", "submitter", "co_signatories",
        "recommendation", "recommendation_quote", "reasoning", "notes")
SPLITS = {"p5dev": dict(work=WORK / "p5dev", seed=20261021), "p5": dict(work=WORK / "p5", seed=20261031)}


# ------------------------------------------------------------------------------------------------ quote resolution
def _rx(quote: str) -> re.Pattern:
    toks = quote.split()
    return re.compile(r"\s*".join(re.escape(t) for t in toks)) if toks else re.compile(r"(?!)")


def find(text: str, quote: str, at: int = 0) -> list[tuple[int, int]]:
    """Every (start, end) where `quote` occurs in text[at:], whitespace-insensitive (whitespace may also be absent between
    tokens: pdftotext sometimes drops it)."""
    return [(m.start(), m.end()) for m in _rx(quote).finditer(text, at)]


def g_off(pages: list[str], page: int, ch: int) -> int:
    return sum(len(p) + 1 for p in pages[: page - 1]) + ch


def resolve_span(sp: dict, docs: dict[str, list[str]]) -> tuple[dict | None, str | None]:
    """A SPAN label -> resolved span, or (None, error)."""
    if not isinstance(sp, dict):
        return None, "span is not an object"
    doc, pg, epg = sp.get("doc"), sp.get("page"), sp.get("end_page", sp.get("page"))
    if doc not in docs:
        return None, f"doc {doc!r}"
    pages = docs[doc]
    if not (isinstance(pg, int) and isinstance(epg, int) and 1 <= pg <= epg <= len(pages)):
        return None, f"page/end_page {pg}/{epg} of {len(pages)}"
    st = find(pages[pg - 1], sp.get("start") or "")
    if not st:
        return None, f"start quote not on page {pg}: {(sp.get('start') or '')[:50]!r}"
    if len(st) > 1:
        return None, f"start quote occurs {len(st)} times on page {pg}: make it longer"
    s = st[0][0]
    en = find(pages[epg - 1], sp.get("end") or "", s if epg == pg else 0)
    if not en:
        return None, f"end quote not on page {epg} after the start: {(sp.get('end') or '')[:50]!r}"
    e = en[0][1]
    return dict(doc=doc, page=pg, char_start=s, end_page=epg, char_end=e, g_start=g_off(pages, pg, s),
                g_end=g_off(pages, epg, e)), None


def resolve_point(q: dict, docs: dict[str, list[str]], maxlen: int) -> tuple[dict | None, str | None]:
    if not isinstance(q, dict):
        return None, "not an object"
    doc, pg, quote = q.get("doc"), q.get("page"), q.get("quote") or ""
    if doc not in docs or not isinstance(pg, int) or not 1 <= pg <= len(docs[doc]):
        return None, f"doc/page {doc!r}/{pg}"
    if len(" ".join(quote.split())) > maxlen:
        return None, f"quote > {maxlen} chars"
    hits = find(docs[doc][pg - 1], quote)
    if not hits:
        return None, f"quote not on page: {quote[:50]!r}"
    s, e = hits[0]
    return dict(doc=doc, page=pg, char_start=s, char_end=e, g_start=g_off(docs[doc], pg, s), g_end=g_off(docs[doc], pg, e)), None


# ------------------------------------------------------------------------------------------------ checking one label file
def check(a: dict, docs: dict[str, list[str]]) -> tuple[list[str], dict]:
    """(errors, resolved label)."""
    e: list[str] = []
    missing = [k for k in KEYS if k not in a]
    if missing:
        e.append(f"missing keys {missing}")
    extra = [k for k in a if k not in KEYS]
    if extra:
        e.append(f"unknown keys {extra}")
    if a.get("question_style") not in QSTYLE:
        e.append("question_style")
    if a.get("answer_style") not in ASTYLE:
        e.append("answer_style")
    if a.get("recommendation") not in REC:
        e.append("recommendation")
    out = dict(affair_id=a.get("affair_id"), question_style=a.get("question_style"), answer_style=a.get("answer_style"),
               recommendation=a.get("recommendation"), notes=a.get("notes"))
    qs = a.get("questions") or []
    ns = [q.get("n") for q in qs if isinstance(q, dict)]
    if ns != list(range(1, len(qs) + 1)):
        e.append(f"questions must be numbered 1..k in order, got {ns}")
    if a.get("question_style") in ("none", "running_text") and qs:
        e.append(f"question_style {a.get('question_style')} but questions given")
    if a.get("question_style") == "single" and len(qs) != 1:
        e.append("question_style single needs exactly one question")
    if a.get("question_style") == "enumerated" and len(qs) < 2:
        e.append("question_style enumerated needs >= 2 items")
    out["questions"] = []
    for q in qs:
        r, err = resolve_span(q.get("span"), docs)
        if err:
            e.append(f"question {q.get('n')}: {err}")
        elif r["doc"] != "question":
            e.append(f"question {q.get('n')}: span must be in the question document")
        out["questions"].append(dict(n=q.get("n"), span=r))
    ans = a.get("answers") or []
    if [x.get("n") for x in ans if isinstance(x, dict)] != ns:
        e.append("answers must have one entry per question, same n, same order")
    out["answers"] = []
    for x in ans:
        r = None
        if x.get("span") is not None:
            r, err = resolve_span(x["span"], docs)
            if err:
                e.append(f"answer {x.get('n')}: {err}")
            elif r["doc"] != "answer":
                e.append(f"answer {x.get('n')}: span must be in the answer document")
        jw = x.get("joint_with") or []
        if not isinstance(jw, list) or any(j not in ns or j == x.get("n") for j in jw):
            e.append(f"answer {x.get('n')}: joint_with {jw}")
        out["answers"].append(dict(n=x.get("n"), span=r, joint_with=sorted(jw) if isinstance(jw, list) else []))
    if a.get("answer_style") in ("global", "no_answer") and any(x["span"] for x in out["answers"]):
        e.append(f"answer_style {a.get('answer_style')} but answer spans given")
    if a.get("answer_style") == "per_question" and any(x["span"] is None for x in out["answers"]) and ans:
        e.append("answer_style per_question but an answer span is null (use mixed)")
    out["people"] = []
    sub = a.get("submitter")
    if sub is not None:
        r, err = resolve_point(sub, docs, 120)
        if err:
            e.append(f"submitter: {err}")
        elif not _name_in(sub.get("name"), docs[sub["doc"]][sub["page"] - 1][r["char_start"]:r["char_end"]]):
            e.append("submitter: name's surname not inside the quote")
        out["people"].append(dict(role="submitter", name=sub.get("name"), loc=r))
    for i, c in enumerate(a.get("co_signatories") or []):
        r, err = resolve_point(c, docs, 120)
        if err:
            e.append(f"co_signatory {i}: {err}")
        elif not _name_in(c.get("name"), docs[c["doc"]][c["page"] - 1][r["char_start"]:r["char_end"]]):
            e.append(f"co_signatory {i}: name's surname not inside the quote")
        out["people"].append(dict(role="co_signatory", name=c.get("name"), loc=r))
    rq = a.get("recommendation_quote")
    out["recommendation_quote"] = None
    if a.get("recommendation") in ("none", "not_applicable"):
        if rq is not None:
            e.append("recommendation_quote must be null for none/not_applicable")
    elif rq is None:
        e.append("recommendation_quote missing")
    else:
        r, err = resolve_point(rq, docs, 200)
        if err:
            e.append(f"recommendation_quote: {err}")
        elif r["doc"] != "answer":
            e.append("recommendation_quote must be in the answer document")
        out["recommendation_quote"] = r
    out["reasoning"] = None
    if a.get("reasoning") is not None:
        r, err = resolve_span(a["reasoning"], docs)
        if err:
            e.append(f"reasoning: {err}")
        elif r["doc"] != "answer":
            e.append("reasoning must be in the answer document")
        out["reasoning"] = r
    return e, out


def _name_in(name, quote: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    last = name.split()[-1]
    return C.fold(last) in C.fold(quote)


# ------------------------------------------------------------------------------------------------ split plumbing
def _rows(split: str) -> list[dict]:
    if split == "p5dev":
        from eval.gold6 import dev6

        return dev6.rows()
    return [json.loads(line) for line in open(C.GOLD6 / "p5_affairs.jsonl")]


def _docs(split: str, affair_id: int) -> dict[str, list[str]]:
    """The cached page texts (sha256-keyed) the packet was printed from; spans index into these."""
    row = next(r for r in _rows(split) if r["affair_id"] == int(affair_id))
    return C.texts(row)


def load(split: str, annotator: str) -> dict[int, dict]:
    d = SPLITS[split]["work"] / "ann" / annotator
    return {int(json.loads(p.read_text())["affair_id"]): json.loads(p.read_text()) for p in sorted(d.glob("*.json"))}


def selfcheck(split: str, annotator: str, affair_id: int) -> int:
    a = json.loads((SPLITS[split]["work"] / "ann" / annotator / f"{affair_id}.json").read_text())
    errs, _ = check(a, _docs(split, int(affair_id)))
    print("OK" if not errs else "ERRORS:\n  " + "\n  ".join(errs))
    return 1 if errs else 0


def verify(split: str, annotator: str) -> int:
    got = load(split, annotator)
    bad = {}
    for k, a in got.items():
        errs, _ = check(a, _docs(split, k))
        if errs:
            bad[k] = errs
    want = {r["affair_id"] for r in _rows(split)}
    missing = sorted(want - set(got)) if annotator != "A3" else []
    print(f"{annotator}: {len(got)} labelled, {len(bad)} with errors, {len(missing)} missing {missing}")
    for k, v in sorted(bad.items()):
        print(" ", k, v)
    return 1 if bad or missing else 0


# ------------------------------------------------------------------------------------------------ agreement keys
def iou(a: dict | None, b: dict | None) -> float:
    if a is None or b is None or a["doc"] != b["doc"]:
        return 0.0
    inter = max(0, min(a["g_end"], b["g_end"]) - max(a["g_start"], b["g_start"]))
    union = max(a["g_end"], b["g_end"]) - min(a["g_start"], b["g_start"])
    return inter / union if union > 0 else 0.0


def name_key(n: str | None) -> str | None:
    if not n:
        return None
    parts = C.fold(n).replace("-", " ").split()
    return parts[-1] if parts else None


def field_keys(r: dict) -> dict:
    """Comparable view of a resolved label (agreement and disagreement detection)."""
    return dict(
        n_questions=len(r["questions"]),
        answer_style=r["answer_style"],
        recommendation=r["recommendation"],
        submitter=next((name_key(p["name"]) for p in r["people"] if p["role"] == "submitter"), None),
    )


def agree_fields(r1: dict, r2: dict) -> list[str]:
    """Fields on which two resolved labels disagree (decided before any label): question count; any question span IoU <
    0.5; answer style; any answer pair where one is null and the other not, or IoU < 0.5; submitter surname;
    recommendation; reasoning IoU < 0.5 (or one null). Co-signatories are a set: never tie-broken, intersection kept."""
    out = []
    if len(r1["questions"]) != len(r2["questions"]) or any(
        iou(a["span"], b["span"]) < 0.5 for a, b in zip(r1["questions"], r2["questions"])
    ):
        out.append("questions")
    if len(r1["answers"]) != len(r2["answers"]) or any(
        (a["span"] is None) != (b["span"] is None) or (a["span"] and iou(a["span"], b["span"]) < 0.5)
        for a, b in zip(r1["answers"], r2["answers"])
    ):
        out.append("answers")
    k1, k2 = field_keys(r1), field_keys(r2)
    for f in ("submitter", "recommendation"):
        if k1[f] != k2[f]:
            out.append(f)
    if (r1["reasoning"] is None) != (r2["reasoning"] is None) or (r1["reasoning"] and iou(r1["reasoning"], r2["reasoning"]) < 0.5):
        out.append("reasoning")
    return out


def resolved(split: str, annotator: str) -> dict[int, dict]:
    out = {}
    for k, a in load(split, annotator).items():
        errs, r = check(a, _docs(split, k))
        if errs:
            raise SystemExit(f"{annotator} {k}: unresolved errors {errs}")
        out[k] = r
    return out


def disagreements(split: str) -> dict:
    w = SPLITS[split]["work"]
    r1, r2 = resolved(split, "A1"), resolved(split, "A2")
    out = {str(i): agree_fields(r1[i], r2[i]) for i in sorted(set(r1) & set(r2))}
    out = {i: v for i, v in out.items() if v}
    (w / "disagreements.json").write_text(json.dumps(out, indent=1))
    print(f"{len(out)} affairs with a disagreeing field; fields: {sum(len(v) for v in out.values())}")
    return out


def a3packets(split: str) -> None:
    w = SPLITS[split]["work"]
    dis = json.loads((w / "disagreements.json").read_text())
    a1, a2 = load(split, "A1"), load(split, "A2")
    (w / "a3").mkdir(parents=True, exist_ok=True)
    order = {}
    for i, fields in dis.items():
        flip = random.Random(f"{SPLITS[split]['seed']}:{i}").random() < 0.5
        x, y = (a2[int(i)], a1[int(i)]) if flip else (a1[int(i)], a2[int(i)])
        order[i] = "X=A2" if flip else "X=A1"
        (w / "a3" / f"{i}.json").write_text(
            json.dumps(dict(affair_id=int(i), disputed_fields=fields, label_X=x, label_Y=y), ensure_ascii=False, indent=1))
    (w / "a3_order.json").write_text(json.dumps(order, indent=1))
    print(f"{len(dis)} tie-break packets in {w / 'a3'}")


FIELD_KEYS = {  # label keys that travel with a disputed field when A3 decides it
    "questions": ("questions", "question_style", "answers", "answer_style"),
    "answers": ("answers", "answer_style"),
    "submitter": ("submitter",),
    "recommendation": ("recommendation", "recommendation_quote"),
    "reasoning": ("reasoning",),
}


def merge(split: str) -> None:
    from gegenprobe.stats import cohen_kappa

    w = SPLITS[split]["work"]
    out_labels = C.GOLD6 / f"{split}_labels.jsonl"
    a1, a2 = load(split, "A1"), load(split, "A2")
    a3 = load(split, "A3") if (w / "ann" / "A3").exists() else {}
    dis = json.loads((w / "disagreements.json").read_text()) if (w / "disagreements.json").exists() else {}
    ids = sorted(set(a1) & set(a2))
    rows, missing = [], []
    for i in ids:
        lab = dict(a1[i])
        fields = dis.get(str(i), [])
        if fields and i not in a3:
            missing.append(i)
            continue
        for f in fields:
            for k in FIELD_KEYS[f]:
                if k in a3[i]:
                    lab[k] = a3[i][k]
        k2 = {name_key(c.get("name")) for c in a2[i].get("co_signatories") or []}
        lab["co_signatories"] = [c for c in a1[i].get("co_signatories") or [] if name_key(c.get("name")) in k2]
        errs, r = check(lab, _docs(split, i))
        if errs:
            raise SystemExit(f"merged label {i} invalid: {errs}")
        r["labeller"] = "claude-agents:" + ("A3 on " + ",".join(fields) if fields else "A1=A2")
        rows.append(r)
    if missing:
        raise SystemExit(f"tie-break missing for {missing}")
    C.GOLD6.mkdir(parents=True, exist_ok=True)
    with open(out_labels, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    adir = C.GOLD6 / "annotations" / split
    adir.mkdir(parents=True, exist_ok=True)
    for name, d in (("A1", a1), ("A2", a2), ("A3", a3)):
        with open(adir / f"{name}.jsonl", "w") as f:
            for v in d.values():
                f.write(json.dumps(v, ensure_ascii=False) + "\n")
    r1, r2 = resolved(split, "A1"), resolved(split, "A2")
    agree = {}
    for f in ("n_questions", "answer_style", "recommendation", "submitter"):
        x = [str(field_keys(r1[i])[f]) for i in ids]
        y = [str(field_keys(r2[i])[f]) for i in ids]
        agree[f] = dict(raw=sum(p == q for p, q in zip(x, y)), n=len(ids), kappa=cohen_kappa(x, y))
    for f in ("questions", "answers", "reasoning"):
        n_dis = sum(f in dis.get(str(i), []) for i in ids)
        agree[f] = dict(raw=len(ids) - n_dis, n=len(ids), rule="IoU >= 0.5 per span (agree_fields)")
    res = dict(split=split, n=len(rows), agreement=agree, tie_broken_affairs=len(dis),
               tie_broken_fields=sum(len(v) for v in dis.values()), a3_order_randomised=True)
    (RESULTS / "eval6").mkdir(parents=True, exist_ok=True)
    (RESULTS / "eval6" / f"{split}_agreement.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    split, cmd = sys.argv[1], sys.argv[2]
    if split not in SPLITS:
        raise SystemExit(f"split must be one of {list(SPLITS)}")
    if cmd == "selfcheck":
        sys.exit(selfcheck(split, sys.argv[3], int(sys.argv[4])))
    elif cmd == "verify":
        sys.exit(verify(split, sys.argv[3]))
    elif cmd == "disagreements":
        disagreements(split)
    elif cmd == "a3packets":
        a3packets(split)
    elif cmd == "merge":
        merge(split)
    else:
        raise SystemExit(f"unknown command {cmd}")
