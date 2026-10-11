"""One OPD affair -> one validated schema v0.2 record, from OPD's exports and the affair's own documents.

    python -m gegenprobe affair --opd-affair 39369 [--schema v0.2] [--mode rules_only|review] [--out FILE]

The record is made by the same functions as the committed converter records (results/schema/v0_2/p3_records.jsonl,
p3b_records.jsonl; gegenprobe.schema.v0_2_all): affair.build.run_affair (OPD metadata first, rules on the two documents,
the frozen P1 answer-date cascade; in review mode the Apertus closed-set pointer adds suggestions next to the record,
never into a field), affair_post.finalize (product corrections, needs_review), v0_2_all.carry_v0_1 (schema 0.2.0, typed
null `not_extracted` for the answering body) and v0_2_all.with_roles (printed authors with their role, printed submission
dates, instrument, language of each text, read by gegenprobe.convert.roles). The record is then validated with the v0.2
Pydantic model (schema/gegenprobe_schema_v0_2.py); an invalid record is a typed failure, never printed as a record.

Inputs, all public:
  OPD metadata   the affair row, its events and contributors, and the affair's document rows. api.openparldata.ch/v1/ is
                 disallowed by OPD's robots.txt (net.FORBIDDEN), so they come from OPD's nightly exports: affairs, events,
                 contributors (single files) and docs/docs_<body> (per body), streamed through gegenprobe.net (RFC 9309
                 robots.txt, fail-closed, 1.2 s per host, GP_USER_AGENT); read from disk when GP_EXPORTS_DIR mirrors the
                 exports directory (net.local_exports). --source local reads the copies a development checkout keeps in
                 GP_OPD_RAW and GP_DOCS_META (census.scan output) instead; --rows FILE reads a saved slice (--save-rows).
  documents      the member's text (question) and the executive's answer that OPD links to the affair, picked by the P3
                 pairing rule (eval.gold3.sample.pair_type: document name, category and the P1 type guess; among several,
                 the one with OPD text in P3's length band, then the lowest OPD id) unless --question-doc / --answer-doc
                 name them. Fetched through pdftext.fetch_pdf (robots.txt, size cap, OPD's own copy where the original's
                 robots.txt disallows the path) into GP_WORK/pdf, text in GP_WORK/text (OCR for scans, ocrguard).

Output (stdout or --out): {"opd_affair", "status": "ok", "schema_version": "0.2.0", "record": <v0.2 record>,
"needs_review", "review", "suggestions", "changes", "sources"}; --record-only prints the record alone. Several
--opd-affair values give one JSON line per affair (one pass over the exports).
Typed failures ({"opd_affair", "status": <kind>, "reason"}, exit 2): affair_not_found, no_documents,
document_not_in_affair, exports_* (the exports could not be read: exports_robots_unreachable, exports_network_error, ...),
the document kinds of `convert` (robots_disallowed, robots_unreachable, http_error, timeout, network_error, not_a_pdf,
sha_mismatch, too_large, text_timeout, ocr_failed) and invalid_record (the v0.2 model rejected the record).
Exit 3: review mode refused because the served model is not the build θ was fitted on (as `convert`).

Document parts (tables, annexes, images): `detect_parts` below is the one adapter to the rule-based detector in
gegenprobe.convert.parts (detect_pdf + schema_parts). A document where it ran and found nothing gets the typed reason
`none_printed`; without that module each document's `parts` stays empty with the typed reason `not_extracted` ("this
converter version does not detect document parts"), as in the committed records.

`make run` step: `step(ctx)` runs the command on the affairs of the three committed v0.2 samples (Bern, Vernier, Lugano;
results/schema/v0_2/samples/) and compares each record with its sample field by field.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator

from . import net
from .compliance import fetchguard
from .paths import DOCS_META, OPD_RAW, PDF_CACHE, ROOT

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

SCHEMA_VERSIONS = ("v0.2",)
SINGLE = ("affairs", "events", "contributors")
SAMPLES_DIR = ROOT / "results" / "schema" / "v0_2" / "samples"
SAMPLE_ROWS = ROOT / "data" / "affair_cli" / "opd_rows_samples.json"
LEVEL = {"canton": "canton", "city": "commune", "municipality": "commune", "country": "federal"}
CONVERTER = "gegenprobe.affair_cli"
PARTS_NOT_EXTRACTED = "this converter version does not detect document parts"
# document kinds that mean "the network or the host is not reachable now" (make-run step: SKIP, not FAIL)
UNREACHABLE = ("robots_unreachable", "network_error", "timeout", "exports_robots_unreachable", "exports_network_error",
               "exports_timeout", "exports_http_error")

_FIRST_ID = re.compile(r'\s*\{\s*"id"\s*:\s*(\d+)')
_AFFAIR_ID = re.compile(r'"affair_id"\s*:\s*(\d+)')
_BODY_KEY = re.compile(r'"body_key"\s*:\s*"([^"]*)"')
_META_A = re.compile(r'"a"\s*:\s*(\d+)')


class AffairError(Exception):
    """A typed failure: `kind` (see the module docstring) and a one-line `detail`."""

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def _eval_importable() -> None:
    """eval/ (the frozen P3 pairing rule) sits next to src/ in the checkout; an editable install without PYTHONPATH=.
    does not put it on sys.path."""
    try:
        import eval.gold3.sample  # noqa: F401
    except ImportError:
        sys.path.append(str(ROOT))


# ------------------------------------------------------------------------------------------------ OPD export rows
def _classify(exc: BaseException, prefix: str = "") -> tuple[str, str]:
    from .convert import output

    kind, reason = output.classify(exc)
    return prefix + kind, reason


def _lines(name: str, source: str) -> Iterator[str]:
    """Text lines of one export file: GP_OPD_RAW (source local) or the exports (network or GP_EXPORTS_DIR)."""
    if source == "local":
        with gzip.open(OPD_RAW / name, "rt", encoding="utf-8") as f:
            yield from f
    else:
        yield from net.stream_ndjson_gz(net.EXPORTS_PREFIX + name)


def _guarded(it: Iterable[str], what: str) -> Iterator[str]:
    try:
        yield from it
    except (OSError, net.Disallowed, ValueError, EOFError) as e:
        kind, reason = _classify(e, "exports_")
        raise AffairError(kind, f"{what}: {reason}") from e


def _local_ok() -> bool:
    return all((OPD_RAW / f"{n}.ndjson.gz").exists() for n in SINGLE)


def _docs_meta_files() -> list[Path]:
    return sorted(DOCS_META.glob("part*/docs_meta.jsonl.gz"))


def _index(source: str) -> dict:
    """Which snapshot the rows come from: index.json's generated_at (one small request for the exports)."""
    try:
        if source == "local":
            p = OPD_RAW / "index.json"
            return dict(generated_at=json.loads(p.read_text())["generated_at"]) if p.exists() else {}
        return dict(generated_at=json.loads(net.get(net.EXPORTS_PREFIX + "index.json"))["generated_at"])
    except Exception as e:  # noqa: BLE001 - provenance only; the rows themselves are checked below
        return dict(index_error=f"{type(e).__name__}: {e}"[:200])


