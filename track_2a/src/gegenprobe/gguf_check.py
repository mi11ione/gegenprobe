"""Parity check of the in-process GGUF scorer (llm.GGUF) against the spike's libllama scores for the same build.

Reference: spikes/gguf/stage_gguf_q4.json (Colby Q4_K_M, llama.cpp with Metal, token ids from the HF/MLX tokenizer, which
equal llama.cpp's own ids on 1058/1058 strings). Twelve cells: ten nearest the decision boundary plus two saturated ones.
Pass rule (fixed before the first run): every decision (sign of log-odds Ja-Nein) agrees, and the mean |delta log-odds| is
at most 1.0 nat (CPU vs Metal kernels differ in float accumulation order).

    python -m gegenprobe.gguf_check [out.json]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .llm import GGUF

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "gguf_parity.json"


def main(argv: list[str]) -> int:
    fx = json.loads(FIX.read_text())
    m = GGUF(cache_readonly=True)
    rows, t0 = [], time.time()
    for r in fx["rows"]:
        a, b = m.score(r["text"] + fx["questions"][r["rung"]], "", fx["candidates"])
        rows.append(dict(key=f"{r['set']}:{r['key']}:{r['rung']}", ref=r["lo_conv"], got=a - b, delta=(a - b) - r["lo_conv"],
                         agree=(a - b > 0) == (r["lo_conv"] > 0)))
        print(rows[-1], flush=True)
    mad = sum(abs(x["delta"]) for x in rows) / len(rows)
    agree = sum(x["agree"] for x in rows)
    ok = agree == len(rows) and mad <= 1.0
    res = dict(rows=rows, decisions_agree=agree, n=len(rows), mean_abs_delta=mad, secs=round(time.time() - t0, 1),
               rendered_tail=m.render("X")[-160:], verdict="PASS" if ok else "FAIL")
    out = Path(argv[0]) if argv else Path("out/gguf_parity.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"GGUF parity: {agree}/{len(rows)} decisions agree, mean |delta| {mad:.2f} nats -> {res['verdict']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
