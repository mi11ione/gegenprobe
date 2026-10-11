"""Document parts (tables, annexes, images, scanned pages, signatures) in the converter's v0.2 records.

    python -m gegenprobe.schema.v0_2_parts detect    run the parts detector (gegenprobe.convert.parts) over the P3, P3b and
                                                     P5 documents (cached PDFs and texts in WORK) and the federal texts
                                                     (WORK/fed/texts) -> results/schema/v0_2/document_parts.jsonl
    python -m gegenprobe.schema.v0_2_parts           write the v0.2 records with their parts: {p3,p3b,p5}_records.jsonl,
                                                     samples/*.json, fed_records.jsonl and validation_all.json (from the
                                                     committed files only: no network, no model, no document text)
    python -m gegenprobe.schema.v0_2_parts --check   exit 1 if a fresh run differs from the committed files

The records are gegenprobe.schema.v0_2_all's (frozen under eval/fed/LOCKFED, not edited): its render is taken as is and
`with_parts` adds, per document, the parts the detector found (`Document.parts`: kind, page range, a label with the rule's
reading and the character span in the document's text where it has one) and replaces the empty-list reason of
`documents.N.parts` ("this converter version does not detect document parts") by `none_printed` (the detector read
the document and found none; the same reason `python -m gegenprobe affair` gives) where the document was examined.
Nothing else of a record changes except a sentence in `extraction.notes`; `strip_parts` undoes the overlay exactly
(tests/test_schema_v0_2_parts.py).

document_parts.jsonl holds, per document, what the rules read: each part with its rule, page range, the character span in
the cached text and the sha256 of the text at the span (annex headings, located tables); the in-text annex references
and attachment lists (signals for eval/parts/sanity.py). No document text is written.

validation_all.json gets a `document_parts` block (EXPLORATORY: the rules were written on these documents; the blind check
is eval/parts): per set, the documents examined and the records and documents carrying each part kind. The federal cell's
15 records (results/fed/fed_records_v0_2.jsonl, eval.fed.arms offline) are carried with their parts to fed_records.jsonl
and counted there, apart from the 105 converter records.

Round 16 (J1): after the parts, each record's author roles pass gegenprobe.schema.role_consistency: where the rules put
`sole_author` next to `joint_author` (a group's name over signatures with no "for the group"), the sole author becomes a
joint author (GUIDE_P8), with a sentence in `extraction.notes`. validation_all.json's `role_consistency` block lists the
records changed and the R1-R4 check over every set (P8's gold included); a violation stops the render.
"""
from __future__ import annotations

import collections
import copy
import json
import sys

from ..convert import parts as P
from ..paths import PDF_CACHE, ROOT
from . import role_consistency as RC
from . import v0_2_all as V
from . import v0_2_roles
from .p8_v0_2 import OUT, schema_module

DETECTIONS = OUT / "document_parts.jsonl"
FED_IN = ROOT / "results" / "fed" / "fed_records_v0_2.jsonl"
FED_OUT = "fed_records.jsonl"
OVERLAY = "gegenprobe.schema.v0_2_parts.with_parts"
KINDS = ("annex", "table", "budget_table", "image", "signature")
CONVERTER_SETS = ("p3", "p3b", "p5")
OLD_REASON = V.CONVERTER_EMPTY["documents.*.parts"]


# ----------------------------------------------------------------------------------------------------------- detection
def _strip_det(det: dict) -> dict:
    keep = ("kind", "page_from", "page_to", "label", "subtype", "rule", "span", "rows", "columns")
    return dict(n_pages=det["n_pages"], parts=[{k: p[k] for k in keep if k in p} for p in det["parts"]],
                signals=det["signals"])


def _pdf_rows(missing: list[str]) -> list[dict]:
    rows = []
    for set_name, path in v0_2_roles.SETS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            for d in r["docs"]:
                pdf = PDF_CACHE / f"{d['sha256']}.pdf"
                got = v0_2_roles.pages_of(d["sha256"], bool(d.get("image_only")))
                if got is None or not pdf.exists():
                    missing.append(f"{set_name}:{r['affair_id']}:{d['role']}")
                    continue
                pages, ext = got
                det = P.detect_pdf(pdf, pages, image_only=bool(d.get("image_only")), ocr=ext.startswith("tesseract"))
                rows.append(dict(set=set_name, affair_id=r["affair_id"], body=r["body"], role=d["role"],
                                 doc_id=f"opd:{d['doc_id']}", sha256=d["sha256"], extractor=ext,
                                 image_only=bool(d.get("image_only")), detector=P.PARTS_VERSION, **_strip_det(det)))
    return rows