def read_rows(affair_ids: Iterable[int], source: str = "auto") -> dict:
    """OPD's rows for the affairs: {"affairs": {id: {affair, events, contributors, docs}}, "names": {body: [[first,
    last], ...]}, "sources": {...}}. One pass per export file; the persons export (contact fields) is never read."""
    from .affair import meta as M

    ids = {int(a) for a in affair_ids}
    if source == "auto":
        source = "local" if _local_ok() else "exports"
    if source == "local" and not _local_ok():
        raise AffairError("exports_not_local", f"--source local needs {', '.join(SINGLE)} .ndjson.gz in {OPD_RAW} (GP_OPD_RAW)")
    where = ("GP_OPD_RAW" if source == "local" else "GP_EXPORTS_DIR" if os.environ.get("GP_EXPORTS_DIR")
             else net.EXPORTS_PREFIX)
    sources = dict(single_exports=dict(source=source, location=where, **_index(source)))
    out = {a: dict(affair=None, events=[], contributors=[], docs=[]) for a in ids}
    left = set(ids)
    for line in _guarded(_lines("affairs.ndjson.gz", source), "affairs export"):
        m = _FIRST_ID.match(line)
        if m and int(m.group(1)) not in ids:
            continue
        a = json.loads(line)
        if a.get("id") in out:
            out[a["id"]]["affair"] = {k: a.get(k) for k in M.AFFAIR_KEYS}
            left.discard(a["id"])
            if not left:
                break
    found = {a for a, v in out.items() if v["affair"] is not None}
    bodies = {out[a]["affair"]["body_key"] for a in found}
    if found:
        for line in _guarded(_lines("events.ndjson.gz", source), "events export"):
            m = _AFFAIR_ID.search(line)
            if m and int(m.group(1)) in found:
                e = json.loads(line)
                if e.get("affair_id") in found:
                    out[e["affair_id"]]["events"].append({k: e.get(k) for k in M.EVENT_KEYS})
    names: dict[str, dict] = collections.defaultdict(dict)
    if found:
        for line in _guarded(_lines("contributors.ndjson.gz", source), "contributors export"):
            ma, mb = _AFFAIR_ID.search(line), _BODY_KEY.search(line)
            if not ((ma and int(ma.group(1)) in found) or (mb and mb.group(1) in bodies)):
                continue
            c = json.loads(line)
            if c.get("affair_id") in found:
                out[c["affair_id"]]["contributors"].append({k: c.get(k) for k in M.CONTRIB_KEYS})
            if c.get("body_key") in bodies and c.get("type") == "person" and c.get("lastname"):
                names[c["body_key"]][c.get("person_id") or c["fullname"]] = [c.get("firstname") or "", c["lastname"]]
    for v in out.values():
        v["events"].sort(key=lambda e: (e["date"] or "", e["position"] or 0, e["id"]))
        v["contributors"].sort(key=lambda c: (c["position"] or 0, c["id"]))
    _read_docs(out, found, bodies, source, sources)
    return dict(affairs=out, sources=sources,
                names={b: sorted({tuple(x) for x in d.values()}) for b, d in sorted(names.items())})


