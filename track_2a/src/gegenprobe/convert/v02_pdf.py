"""`gegenprobe convert <pdf> --schema v0.2`: one bare PDF (no OPD affair id) -> one validated schema v0.2 record.

The PDF goes through the same record pipeline as `gegenprobe affair` (affair.extract rule fields, affair.build.assemble,
affair_post.finalize, schema.v0_2_all.carry_v0_1 and with_roles, the document-parts detector and the Q/A pairing),
with the one difference that there is no OPD record: the metadata half of the pipeline sees an empty affair. Every
field only OPD's metadata could supply (affair number, harmonised type, OPD's events, procedural state, decision, title,
contributors) is therefore a typed null `not_in_corpus`, route metadata, with the evidence that the input was a bare
PDF; every field the rules read from the document carries its page, span and rule as usual. No model (rules_only).

Inputs the caller may add (they are references, not values with provenance): --body (OPD body key: the parliament's
level and official languages come from the census bodies table; with another key give --level), --affair-number
(ref.number), --affair-type (type.harmonised, source_label names the flag; it also makes the recommendation
not_applicable for interpellations and questions), --lang, --doc-role question|answer (default: the converter's
own doc_role; a document it cannot place needs the flag).

Output: the convert row (status, input, schema_version, record, needs_review, review, changes, sources, the v0.1 row's
fields), or a typed failure row (the convert failure kinds, plus `doc_role_unknown` and `level_unknown`).
"""
from __future__ import annotations

import copy
import csv
import gzip
import json
import re

from ..paths import DATA, PDF_CACHE

CONVERTER = "gegenprobe.convert --schema v0.2"
PLACEHOLDER = "pdfinput"  # entry doc_id while the pipeline runs (it prefixes 'opd:'); renamed to the v0.1 doc id after
BARE = "no OPD record: converted from a bare PDF (gegenprobe convert --schema v0.2); only OPD's metadata could supply it"
LEVEL = {"canton": "canton", "city": "commune", "municipality": "commune", "country": "federal"}
LEVELS = ("cantonal", "communal", "federal")
LEVEL_ARG = {"cantonal": "canton", "communal": "commune", "federal": "federal"}


def _census_bodies() -> dict[str, dict]:
    with gzip.open(DATA / "census" / "bodies.tsv.gz", "rt", encoding="utf-8") as f:
        return {r["key"]: r for r in csv.DictReader(f, delimiter="\t")}


FAILURE_KINDS = ("level_unknown", "doc_role_unknown", "invalid_record")  # besides convert's own (convert/output.py)


def _fail(kind: str, reason: str, inp: dict) -> dict:
    assert kind in FAILURE_KINDS, kind
    return dict(status=kind, reason=reason, input=inp, schema_version="0.2.0")


def _rename(o, old: str, new: str):
    """Every string equal to `old` (the pipeline's doc id) becomes `new`, in place."""
    if isinstance(o, dict):
        for k, v in o.items():
            if v == old:
                o[k] = new
            else:
                _rename(v, old, new)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if v == old:
                o[i] = new
            else:
                _rename(v, old, new)


def _bare_nulls(o) -> int:
    """Rewrite the evidence of every metadata-route not_in_corpus null (the empty affair's) to say why; returns how many."""
    n = 0
    if isinstance(o, dict):
        if o.get("kind") == "null" and o.get("null_reason") == "not_in_corpus" and o.get("route") == "metadata":
            o["evidence"] = BARE
            n += 1
        for v in o.values():
            n += _bare_nulls(v)
    elif isinstance(o, list):
        for v in o:
            n += _bare_nulls(v)
    return n