def _fed_rows(missing: list[str]) -> list[dict]:
    """The federal cell's texts (OPD's texts export, HTML): the same pages the federal records' documents carry."""
    try:
        from eval.fed import arms as FA
        from eval.fed import common as C
        from eval.fed import packets as FP
        entries = FA.affairs()
    except (ImportError, SystemExit) as e:
        missing.append(f"fed: {e}")
        return []
    rows = []
    for e in entries:
        try:
            pages = FP.pages_of(e)  # sha256-checked against the draw
            t = FP.load_texts(e["affair_id"])
        except (OSError, SystemExit) as x:
            missing.append(f"fed:{e['affair_id']}: {x}")
            continue
        html = {"question": [None, t["rows"]["member"]] + ([t["rows"]["reason"]] if t["rows"].get("reason") else []),
                "answer": [t["rows"]["answer"]]}
        for role, rid in (("question", e["rows"]["member"]), ("answer", e["rows"]["answer"])):
            det = P.detect_html(html[role], pages[role])
            rows.append(dict(set="fed", affair_id=e["affair_id"], body=e["body"], role=role, doc_id=f"opd-texts:{rid}",
                             sha256=C.sha(t["rows"]["member" if role == "question" else "answer"]),
                             extractor="eval.fed.common.plain", image_only=False, detector=P.PARTS_VERSION,
                             **_strip_det(det)))
    return rows


def detect() -> tuple[str | None, list[str]]:
    """(the detections file's text, documents not cached); text None when any is missing."""
    missing: list[str] = []
    rows = _pdf_rows(missing) + _fed_rows(missing)
    if missing:
        return None, missing
    rows.sort(key=lambda r: (r["set"], r["affair_id"], r["role"], r["doc_id"]))
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), []


def check_detections() -> dict:
    """Re-detect and compare with the committed file: PASS, FAIL, or SKIP when the PDFs / texts are not cached."""
    text, missing = detect()
    if text is None:
        return dict(status="SKIP", summary=f"parts not re-detected: {len(missing)} documents not cached")
    same = DETECTIONS.exists() and DETECTIONS.read_text(encoding="utf-8") == text
    return dict(status="PASS" if same else "FAIL",
                summary=f"parts re-detected from the cached PDFs and texts of {text.count(chr(10))} documents: "
                        + ("identical to the committed file" if same else "DIFFER from the committed file"))


def load() -> dict[tuple[str, str], dict]:
    """The committed detections keyed by (set, doc_id)."""
    out = {}
    for line in DETECTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[(r["set"], r["doc_id"])] = r
    return out


# ----------------------------------------------------------------------------------------------------------- overlay
def _note(n_parts: int, n_docs: int, n_with: int) -> str:
    return (f"document parts by {OVERLAY} (gegenprobe.convert.parts {P.PARTS_VERSION}): {n_parts} parts in {n_with} of "
            f"{n_docs} documents examined")


def with_parts(rec: dict, det: dict[tuple[str, str], dict], set_name: str) -> dict:
    """The record with each examined document's parts and the empty-list reasons of `documents.N.parts` updated."""
    rec = copy.deepcopy(rec)
    n_docs = n_with = n_parts = 0
    for i, d in enumerate(rec.get("documents") or []):
        row = det.get((set_name, d["doc_id"]))
        if row is None:
            continue
        n_docs += 1
        parts = P.schema_parts(row)
        key = f"documents.{i}.parts"
        if parts:
            d["parts"] = parts
            n_with += 1
            n_parts += len(parts)
            rec["empty_reasons"].pop(key, None)
        else:
            route = "ocr+rule" if str(d.get("extractor") or "").startswith("tesseract") else "rule"
            rec["empty_reasons"][key] = dict(
                reason="none_printed", route=route, doc=d["doc_id"],
                evidence=f"gegenprobe.convert.parts {P.DETECTOR}: the detector found no part (annex, table, image, "
                         "signature) in this document")
    if n_docs:
        ex = rec["extraction"]
        note = _note(n_parts, n_docs, n_with)
        ex["notes"] = f"{ex['notes']}; {note}" if ex.get("notes") else note
    return rec


def strip_parts(rec: dict) -> dict:
    """Undo `with_parts` (for the test that the overlay changes nothing else)."""
    rec = copy.deepcopy(rec)
    reason, route, ev = OLD_REASON
    for i, d in enumerate(rec.get("documents") or []):
        key = f"documents.{i}.parts"
        r = rec["empty_reasons"].get(key)
        if d.get("parts") or (r and r["reason"] == "none_printed"):
            d["parts"] = []
            rec["empty_reasons"][key] = dict(reason=reason, route=route, evidence=ev)
    ex = rec["extraction"]
    notes = [x for x in (ex.get("notes") or "").split("; ") if not x.startswith(f"document parts by {OVERLAY}")]
    ex["notes"] = "; ".join(notes)
    return rec


