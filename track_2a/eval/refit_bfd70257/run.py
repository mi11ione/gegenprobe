"""EXPLORATORY deployment refit for the Public AI build bfd70257 (eval/refit_bfd70257/NOTE.md). No LOCK-listed file is
changed: the frozen eval.arms.fit / eval.arms.run, the P2 scorer and the post hoc baseline method are called unchanged,
with their data and output directories pointed at copies.

    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.run old97      (no model call: the old build on the same 97)
    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.run fit        -> data/deploy/theta_bfd70257.json
    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.run p2         -> results/refit_bfd70257/p2_newbuild.json
    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.run p1         -> results/refit_bfd70257/p1_heldout_newbuild.json
    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.run p7old      (no call: P7's rule on the committed dev features)
    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.run p7dev      -> data/deploy/p7_theta_bfd70257.json (P7 dev only)
    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.run partial    (no call: dev documents both builds answered)
    PYTHONPATH=src:. .venv/bin/python -m eval.refit_bfd70257.run audit      the new build's model cache: labels, fingerprints

Route: the budget gateway, model name `swiss-ai/apertus-v1.5-8b` exactly as every registered run sent it (one plain user
message; the prefill only to that name). A response is accepted only with label `swiss-ai/Apertus-v1.5-70B` and
fingerprint `vllm-0.1.dev1+g54b4292c2-tp2-bfd70257` (convert/deploy_theta.accept_only); anything else stops the run.
Responses are cached under the build key `publicai:swiss-ai/apertus-v1.5-8b@bfd70257`. Tag 2a-refit, cap USD 3.00.
`p2` and `p1` refuse to run before the θ file exists (test sets are touched only after θ is written).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gegenprobe.compliance import fetchguard

fetchguard.ensure()

from eval import arms  # noqa: E402
from gegenprobe import llm  # noqa: E402
from gegenprobe.convert import deploy_theta  # noqa: E402
from gegenprobe.paths import DATA, RESULTS, ROOT  # noqa: E402

REQUESTED = "swiss-ai/apertus-v1.5-8b"
ROUTE_BUILD = f"publicai:{REQUESTED}"
NEW_LABEL = "swiss-ai/Apertus-v1.5-70B"
NEW_FP = "vllm-0.1.dev1+g54b4292c2-tp2-bfd70257"
OLD_FP = "vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840"
NEW_BUILD = f"{ROUTE_BUILD}@bfd70257"
TAG, CAP = "2a-refit", 3.0
THETA_FILE = Path(os.environ.get("GP_REFIT_THETA") or DATA / "deploy" / "theta_bfd70257.json")
OUT = Path(os.environ.get("GP_REFIT_OUT") or RESULTS / "refit_bfd70257")
NOTE = "eval/refit_bfd70257/NOTE.md"
LABEL = ("EXPLORATORY (deployment refit after the 12 Oct 2026 Public AI build switch; eval/refit_bfd70257/NOTE.md): "
         "never replaces a registered result")
REGISTERED_THETA = DATA / "convert" / "theta" / "publicai_swiss-ai_apertus-v1.5-8b.json"
LEDGER = Path(os.path.expanduser("~/.config/hackapertus/ledger.jsonl"))


def spent(tag: str = TAG) -> float:
    """USD booked under the tag in the gateway's ledger (the ledger, never the key file)."""
    if not LEDGER.exists():
        return 0.0
    return sum(r["usd"] for r in map(json.loads, LEDGER.read_text().splitlines()) if r.get("tag") == tag)


def backend():
    be = llm.Gateway(REQUESTED, tag=TAG, cap_usd=CAP, build=NEW_BUILD)
    return deploy_theta.accept_only(be, NEW_LABEL, [NEW_FP], REQUESTED)


def _no_spikes() -> Path:
    d = Path(tempfile.mkdtemp(prefix="refit_nospikes_")) / "round8"
    d.mkdir(parents=True)
    (d / "ptr_items.json").write_text("[]")
    return d.parent


