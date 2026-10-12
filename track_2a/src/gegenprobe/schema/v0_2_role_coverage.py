"""Remedy test on committed P8 gold (post hoc, no model, no network): do schema v0.2's named roles cover the values?

P8 (eval/prereg9) asked whether each v0.1 field means one thing everywhere; 6 fields came out role splits. The remedy the
project proposes is schema v0.2: every value carries the role it plays. This module asks the exhaustiveness question
on the same 66 gold affairs from 11 parliaments: for each P8 role-split field and parliament, the share of determinable
affairs whose gold category is one that a *named* v0.2 role or slot represents, against `other` and the categories
v0.2 cannot carry. It generalises the authors-only check (P10 gold: `other` 0/197).

    python -m gegenprobe.schema.v0_2_role_coverage            -> results/p8/p8_v02_role_coverage.json
    python -m gegenprobe.schema.v0_2_role_coverage --check    recompute and compare (exit 1 if different)

Inputs, all committed: data/p8/p8_gold.jsonl (gold categories, the registered P8 derivation), results/p8/p8_hypotheses.json
(which fields are role splits), schema/gegenprobe_schema_v0_2.py (the role vocabularies, read from the schema itself)
and results/schema/v0_2/p8_records.jsonl (whether the committed v0.2 records of these affairs carry the slot).

Two levels per field: `vocabulary` (the v0.2 schema has a named value for the category: every mapping below is asserted
against the schema's Literal types) and `records` (the committed P8 v0.2 records write that slot). Determinable = the
field is applicable and the gold category is not `undeterminable` (P8's denominators). Post hoc: defined after P8's
results, descriptive, no threshold.
"""
from __future__ import annotations

import collections
import json
import sys
from typing import get_args

from ..paths import ROOT
from .p8_v0_2 import schema_module

GOLD = ROOT / "data" / "p8" / "p8_gold.jsonl"
HYP = ROOT / "results" / "p8" / "p8_hypotheses.json"
RECORDS = ROOT / "results" / "schema" / "v0_2" / "p8_records.jsonl"
OUT = ROOT / "results" / "p8" / "p8_v02_role_coverage.json"

