"""Schema v0.2 on every whole-affair test: the converter's own records for P3, P3b and P5 carried to v0.2, next to P8.

    python -m gegenprobe.schema.v0_2_all            write results/schema/v0_2/{p3,p3b,p5}_records.jsonl, samples/*.json and
                                                    validation_all.json (P8's files come from gegenprobe.schema.p8_v0_2)
    python -m gegenprobe.schema.v0_2_all --check    exit 1 if a fresh run differs from the committed files

Records, all from committed files (no network, no model):
  * P3 (29 affairs) and P3b (36): the converter's product records. `per_affair[].affair` of
    results/eval3/p3__<build>.json and results/eval5/p3b__none.json is the default `rules_only` record (metadata + rules;
    Apertus suggestions sit apart in `suggestions`, and the P3b record is identical in the `none` and the Apertus run
    except for its timestamp). Each goes through the product post-processing (gegenprobe.affair_post.finalize) and is
    carried to v0.2 by `carry_v0_1`: schema version 0.2.0, `language_tag` = v0.1's `language`, and `qa[].answering_body`,
    which this converter version does not extract, as v0.2's typed null `not_extracted` (v0.1 had no honest reason for
    it, so affair_post left the field out). Nothing else changes; converter_version stays the converter's.
  * P5 (40): the converter's rules-arm records (results/eval6/p5__none.json, `R.records`: Q/A items, people,
    recommendation) assembled into a v0.2 affair by `p5_affair` with OPD's identification metadata from the committed
    census export (data/census/affairs.tsv.gz, bodies.tsv.gz: number, body, level, type) and the two documents OPD links
    (data/gold6/p5_affairs.jsonl). Fields the P5 path does not extract (procedural state, decision, answering body,
    answer date, decision number, dates) are typed nulls `not_extracted` or empty lists.
  * P8 (66): the gold records of gegenprobe.schema.p8_v0_2 (route `annotator`), counted here from
    results/schema/v0_2/p8_records.jsonl.
validation_all.json counts, per set: affairs, valid, invalid (with the error), the routes and null reasons used, the
actor and date roles used, and which of v0.2's additions occur in the set.
"""
from __future__ import annotations

import collections
import copy
import csv
import gzip
import json
import sys

from ..paths import ROOT
from .p8_v0_2 import OUT, schema_module

P3 = ROOT / "results" / "eval3" / "p3__publicai_swiss-ai_apertus-v1.5-8b.json"
P3B = ROOT / "results" / "eval5" / "p3b__none.json"
P5 = ROOT / "results" / "eval6" / "p5__none.json"
P5_AFFAIRS = ROOT / "data" / "gold6" / "p5_affairs.jsonl"
CENSUS = ROOT / "data" / "census"
SAMPLES_DIR = OUT / "samples"
CARRY = "gegenprobe.schema.v0_2_all.carry_v0_1"
P5_ASSEMBLY = "gegenprobe.schema.v0_2_all.p5_affair"
LEVEL = {"canton": "cantonal", "city": "communal", "municipality": "communal", "country": "federal"}
# the samples: one Bern record (German, P3), one French and one Italian record with per-question Q/A pairs (P5)
SAMPLES = (("p3", "BE", 39369), ("p5", "VS", 295461), ("p5", "GR", 288671))

V02_ACTOR_ROLES = ("sole_author", "joint_author", "supporter", "spokesperson", "group")
V02_DATE_ROLES = ("signed", "lodged", "received", "announced", "later_step")


def _not_extracted(route: str, what: str, by: str) -> dict:
    return dict(kind="null", null_reason="not_extracted", route=route, evidence=f"{what} is not extracted by {by}")


def carry_v0_1(affair: dict) -> dict:
    """A converter product record (v0.1, after affair_post.finalize, `answering_body` possibly left out) as a v0.2 record."""
    rec = copy.deepcopy(affair)
    conv = rec["extraction"]["converter_version"]
    rec["schema_version"] = "0.2.0"
    rec["extraction"]["schema_version"] = "0.2.0"
    note = (f"carried to schema v0.2 by {CARRY}: qa[].answering_body is typed not_extracted (this converter version "
            "does not extract it)")
    rec["extraction"]["notes"] = f"{rec['extraction']['notes']}; {note}" if rec["extraction"].get("notes") else note
    for d in rec.get("documents") or []:
        d["language_tag"] = d.get("language")
    for q in rec.get("qa") or []:
        if "answering_body" not in q:
            q["answering_body"] = _not_extracted("rule", "the answering body", f"converter {conv}")
    return rec