def convert(source: str, *, body: str | None = None, level: str | None = None, affair_number: str | None = None,
            affair_type: str | None = None, lang: str | None = None, doc_role: str | None = None,
            timeout: int = 60, tries: int = 2) -> dict:
    from .. import affair_cli
    from ..affair import build as B
    from ..affair import extract as X
    from ..affair import meta as M
    from ..affair_post import finalize
    from ..schema import body_languages, role_consistency, v0_2_all, v0_2_roles
    from ..schema.p8_v0_2 import schema_module
    from . import batch

    inp = {k: v for k, v in dict(source=source, body=body, level=level, affair_number=affair_number,
                                 affair_type=affair_type, lang=lang, doc_role=doc_role).items() if v not in (None, "")}
    v01 = batch.convert_one(source, dict(body=body, affair_number=affair_number, affair_type=affair_type, lang=lang),
                            mode="rules_only", timeout=timeout, tries=tries)
    if v01["status"] != "ok":
        return dict(v01, schema_version="0.2.0")
    bt = _census_bodies().get(body or "", {})
    lvl = LEVEL_ARG.get(level or "") or LEVEL.get(bt.get("type") or "")
    if not body or not lvl:
        return _fail("level_unknown", "a v0.2 record names its parliament and level (body.key, body.level): give --body "
                     "(an OPD body key, e.g. SG, 261) or, for a parliament outside OPD's bodies table, --body and "
                     "--level cantonal|communal|federal", inp)
    role = doc_role or (v01.get("doc_role") or {}).get("value")
    if role not in ("question", "answer"):
        return _fail("doc_role_unknown", f"the converter placed this document as {role!r} "
                     f"({(v01.get('doc_role') or {}).get('basis')}); give --doc-role question|answer", inp)
    d = v01["record"]["doc"]
    sha, doc_id = d["sha256"], d["doc_id"]
    lg = lang or v01.get("language")
    entry = dict(split="pdf", affair_id=None, body=body, level=lvl, lang=lg if lg in ("de", "fr", "it") else None,
                 affair_type=None, docs=[dict(role=role, doc_id=PLACEHOLDER, url=source if re.match(r"https?://", source)
                                              else None, sha256=sha, image_only=bool(d.get("image_only")),
                                              extractor=d.get("extractor"))])
    # the metadata half sees an empty affair: every OPD-only field becomes a typed null not_in_corpus
    meta = dict(affair=dict(id=None, body_key=body, number=None), events=[], contributors=[])
    names = M.body_names().get(body, [])
    tx = B.texts(entry)
    dq, pq, _ = tx.get("question", (None, None, None))
    da, pa, _ = tx.get("answer", (None, None, None))
    mo = X.from_metadata(meta, None)
    t = X.TYPE_BY_EN.get((affair_type or "").lower())  # --affair-type arrives as OPD's harmonised name
    if t:
        mo["affair_type"] = dict(value=t, route="metadata", basis="metadata", source="input:--affair-type",
                                 source_label=affair_type)
    atype = mo["affair_type"].get("value")
    r_cas = X.rule_fields(pq, pa, dq, da, mo, body, names, atype, [])
    C = {}
    for k in B.SCORED:
        if k in ("answer_date", "decision_number", "related_affairs", "addressed_body"):
            C[k] = r_cas.get(k)
        elif k == "co_signatories":
            C[k] = mo.get("co_signatories", [])
        else:
            mv = mo.get(k)
            C[k] = mv if (isinstance(mv, dict) and mv.get("value") is not None) else r_cas.get(k)
    aff = B.assemble(entry, meta, mo, C, tx).model_dump(mode="json", exclude_none=True)
    post = finalize(aff)
    changes = [dict(c, now="null not_extracted (schema v0.2)") if c["now"] == "omitted" else c for c in post["changes"]]
    rec = v0_2_all.carry_v0_1(post["affair"])
    rec["ref"] = dict(body_key=body, **({"number": affair_number} if affair_number else {}), virtual=False)
    if bt.get("name"):
        rec["body"]["name"] = bt["name"]
    if not rec["body"].get("languages"):
        bl, _ = body_languages.languages(body)
        if bl:
            rec["body"]["languages"] = bl
    notes = affair_cli._apply_parts(rec, entry)
    rec = v0_2_all.with_roles(rec, v0_2_roles.extract_row("pdf", entry))
    rec, _ = role_consistency.harmonise(rec)
    rec, qa_note = affair_cli._apply_qa(rec, entry)
    role_flags = role_consistency.violations(rec.get("actors") or [])
    affair_cli._parts_reasons(rec, notes)
    rec["empty_reasons"] = {k: (dict(v, evidence=BARE) if v.get("reason") == "not_in_corpus" and v.get("route") ==
                                "metadata" else v) for k, v in rec["empty_reasons"].items()}
    n_bare = _bare_nulls(rec)
    _rename(rec, f"opd:{PLACEHOLDER}", doc_id)
    for doc in rec.get("documents") or []:
        if doc["doc_id"] == doc_id:
            doc["source"] = "other"
            doc["sha256"] = sha
            if not entry["docs"][0]["url"]:
                doc.pop("url", None)
    ex = rec["extraction"]
    ex["converter_version"] = "gegenprobe-0.1.0+pdf"
    note = (f"built by {CONVERTER} (rules_only) from one PDF (sha256 {sha}, role {role}) without an OPD record: fields "
            f"only OPD's metadata supplies are typed not_in_corpus ({n_bare} values); document parts: "
            + (notes[0]["note"] if notes else affair_cli.PARTS_NOT_EXTRACTED) + (f"; {qa_note}" if qa_note else ""))
    ex["notes"] = f"{ex['notes']}; {note}" if ex.get("notes") else note
    try:
        valid = schema_module().validate_affair(copy.deepcopy(rec))
    except Exception as e:  # noqa: BLE001 - pydantic.ValidationError and the model's own ValueErrors
        return _fail("invalid_record", f"{type(e).__name__}: {str(e)[:600]}", inp)
    review = list(post["review"]) + [dict(field="actors", reason=f"role_inconsistent: {v} "
                                          "(gegenprobe.schema.role_consistency)") for v in role_flags]
    return dict(status="ok", input=inp, schema_version="0.2.0", record=valid.model_dump(mode="json", exclude_none=True),
                needs_review=bool(post["needs_review"] or review or v01.get("needs_review")),
                review=review + [dict(field=r["field"], reason=r["reason"]) for r in v01.get("review_reasons") or []],
                changes=changes, not_in_corpus=n_bare,
                sources=dict(document=dict(source=source, sha256=sha, doc_id=doc_id, role=role,
                                           role_basis=("--doc-role" if doc_role else (v01.get("doc_role") or {}).get("basis")),
                                           extractor=d.get("extractor"), cache=str(PDF_CACHE / f"{sha}.pdf")),
                             body=dict(key=body, level=rec["body"]["level"],
                                       from_census=bool(bt)), mode="rules_only"),
                v0_1_fields=v01["fields"], rules_coverage=v01.get("rules_coverage"))


def main_args(a) -> int:
    """The CLI branch for `convert --schema v0.2` (single document)."""
    import sys
    if a.batch:
        print("--schema v0.2 converts one PDF per call (no --batch yet); loop over your files", file=sys.stderr)
        return 2
    if not a.source:
        print("give a PDF path or URL", file=sys.stderr)
        return 2
    if a.mode != "rules_only":
        print("--schema v0.2 runs rules_only (review suggestions: the v0.1 row, or `gegenprobe affair --mode review`)",
              file=sys.stderr)
        return 2
    row = convert(a.source, body=a.body, level=a.level, affair_number=a.affair_number, affair_type=a.affair_type,
                  lang=a.lang, doc_role=a.doc_role, timeout=a.timeout, tries=a.tries)
    out = json.dumps(row, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(out + "\n")
    else:
        print(out)
    if row["status"] != "ok":
        print(f"{row['status']}: {row.get('reason')}", file=sys.stderr)
        return 2
    for r in row["review"]:
        print(f"needs review ({r['field']}): {r['reason']}", file=sys.stderr)
    return 0
