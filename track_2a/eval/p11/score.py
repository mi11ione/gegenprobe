"""P11 tables (eval/p11/PROTOCOL.md §7). EXPLORATORY and descriptive: counts and Wilson 95% intervals per stratum and
overall; no hypothesis test, no threshold, no verdict, no pooling with any earlier set.

    PYTHONPATH=src:. .venv/bin/python -m eval.p11.score it    -> results/p11/p11_it_tables.json
    PYTHONPATH=src:. .venv/bin/python -m eval.p11.score ni    -> results/p11/p11_ni_tables.json

IT inputs: data/p11/p11_it_gold.jsonl, results/p11/it_arms_offline.json, results/p11/it_arms_pointer.json (if the model
arms ran; their absence or a partial run is reported), results/p11/pool_probe.json (which arms are in-sample where).
NI inputs: data/p11/p11_ni_gold.jsonl, results/p11/ni_arms_offline.json.
"""

from __future__ import annotations

import collections
import json
import sys

from eval.p8 import common as C8
from eval.p10 import score as S10
from eval.p11 import common as C
from eval.score import summarise
from gegenprobe.stats import wilson

LABEL = "EXPLORATORY P11 (eval/p11/PROTOCOL.md): descriptive counts and Wilson 95% intervals; no hypothesis test"
NAME_FUNCTION = {"motion": "mandate", "postulate": "examine_report", "interpellation": "questions", "question": "questions"}
KIND_OF_TYPE = {"GA": "government_business", "PI": "parliamentary_initiative"}
ROLE_ARMS = ("rules", "record", "doc_order", "opd_first", "reader")


def share(k: int, n: int) -> dict:
    return dict(k=k, n=n, share=round(k / n, 4) if n else None,
                wilson95=[round(x, 4) for x in wilson(k, n)] if n else None)


def by(rows: list[dict], key: str, f, groups=None) -> dict:
    out = {"ALL": f(rows)}
    for g in groups or sorted({r[key] for r in rows}):
        rs = [r for r in rows if r[key] == g]
        if rs:
            out[g] = f(rs)
    return out


def _load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------------------------------------ IT
def it_answer_date(gold: dict, off: dict, ptr: dict | None) -> dict:
    arms: dict[str, list] = collections.defaultdict(list)
    desc = collections.Counter()
    for a, o in off.items():
        g = gold[a]["fields"]["answer_date"]
        gv = None if g["category"] == "null" else g["category"]
        desc[f"answer_present:{g.get('answer_present')}"] += 1
        desc[f"gold:{'printed' if gv else 'null'}"] += 1
        if gv:
            desc[f"role:{g.get('role')}"] += 1
        ad = o["answer_date"]
        base = dict(cell=o["stratum"], gold=gv, lenient=g.get("lenient") or [], doc_dates=ad["doc_dates"])
        arms["rules"].append(dict(base, pred=ad["rules"]["value"], route="rule"))
        arms["latest_on_answer_document"].append(dict(base, pred=ad["latest"], route="rule"))
        arms["converter_record"].append(dict(base, pred=ad["record"], route="rule"))
        if ptr and "date_pointer" in ptr.get(a, {}):
            arms["pointer"].append(dict(base, pred=ptr[a]["date_pointer"]["value"], route="apertus"))
    return dict(gold=dict(desc),
                arms={k: dict(n=len(v), strict=summarise(v, True), lenient=summarise(v, False)) for k, v in arms.items()},
                pointer_ran=bool(arms.get("pointer")), pointer_n=len(arms.get("pointer", [])))


def it_roles(gold: dict, off: dict, ptr: dict | None) -> dict:
    rows = []
    for a, o in off.items():
        gp = [tuple(x) for x in gold[a]["fields"]["people"]["pairs"]]
        preds = {k: [tuple(x) for x in o["roles"][k]] for k in ("rules", "record", "doc_order", "opd_first")}
        if ptr and "role_reader" in ptr.get(a, {}):
            preds["reader"] = [tuple(x) for x in ptr[a]["role_reader"]["pairs"]]
        rows.append(dict(stratum=o["stratum"], arms={k: S10.affair_row(v, gp) for k, v in preds.items()}))

    def table(rs):
        out = {}
        for arm in ROLE_ARMS:
            sub = [r for r in rs if arm in r["arms"]]
            if sub:
                p = S10.pooled(sub, arm)
                out[arm] = dict(p, affairs=len(sub), affairs_exact=share(sum(r["arms"][arm]["exact"] for r in sub),
                                                                          len(sub)))
        return out

    return dict(arms=by(rows, "stratum", table), gold_pairs=sum(len(g["fields"]["people"]["pairs"]) for g in gold.values()),
                reader_ran=any("reader" in r["arms"] for r in rows),
                note="pair = (name, role); P10's scorer (eval/p10/score.py: same person by convert.roles.same_person, "
                     "equal role, greedy one-to-one in printed order); opd_first is a reference row (OPD's names, not "
                     "located in the documents)")


