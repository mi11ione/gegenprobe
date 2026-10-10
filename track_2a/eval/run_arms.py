"""8B arms on a CPU runner (pre-registered exploratory arms; deviations D2/D3 in eval/prereg/DEVIATIONS.md).
Drives the FROZEN eval.arms.fit / eval.arms.run with the speed-optimised GGUF scorer, without editing frozen files.

  fetch --split dev|heldout    fetch every document's PDF by URL, verified against its committed sha256
  fit                          fit θ for gguf:apertus-v1.5-8b-text-q4_k_m on dev (the 30 spike items are skipped: their texts
                               are not in the repository) -> data/convert/theta/gguf_apertus-v1.5-8b-text-q4_k_m.json
  run --shard i/n              held-out shard i of n, arms rules,pointer,cascade -> results/eval/shards/heldout__gguf__i_of_n.json
  merge                        concatenate shards and re-summarise with the frozen eval/score.py
                               -> results/eval/heldout__gguf_apertus-v1.5-8b-text-q4_k_m.json
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from eval import arms
from eval.score import summarise
from gegenprobe import llm, pdftext
from gegenprobe.paths import DATA, RESULTS

SHARDS = RESULTS / "eval" / "shards"
BUILD = "gguf:apertus-v1.5-8b-text-q4_k_m"


def _no_spikes() -> None:
    d = Path(tempfile.mkdtemp()) / "round8"
    d.mkdir(parents=True)
    (d / "ptr_items.json").write_text("[]")
    arms.SPIKES = d.parent


def fetch(split: str) -> None:
    """Fetch every PDF, verified against its committed sha256. Short timeout and 2 tries: some hosts never answer CI IPs."""
    from gegenprobe import net
    from gegenprobe.paths import PDF_CACHE
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    for line in open(DATA / "gold" / f"{split}_docs.jsonl"):
        d = json.loads(line)
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
            print("FETCH-FAIL", d["doc_id"], type(e).__name__, str(e)[:120], flush=True)


def _reachable_only() -> None:
    """Some cantonal/communal PDF hosts time out from CI runner IPs. Documents whose PDF could not be fetched are skipped
    (listed in results/eval/shards/unreachable_<split>.json) by running the frozen loader on a label file restricted to
    reachable documents, instead of letting the loader crash on the first missing PDF."""
    from gegenprobe.paths import PDF_CACHE
    orig = arms.load_split

    def load(split):
        docs = {d["doc_id"]: d for d in map(json.loads, open(DATA / "gold" / f"{split}_docs.jsonl"))}
        miss = sorted(i for i, d in docs.items() if not (PDF_CACHE / f"{d['sha256']}.pdf").exists())
        SHARDS.mkdir(parents=True, exist_ok=True)
        (SHARDS / f"unreachable_{split}.json").write_text(json.dumps(miss))
        tmp = Path(tempfile.mkdtemp())
        (tmp / "gold").mkdir()
        (tmp / "gold" / f"{split}_docs.jsonl").write_text((DATA / "gold" / f"{split}_docs.jsonl").read_text())
        labels = [x for x in open(DATA / "gold" / f"{split}_labels.jsonl") if json.loads(x)["doc_id"] in set(docs) - set(miss)]
        (tmp / "gold" / f"{split}_labels.jsonl").write_text("".join(labels))
        arms.DATA = tmp
        try:
            return orig(split)
        finally:
            arms.DATA = DATA
    arms.load_split = load


def backend():
    from gegenprobe.gguf_fast import GGUFFast
    return GGUFFast()


def fit() -> None:
    _no_spikes()
    _reachable_only()
    out = arms.fit(backend())
    print(json.dumps(out["answer_date"], indent=1)[:1500])


def run(shard: str) -> None:
    i, n = map(int, shard.split("/"))
    _reachable_only()
    orig = arms.load_split
    arms.load_split = lambda split: orig(split)[i::n]
    be = backend()
    theta = json.loads(arms.theta_path(be.build).read_text())["answer_date"]["theta"]
    res = arms.run(be, "heldout", ["rules", "pointer", "cascade"], theta)
    SHARDS.mkdir(parents=True, exist_ok=True)
    src = RESULTS / "eval" / f"heldout__{llm._slug(be.build)}.json"
    dst = SHARDS / f"heldout__gguf__{i}_of_{n}.json"
    src.replace(dst)
    print(dst, res["n_docs"])


def merge() -> None:
    parts = [json.loads(p.read_text()) for p in sorted(SHARDS.glob("heldout__gguf__*_of_*.json"))]
    per_doc = sorted((r for p in parts for r in p["per_doc"]), key=lambda r: r["doc_id"])
    rows: dict[str, list] = {}
    for r in per_doc:
        base = dict(cell=r["cell"], gold=r["gold"], lenient=r.get("lenient") or [], doc_dates=r.get("doc_dates") or [])
        for arm in ("rules", "pointer", "cascade"):
            if arm in r:
                rows.setdefault(arm, []).append(dict(base, pred=r[arm].get("value"), route=r[arm].get("route")))
    res = dict(split="heldout", build=BUILD, theta=parts[0]["theta"], n_docs=len(per_doc), shards=len(parts),
               served_fingerprints=[],
               arms={a: dict(strict=summarise(v, True), lenient=summarise(v, False)) for a, v in rows.items()},
               per_doc=per_doc)
    out = RESULTS / "eval" / f"heldout__{llm._slug(BUILD)}.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(out, len(per_doc), {a: v["strict"]["ALL"]["exact"] for a, v in res["arms"].items()})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "fit", "run", "merge"])
    ap.add_argument("--split", default="heldout")
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args()
    {"fetch": lambda: fetch(a.split), "fit": fit, "run": lambda: run(a.shard), "merge": merge}[a.cmd]()
