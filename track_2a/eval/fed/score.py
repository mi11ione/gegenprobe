"""Federal cell tables (eval/fed/PROTOCOL.md §6). EXPLORATORY and descriptive: counts and Wilson 95% intervals, per
stratum and overall; no hypothesis test, no threshold, no verdict.

    PYTHONPATH=src:. .venv/bin/python -m eval.fed.score    -> results/fed/fed_tables.json

Inputs: data/fed/fed_gold.jsonl (merged gold), results/fed/fed_arms_offline.json, results/fed/fed_arms_pointer.json (if the
pointer arm ran; its absence is reported), data/fed/fed_affairs.jsonl.
"""

from __future__ import annotations

import collections
import json

from eval.fed import common as C
from eval.p8 import common as C8
from eval.p8 import derive as Dv
from eval.score import summarise
from gegenprobe.stats import wilson

LABEL = "EXPLORATORY federal cell (eval/fed/PROTOCOL.md): descriptive counts and Wilson 95% intervals; no hypothesis test"
NAME_FUNCTION = {"motion": "mandate", "postulate": "examine_report", "interpellation": "questions", "question": "questions"}


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if p.exists() else []


def share(k: int, n: int) -> dict:
    return dict(k=k, n=n, share=round(k / n, 4) if n else None, wilson95=[round(x, 4) for x in wilson(k, n)] if n else None)


def by_stratum(rows: list[dict], f) -> dict:
    out = {"ALL": f(rows)}
    for s in C.STRATA:
        rs = [r for r in rows if r["stratum"] == s]
        if rs:
            out[s] = f(rs)
    return out


# ------------------------------------------------------------------------------------------------ answer date
def answer_date_tables(gold: dict, off: dict, ptr: dict | None) -> dict:
    arms: dict[str, list] = collections.defaultdict(list)
    desc = collections.Counter()
    for a, o in off.items():
        g = gold[a]["fields"]["answer_date"]
        gv = None if g["category"] == "null" else g["category"]
        desc[f"answer_present:{g.get('answer_present')}"] += 1
        desc[f"gold:{'printed' if gv else 'null'}"] += 1
        if gv:
            desc[f"role:{g.get('role')}"] += 1
            desc["printed_equals_an_opd_fc_event" if gv in o["fc_event_dates"] else "printed_differs_from_opd_fc_events"] += 1
        base = dict(cell=o["stratum"], gold=gv, lenient=g.get("lenient") or [], doc_dates=o["answer_date"]["doc_dates"])
        arms["rules"].append(dict(base, pred=o["answer_date"]["rules"]["value"], route="rule"))
        arms["latest_printed_date"].append(dict(base, pred=o["answer_date"]["latest"], route="rule"))
        rad = o.get("record_answer_date") or {}
        arms["converter_record_C"].append(dict(base, pred=rad.get("value") if rad.get("kind", "value") != "null" else None,
                                               route=rad.get("route", "rule")))
        if ptr and a in ptr:
            arms["pointer"].append(dict(base, pred=ptr[a]["pointer"]["value"], route="apertus"))
            ca = (ptr[a].get("CA") or {}).get("answer_date")
            arms["converter_CA"].append(dict(base, pred=ca, route="apertus"))
    meta_layer = collections.Counter()
    for o in off.values():
        dates = o.get("record_dates") or []
        ans = [d for d in dates if d.get("role") == "answered"]
        meta_layer["record_carries_opd_answer_event" if ans else "record_without_opd_answer_event"] += 1
    return dict(gold=dict(desc), metadata_layer=dict(meta_layer),
                arms={k: dict(strict=summarise(v, True), lenient=summarise(v, False)) for k, v in arms.items()},
                pointer_ran=ptr is not None)


# ------------------------------------------------------------------------------------------------ P8 fields
def category_table(rows: list[dict], field: str) -> dict:
    def f(rs):
        det = [r for r in rs if r["fields"][field]["applicable"] and r["fields"][field]["category"] != C8.UNDET]
        cats = collections.Counter(r["fields"][field]["category"] for r in det)
        und = collections.Counter(r["fields"][field].get("reason") for r in rs
                                  if r["fields"][field]["applicable"] and r["fields"][field]["category"] == C8.UNDET)
        k = sum(cats[c] for c in C8.E[field])
        return dict(affairs=len(rs), determinable=len(det), undeterminable_by_reason=dict(und), categories=dict(cats),
                    in_E=share(k, len(det)), E=sorted(C8.E[field]),
                    decided_by_A3=sum(r["fields"][field]["source"] == "A3" for r in rs))
    return by_stratum(rows, f)


