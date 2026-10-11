"""8B arms on P2 (Apertus v1.5 8B, GGUF Q4_K_M, llama.cpp CPU): the frozen eval.arms.run on P2's 62 documents, exactly as
eval/gold2/run_p2.py stages them (P2 docs/labels laid out under the P1 file names), with the speed-optimised GGUF scorer that
cleared the D2 gate (src/gegenprobe/gguf_fast.py; results/eval/gguf_fast_verparity.json) and the 8B θ fitted on P1 dev
(data/convert/theta/gguf_apertus-v1.5-8b-text-q4_k_m.json, unchanged). PREREG2 lists the 8B arms as exploratory; this run
was added after review (10 Oct 2026) and is labelled post-hoc in every output.

Arms: rules, pointer, cascade (naive arms not run on the 8B, as in P1, DEVIATIONS.md D3). Runs on CI (workflow arms-8b-p2);
nothing here runs a model unless `run` is called with the real backend.

  fetch                 fetch every P2 PDF by URL, verified against its committed sha256 (a changed source is reported)
  run --shard i/n       shard i of n, sliced on the FULL P2 label order (an unreachable PDF cannot shift other documents
                        between shards); unreachable documents are skipped and listed
                        -> results/eval2/shards/p2__gguf__i_of_n.json, results/eval2/shards/unreachable_p2__i_of_n.json
  run --ids a,b,...     fill-in of named documents -> results/eval2/shards/p2__gguf__fill_<k>.json
  merge                 concatenate shards (a document scored twice must carry identical decisions), re-summarise with the
                        frozen eval/score.py, check the gold against data/gold2/p2_labels.jsonl (eval.replay_all), run the
                        frozen P2 hypotheses script on the 8B rows
                        -> results/eval2/p2__gguf_apertus-v1.5-8b-text-q4_k_m.json,
                           results/eval2/hypotheses2__gguf_apertus-v1.5-8b-text-q4_k_m.json
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from eval import arms
from eval.score import summarise
from gegenprobe import llm, pdftext
from gegenprobe.paths import DATA, PDF_CACHE, RESULTS, TEXT_CACHE

BUILD = "gguf:apertus-v1.5-8b-text-q4_k_m"
SLUG = llm._slug(BUILD)
ARMS = ["rules", "pointer", "cascade"]
P2_DOCS = DATA / "gold2" / "p2_docs.jsonl"
P2_LABELS = DATA / "gold2" / "p2_labels.jsonl"
THETA = DATA / "convert" / "theta" / f"{SLUG}.json"
SHARDS = RESULTS / "eval2" / "shards"
OUT = RESULTS / "eval2" / f"p2__{SLUG}.json"
LABEL = ("POST-HOC (added 10 Oct 2026 after review): the PREREG2 exploratory 8B arms on P2, frozen arms and "
         "scorer, 8B θ from P1 dev")


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def label_order() -> list[int]:
    return list(dict.fromkeys(r["doc_id"] for r in _jsonl(P2_LABELS)))


def shard_ids(shard: str) -> list[int]:
    i, n = map(int, shard.split("/"))
    return label_order()[i::n]


def reachable(doc: dict) -> bool:
    """A document can be scored if its PDF (or its extracted text) is on this machine."""
    return (PDF_CACHE / f"{doc['sha256']}.pdf").exists() or \
        (TEXT_CACHE / f"{doc['sha256']}.pdftotext-{pdftext.poppler_version()}.json").exists()


def fetch() -> list[int]:
    from gegenprobe import net
    from gegenprobe.compliance import fetchguard
    fetchguard.ensure()
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    failed = []
    for d in _jsonl(P2_DOCS):
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
    return failed


def staged_data(ids: set[int]) -> tuple[Path, list[int]]:
    """eval/gold2/run_p2.staged_data, restricted to `ids` and to documents present on this runner."""
    docs = {d["doc_id"]: d for d in _jsonl(P2_DOCS)}
    miss = sorted(i for i in ids if not reachable(docs[i]))
    tmp = Path(tempfile.mkdtemp(prefix="p2data8b_"))
    (tmp / "gold").mkdir()
    (tmp / "gold" / "heldout_docs.jsonl").write_text(P2_DOCS.read_text(encoding="utf-8"), encoding="utf-8")
    keep = ids - set(miss)
    lines = [x for x in open(P2_LABELS, encoding="utf-8") if x.strip() and json.loads(x)["doc_id"] in keep]
    (tmp / "gold" / "heldout_labels.jsonl").write_text("".join(lines), encoding="utf-8")
    return tmp, miss


def backend():
    from gegenprobe.gguf_fast import GGUFFast  # lazy: needs numpy + llama-cpp-python only when a model runs
    return GGUFFast()


def run(shard: str = "0/1", ids: str = "", be=None) -> Path:
    mine = set(shard_ids(shard)) if not ids else {int(x) for x in ids.split(",")}
    be = be if be is not None else backend()
    theta = json.loads(THETA.read_text())["answer_date"]["theta"]
    data, miss = staged_data(mine)
    out_root = Path(tempfile.mkdtemp(prefix="p2res8b_"))
    arms.DATA, arms.RESULTS = data, out_root
    try:
        res = arms.run(be, "heldout", ARMS, theta)
    finally:
        arms.DATA, arms.RESULTS = DATA, RESULTS
    tag = shard.replace("/", "_of_") if not ids else f"fill_{len(mine)}"
    res.update(split="p2", shard=tag, assigned=sorted(mine), unreachable=miss, label=LABEL)
    SHARDS.mkdir(parents=True, exist_ok=True)
    (SHARDS / f"unreachable_p2__{tag}.json").write_text(json.dumps(miss))
    dst = SHARDS / f"p2__gguf__{tag}.json"
    dst.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(dst, res["n_docs"], "unreachable:", miss, flush=True)
    return dst


def merge() -> dict:
    parts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SHARDS.glob("p2__gguf__*.json"))]
    if not parts:
        raise SystemExit(f"no shard files in {SHARDS}")
    per_doc, seen = [], {}
    for r in (r for p in parts for r in p["per_doc"]):
        key = json.dumps({a: (r[a].get("value"), r[a].get("route")) for a in ARMS if a in r})
        if r["doc_id"] in seen:
            assert seen[r["doc_id"]] == key, f"doc {r['doc_id']} scored twice with different decisions"
            continue
        seen[r["doc_id"]] = key
        per_doc.append(r)
    order = {d: k for k, d in enumerate(label_order())}
    per_doc.sort(key=lambda r: order[r["doc_id"]])
    rows: dict[str, list] = {}
    for r in per_doc:
        base = dict(cell=r["cell"], gold=r["gold"], lenient=r.get("lenient") or [], doc_dates=r.get("doc_dates") or [])
        for arm in ARMS:
            if arm in r:
                pred = (r[arm].get("value") if r[arm].get("status") == "value" else None) if arm == "rules" else \
                    r[arm].get("value")
                rows.setdefault(arm, []).append(dict(base, pred=pred, route=r[arm].get("route")))
    missing = sorted(set(order) - set(seen))
    res = dict(
        split="p2",
        build=BUILD,
        theta=parts[0]["theta"],
        n_docs=len(per_doc),
        shards=len(parts),
        not_scored=missing,
        served_fingerprints=[],
        model_file=dict(llm.GGUF_PINS["apertus-v1.5-8b-text-q4_k_m"], scorer="gguf_fast (D2 gate: results/eval/"
                        "gguf_fast_verparity.json)"),
        label=LABEL,
        arms={a: dict(strict=summarise(v, True), lenient=summarise(v, False)) for a, v in rows.items()},
        recommendation={},
        per_doc=per_doc,
    )
    from eval.replay_all import rescore_arms
    bad = rescore_arms(res, P2_LABELS)
    assert not bad, bad[:5]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    from eval.gold2 import hypotheses2  # frozen (LOCK2): the registered P2 hypotheses, computed on the 8B rows
    old = hypotheses2.RESULTS
    hypotheses2.RESULTS = OUT.parent.parent
    try:
        h = hypotheses2.main(SLUG)
    finally:
        hypotheses2.RESULTS = old
    print(OUT, len(per_doc), "not scored:", missing, {a: v["strict"]["ALL"]["exact"] for a, v in res["arms"].items()})
    print("P2-H2 (8B):", h["subsets"]["all"]["theta_10_40"]["H2_pointer_vs_rules"])
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run", "merge"])
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--ids", default="", help="comma-separated P2 doc ids to score instead of a shard (fill-in)")
    a = ap.parse_args()
    if a.cmd == "fetch":
        f = fetch()
        print(f"fetch: {62 - len(f)} of 62 present, failed {f}")
    elif a.cmd == "run":
        run(a.shard, a.ids)
    else:
        merge()
