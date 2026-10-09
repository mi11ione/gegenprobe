"""POST-HOC analyses (not pre-registered; labelled as such in every output). Replays cached pointer scores, frozen code paths.

  curve     H4-triggered precision/coverage curve: cascade outcome at θ over a grid (frozen θ marked), all cells and FR/IT
  errors    anatomy of every cascade error (doc, cell, gold, predicted value, route, the printed context of the chosen date)
  ocr_it    deviation D1: the OCR cell re-scored with the Italian prompt (θ unchanged) -> needs the backend (gateway)

    python -m eval.posthoc curve|errors           (offline)
    python -m eval.posthoc ocr_it --backend gateway:swiss-ai/apertus-v1.5-8b:2a-posthoc:0.5
"""
from __future__ import annotations

import argparse
import collections
import json
import os

from eval import arms
from eval.score import outcome, summarise
from gegenprobe.convert import lattice, pointer, rules
from gegenprobe.paths import RESULTS

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
OUT = RESULTS / "eval" / "posthoc"


def _docs():
    return {d["doc_id"]: d for d in arms.load_split("heldout")}


def _pointer_scores(be, docs):
    """doc_id -> PointerResult at θ = +inf (argmax always), replayed from the cache."""
    out = {}
    for i, d in docs.items():
        out[i] = pointer.answer_date(be, d["pages"], arms._lang(d), float("inf"), anchors=rules.anchors(d["pages"]))
    return out


def curve(be) -> dict:
    res = json.loads((RESULTS / "eval" / f"heldout__{BUILD}.json").read_text())
    rows = {r["doc_id"]: r for r in res["per_doc"]}
    docs = _docs()
    ps = _pointer_scores(be, docs)
    grid = sorted({-40, -30, -20, -10, -5, 0, 2.5, 5, 7.5, 10, res["theta"], 12.5, 15, 20, 30, 40})
    table = []
    for th in grid:
        rs, frit = [], []
        for i, r in rows.items():
            st = r["rules"]["status"]
            if st == "value":
                pred, route = r["rules"]["value"], "rule"
            elif st == "null":
                pred, route = None, "rule"
            else:
                p = ps[i]
                pred = None if (not p.candidates or p.margin > th) else max(p.candidates, key=lambda c: c[1])[0]
                route = "apertus"
            row = dict(cell=r["cell"], gold=r["gold"], lenient=r["lenient"], doc_dates=r["doc_dates"], pred=pred, route=route)
            rs.append(row)
            if r["cell"][:2] in ("fr", "it") and route == "apertus" and pred is not None:
                frit.append(outcome(pred, r["gold"], set(r["doc_dates"]), r["lenient"], True))
        s = summarise(rs, True)["ALL"]
        table.append(dict(theta=th, frozen=abs(th - res["theta"]) < 1e-6, exact=s["exact"], correct=s["correct"],
                          false_null=s["false_null"], misattributed=s["misattributed"], invented_on_null=s["invented_on_null"],
                          apertus_values_fr_it=len(frit), apertus_wrong_fr_it=sum(o != "correct" for o in frit)))
    out = dict(label="POST-HOC (not pre-registered): H4-triggered precision/coverage curve over θ", build=BUILD, table=table)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "theta_curve.json").write_text(json.dumps(out, indent=1))
    return out


def errors(be) -> dict:
    res = json.loads((RESULTS / "eval" / f"heldout__{BUILD}.json").read_text())
    docs = _docs()
    rows = []
    for r in res["per_doc"]:
        c = r["cascade"]
        o = outcome(c.get("value"), r["gold"], set(r["doc_dates"]), r["lenient"], True)
        if o in ("correct", "correct_null"):
            continue
        ctx = None
        if c.get("value"):
            occ = [x for x in lattice.dates(docs[r["doc_id"]]["pages"]) if x["value"] == c["value"]]
            ctx = occ[0]["line"][:160] if occ else None
        rows.append(dict(doc_id=r["doc_id"], cell=r["cell"], gold=r["gold"], pred=c.get("value"), route=c.get("route"),
                         rule=c.get("rule"), margin=c.get("margin"), outcome=o, chosen_line=ctx))
    kinds = collections.Counter((x["outcome"], x["route"], "gold_null" if x["gold"] is None else "gold_value") for x in rows)
    out = dict(label="POST-HOC (not pre-registered): anatomy of cascade errors", n=len(rows),
               kinds={" | ".join(k): v for k, v in kinds.items()}, rows=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cascade_errors.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def ocr_it(be) -> dict:
    res = json.loads((RESULTS / "eval" / f"heldout__{BUILD}.json").read_text())
    theta = res["theta"]
    docs = {i: d for i, d in _docs().items() if d["cell"] == "ocr_ti"}
    rows = {"pointer_de_frozen": [], "pointer_it": [], "cascade_de_frozen": [], "cascade_it": []}
    for r in res["per_doc"]:
        if r["cell"] != "ocr_ti":
            continue
        d = docs[r["doc_id"]]
        base = dict(cell="ocr_ti", gold=r["gold"], lenient=r["lenient"], doc_dates=r["doc_dates"])
        p_it = pointer.answer_date(be, d["pages"], "it", theta, anchors=rules.anchors(d["pages"]))
        rows["pointer_de_frozen"].append(dict(base, pred=r["pointer"]["value"], route="apertus"))
        rows["pointer_it"].append(dict(base, pred=p_it.value, route="apertus"))
        rows["cascade_de_frozen"].append(dict(base, pred=r["cascade"].get("value"), route=r["cascade"].get("route")))
        st = r["rules"]["status"]
        c_it = r["rules"]["value"] if st == "value" else (None if st == "null" else p_it.value)
        rows["cascade_it"].append(dict(base, pred=c_it, route="rule" if st != "abstain" else "apertus"))
    out = dict(label="POST-HOC (deviation D1): OCR cell with the Italian prompt, θ unchanged", theta=theta,
               arms={k: summarise(v, True)["ALL"] for k, v in rows.items()})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ocr_it_prompt.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["curve", "errors", "ocr_it"])
    ap.add_argument("--backend", default="gateway:swiss-ai/apertus-v1.5-8b:2a-posthoc:0.5")
    a = ap.parse_args()
    if a.cmd != "ocr_it":
        os.environ["GP_OFFLINE"] = "1"
    be = arms.backend(a.backend)
    be.offline = os.environ.get("GP_OFFLINE") == "1"
    r = {"curve": curve, "errors": errors, "ocr_it": ocr_it}[a.cmd](be)
    print(json.dumps({k: v for k, v in r.items() if k not in ("rows",)}, indent=1)[:4000])
