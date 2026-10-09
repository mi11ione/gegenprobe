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


def diag(argv: list[str]) -> int:
    """Second opinion on the same CPU: dump the exact token ids this scorer feeds llama.cpp, so the spike's own libllama
    scorer (tools/llscore.cpp) can score them; then compare the two. Separates scorer bugs from backend numerics.
        python -m gegenprobe.gguf_check diag-ids ids.txt
        python -m gegenprobe.gguf_check diag-compare ids.txt llscore_out.txt mine.json
    """
    fx = json.loads(FIX.read_text())
    if argv[0] == "diag-ids":
        m = GGUF(cache_readonly=True)
        m._load()
        with open(argv[1], "w") as f:
            for r in fx["rows"]:
                head = m.render(r["text"] + fx["questions"][r["rung"]])
                pre = m._tok(head)
                cands = [m._tok(head + c)[len(pre):] for c in fx["candidates"]]
                f.write(" ".join(map(str, pre)) + "".join(" ; " + " ".join(map(str, c)) for c in cands) + "\n")
        return 0
    ids = open(argv[1]).read().splitlines()
    ll = [line.split("|")[0].split() for line in open(argv[2]).read().splitlines()]
    mine = json.loads(Path(argv[3]).read_text())["rows"]
    out = []
    for r, lls, mrow, idl in zip(fx["rows"], ll, mine, ids):
        lo = float(lls[0]) - float(lls[1])
        out.append(dict(key=mrow["key"], n_prompt=len(idl.split(";")[0].split()), metal_ref=r["lo_conv"], llscore_cpu=lo,
                        scorer_cpu=mrow["got"], scorer_minus_llscore=mrow["got"] - lo))
        print(out[-1])
    mx = max(abs(x["scorer_minus_llscore"]) for x in out)
    print(f"max |scorer - llscore(CPU)| = {mx:.4f} nats")
    return 0 if mx < 0.05 else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(diag(a) if a and a[0].startswith("diag") else main(a))