def category_table(rows: list[dict], field: str, inner: str | None = None) -> dict:
    def get(r):
        x = r["fields"][field]
        return x[inner] if inner else x

    def f(rs):
        det = [r for r in rs if get(r)["applicable"] and get(r)["category"] != C8.UNDET]
        cats = collections.Counter(get(r)["category"] for r in det)
        und = collections.Counter(get(r).get("reason") for r in rs if get(r)["applicable"]
                                  and get(r)["category"] == C8.UNDET)
        E = C8.E["submitter" if field == "people" else field]
        return dict(affairs=len(rs), determinable=len(det), undeterminable_by_reason=dict(und), categories=dict(cats),
                    in_E=share(sum(cats[c] for c in E), len(det)), E=sorted(E),
                    decided_by_A3=sum(r["fields"][field]["source"] == "A3" for r in rs))
    return by(rows, "stratum", f)


def it_record_fields(gold: dict, off: dict) -> dict:
    fn, named, lang = [], [], []
    for a, o in off.items():
        g, s = gold[a], o["stratum"]
        gf = (g["parts"]["type"].get("function") or {}).get("value")
        gn = (g["parts"]["type"].get("instrument_named") or {}).get("value")
        rf, rn = o["instrument"]["function"], o["instrument"]["named"]
        if gf not in (None, "unclear"):
            fn.append(dict(stratum=s, o="false_null" if rf is None else "correct" if rf == gf else "wrong"))
        if gn is not None:
            named.append(dict(stratum=s, o="correct_null" if rn is None and gn == "none" else "false_null" if rn is None
                              else "correct" if rn == gn else "wrong"))
        gl = g["parts"]["language"].get("languages") or {}
        for role in ("question", "answer"):
            P_, R_ = set(gl.get(role) or []), set(o["language"].get(role) or [])
            lang.append(dict(stratum=s, o="no_label" if not P_ else "false_null" if not R_ else "correct" if P_ == R_
                             else "wrong"))

    def t(xs):
        c = collections.Counter(x["o"] for x in xs)
        return dict(n=len(xs), **dict(c), exact=share(c["correct"] + c["correct_null"], len(xs)))
    return dict(instrument_function=by(fn, "stratum", t), instrument_named=by(named, "stratum", t),
                language_of_text=by(lang, "stratum", t))


