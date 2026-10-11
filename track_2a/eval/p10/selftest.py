"""P10 self-test on synthetic inputs only (no network, no model, no P10 affair): the scoring, the hypothesis machinery,
the role composition, the baselines, the candidate generator and the packet format. `eval/prereg10/lock10.py write`
refuses to write LOCK10 unless this passes.

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.selftest
"""

from __future__ import annotations

import sys

from eval.p10 import arms as A
from eval.p10 import packets as PK
from eval.p10 import score as S
from gegenprobe.convert import role_candidates as RC
from gegenprobe.convert import roles_pointer as RP


def _row(body, gold, **arms):
    return dict(id=body, body=body, stratum="de", cell="primary",
                arms={k: S.affair_row(v, gold) for k, v in arms.items()})


def checks() -> list[str]:
    bad: list[str] = []

    def ok(cond, msg):
        if not cond:
            bad.append(msg)

    # matching: same person by token subset, role must match, one-to-one
    gold = [("Anna Muster", "first_signatory"), ("Beat Beispiel", "co_signatory")]
    ok(S.match([("Muster", "first_signatory")], gold)[0] == 1, "surname-only print matches")
    ok(S.match([("Anna Muster", "joint_author")], gold)[0] == 0, "role must match")
    ok(S.match([("Anna Muster", "joint_author")], gold, with_role=False)[0] == 1, "names without role")
    ok(S.match([("Anna Muster", "first_signatory")] * 2, gold)[0] == 1, "one-to-one")
    r = S.affair_row([("Anna Muster", "first_signatory"), ("X Y", "co_signatory")], gold)
    ok((r["m_role"], r["n_pred"], r["n_gold"], r["exact"]) == (1, 2, 2, False), "affair row")
    # pooled metrics and an abstaining arm
    rows = [_row("B1", gold, pointer=gold, rules=[], opd_first=gold[:1], opd_joint=[],
                 cand_joint=[(n, "joint_author") for n, _ in gold]),
            _row("B2", [("C D", "sole_author")], pointer=[("C D", "sole_author")], rules=[("C D", "sole_author")],
                 opd_first=[], opd_joint=[("C D", "sole_author")], cand_joint=[("C D", "sole_author")])]
    p = S.pooled(rows, "rules")
    ok(p["recall"] == 1 / 3 and p["precision"] == 1.0, "pooled recall/precision; abstention costs no precision")
    ok(S.pooled(rows, "pointer")["f1"] == 1.0, "perfect arm F1 = 1")
    # Holm
    h = S.holm({"H1": 0.01, "H2": 0.015, "H3a": 0.04, "H3b": 0.2})
    ok(h["H1"]["rejected"] and h["H2"]["rejected"] and not h["H3a"]["rejected"], "Holm step-down")
    ok(abs(h["H3a"]["p_holm"] - 0.08) < 1e-9, "Holm adjusted p")
    # bootstrap determinism and the stop rule
    hy1 = S.hypotheses(rows * 20, seed=1, n_boot=200)
    hy2 = S.hypotheses(rows * 20, seed=1, n_boot=200)
    ok(hy1 == hy2, "bootstrap is deterministic under a seed")
    ok(S.hypotheses(rows, seed=1, n_boot=50)["underpowered"], "stop rule: too few affairs -> underpowered")
    ok(S.mcnemar_exact(5, 0) == 1 / 32, "exact McNemar")
    ok(abs(S.stat(rows, "H2") - 0.0) < 1e-12, "H2 statistic: precision difference")
    f_first, f_joint = S.pooled(rows, "opd_first")["f1"], S.pooled(rows, "opd_joint")["f1"]
    ok(abs(S.stat(rows, "H3a") - (1.0 - max(f_first, f_joint))) < 1e-12, "H3a: against the stronger OPD reading")
    # composition of roles (staged)
    def d(v, kind, pa, pf):
        return dict(value=v, kind=kind, p_author=pa, p_first=pf, coherence=[])
    c = RP.compose([d("A", "person", .99, .1), d("B", "person", .99, .1)], .5, .5)
    ok([x["role"] for x in c] == ["joint_author", "joint_author"], "several persons, nobody set apart -> joint")
    c = RP.compose([d("A", "person", .99, .9), d("B", "person", .99, .1), d("Z", "person", .1, .9)], .5, .5)
    ok([x["role"] for x in c] == ["first_signatory", "co_signatory", "not_an_author"], "first + co; non-author out")
    c = RP.compose([d("SP-Fraktion", "parliamentary_group", .99, None), d("A", "person", .99, .1)], .5, .5)
    ok([x["role"] for x in c] == ["sole_author", "spokesperson"], "group author + spokesperson")
    c = RP.compose([d("A", "person", .99, .99)], .5, .5, cue=False)
    ok(c[0]["role"] == "sole_author", "a lone person without a co-signing cue is sole author")
    c = RP.compose([d("A", "person", .99, .99)], .5, .5, cue=True)
    ok(c[0]["role"] == "first_signatory", "a lone person with 'et consorts' is first signatory")
    ok(abs(RP.p_author(dict(p_author_pos=.9, p_author_neg=.3)) - 0.8) < 1e-12, "two polarities averaged")
    # baselines
    meta = dict(contributors=[dict(type="person", firstname="Anna", lastname="Muster", role_harmonized="author",
                                   person_id=1),
                              dict(type="person", firstname="Beat", lastname="Beispiel", role_harmonized="cosign",
                                   person_id=2)])
    ok(A.opd_pairs(meta) == [("Anna Muster", "first_signatory"), ("Beat Beispiel", "co_signatory")], "OPD mapping")
    meta2 = dict(contributors=[dict(meta["contributors"][0]), dict(meta["contributors"][1], role_harmonized="author")])
    ok(A.opd_pairs(meta2, "joint") == [("Anna Muster", "joint_author"), ("Beat Beispiel", "joint_author")], "OPD joint")
    ok(A.opd_pairs(None) == [], "OPD without metadata abstains")
    ok(A.cand_joint_pairs([dict(value="A")]) == [("A", "sole_author")], "one candidate -> sole")
    # candidates: rules, roster cue, group phrase, located spans
    q = ["Interpellation von Anna Muster und Beat Beispiel betreffend Velowege\n\nText der Interpellation. Frau "
         "Clara Dritt hat das schon 2019 gefordert.\n\nFür die SP-Fraktion\n"]
    a = ["Antwort des Regierungsrates auf die Interpellation von Anna Muster\n"]
    cd = RC.candidates(q, a, [("Anna", "Muster"), ("Beat", "Beispiel"), ("Clara", "Dritt")])
    vals = [x["value"] for x in cd["candidates"]]
    ok("Anna Muster" in vals and "Beat Beispiel" in vals and "Clara Dritt" in vals, f"candidates found: {vals}")
    ok(any("Fraktion" in v for v in vals), f"group phrase found: {vals}")
    for x in cd["candidates"]:
        page = (q if x["doc"] == "question" else a)[x["page"] - 1]
        ok(" ".join(page[x["char_start"]:x["char_end"]].split()) == x["value"], f"span locates {x['value']!r}")
    # quotas from a probe: PER_BODY each, the rest of the target to the largest pool; the secondary cell apart
    from eval.p10 import common as C
    pr = dict(frame={"de": ["A", "B"], "fr": ["X", "Y"], "it": []},
              per_body={"A": dict(robots_allowed=50, lang="de"), "B": dict(robots_allowed=9, lang="de"),
                        "X": dict(robots_allowed=35, lang="fr"), "Y": dict(robots_allowed=4, lang="fr"),
                        "5192": dict(robots_allowed=400, lang="it")})
    qs = {b: (n, cell) for b, _, n, cell in C.quotas(pr)}
    ok(qs["X"] == (C.TARGET["fr"] - C.PER_BODY, "primary") and qs["Y"] == (C.PER_BODY, "primary"), f"FR quotas {qs}")
    ok(qs["A"][0] == C.TARGET["de"] - C.PER_BODY and qs["5192"] == (C.SECONDARY_N, "secondary_it"), f"quotas {qs}")
    # packets round-trip
    pages = {"question": ["page one\nline", "page two"], "answer": ["answer"]}
    ok(PK.packet_pages("P10-000", PK.render("P10-000", pages)) == pages, "packet pages round-trip")
    return bad


if __name__ == "__main__":
    b = checks()
    print("P10 selftest:", "PASS" if not b else "FAIL\n- " + "\n- ".join(b))
    sys.exit(1 if b else 0)
