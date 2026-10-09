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


IMPL = FIX.with_name("gguf_impl60.json")


def impl(argv: list[str]) -> int:
    """Implementation table on 60 conv cells with a bf16 reference (DPO bf16 stands in for final bf16; spikes/inversions F1):
        impl-ids ids.txt | impl-mine mine.json | impl-compare mine.json <label>=<llscore_out.txt> ... out.json
    Reports, for each implementation of the same Q4_K_M file, decision agreement and mean |delta log-odds| against bf16."""
    fx = json.loads(IMPL.read_text())
    if argv[0] == "impl-ids":
        m = GGUF(cache_readonly=True)
        m._load()
        with open(argv[1], "w") as f:
            for r in fx["rows"]:
                head = m.render(r["text"] + fx["questions"][r["rung"]])
                pre = m._tok(head)
                f.write(" ".join(map(str, pre)) + "".join(" ; " + " ".join(map(str, m._tok(head + c)[len(pre):]))
                                                          for c in fx["candidates"]) + "\n")
        return 0
    if argv[0] == "impl-mine":
        m = GGUF(cache_readonly=True)
        vals = []
        for r in fx["rows"]:
            a, b = m.score(r["text"] + fx["questions"][r["rung"]], "", fx["candidates"])
            vals.append(a - b)
        Path(argv[1]).write_text(json.dumps(vals))
        return 0
    impls = {"metal_q4_spike": [r["metal_q4"] for r in fx["rows"]], "llama_cpp_python": json.loads(Path(argv[1]).read_text())}
    for spec in argv[2:-1]:
        label, path = spec.split("=", 1)
        impls[label] = [float(x.split("|")[0].split()[0]) - float(x.split("|")[0].split()[1])
                        for x in Path(path).read_text().splitlines()]
    ref = [r["bf16_dpo"] for r in fx["rows"]]
    table = {}
    for k, v in impls.items():
        table[k] = dict(decisions_agree_bf16=sum((a > 0) == (b > 0) for a, b in zip(v, ref)), n=len(ref),
                        mean_abs_delta_bf16=sum(abs(a - b) for a, b in zip(v, ref)) / len(ref))
    pair = {f"{a}~{b}": sum(abs(x - y) for x, y in zip(impls[a], impls[b])) / len(ref) for a in impls for b in impls if a < b}
    out = dict(table=table, pairwise_mean_abs_delta=pair, rows=[dict(key=f"{r['set']}:{r['key']}:{r['rung']}", bf16=r["bf16_dpo"],
               **{k: v[i] for k, v in impls.items()}) for i, r in enumerate(fx["rows"])])
    Path(argv[-1]).write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(table=table, pairwise=pair), indent=1))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(diag(a) if a and a[0].startswith("diag") else impl(a) if a and a[0].startswith("impl") else main(a))
