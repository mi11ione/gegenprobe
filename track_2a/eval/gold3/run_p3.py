"""P3 runner: whole-affair extraction on the P3 affairs (eval/prereg3), every arm, scored per field against the gold labels.

    python -m eval.gold3.run_p3 --backend none                                               (arms M, R, C; no model)
    python -m eval.gold3.run_p3 --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p3:2.0          (adds CA; 70B weights)
    python -m eval.gold3.run_p3 --backend gguf                                               (adds CA; 8B, θ of that build)
    python -m eval.gold3.run_p3 --backend fake                                               (tests)
Writes results/eval3/p3__<build>.json (per-affair arm values, suggestions, the validated Affair instances, per-field scores
when data/gold3/p3_labels.jsonl exists).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.arms import backend as make_backend
from eval.arms import theta_path
from eval.gold3.score3 import score_all
from gegenprobe import llm
from gegenprobe.affair import build, meta
from gegenprobe.paths import DATA, RESULTS

GOLD3 = DATA / "gold3"
OUT3 = RESULTS / "eval3"
LINKS = GOLD3 / "link_status_p3.json"


def affairs() -> list[dict]:
    return [json.loads(line) for line in open(GOLD3 / "p3_affairs.jsonl")]


def link_status(ids: set[int]) -> dict[int, str]:
    """Answer-link status from the census (vendored tables); cached because the census pass takes about a minute."""
    if LINKS.exists():
        return {int(k): v for k, v in json.loads(LINKS.read_text()).items()}
    from gegenprobe.census import funnel

    _, aff = funnel.compute()
    out = {a: aff[a]["link"] for a in ids if a in aff}
    LINKS.write_text(json.dumps({str(k): v for k, v in sorted(out.items())}))
    return out


class FakeBackend:
    """Deterministic stand-in for tests: prefers the first candidate, never null."""

    build = "fake"

    def score(self, user, prefix, conts):
        return [-50.0] + [-1.0 - i for i in range(len(conts) - 1)]


def get_backend(spec: str):
    if spec == "fake":
        return FakeBackend(), 0.0
    be = make_backend(spec)
    if be is None:
        return None, None
    tp = theta_path(be.build)
    theta = json.loads(tp.read_text())["answer_date"]["theta"] if tp.exists() else None
    if theta is None:
        raise SystemExit(f"no fitted θ for {be.build} (data/convert/theta/)")
    return be, theta


def run(spec: str, labels: Path = GOLD3 / "p3_labels.jsonl") -> dict:
    be, theta = get_backend(spec)
    rows = affairs()
    M, N = meta.load(), meta.body_names()
    links = link_status({r["affair_id"] for r in rows})
    per = [build.run_affair(r, M[r["affair_id"]], N.get(r["body"], []), links.get(r["affair_id"]), be, theta) for r in rows]
    res = dict(
        split="p3",
        build=getattr(be, "build", "none"),
        theta_answer=theta,
        theta_new_fields=0.0,
        n_affairs=len(per),
        served_fingerprints=sorted(getattr(be, "served", set())) if be else [],
        per_affair=per,
    )
    if labels.exists():
        gold = {g["affair_id"]: g for g in map(json.loads, open(labels))}
        res["scores"] = score_all(per, gold, {r["affair_id"]: r for r in rows})
    OUT3.mkdir(parents=True, exist_ok=True)
    out = OUT3 / f"p3__{llm._slug(res['build'])}.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="none")
    a = ap.parse_args()
    r = run(a.backend)
    print(f"{r['n_affairs']} affairs -> results/eval3/p3__{llm._slug(r['build'])}.json")
    if "scores" in r:
        for f, v in r["scores"]["fields"].items():
            print(f, {arm: f"{s['correct']}/{s['n']}" for arm, s in v.items()})
