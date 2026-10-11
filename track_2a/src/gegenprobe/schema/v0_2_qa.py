"""Question/answer pairing (question n -> answer n) in the converter's product records: `qa[].items`.

    python -m gegenprobe.schema.v0_2_qa detect    run the P5 pairing rules (gegenprobe.qa.extract, rules route, no model) over
                                                  the P3 and P3b documents (cached texts in WORK) ->
                                                  results/schema/v0_2/qa_pairs.jsonl
    python -m gegenprobe.schema.v0_2_qa --check   exit 1 if a fresh detection differs from the committed file (SKIP when
                                                  the texts are not cached)

The P5 records carry the pairing of the frozen P5 rules (results/eval6/p5__none.json, `R.records`); the product records
of P3 and P3b (and `python -m gegenprobe affair`) left `qa[].items` empty with the reason "this record's path does not
pair numbered questions with answers". `pair` runs the same function the P5 rules arm ran (gegenprobe.qa.extract.extract,
backend None: rules only, frozen under LOCK6) on the question and answer document of an affair; `with_qa` puts its items
into the record's Q/A block and replaces the empty-list reason:

  * questions found (enumerated, or a single question / request): one item per question, the question's span and the
    answer passage's span where the rules locate one, else a typed null (present_unanchored: the reply does not mark
    which passage answers it; not_in_document: no reply found); route `rule` (`ocr+rule` on an OCR text)
  * no question printed (style none): reason none_printed
  * several questions in running text without markers: reason present_unanchored (the rules do not split them)

Only `qa[0].items`, its empty-list reason and a sentence in `extraction.notes` change (`strip_qa` undoes the overlay
exactly; tests/test_schema_v0_2_qa.py). gegenprobe.schema.v0_2_parts applies it after the document parts;
gegenprobe.affair_cli applies it to the documents it fetched.
"""
from __future__ import annotations

import copy
import json
import sys

from ..paths import ROOT
from . import v0_2_roles
from .p8_v0_2 import OUT

PAIRS = OUT / "qa_pairs.jsonl"
SETS = ("p3", "p3b")
OVERLAY = "gegenprobe.schema.v0_2_qa.with_qa"
RULES = "gegenprobe.qa.extract (the P5 rules arm, no model)"
OLD_REASON = ("not_extracted", "rule", "this record's path does not pair numbered questions with answers")


def _ocr(extractor: str | None) -> bool:
    return str(extractor or "").startswith("tesseract")


def pair(q: tuple[list[str], str, str] | None, a: tuple[list[str], str, str] | None, lang: str | None) -> dict:
    """The rules' pairing of one affair. q, a: (pages, doc_id, extractor) of the question and answer document (None when
    the affair has no such document). Returns {style, rules, n_questions, n_answers_located, items}: items are schema
    QAItem dicts (question n, answer n), values located on the documents' pages."""
    from ..qa import extract as X

    res = X.extract(q[0] if q else None, a[0] if a else None, lang or "de", None, None,
                    q[1] if q else "question", a[1] if a else "answer")
    ocr = {d[1] for d in (q, a) if d and _ocr(d[2])}
    items = res["records"]["qa_items"]
    for it in items:
        for k in ("question", "answer"):
            v = it[k]
            if v.get("route") == "rule" and v.get("doc") in ocr:
                v["route"] = "ocr+rule"
    return dict(style=res["view"]["question_style"], rules=res["rules"], n_questions=len(items),
                n_answers_located=sum(it["answer"].get("kind") == "value" for it in items), items=items)


def _reason(p: dict, doc: str | None) -> dict:
    if p["style"] == "running_text":
        return dict(reason="present_unanchored", route="rule", **({"doc": doc} if doc else {}),
                    evidence=f"{RULES}: the member's text asks several questions in running text without markers; the "
                             "rules do not split them into items")
    return dict(reason="none_printed", route="rule", **({"doc": doc} if doc else {}),
                evidence=f"{RULES}: no question printed in the member's text (style {p['style']})")


def _note(p: dict) -> str:
    return (f"Q/A pairing by {OVERLAY} ({RULES}): {p['n_questions']} questions ({p['style']}), "
            f"{p['n_answers_located']} answer passages located")


def with_qa(rec: dict, p: dict | None) -> dict:
    """The record with the pairing `p` (from `pair` or the committed qa_pairs.jsonl) in qa[0].items. A record without a
    Q/A block, or without a pairing, is returned unchanged."""
    if p is None or not rec.get("qa"):
        return rec
    rec = copy.deepcopy(rec)
    key = "qa.0.items"
    if p["items"]:
        rec["qa"][0]["items"] = copy.deepcopy(p["items"])
        rec["empty_reasons"].pop(key, None)
    else:
        rec["empty_reasons"][key] = _reason(p, rec["qa"][0].get("question_doc"))
    ex = rec["extraction"]
    ex["notes"] = f"{ex['notes']}; {_note(p)}" if ex.get("notes") else _note(p)
    return rec


def strip_qa(rec: dict) -> dict:
    """Undo `with_qa` (for the test that the overlay changes nothing else)."""
    rec = copy.deepcopy(rec)
    ex = rec["extraction"]
    notes = (ex.get("notes") or "").split("; ")
    if not any(x.startswith(f"Q/A pairing by {OVERLAY}") for x in notes):
        return rec
    ex["notes"] = "; ".join(x for x in notes if not x.startswith(f"Q/A pairing by {OVERLAY}"))
    rec["qa"][0]["items"] = []
    reason, route, ev = OLD_REASON
    rec["empty_reasons"]["qa.0.items"] = dict(reason=reason, route=route, evidence=ev)
    return rec


