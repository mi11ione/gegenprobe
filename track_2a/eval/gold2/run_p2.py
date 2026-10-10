"""P2 runner: the FROZEN eval.arms.run (LOCK 812030f) on the P2 documents, unchanged, by pointing its data and results
directories at P2 copies. Writes results/eval2/p2__<build>.json (same layout as the P1 scoreboards).

    python -m eval.gold2.run_p2 --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p2:2.0      (70B weights; θ 10.40 frozen)
    python -m eval.gold2.run_p2 --backend none                                               (rules only)
    python -m eval.gold2.run_p2 --backend gguf                                               (8B, CI; θ of that build)
Requires data/gold2/p2_labels.jsonl (written only after LOCK2).
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from eval import arms
from gegenprobe import llm
from gegenprobe.paths import DATA, RESULTS

ARMS = ["rules", "pointer", "cascade", "naive"]


def staged_data() -> Path:
    """A data dir whose gold/heldout_{docs,labels}.jsonl are the P2 files (arms.load_split reads exactly these names)."""
    tmp = Path(tempfile.mkdtemp(prefix="p2data_"))
    (tmp / "gold").mkdir()
    shutil.copyfile(DATA / "gold2" / "p2_docs.jsonl", tmp / "gold" / "heldout_docs.jsonl")
    shutil.copyfile(DATA / "gold2" / "p2_labels.jsonl", tmp / "gold" / "heldout_labels.jsonl")
    return tmp


def main(spec: str, arm_list: list[str]) -> Path:
    be = arms.backend(spec)
    theta = None
    if be is not None:
        tp = arms.theta_path(be.build)  # θ files live in the real data dir (THETA_DIR is bound at import time)
        theta = json.loads(tp.read_text())["answer_date"]["theta"]
    out_root = Path(tempfile.mkdtemp(prefix="p2res_"))
    arms.DATA, arms.RESULTS = staged_data(), out_root
    try:
        res = arms.run(be, "heldout", arm_list if be is not None else ["rules"], theta)
    finally:
        arms.DATA, arms.RESULTS = DATA, RESULTS
    res["split"] = "p2"
    dst = RESULTS / "eval2" / f"p2__{llm._slug(res['build'])}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="none")
    ap.add_argument("--arms", default=",".join(ARMS))
    a = ap.parse_args()
    print(main(a.backend, a.arms.split(",")))