def _read_docs(out: dict, found: set, bodies: set, source: str, sources: dict) -> None:
    """Document rows (census.scan's metadata row: id, b, a, name, cat, ch, lang, url, st, n, ...; never the text)."""
    seen: set[int] = set()
    metas = _docs_meta_files() if source == "local" else []
    if metas:
        sources["docs"] = dict(source="local", location="GP_DOCS_META (census.scan metadata rows)")
        for f in metas:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    m = _META_A.search(line)
                    if not (m and int(m.group(1)) in found):
                        continue
                    d = json.loads(line)
                    if d["id"] not in seen and d.get("a") in found:  # first part wins, as in eval.gold3.sample.pairs
                        seen.add(d["id"])
                        out[d["a"]]["docs"].append(d)
        return
    from .census import scan

    sources["docs"] = dict(source="exports", location=("GP_EXPORTS_DIR" if os.environ.get("GP_EXPORTS_DIR")
                                                       else net.EXPORTS_PREFIX) + "docs/docs_<body>.ndjson.gz")
    for b in sorted(bodies):
        for line in _guarded(_lines(f"docs/docs_{b}.ndjson.gz", "exports"), f"docs_{b} export"):
            m = _AFFAIR_ID.search(line)
            if not (m and int(m.group(1)) in found):
                continue
            d = json.loads(line)
            if d.get("affair_id") in found and d["id"] not in seen:
                seen.add(d["id"])
                out[d["affair_id"]]["docs"].append(scan.doc_row(d, b)[0])
    for v in out.values():
        v["docs"].sort(key=lambda d: d["id"])


