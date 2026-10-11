"""P6 independent non-Anthropic gold check (registered in PREREG7 'Labels'): Qwen-SEA-LION-v4-32B-IT labels every P6
document blind with exactly the earlier protocol (eval/posthoc_r5.py: the guide cut to presence and date, the same packet
text the Claude annotators read, served model checked on every call), then the P6 hypotheses are recomputed with Qwen's
labels as gold (sensitivity; the registered decisions use the committed gold).

    PYTHONPATH=src:. python -m eval.p6.qwen7 annotate    -> data/p6/qwen_p6.jsonl (labels, no text)
    PYTHONPATH=src:. python -m eval.p6.qwen7 analyse     -> results/p6/qwen7_check.json
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from eval import posthoc_r5 as R
from eval.p6 import hypotheses7 as H
from eval.p6 import sample as S
from gegenprobe.paths import DATA, RESULTS, WORK

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
R.SETS["p6"] = dict(docs=S.DOCS, labels=S.LABELS, packets=WORK / "p6" / "packets", res=RESULTS / "p6" / f"p6__{BUILD}.json")
R.OUT = DATA / "p6"
R.TAG, R.TAG_CAP = "2a-p6-qwen", 0.5


def analyse() -> dict:
    out = dict(protocol="eval/posthoc_r5.py (Qwen protocol, unchanged), set p6", model=R.MODEL,
               agreement_strict=R.agreement("p6", True), agreement_lenient_quote=R.agreement("p6", False))
    Q = R.qwen("p6")
    G = R.labels("p6")
    sens = {}
    for name, strict in (("qwen_strict", True), ("qwen_quote_lenient", False)):
        tmp = Path(tempfile.mkdtemp()) / "labels.jsonl"
        with open(tmp, "w") as f:
            for i, g in G.items():
                f.write(json.dumps(dict(g, answer_date=R.q_date(Q[i], strict), answer_date_lenient=[])) + "\n")
        h = H.main(BUILD, labels_path=tmp, out_path=Path(tempfile.mkdtemp()) / "h.json")
        sens[name] = dict(
            arms={a: dict(exact=v["exact"], dated_answerless=v["dated_answerless"]) for a, v in h["arms"].items()},
            H1=dict(h["H1_v2_vs_free_null"]["doc_level"], holds=h["H1_v2_vs_free_null"]["holds"]),
            H2=dict(v2=h["H2_answerless"]["v2"], wilson95=h["H2_answerless"]["wilson95"], v1=h["H2_answerless"]["v1"],
                    free_null=h["H2_answerless"]["free_null"], holds=h["H2_answerless"]["holds"]),
            H3=dict(h["H3_v2_vs_v1"]["doc_level"], holds=h["H3_v2_vs_v1"]["holds"]),
            S1=h["S1_v2_vs_free_guided"]["doc_level"])
    out["hypotheses_under_qwen_gold"] = sens
    p = RESULTS / "p6" / "qwen7_check.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    if sys.argv[1] == "annotate":
        R.annotate("p6", workers=6)
    else:
        o = analyse()
        print(json.dumps(dict(overall=o["agreement_strict"]["overall"], hyp=o["hypotheses_under_qwen_gold"]), indent=1)[:4000])
