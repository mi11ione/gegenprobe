"""How complete the validated v0.2 records are: per field, how often a record carries a value, a typed null (by reason),
an empty list (by reason) or nothing. "186 records validate" says the records have the schema's form; this says what they
hold.

    python -m gegenprobe.schema.v0_2_completeness           write results/schema/v0_2/field_completeness.json
    python -m gegenprobe.schema.v0_2_completeness --check   exit 1 if a fresh run differs from the committed file

Records: the converter's 120 (P3 29, P3b 36, P5 40, federal 15: results/schema/v0_2/{p3,p3b,p5,fed}_records.jsonl) and
P8's 66 gold records (p8_records.jsonl), 186 in all; `before` = the same records without the OPD-metadata overlay
(gegenprobe.schema.v0_2_parts.render(meta=False)), `after` = the committed records (with gegenprobe.schema.v0_2_meta).
No network, no model, no document text.

Fields: the 17 of the skeleton, each read exactly as P11 reads a record (eval.p11.arms.record_status, GUIDE_P11_NI.md §3):
value / value_role_unsplit (an answer date whose role, decision or dispatch, the record does not split) / value:<status>
(answer-link status) / null:<reason> / empty:<reason> (an empty list and its typed reason) / partial (some documents
without a language of text) / absent (the record carries neither the role nor a reason for its absence). Plus the
provenance-bearing fields outside the 17 that the brief names or J1 counted: qa[0].answering_body, qa[0].answer_identifier,
type.harmonised (OPD's type; `unknown` counts as absent) and type.instrument_named.
`carries` counts value and value:<status>, `unsplit` value_role_unsplit, `typed_gap` null:* and empty:*, `untyped` absent
and partial.
"""
from __future__ import annotations

import collections
import json
import sys

from .p8_v0_2 import OUT

FILE = OUT / "field_completeness.json"
CONVERTER = ("p3", "p3b", "p5", "fed")
SETS = CONVERTER + ("p8",)
EXTRA = ("answering_body", "answer_identifier", "type_harmonised", "instrument_named")


def _vs(v: dict | None) -> str:
    if not v:
        return "absent"
    return "value" if v.get("kind") == "value" else f"null:{v.get('null_reason')}"


ACTOR_FIELDS = {"submitter": ("sole_author", "first_signatory", "joint_author", "spokesperson", "submitter"),
                "co_signatories": ("co_signatory", "supporter"), "addressed_body": ("addressed_body",)}
DATE_FIELDS = {"date_decision": "answer_decided", "date_dispatch": "answer_dispatched"}


def _null_slot(slots: list[dict]) -> str | None:
    """A role carried only as typed nulls (an actor whose name, a dated event whose date, is a TypedNull)."""
    vals = [v for v in slots if (v or {}).get("kind") == "value"]
    nulls = [v for v in slots if (v or {}).get("kind") == "null"]
    return None if vals or not nulls else f"null:{nulls[0].get('null_reason')}"


def status(rec: dict, field: str) -> str:
    """P11's reading (eval.p11.arms.record_status, frozen), extended (R20) where P11's reading cannot see a typed reason:
    a role carried only as a typed null (an actor with a TypedNull name, a dated event with a TypedNull date) reads
    null:<reason>, not value; the addressed body of a record whose actors list is empty reads that list's reason;
    a language of text missing only for documents whose empty list carries a typed reason reads
    partial_typed:<reason> (some documents carry it) or empty:<reason> (none does)."""
    from eval.p11.arms import _empty, record_status

    if field in ACTOR_FIELDS:
        actors = rec.get("actors") or []
        n = _null_slot([a.get("name") for a in actors if a.get("role") in ACTOR_FIELDS[field]])
        if n:
            return n
        if field == "addressed_body" and not actors:
            return _empty(rec, "actors")
    if field in DATE_FIELDS:
        want = DATE_FIELDS[field]
        q = (rec.get("qa") or [None])[0] or {}
        n = _null_slot([d.get("date") for d in rec.get("dates") or [] if d.get("role") == want])
        if n and (q.get("answer_date") or {}).get("role") != want:
            return n
    if field == "language":
        docs = rec.get("documents") or []
        miss = [i for i, d in enumerate(docs) if not d.get("language_of_text")]
        reasons = [(rec.get("empty_reasons") or {}).get(f"documents.{i}.language_of_text") for i in miss]
        if docs and miss and all(reasons):
            return f"{'empty' if len(miss) == len(docs) else 'partial_typed'}:{reasons[0]['reason']}"
    if field not in EXTRA:
        return record_status(rec, field)
    q = (rec.get("qa") or [None])[0]
    if field in ("answering_body", "answer_identifier"):
        if q is None:
            r = (rec.get("empty_reasons") or {}).get("qa")
            return f"empty:{r['reason']}" if r else "absent"
        return _vs(q.get(field))
    t = rec.get("type") or {}
    if field == "type_harmonised":
        return "absent" if t.get("harmonised") in (None, "unknown") else "value"
    return _vs(t.get("instrument_named"))