def _fit_compact(a: dict) -> dict:
    return dict(theta=a["theta"], loo=[a["loo"]["correct"], a["loo"]["n"]], loo_acc=a["loo"]["acc"],
                loo_wilson95=a["loo"]["wilson95"], auroc=a["auroc"], acc_in_sample=a["acc_in_sample"], n_pos=a["n_pos"],
                n_neg=a["n_neg"], gap=a.get("gap"))


def old97() -> dict:
    """The registered build's fit on the same 97 committed dev documents, replayed from the committed cache (no call)."""
    saved = arms.SPIKES, arms.THETA_DIR
    arms.SPIKES, arms.THETA_DIR = _no_spikes(), Path(tempfile.mkdtemp(prefix="refit_old97_"))
    be = llm.OpenAICompat(base_url="http://offline.invalid", model=REQUESTED, build=ROUTE_BUILD, cache_readonly=True)
    be.offline = True  # replay only: a cache miss raises CacheMiss, nothing goes to the network
    try:
        return _fit_compact(arms.fit(be)["answer_date"])
    finally:
        arms.SPIKES, arms.THETA_DIR = saved


def audit(build: str = NEW_BUILD) -> dict:
    """Every response cached under the new build key: (label, fingerprint) counts. Must be only (NEW_LABEL, NEW_FP)."""
    d = llm.ModelCache(build).dir
    pairs: dict[str, int] = {}
    n = 0
    for p in sorted(d.rglob("*.json")) if d.exists() else []:
        r = json.loads(p.read_text()).get("resp") or {}
        k = f"{r.get('model')} | {r.get('system_fingerprint')}"
        pairs[k] = pairs.get(k, 0) + 1
        n += 1
    ok = set(pairs) <= {f"{NEW_LABEL} | {NEW_FP}"}
    return dict(cache_dir=str(d.relative_to(ROOT)), responses=n, label_fingerprint_pairs=pairs, only_new_build=ok)


def _require_clean(be) -> None:
    if set(be.served) - {NEW_FP}:
        raise SystemExit(f"served fingerprints {sorted(be.served)} include another build")
    a = audit()
    if not a["only_new_build"]:
        raise SystemExit(f"the new build's cache holds other builds' responses: {a['label_fingerprint_pairs']}")


def fit() -> dict:
    t0, usd0 = time.time(), spent()
    be = backend()
    saved = arms.SPIKES, arms.THETA_DIR
    tmp = Path(tempfile.mkdtemp(prefix="refit_theta_"))
    arms.SPIKES, arms.THETA_DIR = _no_spikes(), tmp
    try:
        out = arms.fit(be)  # frozen, unchanged: pointer at θ = 0 on dev, calibrate.calibrate
    finally:
        arms.SPIKES, arms.THETA_DIR = saved
    _require_clean(be)
    reg = json.loads(REGISTERED_THETA.read_text())["answer_date"]
    a = out["answer_date"]
    doc = dict(
        label=LABEL,
        note=NOTE,
        written=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        build=NEW_BUILD,
        route_build=ROUTE_BUILD,
        requested_model=REQUESTED,
        served_label=NEW_LABEL,
        served_fingerprints=[NEW_FP],
        served_fingerprints_live=sorted(be.served),
        answer_date=a,
        dev=dict(split="P1 dev: the 97 committed dev documents (data/gold/dev_docs.jsonl, dev_labels.jsonl); the 30 "
                 "spike items left out (no texts in the repository), as docs/runbook.md GP_SPIKES_DIR=none and P1 D3",
                 n_docs=97, n_fitted=a["n_pos"] + a["n_neg"]),
        rule="eval.arms.fit unchanged: closed-set pointer (prompt answer_date) at θ = 0 on every dev document; "
             "calibrate.calibrate: abstain iff margin > θ, θ = midpoint of the widest contiguous accuracy-optimal "
             "interval; leave-one-out accuracy and AUROC reported",
        compare=dict(
            this_fit=_fit_compact(a),
            registered_build_same_97_docs=old97(),
            registered_fit_127_docs=dict(_fit_compact(reg), file=str(REGISTERED_THETA.relative_to(ROOT)),
                                         fingerprint=OLD_FP)),
        relabel=dict(be.relabel),
        cost=dict(tag=TAG, usd=round(spent() - usd0, 6), wall_s=round(time.time() - t0, 1)),
    )
    THETA_FILE.parent.mkdir(parents=True, exist_ok=True)
    THETA_FILE.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return doc


