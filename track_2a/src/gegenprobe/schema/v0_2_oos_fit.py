"""Out-of-sample role fit (EXPLORATORY, post hoc, no model, no network): do schema v0.2's named roles hold the gold
values of tests labelled after v0.2's role vocabularies were fixed?

    python -m gegenprobe.schema.v0_2_oos_fit            -> results/schema/v0_2/oos_role_fit.json
    python -m gegenprobe.schema.v0_2_oos_fit --check    recompute and compare (exit 1 if different)

Why: gegenprobe.schema.v0_2_role_coverage (302/302) checks v0.2's roles against P8's own gold, from whose categories the
roles were written, so it can only fail through categories P8 never saw. This module asks the same exhaustiveness
question on the gold of three later tests, beyond authorship:
  * P10 (eval/prereg10, LOCK10): authors only (GUIDE_P10.md labels `people`); no date, language or instrument.
  * P11 IT (eval/p11, LOCKP11): 12 Italian interventions; people, instrument (function, instrument_named), the languages
    of both documents and the answer date with its role (GUIDE_P11_IT.md). No submission date.
  * Federal cell (eval/fed, LOCKFED): 15 federal interventions; the same keys as P11 IT (GUIDE_FED.md). No submission
    date.
  * P11 NI (LOCKP11): 15 government-business and parliamentary-initiative affairs, outside the verdict's scope
    (interventions); each of the 17 fields judged `fits` (an existing role, named), `new_role` (a printed value no
    existing role describes), `not_printed`, `not_applicable` or `cannot_tell` (GUIDE_P11_NI.md). The only gold that
    labels a submission-date role.

Order in time (VOCAB, LOCKS below): v0.2's role vocabularies (DateRole, InstrumentFunction, InstrumentNamed, ActorRole,
Lang) were committed in 836185d1 at 2026-10-11T12:35:37+02:00 and have not changed since (the later commit 36275f95
adds empty-list reasons only); LOCKFED, LOCK10 and LOCKP11 were written after it, and each test's gold after its lock.
So no value counted here was seen when the roles were written. The vocabularies the annotators chose from are P8's
(the guides reuse GUIDE_P8 sections 2, 5, 6 and P1/P2's answer-date roles), each with an escape (`other`, `unclear`,
`none`, or NI's `new_role`): "named" means the annotator found a named value and v0.2 has a named slot for it.

Per field: determinable = a printed value whose gold is not undeterminable / unclear / cannot_tell; named = its gold
value maps to a named v0.2 value (asserted against schema/gegenprobe_schema_v0_2.py's Literal types; v0.2's
catch-all `other` counts as unnamed); unnamed lists the categories that do not. Per test and per parliament. Post hoc:
defined after these tests' results, descriptive, no threshold.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import sys
from typing import get_args

from ..paths import ROOT
from .p8_v0_2 import DATE_ROLE as P8_DATE_ROLE
from .p8_v0_2 import schema_module
from .v0_2_role_coverage import MAP as P8_MAP

OUT = ROOT / "results" / "schema" / "v0_2" / "oos_role_fit.json"
GOLD = dict(p10=ROOT / "data" / "p10" / "p10_gold.jsonl", p11_it=ROOT / "data" / "p11" / "p11_it_gold.jsonl",
            fed=ROOT / "data" / "fed" / "fed_gold.jsonl", p11_ni=ROOT / "data" / "p11" / "p11_ni_gold.jsonl")
GUIDES = dict(p10="eval/p10/GUIDE_P10.md", p11_it="eval/p11/GUIDE_P11_IT.md", fed="eval/fed/GUIDE_FED.md",
              p11_ni="eval/p11/GUIDE_P11_NI.md")
LOCKS = dict(p10="eval/prereg10/LOCK10", p11_it="eval/p11/LOCKP11", fed="eval/fed/LOCKFED", p11_ni="eval/p11/LOCKP11")
# the commit that fixed v0.2's role vocabularies (git log -- schema/gegenprobe_schema_v0_2.py; unchanged since)
VOCAB = dict(commit="836185d1", committed="2026-10-11T12:35:37+02:00", file="schema/gegenprobe_schema_v0_2.py")
INTERVENTIONS = ("p11_it", "fed")  # the verdict's scope; p11_ni is outside it, p10 labels authors only

# gold value -> v0.2 (type, value); None = no named v0.2 value (v0.2 `other`, or a role v0.2 lacks)
SUBMISSION_ROLE = {r: (("DateRole", v) if v != "other" else None) for r, v in P8_DATE_ROLE.items()
                   if r in ("signed", "lodged", "session_lodged", "cited")}
ANSWER_ROLE = {"decision": ("DateRole", "answer_decided"), "dispatch": ("DateRole", "answer_dispatched")}
UNDETERMINABLE = ("undeterminable", "unclear", "cannot_tell")


def _t(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def _vocab() -> dict[str, set[str]]:
    m = schema_module()
    return dict(DateRole=set(get_args(m.DateRole)), InstrumentFunction=set(get_args(m.InstrumentFunction)),
                InstrumentNamed=set(get_args(m.InstrumentNamed)), ActorRole=set(get_args(m.ActorRole)),
                Lang=set(get_args(m.Lang)), AffairType=set(get_args(m._v01.AffairType)),
                ActorKind=set(get_args(m._v01.ActorKind)), RecommendationStage=set(get_args(m.RecommendationStage)))


def _rows(name: str) -> list[dict]:
    return [json.loads(x) for x in GOLD[name].read_text(encoding="utf-8").splitlines() if x.strip()]


class Tally:
    """Per field: values by parliament, each `named`, `unnamed:<category>`, `undeterminable` or `not_printed`."""

    def __init__(self):
        self.per = collections.defaultdict(collections.Counter)
        self.cats = collections.Counter()

    def add(self, body: str, cat: str, mapped, status: str | None = None):
        st = status or ("named" if mapped is not None else "unnamed")
        self.per[body][st] += 1
        self.cats[(st, cat)] += 1

    def out(self) -> dict:
        def block(c):
            n = c["named"] + c["unnamed"]
            return dict(determinable=n, named=c["named"], unnamed=c["unnamed"], undeterminable=c["undeterminable"],
                        not_printed=c["not_printed"], share_named=round(c["named"] / n, 3) if n else None)
        tot = collections.Counter()
        for c in self.per.values():
            tot.update(c)
        return dict(**block(tot),
                    categories={st: {cat: n for (s, cat), n in sorted(self.cats.items()) if s == st}
                                for st in ("named", "unnamed", "undeterminable", "not_printed")
                                if any(s == st for s, _ in self.cats)},
                    parliaments=len([b for b, c in self.per.items() if c["named"] + c["unnamed"]]),
                    parliaments_all_named=sum(1 for c in self.per.values() if c["named"] + c["unnamed"]
                                              and c["unnamed"] == 0),
                    per_parliament={b: block(c) for b, c in sorted(self.per.items())})


def _check(vocab: dict, mapped) -> None:
    if mapped is not None:
        typ, val = mapped
        assert val in vocab[typ], (typ, val)


def compute() -> dict:
    vocab = _vocab()
    for m in list(SUBMISSION_ROLE.values()) + list(ANSWER_ROLE.values()):
        _check(vocab, m)
    named_fn = vocab["InstrumentFunction"] - {"other"}
    named_in = vocab["InstrumentNamed"] - {"other"}
    named_actor = vocab["ActorRole"] - {"other"}
    fields: dict[str, dict] = {}
    labelled = collections.defaultdict(dict)

    def tally(field: str, test: str) -> Tally:
        return labelled[field].setdefault(test, Tally())

    # ---- P11 IT and the federal cell (the same packet keys)
    for test in INTERVENTIONS:
        for g in _rows(test):
            body = g.get("body") or "CHE"
            f = g["fields"]
            # answer date role (P1/P2 roles decision / dispatch)
            ad = f["answer_date"]
            if ad["category"] in (None, "null"):
                tally("answer_date_role", test).add(body, "not printed", None, "not_printed")
            else:
                m = ANSWER_ROLE.get(ad["role"])
                tally("answer_date_role", test).add(body, str(ad["role"]), m)
            # instrument: function and the name the documents give it
            sec = f["type"]["secondary"]
            fn = sec["function"]
            if fn in UNDETERMINABLE:
                tally("instrument_function", test).add(body, fn, None, "undeterminable")
            else:
                tally("instrument_function", test).add(body, fn, ("InstrumentFunction", fn) if fn in named_fn else None)
            nm = sec["instrument_named"]
            if nm == "none":
                tally("instrument_named", test).add(body, "none", None, "not_printed")
            else:
                tally("instrument_named", test).add(body, nm, ("InstrumentNamed", nm) if nm in named_in else None)
            # type category against OPD's type (P8's derivation; mapping of v0_2_role_coverage)
            tc = f["type"]["category"]
            if tc in UNDETERMINABLE or not f["type"]["applicable"]:
                tally("type_category", test).add(body, tc, None, "undeterminable")
            else:
                tally("type_category", test).add(body, tc, P8_MAP["type"][tc])
            # languages: the language of each document's text, and the tag-vs-text category (P8's derivation)
            for _role, langs in sorted((g["parts"]["language"].get("languages") or {}).items()):
                for lg in langs or []:
                    tally("text_language", test).add(body, lg, ("Lang", lg) if lg in vocab["Lang"] else None)
            lc = f["language"]
            if lc["category"] in UNDETERMINABLE or not lc["applicable"]:
                tally("language_tag_vs_text", test).add(body, lc["category"], None, "undeterminable")
            else:
                tally("language_tag_vs_text", test).add(body, lc["category"], P8_MAP["language"][lc["category"]])
            # authorship (for reference: extends P10's 0/197)
            ppl = (g["parts"].get("people") or g["parts"].get("submitter") or {}).get("people") or []
            if not ppl:
                tally("author_role", test).add(body, "no person printed", None, "not_printed")
            for p in ppl:
                tally("author_role", test).add(body, p["role"], ("ActorRole", p["role"]) if p["role"] in named_actor
                                               else None)
    # ---- P10: authors only
    for g in _rows("p10"):
        for p in g["people"]:
            tally("author_role", "p10").add(g["body"], p["role"], ("ActorRole", p["role"]) if p["role"] in named_actor
                                            else None)
    # ---- P11 NI: field verdicts
    for g in _rows("p11_ni"):
        body = g["body"]
        for field, key, mapper in (
                ("submission_date_role", "date_submission", lambda r: SUBMISSION_ROLE.get(r)),
                ("answer_date_role", "date_answer", lambda r: ANSWER_ROLE.get(r)),
                ("instrument_function", "type", lambda r: ("InstrumentFunction", r) if r in named_fn else None),
                ("text_language", "language", lambda r: ("Document", "language_of_text") if r == "text_language" else None),
                ("author_role", "submitter", lambda r: ("ActorRole", r) if r in named_actor else None),
                ("co_signatory_role", "co_signatories", lambda r: ("ActorRole", r) if r in named_actor else None)):
            v = g["fields"][key]
            t = tally(field, "p11_ni")
            if v["verdict"] == "fits":
                t.add(body, v["role"], mapper(v["role"]))
            elif v["verdict"] == "new_role":
                t.add(body, "new_role: " + "; ".join(sorted(set(v["new_role_labels"]))), None)
            elif v["verdict"] == "cannot_tell":
                t.add(body, "cannot_tell", None, "undeterminable")
            else:
                t.add(body, v["verdict"], None, "not_printed")

    not_labelled = {
        "submission_date_role": {"p10": "GUIDE_P10 labels people only", "p11_it": "GUIDE_P11_IT: P8 section 3 (dates) "
                                 "not asked", "fed": "GUIDE_FED: P8 section 3 (dates) not asked"},
        "answer_date_role": {"p10": "GUIDE_P10 labels people only"},
        "instrument_function": {"p10": "GUIDE_P10 labels people only"},
        "instrument_named": {"p10": "GUIDE_P10 labels people only", "p11_ni": "GUIDE_P11_NI judges the function only"},
        "type_category": {"p10": "GUIDE_P10 labels people only", "p11_ni": "not derived for NI"},
        "text_language": {"p10": "GUIDE_P10 labels people only"},
        "language_tag_vs_text": {"p10": "GUIDE_P10 labels people only", "p11_ni": "GUIDE_P11_NI: role text_language "
                                 "only, no tag comparison"},
        "author_role": {},
        "co_signatory_role": {"p10": "counted under author_role (one people list)", "p11_it": "counted under "
                              "author_role (one people list)", "fed": "counted under author_role (one people list)"},
    }
    unit = {"text_language": "document languages (IT, fed); affairs (NI)", "author_role": "persons (P10, IT, fed); "
            "affairs (NI)", "co_signatory_role": "affairs"}
    for field, tests in labelled.items():
        per_test = {t: tally_.out() for t, tally_ in sorted(tests.items())}
        iv = [per_test[t] for t in INTERVENTIONS if t in per_test]
        fields[field] = dict(unit=unit.get(field, "affairs"), tests=per_test,
                             not_labelled=not_labelled.get(field, {}),
                             interventions=dict(determinable=sum(x["determinable"] for x in iv),
                                                named=sum(x["named"] for x in iv),
                                                unnamed=sum(x["unnamed"] for x in iv)))
    beyond = ("submission_date_role", "answer_date_role", "instrument_function", "instrument_named", "text_language")

    def total(field_names, tests):
        k = n = 0
        un = collections.Counter()
        for f in field_names:
            for t in tests:
                x = fields[f]["tests"].get(t)
                if x:
                    k += x["named"]
                    n += x["determinable"]
                    for cat, c in (x["categories"].get("unnamed") or {}).items():
                        un[f"{f}: {cat}"] += c
        return dict(named=k, determinable=n, unnamed=dict(sorted(un.items())))

    locks = {}
    for t, p in LOCKS.items():
        written = json.loads((ROOT / p).read_text(encoding="utf-8"))["written"]
        locks[t] = dict(lock=p, written=written, after_vocabulary=_t(written) > _t(VOCAB["committed"]))
    summary = dict(
        beyond_authorship_interventions=total(beyond, INTERVENTIONS),
        beyond_authorship_interventions_without_text_language=total(beyond[:-1], INTERVENTIONS),
        beyond_authorship_non_interventions=total(beyond, ("p11_ni",)),
        interventions=dict(n_affairs=sum(len(_rows(t)) for t in INTERVENTIONS),
                           n_parliaments=len({g.get("body") or "CHE" for t in INTERVENTIONS for g in _rows(t)})),
        authorship=total(("author_role",), ("p10", "p11_it", "fed")),
        authorship_non_interventions=total(("author_role", "co_signatory_role"), ("p11_ni",)),
        submission_date_role=dict(
            labelled_by=["p11_ni"], interventions="not labelled by any out-of-sample test (P10, P11 IT, fed)",
            p11_ni=dict(named=fields["submission_date_role"]["tests"]["p11_ni"]["named"],
                        determinable=fields["submission_date_role"]["tests"]["p11_ni"]["determinable"],
                        unnamed=fields["submission_date_role"]["tests"]["p11_ni"]["categories"].get("unnamed", {}))),
        circular_check=dict(file="results/p8/p8_v02_role_coverage.json", note=(
            "302/302 on P8's own gold (v0.2's roles written from P8's categories); this file is the out-of-sample "
            "counterpart")),
    )
    return dict(
        label=("EXPLORATORY, POST HOC (not pre-registered): v0.2 role fit on gold labelled after v0.2's role "
               "vocabularies were fixed; descriptive, no threshold (gegenprobe/schema/v0_2_oos_fit.py)"),
        command="PYTHONPATH=src:. python -m gegenprobe.schema.v0_2_oos_fit",
        vocabulary=dict(VOCAB, locks=locks),
        gold={t: dict(file=p.relative_to(ROOT).as_posix(), guide=GUIDES[t], n_affairs=len(_rows(t)),
                      n_parliaments=len({g.get("body") or "CHE" for g in _rows(t)}),
                      scope="interventions" if t != "p11_ni" else "government business and parliamentary initiatives")
              for t, p in GOLD.items()},
        definition=("determinable = a printed gold value that is not undeterminable / unclear / cannot_tell; named = "
                    "the value maps to a named v0.2 value (asserted against the schema's Literal types; v0.2 `other` "
                    "is unnamed); NI: `fits` maps through the role, `new_role` is unnamed, not_printed and "
                    "not_applicable are not determinable"),
        mappings=dict(submission_date_role={k: (None if v is None else v[1]) for k, v in SUBMISSION_ROLE.items()},
                      answer_date_role={k: v[1] for k, v in ANSWER_ROLE.items()},
                      type_category={k: (None if v is None else list(v[1])) for k, v in P8_MAP["type"].items()},
                      language_tag_vs_text={k: (None if v is None else v[0]) for k, v in P8_MAP["language"].items()}),
        summary=summary, fields=dict(sorted(fields.items())))


def main(argv: list[str]) -> int:
    res = compute()
    blob = json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == blob
        print(OUT.name, "matches" if same else "DIFFERS from a recompute")
        return 0 if same else 1
    OUT.write_text(blob, encoding="utf-8")
    s = res["summary"]
    b, ni = s["beyond_authorship_interventions"], s["beyond_authorship_non_interventions"]
    print(f"{OUT.relative_to(ROOT)}: beyond authorship, interventions {b['named']}/{b['determinable']} named; "
          f"non-interventions (P11 NI) {ni['named']}/{ni['determinable']} named, unnamed {ni['unnamed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