def _route(rec: dict, field: str) -> str | None:
    """The route of a carried value where the field is one provenance-bearing value (else None)."""
    q = (rec.get("qa") or [{}])[0]
    v = {"date_answer": q.get("answer_date"), "procedural_state": rec.get("procedural_state"),
         "decision_outcome": rec.get("decision"), "government_recommendation": rec.get("government_recommendation"),
         "answering_body": q.get("answering_body"), "answer_identifier": q.get("answer_identifier"),
         "type": (rec.get("type") or {}).get("instrument_function"),
         "instrument_named": (rec.get("type") or {}).get("instrument_named")}.get(field)
    return v.get("route") if isinstance(v, dict) and v.get("kind") == "value" else None


def _kind(s: str) -> str:
    if s == "value_role_unsplit":
        return "unsplit"
    return "carries" if s.startswith("value") else "typed_gap" if s.startswith(("null:", "empty:", "partial_typed:")) \
        else "untyped"


def table(records: dict[str, list[dict]]) -> dict:
    """{field: {set: {n, carries, typed_gap, untyped, statuses, value_routes}}} plus the converter and all totals."""
    from eval.p11.annotate import NI_FIELDS

    out = {}
    groups = {**{k: records[k] for k in records}, "converter": [r for k in CONVERTER for r in records[k]],
              "all": [r for k in SETS for r in records[k]]}
    for f in NI_FIELDS + EXTRA:
        out[f] = {}
        for g, recs in groups.items():
            st = collections.Counter(status(r, f) for r in recs)
            kinds = collections.Counter()
            for s, n in st.items():
                kinds[_kind(s)] += n
            routes = collections.Counter(_route(r, f) for r in recs if status(r, f).startswith("value"))
            routes.pop(None, None)
            out[f][g] = dict(n=len(recs), carries=kinds["carries"], unsplit=kinds["unsplit"],
                             typed_gap=kinds["typed_gap"], untyped=kinds["untyped"], statuses=dict(sorted(st.items())),
                             **({"value_routes": dict(sorted(routes.items()))} if routes else {}))
    return out


def _records(files: dict[str, str] | None) -> dict[str, list[dict]]:
    def lines(name: str) -> list[dict]:
        text = files[name] if files and name in files else (OUT / name).read_text(encoding="utf-8")
        return [json.loads(x) for x in text.splitlines() if x.strip()]
    return {k: lines("fed_records.jsonl" if k == "fed" else f"{k}_records.jsonl") for k in SETS}


def _walk(o, path: str = ""):
    """Yield (path, value) for every provenance-bearing value (Valued or TypedNull) of a record."""
    if isinstance(o, dict):
        if o.get("kind") in ("value", "null") and "route" in o:
            yield path, o
            return
        for k, v in o.items():
            if k != "empty_reasons":
                yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{path}.{i}")


def provenance_kind(v: dict) -> str:
    """page_span (document, page and character span, pinned by quote or hash) / page_only (an annotator's label on a
    document page) / document_level (a model's closed-set pick over a whole document) / opd_record (basis metadata,
    source an OPD record) / other_record (basis metadata, another committed record) / typed_null / other."""
    if v.get("kind") == "null":
        return "typed_null"
    if v.get("page") is not None and v.get("char_start") is not None and v.get("char_end") is not None:
        return "page_span"
    if v.get("basis") == "metadata":
        return "opd_record" if str(v.get("source") or "").startswith("opd:") else "other_record"
    if v.get("page") is not None and v.get("doc"):
        return "page_only"
    if v.get("doc") and v.get("candidates"):
        return "document_level"
    return "other"


def provenance(records: dict[str, list[dict]]) -> dict:
    """Every provenance-bearing value of the records by provenance kind, per set, the converter's and all; plus the
    typed reasons of empty lists (empty_reasons) and the metadata sources that are not OPD records."""
    groups = {**records, "converter": [r for k in CONVERTER for r in records[k]],
              "all": [r for k in SETS for r in records[k]]}
    out = {}
    for g, recs in groups.items():
        c, other = collections.Counter(), collections.Counter()
        for r in recs:
            for _path, v in _walk(r):
                k = provenance_kind(v)
                c[k] += 1
                if k == "other_record":
                    other[str(v.get("source")).split("#", 1)[0]] += 1
        n_val = sum(n for k, n in c.items() if k != "typed_null")
        out[g] = dict(n_records=len(recs), n_values=n_val, n_typed_nulls=c["typed_null"],
                      kinds=dict(sorted(c.items())),
                      typed_empty_lists=sum(len(r.get("empty_reasons") or {}) for r in recs),
                      other_record_sources=dict(sorted(other.items())))
    return dict(
        label="POST HOC, descriptive (R20): what each value's provenance is, over every provenance-bearing value",
        definitions=(
            "page_span: document, page and character span (quote or quote_sha256); page_only: an annotator's label "
            "located to a document page; document_level: a model's closed-set pick over a document; opd_record: basis "
            "metadata with an OPD record as source; other_record: basis metadata with another committed record as "
            "source; typed_null: a TypedNull with its reason; typed_empty_lists: empty_reasons entries"),
        groups=out)