# ------------------------------------------------------------------------------------------------ held-out (after θ)
def _theta() -> float:
    if not THETA_FILE.exists():
        raise SystemExit(f"{THETA_FILE} missing: run `fit` first (held-out documents are scored only after θ is written)")
    t = json.loads(THETA_FILE.read_text())
    if t["build"] != NEW_BUILD or t["served_fingerprints"] != [NEW_FP]:
        raise SystemExit(f"{THETA_FILE} is not the θ file of {NEW_BUILD}")
    return float(t["answer_date"]["theta"])


def _warm(be, docs: list[dict], theta: float, naive: bool, rec: bool) -> None:
    """The calls eval.arms.run makes per document, in parallel (same payloads, so the same cache keys); arms.run then
    replays them from the cache in its own order. Only speed changes."""
    from eval import naive_baseline
    from gegenprobe.convert import cascade, pointer, rules

    def one(d):
        pages, lg = d["pages"], arms._lang(d)
        pointer.answer_date(be, pages, lg, theta, anchors=rules.anchors(pages))
        cascade.answer_date(dict(pages=pages, lang=lg, image_only=d["image_only"]), be, theta, use_metadata=False)
        if naive:
            for arm in ("plain", "null"):
                naive_baseline.run_doc(be, pages, lg, arm, seed=d["doc_id"] % 100000)
        if rec:
            pointer.recommendation(be, pages, lg, arms.REC_THETA)
        return d["doc_id"]

    with ThreadPoolExecutor(int(os.environ.get("GP_WORKERS", "3"))) as ex:
        for i, _ in enumerate(ex.map(one, docs), 1):
            if i % 10 == 0:
                print(f"warm {i}/{len(docs)} usd={spent():.4f}", flush=True)


def _run(split_files: tuple[Path, Path] | None, arm_list: list[str]) -> dict:
    """eval.arms.run unchanged on the held-out split (or on staged P2 files), with the new build and the refitted θ."""
    theta = _theta()
    be = backend()
    saved = arms.DATA, arms.RESULTS
    data = DATA
    if split_files is not None:
        data = Path(tempfile.mkdtemp(prefix="refit_data_"))
        (data / "gold").mkdir()
        shutil.copyfile(split_files[0], data / "gold" / "heldout_docs.jsonl")
        shutil.copyfile(split_files[1], data / "gold" / "heldout_labels.jsonl")
    arms.DATA, arms.RESULTS = data, Path(tempfile.mkdtemp(prefix="refit_res_"))
    try:
        _warm(be, arms.load_split("heldout"), theta, "naive" in arm_list, "recommendation" in arm_list)
        res = arms.run(be, "heldout", arm_list, theta)
    finally:
        arms.DATA, arms.RESULTS = saved
    _require_clean(be)
    res["relabel"] = dict(be.relabel)
    return res


def _rows(res: dict, labels_p: Path, docs_p: Path) -> list[dict]:
    """Per-document rows as eval.posthoc_r6._p12_rows builds them, from a result dict."""
    from eval.replay_all import _arm_rows

    labels = {x["doc_id"]: x for x in map(json.loads, open(labels_p))}
    body = {d["doc_id"]: d["body"] for d in map(json.loads, open(docs_p))}
    rows, _, bad = _arm_rows(res["per_doc"], labels)
    assert not bad, bad[:3]
    out = []
    for i, r in enumerate(res["per_doc"]):
        row = dict(doc_id=r["doc_id"], body=body[r["doc_id"]], gold=labels[r["doc_id"]]["answer_date"],
                   lenient=labels[r["doc_id"]].get("answer_date_lenient") or [], doc_dates=r.get("doc_dates") or [])
        for a, rs in rows.items():
            row[a] = rs[i]["pred"]
        out.append(row)
    return out


