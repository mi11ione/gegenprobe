"""Out-of-sample role fit on the DRAFT schema v0.2.1 (POST HOC, proposed in review; EXPLORATORY, no model, no network).

    python -m gegenprobe.schema.v0_2_1_oos_fit           -> results/schema/v0_2_1/{oos_role_fit.json, affair.schema.json}
    python -m gegenprobe.schema.v0_2_1_oos_fit --check   recompute and compare (exit 1 if different)

v0.2.0 (schema/gegenprobe_schema_v0_2.py) is frozen in LOCKP11 and LOCKFED and has no `cited` date role, although the
registered meaning test P8 counts `cited` submission dates inside the shared meaning (eval/prereg9/PREREG9.md). The draft
schema/gegenprobe_schema_v0_2_1.py adds `cited` and nothing else. This module re-runs gegenprobe.schema.v0_2_oos_fit's
computation unchanged, with two substitutions only: the vocabularies are read from v0.2.1, and the gold role `cited`
maps to v0.2.1's `cited` (in v0.2.0 it maps to no named value). It reports the v0.2.0 result next to it, and what
changed. Post hoc: v0.2.1 was written after these gold labels were seen (the `cited` labels are the reason for it), so
the v0.2.1 fit is not out of sample for the `cited` role; it measures the consistency fix, not a new test.
"""
from __future__ import annotations

import importlib
import json
import sys
from typing import get_args
from unittest import mock

from ..paths import ROOT
from . import v0_2_oos_fit as V

OUT_DIR = ROOT / "results" / "schema" / "v0_2_1"
OUT = OUT_DIR / "oos_role_fit.json"
OUT_SCHEMA = OUT_DIR / "affair.schema.json"
LABEL = ("POST HOC (12 Oct 2026; proposed in review; not pre-registered): v0.2's out-of-sample role fit re-run on the "
         "draft schema v0.2.1 (v0.2.0 plus the date role `cited`); `cited` was added after these labels were seen, so "
         "this is a consistency check with P8's definition, not an out-of-sample test of it")


def schema_module():
    """schema/gegenprobe_schema_v0_2_1.py, imported the way an integrator does (the schema/ directory on sys.path)."""
    d = str(ROOT / "schema")
    if d not in sys.path:
        sys.path.insert(0, d)
    return importlib.import_module("gegenprobe_schema_v0_2_1")


def _vocab_v021() -> dict[str, set[str]]:
    """V._vocab's vocabularies, read from v0.2.1 (which changes DateRole only)."""
    m = schema_module()
    voc = dict(DateRole=set(get_args(m.DateRole)), InstrumentFunction=set(get_args(m.InstrumentFunction)),
               InstrumentNamed=set(get_args(m.InstrumentNamed)), ActorRole=set(get_args(m.ActorRole)),
               Lang=set(get_args(m.Lang)), AffairType=set(get_args(m._v01.AffairType)),
               ActorKind=set(get_args(m._v01.ActorKind)), RecommendationStage=set(get_args(m.RecommendationStage)))
    assert voc["DateRole"] - set(get_args(m._v02.DateRole)) == set(m.NEW_DATE_ROLES)
    return voc


def compute() -> dict:
    base = V.compute()
    sub = dict(V.SUBMISSION_ROLE, cited=("DateRole", "cited"))
    with mock.patch.object(V, "SUBMISSION_ROLE", sub), mock.patch.object(V, "_vocab", _vocab_v021):
        new = V.compute()
    m = schema_module()

    def pick(r: dict) -> dict:
        s = r["summary"]
        return dict(beyond_authorship_interventions=s["beyond_authorship_interventions"],
                    beyond_authorship_non_interventions=s["beyond_authorship_non_interventions"],
                    submission_date_role_p11_ni=s["submission_date_role"]["p11_ni"])

    b, n = pick(base), pick(new)
    bn, nn = b["beyond_authorship_non_interventions"], n["beyond_authorship_non_interventions"]
    return dict(
        label=LABEL, command="PYTHONPATH=src:. python -m gegenprobe.schema.v0_2_1_oos_fit",
        schema=dict(file="schema/gegenprobe_schema_v0_2_1.py", version=m.SCHEMA_VERSION, extends=m.V02_VERSION,
                    added_date_roles=list(m.NEW_DATE_ROLES),
                    v0_2_0_locked_in=["eval/p11/LOCKP11", "eval/fed/LOCKFED"]),
        v0_2_0=b, v0_2_1=n,
        changed=dict(
            non_interventions=f"{bn['named']}/{bn['determinable']} -> {nn['named']}/{nn['determinable']}",
            submission_date_role_p11_ni=(f"{b['submission_date_role_p11_ni']['named']}/"
                                         f"{b['submission_date_role_p11_ni']['determinable']} -> "
                                         f"{n['submission_date_role_p11_ni']['named']}/"
                                         f"{n['submission_date_role_p11_ni']['determinable']}"),
            interventions_unchanged=b["beyond_authorship_interventions"] == n["beyond_authorship_interventions"],
            remaining_unnamed=nn["unnamed"]),
        mappings=dict(submission_date_role={k: (None if v is None else v[1]) for k, v in sub.items()}),
        fit_v0_2_1=new)


def outputs() -> dict[str, str]:
    m = schema_module()
    return {"oos_role_fit.json": json.dumps(compute(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            "affair.schema.json": json.dumps(m.json_schema("affair"), ensure_ascii=False, indent=1) + "\n"}


def main(argv: list[str]) -> int:
    outs = outputs()
    if "--check" in argv:
        bad = [k for k, v in outs.items() if not (OUT_DIR / k).exists() or (OUT_DIR / k).read_text(encoding="utf-8") != v]
        print("v0_2_1 outputs", "match" if not bad else f"DIFFER: {bad}")
        return 1 if bad else 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for k, v in outs.items():
        (OUT_DIR / k).write_text(v, encoding="utf-8")
    print(json.dumps(json.loads(outs["oos_role_fit.json"])["changed"], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
