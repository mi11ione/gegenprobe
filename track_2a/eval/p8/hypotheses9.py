"""P8 registered decisions (eval/prereg9/PREREG9.md §7), applied by code to results/p8/p8_tables.json. Model-free.

    PYTHONPATH=src:. python -m eval.p8.hypotheses9      -> results/p8/p8_hypotheses.json

Per field f with shared-meaning set E_f (common.E), per parliament p with n determinable affairs:
  evaluable   n >= K (3)
  conforms    evaluable and at most max(1, floor(0.10 n)) affairs fall outside E_f
  deviates    evaluable and not conforms
A deviating parliament is
  unnamed     more than half of its affairs outside E_f fall in an unnamed category (common.UNNAMED[f]: other / unexplained)
  systematic  otherwise, if one named category outside E_f holds at least 2 of its affairs (a role it uses the field for)
  scattered   otherwise (no named category repeats: the deviation could be labelling noise)
Verdict:
  shared                at least MIN_PARLIAMENTS (6) evaluable parliaments, none deviates, and the pooled share in E_f
                        over the evaluable parliaments is >= X (0.90)
  body_specific         some deviating parliament is `unnamed`
  role_split            no deviating parliament is `unnamed` and at least one is `systematic`; the roles to keep apart
                        are its repeated named categories
  shared_other_meaning  replaces body_specific, role_split or an unsystematic result when one category c outside E_f passes
                        the `shared` test on its own (every evaluable parliament conforms to {c}, >= MIN_PARLIAMENTS of
                        them, pooled >= X): the field is shared, but not in the meaning v0.1 gives it
  inconclusive          no parliament deviates but fewer than MIN_PARLIAMENTS are evaluable or the pooled share is < X;
                        or every deviating parliament is `scattered`
"""

from __future__ import annotations

import collections
import json

from eval.p8 import common as C
from eval.p8 import score as S

CONSEQUENCE = {
    "shared": "field_verdict_classes.json: meaning_tested = 'measured (P8): shared'; stays in class shared",
    "role_split": "moves to class shared_with_role_split; the roles to keep apart are the categories named in the "
                  "deviating parliaments",
    "body_specific": "moves to class body_specific for the deviating parliaments' meaning; the schema needs the body's "
                     "own vocabulary there",
    "shared_other_meaning": "stays shared, with its definition rewritten to the category every parliament shares",
    "inconclusive": "stays 'by definition, untested', with the P8 reason (too few evaluable parliaments, pooled share "
                    "below X, or only scattered deviations)",
}


def verdict(field: str, pp: dict[str, dict], pool: dict) -> dict:
    ev = [b for b, v in pp.items() if v["evaluable"]]
    dev = [b for b in ev if pp[b]["deviates"]]
    out = dict(evaluable=ev, n_evaluable=len(ev), deviating=dev, pooled_share_E=pool["share"])
    if dev:
        kinds, roles = {}, {}
        for b in dev:
            nonE = {k: n for k, n in pp[b]["counts"].items() if k not in C.E[field]}
            rep = sorted(k for k, n in nonE.items() if k not in C.UNNAMED[field] and n >= 2)
            kinds[b] = ("unnamed" if pp[b]["nonE_unnamed"] * 2 > pp[b]["n_nonE"] else "systematic" if rep else "scattered")
            roles[b] = dict(outside_E=nonE, repeated_roles=rep)
        if "unnamed" in kinds.values():
            v = "body_specific"
        elif "systematic" in kinds.values():
            v = "role_split"
        else:
            v = "inconclusive"
            out["reason"] = "every deviating parliament is scattered (no named category outside E repeats)"
        out.update(deviation_kind=kinds, roles_in_deviating=roles)
        # the same test for the most frequent category outside E (pooled over the evaluable parliaments)
        tot = collections.Counter()
        for b in ev:
            tot.update({k: n for k, n in pp[b]["counts"].items() if k not in C.E[field]})
        if tot:
            c = max(sorted(tot), key=lambda k: tot[k])
            alt_pp = S.per_parliament([(b, dict(applicable=True, category=k, layer=None, reason=None))
                                       for b in pp for k, n in pp[b]["counts"].items() for _ in range(n)], field, {c})
            alt_ev = [b for b, x in alt_pp.items() if x["evaluable"]]
            alt_pool = S.pooled(alt_pp)
            alt_ok = (len(alt_ev) >= C.MIN_PARLIAMENTS and not any(alt_pp[b]["deviates"] for b in alt_ev)
                      and alt_pool["share"] is not None and alt_pool["share"] >= C.X)
            out["other_meaning_test"] = dict(category=c, evaluable=len(alt_ev), pooled=alt_pool["share"], passes=alt_ok)
            if alt_ok:
                v = "shared_other_meaning"
                out["shared_as"] = c
                out.pop("reason", None)
    elif len(ev) >= C.MIN_PARLIAMENTS and pool["share"] is not None and pool["share"] >= C.X:
        v = "shared"
    else:
        v = "inconclusive"
        out["reason"] = (f"{len(ev)} evaluable parliaments (< {C.MIN_PARLIAMENTS})" if len(ev) < C.MIN_PARLIAMENTS
                         else f"pooled share {pool['share']} < {C.X}")
    out["verdict"] = v
    out["consequence"] = CONSEQUENCE[v]
    return out


def main(tables_path=C.R8 / "p8_tables.json", out_path=C.R8 / "p8_hypotheses.json") -> dict:
    t = json.loads(tables_path.read_text())
    res = {}
    for f in C.FIELDS:
        ft = t["fields"][f]
        res[f] = verdict(f, ft["by_parliament"], ft["pooled"])
        res[f]["pooled"] = ft["pooled"]
        fa = t["fields_agreed_only"][f]  # sensitivity (reported, never decisive): affairs A1 and A2 labelled alike
        res[f]["verdict_agreed_only"] = verdict(f, fa["by_parliament"], fa["pooled"])["verdict"]
        res[f]["per_parliament"] = {b: dict(n_det=v["n_det"], n_E=v["n_E"], share_E=v["share_E"], wilson=v["wilson"],
                                            evaluable=v["evaluable"], conforms=v["conforms"], counts=v["counts"])
                                    for b, v in ft["by_parliament"].items()}
    summary = collections.Counter(r["verdict"] for r in res.values())
    out = dict(prereg="eval/prereg9/PREREG9.md", X=C.X, K=C.K, min_parliaments=C.MIN_PARLIAMENTS,
               n_affairs=t["n_affairs"], n_parliaments=t["n_parliaments"], fields=res, summary=dict(summary),
               meaning_tested=sum(r["verdict"] != "inconclusive" for r in res.values()))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    r = main()
    print(json.dumps({f: dict(verdict=v["verdict"], evaluable=v["n_evaluable"], deviating=v["deviating"],
                              pooled=v["pooled_share_E"]) for f, v in r["fields"].items()}, indent=1))
    print(r["summary"], "meaning tested for", r["meaning_tested"], "of", len(C.FIELDS), "fields")