def summary(recs: list[dict], det: dict, set_name: str) -> dict:
    rc, dc, pc, sub = (collections.Counter() for _ in range(4))
    n_docs = examined = 0
    for r in recs:
        kinds = set()
        for d in r.get("documents") or []:
            n_docs += 1
            row = det.get((set_name, d["doc_id"]))
            examined += row is not None
            ks = {p["kind"] for p in d.get("parts") or []}
            kinds |= ks
            dc.update(ks)
            dc["any"] += bool(ks)
            pc.update(p["kind"] for p in d.get("parts") or [])
            if row:
                sub.update(p["subtype"] for p in row["parts"])
        rc.update(kinds)
        rc["any"] += bool(kinds)
    order = ("any",) + KINDS
    return dict(n_records=len(recs), n_documents=n_docs, documents_examined=examined,
                records_carrying={k: rc[k] for k in order}, documents_carrying={k: dc[k] for k in order},
                parts={k: pc[k] for k in KINDS}, parts_by_rule=dict(sorted(sub.items())))


def render() -> dict[str, str]:
    """v0_2_all's files with the parts overlay (and fed_records.jsonl); raises if a record stops validating."""
    m = schema_module()
    det = load()
    base = V.render()
    files = dict(base)
    val = json.loads(base["validation_all.json"])
    by_set, block, roles_changed = {}, {}, {}
    for k in CONVERTER_SETS:
        recs = [with_roles_consistent(with_parts(json.loads(x), det, k), roles_changed, k)
                for x in base[f"{k}_records.jsonl"].splitlines() if x.strip()]
        st, valid = V.stats(recs, m)
        if st["n_invalid"]:
            raise ValueError(f"{k}: {st['invalid'][:2]}")
        val["sets"][k] = st
        by_set[k] = valid
        files[f"{k}_records.jsonl"] = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in valid)
        block[k] = summary(valid, det, k)
    fed = [with_roles_consistent(with_parts(json.loads(x), det, "fed"), roles_changed, "fed")
           for x in FED_IN.read_text(encoding="utf-8").splitlines() if x.strip()]
    st, valid = V.stats(fed, m)
    if st["n_invalid"]:
        raise ValueError(f"fed: {st['invalid'][:2]}")
    files[FED_OUT] = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in valid)
    fed_block = dict(summary(valid, det, "fed"), n_valid=st["n_valid"])
    for p in val["samples"]:
        set_name, body, opd = p.rsplit("/", 1)[1][:-5].split("_", 2)
        rec = next(r for r in by_set[set_name] if r["ref"]["body_key"] == body and str(r["ref"]["opd_id"]) == opd)
        files[p.split("results/schema/v0_2/", 1)[1]] = json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    total = collections.Counter()
    for k in CONVERTER_SETS:
        for part in ("records_carrying", "documents_carrying"):
            for kind, n in block[k][part].items():
                total[(part, kind)] += n
        total[("n", "records")] += block[k]["n_records"]
        total[("n", "documents")] += block[k]["n_documents"]
        total[("n", "examined")] += block[k]["documents_examined"]
    val["document_parts"] = dict(
        label=("EXPLORATORY: rules written on these documents (no held-out test); the blind check of the detector is "
               "eval/parts (GUIDE_PARTS.md)"),
        command="PYTHONPATH=src:. python -m gegenprobe.schema.v0_2_parts (after gegenprobe.schema.v0_2_all)",
        detector=P.DETECTOR, rules="src/gegenprobe/convert/parts.py",
        detections="results/schema/v0_2/document_parts.jsonl (python -m gegenprobe.schema.v0_2_parts detect)",
        converter_made=dict(n_records=total[("n", "records")], n_documents=total[("n", "documents")],
                            documents_examined=total[("n", "examined")],
                            records_carrying={k: total[("records_carrying", k)] for k in ("any",) + KINDS},
                            documents_carrying={k: total[("documents_carrying", k)] for k in ("any",) + KINDS}),
        sets=block,
        fed=dict(fed_block, records="results/schema/v0_2/fed_records.jsonl",
                 source=f"{FED_IN.relative_to(ROOT).as_posix()} (eval.fed.arms offline) + {OVERLAY}"),
    )
    val["role_consistency"] = role_block(files, roles_changed)
    files["validation_all.json"] = json.dumps(val, ensure_ascii=False, indent=1) + "\n"
    return files


# ----------------------------------------------------------------------------------------------------------- roles
def with_roles_consistent(rec: dict, changed: dict, set_name: str) -> dict:
    """The record with R2 (sole_author next to joint_author) repaired by gegenprobe.schema.role_consistency."""
    rec, ch = RC.harmonise(rec)
    if ch:
        changed[f"{set_name}:{rec['ref']['body_key']}:{rec['ref']['opd_id']}"] = ch
    return rec