def render() -> str:
    from . import v0_2_parts as VP

    before = table(_records(VP.render(meta=False)))
    after = table(_records(None))
    rows = []
    for f in after:
        a, b = after[f]["converter"], before[f]["converter"]
        rows.append(dict(field=f, extra=f in EXTRA, converter_n=a["n"], converter_carries_before=b["carries"],
                         converter_carries=a["carries"], converter_unsplit=a["unsplit"],
                         converter_typed_gap=a["typed_gap"],
                         converter_untyped=a["untyped"], all_n=after[f]["all"]["n"],
                         all_carries=after[f]["all"]["carries"], all_unsplit=after[f]["all"]["unsplit"],
                         all_typed_gap=after[f]["all"]["typed_gap"],
                         all_untyped=after[f]["all"]["untyped"]))
    n17 = [r for r in rows if not r["extra"]]
    out = dict(
        label=("POST HOC, descriptive: what the validated v0.2 records carry per field (no hypothesis); the record "
               "reading is P11's (eval.p11.arms.record_status)"),
        command="PYTHONPATH=src:. python -m gegenprobe.schema.v0_2_completeness",
        records=dict(converter={k: len(_records(None)[k]) for k in CONVERTER}, p8=len(_records(None)["p8"]),
                     converter_n=sum(len(_records(None)[k]) for k in CONVERTER),
                     all_n=sum(len(_records(None)[k]) for k in SETS)),
        definitions=dict(carries="value or value:<answer-link status>",
                         unsplit=("value_role_unsplit: decision / dispatch date, where the record carries an answer "
                                  "date without saying which of the two it is"),
                         typed_gap="a typed null (null:<reason>) or an empty list with its typed reason (empty:<reason>)",
                         untyped="absent (no value and no reason) or partial (a language of text for some documents only)",
                         reading=("P11's (eval.p11.arms.record_status), extended in R20 where it cannot see a typed "
                                  "reason (status): a role carried only as a typed null reads null:<reason>; a "
                                  "language of text missing only where the document's empty list carries a typed "
                                  "reason reads partial_typed:<reason> / empty:<reason> (typed_gap)"),
                         before="the same records without gegenprobe.schema.v0_2_meta (OPD metadata overlay)",
                         extra="fields outside the 17 of the skeleton: " + ", ".join(EXTRA)),
        summary=dict(
            fields_17=len(n17),
            converter_cells=len(n17) * n17[0]["converter_n"],
            converter_carries_before=sum(r["converter_carries_before"] for r in n17),
            converter_carries=sum(r["converter_carries"] for r in n17),
            converter_unsplit=sum(r["converter_unsplit"] for r in n17),
            converter_typed_gap=sum(r["converter_typed_gap"] for r in n17),
            converter_untyped=sum(r["converter_untyped"] for r in n17),
            all_cells=len(n17) * n17[0]["all_n"],
            all_carries=sum(r["all_carries"] for r in n17),
            all_unsplit=sum(r["all_unsplit"] for r in n17),
            all_typed_gap=sum(r["all_typed_gap"] for r in n17),
            all_untyped=sum(r["all_untyped"] for r in n17),
            fields_carried_by_every_converter_record=sorted(r["field"] for r in n17
                                                            if r["converter_carries"] == r["converter_n"]),
            fields_untyped_somewhere_in_converter=sorted(r["field"] for r in n17 if r["converter_untyped"]),
        ),
        rows=rows,
        provenance=provenance(_records(None)),
        after=after,
        before={f: {g: {k: v for k, v in x.items() if k in ("n", "carries", "unsplit", "typed_gap", "untyped",
                                                               "statuses")}
                    for g, x in before[f].items() if g in CONVERTER + ("converter",)} for f in before},
    )
    return json.dumps(out, ensure_ascii=False, indent=1) + "\n"


def step(ctx: dict) -> dict:
    text = render()
    same = FILE.exists() and FILE.read_text(encoding="utf-8") == text
    s = json.loads(text)["summary"]
    return dict(status="PASS" if same else "FAIL",
                summary=(f"field completeness: {s['converter_carries']}/{s['converter_cells']} field cells of the "
                         f"converter's records carry a value ({s['converter_carries_before']} before the OPD-metadata "
                         f"overlay), {s['converter_typed_gap']} a typed gap, {s['converter_untyped']} untyped; "
                         + ("identical to the committed file" if same else "DIFFERS from the committed file")))


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        same = FILE.exists() and FILE.read_text(encoding="utf-8") == text
        print("field completeness:", "committed file current" if same else "differs")
        return 0 if same else 1
    FILE.write_text(text, encoding="utf-8")
    print(FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
