"""Stale procedural states: OPD's state says `submitted` while an answer is attached or dated (post hoc, descriptive OPD
data finding; no model, no network).

Rule (one cross-field consistency check, the same on the converter's records and on the census):
  a record / affair is *stale* when its procedural state, read from OPD's events as the last event whose harmonised title
  maps to a state (data/schema/opd_event_titles.json `maps_to.state`, the converter's EVENT_MAP; gegenprobe.schema.v0_2_meta
  `_state`), is `submitted` (PRE_ANSWER_STATES) while an answer is already there:
    records  qa[] names an answer document (answer_doc / answer_text_ref), or carries an answer date value, or dates[]
             carries an answer role (answered / answer_decided / answer_dispatched) with a value;
    census   the census answer-link status is `attached` (answer text in OPD on the affair: an answer document with
             usable text or an answer row in the texts export; gegenprobe.census.funnel), or the affair has a written-answer
             event (census.defs.classify_event == 'written').
  Census ties: when several state events share the latest date, the affair counts only if every one of them is
  `submitted` (conservative). Strict variant (`strict`): a written-answer event dated after the state event, i.e. OPD's
  own events show the state is older than the answer. Scope: the census's in-scope affairs (defs.SCOPE_TYPES).
  The federal parliament's Curia Vista events carry no harmonised title; their state is not read here (as in the census).

What it means for OPD: the state field lags the documents and events OPD already holds; a consumer filtering on
`state = submitted` to find unanswered interventions gets answered ones.

    python -m gegenprobe.findings.stale_states           -> results/findings/stale_states.json (+ stale_states.tsv.gz)
    python -m gegenprobe.findings.stale_states --check   exit 1 if a fresh derivation differs from the committed files
"""
from __future__ import annotations

import collections
import csv
import gzip
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V02 = ROOT / "results" / "schema" / "v0_2"
RECORD_SETS = (("p3", "p3_records.jsonl"), ("p3b", "p3b_records.jsonl"), ("p5", "p5_records.jsonl"),
               ("fed", "fed_records.jsonl"))
OUT = ROOT / "results" / "findings" / "stale_states.json"
OUT_TSV = ROOT / "results" / "findings" / "stale_states.tsv.gz"
TITLES = ROOT / "data" / "schema" / "opd_event_titles.json"
PRE_ANSWER_STATES = ("submitted",)
ANSWER_ROLES = ("answered", "answer_decided", "answer_dispatched")
LABEL = "POST HOC, descriptive OPD data finding"
COMMAND = "PYTHONPATH=src:. python -m gegenprobe.findings.stale_states"
N_EXAMPLES = 3


# ----------------------------------------------------------------------------------------------------------- records
def stale_state(rec: dict) -> dict | None:
    """The evidence when the record's procedural state is a pre-answer state while an answer is attached or dated, else
    None. Pure: reads the record only."""
    ps = rec.get("procedural_state") or {}
    if ps.get("kind") != "value" or ps.get("value") not in PRE_ANSWER_STATES:
        return None
    docs, dates = [], []
    for q in rec.get("qa") or []:
        d = q.get("answer_doc") or q.get("answer_text_ref")
        if d:
            docs.append(d)
        ad = q.get("answer_date") or {}
        if ad.get("kind") == "value":
            dates.append(dict(path="qa.answer_date", value=ad.get("value"), role=ad.get("role"), route=ad.get("route")))
    for d in rec.get("dates") or []:
        v = d.get("date") or {}
        if d.get("role") in ANSWER_ROLES and v.get("kind") == "value":
            dates.append(dict(path=f"dates[{d['role']}]", value=v.get("value"), role=d["role"], route=v.get("route")))
    if not (docs or dates):
        return None
    src = ps.get("source")
    state_date = next((d["date"].get("value") for d in rec.get("dates") or []
                       if src and (d.get("date") or {}).get("source") == src), None)
    vals = sorted({d["value"] for d in dates if d.get("value")})
    return dict(state=ps["value"], state_source=src, state_date=state_date, answer_docs=sorted(set(docs)),
                answer_dates=dates, kind="answer_attached" if docs else "answer_dated",
                answer_before_state=bool(state_date and vals and vals[0] < state_date))


