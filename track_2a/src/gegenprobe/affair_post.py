"""Product post-processing of whole-affair records (schema v0.1 `Affair`, as affair.build.run_affair assembles them).

affair/build.py and affair/extract.py are frozen by the P3/P3b pre-registrations (eval/prereg3/LOCK3, eval/prereg5/LOCK5),
and the scored results files keep their output unchanged. What OPD would load runs through this module instead; it only
corrects what the frozen assembly states wrongly or cannot know, and says so:

  1. qa[].answering_body  build.py writes a typed null `present_unanchored` ("candidate values present but none is
     anchored") with evidence "not extracted in P3". Nobody looked, so that reason is false. Schema v0.1's null reasons
     (data/schema/null_reasons.json) have none for "not attempted", and the field is required, so the field is LEFT OUT of
     the product record and listed in `omitted` with that note. (The record is then not v0.1-valid as a whole; `validate`
     checks everything else. Schema v0.2 has the reason `not_extracted`; gegenprobe.schema.v0_2_all.carry_v0_1 carries
     the record to v0.2 with it, and all 65 P3/P3b records validate.)
  2. decision  for an interpellation, a written question or question time (types on which parliament takes no decision;
     the same three types make the recommendation not_applicable, convert/affair_types.py), a metadata null
     `not_in_corpus` ("no record holding the value exists") becomes `not_applicable`, route metadata, with the type as
     evidence. A decision value OPD does record is kept.
  3. qa[].answer_date (P3b Luzern case)  when a rule read the answer date from the document and that date equals the
     affair's submission date while OPD's answer event has another date, the rule most likely read the date of the
     member's motion printed on the answer (Luzern "Antrag … vom <submission date>"). OPD's answer date is kept in the
     field (basis/route metadata, with its OPD record), the rule's value goes to `review` with the reason, and the record
     needs review. Never applied in the evaluation path (eval/gold3, eval/gold5 score the frozen output).

usage: python -m gegenprobe.affair_post <results file with per_affair[]> [--out FILE.jsonl]
       one product row per affair: {"affair_id", "affair", "needs_review", "review", "omitted", "changes"}
       python -m gegenprobe.affair_post --measure   -> results/eval5/affair_post_check.json (post hoc, on P3 and P3b)
"""
from __future__ import annotations

import argparse
import copy
import json
import sys

NO_DECISION_TYPES = ("interpellation", "question", "question_time")
NOT_EXTRACTED = "not extracted in P3"
OMITTED_NOTE = ("not extracted by this converter version. Schema v0.1 has no null reason for a field nobody looked at, so "
                "the field is left out instead of carrying the false reason 'present_unanchored' (candidates present, "
                "none anchored)")
RULE_ROUTES = ("rule", "ocr+rule")


def _date(rec: dict, role: str) -> dict | None:
    for d in rec.get("dates") or []:
        if d.get("role") == role and (d.get("date") or {}).get("kind") == "value":
            return d["date"]
    return None


def finalize(affair: dict) -> dict:
    """-> {affair, needs_review, review: [{field, reason, rule_value}], omitted: [{field, note}], changes: [...]}"""
    rec = copy.deepcopy(affair)
    review, omitted, changes = [], [], []
    for i, qa in enumerate(rec.get("qa") or []):
        ab = qa.get("answering_body") or {}
        if ab.get("kind") == "null" and ab.get("evidence") == NOT_EXTRACTED:
            del qa["answering_body"]
            omitted.append(dict(field=f"qa.{i}.answering_body", note=OMITTED_NOTE))
            changes.append(dict(field=f"qa.{i}.answering_body", was="null present_unanchored (not extracted in P3)",
                                now="omitted"))
        ad, sub, opd = qa.get("answer_date") or {}, _date(rec, "submitted"), _date(rec, "answered")
        if (ad.get("kind") == "value" and ad.get("route") in RULE_ROUTES and sub and opd
                and ad.get("value") == sub.get("value") and opd.get("value") != ad.get("value")):
            qa["answer_date"] = {k: v for k, v in opd.items()}
            review.append(dict(
                field=f"qa.{i}.answer_date",
                reason=(f"the rule {ad.get('rule')} read {ad.get('value')} on p. {ad.get('page')} ({ad.get('quote')!r}), which "
                        f"is the affair's submission date; OPD's answer event says {opd.get('value')} ({opd.get('source')}). "
                        "OPD's date is kept: check the document"),
                rule_value=ad))
            changes.append(dict(field=f"qa.{i}.answer_date", was=f"{ad.get('value')} (rule {ad.get('rule')})",
                                now=f"{opd.get('value')} (OPD answer event)"))
    t = (rec.get("type") or {}).get("harmonised")
    dec = rec.get("decision") or {}
    if t in NO_DECISION_TYPES and dec.get("kind") == "null" and dec.get("null_reason") == "not_in_corpus":
        rec["decision"] = dict(kind="null", null_reason="not_applicable", route="metadata",
                               evidence=f"affair type {t} ({(rec.get('type') or {}).get('source_label')}): parliament takes "
                                        "no decision on it")
        changes.append(dict(field="decision", was="null not_in_corpus", now="null not_applicable"))
    return dict(affair=rec, needs_review=bool(review), review=review, omitted=omitted, changes=changes)