def _paired(new: list[dict], reg: list[dict], extra: dict[str, dict] | None = None) -> dict:
    """New-build arms against the registered build's arms (and any extra per-document column), with the post hoc method
    of eval/gold2/posthoc_best_baseline.py (eval.posthoc_r6.doc_level_block)."""
    from eval import posthoc_r6 as R6

    regd = {r["doc_id"]: r for r in reg}
    rows = []
    for r in new:
        g = regd[r["doc_id"]]
        assert g["gold"] == r["gold"]
        row = dict(doc_id=r["doc_id"], body=r["body"], gold=r["gold"], lenient=r["lenient"], doc_dates=g["doc_dates"])
        for a in ("pointer", "cascade", "rules"):
            row[f"{a}_new"], row[f"{a}_registered"] = r.get(a), g.get(a)
        for k, col in (extra or {}).items():
            row[k] = col[r["doc_id"]]
        rows.append(row)
    cols = ["pointer_new", "pointer_registered", "cascade_new", "cascade_registered", "rules_new", *(extra or {})]
    pairs = [("pointer_new", "pointer_registered"), ("cascade_new", "cascade_registered"),
             ("pointer_new", "pointer_registered", lambda r: r["gold"] is not None, "answered")]
    for k in extra or {}:
        pairs += [("pointer_new", k), ("pointer_new", k, lambda r: r["gold"] is not None, "answered"),
                  ("pointer_registered", k)]
    blk = R6.doc_level_block(rows, cols, pairs)
    answered = [r for r in rows if r["gold"] is not None]
    blk["answer_dates_found"] = {a: [sum(R6._ok(r[a], r) for r in answered), len(answered)] for a in cols}
    blk["values_on_gold_null"] = {a: [sum(r[a] is not None for r in rows if r["gold"] is None),
                                      sum(r["gold"] is None for r in rows)] for a in cols}
    return blk


