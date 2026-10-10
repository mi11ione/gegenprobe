"""U3 development harness for pointer v2 (DEV ONLY: P1 dev, and DEV2 once labelled; never P1 held-out, P2, P3, P3b, P4).

    PYTHONPATH=src:. python -m eval.p6.dev features --set dev  --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p6-dev:3.0
    PYTHONPATH=src:. python -m eval.p6.dev features --set dev2 --backend ...      (DEV2 documents; labels optional)
    PYTHONPATH=src:. python -m eval.p6.dev table    --set dev [--set dev2]        -> results/p6/dev_variants.json

`features` writes one row per document with everything a variant needs (rules decision, v1 scores with token counts,
v2 presence and choice scores, the registered free-prompting answer re-parsed with eval/posthoc_r3.to_iso_fixed, printed
dates); `table` fits θ by leave-one-out on the selected development documents and scores every variant with the frozen
eval/score.py outcome (strict). No document text is written.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eval import arms
from eval import naive_baseline as nb
from eval.posthoc_r3 import to_iso_fixed
from eval.score import outcome
from gegenprobe import llm
from gegenprobe.convert import calibrate, lattice, pointer, rules
from gegenprobe.convert import pointer_v2 as V
from gegenprobe.paths import RESULTS, WORK
from gegenprobe.stats import logsumexp, wilson

OUT = RESULTS / "p6"
FEAT = WORK / "p6dev" / "features"
V1_THETA = 10.395354058425431  # data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json (P1 dev fit, frozen)


# ------------------------------------------------------------------------------------------------------------ loading
def load(set_name: str) -> list[dict]:
    if set_name == "dev":
        return arms.load_split("dev")
    from eval.p6 import dev2

    return dev2.load()


def v1_scores(be, pages: list[str], lang: str) -> dict:
    """v1 pointer scores, read through the normal backend, plus the token count of every continuation (cache entry)."""
    text, offs, trunc = pointer.doc_text(pages)
    cands = [c for c in lattice.dates(pages) if pointer._visible(c, offs, pointer.CHAR_BUDGET)]
    values = lattice.distinct_dates(cands)
    if not values:
        return dict(values=[], lps=[], lp_null=0.0, ntok=[], ntok_null=1)
    conts = [f' "{pointer.ddmmyyyy(v)}"' for v in values]
    lps, lp_null, pid, _ = pointer.score_field(be, "answer_date", lang, pages, values, conts)
    tmpl, _ = pointer.template("answer_date", lang)
    user = tmpl.replace("{doc}", text)
    pre = pointer.PREFIX["answer_date"][lang]
    ntok = []
    for c in [pointer.NULL_CONT] + conts:
        payload = dict(model=be.model, temperature=0.0, max_tokens=1,
                       messages=[{"role": "user", "content": user}, {"role": "assistant", "content": pre + c}],
                       continue_final_message=True, add_generation_prompt=False, prompt_logprobs=1, _cont=c)
        hit = be.cache.get(llm.ModelCache.key(be.build, "score", payload))
        ntok.append(len(hit["toks"]) if hit and "toks" in hit else None)
    return dict(values=values, lps=lps, lp_null=lp_null, ntok=ntok[1:], ntok_null=ntok[0], prompt_id=pid)


def features(be, d: dict) -> dict:
    pages, lg = d["pages"], arms._lang(d)
    lab = d.get("label") or {}
    dd = sorted({c["value"] for c in lattice.dates(pages)})
    r = rules.answer_date(pages, d.get("image_only", False))
    row = dict(doc_id=d["doc_id"], cell=d.get("cell"), body=d.get("body"), lang=lg, gold=lab.get("answer_date"),
               lenient=lab.get("answer_date_lenient") or [], has_label=bool(lab), doc_dates=dd,
               rules=dict(status=r["status"], value=r.get("value") if r["status"] == "value" else None))
    if be is None:
        return row
    row["v1"] = v1_scores(be, pages, lg)
    vals, _, _ = V.options(pages)
    if vals:
        row["presence"] = V.presence(be, pages, lg)
        q = V.mcq(be, pages, lg)
        row["mcq"] = dict(values=q["values"], lps=q["lps"], lp_none=q["lp_none"], m_mcq=q["m_mcq"])
        q = V.guided(be, pages, lg)
        row["guided"] = dict(values=q["values"], lps=q["lps"], lp_null=q["lp_null"], m_guided=q["m_guided"])
        for name in V.ROLE_TEMPLATES:
            q = V.mcq(be, pages, lg, name=name)
            row[name] = dict(values=q["values"], lps=q["lps"], lp_none=q["lp_none"], m_mcq=q["m_mcq"])
    text = pointer.doc_text(pages)[0]
    g = be.generate(nb.prompt(lg, "null").replace("{doc}", text), max_tokens=200, seed=d["doc_id"] % 100000)
    o = nb.parse(g)
    fixed, how = to_iso_fixed(o.get("antwort_datum"))
    row["naive_null"] = dict(raw=o.get("antwort_datum"), date=fixed, how=how)
    g = be.generate(nb.prompt(lg, "guided").replace("{doc}", text), max_tokens=60, seed=d["doc_id"] % 100000)
    fixed, how = to_iso_fixed(nb.parse(g).get("antwort_datum"))
    row["naive_guided"] = dict(raw=nb.parse(g).get("antwort_datum"), date=fixed, how=how, gen=g[:120])
    return row


def run_features(set_name: str, spec: str) -> Path:
    be = arms.backend(spec)
    docs = load(set_name)
    with ThreadPoolExecutor(int(os.environ.get("GP_WORKERS", "3"))) as ex:
        rows = list(ex.map(lambda d: features(be, d), docs))
    FEAT.mkdir(parents=True, exist_ok=True)
    p = FEAT / f"{set_name}.jsonl"
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(p, len(rows), "served:", sorted(getattr(be, "served", set())))
    return p


# ------------------------------------------------------------------------------------------------------------ variants
def _argmax(values, lps):
    return values[max(range(len(values)), key=lambda i: lps[i])] if values else None


def _softmax(xs):
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    s = sum(e)
    return [v / s for v in e]


def m_v1(r):
    v = r["v1"]
    return v["lp_null"] - logsumexp(v["lps"]) if v["values"] else math.inf


def m_v1_norm(r):
    """Per-token mean log-probability: ' null' vs the best date string, each divided by its own token count."""
    v = r["v1"]
    if not v["values"]:
        return math.inf
    per = [lp / max(1, n or 1) for lp, n in zip(v["lps"], v["ntok"])]
    return v["lp_null"] / max(1, v["ntok_null"] or 1) - max(per)


def m_pres(r):
    return r["presence"]["m_absent"] if "presence" in r else math.inf


def m_mcq(r):
    return r["mcq"]["m_mcq"] if "mcq" in r else math.inf


def pick_v1(r):
    return _argmax(r["v1"]["values"], r["v1"]["lps"])


def pick_mcq(r):
    return _argmax(r["mcq"]["values"], r["mcq"]["lps"]) if "mcq" in r else None


def pick_ens(r):
    """Mean of the two normalised distributions over the same printed dates (v1 date strings, v2 lettered options)."""
    if "mcq" not in r or not r["v1"]["values"]:
        return pick_mcq(r)
    a = dict(zip(r["v1"]["values"], _softmax(r["v1"]["lps"])))
    b = dict(zip(r["mcq"]["values"], _softmax(r["mcq"]["lps"])))
    vals = list(b)
    return max(vals, key=lambda v: a.get(v, 0.0) + b[v])


def pick_role(r, fallback=None):
    """The gold guide's precedence applied in code: the decision-date choice if it names a date (its letter beats 'none'),
    else the dispatch-date choice if it names a date, else the fallback pick (default: the answer-date choice)."""
    for name in V.ROLE_TEMPLATES:
        q = r.get(name)
        if q and q["values"] and max(q["lps"]) > q["lp_none"]:
            return _argmax(q["values"], q["lps"])
    return (fallback or pick_mcq)(r)


def pick_role_ens(r):
    return pick_role(r, pick_ens)


def m_sum(r):
    """Two-signal null score: presence margin + v2 'none' margin (both in nats)."""
    return m_pres(r) + m_mcq(r)


def m_guided(r):
    return r["guided"]["m_guided"] if "guided" in r else math.inf


def pick_guided(r):
    return _argmax(r["guided"]["values"], r["guided"]["lps"]) if "guided" in r else None


def m_role(r):
    """Null margin from the two role choices: −(best date letter − 'none' letter), taken over decision and dispatch."""
    v = [max(r[n]["lps"]) - r[n]["lp_none"] for n in V.ROLE_TEMPLATES if r.get(n) and r[n]["values"]]
    return -max(v) if v else math.inf


GATES = {"v1": m_v1, "guided": m_guided, "role_none": m_role, "v1_norm": m_v1_norm, "presence": m_pres, "mcq_none": m_mcq,
         "presence+mcq_sum": m_sum}
PICKS = {"v1": pick_v1, "mcq": pick_mcq, "ens": pick_ens, "role": pick_role, "role_ens": pick_role_ens, "guided": pick_guided}


def loo_null(ms: list[float], ys: list[bool]) -> list[bool]:
    """Leave-one-out abstention decision per document (θ fitted on the others by calibrate.fit_theta)."""
    out = []
    finite = [i for i, m in enumerate(ms) if math.isfinite(m)]
    for i, m in enumerate(ms):
        if not math.isfinite(m):
            out.append(True)
            continue
        idx = [j for j in finite if j != i]
        th, _ = calibrate.fit_theta([ms[j] for j in idx], [ys[j] for j in idx])
        out.append(m > th)
    return out


def ok(pred, r) -> bool:
    return outcome(pred, r["gold"], set(r["doc_dates"]), r.get("lenient"), True) in ("correct", "correct_null")


def summary(rows: list[dict], preds: list) -> dict:
    n = len(rows)
    ex = sum(ok(p, r) for p, r in zip(preds, rows))
    val = [(p, r) for p, r in zip(preds, rows) if r["gold"] is not None]
    nul = [(p, r) for p, r in zip(preds, rows) if r["gold"] is None]
    found = sum(p == r["gold"] for p, r in val)
    wrong = sum(p is not None and p != r["gold"] for p, r in val)
    on_null = sum(p is not None for p, r in nul)
    return dict(exact=[ex, n], exact_ci=[round(x, 3) for x in wilson(ex, n)], dates_found=[found, len(val)],
                wrong_date_on_answered=wrong, missed=len(val) - found - wrong, dated_answerless=[on_null, len(nul)])


def table(sets: list[str]) -> dict:
    rows = []
    for s in sets:
        rows += [dict(json.loads(x), set=s) for x in open(FEAT / f"{s}.jsonl")]
    rows = [r for r in rows if r["has_label"] and "v1" in r]
    ys = [r["gold"] is None for r in rows]
    out = dict(sets=sets, n=len(rows), n_answered=sum(not y for y in ys), variants={})

    def put(name, preds):
        out["variants"][name] = summary(rows, preds)
        return preds

    put("rules", [r["rules"]["value"] for r in rows])
    put("v1_theta_frozen", [None if m_v1(r) > V1_THETA else pick_v1(r) for r in rows])
    put("naive_null_reparsed", [r["naive_null"]["date"] for r in rows])
    if all("naive_guided" in r for r in rows):
        put("naive_guided_reparsed", [r["naive_guided"]["date"] for r in rows])
    put("latest_printed_date", [max(r["doc_dates"]) if r["doc_dates"] else None for r in rows])
    put("always_null", [None for _ in rows])
    for gname, gf in GATES.items():
        ms = [gf(r) for r in rows]
        nulls = loo_null(ms, ys)
        nulls0 = [not math.isfinite(m) or m > 0 for m in ms]
        for pname, pf in PICKS.items():
            put(f"{gname}_loo|{pname}", [None if z else pf(r) for z, r in zip(nulls, rows)])
            if gname in ("presence", "mcq_none", "presence+mcq_sum", "role_none", "guided"):
                put(f"{gname}_theta0|{pname}", [None if z else pf(r) for z, r in zip(nulls0, rows)])
    # oracle diagnostics: date choice alone (on answered documents) and null detection alone
    val = [r for r in rows if r["gold"] is not None]
    out["pick_accuracy_on_answered"] = {p: [sum(f(r) == r["gold"] for r in val), len(val)] for p, f in PICKS.items()}
    from gegenprobe.stats import auroc

    out["null_auroc"] = {g: auroc([f(r) for r in rows if r["gold"] is None and math.isfinite(f(r))],
                                  [f(r) for r in rows if r["gold"] is not None and math.isfinite(f(r))])
                         for g, f in GATES.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"dev_variants__{'+'.join(sets)}.json"
    p.write_text(json.dumps(out, indent=1))
    return out


THETA_PRESENCE_DEV = -5.887991393334232  # calibrate.fit_theta on the P1 dev presence margins (127 documents)


def select() -> dict:
    """Apply eval/p6/DEV2_SELECTION.md exactly: candidates A, B, C on DEV2 with θ from P1 dev, plus the comparison arms."""
    out = dict(rule="eval/p6/DEV2_SELECTION.md (committed 6810ee5 before any DEV2 label)",
               theta_presence_p1dev=THETA_PRESENCE_DEV, sets={})
    for s in ("dev2", "dev"):
        rows = [r for r in (json.loads(x) for x in open(FEAT / f"{s}.jsonl")) if r["has_label"]]

        def gv(r):
            g = r["naive_guided"]["date"]
            return g if g in r["doc_dates"] else None

        arms_ = {
            "A_presence_theta_dev+role": [None if m_pres(r) > THETA_PRESENCE_DEV else pick_role(r) for r in rows],
            "B_presence_theta0+role": [None if m_pres(r) > 0 else pick_role(r) for r in rows],
            "C_presence_theta_dev+generate_then_point": [None if m_pres(r) > THETA_PRESENCE_DEV else (gv(r) or pick_role(r))
                                                         for r in rows],
            "v1_pointer_theta_10.40": [None if m_v1(r) > V1_THETA else pick_v1(r) for r in rows],
            "rules": [r["rules"]["value"] for r in rows],
            "free_prompt_registered_null_reparsed": [r["naive_null"]["date"] for r in rows],
            "free_prompt_guided_reparsed": [r["naive_guided"]["date"] for r in rows],
            "latest_printed_date": [max(r["doc_dates"]) if r["doc_dates"] else None for r in rows],
            "always_null": [None for _ in rows],
        }
        out["sets"][s] = dict(n=len(rows), n_answered=sum(r["gold"] is not None for r in rows),
                              bodies=sorted({str(r.get("body")) for r in rows if r.get("body")}),
                              arms={k: summary(rows, v) for k, v in arms_.items()})
    d2 = out["sets"]["dev2"]["arms"]
    cand = ["A_presence_theta_dev+role", "B_presence_theta0+role", "C_presence_theta_dev+generate_then_point"]
    calls = {"B_presence_theta0+role": 0, "A_presence_theta_dev+role": 1, "C_presence_theta_dev+generate_then_point": 2}
    pooled = {c: d2[c]["exact"][0] + out["sets"]["dev"]["arms"][c]["exact"][0] for c in cand}
    order = sorted(cand, key=lambda c: (-d2[c]["exact"][0], d2[c]["dated_answerless"][0], -pooled[c], calls[c]))
    out["chosen"] = order[0]
    out["ranking"] = order
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev2_selection.json").write_text(json.dumps(out, indent=1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["features", "table", "select"])
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--backend", default="gateway:swiss-ai/apertus-v1.5-8b:2a-p6-dev:3.0")
    a = ap.parse_args()
    sets = a.set or ["dev"]
    if a.cmd == "select":
        o = select()
        print("chosen:", o["chosen"], "ranking:", o["ranking"])
        return
    if a.cmd == "features":
        for s in sets:
            run_features(s, a.backend)
    else:
        t = table(sets)
        print("n", t["n"], "answered", t["n_answered"])
        for k, v in t["variants"].items():
            print(f"{k:34s} exact {v['exact'][0]:3d}/{v['exact'][1]}  found {v['dates_found'][0]:2d}/{v['dates_found'][1]}"
                  f"  wrong {v['wrong_date_on_answered']:2d}  missed {v['missed']:2d}"
                  f"  dated-answerless {v['dated_answerless'][0]}/{v['dated_answerless'][1]}")
        print("pick acc", t["pick_accuracy_on_answered"])
        print("null auroc", {k: round(v, 3) for k, v in t["null_auroc"].items()})


if __name__ == "__main__":
    main()