# ----------------------------------------------------------------------------------------------------------- detection
def _rows() -> list[tuple[str, dict]]:
    out = []
    for set_name, path in v0_2_roles.SETS:
        if set_name not in SETS:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append((set_name, json.loads(line)))
    return out


def detect() -> tuple[str | None, list[str]]:
    """(qa_pairs.jsonl's text, documents not cached); text None when any is missing."""
    missing: list[str] = []
    rows = []
    for set_name, r in _rows():
        docs = {d["role"]: d for d in r["docs"]}
        got = {}
        for role, d in docs.items():
            pg = v0_2_roles.pages_of(d["sha256"], bool(d.get("image_only")))
            if pg is None:
                missing.append(f"{set_name}:{r['affair_id']}:{role}")
                continue
            got[role] = (pg[0], f"opd:{d['doc_id']}", pg[1])
        if len(got) < len(docs) or "answer" not in got:
            continue
        p = pair(got.get("question"), got["answer"], r.get("lang"))
        rows.append(dict(set=set_name, affair_id=r["affair_id"], body=r["body"],
                         question_doc=got["question"][1] if "question" in got else None, answer_doc=got["answer"][1],
                         sha256={role: docs[role]["sha256"] for role in sorted(got)},
                         extractor={role: got[role][2] for role in sorted(got)}, **p))
    if missing:
        return None, missing
    rows.sort(key=lambda x: (x["set"], x["affair_id"]))
    return "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows), []


def load() -> dict[tuple[str, int], dict]:
    out = {}
    if PAIRS.exists():
        for line in PAIRS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[(r["set"], r["affair_id"])] = r
    return out


def for_record(rec: dict, pairs: dict, set_name: str) -> dict | None:
    """The committed pairing for a record, when its Q/A block names the same two documents."""
    p = pairs.get((set_name, rec["ref"]["opd_id"]))
    if p is None or not rec.get("qa"):
        return None
    q = rec["qa"][0]
    return p if (q.get("question_doc"), q.get("answer_doc")) == (p["question_doc"], p["answer_doc"]) else None


def check_detections() -> dict:
    text, missing = detect()
    if text is None:
        return dict(status="SKIP", summary=f"Q/A pairs not re-derived: {len(missing)} documents not cached")
    same = PAIRS.exists() and PAIRS.read_text(encoding="utf-8") == text
    return dict(status="PASS" if same else "FAIL",
                summary=f"Q/A pairs re-derived from the cached texts of {text.count(chr(10))} affairs: "
                        + ("identical to the committed file" if same else "DIFFER from the committed file"))


def block(by_set: dict[str, list[dict]], before: dict[str, int]) -> dict:
    """validation_all.json's `qa_pairing`: per converter set, records with items, questions and located answers."""
    sets = {}
    for k, recs in by_set.items():
        with_items = [r for r in recs if any(q.get("items") for q in r.get("qa") or [])]
        items = [i for r in recs for q in r.get("qa") or [] for i in q.get("items") or []]
        sets[k] = dict(n_records=len(recs), records_with_qa_block=sum(bool(r.get("qa")) for r in recs),
                       records_with_items=len(with_items), items=len(items),
                       answers_located=sum(i["answer"].get("kind") == "value" for i in items),
                       source=("results/eval6/p5__none.json (R.records, the P5 rules arm)" if k == "p5"
                               else "results/schema/v0_2/qa_pairs.jsonl (gegenprobe.schema.v0_2_qa detect)"))
    return dict(
        label=("the P5 pairing rules (gegenprobe.qa.extract, rules route, no model; held-out P5: precision 0.83, "
               "recall 0.67) applied to every converter record; on P3 and P3b these documents were not part of P5's "
               "test, so their pairs are unscored"),
        command="PYTHONPATH=src:. python -m gegenprobe.schema.v0_2_qa detect (then gegenprobe.schema.v0_2_parts)",
        pairs="results/schema/v0_2/qa_pairs.jsonl", sets=sets,
        records_with_items_before_overlay=before,
    )


def samples_check(files: dict[str, str], samples: list[str]) -> dict:
    """make run: every committed sample whose documents print questions (the pairing found some) carries qa items."""
    pairs = load()
    bad, shown = [], []
    for p in samples:
        set_name, body, opd = p.rsplit("/", 1)[1][:-5].split("_", 2)
        rec = json.loads(files[p.split("results/schema/v0_2/", 1)[1]])
        n = sum(len(q.get("items") or []) for q in rec.get("qa") or [])
        if set_name in SETS:
            pr = for_record(rec, pairs, set_name)
            want = bool(pr and pr["n_questions"])
        else:  # P5: the P5 rules arm's own pairing
            want = rec.get("empty_reasons", {}).get("qa.0.items") is None and bool(rec.get("qa"))
        if want and not n:
            bad.append(f"{body}:{opd}")
        shown.append(f"{body}:{opd} {n} items")
    return dict(status="FAIL" if bad else "PASS",
                summary=f"samples' qa items: {', '.join(shown)}" + (f"; MISSING in {', '.join(bad)}" if bad else ""))


def main(argv: list[str]) -> int:
    if argv[:1] == ["detect"]:
        text, missing = detect()
        if text is None:
            print(f"not cached: {len(missing)} documents (e.g. {missing[:3]}); fetch them through gegenprobe.pdftext",
                  file=sys.stderr)
            return 1
        PAIRS.write_text(text, encoding="utf-8")
        print(PAIRS.relative_to(ROOT))
        return 0
    if "--check" in argv:
        r = check_detections()
        print(r["status"], r["summary"])
        return 1 if r["status"] == "FAIL" else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
