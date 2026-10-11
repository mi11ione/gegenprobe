"""P8 scoring (eval/prereg9/PREREG9.md §6): per field and parliament, the meaning categories of the carried values, the
share in the shared-meaning set E with a Wilson 95% interval, whether the parliament is evaluable and conforms, the pooled
share with a parliament-cluster bootstrap interval, and the secondary OPD-vs-documents agreement. Model-free.

    PYTHONPATH=src:. python -m eval.p8.score        data/p8/p8_gold.jsonl -> results/p8/p8_tables.json
"""

from __future__ import annotations

import collections
import json
import random


from eval.p8 import common as C
from eval.p8 import derive as Dv
from gegenprobe.stats import wilson

STRATUM = {q[0]: dict(level=q[1], stratum=q[2]) for q in C.QUOTAS}


def per_parliament(items: list[tuple[str, dict]], field: str, E: set[str] | None = None) -> dict[str, dict]:
    """items: (body, derived result) for one field. E defaults to the registered set."""
    E = C.E[field] if E is None else E
    by = collections.defaultdict(list)
    for b, r in items:
        by[b].append(r)
    out = {}
    for b in sorted(by, key=lambda x: C.BODIES.index(x) if x in C.BODIES else 99):
        rs = by[b]
        app = [r for r in rs if r["applicable"]]
        det = [r for r in app if r["category"] != C.UNDET]
        cats = collections.Counter(r["category"] for r in det)
        nE = sum(v for k, v in cats.items() if k in E)
        non = len(det) - nE
        unnamed = sum(v for k, v in cats.items() if k not in E and k in C.UNNAMED[field])
        ev = len(det) >= C.K
        conforms = ev and non <= C.max_exceptions(len(det))
        lo, hi = wilson(nE, len(det))
        out[b] = dict(**STRATUM.get(b, {}), n=len(rs), n_applicable=len(app), n_det=len(det),
                      not_applicable=collections.Counter(r["reason"] for r in rs if not r["applicable"]),
                      undeterminable=collections.Counter(r["reason"] for r in app if r["category"] == C.UNDET),
                      counts=dict(cats), n_E=nE, share_E=round(nE / len(det), 3) if det else None,
                      wilson=[round(lo, 3), round(hi, 3)] if det else None, n_nonE=non,
                      max_exceptions=C.max_exceptions(len(det)) if det else None, evaluable=ev, conforms=conforms,
                      deviates=ev and not conforms, nonE_unnamed=unnamed, nonE_named=non - unnamed,
                      layers=dict(collections.Counter(r["layer"] for r in app if r["layer"])))
    return out


def pooled(pp: dict[str, dict], evaluable_only: bool = True) -> dict:
    bs = [b for b, v in pp.items() if (v["evaluable"] if evaluable_only else v["n_det"] > 0)]
    nE, n = sum(pp[b]["n_E"] for b in bs), sum(pp[b]["n_det"] for b in bs)
    if not n:
        return dict(parliaments=len(bs), n=0, n_E=0, share=None, cluster_ci=None, wilson=None)
    rnd = random.Random(C.SEED_BOOT)
    boot = []
    for _ in range(C.N_BOOT):
        s = [rnd.choice(bs) for _ in bs]
        d = sum(pp[b]["n_det"] for b in s)
        boot.append(sum(pp[b]["n_E"] for b in s) / d)
    boot.sort()
    lo, hi = wilson(nE, n)
    return dict(parliaments=len(bs), n=n, n_E=nE, share=round(nE / n, 3),
                cluster_ci=[round(boot[int(0.025 * C.N_BOOT)], 3), round(boot[int(0.975 * C.N_BOOT) - 1], 3)],
                wilson=[round(lo, 3), round(hi, 3)])


