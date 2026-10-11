"""Re-derive the spike numbers the converter rests on, through the repo's own code path (convert.calibrate), from the cached
spike outputs. No model is called. This proves calibrate.py reproduces spikes/inversions/f2_abstain.py.

Inputs (read-only, outside the repo; the small extracts needed for `make run` are vendored by `--vendor` into
data/convert/spike_margins.json):
  spikes/stage/results/{SFT,RLVR,DPO,final,final_dwq}.json   S-NULL margins lp(' null') − lp(' "'), 15 answerless + 5 answered BE
  spikes/round8/results/shape.json                          S-SHAPE: lp of ' null' and each ' "DD.MM.YYYY"' candidate, 30 docs
  spikes/live/results/null_apertus-v1.5-8b.json             live S-NULL margins (Public AI -8b name = 70B weights)
Out: results/convert/spike_replay.json
usage: python -m eval.replay_spikes [--vendor]
"""

import json
import sys

from gegenprobe.convert.calibrate import calibrate, fit_theta, transfer
from gegenprobe import devpaths
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import logsumexp

SPIKES = devpaths.spikes()  # GP_SPIKES_DIR (development only; gegenprobe/devpaths.py)
VENDOR = DATA / "convert" / "spike_margins.json"
STAGES = ["SFT", "RLVR", "DPO", "final", "final_dwq"]
SHAPE_ARMS = ["a_json_null", "b_verbal", "c_schema_sentinel", "d_doc_sentinel"]


def extract() -> dict:
    """Pull only margins/labels (no document text) from the spike files."""
    devpaths.require_spikes("eval.replay_spikes extract")
    out = {"snull": {}, "shape": [], "live": None}
    for st in STAGES:
        d = json.load(open(SPIKES / f"stage/results/{st}.json"))
        out["snull"][st] = [
            dict(
                id=r["affair_id"],
                kind=r["kind"],
                **{a: float(r["arms"][a]["logodds"]) for a in ("chat_plain", "chat_null") if a in r["arms"]},
            )
            for r in d["rows"]
        ]
    for r in json.load(open(SPIKES / "round8/results/shape.json"))["rows"]:
        out["shape"].append(
            dict(
                id=r["affair_id"],
                body=r["body"],
                kind=r["kind"],
                gold_lenient=r.get("gold_lenient") or [],
                arms={a: dict(conts=r["arms"][a]["conts"], lp=r["arms"][a]["lp"]) for a in SHAPE_ARMS},
            )
        )
    out["naive"] = naive_extract()
    lp = SPIKES / "live/results/null_apertus-v1.5-8b.json"
    if lp.exists():
        rows = json.load(open(lp))["rows"]
        out["live"] = [
            dict(id=r["affair_id"], kind=r["kind"], **{a: r["arms"][a].get("logodds") for a in ("plain", "null")}) for r in rows
        ]
    return out


def naive_extract() -> dict:
    """S-NULL free generations (round7 local DWQ 8B; live Public AI names), reduced to what the scorer needs:
    generation text, gold, the set of dates in the document and the receipt check. No document text is kept."""
    from eval.naive_baseline import parse, receipt_ok
    from gegenprobe.convert.lattice import dates

    items = {str(x["affair_id"]): x for x in json.load(open(SPIKES / "round7/null_items.json"))}
    live_docs = json.load(open(SPIKES / "live/null_docs.json")) if (SPIKES / "live/null_docs.json").exists() else {}
    runs = {"round7_dwq_8b": json.load(open(SPIKES / "round7/results/null.json"))["rows"]}
    # Public AI serves the 70B weights under both names (spikes/live): keys say so; no dots (claims paths are dotted)
    for name, key in (("apertus-v1.5-8b", "live_publicai_70b_via_8b_name"), ("apertus-v1.5-70b", "live_publicai_70b_name")):
        p = SPIKES / f"live/results/null_{name}.json"
        if p.exists():
            runs[key] = json.load(open(p))["rows"]
    out = {}
    for run, rows in runs.items():
        recs = []
        for r in rows:
            aid = str(r["affair_id"])
            text = live_docs[aid]["doc"] if run.startswith("live") and aid in live_docs else items[aid]["text"]
            gold = items[aid]["gold_answer_date"]
            gold = None if gold in (None, "None") else gold
            arms = {}
            for arm in ("plain", "null"):
                o = parse(r["arms"][arm]["gen"])
                arms[arm] = dict(gen=r["arms"][arm]["gen"], receipt_ok=receipt_ok(o, text))
            recs.append(dict(id=aid, kind=r["kind"], gold=gold, doc_dates=sorted({c["value"] for c in dates([text])}), arms=arms))
        out[run] = recs
    return out


def naive_scores(d: dict) -> dict:
    from eval.naive_baseline import parse, score, to_iso

    res = {}
    for run, recs in d.items():
        for arm in ("plain", "null"):
            rows = [
                dict(
                    pred=to_iso(parse(r["arms"][arm]["gen"]).get("antwort_datum")),
                    gold=r["gold"],
                    doc_dates=r["doc_dates"],
                    receipt_ok=r["arms"][arm]["receipt_ok"],
                )
                for r in recs
            ]
            res[f"{run}|{arm}"] = score(rows)
    return res