def records_block(base: Path = V02) -> dict:
    by_set, rows = {}, []
    for k, name in RECORD_SETS:
        p = base / name
        recs = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
        n = 0
        for r in recs:
            ev = stale_state(r)
            if ev:
                n += 1
                rows.append(dict(set=k, body=r["ref"]["body_key"], opd_id=r["ref"]["opd_id"],
                                 state_source=ev["state_source"], state_date=ev["state_date"], kind=ev["kind"],
                                 answer_docs=ev["answer_docs"],
                                 answer_dates=sorted({d["value"] for d in ev["answer_dates"] if d.get("value")}),
                                 answer_before_state=ev["answer_before_state"]))
        by_set[k] = dict(n_records=len(recs), stale=n)
    rows.sort(key=lambda r: (r["set"], str(r["body"]), int(r["opd_id"])))
    n_all = sum(v["n_records"] for v in by_set.values())
    n_stale = len(rows)
    return dict(files=[f"results/schema/v0_2/{n}" for _, n in RECORD_SETS], n_records=n_all, stale=n_stale,
                sets=by_set, by_body=dict(sorted(collections.Counter(str(r["body"]) for r in rows).items())),
                answer_before_state=sum(r["answer_before_state"] for r in rows), records=rows,
                sentence=f"{n_stale} of {n_all} converter records carry procedural_state `submitted` from OPD's events "
                         "next to an attached or dated answer")


# ----------------------------------------------------------------------------------------------------------- census
def _state_map() -> dict[int, str]:
    return {e["opd_id"]: e["maps_to"]["state"] for e in json.loads(TITLES.read_text(encoding="utf-8"))
            if "state" in e["maps_to"]}


def census_block(root: Path | None = None) -> tuple[dict, list[dict]]:
    """Per body: in-scope affairs, answered (attached or written-answer event), last state submitted, stale."""
    from ..census import defs, funnel
    from ..census.tables import CENSUS, i, rows

    root = root or CENSUS
    _, aff = funnel.compute(root)
    smap = _state_map()
    last: dict[int, tuple[str, set]] = {}
    for e in rows("events", root):
        a = i(e["affair"])
        if a not in aff or not e["date"]:
            continue
        st = smap.get(i(e["hid"]))
        if st is None:
            continue
        d = e["date"][:10]
        cur = last.get(a)
        if cur is None or d > cur[0]:
            last[a] = (d, {st})
        elif d == cur[0]:
            cur[1].add(st)
    ans_dates: dict[int, list[str]] = collections.defaultdict(list)
    for e in rows("events", root):
        a = i(e["affair"])
        if a in aff and e["date"] and defs.classify_event(e["title"], i(e["hid"])) == "written":
            ans_dates[a].append(e["date"][:10])
    per = collections.defaultdict(collections.Counter)
    out_rows = []
    for a, x in aff.items():
        c = per[x["b"]]
        c["in_scope"] += 1
        attached = x.get("link") == "attached"
        answered = attached or x["ev_w"]
        c["answered"] += answered
        ls = last.get(a)
        sub = bool(ls and ls[1] <= set(PRE_ANSWER_STATES))
        c["last_state_submitted"] += sub
        if not (sub and answered):
            continue
        later = sorted(d for d in ans_dates.get(a, []) if d > ls[0])
        c["stale"] += 1
        c["stale_attached"] += attached
        c["stale_answer_event"] += x["ev_w"]
        c["strict"] += bool(later)
        out_rows.append(dict(body=x["b"], affair_id=a, type=x["t"], state_date=ls[0], link_status=x.get("link"),
                             answer_event=int(x["ev_w"]), first_answer_event=min(ans_dates[a]) if ans_dates.get(a) else "",
                             strict=int(bool(later))))
    out_rows.sort(key=lambda r: (r["body"], r["affair_id"]))
    keys = ("in_scope", "answered", "last_state_submitted", "stale", "stale_attached", "stale_answer_event", "strict")
    tot = collections.Counter()
    for c in per.values():
        tot.update({k: c[k] for k in keys})
    ex = collections.defaultdict(list)
    for r in out_rows:
        if len(ex[r["body"]]) < N_EXAMPLES:
            ex[r["body"]].append(r["affair_id"])
    bodies = sorted(((b, c) for b, c in per.items() if c["stale"]), key=lambda bc: (-bc[1]["stale"], bc[0]))
    block = dict(
        source="data/census/{affairs,events,docs,docs_other,agendas,texts,be_ogd_answers}.tsv.gz (OPD exports of the "
               "census snapshot; answer-link status by gegenprobe.census.funnel)",
        totals={k: tot[k] for k in keys},
        share_of_answered=round(tot["stale"] / tot["answered"], 4) if tot["answered"] else None,
        n_bodies_with_stale=len(bodies),
        bodies=[dict(body=b, **{k: c[k] for k in keys},
                     share_of_answered=round(c["stale"] / c["answered"], 4) if c["answered"] else None,
                     examples=ex[b]) for b, c in bodies],
        list="results/findings/stale_states.tsv.gz (one row per stale affair)",
        sentence=(f"{tot['stale']:,} of {tot['answered']:,} answered in-scope affairs in OPD "
                  f"({100 * tot['stale'] / max(tot['answered'], 1):.1f}%, {len(bodies)} parliaments) still carry the state "
                  f"`submitted` as their last state event; {tot['strict']:,} of them have a written-answer event dated "
                  "after that state event"),
    )
    return block, out_rows