def _census(name: str, key: str, ids: set[str] | None = None) -> dict[str, dict]:
    out = {}
    with gzip.open(CENSUS / name, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if ids is None or r[key] in ids:
                out[r[key]] = r
    return out


# OPD's harmonised type names as the census export carries them (affairs.tsv.gz column type_h) -> schema AffairType key
OPD_TYPE_NAMES = {"Motion": "motion", "Postulate": "postulate", "Interpellation": "interpellation", "Question": "question",
                  "Question time": "question_time", "Parliamentary initiative": "parliamentary_initiative",
                  "Popular initiative": "popular_initiative", "Government affairs": "government_affair",
                  "Petition": "petition", "Consultation": "consultation", "Amendment": "amendment",
                  "Naturalisation": "naturalisation", "Report": "report", "information document": "information_document",
                  "Parliamentary approval decision": "approval_decision", "Miscellaneous": "miscellaneous"}


def _types() -> dict[str, tuple[str, int | None]]:
    """census type name -> (AffairType key, OPD harmonised id when the key has exactly one)."""
    t = {x["key"]: x for x in json.loads((ROOT / "data" / "schema" / "affair_types.json").read_text(encoding="utf-8"))}
    return {name: (key, t[key]["opd_harmonised_ids"][0] if len(t[key].get("opd_harmonised_ids") or []) == 1 else None)
            for name, key in OPD_TYPE_NAMES.items()}


def _clean(v: dict | None) -> dict | None:
    """A rules-arm value as a schema value: `value_sha256` (an evaluation field) is dropped where `quote_sha256` pins
    the same text; the role `submitter`/`co_signatory` on an actor's name value is kept (StrF role is free text)."""
    if v is None:
        return None
    v = dict(v)
    if "value_sha256" in v and v.get("quote_sha256") == v["value_sha256"]:
        del v["value_sha256"]
    return v


def p5_affair(row: dict, rec: dict, meta: dict, body: dict, types: dict, created: str, build: str) -> dict:
    """One P5 rules-arm record (+ OPD identification metadata and the linked documents) as a v0.2 affair."""
    by = "the P5 rules path (Q/A pairs, people, recommendation)"
    docs = [dict(doc_id=f"opd:{d['doc_id']}", source="opd", url=d["url"], sha256=d["sha256"], role=d["role"],
                 n_pages=d["pages"], extractor=d["extractor"], image_only=bool(d["image_only"]),
                 opd_text_status=d["opd_text_status"]) for d in row["docs"]]
    q = next((d["doc_id"] for d in docs if d["role"] == "question"), None)
    a = next((d["doc_id"] for d in docs if d["role"] == "answer"), None)
    harmonised, hid = types.get(meta["type_h"].strip(), ("unknown", None))
    items = [dict(n=it["n"], question=_clean(it["question"]), answer=_clean(it["answer"])) for it in rec["qa_items"]]
    actors = [dict(role=x["role"], kind=x["kind"], name=_clean(x["name"])) for x in rec["actors"]]
    gov = _clean(rec.get("recommendation")) or _not_extracted("rule", "the government recommendation", by)
    return dict(
        schema_version="0.2.0",
        ref=dict(body_key=row["body"], number=meta["number"] or None, opd_id=row["affair_id"]),
        body=dict(key=row["body"], name=body.get("name") or None, level=LEVEL[body["type"]]),
        type=dict(harmonised=harmonised, opd_harmonised_id=hid, source_label=meta["type_raw"] or None),
        languages=[row["lang"]] if row.get("lang") else [],
        actors=actors, dates=[],
        procedural_state=_not_extracted("metadata", "the procedural state", by),
        decision=_not_extracted("metadata", "the decision", by),
        government_recommendation=gov,
        qa=[dict(question_doc=q, answer_doc=a, link_status="attached",
                 answering_body=_not_extracted("rule", "the answering body", by),
                 answer_date=_not_extracted("rule", "the answer date", by),
                 answer_identifier=_not_extracted("rule", "the decision number", by),
                 items=items)],
        answer_link_status="attached",
        documents=docs,
        extraction=dict(converter_version=f"gegenprobe P5 rules arm ({build})", schema_version="0.2.0", created=created,
                        notes=(f"assembled as a v0.2 affair by {P5_ASSEMBLY} from results/eval6/p5__none.json "
                               "(R.records) and OPD's census export (number, body, type); no value was changed")),
    )


def converter_records() -> dict[str, list[dict]]:
    from ..affair_post import finalize

    out = {}
    for name, f in (("p3", P3), ("p3b", P3B)):
        res = json.loads(f.read_text(encoding="utf-8"))
        out[name] = [carry_v0_1(finalize(x["affair"])["affair"]) for x in res["per_affair"]]
    res = json.loads(P5.read_text(encoding="utf-8"))
    rows = {r["affair_id"]: r for r in map(json.loads, P5_AFFAIRS.read_text(encoding="utf-8").splitlines()) if r}
    ids = {str(x["affair_id"]) for x in res["per_affair"]}
    metas = _census("affairs.tsv.gz", "id", ids)
    bodies = _census("bodies.tsv.gz", "key", {x["body"] for x in res["per_affair"]})
    types = _types()
    created = "2026-10-10T21:08:35+00:00"  # results/eval6/p5__none.json carries no timestamp: its commit time (fixed)
    out["p5"] = [p5_affair(rows[x["affair_id"]], x["R"]["records"], metas[str(x["affair_id"])], bodies[x["body"]], types,
                           created, res["build"]) for x in res["per_affair"]]
    return out


def _walk(o, c: dict) -> None:
    if isinstance(o, dict):
        if o.get("kind") in ("value", "null") and "route" in o:
            c["routes"][o["route"]] += 1
            if o["kind"] == "null":
                c["null_reasons"][o["null_reason"]] += 1
            if o.get("quote_sha256"):
                c["v02_additions_used"]["quote_sha256"] += 1
        for v in o.values():
            _walk(v, c)
    elif isinstance(o, list):
        for v in o:
            _walk(v, c)


def stats(records: list[dict], m) -> dict:
    valid, invalid = [], []
    c = collections.defaultdict(collections.Counter)
    for r in records:
        try:
            v = m.validate_affair(r)
        except Exception as e:  # noqa: BLE001 - recorded; the test requires none
            invalid.append(dict(affair=f"{r['ref']['body_key']}:{r['ref'].get('opd_id')}",
                                error=f"{type(e).__name__}: {str(e)[:300]}"))
            continue
        d = v.model_dump(mode="json", exclude_none=True)
        valid.append(d)
        _walk(d, c)
        c["actor_roles"].update(x.role for x in v.actors)
        c["date_roles"].update(x.role for x in v.dates)
        c["bodies"][v.ref.body_key] += 1
        c["qa_items"]["with_items" if any(q.items for q in v.qa) else "none"] += 1
        add = c["v02_additions_used"]
        for x in v.actors:
            if x.role in V02_ACTOR_ROLES:
                add[f"actor_role:{x.role}"] += 1
        for x in v.dates:
            if x.role in V02_DATE_ROLES:
                add[f"date_role:{x.role}"] += 1
        if v.type.instrument_function is not None:
            add["instrument_function"] += 1
        if v.government_recommendation.kind == "value" and v.government_recommendation.stage:
            add["recommendation_stage"] += 1
        if any(doc.language_of_text for doc in v.documents):
            add["language_of_text"] += 1
    c["v02_additions_used"] = collections.Counter({k: n for k, n in c["v02_additions_used"].items() if n})
    return dict(n_affairs=len(records), n_valid=len(valid), n_invalid=len(invalid), invalid=invalid,
                n_parliaments=len(c["bodies"]),
                counts={k: dict(sorted(v.items())) for k, v in sorted(c.items()) if k != "bodies"}), valid


def render() -> dict[str, str]:
    m = schema_module()
    conv = converter_records()
    p8 = [json.loads(x) for x in (OUT / "p8_records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    p8_val = json.loads((OUT / "p8_validation.json").read_text(encoding="utf-8"))
    files, sets, valid_by = {}, {}, {}
    for name, recs in conv.items():
        st, valid = stats(recs, m)
        sets[name] = st
        valid_by[name] = valid
        files[f"{name}_records.jsonl"] = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in valid)
    bodies = {k: {r["ref"]["body_key"] for r in v} for k, v in valid_by.items()}
    st, _ = stats(p8, m)
    bodies["p8"] = {r["ref"]["body_key"] for r in p8}
    sets["p8"] = dict(st, n_affairs=p8_val["n_affairs"], n_valid=st["n_valid"],
                      n_invalid=p8_val["n_affairs"] - st["n_valid"])
    conv_n = sum(sets[k]["n_affairs"] for k in conv)
    conv_valid = sum(sets[k]["n_valid"] for k in conv)
    used = {k: set(v["counts"].get("v02_additions_used", {})) for k, v in sets.items()}
    outside_p8 = set().union(*(used[k] for k in conv))
    all_add = ([f"actor_role:{r}" for r in V02_ACTOR_ROLES] + [f"date_role:{r}" for r in V02_DATE_ROLES]
               + ["instrument_function", "recommendation_stage", "language_of_text", "quote_sha256"])
    samples = []
    for set_name, body, opd_id in SAMPLES:
        rec = next(r for r in valid_by[set_name] if r["ref"]["body_key"] == body and r["ref"]["opd_id"] == opd_id)
        fn = f"{set_name}_{body}_{rec['ref']['opd_id']}.json"
        files[f"samples/{fn}"] = json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        samples.append(f"results/schema/v0_2/samples/{fn}")
    val = dict(
        schema_version=m.SCHEMA_VERSION,
        command="PYTHONPATH=src:. python -m gegenprobe.schema.v0_2_all",
        sources=dict(p3=P3.relative_to(ROOT).as_posix(), p3b=P3B.relative_to(ROOT).as_posix(),
                     p5=f"{P5.relative_to(ROOT).as_posix()} (R.records) + data/census/affairs.tsv.gz, bodies.tsv.gz + "
                        f"{P5_AFFAIRS.relative_to(ROOT).as_posix()}",
                     p8="results/schema/v0_2/p8_records.jsonl (gegenprobe.schema.p8_v0_2, P8 gold labels)"),
        record_makers=dict(p3=f"converter (rules_only product record) + affair_post.finalize + {CARRY}",
                           p3b=f"converter (rules_only product record) + affair_post.finalize + {CARRY}",
                           p5=f"converter P5 rules arm + {P5_ASSEMBLY}", p8="P8 gold labels (route annotator)"),
        n_affairs=sum(s["n_affairs"] for s in sets.values()),
        n_valid=sum(s["n_valid"] for s in sets.values()),
        n_invalid=sum(s["n_invalid"] for s in sets.values()),
        n_parliaments=len({b for r in bodies.values() for b in r}),
        converter_made=dict(n_affairs=conv_n, n_valid=conv_valid, sets=sorted(conv),
                            n_parliaments=len({b for k in conv for b in bodies[k]})),
        product_records=dict(n_affairs=sets["p3"]["n_affairs"] + sets["p3b"]["n_affairs"],
                             n_valid=sets["p3"]["n_valid"] + sets["p3b"]["n_valid"], sets=["p3", "p3b"]),
        sets=sets,
        v02_additions=dict(all=all_add, used_in_converter_records=sorted(outside_p8 & set(all_add)),
                           used_only_in_p8=sorted((used["p8"] - outside_p8) & set(all_add)),
                           used_nowhere=sorted(set(all_add) - outside_p8 - used["p8"])),
        samples=samples,
    )
    files["validation_all.json"] = json.dumps(val, ensure_ascii=False, indent=1) + "\n"
    return files


def _diff(files: dict[str, str]) -> list[str]:
    return [n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != t]


def step(ctx: dict) -> dict:
    """`make run` step schema_v02: P8 (gegenprobe.schema.p8_v0_2) and the converter records re-derived and compared with
    results/schema/v0_2/ (FAIL on a diff or an invalid record)."""
    from . import p8_v0_2

    p8 = p8_v0_2.step(ctx)
    files = render()
    bad = _diff(files)
    val = json.loads(files["validation_all.json"])
    s = val["sets"]
    ok = p8["status"] == "PASS" and not bad and val["n_invalid"] == 0
    summary = (f"schema v0.2: {val['n_valid']}/{val['n_affairs']} affairs valid (converter records: P3 "
               f"{s['p3']['n_valid']}/{s['p3']['n_affairs']}, P3b {s['p3b']['n_valid']}/{s['p3b']['n_affairs']}, P5 "
               f"{s['p5']['n_valid']}/{s['p5']['n_affairs']}; P8 gold {s['p8']['n_valid']}/{s['p8']['n_affairs']}); "
               + p8["summary"].split("; ", 1)[0].split(", ", 1)[-1]
               + (f"; differs: {', '.join(bad)}" if bad else "")
               + ("" if p8["status"] == "PASS" else f"; P8: {p8['summary']}"))
    return dict(status="PASS" if ok else "FAIL", summary=summary)


def main(argv: list[str]) -> int:
    files = render()
    if "--check" in argv:
        bad = _diff(files)
        print("schema v0.2 (all sets):", "differs: " + ", ".join(bad) if bad else "committed files current")
        return 1 if bad else 0
    (OUT / "samples").mkdir(parents=True, exist_ok=True)
    for n, s in files.items():
        (OUT / n).write_text(s, encoding="utf-8")
        print(OUT / n)
    v = json.loads(files["validation_all.json"])
    print(f"{v['n_valid']}/{v['n_affairs']} valid; converter-made {v['converter_made']['n_valid']}/"
          f"{v['converter_made']['n_affairs']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
