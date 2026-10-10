"""P3b runner: P3's runner (`eval.gold3.run_p3.run`, frozen) on the P3b affairs, with P3's paths rebound to data/gold5 and
results/eval5. No logic of its own (eval/prereg5/PREREG5.md, "Arms").

    python -m eval.gold5.run_p3b --backend none                                          (arms M, R, C; no model)
    python -m eval.gold5.run_p3b --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p3b:3.0    (adds CA; 70B weights)
Writes results/eval5/p3b__<build>.json; per-field scores are included when data/gold5/p3b_labels.jsonl exists (otherwise
`python -m eval.gold5.score5 <build>` adds them once the labels are merged).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import types

from eval.gold3 import run_p3
from gegenprobe import llm
from gegenprobe.affair import meta
from gegenprobe.paths import DATA, RESULTS, WORK

GOLD5 = DATA / "gold5"
OUT5 = RESULTS / "eval5"
STAGE = WORK / "gold5" / "stage_run"
AFFAIRS = GOLD5 / "p3b_affairs.jsonl"
META5 = GOLD5 / "opd_meta_p3b.jsonl"
NAMES5 = GOLD5 / "body_names_p3b.json"
LINKS5 = GOLD5 / "link_status_p3b.json"
LABELS5 = GOLD5 / "p3b_labels.jsonl"


def affairs() -> list[dict]:
    return [json.loads(line) for line in open(AFFAIRS)]


@contextlib.contextmanager
def gold5_paths():
    """Point the frozen P3 runner at the P3b files for the duration of one call."""
    saved = (run_p3.affairs, run_p3.meta, run_p3.LINKS, run_p3.OUT3)
    run_p3.affairs = affairs
    run_p3.meta = types.SimpleNamespace(load=lambda: meta.load(META5), body_names=lambda: meta.body_names(NAMES5))
    run_p3.LINKS, run_p3.OUT3 = LINKS5, STAGE
    try:
        yield
    finally:
        run_p3.affairs, run_p3.meta, run_p3.LINKS, run_p3.OUT3 = saved


def out_path(build: str):
    return OUT5 / f"p3b__{llm._slug(build)}.json"


def run(spec: str) -> dict:
    if not LINKS5.exists():
        raise SystemExit(f"{LINKS5} missing: run the P3b sampler (eval.gold5.sample5) first")
    with gold5_paths():
        res = run_p3.run(spec, labels=LABELS5)
    staged = STAGE / f"p3__{llm._slug(res['build'])}.json"
    res = dict(res, split="p3b", prereg="eval/prereg5/PREREG5.md")
    OUT5.mkdir(parents=True, exist_ok=True)
    out_path(res["build"]).write_text(json.dumps(res, indent=1, ensure_ascii=False))
    staged.unlink(missing_ok=True)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="none")
    a = ap.parse_args()
    r = run(a.backend)
    print(f"{r['n_affairs']} affairs -> {out_path(r['build']).relative_to(RESULTS.parent)}")
    for f, v in (r.get("scores") or {}).get("fields", {}).items():
        print(f, {arm: f"{s.get('correct', 0)}/{s['n']}" for arm, s in v.items()})
