"""Schema v0.2 on P8: the 66 P8 gold affairs as v0.2 records, the v0.1 samples upgraded, the v0.2 JSON Schema.

    python -m gegenprobe.schema.p8_v0_2            write results/schema/v0_2/{affair.schema.json, p8_records.jsonl,
                                                   p8_validation.json}
    python -m gegenprobe.schema.p8_v0_2 --check    exit 1 if a fresh run differs from the committed files

Inputs, all committed: data/p8/p8_gold.jsonl (the P8 gold labels: A1=A2 agreements and A3 tie-breaks), p8_affairs.jsonl
(the two documents OPD links per affair), p8_datelists.jsonl (the letter -> ISO date lists the annotators labelled),
opd_meta_p8.jsonl (OPD's affair, events) and data/schema/affair_types.json (OPD harmonised id -> type). No network, no
model. The schema itself is schema/gegenprobe_schema_v0_2.py (pydantic only, next to schema v0.1).

What the converter writes for each affair, from the gold labels (route `annotator`; a span keeps the gold's
`quote_sha256`, the repository carries no document text for P8):
  * actors: every person or body the documents print as author, signatory, supporter or spokesperson, with its P8 role
    (sole_author, first_signatory, joint_author, co_signatory, supporter, spokesperson; `other` stays `other`) and kind
    (person; group -> parliamentary_group; committee; other_body -> other); a spokesperson names the body it speaks for
  * type: OPD's harmonised type (metadata) with `instrument_function` and `instrument_named` from the documents
  * documents: OPD's language tag (`language_tag`, also v0.1's `language`) and the language of the text (`language_of_text`)
  * dates: OPD's own submission event (role `submitted`, metadata) next to every printed date of the procedure with its
    v0.2 role: signed -> signed, lodged -> lodged, session_lodged -> announced (handed in at a sitting), later_step ->
    later_step, answer_or_decision -> answered, cited and other_procedural -> other; a date with several roles is listed
    once per role
  * government_recommendation: the printed recommendation with its stage (on_referral -> on_adoption, on_fulfilment ->
    on_fulfilment); an interpellation or question gets a typed null `not_applicable`, an answer that prints none
    `not_in_document`
  * procedural_state and decision: typed null `not_extracted` (P8 did not label them)
  * body.languages: the parliament's official languages (gegenprobe.schema.body_languages); documents carry
    `language_of_text_method` "annotator"; every empty list has a typed reason in `empty_reasons` (P8_EMPTY)
"""
from __future__ import annotations

import collections
import datetime as dt
import importlib
import json
import sys

from ..paths import ROOT
from . import body_languages

DATA = ROOT / "data" / "p8"
OUT = ROOT / "results" / "schema" / "v0_2"
SAMPLES = ROOT / "results" / "schema" / "samples"
CONVERTER = "gegenprobe-p8-gold-to-v0.2"
CREATED = dt.datetime(2026, 10, 11, 8, 35, 38, tzinfo=dt.timezone.utc)  # commit time of data/p8/p8_gold.jsonl (fixed)

KIND = {"person": "person", "group": "parliamentary_group", "committee": "committee", "other_body": "other"}
DATE_ROLE = {"signed": "signed", "lodged": "lodged", "session_lodged": "announced", "later_step": "later_step",
             "answer_or_decision": "answered", "cited": "other", "other_procedural": "other"}
STAGE = {"on_referral": "on_adoption", "on_fulfilment": "on_fulfilment"}
LEVEL = {"canton": "cantonal", "commune": "communal", "federal": "federal"}


def schema_module():
    """schema/gegenprobe_schema_v0_2.py, imported the way an integrator does (the schema/ directory on sys.path)."""
    d = str(ROOT / "schema")
    if d not in sys.path:
        sys.path.insert(0, d)
    return importlib.import_module("gegenprobe_schema_v0_2")


