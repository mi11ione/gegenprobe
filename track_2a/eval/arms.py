"""Evaluation arms on the gold set (the parent/integrator runs the model; this module only orchestrates and scores).

  rules     frozen rules only; abstain → null                              (no model)
  pointer   closed-set pointer on every document, per-build θ             (Apertus, forced choice)
  cascade   rules, then the pointer on the residue only                    (Apertus on the residue; model share N/M)
  naive     free-generation JSON, plain and null-allowed prompts            (the strawman; Apertus, generation)

Commands
  fit  --backend B          score the DEV labels with the pointer, fit θ per build × prompt, write data/convert/theta/<build>.json
  run  --backend B --split heldout|dev [--arms rules,pointer,cascade,naive]
                            write results/eval/<split>__<build>.json (per-cell scoreboard with Wilson CIs + per-doc rows)
Backends: gateway:<model>:<tag>:<cap_usd> (development, Roman's budget gateway) | openai (LLM_BASE_URL/LLM_API_KEY/LLM_NAME) |
          gguf (pinned Q4_K_M, llama-cpp-python, CPU) | none (rules only). GP_OFFLINE=1 replays the hash cache only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from eval import naive_baseline
from eval.score import summarise
from gegenprobe import llm, pdftext
from gegenprobe.convert import calibrate, cascade, lattice, pointer, rules
from gegenprobe.paths import DATA, RESULTS

SPIKES = Path(os.path.expanduser("~/Desktop/hackapertus/spikes"))
THETA_DIR = DATA / "convert" / "theta"


def backend(spec: str):
    if spec == "none":
        return None
    if spec.startswith("gateway:"):
        _, model, tag, cap = spec.split(":", 3) if spec.count(":") >= 3 else (*spec.split(":", 1), "2a-convert", "1.0")
        return llm.Gateway(model, tag=tag, cap_usd=float(cap), build=f"publicai:{model}")
    if spec == "openai":
        return llm.OpenAICompat()
    if spec == "gguf":
        return llm.GGUF()
    raise ValueError(spec)


def load_split(split: str) -> list[dict]:
    """Labelled documents with page texts. Dev includes the 30 spike items (texts from the local spikes folder)."""
    labels = {(r["source"], r["doc_id"]): r for r in map(json.loads, open(DATA / "gold" / f"{split}_labels.jsonl"))}
    docs = {d["doc_id"]: d for d in map(json.loads, open(DATA / "gold" / f"{split}_docs.jsonl"))}
    spike = {int(x["doc_id"]): x for x in json.load(open(SPIKES / "round8/ptr_items.json"))} if split == "dev" else {}
    out = []
    for (src, did), lab in labels.items():
        if src.startswith("spike"):
            x = spike.get(did)
            if x is None:
                continue
            out.append(
                dict(
                    doc_id=did,
                    cell="spike_be_zh_bs",
                    lang="de",
                    pages=x["text"].split("\x0c"),
                    image_only=False,
                    affair_type="Interpellation",
                    label=lab,
                )
            )
        else:
            d = docs[did]
            t = pdftext.extract(d["sha256"])
            out.append(
                dict(
                    doc_id=did,
                    cell=d["cell"],
                    lang=d.get("lang") or {"it": "it", "fr": "fr"}.get(d["cell"][:2], "de"),
                    pages=t["pages"],
                    image_only=t["image_only"],
                    affair_type=d.get("affair_type"),
                    body=d["body"],
                    sha256=d["sha256"],
                    label=lab,
                )
            )
    return out


def _lang(doc: dict) -> str:
    lg = doc.get("lang")
    if lg in ("de", "fr", "it"):
        return lg
    return {"fr": "fr", "it": "it", "oc": "it"}.get(doc["cell"][:2], "de")


REC_THETA = 0.0  # recommendation pointer: no dev labels to fit on (2 non-null on dev), θ = 0 declared in PREREG (exploratory)
REC_VALUES = {"accept", "reject", "convert", "partial"}


def score_rec(rows: list[dict]) -> dict:
    """Exact enum match; gold none/not_applicable/None form the null class (a null prediction is correct there)."""
    from gegenprobe.stats import wilson

    n = len(rows)
    ok = sum((r["pred"] == r["gold"]) if r["gold"] in REC_VALUES else (r["pred"] is None) for r in rows)
    on_null = [r for r in rows if r["gold"] not in REC_VALUES]
    inv = sum(r["pred"] is not None for r in on_null)
    vals = [r for r in rows if r["gold"] in REC_VALUES]
    return dict(n=n, correct=ok, correct_ci=list(wilson(ok, n)), n_gold_value=len(vals),
                correct_on_value=sum(r["pred"] == r["gold"] for r in vals), n_gold_null=len(on_null), invented_on_null=inv,
                invented_on_null_ci=list(wilson(inv, len(on_null))))


def theta_path(build: str) -> Path:
    return THETA_DIR / f"{llm._slug(build)}.json"


def fit(be, prompt_variant: str = "") -> dict:
    from concurrent.futures import ThreadPoolExecutor

    docs = load_split("dev")

    def one(d):
        return pointer.answer_date(be, d["pages"], _lang(d), theta=0.0, variant=prompt_variant)

    workers = int(os.environ.get("GP_WORKERS", "3"))  # low concurrency: Public AI answers 429 under load
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, docs))
    ids = [d["doc_id"] for d in docs]
    m = [p.margin if p.candidates else 1e9 for p in res]
    y = [d["label"]["answer_date"] is None for d in docs]
    keep = [i for i, v in enumerate(m) if v != 1e9]  # documents without any date cannot inform θ
    c = calibrate.calibrate(
        be.build, prompt_variant or "answer_date", [ids[i] for i in keep], [m[i] for i in keep], [y[i] for i in keep]
    )
    out = dict(build=be.build, served_fingerprints=sorted(getattr(be, "served", set())), answer_date=c.__dict__)
    THETA_DIR.mkdir(parents=True, exist_ok=True)
    theta_path(be.build).write_text(json.dumps(out, indent=1))
    return out


def run(be, split: str, arms: list[str], theta: float | None) -> dict:
    docs = load_split(split)
    rows = {a: [] for a in arms if a != "recommendation"}
    rec_rows: dict[str, list] = {}
    per_doc = []
    for d in docs:
        lab, pages = d["label"], d["pages"]
        dd = [c["value"] for c in lattice.dates(pages)]
        base = dict(cell=d["cell"], gold=lab["answer_date"], lenient=lab.get("answer_date_lenient") or [], doc_dates=dd)
        rec = dict(doc_id=d["doc_id"], cell=d["cell"], gold=lab["answer_date"], lenient=base["lenient"], doc_dates=dd)
        if "rules" in arms:
            r = rules.answer_date(pages, d["image_only"])
            rows["rules"].append(dict(base, pred=r.get("value") if r["status"] == "value" else None, route="rule"))
            rec["rules"] = dict(status=r["status"], value=r.get("value"), rule=r["rule"], route="rule")
        if be is not None and theta is not None and "pointer" in arms:
            p = pointer.answer_date(be, pages, _lang(d), theta, anchors=rules.anchors(pages))
            rows["pointer"].append(dict(base, pred=p.value, route="apertus"))
            rec["pointer"] = dict(value=p.value, margin=p.margin, n_cands=len(p.candidates), truncated=p.truncated,
                                  route="apertus")
        if be is not None and theta is not None and "cascade" in arms:
            c = cascade.answer_date(dict(pages=pages, lang=_lang(d), image_only=d["image_only"]), be, theta, use_metadata=False)
            rows["cascade"].append(dict(base, pred=c.get("value"), route=c["route"]))
            rec["cascade"] = {k: c.get(k) for k in ("value", "route", "null_reason", "margin", "rule")}
        if be is not None and "naive" in arms:
            for arm in ("plain", "null"):
                g = naive_baseline.run_doc(be, pages, _lang(d), arm, seed=d["doc_id"] % 100000)
                rows.setdefault(f"naive_{arm}", []).append(
                    dict(
                        base,
                        pred=None if (g["date"] or "").startswith("unparseable") else g["date"],
                        route="apertus",
                        receipt_ok=g["receipt_ok"],
                    )
                )
                rec[f"naive_{arm}"] = dict(date=g["date"], receipt_ok=g["receipt_ok"], gen=g["gen"][:400], route="apertus")
        if "recommendation" in arms:
            gold_rec = lab.get("recommendation")
            rr = rules.recommendation(pages, d.get("affair_type"))
            r_val = rr.get("value") if rr["status"] == "value" else None
            rec["rec_gold"] = gold_rec
            rec["rec_rules"] = dict(status=rr["status"], value=r_val, rule=rr["rule"])
            rec_rows.setdefault("rec_rules", []).append(dict(cell=d["cell"], gold=gold_rec, pred=r_val))
            if be is not None:
                pr = pointer.recommendation(be, pages, _lang(d), REC_THETA)
                rec["rec_pointer"] = dict(value=pr.value, margin=pr.margin)
                rec_rows.setdefault("rec_pointer", []).append(dict(cell=d["cell"], gold=gold_rec, pred=pr.value))
                c_val = r_val if rr["status"] == "value" else (None if rr["status"] == "null" else pr.value)
                rec_rows.setdefault("rec_cascade", []).append(dict(cell=d["cell"], gold=gold_rec, pred=c_val,
                                                                   route="rule" if rr["status"] != "abstain" else "apertus"))
        per_doc.append(rec)
    res = dict(
        split=split,
        build=getattr(be, "build", "none"),
        theta=theta,
        n_docs=len(docs),
        served_fingerprints=sorted(getattr(be, "served", set())) if be else [],
        arms={a: dict(strict=summarise(r, True), lenient=summarise(r, False)) for a, r in rows.items() if r},
        recommendation={a: score_rec(r) for a, r in rec_rows.items()},
        per_doc=per_doc,
    )
    out = RESULTS / "eval" / f"{split}__{llm._slug(res['build'])}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "run"])
    ap.add_argument("--backend", default="none")
    ap.add_argument("--split", default="heldout")
    ap.add_argument("--arms", default="rules,pointer,cascade,naive,recommendation")
    a = ap.parse_args()
    be = backend(a.backend)
    if a.cmd == "fit":
        print(json.dumps(fit(be), indent=1)[:2000])
        return
    theta = None
    if be is not None and theta_path(be.build).exists():
        theta = json.loads(theta_path(be.build).read_text())["answer_date"]["theta"]
    r = run(be, a.split, a.arms.split(","), theta)
    for arm, v in r["arms"].items():
        s = v["strict"]["ALL"]
        print(arm, {k: s[k] for k in ("n", "exact", "correct", "correct_null", "false_null", "misattributed", "fabricated")})


if __name__ == "__main__":
    main()