def validate(post: dict) -> None:
    """Validate the product record against schema v0.1, with the omitted fields put back as the frozen placeholder (so
    everything that is present is checked). Raises pydantic.ValidationError."""
    from .schema import schema_v0_1 as S

    rec = copy.deepcopy(post["affair"])
    for o in post["omitted"]:
        _, i, name = o["field"].split(".")
        rec["qa"][int(i)][name] = dict(kind="null", null_reason="present_unanchored", route="rule", evidence=NOT_EXTRACTED)
    S.Affair.model_validate(rec)


CHECKS = (  # (results file, labels) of the two whole-affair tests; labels are the blind annotators' (eval/gold3, gold5)
    ("results/eval3/p3__publicai_swiss-ai_apertus-v1.5-8b.json", "data/gold3/p3_labels.jsonl", "P3"),
    ("results/eval5/p3b__publicai_swiss-ai_apertus-v1.5-8b.json", "data/gold5/p3b_labels.jsonl", "P3b"),
)


def measure() -> dict:
    """POST-HOC: what the post-processing changes on the committed P3 / P3b records, and whether each answer-date change
    agrees with the gold label (the scored results are untouched). -> results/eval5/affair_post_check.json"""
    from .paths import RESULTS, ROOT

    out = dict(label="POST-HOC (not pre-registered): round-5 product post-processing (gegenprobe.affair_post) applied to "
                     "the committed P3 and P3b records; the scored results files are not changed", tests={})
    for rf, lf, name in CHECKS:
        res = json.loads((ROOT / rf).read_text())
        gold = {g["affair_id"]: g for g in map(json.loads, open(ROOT / lf, encoding="utf-8"))}
        t = dict(results=rf, labels=lf, affairs=0, answering_body_omitted=0, decision_not_applicable=0,
                 answer_date_guard=[], valid=0)
        for x in res["per_affair"]:
            p = finalize(x["affair"])
            validate(p)
            t["affairs"] += 1
            t["valid"] += 1
            for c in p["changes"]:
                t["answering_body_omitted"] += c["field"].endswith("answering_body")
                t["decision_not_applicable"] += c["field"] == "decision"
            for r in p["review"]:
                g = gold.get(x["affair_id"], {}).get("answer_date")
                kept = p["affair"]["qa"][int(r["field"].split(".")[1])]["answer_date"]["value"]
                t["answer_date_guard"].append(dict(affair_id=x["affair_id"], body=x["affair"]["ref"]["body_key"],
                                                   rule_value=r["rule_value"]["value"], kept=kept, gold=g, kept_correct=kept == g,
                                                   rule_correct=r["rule_value"]["value"] == g))
        t["guard_fired"] = len(t["answer_date_guard"])
        t["guard_kept_correct"] = sum(r["kept_correct"] for r in t["answer_date_guard"])
        out["tests"][name] = t
    (RESULTS / "eval5" / "affair_post_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--measure"]:
        r = measure()
        print(json.dumps({k: {kk: vv for kk, vv in v.items() if not isinstance(vv, list)} for k, v in r["tests"].items()}))
        return 0
    ap = argparse.ArgumentParser(prog="python -m gegenprobe.affair_post", description=__doc__.split("\n\n")[0])
    ap.add_argument("results", help="a results file with per_affair[] (results/eval3/p3__*.json, results/eval5/p3b__*.json)")
    ap.add_argument("--out", help="write one JSON row per affair here (default: stdout)")
    a = ap.parse_args(argv)
    res = json.loads(open(a.results, encoding="utf-8").read())
    sink = open(a.out, "w", encoding="utf-8") if a.out else sys.stdout
    n = flagged = 0
    try:
        for x in res["per_affair"]:
            p = finalize(x["affair"])
            validate(p)
            sink.write(json.dumps(dict(affair_id=x["affair_id"], **p), ensure_ascii=False) + "\n")
            n += 1
            flagged += p["needs_review"]
    finally:
        if a.out:
            sink.close()
    print(f"{n} affairs, {flagged} need review", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