# ----------------------------------------------------------------------------------------------------------- output
def _tsv(rows_: list[dict]) -> bytes:
    s = io.StringIO()
    cols = ("body", "affair_id", "type", "state_date", "link_status", "answer_event", "first_answer_event", "strict")
    w = csv.DictWriter(s, fieldnames=cols, delimiter="\t", lineterminator="\n")
    w.writeheader()
    for r in rows_:
        w.writerow(r)
    return gzip.compress(s.getvalue().encode("utf-8"), mtime=0)


def render() -> tuple[str, bytes]:
    census, rows_ = census_block()
    doc = dict(
        label=LABEL, command=COMMAND,
        rule=("procedural state = the last OPD event whose harmonised title maps to a state (data/schema/"
              "opd_event_titles.json; gegenprobe.schema.v0_2_meta._state) is `submitted` while an answer is attached "
              "(answer document / text) or dated (answer date, answer event); strict: a written-answer event dated after "
              "the state event"),
        pre_answer_states=list(PRE_ANSWER_STATES),
        records=records_block(),
        census=census,
        next_to="results/census/vocab_bugs.tsv (OPD vocabulary findings)",
    )
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n", _tsv(rows_)


def check() -> dict:
    text, tsv = render()
    same = (OUT.exists() and OUT.read_text(encoding="utf-8") == text and OUT_TSV.exists()
            and gzip.decompress(OUT_TSV.read_bytes()) == gzip.decompress(tsv))
    d = json.loads(text)
    return dict(status="PASS" if same else "FAIL",
                summary=f"stale states: {d['records']['stale']}/{d['records']['n_records']} converter records, "
                        f"{d['census']['totals']['stale']} census affairs; "
                        + ("identical to the committed files" if same else "DIFFER from the committed files"))


def step(ctx: dict) -> dict:
    return check()


def main(argv: list[str]) -> int:
    if "--check" in argv:
        r = check()
        print(r["summary"])
        return 0 if r["status"] == "PASS" else 1
    text, tsv = render()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    OUT_TSV.write_bytes(tsv)
    d = json.loads(text)
    print(OUT)
    print(d["records"]["sentence"])
    print(d["census"]["sentence"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