def secondary(field: str, items: list[tuple[str, dict]]) -> dict:
    """OPD's value vs what the documents print (agreement; never part of a decision)."""
    app = [(b, r) for b, r in items if r["applicable"]]
    s = [r["secondary"] for _, r in app]
    by_layer = dict(collections.Counter(r["layer"] for _, r in app))
    if field == "submitter":
        both = [x for x in s if x.get("opd_is_author_of_record") is not None]
        return dict(by_layer=by_layer, opd_has_submitter=sum(x.get("opd_name") is not None for x in s),
                    opd_is_printed_author_of_record=sum(bool(x.get("opd_is_author_of_record")) for x in both), of=len(both),
                    opd_submitter_not_printed=sum(r["reason"] == "OPD's submitter is not printed" for _, r in app))
    if field == "co_signatories":
        js = [x["jaccard"] for x in s if x.get("jaccard") is not None]
        return dict(by_layer=by_layer, opd_lists=sum((x.get("opd_n") or 0) > 0 for x in s),
                    printed_lists=sum((x.get("printed_n") or 0) > 0 for x in s),
                    mean_jaccard_surnames=round(sum(js) / len(js), 3) if js else None,
                    identical_surname_sets=sum(j == 1.0 for j in js), of=len(js))
    if field == "date_submission":
        off = [x["offset_days"] for x in s if x.get("offset_days") is not None]
        byb = collections.defaultdict(list)
        for b, r in app:
            if r["secondary"].get("offset_days") is not None:
                byb[b].append(r["secondary"]["offset_days"])
        return dict(by_layer=by_layer, with_printed_lodging_date=len(off), equal=sum(o == 0 for o in off),
                    within_1_day=sum(abs(o) <= 1 for o in off), offsets=Dv.median_iqr(off),
                    equal_by_parliament={b: [sum(o == 0 for o in v), len(v)] for b, v in byb.items()})
    if field == "addressed_body":
        dept = [r["category"] for _, r in app if r["secondary"].get("opd_department")]
        return dict(by_layer=by_layer, opd_names_a_department=len(dept),
                    printed_addressee_where_opd_names_a_department=dict(collections.Counter(dept)))
    if field == "language":
        return dict(by_layer=by_layer, answer_document=dict(collections.Counter(str(x.get("answer_doc_category")) for x in s)),
                    member_text_tags=dict(collections.Counter(str(x.get("question_tag")) for x in s)))
    if field == "government_recommendation":
        both = [x for x in s if x.get("opd_value") and x.get("printed_value") not in (None, "not_applicable")]
        return dict(by_layer=by_layer, opd_has_value=sum(bool(x.get("opd_value")) for x in s),
                    opd_equals_printed=sum(x.get("opd_value") == x.get("printed_value") for x in both), of=len(both),
                    fits=dict(collections.Counter(str(x.get("fits")) for x in s)))
    if field == "type":
        named = [x for x in s if x.get("name_agrees") is not None]
        fn = collections.defaultdict(collections.Counter)
        for x in s:
            fn[str(x.get("opd_type"))][str(x.get("function"))] += 1
        return dict(by_layer=by_layer, printed_name_equals_opd_type=sum(bool(x.get("name_agrees")) for x in named), of=len(named),
                    function_by_opd_type={k: dict(v) for k, v in fn.items()})
    return {}


def items_of(gold: list[dict], field: str, agreed_only: bool = False) -> list[tuple[str, dict]]:
    """(parliament, derived result) per affair; agreed_only keeps the affairs whose field A1 and A2 labelled alike."""
    return [(g["body"], g["fields"][field]) for g in gold
            if not agreed_only or g["fields"][field].get("source", "A1=A2") == "A1=A2"]


def tables(gold: list[dict], agreed_only: bool = False) -> dict:
    out = {}
    for f in C.FIELDS:
        it = items_of(gold, f, agreed_only)
        pp = per_parliament(it, f)
        out[f] = dict(E=sorted(C.E[f]), by_parliament=pp, pooled=pooled(pp), pooled_all_determinable=pooled(pp, False),
                      categories=dict(collections.Counter(r["category"] for _, r in it if r["applicable"])),
                      secondary={} if agreed_only else secondary(f, it))
    return out


def main(gold_path=C.GOLD, out=C.R8 / "p8_tables.json") -> dict:
    gold = C._jsonl(gold_path)
    if not gold:
        raise SystemExit(f"{gold_path} missing: merge the labels first")
    t = dict(n_affairs=len(gold), n_parliaments=len({g["body"] for g in gold}), X=C.X, K=C.K,
             min_parliaments=C.MIN_PARLIAMENTS, fields=tables(gold), fields_agreed_only=tables(gold, True))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(t, indent=1, ensure_ascii=False) + "\n")
    return t


if __name__ == "__main__":
    r = main()
    print(json.dumps({f: dict(pooled=v["pooled"], categories=v["categories"]) for f, v in r["fields"].items()}, indent=1))
