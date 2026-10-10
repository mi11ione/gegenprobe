"""EXPLORATORY (PREREG7, added after LOCK7): the real Apertus v1.5 8B (GGUF Q4_K_M, llama.cpp CPU, fast scorer that cleared
the D2 gate) on P6. Same v2 configuration as the registered 70B arm except θ_presence, which is fitted for this build on
P1 dev by the same rule (calibrate.fit_theta; the 30 spike items are skipped, their texts are not in the repository), as
v1's 8B θ was. Runs on CI (workflow arms-8b-p6); nothing here runs a model unless called with the real backend.

  fetch                 fetch every P1 dev and P6 PDF by URL, verified against its committed sha256
  fit                   presence margins on P1 dev -> data/p6/v2_theta_gguf.json
  run --shard i/n       P6 shard i of n (document order of data/p6/p6_docs.jsonl): rules, v1 (8B θ), cascade_v1, v2 (8B θ),
                        cascade_v2, free_guided (the v2 generation request), free_null -> results/p6/shards/p6__gguf__i_of_n.json
  merge                 -> results/p6/p6__gguf_apertus-v1.5-8b-text-q4_k_m.json (+ hypotheses7 if P6 labels exist)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from eval import arms
from eval import naive_baseline as nb
from eval.p6 import run_p6
from eval.p6 import sample as S
from eval.posthoc_r3 import to_iso_fixed
from gegenprobe import llm
from gegenprobe.convert import calibrate, cascade, lattice, pointer, rules
from gegenprobe.convert import pointer_v2 as V
from gegenprobe.paths import DATA, PDF_CACHE, RESULTS

BUILD = "gguf:apertus-v1.5-8b-text-q4_k_m"
SLUG = llm._slug(BUILD)
THETA_V1 = DATA / "convert" / "theta" / f"{SLUG}.json"
THETA_V2 = DATA / "p6" / "v2_theta_gguf.json"
SHARDS = RESULTS / "p6" / "shards"
LABEL = "EXPLORATORY (PREREG7, added after LOCK7): real 8B on P6; v2 θ_presence fitted for this build on P1 dev"
ARMS8 = ["rules", "v1", "cascade_v1", "v2", "cascade_v2", "free_guided", "free_null",
         "latest_printed_date", "latest_on_answer_typed", "always_null"]


def backend():
    from gegenprobe.gguf_fast import GGUFFast

    return GGUFFast()


def fetch() -> list[int]:
    from eval import run_arms
    from gegenprobe import net, pdftext

    run_arms.fetch("dev")
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    failed = []
    for d in run_p6.C._jsonl(S.DOCS):
        p = PDF_CACHE / f"{d['sha256']}.pdf"
        if p.exists():
            continue
        try:
            with net.open_url(d["url"], timeout=30, tries=2) as r:
                b = r.read()
            if pdftext.sha256_bytes(b) != d["sha256"]:
                raise ValueError("sha256 changed at source")
            p.write_bytes(b)
        except Exception as e:  # a changed or vanished source is reported, never silently replaced
            failed.append(d["doc_id"])
            print("FETCH-FAIL", d["doc_id"], type(e).__name__, str(e)[:120], flush=True)
    print("P6 fetch failed:", failed)
    return failed


def fit(be=None) -> dict:
    from eval import run_arms

    os.environ["GP_WORKERS"] = "1"
    run_arms._no_spikes()
    run_arms._reachable_only()
    be = be or backend()
    docs = arms.load_split("dev")
    m, y, ids = [], [], []
    for d in docs:
        if not V.options(d["pages"])[0]:
            continue  # no printed date: nothing to gate, no call (as in v1's fit)
        p = V.presence(be, d["pages"], arms._lang(d))
        m.append(p["m_absent"])
        y.append(d["label"]["answer_date"] is None)
        ids.append(d["doc_id"])
    c = calibrate.calibrate(be.build, "answer_present", ids, m, y)
    out = dict(label=LABEL, build=be.build, theta_presence=c.theta, calibration=c.__dict__)
    THETA_V2.write_text(json.dumps(out, indent=1))
    print("8B θ_presence", c.theta, "auroc", c.auroc, "loo", c.loo["acc"])
    return out


def run_doc(be, d: dict, cfg: V.Config, theta_v1: float) -> dict:
    pages, lg, seed = d["pages"], d["lg"], d["doc_id"] % 100000
    dd = sorted({c["value"] for c in lattice.dates(pages)})
    r = rules.answer_date(pages, d["image_only"])
    rv = r.get("value") if r["status"] == "value" else None
    latest = max(dd) if dd else None
    anch = rules.anchors(pages)
    p1 = pointer.answer_date(be, pages, lg, theta_v1, anchors=anch)
    c1 = cascade.answer_date(dict(pages=pages, lang=lg, image_only=d["image_only"]), be, theta_v1, use_metadata=False)
    v2 = V.answer_date(be, pages, lg, cfg, anchors=anch, seed=seed)
    g = V.generate_then_point(be, pages, lg, seed=seed, max_tokens=cfg.gen_max_tokens)
    n = nb.run_doc(be, pages, lg, "null", seed=seed)
    fixed, how = to_iso_fixed(n["parsed"].get("antwort_datum"))
    return dict(
        doc_id=d["doc_id"], body=d["body"], cell=d["cell"], dtype=d["dtype"], lang=lg, doc_dates=dd,
        rules=dict(status=r["status"], value=rv, rule=r["rule"]),
        latest_printed_date=dict(value=latest), latest_on_answer_typed=dict(value=latest if d["dtype"] == "answer" else None),
        always_null=dict(value=None),
        v1=dict(value=p1.value, margin=p1.margin, n_cands=len(p1.candidates)),
        cascade_v1=dict(value=c1.get("value"), route=c1["route"]),
        v2=dict(value=v2.value, stage=v2.stage, presence_margin=v2.m_absent, calls=v2.calls),
        cascade_v2=dict(value=rv, route="rule") if r["status"] in ("value", "null")
        else dict(value=v2.value, route="apertus" if v2.stage != "no_dates" else "rule"),
        free_guided=dict(value=g["iso"], printed=g["printed"]),
        free_null=dict(value=fixed, how=how),
    )


def run(shard: str, be=None) -> Path:
    os.environ["GP_WORKERS"] = "1"
    i, n = map(int, shard.split("/"))
    order = [d["doc_id"] for d in run_p6.C._jsonl(S.DOCS)]
    mine = set(order[i::n])
    docs = [d for d in run_p6.C._jsonl(S.DOCS) if d["doc_id"] in mine]
    have = [d for d in docs if (PDF_CACHE / f"{d['sha256']}.pdf").exists()]
    miss = sorted(d["doc_id"] for d in docs if d not in have)
    from gegenprobe import pdftext

    loaded = []
    for d in have:
        t = pdftext.extract(d["sha256"])
        loaded.append(dict(d, pages=t["pages"], image_only=t["image_only"], lg=run_p6.lang_of(d)))
    be = be or backend()
    th2 = json.loads(THETA_V2.read_text())["theta_presence"]
    c = json.loads(run_p6.CONFIG.read_text())
    cfg = V.Config(gate=c["gate"], theta_presence=th2, pick=c["pick"], gen_max_tokens=c["gen_max_tokens"], name="v2-8b")
    th1 = json.loads(THETA_V1.read_text())["answer_date"]["theta"]
    rows = [run_doc(be, d, cfg, th1) for d in loaded]
    tag = shard.replace("/", "_of_")
    SHARDS.mkdir(parents=True, exist_ok=True)
    dst = SHARDS / f"p6__gguf__{tag}.json"
    dst.write_text(json.dumps(dict(label=LABEL, build=BUILD, shard=tag, assigned=sorted(mine), unreachable=miss,
                                   theta_v1=th1, theta_presence=th2, per_doc=rows), indent=1, ensure_ascii=False))
    print(dst, len(rows), "unreachable:", miss, flush=True)
    return dst


def merge() -> dict:
    parts = [json.loads(p.read_text()) for p in sorted(SHARDS.glob("p6__gguf__*.json"))]
    if not parts:
        raise SystemExit(f"no shard files in {SHARDS}")
    order = {d["doc_id"]: k for k, d in enumerate(run_p6.C._jsonl(S.DOCS))}
    per_doc = sorted({r["doc_id"]: r for p in parts for r in p["per_doc"]}.values(), key=lambda r: order[r["doc_id"]])
    res = dict(split="p6", build=BUILD, label=LABEL, theta_v1=parts[0]["theta_v1"], theta_presence=parts[0]["theta_presence"],
               n_docs=len(per_doc), not_scored=sorted(set(order) - {r["doc_id"] for r in per_doc}),
               model_file=dict(llm.GGUF_PINS["apertus-v1.5-8b-text-q4_k_m"], scorer="gguf_fast"), per_doc=per_doc)
    out = RESULTS / "p6" / f"p6__{SLUG}.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(out, len(per_doc), "not scored:", res["not_scored"])
    if S.LABELS.exists():
        from eval.p6 import hypotheses7

        labels = {json.loads(x)["doc_id"] for x in open(S.LABELS)}
        sub = dict(res, per_doc=[r for r in per_doc if r["doc_id"] in labels])
        tmp = RESULTS / "p6" / f"p6__{SLUG}__scored.json"
        tmp.write_text(json.dumps(sub, ensure_ascii=False))
        h = hypotheses7.main(SLUG, res_path=tmp)
        tmp.unlink()
        print({a: v["exact"] for a, v in h["arms"].items()})
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "fit", "run", "merge"])
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args()
    {"fetch": lambda: fetch(), "fit": lambda: fit(), "run": lambda: run(a.shard), "merge": lambda: merge()}[a.cmd]()
