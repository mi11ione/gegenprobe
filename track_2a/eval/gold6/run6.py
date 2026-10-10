"""P5 runner: every arm on a split (p5dev | p5), scored against the merged labels when they exist.

    python -m eval.gold6.run6 <split> --backend none                                            arms R, B (no model)
    python -m eval.gold6.run6 <split> --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p5-<x>:<cap> adds RA and G
Arms
  R    rules only (src/gegenprobe/qa, no model): the residue stays a typed null
  RA   R + the Apertus closed-set pointer on the residue (every suggestion accepted), θ from the dev fit (primary)
  RA0  as RA with the pairing pointer at θ_pair = 0 (secondary arm, registered in PREREG6)
  G    free-generation Apertus, null allowed (eval/gold6/freegen6.py): values located in the documents by their quotes
  B*   trivial baselines (eval/gold6/baselines6.py)
Writes results/eval6/<split>__<build>.json (views, records, pointer calls, scores). Document text is never written.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from eval.arms import backend as make_backend
from eval.gold6 import baselines6, common6 as C, freegen6
from eval.gold6.annotate6 import _rows
from eval.gold6.score6 import gold_view, score
from gegenprobe import llm
from gegenprobe.paths import RESULTS
from gegenprobe.qa import extract as X

OUT = RESULTS / "eval6"


def labels(split: str) -> dict:
    p = C.GOLD6 / f"{split}_labels.jsonl"
    return {r["affair_id"]: gold_view(r) for r in map(json.loads, open(p))} if p.exists() else {}


def recheck(rec: dict, tx: dict, ids: dict) -> dict:
    """Span re-check (validate.spans.recheck) of every value in the schema records against the cached page texts."""
    from types import SimpleNamespace

    from gegenprobe.validate.spans import recheck as rc

    pages = {ids.get(role): tx[role] for role in tx}
    vals = []
    for it in rec["qa_items"]:
        vals += [it["question"], it["answer"]]
    vals += [a["name"] for a in rec["actors"]] + [rec["recommendation"], rec["reasoning"]]
    ok = bad = 0
    for v in vals:
        if v.get("kind") != "value" or v.get("page") is None:
            continue
        r = rc(SimpleNamespace(**{k: v.get(k) for k in ("value", "basis", "route", "page", "char_start", "char_end", "quote")}),
               pages[v["doc"]])
        ok += r.ok
        bad += not r.ok
    return dict(ok=ok, failed=bad)


def slim(obj):
    """Committed results keep no bulk document text: every quote/value/context string longer than 80 characters is cut to
    80 characters plus the sha256 of the full string (the full records are rebuilt from the cached pages by re-running)."""
    import hashlib

    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("quote", "value", "context") and isinstance(v, str) and len(v) > 80:
                out[k] = v[:80] + "…"
                out[k + "_sha256"] = hashlib.sha256(v.encode()).hexdigest()
            else:
                out[k] = slim(v)
        return out
    if isinstance(obj, list):
        return [slim(x) for x in obj]
    return obj


def run(split: str, spec: str, thetas: dict | None = None, arms=("R", "RA", "RA0", "G", "B"), write: bool = True) -> dict:
    be = make_backend(spec) if spec != "none" else None
    rows = _rows(split)

    def one(r):
        tx = C.texts(r)
        ids = {d["role"]: f"opd:{d['doc_id']}" for d in r["docs"]}
        lang = r.get("lang") or "de"
        out = dict(affair_id=r["affair_id"], body=r["body"], lang=lang, affair_type=r["affair_type"])
        R = X.extract(tx.get("question"), tx.get("answer"), lang, None, thetas, ids.get("question", "q"),
                      ids.get("answer", "a"))
        out["R"] = R
        R["recheck"] = recheck(R["records"], tx, ids)
        if be is not None and "RA" in arms:
            out["RA"] = X.extract(tx.get("question"), tx.get("answer"), lang, be, thetas, ids.get("question", "q"),
                                  ids.get("answer", "a"))
            out["RA"]["recheck"] = recheck(out["RA"]["records"], tx, ids)
        if be is not None and "RA0" in arms:
            # SECONDARY (registered after the dev fit): the pairing pointer at θ_pair = 0; the same cached scores as RA
            out["RA0"] = X.extract(tx.get("question"), tx.get("answer"), lang, be, dict(thetas or {}, pair=0.0),
                                   ids.get("question", "q"), ids.get("answer", "a"))
            out["RA0"]["recheck"] = recheck(out["RA0"]["records"], tx, ids)
        if be is not None and "G" in arms:
            out["G"] = freegen6.run(be, tx, lang)
        if "B" in arms:
            out["B"] = baselines6.all_baselines(tx, R["view"])
        return out

    workers = 4 if be is not None else 8
    with ThreadPoolExecutor(workers) as ex:
        per = list(ex.map(one, rows))
    res = dict(split=split, build=getattr(be, "build", "none"), thetas=dict(X.THETAS, **(thetas or {})), n=len(per),
               served_fingerprints=sorted(getattr(be, "served", set())) if be else [], per_affair=per)
    gold = labels(split)
    if gold:
        sc = {}
        for arm in ("R", "RA", "RA0", "G"):
            if all(arm in p for p in per):
                sc[arm] = score({p["affair_id"]: p[arm]["view"] for p in per}, gold)
        if all("B" in p for p in per):
            for b in per[0]["B"]:
                sc[b] = score({p["affair_id"]: p["B"][b] for p in per}, gold)
        res["scores"] = sc
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{split}__{llm._slug(res['build'])}.json").write_text(json.dumps(slim(res), indent=1, ensure_ascii=False))
    return res


def summary(res: dict) -> str:
    lines = []
    for arm, s in (res.get("scores") or {}).items():
        def f(x):
            return f"{x['k']}/{x['n']}"
        lines.append(f"{arm:14s} Q rec {f(s['questions']['recall'])} prec {f(s['questions']['precision'])} | "
                     f"QA rec {f(s['qa_pairs']['recall'])} prec {f(s['qa_pairs']['precision'])} "
                     f"fs {s['qa_pairs']['false_span_on_gold_null']} | "
                     f"sub {f(s['submitter'])} co R {f(s['co_signatories']['recall'])} P {f(s['co_signatories']['precision'])} | "
                     f"rec {f(s['recommendation'])} | reas {f(s['reasoning']['match'])} "
                     f"iou {s['reasoning']['mean_iou'] or 0:.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--backend", default="none")
    ap.add_argument("--arms", default="R,RA,RA0,G,B")
    a = ap.parse_args()
    r = run(a.split, a.backend, arms=tuple(a.arms.split(",")))
    print(summary(r))