def _authors_of_record(people: list[dict]) -> list[dict]:
    rec = [p for p in people if p.get("role") in ("sole_author", "first_signatory")]
    return rec or [p for p in people if p.get("role") == "joint_author"]


def name_outcome(pred: str | None, people: list[dict]) -> str:
    """A submitter name against the printed author(s) of record (P8's name matcher, surname tokens + first initial)."""
    rec = _authors_of_record(people)
    if pred is None:
        return "correct_null" if not rec else "false_null"
    parts = pred.split()
    first, last = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", pred)
    if any(Dv.name_match(first, last, p.get("name")) for p in rec):
        return "correct"
    return "wrong_printed" if any(Dv.name_match(first, last, p.get("name")) for p in people) else "wrong_or_unprinted"


def outcome_table(pairs: list[tuple[str, str]]) -> dict:
    """pairs of (stratum, outcome)."""
    def f(xs):
        c = collections.Counter(o for _, o in xs)
        ok = c["correct"] + c["correct_null"]
        return dict(n=len(xs), **dict(c), exact=share(ok, len(xs)))
    out = {"ALL": f(pairs)}
    for s in C.STRATA:
        xs = [p for p in pairs if p[0] == s]
        if xs:
            out[s] = f(xs)
    return out


def converter_people_and_type(gold: dict, off: dict, ptr: dict | None) -> dict:
    sub, typ_name, typ_fn = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for a, o in off.items():
        g = gold[a]
        people = g["parts"]["submitter"].get("people") or []
        named = (g["parts"]["type"].get("instrument_named") or {}).get("value")
        fn = (g["parts"]["type"].get("function") or {}).get("value")
        s = o["stratum"]
        arms = dict(o["converter"])
        if ptr and a in ptr and ptr[a].get("CA"):
            arms["CA"] = ptr[a]["CA"]
        for arm, v in arms.items():
            sub[arm].append((s, name_outcome(v.get("submitter"), people)))
            t = v.get("affair_type")
            if named is not None:
                typ_name[arm].append((s, "correct_null" if t is None and named == "none" else "false_null" if t is None
                                      else "correct" if t == named else "wrong"))
            if fn not in (None, "unclear"):
                typ_fn[arm].append((s, "false_null" if t is None else "correct" if NAME_FUNCTION.get(t) == fn else "wrong"))
    return dict(submitter_name={k: outcome_table(v) for k, v in sub.items()},
                type_vs_instrument_named={k: outcome_table(v) for k, v in typ_name.items()},
                type_vs_function={k: outcome_table(v) for k, v in typ_fn.items()})


def language_guess(gold: dict, off: dict) -> dict:
    pairs = collections.defaultdict(list)
    for a, o in off.items():
        langs = gold[a]["parts"]["language"].get("languages") or {}
        for role in ("question", "answer"):
            P = set(langs.get(role) or [])
            gu = o["language_guess"].get(role)
            pairs[role].append((o["stratum"], "correct" if P and {gu} == P else "no_label" if not P else "wrong"))
    return {r: outcome_table(v) for r, v in pairs.items()}


KIND = {"person": "person", "parliamentary_group": "group", "group": "group", "committee": "committee"}