def role_block(files: dict[str, str], changed: dict) -> dict:
    """validation_all.json's `role_consistency`: the records the repair changed and the R1-R4 check over every set
    (raises if a record still violates a rule)."""
    sets = {k: f"{k}_records.jsonl" for k in CONVERTER_SETS}
    sets["fed"] = FED_OUT
    checked = {}
    for k, name in sets.items():
        checked[k] = RC.check_records([json.loads(x) for x in files[name].splitlines() if x.strip()])
    p8 = OUT / "p8_records.jsonl"
    if p8.exists():
        checked["p8"] = RC.check_records([json.loads(x) for x in p8.read_text(encoding="utf-8").splitlines()
                                          if x.strip()])
    bad = {k: c["violations"] for k, c in checked.items() if c["n_violating"]}
    if bad:
        raise ValueError(f"role consistency (R1-R4): {bad}")
    return dict(
        rules=("R1 at most one sole_author; R2 sole_author excludes joint_author; R3 a person sole_author excludes a "
               "first_signatory; R4 joint_author excludes first_signatory and needs another joint author "
               "(gegenprobe.schema.role_consistency, from eval/p8/GUIDE_P8.md section 2)"),
        repair=("R2: every sole_author next to a joint_author becomes joint_author (GUIDE_P8: authors printed with equal "
                "standing, none designated first); names, pages, spans and rules unchanged"),
        n_records_changed=len(changed),
        changed={k: [dict(kind=x["kind"], was=x["was"], now=x["now"]) for x in v] for k, v in sorted(changed.items())},
        checked={k: dict(n_records=c["n_records"], n_violating=c["n_violating"]) for k, c in checked.items()},
    )


def _diff(files: dict[str, str]) -> list[str]:
    return [n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != t]


def step(ctx: dict) -> dict:
    """`make run` step schema_v02: P8 and the converter records (gegenprobe.schema.v0_2_all) with their document parts,
    re-derived and compared with results/schema/v0_2/ (FAIL on a diff or an invalid record)."""
    from . import p8_v0_2

    p8 = p8_v0_2.step(ctx)
    rc = v0_2_roles.check()
    pc = check_detections()
    files = render()
    bad = _diff(files)
    val = json.loads(files["validation_all.json"])
    s, dp = val["sets"], val["document_parts"]["converter_made"]
    ok = p8["status"] == "PASS" and not bad and val["n_invalid"] == 0 and rc["status"] != "FAIL" and pc["status"] != "FAIL"
    carry = dp["records_carrying"]
    summary_ = (f"schema v0.2: {val['n_valid']}/{val['n_affairs']} affairs valid (converter records: P3 "
                f"{s['p3']['n_valid']}/{s['p3']['n_affairs']}, P3b {s['p3b']['n_valid']}/{s['p3b']['n_affairs']}, P5 "
                f"{s['p5']['n_valid']}/{s['p5']['n_affairs']}; P8 gold {s['p8']['n_valid']}/{s['p8']['n_affairs']}); "
                + p8["summary"].split("; ", 1)[0].split(", ", 1)[-1]
                + f"; {rc['summary']}"
                + f"; document parts in {carry['any']}/{dp['n_records']} converter records (annex {carry['annex']}, table "
                  f"{carry['table']}, budget table {carry['budget_table']}, image {carry['image']}, signature "
                  f"{carry['signature']}); "
                + pc["summary"]
                + (f"; differs: {', '.join(bad)}" if bad else "")
                + ("" if p8["status"] == "PASS" else f"; P8: {p8['summary']}"))
    return dict(status="PASS" if ok else "FAIL", summary=summary_)


def main(argv: list[str]) -> int:
    if argv[:1] == ["detect"]:
        text, missing = detect()
        if text is None:
            print(f"not cached: {len(missing)} documents (e.g. {missing[:3]}); fetch them through gegenprobe.pdftext",
                  file=sys.stderr)
            return 1
        DETECTIONS.write_text(text, encoding="utf-8")
        print(DETECTIONS)
        return 0
    files = render()
    if "--check" in argv:
        bad = _diff(files)
        print("schema v0.2 with document parts:", "differs: " + ", ".join(bad) if bad else "committed files current")
        return 1 if bad else 0
    (OUT / "samples").mkdir(parents=True, exist_ok=True)
    for n, s in files.items():
        (OUT / n).write_text(s, encoding="utf-8")
        print(OUT / n)
    dp = json.loads(files["validation_all.json"])["document_parts"]
    print(f"document parts: {dp['converter_made']['records_carrying']['any']}/{dp['converter_made']['n_records']} converter "
          f"records carry a part; fed {dp['fed']['records_carrying']['any']}/{dp['fed']['n_records']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