# P8 category -> the v0.2 vocabulary that names it: (schema type, values) or None (no named v0.2 role: `other`, or a
# value v0.2 cannot carry). "Document.language" means the pair language_tag (Lang | unspecified) and language_of_text.
MAP: dict[str, dict[str, tuple[str, tuple[str, ...]] | None]] = {
    "submitter": {
        "author_person": ("ActorRole", ("sole_author", "first_signatory")),
        "joint_person": ("ActorRole", ("joint_author",)),
        "cosigner_person": ("ActorRole", ("co_signatory", "supporter")),
        "group": ("ActorKind", ("parliamentary_group",)),
        "committee_or_body": ("ActorKind", ("committee",)),
        "other": None,
    },
    "co_signatories": {
        "cosigners": ("ActorRole", ("co_signatory",)),
        "supporters": ("ActorRole", ("supporter",)),
        "cosigners_and_supporters": ("ActorRole", ("co_signatory", "supporter")),
        "joint_authors": ("ActorRole", ("joint_author",)),
        "includes_author_of_record": ("ActorRole", ("sole_author", "first_signatory", "co_signatory")),
        "signing_for_group": ("ActorRole", ("spokesperson",)),
        "other": None,
    },
    "addressed_body": {
        "executive": ("ActorKind", ("executive",)),
        "executive_member_or_department": ("ActorKind", ("person", "administration")),
        "parliament": ("ActorKind", ("parliament",)),
        "committee": ("ActorKind", ("committee",)),
        "administration": ("ActorKind", ("administration",)),
        "other": None,
    },
    "language": {
        "text_language": ("Lang", ()),
        "subset_of_text": ("Lang", ()),
        "superset_of_text": ("Lang", ()),
        "other_language": ("Lang", ()),
        "invalid_tag": None,  # language_tag accepts a language code or 'unspecified' only
    },
    "government_recommendation": {
        "on_referral": ("RecommendationStage", ("on_adoption",)),
        "on_fulfilment": ("RecommendationStage", ("on_fulfilment",)),
        "other": None,
    },
    "type": {
        "conforms": ("AffairType", ("motion", "postulate", "interpellation", "question")),
        "mandate": ("InstrumentFunction", ("mandate",)),
        "examine_report": ("InstrumentFunction", ("examine_report",)),
        "questions": ("InstrumentFunction", ("questions",)),
        "direct_decision": ("InstrumentFunction", ("direct_decision",)),
        "other": None,  # instrument_function 'other'
    },
    # the body-specific field, for completeness: v0.2 carries OPD's date (role submitted, metadata) next to the printed
    # lodging dates, so `unprinted_differs` is representable; `cited` and `other_printed` land in DateRole 'other'
    "date_submission": {
        "lodged": ("DateRole", ("signed", "lodged", "announced")),
        "cited": None,
        "later_step": ("DateRole", ("later_step",)),
        "answer_or_decision": ("DateRole", ("answered",)),
        "other_printed": None,
        "unprinted_differs": ("DateRole", ("submitted", "signed", "lodged")),
    },
}
# the slot of the committed P8 v0.2 record that would carry the field's role
SLOT = {
    "submitter": "actors (role, kind)",
    "co_signatories": "actors (role)",
    "addressed_body": "actors with role addressed_body",
    "language": "documents[].language_tag and language_of_text",
    "government_recommendation": "government_recommendation.stage",
    "type": "type.harmonised and type.instrument_function",
    "date_submission": "dates[] (role)",
}


def _vocab() -> dict[str, set[str]]:
    m = schema_module()
    v01 = m._v01
    return dict(ActorRole=set(get_args(m.ActorRole)), ActorKind=set(get_args(v01.ActorKind)),
                DateRole=set(get_args(m.DateRole)), InstrumentFunction=set(get_args(m.InstrumentFunction)),
                RecommendationStage=set(get_args(m.RecommendationStage)), AffairType=set(get_args(v01.AffairType)),
                Lang=set(get_args(m.Lang)))


def _records_carry(recs: list[dict]) -> dict[str, int]:
    """Per field: how many of the committed P8 v0.2 records write the slot."""
    return dict(
        submitter=sum(bool(r["actors"]) for r in recs),
        co_signatories=sum(any(a["role"] in ("co_signatory", "supporter", "joint_author", "spokesperson")
                               for a in r["actors"]) for r in recs),
        addressed_body=sum(any(a["role"] == "addressed_body" for a in r["actors"]) for r in recs),
        language=sum(any(d.get("language_tag") is not None and d.get("language_of_text") for d in r["documents"])
                     for r in recs),
        government_recommendation=sum(r["government_recommendation"].get("stage") is not None for r in recs),
        type=sum(r["type"].get("instrument_function") is not None for r in recs),
        date_submission=sum(bool(r["dates"]) for r in recs),
    )