def shape_arm(rows: list[dict], arm: str) -> dict:
    recs = []
    for r in rows:
        a = r["arms"][arm]
        lp, conts = a["lp"], a["conts"]
        margin = lp[0] - logsumexp(lp[1:])
        best = max(range(1, len(lp)), key=lambda i: lp[i])
        dd = conts[best].strip().strip('"')
        iso = f"{dd[6:10]}-{dd[3:5]}-{dd[0:2]}"
        recs.append(dict(id=r["id"], body=r["body"], kind=r["kind"], margin=margin, best=iso, ok=iso in r["gold_lenient"]))
    be = [x for x in recs if x["body"] == "BE"]
    m, y = [x["margin"] for x in be], [x["kind"] == "no_answer" for x in be]
    cal = calibrate("final_dwq", f"shape_{arm}", [x["id"] for x in be], m, y)
    ctrl = [x for x in recs if x["body"] in ("ZH", "BS")]
    kept = [x for x in ctrl if x["margin"] <= cal.theta]
    folds = []
    for i in range(len(m)):
        t, _ = fit_theta(m[:i] + m[i + 1 :], y[:i] + y[i + 1 :])
        folds.append(sum(x["margin"] <= t for x in ctrl))
    be_ans = [x for x in be if x["kind"] != "no_answer"]
    return dict(
        BE_auroc=cal.auroc,
        BE_gap=cal.gap,
        theta=cal.theta,
        BE_loo=cal.loo,
        ctrl_n=len(ctrl),
        ctrl_kept=len(kept),
        ctrl_kept_correct=sum(x["ok"] for x in kept),
        ctrl_kept_across_loo_folds=[min(folds), max(folds)],
        ctrl_kept_default0=sum(x["margin"] <= 0 for x in ctrl),
        BE_answered_date_correct=sum(x["ok"] for x in be_ans),
        BE_answered_n=len(be_ans),
    )


def main(vendor: bool = False) -> dict:
    if vendor or not VENDOR.exists():
        d = extract()
        VENDOR.parent.mkdir(parents=True, exist_ok=True)
        VENDOR.write_text(json.dumps(d, ensure_ascii=False, indent=0))
    d = json.loads(VENDOR.read_text())
    res = {"f2": {}, "transfer": {}, "shape": {}, "live": {}}
    for st, rows in d["snull"].items():
        y = [r["kind"] == "no_answer" for r in rows]
        for arm in ("chat_plain", "chat_null"):
            if arm not in rows[0]:
                continue
            m = [r[arm] for r in rows]
            c = calibrate(st, arm, [r["id"] for r in rows], m, y)
            res["f2"][f"{st}|{arm}"] = dict(
                auroc=c.auroc,
                gap=c.gap,
                theta=c.theta,
                loo_acc=c.loo["acc"],
                loo_correct=c.loo["correct"],
                n=c.loo["n"],
                loo_abstain=f"{c.loo['abstain_correct']}/{c.loo['n_pos']}",
                loo_answer=f"{c.loo['answer_correct']}/{c.loo['n_neg']}",
                acc_default0=sum((mi > 0) == yi for mi, yi in zip(m, y)) / len(m),
            )
    for arm in ("chat_plain", "chat_null"):
        for s, t in (("DPO", "final"), ("final", "final_dwq"), ("final_dwq", "final"), ("RLVR", "final"), ("SFT", "final")):
            rs, rt = d["snull"][s], d["snull"][t]
            th, _ = fit_theta([r[arm] for r in rs], [r["kind"] == "no_answer" for r in rs])
            res["transfer"][f"{arm}|{s}->{t}"] = transfer(th, [r[arm] for r in rt], [r["kind"] == "no_answer" for r in rt])
    for arm in SHAPE_ARMS:
        res["shape"][arm] = shape_arm(d["shape"], arm)
    if d.get("live"):
        y = [r["kind"] == "no_answer" for r in d["live"]]
        for arm in ("plain", "null"):
            m = [r[arm] for r in d["live"]]
            if any(v is None for v in m):
                continue
            c = calibrate("publicai:swiss-ai/apertus-v1.5-8b", f"snull_{arm}", [r["id"] for r in d["live"]], m, y)
            res["live"][arm] = dict(
                auroc=c.auroc,
                gap=c.gap,
                theta=c.theta,
                loo_correct=c.loo["correct"],
                n=c.loo["n"],
                abstain_at_0=sum(mi > 0 and yi for mi, yi in zip(m, y)),
                kept_at_0=sum(mi <= 0 and not yi for mi, yi in zip(m, y)),
                pos_range=[min(a for a, b in zip(m, y) if b), max(a for a, b in zip(m, y) if b)],
                neg_range=[min(a for a, b in zip(m, y) if not b), max(a for a, b in zip(m, y) if not b)],
            )
    if d.get("naive"):
        res["naive"] = naive_scores(d["naive"])
    out = RESULTS / "convert" / "spike_replay.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main("--vendor" in sys.argv)
    for k, v in r["f2"].items():
        print("F2", k, {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()})
    for k, v in r["shape"].items():
        print(
            "SHAPE",
            k,
            {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != "BE_loo"},
            v["BE_loo"]["correct"],
            "/",
            v["BE_loo"]["n"],
        )
    for k, v in r["transfer"].items():
        print("T", k, v)
    print("LIVE", r["live"])
    for k, v in r.get("naive", {}).items():
        print("NAIVE", k, v)