def it_main() -> dict:
    gold = {g["affair_id"]: g for g in C._jsonl(C.GOLD["it"])}
    if not gold:
        raise SystemExit(f"{C.GOLD['it']} missing: merge the IT gold first")
    from eval.p11 import arms as AR

    off_res = _load(AR.IT_OFF)
    if off_res is None:
        raise SystemExit("run `eval.p11.arms it-offline` first")
    off = {o["affair_id"]: o for o in off_res["per_affair"]}
    ptr_res = _load(AR.IT_PTR)
    ptr = {p["affair_id"]: p for p in ptr_res["per_affair"]} if ptr_res else None
    rows = list(gold.values())
    probe = _load(C.PROBE) or {}
    docs = collections.Counter((g["question_doc"], g["answer_doc"]) for g in rows)
    not_answer = sum(g["answer_doc"] != "executive_answer" for g in rows)
    out = dict(
        label=LABEL + ": IT cell (Italian-language interventions)",
        n=len(rows), by_stratum=dict(collections.Counter(g["stratum"] for g in rows)),
        by_type=dict(collections.Counter(g["affair_type"] for g in rows)),
        type_source=dict(collections.Counter(g["type_source"] for g in rows)),
        documents_by_route=dict(collections.Counter(v for o in off.values() for v in o["fetched_from"].values())),
        in_sample_for={b: v.get("in_sample_for") for b, v in ((probe.get("it") or {}).get("per_body") or {}).items()},
        documents_as_labelled={f"{q}|{a}": n for (q, a), n in docs.items()},
        converter_status=dict(collections.Counter(o["converter_status"] for o in off.values())),
        answer_date=it_answer_date(gold, off, ptr),
        author_roles=it_roles(gold, off, ptr),
        submitter_role=category_table(rows, "people", "submitter"),
        instrument_function=category_table(rows, "type"),
        text_language=category_table(rows, "language"),
        text_language_answer_document=by(rows, "stratum", lambda rs: dict(collections.Counter(
            g["fields"]["language"]["secondary"].get("answer_doc_category") for g in rs))),
        converter_record_fields=it_record_fields(gold, off),
        model_arms=dict(ran=ptr_res is not None, stopped=(ptr_res or {}).get("stopped"),
                        served_fingerprints=(ptr_res or {}).get("served_fingerprints"),
                        fingerprints_not_seen_in_role_reader_development=(ptr_res or {}).get(
                            "fingerprints_not_seen_in_role_reader_development")),
        stop_rules=dict(frame_check=dict(answer_doc_not_executive_answer=not_answer, n=len(rows),
                                         frame_invalid=not_answer * 2 > len(rows))),
    )
    C.R11.mkdir(parents=True, exist_ok=True)
    (C.R11 / "p11_it_tables.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


# ------------------------------------------------------------------------------------------------ NI
def verdict_table(rows: list[dict], f: str) -> dict:
    def t(rs):
        c = collections.Counter(r["fields"][f]["verdict"] for r in rs)
        det = len(rs) - c["cannot_tell"]
        roles = collections.Counter(r["fields"][f]["role"] for r in rs if r["fields"][f]["verdict"] == "fits")
        return dict(affairs=len(rs), verdicts=dict(c), determinable=det,
                    needs_new_role=share(c["new_role"], det), fits_existing_role=share(c["fits"], det),
                    not_printed=share(c["not_printed"], det), not_applicable=share(c["not_applicable"], det),
                    roles_used=dict(roles), decided_by_A3=sum(r["fields"][f]["source"] == "A3" for r in rs))
    return dict(by_type=by(rows, "ni_type", t, ("GA", "PI")), by_language=by(rows, "lang", t, C.NI_LANGS),
                by_stratum=by(rows, "stratum", t))


def record_class(s: str | None) -> str:
    if s is None:
        return "no_record"
    return s.split(":", 1)[0]


def ni_main() -> dict:
    from eval.p11 import arms as AR
    from eval.p11.annotate import NI_FIELDS

    rows = C._jsonl(C.GOLD["ni"])
    if not rows:
        raise SystemExit(f"{C.GOLD['ni']} missing: merge the NI gold first")
    off_res = _load(AR.NI_OFF)
    if off_res is None:
        raise SystemExit("run `eval.p11.arms ni-offline` first")
    off = {o["affair_id"]: o for o in off_res["per_affair"]}
    kinds = by(rows, "ni_type", lambda rs: dict(collections.Counter(r["affair_kind"]["value"] for r in rs)), ("GA", "PI"))
    conforms = [r for r in rows if r["affair_kind"]["value"] == KIND_OF_TYPE[r["ni_type"]]]
    mistyped = {t: sum(1 for r in rows if r["ni_type"] == t and r["affair_kind"]["value"] == "intervention")
                for t in ("GA", "PI")}
    n_type = {t: sum(1 for r in rows if r["ni_type"] == t) for t in ("GA", "PI")}
    new_roles = {f: [dict(id=r["id"], stratum=r["stratum"], labels=r["fields"][f]["new_role_labels"])
                     for r in rows if r["fields"][f]["verdict"] == "new_role"] for f in NI_FIELDS}
    cross = {}
    for f in NI_FIELDS:
        c = collections.Counter()
        for r in rows:
            o = off.get(r["affair_id"]) or {}
            st = (o.get("fields") or {}).get(f) if o.get("fields") else None
            c[f"{r['fields'][f]['verdict']}|{record_class(st)}"] += 1
        cross[f] = dict(c)
    status = by([dict(o, stratum=o["stratum"]) for o in off.values()], "stratum",
                lambda os: dict(collections.Counter(o["converter_status"] for o in os)))
    valid = sum(o["converter_status"] == "ok" for o in off.values())
    out = dict(
        label=LABEL + ": NI cell (government business and parliamentary initiatives vs the 17-field skeleton)",
        n=len(rows), by_stratum=dict(collections.Counter(r["stratum"] for r in rows)),
        type_source=dict(collections.Counter(r["type_source"] for r in rows)),
        affair_kind=kinds, affair_kind_conforms_to_opd_type=share(len(conforms), len(rows)),
        documents=dict(collections.Counter(v for r in rows for v in r["documents"].values())),
        fields={f: verdict_table(rows, f) for f in NI_FIELDS},
        fields_on_conforming_affairs={f: verdict_table(conforms, f)["by_type"] for f in NI_FIELDS} if conforms else None,
        new_roles=new_roles,
        converter=dict(status=status, valid_v0_2_records=share(valid, len(off)), gold_verdict_by_record_status=cross),
        stop_rules=dict(type_check={t: dict(labelled_intervention=mistyped[t], n=n_type[t],
                                            stratum_reported_as_opd_mistyping=mistyped[t] * 2 > n_type[t])
                                    for t in ("GA", "PI")}),
    )
    C.R11.mkdir(parents=True, exist_ok=True)
    (C.R11 / "p11_ni_tables.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1:]
    if cmd == ["it"]:
        r = it_main()
        print(json.dumps({k: r[k] for k in ("n", "by_stratum", "stop_rules")}, indent=1))
    elif cmd == ["ni"]:
        r = ni_main()
        print(json.dumps({k: r[k] for k in ("n", "by_stratum", "stop_rules")}, indent=1))
    else:
        print(__doc__)
