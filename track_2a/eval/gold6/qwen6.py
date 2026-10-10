"""P5 independent gold check (pre-registered in eval/prereg6/PREREG6.md, "Gold"): Qwen-SEA-LION-v4-32B-IT (AI Singapore;
Qwen family: not Anthropic, not Apertus) labels every P5 affair blind from the same packet and the same guide
(eval/gold6/GUIDE_P5.md, verbatim, with the output instruction changed to "reply with one JSON object"). Calls go through
the budget gateway only (tag 2a-p5-qwen); the served model name is checked on every call. Its labels are resolved by the
same code as the Claude annotators' (annotate6.check); an invalid file is kept with its errors and counts as missing for
the fields it fails.

    python -m eval.gold6.qwen6 annotate     -> data/gold6/annotations/p5/QWEN.jsonl (raw JSON + check errors; no text)
    python -m eval.gold6.qwen6 analyse      -> results/eval6/p5_qwen_check.json (agreement with gold; H1 recomputed with
                                               the Qwen labels as gold and on the consensus subset)
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import sys

from eval.gold6 import annotate6 as A
from eval.gold6 import common6 as C
from eval.gold6.score6 import gold_view, iou, name_match, score
from gegenprobe.paths import RESULTS, ROOT

MODEL = "aisingapore/Qwen-SEA-LION-v4-32B-IT"
TAG, TAG_CAP = "2a-p5-qwen", 0.6
MAX_TOKENS = 3000
MAX_CHARS = 60_000
OUT = C.GOLD6 / "annotations" / "p5" / "QWEN.jsonl"
GATEWAY = os.path.expanduser("~/Desktop/hackapertus/gateway")
INSTR = ("\n\nReply with exactly one JSON object with the keys defined above and nothing else (no files, no self-check "
         "command). The packet follows.\n\n")


def prompt(affair_id: int) -> str:
    guide = (ROOT / "eval" / "gold6" / "GUIDE_P5.md").read_text(encoding="utf-8")
    packet = (C.W6 / "packets" / f"{affair_id}.txt").read_text(encoding="utf-8")[:MAX_CHARS]
    return guide + INSTR + packet


def call(affair_id: int) -> dict:
    sys.path.insert(0, GATEWAY)
    import gw

    choice, meta = gw.chat([{"role": "user", "content": prompt(affair_id)}], model=MODEL, max_tokens=MAX_TOKENS,
                           temperature=0.0, tag=TAG, tag_cap_usd=TAG_CAP, full=True, seed=0)
    served = (meta.get("resp") or {}).get("model")
    if served != MODEL:
        raise RuntimeError(f"requested {MODEL}, served {served}")
    text = (choice.get("message") or {}).get("content") or ""
    from eval.gold6.freegen6 import parse

    js = parse(text)
    return dict(affair_id=affair_id, served=served, parse_ok=js is not None, label=js, usd=meta.get("usd"))


def annotate() -> None:
    rows = A._rows("p5")
    done = {}
    if OUT.exists():
        done = {r["affair_id"]: r for r in map(json.loads, open(OUT))}
    todo = [r["affair_id"] for r in rows if r["affair_id"] not in done]
    with cf.ThreadPoolExecutor(3) as ex:
        for r in ex.map(call, todo):
            done[r["affair_id"]] = r
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        for k in sorted(done):
            f.write(json.dumps(done[k], ensure_ascii=False) + "\n")
    print(f"{len(done)} Qwen labels -> {OUT}")


def analyse(build: str) -> dict:
    gold = {r["affair_id"]: r for r in map(json.loads, open(C.GOLD6 / "p5_labels.jsonl"))}
    qw = {r["affair_id"]: r for r in map(json.loads, open(OUT))}
    res_file = RESULTS / "eval6" / f"p5__{build}.json"
    res = json.loads(res_file.read_text())
    qviews, errors = {}, {}
    for i, r in qw.items():
        lab = dict(r["label"] or {}, affair_id=i)
        errs, resolved = A.check(lab, A._docs("p5", i)) if r["label"] else (["no JSON"], None)
        errors[i] = errs
        if resolved is not None:
            qviews[i] = gold_view(resolved)
    gviews = {i: gold_view(g) for i, g in gold.items()}
    agree = dict(n=len(gold), valid=sum(not e for e in errors.values()))
    for f in ("n_questions", "answer_style", "recommendation", "submitter"):
        k = 0
        for i in gold:
            g, q = gviews[i], qviews.get(i)
            if q is None:
                continue
            if f == "n_questions":
                k += len(g["questions"]) == len(q["questions"])
            elif f == "submitter":
                k += (g["submitter"] is None and q["submitter"] is None) or name_match(g["submitter"], q["submitter"])
            else:
                k += g[f] == q[f]
        agree[f] = k
    ans_agree = ans_n = 0
    consensus = {}
    for i, g in gviews.items():
        q = qviews.get(i)
        qa = {x["n"]: x["span"] for x in (q or {}).get("answers") or []}
        keep = []
        for x in g["answers"]:
            if x["span"] is None:
                keep.append(x)
                continue
            ans_n += 1
            ok = iou(x["span"], qa.get(x["n"])) >= 0.5
            ans_agree += ok
            keep.append(x if ok else dict(x, span=None, dropped=True))
        consensus[i] = dict(g, answers=[x for x in keep if not x.get("dropped")])
    agree["answers_iou05"] = dict(k=ans_agree, n=ans_n)
    arms = {}
    for arm in ("R", "RA"):
        if all(arm in p for p in res["per_affair"]):
            preds = {p["affair_id"]: p[arm]["view"] for p in res["per_affair"]}
            arms[arm] = dict(qwen_as_gold=score(preds, qviews)["qa_pairs"], consensus=score(preds, consensus)["qa_pairs"])
    out = dict(model=MODEL, agreement=agree, errors={k: v for k, v in errors.items() if v}, h1_sensitivity=arms)
    (RESULTS / "eval6" / "p5_qwen_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    if sys.argv[1] == "annotate":
        annotate()
    else:
        print(json.dumps(analyse(sys.argv[2] if len(sys.argv) > 2 else "publicai_swiss-ai_apertus-v1.5-8b"), indent=1)[:3000])