def compute() -> dict:
    vocab = _vocab()
    for f, cats in MAP.items():  # every named mapping exists in the schema
        for c, m in cats.items():
            if m is not None:
                typ, vals = m
                assert set(vals) <= vocab[typ], (f, c, typ, set(vals) - vocab[typ])
    gold = [json.loads(x) for x in GOLD.read_text(encoding="utf-8").splitlines() if x.strip()]
    hyp = json.loads(HYP.read_text(encoding="utf-8"))
    recs = [json.loads(x) for x in RECORDS.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(recs) == len(gold) == hyp["n_affairs"]
    carry = _records_carry(recs)
    verdict = {f: v["verdict"] for f, v in hyp["fields"].items()}
    out = {}
    for f in MAP:
        per = collections.defaultdict(collections.Counter)
        cats = collections.Counter()
        for g in gold:
            y = g["fields"][f]
            if not y["applicable"] or y["category"] == "undeterminable":
                continue
            c = y["category"]
            assert c in MAP[f], (f, c)
            cats[c] += 1
            per[g["body"]]["n"] += 1
            per[g["body"]]["named" if MAP[f][c] is not None else "unnamed"] += 1
            per[g["body"]][f"cat:{c}"] += 1
        pp = {b: dict(n=c["n"], named=c["named"], share_named=round(c["named"] / c["n"], 3),
                      categories={k[4:]: v for k, v in sorted(c.items()) if k.startswith("cat:")})
              for b, c in sorted(per.items())}
        n, k = sum(c["n"] for c in per.values()), sum(c["named"] for c in per.values())
        out[f] = dict(
            p8_verdict=verdict[f],
            slot=SLOT[f],
            mapping={c: (None if m is None else dict(type=m[0], values=list(m[1]))) for c, m in MAP[f].items()},
            categories=dict(sorted(cats.items())),
            determinable=n, named=k, share_named=round(k / n, 3) if n else None,
            unnamed_categories=sorted(c for c in cats if MAP[f][c] is None),
            parliaments=len(pp), parliaments_all_named=sum(v["named"] == v["n"] for v in pp.values()),
            records_carry_slot=carry[f], per_parliament=pp)
    rs = [f for f, v in verdict.items() if v == "role_split"]
    other_actors = [dict(body=r["ref"]["body_key"], number=r["ref"]["number"],
                         n=sum(a["role"] == "other" for a in r["actors"]))
                    for r in recs if any(a["role"] == "other" for a in r["actors"])]
    summary = dict(
        role_split_fields=rs,
        determinable=sum(out[f]["determinable"] for f in rs),
        named=sum(out[f]["named"] for f in rs),
        fields_fully_named=sum(out[f]["named"] == out[f]["determinable"] for f in rs),
        cells=sum(out[f]["parliaments"] for f in rs),
        cells_fully_named=sum(out[f]["parliaments_all_named"] for f in rs),
        fields_whose_records_do_not_write_the_slot=[f for f in rs if out[f]["records_carry_slot"] == 0],
        actors_with_role_other=dict(n=sum(x["n"] for x in other_actors), affairs=other_actors,
                                    of_actors=sum(len(r["actors"]) for r in recs)),
        body_specific_field=dict(field="date_submission", determinable=out["date_submission"]["determinable"],
                                 named=out["date_submission"]["named"],
                                 unnamed=dict((c, out["date_submission"]["categories"][c])
                                              for c in out["date_submission"]["unnamed_categories"])),
    )
    return dict(
        label=("POST HOC (not pre-registered): v0.2 role coverage of P8's gold values; descriptive, no threshold "
               "(gegenprobe/schema/v0_2_role_coverage.py)"),
        n_affairs=len(gold), n_parliaments=len({g["body"] for g in gold}),
        definition=("per field and parliament: determinable affairs (applicable, gold category not undeterminable) whose "
                    "gold category is named by a v0.2 role or slot (vocabulary asserted against "
                    "schema/gegenprobe_schema_v0_2.py), vs `other` or a value v0.2 cannot carry"),
        summary=summary, fields=out)


def main(argv: list[str]) -> int:
    res = compute()
    blob = json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == blob
        print(OUT.name, "matches" if same else "DIFFERS from a recompute")
        return 0 if same else 1
    OUT.write_text(blob, encoding="utf-8")
    s = res["summary"]
    print(f"{OUT.relative_to(ROOT)}: role-split fields {s['named']}/{s['determinable']} determinable values named; "
          f"{s['cells_fully_named']}/{s['cells']} field x parliament cells fully named; slot not written by the P8 "
          f"records: {s['fields_whose_records_do_not_write_the_slot']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
