"""`make run` step 2: recompute the census from the committed compact tables (data/census/) and assert that every output
equals the committed results/census/* byte for byte (JSON compared as parsed objects). Exit 1 on any difference.

Also verifies the sha256 of every compact table against data/census/meta.json before computing.

usage: python -m gegenprobe.census.replay [--data data/census]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

from . import findings, funnel, matrix, question
from .tables import CENSUS

COMPARED = ["funnel.json", "summary.json", "matrix.json", "matrix.csv", "question.json", "findings.json"]


def verify_inputs(root: Path) -> list[str]:
    meta = json.loads((root / "meta.json").read_text())
    errs = []
    for name, h in meta["sha256"].items():
        got = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if got != h:
            errs.append(f"input {name}: sha256 {got[:12]} != {h[:12]}")
    return errs


def run_all(root: Path, out: Path) -> None:
    _, F = funnel.main(root, out)
    matrix.main(root, out, F)
    question.main(root, out, F)
    findings.main(root, out)


def replay(root: Path = CENSUS, committed: Path = funnel.OUT) -> tuple[list[str], float]:
    t0 = time.time()
    errs = verify_inputs(root)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        run_all(root, out)
        for name in COMPARED:
            a, b = out / name, committed / name
            if not b.exists():
                errs.append(f"{name}: committed result missing")
                continue
            if name.endswith(".json"):
                same = json.loads(a.read_text()) == json.loads(b.read_text())
            else:
                same = a.read_bytes() == b.read_bytes()
            if not same:
                errs.append(f"{name}: replay differs from committed results/census/{name}")
    return errs, time.time() - t0


def step(ctx: dict) -> dict:
    """`make run` step 2 (gegenprobe.run contract)."""
    errs, secs = replay(CENSUS)
    s = json.loads((funnel.OUT / "summary.json").read_text())["national"]
    return dict(status="FAIL" if errs else "PASS", errors=errs[:50],
                summary=f"{len(COMPARED)} outputs recomputed from data/census, {len(errs)} differences; in scope {s['n']:,}, "
                        f"written-answer {s['ev_answer']:,}, no answer text {s['gap']:,}, after agenda join "
                        f"{s['gap_after_agenda_join']:,}")


def main(ctx: dict | None = None) -> int | dict:
    if isinstance(ctx, dict):
        return step(ctx)
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=CENSUS)
    a = ap.parse_args()
    errs, secs = replay(a.data)
    for e in errs:
        print("CENSUS REPLAY FAIL", e)
    s = json.loads((funnel.OUT / "summary.json").read_text())["national"]
    print(
        f"census replay: {len(COMPARED)} outputs, {len(errs)} differences, {secs:.0f} s; "
        f"in scope {s['n']:,}, written-answer {s['ev_answer']:,}, gap {s['gap']:,}, gap' {s['gap_after_agenda_join']:,}"
    )
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