def p2() -> dict:
    from eval import posthoc_r6 as R6
    from eval.gold2 import hypotheses2 as H

    t0, usd0 = time.time(), spent()
    docs_p, labels_p = DATA / "gold2" / "p2_docs.jsonl", DATA / "gold2" / "p2_labels.jsonl"
    res = _run((docs_p, labels_p), ["rules", "pointer", "cascade", "naive"])
    res["split"] = "p2"
    slug = llm._slug(res["build"])
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / f"p2__{slug}.json"
    raw.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    # the P2 scorer, unchanged, on this result (its RESULTS pointed at a copy)
    tmp = Path(tempfile.mkdtemp(prefix="refit_h2_"))
    (tmp / "eval2").mkdir()
    shutil.copyfile(raw, tmp / "eval2" / f"p2__{slug}.json")
    saved = H.RESULTS
    H.RESULTS = tmp
    try:
        hyp = H.main(slug)
    finally:
        H.RESULTS = saved
    reg_h = json.loads((RESULTS / "eval2" / "hypotheses2__publicai_swiss-ai_apertus-v1.5-8b.json").read_text())
    dtype = {d["doc_id"]: d["dtype"] for d in map(json.loads, open(docs_p))}
    new_rows = _rows(res, labels_p, docs_p)
    base = {r["doc_id"]: ((max(r["doc_dates"]) if r["doc_dates"] else None) if dtype[r["doc_id"]] == "answer" else None)
            for r in new_rows}
    cmp_ = _paired(new_rows, R6._p12_rows("P2"), {"latest_date_on_answer_docs_only": base})
    a_new, a_reg = hyp["subsets"]["all"]["theta_10_40"]["arms"], reg_h["subsets"]["all"]["theta_10_40"]["arms"]
    out = dict(
        label=LABEL, note=NOTE, build=res["build"], theta=res["theta"], theta_file=str(THETA_FILE.relative_to(ROOT)),
        n=len(new_rows), served_fingerprints=res["served_fingerprints"], relabel=res["relabel"], cache=audit(),
        scorer="eval/gold2/hypotheses2.py unchanged (strict outcome of eval/score.py); the key theta_10_40 there is the "
               "run's own θ (this file's `theta`), theta_0 the same margins at θ = 0",
        summary={a: dict(new=dict(exact=a_new[a]["exact"], answer_dates=a_new[a]["value_recall"],
                                  values_on_gold_null=a_new[a]["values_on_gold_null"]),
                         registered=dict(exact=a_reg[a]["exact"], answer_dates=a_reg[a]["value_recall"],
                                         values_on_gold_null=a_reg[a]["values_on_gold_null"]))
                 for a in a_new},
        baseline_latest_date_on_answer_docs=dict(exact=cmp_["arms"]["latest_date_on_answer_docs_only"]["exact"],
                                                 answer_dates=cmp_["answer_dates_found"]["latest_date_on_answer_docs_only"],
                                                 file="results/eval2/p2_posthoc_best_baseline.json"),
        h2_h3_h4=dict(new={k: hyp["subsets"]["all"]["theta_10_40"][k] for k in ("H2_pointer_vs_rules",
                                                                                 "H3_cascade_values_on_null")}
                      | dict(H4_auroc=hyp["subsets"]["all"]["H4_auroc"]),
                      registered={k: reg_h["subsets"]["all"]["theta_10_40"][k] for k in ("H2_pointer_vs_rules",
                                                                                         "H3_cascade_values_on_null")}
                      | dict(H4_auroc=reg_h["subsets"]["all"]["H4_auroc"])),
        paired=cmp_,
        hypotheses2=hyp,
        raw=str(raw.relative_to(ROOT)),
        cost=dict(tag=TAG, usd=round(spent() - usd0, 6), wall_s=round(time.time() - t0, 1)),
    )
    (OUT / "p2_newbuild.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def p1() -> dict:
    from eval import posthoc_r6 as R6

    t0, usd0 = time.time(), spent()
    res = _run(None, ["rules", "pointer", "cascade", "naive", "recommendation"])
    slug = llm._slug(res["build"])
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / f"heldout__{slug}.json"
    raw.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    reg = json.loads((RESULTS / "eval" / "heldout__publicai_swiss-ai_apertus-v1.5-8b.json").read_text())
    keys = ("n", "exact", "correct", "correct_null", "false_null", "misattributed", "fabricated")
    summ = {a: dict(new={k: res["arms"][a]["strict"]["ALL"].get(k) for k in keys},
                    registered={k: reg["arms"][a]["strict"]["ALL"].get(k) for k in keys}) for a in res["arms"]}
    new_rows = _rows(res, DATA / "gold" / "heldout_labels.jsonl", DATA / "gold" / "heldout_docs.jsonl")
    out = dict(
        label=LABEL, note=NOTE, build=res["build"], theta=res["theta"], theta_file=str(THETA_FILE.relative_to(ROOT)),
        n=res["n_docs"], served_fingerprints=res["served_fingerprints"], relabel=res["relabel"], cache=audit(),
        scorer="eval.arms.run unchanged (eval/score.py summarise, strict, ALL cells)",
        summary=summ, recommendation=dict(new=res["recommendation"], registered=reg["recommendation"]),
        paired=_paired(new_rows, R6._p12_rows("P1")),
        raw=str(raw.relative_to(ROOT)),
        cost=dict(tag=TAG, usd=round(spent() - usd0, 6), wall_s=round(time.time() - t0, 1)),
    )
    (OUT / "p1_heldout_newbuild.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


# ------------------------------------------------------------------------------------------------ partial dev (no call)
def partial() -> dict:
    """No model call. The dev documents whose every pointer call the stopped fit got from the new build (its cache),
    replayed under both builds' caches: margins side by side, AUROC per build on the same documents, and how often the
    abstain/answer decision agrees at the old build's θ (97-document fit). Descriptive only: no θ is fitted on a part."""
    from gegenprobe.convert import pointer
    from gegenprobe.stats import auroc

    saved = arms.SPIKES
    arms.SPIKES = _no_spikes()
    try:
        docs = arms.load_split("dev")
    finally:
        arms.SPIKES = saved

    def be_of(build):
        b = llm.OpenAICompat(base_url="http://offline.invalid", model=REQUESTED, build=build, cache_readonly=True)
        b.offline = True
        return b
    old, new = be_of(ROUTE_BUILD), be_of(NEW_BUILD)
    theta_old = old97()["theta"]
    rows, missing, complete = [], 0, 0
    for d in docs:
        try:
            pn = pointer.answer_date(new, d["pages"], arms._lang(d), theta=0.0)
        except llm.CacheMiss:
            missing += 1
            continue
        complete += 1
        po = pointer.answer_date(old, d["pages"], arms._lang(d), theta=0.0)
        if not po.candidates:
            continue
        rows.append(dict(doc_id=d["doc_id"], gold_null=d["label"]["answer_date"] is None, margin_old=po.margin,
                         margin_new=pn.margin, top_old=po.value, top_new=pn.value))
    pos_o = [r["margin_old"] for r in rows if r["gold_null"]]
    neg_o = [r["margin_old"] for r in rows if not r["gold_null"]]
    pos_n = [r["margin_new"] for r in rows if r["gold_null"]]
    neg_n = [r["margin_new"] for r in rows if not r["gold_null"]]
    agree = sum((r["margin_old"] > theta_old) == (r["margin_new"] > theta_old) for r in rows)
    top_same = sum(r["top_old"] == r["top_new"] for r in rows)
    d_abs = sorted(abs(r["margin_new"] - r["margin_old"]) for r in rows)
    out = dict(label=LABEL + "; partial: the fit was stopped by the response check when the route went back to the "
               "registered build (~03:33 UTC)", n_dev=len(docs), n_complete_new_build=complete,
               n_incomplete=missing, n_compared=len(rows), n_gold_null=len(pos_o), n_gold_value=len(neg_o),
               auroc_old=auroc(pos_o, neg_o) if pos_o and neg_o else None,
               auroc_new=auroc(pos_n, neg_n) if pos_n and neg_n else None,
               theta_old_97=theta_old, decision_agreement_at_theta_old=[agree, len(rows)],
               top_candidate_same=[top_same, len(rows)],
               margin_abs_diff=dict(median=d_abs[len(d_abs) // 2] if d_abs else None, max=d_abs[-1] if d_abs else None),
               rows=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev_partial_compare.json").write_text(json.dumps(out, indent=1) + "\n")
    return {k: v for k, v in out.items() if k != "rows"}


# ------------------------------------------------------------------------------------------------ P7 verifier (dev only)
P7_THETA_FILE = Path(os.environ.get("GP_REFIT_P7_THETA") or DATA / "deploy" / "p7_theta_bfd70257.json")
P7_IS_ANSWER, P7_DATE = "a2", "b1"  # the frozen P7 prompts (data/p7/p7_config.json)


def _p7_fit(feats: list[dict]) -> dict:
    """θ_A, θ_B by the rule of eval/p7/tune.py, unchanged, exactly as eval/p7/run_8b.py `_fit_inner` applies it (the
    is_answer prompt fixed at the frozen a2; the free arm not run)."""
    from eval.p7 import run_8b as R8
    from eval.p7 import tune

    R8._patch_offline()
    feats = [dict(f) for f in feats]
    for f in feats:
        f.setdefault("free", dict(answer="not_run", date=None, rule=[None, False]))
    tmp = Path(tempfile.mkdtemp(prefix="refit_p7_"))
    (tmp / "ann").mkdir()
    shutil.copyfile(DATA / "p7" / "dev_annotations" / "gold.jsonl", tmp / "ann" / "gold.jsonl")
    gold = tune.load_ann(tmp)
    cf = tune.configs(feats, gold)
    best = sorted(cf, key=lambda c: (-c["correct"], c["is_answer"] != "a1", c["theta_b"]))[0]
    ok = best["theta_a"] is not None
    return dict(theta_a=best["theta_a"], theta_b=best["theta_b"] if ok else None,
                dev={k: best[k] for k in ("promoted", "correct", "precision", "wilson", "recall_all",
                                          "recall_attainable", "date_hit")},
                no_theta_note=None if ok else "no grid value satisfies the rule for any θ_B: nothing is promoted",
                configs=cf)


def p7_old() -> dict:
    """No model call: the rule on the registered build's committed dev features with is_answer fixed at a2 (must give the
    registered θ_A = 8, θ_B = 10, as data/p7/p7_config.json)."""
    feats = [json.loads(x) for x in (DATA / "p7" / "dev_features.jsonl").read_text().splitlines() if x.strip()]
    for f in feats:
        f["a"] = {P7_IS_ANSWER: f["a"][P7_IS_ANSWER]}
        f.pop("free", None)
    r = _p7_fit(feats)
    return {k: r[k] for k in ("theta_a", "theta_b", "dev")}


def p7dev() -> dict:
    """The 80 P7 dev rows (texts from the local P7 work copies, each checked against the committed text_sha256 by
    adjudicate.features), the frozen a2/b1 questions on the new build; then θ_A/θ_B by the frozen rule. No test row."""
    from eval.p7 import run_8b as R8
    from gegenprobe.repair.adapters import adjudicate as J

    t0, usd0 = time.time(), spent()
    be = backend()
    rows = sorted(R8.load_rows("dev"), key=lambda r: (r["body"], r["affair_id"]))

    def one(r):
        row = dict(body=r["body"], affair_id=r["affair_id"], reason=r["reason"], text_sha256=r["text_sha256"])
        f = J.features(be, row, r["target"], (P7_IS_ANSWER,), (P7_DATE,), free=False)
        f.update(id=r["id"], split="dev", text_identical=True)
        return R8._strip(f)

    with ThreadPoolExecutor(int(os.environ.get("GP_WORKERS", "3"))) as ex:
        feats = list(ex.map(one, rows))
    _require_clean(be)
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / "p7_features_dev.jsonl"
    src.write_text("".join(json.dumps(f, ensure_ascii=False, sort_keys=True) + "\n" for f in feats), encoding="utf-8")
    r = _p7_fit(feats)
    import hashlib
    doc = dict(label=LABEL, note=NOTE, written=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), build=NEW_BUILD,
               route_build=ROUTE_BUILD, requested_model=REQUESTED, served_label=NEW_LABEL, served_fingerprints=[NEW_FP],
               is_answer=P7_IS_ANSWER, date=P7_DATE, theta_a=r["theta_a"], theta_b=r["theta_b"], dev=r["dev"],
               no_theta_note=r["no_theta_note"], dev_scored=len(feats),
               rule="eval/p7/tune.py unchanged, as eval/p7/run_8b.py fit applies it: per θ_B in tune.THETA_B, θ_A = the "
                    "smallest tune.GRID value with no promoted dev row gold no/unclear/disputed (tune.rule_theta); chosen: "
                    "most correct promotions at its θ_A, ties the smaller θ_B (is_answer fixed at the frozen a2)",
               registered=dict(json.loads((DATA / "p7" / "p7_config.json").read_text()), file="data/p7/p7_config.json",
                               same_rule_a2_on_committed_dev_features=p7_old()),
               features=str(src.relative_to(ROOT)), features_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
               relabel=dict(be.relabel), cost=dict(tag=TAG, usd=round(spent() - usd0, 6), wall_s=round(time.time() - t0, 1)),
               test_rows_scored=0)
    P7_THETA_FILE.parent.mkdir(parents=True, exist_ok=True)
    P7_THETA_FILE.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    (OUT / "p7_dev_table.json").write_text(json.dumps(dict(label=LABEL, configs=r["configs"]), indent=1,
                                                      ensure_ascii=False) + "\n")
    return {k: v for k, v in doc.items() if k != "registered"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["old97", "fit", "p2", "p1", "audit", "p7old", "p7dev", "partial"])
    a = ap.parse_args()
    out = dict(old97=old97, fit=fit, p2=p2, p1=p1, audit=audit, p7old=p7_old, p7dev=p7dev, partial=partial)[a.cmd]()
    print(json.dumps(out, indent=1, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