def roles_tables(gold: dict, off: dict) -> dict | None:
    """The converter's role rules (if LOCKFED froze them) against the gold: the submitter pattern (P8's document-layer
    category of the printed authors), the author-of-record name, the instrument named and its function, and the
    language of each text."""
    if not any(o.get("roles") for o in off.values()):
        return None
    pat, name, named, fn, lang = ([] for _ in range(5))
    for a, o in off.items():
        r, g, s = o.get("roles") or {}, gold[a], o["stratum"]
        people = g["parts"]["submitter"].get("people") or []
        mine = [dict(name=(x.get("name") or {}).get("value"), role=x.get("role"), kind=KIND.get(x.get("kind"), "other_body"))
                for x in r.get("actors") or []]
        gcat, _ = Dv.submitter_doc(people)
        rcat, _ = Dv.submitter_doc(mine)
        pat.append((s, "correct_null" if gcat == rcat == C8.UNDET else "false_null" if rcat == C8.UNDET
                    else "correct" if rcat == gcat else "wrong"))
        rec = [m for m in mine if m["role"] in ("sole_author", "first_signatory")]
        name.append((s, name_outcome(rec[0]["name"] if rec else None, people)))
        gn = (g["parts"]["type"].get("instrument_named") or {}).get("value")
        gf = (g["parts"]["type"].get("function") or {}).get("value")
        ins = r.get("instrument") or {}
        rn, rf = (ins.get("named") or {}).get("value"), (ins.get("function") or {}).get("value")
        if gn is not None:
            named.append((s, "correct_null" if rn is None and gn == "none" else "false_null" if rn is None
                          else "correct" if rn == gn else "wrong"))
        if gf not in (None, "unclear"):
            fn.append((s, "false_null" if rf is None else "correct" if rf == gf else "wrong"))
        gl = g["parts"]["language"].get("languages") or {}
        for role in ("question", "answer"):
            P, R = set(gl.get(role) or []), set((r.get("language_of_text") or {}).get(role) or [])
            lang.append((s, "no_label" if not P else "false_null" if not R else "correct" if P == R else "wrong"))
    return dict(submitter_pattern=outcome_table(pat), submitter_name=outcome_table(name),
                instrument_named=outcome_table(named), instrument_function=outcome_table(fn),
                language_of_text=outcome_table(lang))


def main() -> dict:
    gold = {g["affair_id"]: g for g in _jsonl(C.GOLD)}
    if not gold:
        raise SystemExit(f"{C.GOLD} missing: merge the gold first")
    off_res = json.loads((C.RF / "fed_arms_offline.json").read_text(encoding="utf-8"))
    off = {o["affair_id"]: o for o in off_res["per_affair"]}
    for o in off.values():
        o["fc_event_dates"] = []
    for e in _jsonl(C.AFFAIRS):
        if e["affair_id"] in off:
            off[e["affair_id"]]["fc_event_dates"] = e.get("fc_event_dates") or []
    pp = C.RF / "fed_arms_pointer.json"
    ptr = {p["affair_id"]: p for p in json.loads(pp.read_text(encoding="utf-8"))["per_affair"]} if pp.exists() else None
    rows = [dict(g, stratum=g["stratum"]) for g in gold.values()]
    docs = collections.Counter((g["question_doc"], g["answer_doc"]) for g in rows)
    out = dict(
        label=LABEL,
        n=len(rows),
        by_stratum=dict(collections.Counter(g["stratum"] for g in rows)),
        by_type=dict(collections.Counter(g["affair_type"] for g in rows)),
        documents_as_labelled={f"{q}|{a}": n for (q, a), n in docs.items()},
        answer_date=answer_date_tables(gold, off, ptr),
        submitter_role=category_table(rows, "submitter"),
        instrument_function=category_table(rows, "type"),
        text_language=category_table(rows, "language"),
        text_language_answer_document={s: dict(collections.Counter(
            g["fields"]["language"]["secondary"].get("answer_doc_category") for g in rows if s in ("ALL", g["stratum"])))
            for s in ("ALL",) + C.STRATA},
        converter_fields=converter_people_and_type(gold, off, ptr),
        converter_language_guess=language_guess(gold, off),
        converter_role_rules=roles_tables(gold, off) or off_res.get("roles_arm"),
        v0_2_records=off_res["v0_2_validation"],
        stop_rules=stop_rules(rows, ptr),
    )
    C.RF.mkdir(parents=True, exist_ok=True)
    C.TABLES.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def stop_rules(rows: list[dict], ptr: dict | None) -> dict:
    """The protocol's reporting stop rules, evaluated (PROTOCOL.md §7)."""
    not_answer = sum(g["answer_doc"] != "executive_answer" for g in rows)
    return dict(frame_check=dict(answer_doc_not_executive_answer=not_answer, n=len(rows),
                                 frame_invalid=not_answer * 2 > len(rows)),
                pointer_arm="ran" if ptr is not None else "not run (see results/fed/sample.json and the run log)")


if __name__ == "__main__":
    r = main()
    print(json.dumps({k: r[k] for k in ("n", "by_stratum", "stop_rules")}, indent=1))