def _jsonl(name: str) -> dict[str, dict]:
    out = {}
    for line in (DATA / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[str(r.get("id", r.get("affair_id")))] = r
    return out


def _types() -> dict[int, str]:
    return {i: t["key"] for t in json.loads((ROOT / "data" / "schema" / "affair_types.json").read_text(encoding="utf-8"))
            for i in t.get("opd_harmonised_ids") or []}


def _loc(lab: dict, docs: dict[str, str]) -> dict:
    """doc/page and, when the gold carries one, the span pinned by quote_sha256."""
    sp = lab.get("span") or {}
    out = dict(doc=docs[sp.get("doc") or lab["doc"]], page=sp.get("page") or lab["page"])
    if sp:
        out.update(char_start=sp["char_start"], char_end=sp["char_end"], quote_sha256=sp["quote_sha256"])
    return out


def convert(gold: dict, affair: dict, meta: dict, dates: dict, types: dict[int, str]) -> dict:
    """One P8 gold record -> a v0.2 affair (as a JSON dict)."""
    a, parts, pid = meta["affair"], gold["parts"], gold["id"]
    docs = {d["role"]: f"opd:{d['doc_id']}" for d in affair["docs"]}
    langs = parts["language"]["languages"]
    documents = [dict(doc_id=docs[d["role"]], source="opd", url=d["url"], sha256=d["sha256"], role=d["role"],
                      language=d["opd_lang"] or "unspecified", language_tag=d["opd_lang"] or "unspecified",
                      language_of_text=langs.get(d["role"], []), language_of_text_method="annotator",
                      n_pages=d["pages"], extractor=d["extractor"],
                      image_only=bool(d["image_only"]), opd_text_status=d["opd_text_status"]) for d in affair["docs"]]

    # actors: the submitter part, then anyone the co-signatory part adds (the two lists are the same people in 64/66)
    people, seen = [], set()
    for p in parts["submitter"]["people"] + parts["co_signatories"]["people"]:
        key = (p["name"], p["role"], p["kind"])
        if key not in seen:
            seen.add(key)
            people.append(p)
    bodies = [p["name"] for p in people if p["kind"] in ("group", "committee")
              and p["role"] in ("sole_author", "first_signatory", "joint_author")]
    actors = []
    for p in people:
        actors.append(dict(role=p["role"], kind=KIND[p["kind"]],
                           name=dict(kind="value", value=p["name"], basis="extracted", route="annotator", **_loc(p, docs)),
                           **({"on_behalf_of": bodies[0]} if p["role"] == "spokesperson" and bodies else {})))

    # dates: OPD's submission event (metadata) and the printed procedure dates with their v0.2 roles
    events = []
    sub = next((e for e in sorted(meta["events"], key=lambda e: e["position"]) if e["title_harmonized_id"] == 1), None)
    if sub:
        events.append(dict(role="submitted", label=sub["title_de"] or sub["title_fr"] or sub["title_it"],
                           date=dict(kind="value", value=sub["date"][:10], role="submitted", basis="metadata",
                                     route="metadata", source=f"opd:events/{sub['id']}")))
    letters = {d["letter"]: d for d in dates["dates"]}
    labelled = [(letters[k]["date"], roles, dict(doc=docs[letters[k]["at"][0][0]], page=letters[k]["at"][0][1]))
                for k, roles in sorted(parts["date_submission"]["dates"].items())]
    labelled += [(e["date"], e["roles"], _loc(e, docs)) for e in parts["date_submission"]["extra_dates"]]
    for iso, roles, loc in labelled:
        for r in roles:
            role = DATE_ROLE[r]
            events.append(dict(role=role, label=f"P8: {r}",
                               date=dict(kind="value", value=iso, role=role, basis="normalised", route="annotator", **loc)))

    # type with the instrument's function and name
    fn, named = parts["type"]["function"], parts["type"].get("instrument_named") or {}
    ev = f"P8 gold {pid}: the documents do not let the annotators tell the operative request"
    instrument_function = (dict(kind="null", null_reason="present_unanchored", route="annotator", evidence=ev)
                           if fn["value"] == "unclear" else
                           dict(kind="value", value=fn["value"], basis="inferred", route="annotator", **_loc(fn, docs)))
    instrument_named = None
    if named.get("value") and named["value"] != "none":
        instrument_named = dict(kind="value", value=named["value"], basis="extracted", route="annotator", **_loc(named, docs))
    harmonised = types.get(a["type_harmonized_id"], "unknown")
    typ = dict(harmonised=harmonised, opd_harmonised_id=a["type_harmonized_id"],
               source_label=a["type_name_de"] or a["type_name_fr"] or a["type_name_it"],
               instrument_function=instrument_function, instrument_named=instrument_named)

    # government recommendation with its stage
    rec = parts["government_recommendation"]["recommendation"]
    if rec["act"] in STAGE:
        gov = dict(kind="value", value=rec["value"], basis="inferred", route="annotator", stage=STAGE[rec["act"]],
                   **_loc(rec, docs))
    elif rec["act"] == "not_applicable":
        gov = dict(kind="null", null_reason="not_applicable", route="annotator", doc=docs["answer"],
                   evidence=f"P8 gold {pid}: an interpellation or question, or the answer document is not the executive's answer")
    else:  # none_printed, other
        gov = dict(kind="null", null_reason="not_in_document", route="annotator", doc=docs["answer"],
                   evidence=f"P8 gold {pid}: the answer prints no recommendation by the executive on this affair ({rec['act']})")

    not_extracted = dict(kind="null", null_reason="not_extracted", route="annotator",
                         evidence="P8 labels authors, dates, addressee, instrument, languages and recommendation only")
    title = {lg: a[f"title_{lg}"] for lg in ("de", "fr", "it") if a.get(f"title_{lg}")}
    body_langs, _ = body_languages.languages(a["body_key"])
    rec = dict(
        schema_version="0.2.0",
        ref=dict(body_key=a["body_key"], number=a["number"], opd_id=a["id"]),
        body=dict(key=a["body_key"], level=LEVEL[affair["level"]], languages=body_langs),
        type=typ, title=title, actors=actors, dates=events,
        procedural_state=not_extracted, decision=not_extracted, government_recommendation=gov,
        answer_link_status="attached", documents=documents,
        extraction=dict(converter_version=CONVERTER, schema_version="0.2.0", created=CREATED.isoformat(),
                        notes=f"P8 gold labels ({gold['id']}, eval/prereg9/LOCK9); data/p8/p8_gold.jsonl"),
    )
    rec["empty_reasons"] = p8_empty_reasons(rec, pid)
    return rec


# why a list of a P8 record is empty (path pattern -> reason, route, evidence)
P8_EMPTY = {
    "title": ("not_in_corpus", "metadata", "OPD's affair record carries no title"),
    "languages": ("not_extracted", "annotator", "P8 labels the language of each document, not of the affair"),
    "actors": ("none_printed", "annotator", "P8 gold: the documents print no author"),
    "dates": ("none_printed", "annotator", "P8 gold: no procedure date printed and no OPD submission event"),
    "qa": ("not_extracted", "annotator", "P8 labels no question/answer pairs"),
    "related_affairs": ("not_extracted", "annotator", "P8 labels no related affairs"),
    "body.languages": ("not_in_corpus", "metadata", "no official language recorded for this body"),
    "documents.*.language_of_text": ("text_failed", "annotator", "P8 gold: the document has no readable text"),
    "documents.*.parts": ("not_extracted", "annotator", "P8 labels no document parts (tables, annexes, images)"),
}


def p8_empty_reasons(rec: dict, pid: str) -> dict:
    m = schema_module()
    out = {}
    for path in m.empty_fields(rec):
        key = path if path in P8_EMPTY else ".".join("*" if p.isdigit() else p for p in path.split("."))
        reason, route, ev = P8_EMPTY[key]
        out[path] = dict(reason=reason, route=route, evidence=f"{ev} ({pid})")
    return out


def build() -> tuple[list[dict], dict]:
    m = schema_module()
    gold = _jsonl("p8_gold.jsonl")
    affairs = {str(r["affair_id"]): r for r in _jsonl("p8_affairs.jsonl").values()}
    metas = {str(r["affair_id"]): r for r in _jsonl("opd_meta_p8.jsonl").values()}
    dlists = _jsonl("p8_datelists.jsonl")
    types = _types()
    records, invalid = [], []
    c = collections.defaultdict(collections.Counter)
    for pid in sorted(gold):
        g = gold[pid]
        aid = str(g["affair_id"])
        rec = convert(g, affairs[aid], metas[aid], dlists[pid], types)
        try:
            v = m.validate_affair(rec)
        except Exception as e:  # noqa: BLE001 - recorded, and the test requires none
            invalid.append(dict(id=pid, error=f"{type(e).__name__}: {str(e)[:300]}"))
            continue
        records.append(v.model_dump(mode="json", exclude_none=True))
        for x in v.actors:
            c["actors_by_role"][x.role] += 1
            c["actors_by_kind"][x.kind] += 1
            if x.role == "spokesperson":
                c["spokesperson_on_behalf_of"]["named" if x.on_behalf_of else "not_named"] += 1
        f = v.type.instrument_function
        c["instrument_function"][f.value if f.kind == "value" else f"null:{f.null_reason}"] += 1
        c["dates_by_role"].update(d.role for d in v.dates)
        gr = v.government_recommendation
        c["recommendation_stage"][(gr.stage or "none") if gr.kind == "value" else f"null:{gr.null_reason}"] += 1
        c["documents_with_language_of_text"]["yes" if all(d.language_of_text for d in v.documents) else "no"] += 1
        c["documents_language_tag"].update(d.language_tag for d in v.documents)
        c["affairs_with_new_actor_role"]["yes" if any(x.role in NEW_ROLES for x in v.actors) else "no"] += 1
    up = upgrade_samples(m)
    val = dict(
        schema_version=m.SCHEMA_VERSION,
        source="data/p8/p8_gold.jsonl (P8, eval/prereg9/LOCK9)",
        command="PYTHONPATH=src:. python -m gegenprobe.schema.p8_v0_2",
        n_affairs=len(gold), n_valid=len(records), n_invalid=len(invalid), invalid=invalid,
        n_parliaments=len({r["ref"]["body_key"] for r in records}),
        n_actors=sum(c["actors_by_role"].values()), n_dates=sum(c["dates_by_role"].values()),
        counts={k: dict(sorted(v.items())) for k, v in sorted(c.items())},
        v0_1_samples=up,
    )
    return records, val


NEW_ROLES = {"sole_author", "joint_author", "supporter", "spokesperson", "group"}


def upgrade_samples(m) -> dict:
    v1 = sys.modules["gegenprobe_schema"]
    rows = []
    for p in sorted(SAMPLES.glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        before = v1.Affair.model_validate(obj).model_dump(mode="json")
        after = m.upgrade_v0_1(obj)
        rows.append(dict(sample=p.relative_to(ROOT).as_posix(), valid_v0_2=True,
                         lossless=m.downgrade_to_v0_1(after) == before))
    return dict(n_samples=len(rows), n_lossless=sum(r["lossless"] for r in rows), samples=rows)


def render() -> dict[str, str]:
    m = schema_module()
    records, val = build()
    return {
        "affair.schema.json": json.dumps(m.json_schema("affair"), ensure_ascii=False, indent=1) + "\n",
        "p8_records.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records),
        "p8_validation.json": json.dumps(val, ensure_ascii=False, indent=1) + "\n",
    }


def step(ctx: dict) -> dict:
    """`make run` step: v0.2 re-derived from the committed P8 gold and compared with results/schema/v0_2/ (FAIL on a diff)."""
    files = render()
    bad = [n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != t]
    val = json.loads(files["p8_validation.json"])
    ok = not bad and val["n_invalid"] == 0 and val["v0_1_samples"]["n_lossless"] == val["v0_1_samples"]["n_samples"]
    return dict(status="PASS" if ok else "FAIL",
                summary=f"schema v0.2: {val['n_valid']}/{val['n_affairs']} P8 gold affairs valid, "
                        f"{val['v0_1_samples']['n_lossless']}/{val['v0_1_samples']['n_samples']} v0.1 samples upgrade losslessly"
                        + (f"; differs: {', '.join(bad)}" if bad else ""))


def main(argv: list[str]) -> int:
    files = render()
    if "--check" in argv:
        bad = [n for n, s in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != s]
        print("schema v0.2:", "differs: " + ", ".join(bad) if bad else "committed files current")
        return 1 if bad else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n, s in files.items():
        (OUT / n).write_text(s, encoding="utf-8")
        print(OUT / n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
