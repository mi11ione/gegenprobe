"""P7 independent check of the test gold: Qwen-SEA-LION-v4-32B-IT (another model family, never Apertus) through the
budget gateway answers the annotation guide's questions on every test packet. It changes no gold label and no decision;
results/p7/p7_hypotheses.json reports agreement and kappa with the gold.

    PYTHONPATH=src:. python -m eval.p7.qwen8     -> WORK/p7test/ann/qwen.jsonl
"""

from __future__ import annotations

import collections
import json
import sys

from eval.p7 import common as C
from eval.p7 import test as T
from gegenprobe.paths import ROOT
from gegenprobe.repair.adapters import audit3

QWEN = audit3.QWEN
TAG = "2a-p7-qwen"
CAP = 0.6

ITEM = """You check whether a document is the government's written answer to a parliamentary intervention in a Swiss \
parliament (a canton or a municipality). You see the intervention's metadata from OpenParlData (OPD) and the text \
extracted from one document. Judge only from what is shown.

Intervention
- number: {number}
- title: {title}
- type: {type}
- OPD answer event date(s): {dates}

Document text (extracted; when longer than 15,000 characters, the first 12,000 and the last 3,000 are shown):
<<<
{text}
>>>

Questions
1. is_answer: does this document print the executive's written answer to THIS intervention (the government: \
Regierungsrat, Stadtrat, Gemeinderat, Kleiner Rat, Conseil d'État, Conseil communal, Municipalité, Consiglio di Stato, \
Municipio ...)? yes = it is the answer or contains it in full; no = something else (the intervention's own text as \
submitted, minutes of the parliament that only mention the answer, a commission report or a report of a body of the \
parliament, an interim report, a request for more time, the answer to a different intervention, a list or agenda); \
unclear = the text does not let you decide.
2. decision_date: the date on which the executive decided the answer, as printed (DD.MM.YYYY), or null.
3. letter_date: the date of the answer letter or of its signature, as printed (DD.MM.YYYY), or null.

Reply with one JSON object only, no other text:
{{"is_answer": "yes|no|unclear", "decision_date": "DD.MM.YYYY" or null, "letter_date": "DD.MM.YYYY" or null}}"""


def main(max_tokens: int = 120) -> dict:
    sys.path.insert(0, str(audit3.GATEWAY))
    import gw  # noqa: E402
    out = T.WORKDIR / "ann" / "qwen.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(x)["id"] for x in out.read_text().splitlines() if x.strip()} if out.exists() else set()
    served, usd = collections.Counter(), 0.0
    with open(out, "a", encoding="utf-8") as f:
        for p in C.load_packets(T.WORKDIR):
            if p["id"] in done:
                continue
            text = (ROOT / p["excerpt_path"]).read_text(encoding="utf-8")
            msg = ITEM.format(number=p["affair_number"], title=p["title"], type=p["type"],
                              dates=", ".join(p["answer_event_dates"]) or "none", text=text)
            choice, meta = gw.chat([dict(role="user", content=msg)], model=QWEN, max_tokens=max_tokens, temperature=0.0,
                                   tag=TAG, tag_cap_usd=CAP, full=True)
            m = (meta.get("resp") or {}).get("model")
            if not m or "qwen-sea-lion" not in m.lower():
                raise RuntimeError(f"{p['id']}: served {m!r}, expected {QWEN}")
            served[m] += 1
            reply = (choice.get("message") or {}).get("content") or ""
            v = audit3.parse(reply)
            f.write(json.dumps(dict(id=p["id"], is_answer=v["is_answer"], model=m, raw=reply[:600]),
                               ensure_ascii=False) + "\n")
            f.flush()
            usd += 0.0 if meta.get("cached") else meta.get("usd", 0.0)
    return dict(usd=round(usd, 4), served=dict(served))


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