def save_rows(rows: dict, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    dump = dict(rows, affairs={str(k): v for k, v in sorted(rows["affairs"].items())})
    Path(path).write_text(json.dumps(dump, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load_rows(path: Path) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    d["affairs"] = {int(k): v for k, v in d["affairs"].items()}
    d["names"] = {b: [tuple(x) for x in v] for b, v in d["names"].items()}
    return d


# ------------------------------------------------------------------------------------------------ documents
def pick_docs(docs: list[dict], affair_type: str | None, question_doc: int | None = None,
              answer_doc: int | None = None) -> dict[str, dict]:
    """role -> OPD document row. The P3 pairing rule (eval.gold3.sample.pair_type), preferring a document with OPD text
    in P3's length band, then one with OPD text, then the lowest id; the census answer-document rule
    (census.defs.is_answer_doc) when the pairing rule finds no answer. --question-doc / --answer-doc override."""
    _eval_importable()
    from eval.gold3.sample import LEN_BAND, pair_type

    from .census import defs

    by_id = {d["id"]: d for d in docs}
    out: dict[str, dict] = {}
    for role, want in (("question", question_doc), ("answer", answer_doc)):
        if want is not None:
            if want not in by_id:
                raise AffairError("document_not_in_affair", f"OPD document {want} is not linked to this affair "
                                  f"(linked: {', '.join(map(str, sorted(by_id))) or 'none'})")
            out[role] = by_id[want]
    cands: dict[str, list[dict]] = {"question": [], "answer": []}
    for d in docs:
        if not d.get("url"):
            continue
        t = pair_type(dict(d, a_type=affair_type))
        if t == "intervention":
            cands["question"].append(d)
        elif t == "answer":
            cands["answer"].append(d)
    if not cands["answer"]:
        cands["answer"] = [d for d in docs if d.get("url") and d not in cands["question"]
                           and defs.is_answer_doc(d.get("name"), d.get("cat"), d.get("fl") or [])]

    def tier(d):
        ok = d.get("st") == "ok"
        return (0 if ok and LEN_BAND[0] <= (d.get("n") or 0) <= LEN_BAND[1] else 1 if ok else 2, d["id"])
    for role in ("question", "answer"):
        if role not in out and cands[role]:
            pick = sorted((d for d in cands[role] if d is not out.get("question")), key=tier)
            if pick:
                out[role] = pick[0]
    return out


def fetch_doc(role: str, d: dict, timeout: int = 60, tries: int = 2) -> dict:
    """Fetch and extract one OPD document (pdftext.fetch_pdf through convert.batch.get_document; OCR for a scan) ->
    the document entry affair.build expects. Raises AffairError with the `convert` failure kinds."""
    from . import pdftext
    from .convert import batch

    try:
        sha, path = batch.get_document(d["url"], timeout=timeout, tries=tries)
        t = pdftext.extract(sha, path, ocr=True)
    except Exception as e:  # noqa: BLE001 - every fetch/extract failure is typed (convert/output.classify)
        kind, reason = _classify(e)
        raise AffairError(kind, f"{role} document opd:{d['id']} ({d['url']}): {reason}") from e
    chars = sum(len(p) for p in t["pages"])
    if not chars:
        raise AffairError("text_failed", f"{role} document opd:{d['id']}: no text after extraction")
    return dict(role=role, doc_id=d["id"], name=d.get("name"), url=d["url"], opd_text_status=d.get("st"),
                opd_chars=d.get("n"), sha256=sha, pages=len(t["pages"]), chars=chars, extractor=t["extractor"],
                image_only=bool(t["image_only"]))


# ------------------------------------------------------------------------------------------------ document parts hook
def detect_parts(pages: list[str], pdf_path: Path | None = None, *, image_only: bool = False,
                 ocr: bool = False) -> tuple[list[dict] | None, str]:
    """Rule-based document parts of one document, as schema v0.2 `DocumentPart` dicts {kind, page_from, page_to,
    label}: (parts, detector id), or (None, why) when no detector ran.

    The single adapter to gegenprobe.convert.parts. It calls `detect_pdf(pdf_path, pages, image_only=, ocr=)` and
    `schema_parts(detection)` there (pages: the cached text the record's spans point into, page 1 first; pdf_path: the
    cached PDF), or, failing those, `detect(pages, pdf_path=)` returning DocumentPart dicts. A module that is absent or
    has neither keeps `parts` empty with the typed reason not_extracted; a detector that raises is reported in that
    reason, never fatal."""
    try:
        from .convert import parts as P
    except ImportError:
        return None, PARTS_NOT_EXTRACTED
    version = getattr(P, "PARTS_VERSION", None) or getattr(P, "RULES_VERSION", None)
    detector = f"gegenprobe.convert.parts {version}" if version else "gegenprobe.convert.parts"
    try:
        if hasattr(P, "detect_pdf") and hasattr(P, "schema_parts") and pdf_path is not None:
            det = P.detect_pdf(Path(pdf_path), pages, image_only=image_only, ocr=ocr)
            if det.get("detector"):
                detector = f"gegenprobe.convert.parts {det['detector']}"
            got = P.schema_parts(det)
        elif hasattr(P, "detect"):
            got = P.detect(pages, pdf_path=pdf_path)
        else:
            return None, PARTS_NOT_EXTRACTED + " (gegenprobe.convert.parts has no detect_pdf or detect)"
    except Exception as e:  # noqa: BLE001 - parts are optional; the failure is typed in the record
        return None, f"{detector} raised {type(e).__name__}: {str(e)[:160]}"
    out = []
    for p in got or []:
        p = p.model_dump(mode="json") if hasattr(p, "model_dump") else dict(p)
        out.append({k: p[k] for k in ("kind", "page_from", "page_to", "label") if p.get(k) is not None})
    return out, detector


def _apply_parts(rec: dict, entry: dict) -> list[dict]:
    """Fill documents[].parts through detect_parts; returns per-document notes for the empty reasons."""
    from .schema.v0_2_roles import pages_of

    by_id = {f"opd:{d['doc_id']}": d for d in entry["docs"]}
    notes = []
    for i, doc in enumerate(rec.get("documents") or []):
        d = by_id.get(doc["doc_id"])
        got = pages_of(d["sha256"], bool(d.get("image_only"))) if d else None
        if got is None:
            notes.append(dict(index=i, doc=doc["doc_id"], ran=False, note=PARTS_NOT_EXTRACTED))
            continue
        parts, note = detect_parts(got[0], PDF_CACHE / f"{d['sha256']}.pdf", image_only=bool(d.get("image_only")),
                                   ocr=str(got[1]).startswith("tesseract"))
        if parts:
            doc["parts"] = parts
        notes.append(dict(index=i, doc=doc["doc_id"], ran=parts is not None, note=note))
    return notes


def _parts_reasons(rec: dict, notes: list[dict]) -> None:
    for n in notes:
        key = f"documents.{n['index']}.parts"
        if key not in rec["empty_reasons"]:
            continue
        if n["ran"]:
            rec["empty_reasons"][key] = dict(reason="none_printed", route="rule", doc=n["doc"],
                                             evidence=f"{n['note']}: the detector found no part (annex, table, image, "
                                                      "signature) in this document")
        elif n["note"] != PARTS_NOT_EXTRACTED:
            rec["empty_reasons"][key] = dict(reason="not_extracted", route="rule", evidence=n["note"])


# ------------------------------------------------------------------------------------------------ the record
def _census_bodies() -> dict[str, dict]:
    with gzip.open(ROOT / "data" / "census" / "bodies.tsv.gz", "rt", encoding="utf-8") as f:
        return {r["key"]: r for r in csv.DictReader(f, delimiter="\t")}


def link_status(row: dict, picked: dict) -> str:
    """answer_link_status from this affair's own rows (census.funnel's definitions, per affair): attached (OPD links
    an answer document with usable text), image_only (one without), else from the events: absent (a written answer
    is recorded), oral (only oral answer events), not_applicable."""
    from .census import defs

    a = picked.get("answer")
    if a is not None:
        return "attached" if a.get("st") == "ok" and (a.get("n") or 0) >= 200 else "image_only"
    kinds = {defs.classify_event(defs.event_title(e), e.get("title_harmonized_id")) for e in row["events"]}
    return "absent" if "written" in kinds else "oral" if "oral" in kinds else "not_applicable"


def _lang(picked: dict, body: str) -> str | None:
    _eval_importable()
    from eval.gold.sample import lang_of

    from .schema import body_languages

    for role in ("question", "answer"):
        lg = lang_of(picked[role]) if role in picked else None
        if lg in ("de", "fr", "it"):
            return lg
    langs, _ = body_languages.languages(body)
    return next((x for x in langs if x in ("de", "fr", "it")), None)


def harmonised_type(affair: dict, opd: dict) -> tuple[dict, list[dict]]:
    """The frozen assembly (affair/extract.py TYPE_BY_EN) matches OPD's harmonised English type name against the
    vocabulary's English labels, so OPD's "Question" (label "Written question") comes out `unknown`. When it does, the
    type is taken from OPD's name by the mapping the committed P5 records use (gegenprobe.schema.v0_2_all.OPD_TYPE_NAMES),
    before affair_post.finalize (so a question's decision becomes not_applicable). Listed in `changes`."""
    import copy

    from .schema import v0_2_all

    t = affair.get("type") or {}
    name = (opd.get("type_harmonized_en") or "").strip()
    key, _ = v0_2_all._types().get(name, (None, None))
    if t.get("harmonised") != "unknown" or not key or key == "unknown":
        return affair, []
    affair = copy.deepcopy(affair)
    affair["type"]["harmonised"] = key
    return affair, [dict(field="type.harmonised", was="unknown", now=f"{key} (OPD harmonised type {name!r}, mapping "
                         "gegenprobe.schema.v0_2_all.OPD_TYPE_NAMES)")]


def build(affair_id: int, row: dict, names: list, *, sources: dict | None = None, mode: str = "rules_only",
          backend=None, theta=None, question_doc: int | None = None, answer_doc: int | None = None, timeout: int = 60,
          tries: int = 2) -> dict:
    """One affair's product row with the validated v0.2 record (see the module docstring). Raises AffairError."""
    from .affair import build as B
    from .affair_post import finalize
    from .schema import v0_2_all, v0_2_roles
    from .schema.p8_v0_2 import schema_module

    a = row.get("affair")
    if not a:
        raise AffairError("affair_not_found", f"OPD affair {affair_id} is not in the affairs export")
    body = a["body_key"]
    picked = pick_docs(row.get("docs") or [], a.get("type_harmonized_en"), question_doc, answer_doc)
    if not picked:
        n = len(row.get("docs") or [])
        raise AffairError("no_documents", (
            f"OPD's docs export links {n} documents to affair {affair_id}, none is a member's text or an answer by the "
            "P3 pairing rule (name them with --question-doc / --answer-doc)") if n else (
            f"OPD's docs export links no document to affair {affair_id}"
            + (" (the federal parliament's texts are in OPD's texts export, which this command does not read)"
               if body == "CHE" else "")))
    bt = _census_bodies().get(body, {})
    docs = [fetch_doc(role, picked[role], timeout, tries) for role in ("question", "answer") if role in picked]
    entry = dict(split="opd", affair_id=affair_id, body=body, level=LEVEL.get(bt.get("type") or "", "canton"),
                 lang=_lang(picked, body), affair_type=a.get("type_harmonized_en"), docs=docs)
    meta = dict(affair=a, events=row["events"], contributors=row["contributors"])
    ls = link_status(row, picked)
    res = B.run_affair(entry, meta, names, ls, backend if mode == "review" else None, theta)
    aff, typed = harmonised_type(res["affair"], a)
    post = finalize(aff)
    # v0.1 leaves a field nobody extracted out (affair_post); v0.2 types it (carry_v0_1)
    post["changes"] = typed + [dict(c, now="null not_extracted (schema v0.2)") if c["now"] == "omitted" else c
                               for c in post["changes"]]
    rec = v0_2_all.carry_v0_1(post["affair"])
    if bt.get("name"):
        rec["body"]["name"] = bt["name"]
    if isinstance(a.get("type_harmonized_id"), int):
        rec["type"]["opd_harmonised_id"] = a["type_harmonized_id"]
    fetched = {f"opd:{d['doc_id']}": d for d in docs}
    for doc in rec.get("documents") or []:  # as in the P5 records: the fetched file's sha256 and OPD's text status
        d = fetched.get(doc["doc_id"])
        if d:
            doc["sha256"] = d["sha256"]
            if d.get("opd_text_status"):
                doc["opd_text_status"] = d["opd_text_status"]
    notes = _apply_parts(rec, entry)
    roles = v0_2_roles.extract_row("opd", entry)
    rec = v0_2_all.with_roles(rec, roles)
    _parts_reasons(rec, notes)
    src = sources or {}
    single = src.get("single_exports") or {}
    ran = [n for n in notes if n["ran"]]
    note = (f"built by {CONVERTER} ({mode}) from OPD's export rows ({single.get('source', 'given rows')}"
            + (f", saved slice {src['slice']}" if src.get("slice") else "")
            + (f", index generated {single['generated_at']}" if single.get("generated_at") else "") + ") and the "
            "affair's documents (" + ", ".join(f"{d['role']} opd:{d['doc_id']}" for d in docs) + "); answer-link status "
            f"{ls} from this affair's rows; document parts: "
            + (f"{sum(len(rec['documents'][n['index']].get('parts') or []) for n in ran)} by {ran[0]['note']}" if ran
               else notes[0]["note"] if notes else PARTS_NOT_EXTRACTED))
    ex = rec["extraction"]
    ex["notes"] = f"{ex['notes']}; {note}" if ex.get("notes") else note
    try:
        valid = schema_module().validate_affair(rec)
    except Exception as e:  # noqa: BLE001 - pydantic.ValidationError and the model's own ValueErrors
        raise AffairError("invalid_record", f"{type(e).__name__}: {str(e)[:600]}") from e
    sugg = res.get("suggestions") or {}
    return dict(opd_affair=affair_id, status="ok", schema_version="0.2.0",
                record=valid.model_dump(mode="json", exclude_none=True),
                needs_review=bool(post["needs_review"] or sugg), review=post["review"], suggestions=sugg,
                changes=post["changes"],
                sources=dict(src, documents=[{k: d[k] for k in ("role", "doc_id", "name", "url", "sha256", "extractor",
                                                                    "image_only")} for d in docs],
                             answer_link_status=ls, mode=mode))


def failure(affair_id: int, e: AffairError) -> dict:
    return dict(opd_affair=affair_id, status=e.kind, reason=e.detail)


def run(affair_ids: list[int], *, source: str = "auto", rows_file: str | None = None, save_rows_file: str | None = None,
        **kw) -> list[dict]:
    """Rows for the affairs (one pass over the exports), then one product row or typed failure per affair."""
    try:
        rows = load_rows(Path(rows_file)) if rows_file else read_rows(affair_ids, source)
    except AffairError as e:
        return [failure(a, e) for a in affair_ids]
    if rows_file:
        p = Path(rows_file).resolve()
        rows["sources"] = dict(rows.get("sources") or {}, slice=p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT)
                               else p.name)
    if save_rows_file:
        save_rows(rows, Path(save_rows_file))
    out = []
    for aid in affair_ids:
        row = rows["affairs"].get(aid) or dict(affair=None)
        body = (row.get("affair") or {}).get("body_key")
        try:
            out.append(build(aid, row, rows["names"].get(body, []), sources=rows.get("sources"), **kw))
        except AffairError as e:
            out.append(failure(aid, e))
    return out


# ------------------------------------------------------------------------------------------------ CLI
def add_parser(sub) -> argparse.ArgumentParser:
    p = sub.add_parser("affair", help="one OPD affair -> one validated schema v0.2 record (OPD exports + its documents)",
                       description="Build one validated schema v0.2 record for an OPD affair from OPD's exports and the "
                       "affair's question and answer documents. See docs/affair.md.")
    p.add_argument("--opd-affair", type=int, action="append", required=True, metavar="ID",
                   help="OPD affair id (repeat for several: one JSON line each, one pass over the exports)")
    p.add_argument("--schema", choices=SCHEMA_VERSIONS, default="v0.2", help="record schema (v0.2)")
    p.add_argument("--mode", choices=["rules_only", "review"], default="rules_only",
                   help="rules_only (default, no model) | review (adds Apertus suggestions next to the record, flagged "
                   "needs_review; needs a fitted θ)")
    p.add_argument("--out", metavar="FILE", help="write here instead of stdout")
    p.add_argument("--record-only", action="store_true", help="print the v0.2 record alone (no needs_review/sources)")
    p.add_argument("--source", choices=["auto", "exports", "local"], default="auto",
                   help="where OPD's rows come from: exports (files.openparldata.ch, or GP_EXPORTS_DIR), local (GP_OPD_RAW "
                   "+ GP_DOCS_META copies), auto (local when present, else exports)")
    p.add_argument("--rows", metavar="FILE", help="read OPD's rows from a slice saved with --save-rows (no exports read)")
    p.add_argument("--save-rows", metavar="FILE", help="also save the OPD rows read (affair, events, contributors, "
                   "document rows, the body's office holders' names) to FILE")
    p.add_argument("--question-doc", type=int, metavar="OPD_DOC_ID", help="the member's text, if the pairing rule "
                   "picks another or none (single affair)")
    p.add_argument("--answer-doc", type=int, metavar="OPD_DOC_ID", help="the answer document (single affair)")
    p.add_argument("--backend", default="gguf", help="review mode: as `convert --backend`")
    p.add_argument("--theta", type=float, help="review mode: override θ (not recommended)")
    p.add_argument("--allow-build-mismatch", action="store_true", help="review mode: as `convert`")
    p.add_argument("--timeout", type=int, default=60, help="seconds per document request (default 60)")
    p.add_argument("--tries", type=int, default=2, help="attempts per document (default 2)")
    return p


def main_args(a) -> int:
    if len(a.opd_affair) > 1 and (a.question_doc or a.answer_doc):
        print("--question-doc / --answer-doc apply to a single --opd-affair", file=sys.stderr)
        return 2
    be = theta = None
    if a.mode == "review":
        from .convert import batch

        be, theta = batch.resolve_review(a.backend, a.theta, allow_build_mismatch=a.allow_build_mismatch)
    rows = run(a.opd_affair, source=a.source, rows_file=a.rows, save_rows_file=a.save_rows, mode=a.mode, backend=be,
               theta=theta, question_doc=a.question_doc, answer_doc=a.answer_doc, timeout=a.timeout, tries=a.tries)
    many = len(rows) > 1

    def show(r):
        x = r["record"] if (a.record_only and r["status"] == "ok") else r
        return json.dumps(x, ensure_ascii=False, **({} if many else dict(indent=1))) + "\n"
    text = "".join(show(r) for r in rows)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    bad = 0
    for r in rows:
        if r["status"] != "ok":
            bad += 1
            print(f"affair {r['opd_affair']}: {r['status']}: {r['reason']}", file=sys.stderr)
        elif r["needs_review"]:
            for x in r["review"]:
                print(f"affair {r['opd_affair']}: needs review ({x['field']}): {x['reason']}", file=sys.stderr)
            for k in r["suggestions"]:
                print(f"affair {r['opd_affair']}: needs review ({k}): Apertus suggestion", file=sys.stderr)
    return 2 if bad else 0


def main(argv: list[str] | None = None) -> int:
    from .convert.build_guard import BuildMismatch

    ap = argparse.ArgumentParser(prog="python -m gegenprobe.affair_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add_parser(sub)
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["affair"]:
        args = ["affair", *args]
    try:
        return main_args(ap.parse_args(args))
    except BuildMismatch as e:
        print(str(e), file=sys.stderr)
        return 3


# ------------------------------------------------------------------------------------------------ make run step
def _item_key(path: str, i: int, x: dict) -> str:
    """List items of actors and dates are keyed by role and value (their order differs between record paths)."""
    if path == "actors":
        return f"[{x.get('role')}:{(x.get('name') or {}).get('value')}]"
    if path == "dates":
        return f"[{x.get('role')}:{(x.get('date') or {}).get('value')}]"
    return str(i)


def _flat(o, prefix: str = "") -> dict[str, object]:
    out = {}
    if isinstance(o, dict):
        for k, v in o.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(o, list) and o and all(isinstance(x, dict) for x in o):
        for i, v in enumerate(o):
            out.update(_flat(v, f"{prefix}.{_item_key(prefix, i, v)}"))
    else:
        out[prefix] = o
    return out


IGNORED = ("extraction.", "empty_reasons.")  # run metadata and the reasons of empty lists (compared via the lists)


def compare(rec: dict, sample: dict) -> dict:
    """Field-by-field comparison where comparable: the leaf paths both records carry (extraction metadata excluded),
    plus the asserted fields (answer date when the sample has one, language of each text, the documents)."""
    a, b = _flat(rec), _flat(sample)
    both = sorted(k for k in set(a) & set(b) if not k.startswith(IGNORED))
    diff = [k for k in both if a[k] != b[k]]

    def ans(r):
        q = (r.get("qa") or [{}])[0].get("answer_date") or {}
        return q.get("value") if q.get("kind") == "value" else None

    def docs(r):
        return {d["role"]: (d["doc_id"], tuple(d.get("language_of_text") or [])) for d in r.get("documents") or []}
    checks = dict(documents=docs(rec) == docs(sample), language_of_text=docs(rec) == docs(sample))
    if ans(sample) is not None:
        checks["answer_date"] = ans(rec) == ans(sample)
    return dict(compared=len(both), equal=len(both) - len(diff), differ=diff, checks=checks,
                answer_date=ans(rec), sample_answer_date=ans(sample))


def _samples() -> list[tuple[Path, dict]]:
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(SAMPLES_DIR.glob("*.json"))]


def step(ctx: dict) -> dict:
    """`make run` step: the affair command on the affairs of the three committed v0.2 samples (Bern, Vernier, Lugano).
    OPD's rows: the committed slice data/affair_cli/opd_rows_samples.json (saved by --save-rows), or, with
    GP_AFFAIR_LIVE_EXPORTS=1, the live exports (about 0.7 GB streamed, BE's docs export included); the documents are
    fetched from their sources. PASS: every reached record validates and its documents, language of each text and
    answer date (where the sample has one) equal the committed sample's. SKIP offline or when no source is reachable."""
    if not ctx.get("online"):
        return dict(status="SKIP", summary="offline: the affair command fetches the documents from their sources")
    samples = _samples()
    if not samples:
        return dict(status="SKIP", summary=f"no committed samples in {SAMPLES_DIR}")
    ids = [s["ref"]["opd_id"] for _, s in samples]
    live = os.environ.get("GP_AFFAIR_LIVE_EXPORTS") == "1"
    rows_file = None if live or not SAMPLE_ROWS.exists() else str(SAMPLE_ROWS)
    rows = run(ids, source="exports" if live else "auto", rows_file=rows_file)
    out_dir = Path(ctx.get("out") or "out") / "affair_cli"
    out_dir.mkdir(parents=True, exist_ok=True)
    per, failed, unreachable = [], [], []
    for (p, sample), r in zip(samples, rows):
        tag = f"{sample['ref']['body_key']}:{sample['ref']['opd_id']}"
        (out_dir / f"{sample['ref']['body_key']}_{sample['ref']['opd_id']}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if r["status"] != "ok":
            (unreachable if r["status"] in UNREACHABLE else failed).append(f"{tag} {r['status']}")
            per.append(dict(affair=tag, status=r["status"], reason=r["reason"][:300]))
            continue
        c = compare(r["record"], sample)
        ok = all(c["checks"].values())
        if not ok:
            failed.append(f"{tag} differs from {p.name} in {', '.join(k for k, v in c['checks'].items() if not v)}")
        per.append(dict(affair=tag, sample=p.relative_to(ROOT).as_posix(), status="ok" if ok else "differs",
                        needs_review=r["needs_review"], answer_date=c["answer_date"],
                        sample_answer_date=c["sample_answer_date"], fields_compared=c["compared"],
                        fields_equal=c["equal"], fields_differ=c["differ"], checks=c["checks"]))
    done = [x for x in per if x["status"] in ("ok", "differs")]
    src = "committed export slice" if rows_file else "live exports"
    summary = (f"affair command on {len(samples)} sample affairs (rows: {src}; documents fetched): "
               + "; ".join(f"{x['affair']} " + (f"valid, answer date {x['answer_date']}, {x['fields_equal']}/"
                                                 f"{x['fields_compared']} comparable fields equal to the "
                                                 f"{x['sample'].rsplit('/', 1)[-1].split('_', 1)[0].upper()} sample"
                                                 if x in done else x["status"]) for x in per))
    if failed:
        return dict(status="FAIL", summary=summary + f"; FAIL: {'; '.join(failed)}", affairs=per)
    if not done:
        return dict(status="SKIP", summary=f"no source reachable ({'; '.join(unreachable)})", affairs=per)
    return dict(status="PASS", summary=summary + (f"; unreachable: {'; '.join(unreachable)}" if unreachable else ""),
                affairs=per)


if __name__ == "__main__":
    sys.exit(main())
