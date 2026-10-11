"""P8 self-test on synthetic labels (no document, no network, no model): the derivation rules, the per-parliament table and
every registered verdict path, run before LOCK9 so the frozen code is known to work.

    PYTHONPATH=src:. python -m eval.p8.selftest       (exit 0 = all checks pass; writes only to a temporary directory)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from eval.p8 import common as C
from eval.p8 import derive as Dv
from eval.p8 import hypotheses9 as H
from eval.p8 import score as S


def _meta(authors=(), submitted=None, dept=False):
    cons = [dict(id=i + 1, person_id=i + 1, type="person", fullname=f"{first} {last}", firstname=first, lastname=last,
                 role_harmonized="author", position=i + 1) for i, (first, last) in enumerate(authors)]
    if dept:
        cons.append(dict(id=99, type="group", fullname="Bildungsdirektion", role_harmonized="leading_department",
                         position=99))
    evs = ([dict(id=1, date=f"{submitted}T00:00:00", title_de="Eingereicht", title_harmonized_id=1, position=1)]
           if submitted else [])
    return dict(affair=dict(id=1, body_key="X", begin_date=None, number="1", type_harmonized_en="Motion"), events=evs,
                contributors=cons)


def _entry(t="Motion", qtag="de", atag=None):
    return dict(affair_type=t, docs=[dict(role="question", opd_lang=qtag), dict(role="answer", opd_lang=atag)])


def unit() -> list[str]:
    bad = []

    def ok(cond, what):
        if not cond:
            bad.append(what)

    ok(Dv.name_match("Andrea", "Nava", "Nava Andrea"), "name: reversed order")
    ok(Dv.name_match("Andrea", "Nava", "A. Nava"), "name: initial")
    ok(not Dv.name_match("Andrea", "Nava", "Marco Nava"), "name: other first name")
    ok(Dv.name_match("Morena", "Ferrari Gamba", "Morena Ferrari Gamba"), "name: compound surname")
    ok(Dv.name_match("Ivo", "Peyer", "Peyer"), "name: surname only")
    people = [dict(name="Peter Muster", kind="person", role="first_signatory"),
              dict(name="Anna Beispiel", kind="person", role="co_signatory"),
              dict(name="Hans Stütz", kind="person", role="supporter")]
    lab = dict(people=people)
    ok(Dv.submitter(lab, _meta([("Peter", "Muster"), ("Anna", "Beispiel")]))["category"] == "author_person", "sub: first")
    ok(Dv.submitter(lab, _meta([("Anna", "Beispiel"), ("Peter", "Muster")]))["category"] == "cosigner_person",
       "sub: OPD first is a co-signer")
    ok(Dv.submitter(lab, _meta([("Nora", "Fremd")]))["category"] == C.UNDET, "sub: not printed")
    ok(Dv.submitter(lab, None)["layer"] == "doc", "sub: doc layer")
    grp = dict(people=[dict(name="SP-Fraktion", kind="group", role="sole_author"),
                       dict(name="Lea Rot", kind="person", role="spokesperson")])
    ok(Dv.submitter(grp, _meta([("Lea", "Rot")]))["category"] == "group", "sub: spokesperson for a group")
    ok(Dv.co_signatories(lab, _meta([("Peter", "Muster"), ("Anna", "Beispiel")]))["category"] == "cosigners", "cos: E")
    ok(Dv.co_signatories(lab, _meta([("Anna", "Beispiel"), ("Peter", "Muster")]))["category"]
       == "includes_author_of_record", "cos: includes the author of record")
    ok(Dv.co_signatories(lab, _meta([("Peter", "Muster"), ("Hans", "Stütz")]))["category"] == "supporters", "cos: supporters")
    ok(Dv.co_signatories(lab, None)["category"] == "cosigners_and_supporters", "cos: doc layer mixed")
    ok(not Dv.co_signatories(dict(people=people[:1]), _meta([("Peter", "Muster")]))["applicable"], "cos: n/a")
    dl = {"D01": "2024-03-12", "D02": "2024-04-02", "D03": "2024-06-01"}
    dlab = dict(dates={"D01": ["signed"], "D02": ["later_step"], "D03": ["answer_or_decision"]}, extra_dates=[])
    ok(Dv.date_submission(dlab, _meta(submitted="2024-03-12"), dl)["category"] == "lodged", "date: lodged")
    ok(Dv.date_submission(dlab, _meta(submitted="2024-04-02"), dl)["category"] == "later_step", "date: later step")
    ok(Dv.date_submission(dlab, _meta(submitted="2024-05-05"), dl)["category"] == "unprinted_differs", "date: unprinted")
    r = Dv.date_submission(dlab, _meta(submitted="2024-04-02"), dl)
    ok(r["secondary"]["offset_days"] == 21, "date: offset")
    ok(Dv.date_submission(dict(dates={}, extra_dates=[]), _meta(submitted="2024-05-05"), dl)["category"] == C.UNDET,
       "date: undeterminable")
    ok(Dv.language_category("de", ["de"])[0] == "text_language", "lang: E")
    ok(Dv.language_category("GR", ["de"])[0] == "invalid_tag", "lang: invalid")
    ok(Dv.language_category("de;fr", ["fr"])[0] == "superset_of_text", "lang: superset")
    ok(Dv.language_category("de", ["de", "rm"])[0] == "subset_of_text", "lang: subset")
    ok(Dv.language_category(None, ["de"])[0] == C.UNDET, "lang: untagged")
    tl = dict(function=dict(value="examine_report"), instrument_named=dict(value="motion"))
    ok(Dv.type_(tl, _entry("Motion"))["category"] == "examine_report", "type: deviation")
    ok(Dv.type_(tl, _entry("Postulate"))["category"] == "conforms", "type: conforms")
    rl = dict(answer_doc="executive_answer", recommendation=dict(act="on_fulfilment", value="accept", fits="one"))
    ok(Dv.government_recommendation(rl, None, _entry("Postulate"))["category"] == "on_fulfilment", "rec: fulfilment")
    ok(not Dv.government_recommendation(rl, None, _entry("Interpellation"))["applicable"], "rec: n/a")
    ok(C.max_exceptions(6) == 1 and C.max_exceptions(10) == 1 and C.max_exceptions(20) == 2, "max_exceptions")
    return bad


def _gold(spec: dict[str, list[str]], field: str) -> list[dict]:
    """spec: body -> categories (one per affair) -> minimal gold rows for one field."""
    rows = []
    for b, cats in spec.items():
        for c in cats:
            f = {x: dict(applicable=False, layer=None, category=C.UNDET, reason="n/a", secondary={}) for x in C.FIELDS}
            f[field] = dict(applicable=True, layer="opd", category=c, reason=None, doc_category=c, opd_category=c,
                            secondary={})
            rows.append(dict(id=f"{b}-{len(rows)}", body=b, fields=f))
    return rows


def verdicts() -> list[str]:
    bad = []
    bodies = C.BODIES
    cases = [
        ("shared", "addressed_body", {b: ["executive"] * 6 for b in bodies}),
        ("shared", "addressed_body", {b: ["executive"] * 5 + ["parliament"] for b in bodies[:4]}
         | {b: ["executive"] * 6 for b in bodies[4:]}),
        ("role_split", "date_submission", {b: ["lodged"] * 6 for b in bodies[:11]} | {"GR": ["later_step"] * 4 + ["lodged"] * 2}),
        ("body_specific", "date_submission", {b: ["lodged"] * 6 for b in bodies[:11]}
         | {"GR": ["unprinted_differs"] * 3 + ["lodged"] * 3}),
        ("inconclusive", "date_submission", {b: ["lodged"] * 6 for b in bodies[:11]}
         | {"GR": ["later_step", "answer_or_decision"] + ["lodged"] * 4}),
        ("inconclusive", "language", {b: ["text_language"] * 6 for b in bodies[:5]} | {"GR": ["text_language"] * 2}),
        ("shared_other_meaning", "co_signatories", {b: ["supporters"] * 6 for b in bodies}),
        ("inconclusive", "type", {b: ["conforms"] * 5 + ["mandate"] for b in bodies}),
    ]
    with tempfile.TemporaryDirectory() as d:
        for want, field, spec in cases:
            gold = _gold(spec, field)
            gp, tp, hp = Path(d) / "g.jsonl", Path(d) / "t.json", Path(d) / "h.json"
            gp.write_text("".join(json.dumps(g) + "\n" for g in gold))
            S.main(gp, tp)
            got = H.main(tp, hp)["fields"][field]["verdict"]
            if got != want:
                bad.append(f"verdict {field}: want {want}, got {got}")
    return bad


if __name__ == "__main__":
    errs = unit() + verdicts()
    print("P8 selftest:", "all checks pass" if not errs else "FAILED\n- " + "\n- ".join(errs))
    sys.exit(1 if errs else 0)
