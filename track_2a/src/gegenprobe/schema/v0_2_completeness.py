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


def status(rec: dict, field: str) -> str:
    from eval.p11.arms import record_status

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
    return "carries" if s.startswith("value") else "typed_gap" if s.startswith(("null:", "empty:")) else "untyped"


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
