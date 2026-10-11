"""P8 independent check of the gold (eval/prereg9/PREREG9.md §5): Qwen-SEA-LION-v4-32B-IT (another model family; never
Apertus) through the budget gateway labels every packet with the same closed vocabularies, blind like the annotators.
Its labels go through the same derivation (eval/p8/derive.py); results/p8/p8_qwen.json reports, per field, agreement and
Cohen's kappa of the derived category with the gold. It changes no gold label and no decision.

    PYTHONPATH=src:. .venv/bin/python -m eval.p8.qwen9 run       -> WORK/p8/ann/qwen.jsonl   (tag 2a-p8-qwen, cap USD 0.8)
    PYTHONPATH=src:. .venv/bin/python -m eval.p8.qwen9 score     -> results/p8/p8_qwen.json  (after the gold is merged)

The packet is shortened for Qwen: the member text's first 14,000 characters, the answer's first 8,000 and last 3,000,
and the full date list. Quotes are not asked for (Qwen's quotes failed the verbatim check on P5); categories are
derived from its people, date roles, addressee, function, languages and recommendation.
"""

from __future__ import annotations

import collections
import json
import re
import sys

from eval.p8 import annotate as A
from eval.p8 import common as C
from eval.p8 import packets as P
from gegenprobe.devpaths import import_gw
from gegenprobe.stats import cohen_kappa

OUT = C.ANN / "qwen.jsonl"
MAX_TOKENS = 1500

ITEM = """You read the documents of one affair of a Swiss parliament (a canton or a municipality): the "question" document \
is what OpenParlData links as the member's text, the "answer" document what it links as the executive's answer. Judge \
ONLY from what the documents print; never use outside knowledge. Reply with ONE JSON object, no other text.

Keys and allowed values:
- "question_doc": "member_text" (the intervention as lodged by members) | "other" | "unclear"
- "answer_doc": "executive_answer" (the government's / municipal executive's answer or report on this intervention) | \
"other" | "unclear"
- "people": every person or body printed as author, signatory, supporter or spokesperson of THIS intervention, in printed \
order: [{{"name": "...", "kind": "person|group|committee|other_body", "role": "sole_author|first_signatory|joint_author|\
co_signatory|supporter|spokesperson|other"}}]. sole_author = the only author; first_signatory = designated first among \
several (Erstunterzeichner, premier signataire, primo firmatario, 'X und Mitunterzeichnende', 'X et consorts', 'X e \
cofirmatari'); joint_author = one of several authors with equal standing, none designated first; co_signatory = \
co-signs the text (Mitunterzeichner, cosignataire, cofirmatario); supporter = printed as supporting / backing (Unterstützer, \
unterstützt von, appuyé par, soutenu par, sostenuto da); spokesperson = a person who signs or speaks for a group or committee \
that is the author (then the group/committee is the sole_author or first_signatory). Do not list executive members who \
answer.
- "dates": for the letters of the DATES list that carry a step of THIS intervention's procedure: {{"D01": ["signed"], ...}} \
with roles signed (date of the member's text / signature line), lodged (printed as lodged, submitted, received, registered: \
eingereicht, Eingang, déposé, reçu, presentata, inoltrata), session_lodged (the sitting at which it was handed in), cited \
(the date by which a heading or the answer names the intervention, e.g. 'Interpellation vom 12. März 2024'), later_step \
(announced, read, justified, developed, debated, referred / transmitted, urgency granted, deadline extended), \
answer_or_decision (date of the executive's answer, decision or letter, or of parliament's decision on it), \
other_procedural. Leave out dates of the content.
- "extra_dates": []
- "addressed_body": {{"value": \
"executive|executive_member_or_department|parliament|committee|administration|other|none_printed"}} (the body asked to \
act or to answer; by function: the government / municipal executive = executive)
- "function": {{"value": "mandate|examine_report|questions|direct_decision|other|unclear"}} (the operative request of the \
member's text: mandate = charges the executive to act, draft or present a bill / measure; examine_report = asks the \
executive to examine or study and report; questions = asks questions to be answered, requests no action; direct_decision \
= proposes a decision parliament itself takes, e.g. a drafted regulation change; priority direct_decision > mandate > \
examine_report > questions)
- "instrument_named": {{"value": "motion|postulate|interpellation|question|resolution|initiative|other|none"}} (the \
instrument the documents name: Motion/mozione, Postulat/postulato, Interpellation/interpellanza, Anfrage/Frage/question/\
interrogazione)
- "languages": {{"question": ["de"], "answer": ["de"]}} (languages the text of each document is written in: de, fr, it, \
rm, en; several only if substantial parts are in several)
- "recommendation": {{"act": "on_referral|on_fulfilment|other|none_printed|not_applicable", "value": \
"accept|reject|convert|partial|accept_and_write_off|none|not_applicable", "fits": "one|several|none|not_applicable"}} \
(on_referral = the executive recommends how parliament should decide on adopting / referring the motion or postulate; \
on_fulfilment = the executive reports on a motion / postulate parliament already adopted or referred and asks it to \
approve the report or write it off; other = by another actor or on another object; none_printed = the executive's \
answer to a motion or postulate prints none; not_applicable = interpellations, questions, or no executive answer; \
fits = how many of the value labels fit the printed wording)
- "notes": ""

DOCUMENTS (extracted text; long documents shortened):
<<<
{text}
>>>"""


def view(pid: str) -> str:
    pages = P.packet_pages(pid)
    q = "\n".join(pages["question"])
    a = "\n".join(pages["answer"])
    q = q if len(q) <= 14000 else q[:14000] + "\n[...]"
    a = a if len(a) <= 11000 else a[:8000] + "\n[...]\n" + a[-3000:]
    full = (C.PACK / f"{pid}.txt").read_text(encoding="utf-8")
    dates = "=== DATES (" + re.split(r"(?m)^=== DATES \(", full, maxsplit=1)[1] if "=== DATES (" in full else ""
    return f"=== DOCUMENT question ===\n{q}\n=== DOCUMENT answer ===\n{a}\n{dates}"


def parse(reply: str) -> dict | None:
    i, j = (reply or "").find("{"), (reply or "").rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(reply[i:j + 1])
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def run() -> dict:
    gw = import_gw("the P8 Qwen check")
    key = P.load_key()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(x)["id"] for x in OUT.read_text().splitlines() if x.strip()} if OUT.exists() else set()
    served, usd = collections.Counter(), 0.0
    with open(OUT, "a", encoding="utf-8") as f:
        for pid in sorted(key):
            if pid in done:
                continue
            choice, meta = gw.chat([dict(role="user", content=ITEM.format(text=view(pid)))], model=C.QWEN,
                                   max_tokens=MAX_TOKENS, temperature=0.0, tag=C.QWEN_TAG, tag_cap_usd=C.QWEN_CAP_USD,
                                   full=True)
            m = (meta.get("resp") or {}).get("model")
            if not m or "qwen-sea-lion" not in m.lower():
                raise RuntimeError(f"{pid}: served {m!r}, expected {C.QWEN}")
            served[m] += 1
            reply = (choice.get("message") or {}).get("content") or ""
            f.write(json.dumps(dict(id=pid, label=parse(reply), model=m, raw=reply[:4000]), ensure_ascii=False) + "\n")
            f.flush()
            usd += 0.0 if meta.get("cached") else meta.get("usd", 0.0)
    return dict(usd=round(usd, 4), served=dict(served))


def score() -> dict:
    ctx = A.context()
    gold = {g["id"]: g for g in C._jsonl(C.GOLD)}
    q = {r["id"]: r for r in C._jsonl(OUT)}
    res, invalid = {}, sorted(pid for pid in gold if not (q.get(pid) or {}).get("label"))
    for f in C.FIELDS:
        x, y = [], []
        for pid, g in sorted(gold.items()):
            lab = (q.get(pid) or {}).get("label")
            if not lab:  # no parseable label counts as a disagreement
                x.append(A.Dv.key(g["fields"][f]))
                y.append("invalid")
                continue
            try:
                d = A.derive_one({k: lab.get(k) for k in C.PARTS[f]}, pid, ctx)[f]
            except Exception:  # a malformed Qwen label counts as a disagreement
                d = dict(applicable=True, category="invalid")
            x.append(A.Dv.key(g["fields"][f]))
            y.append(A.Dv.key(d))
        res[f] = dict(n=len(x), agree=sum(a == b for a, b in zip(x, y)),
                      kappa=round(cohen_kappa(x, y), 3) if x else None,
                      gold_in_E_vs_qwen_in_E=sum((a in C.E[f]) == (b in C.E[f]) for a, b in zip(x, y)))
    out = dict(model=C.QWEN, tag=C.QWEN_TAG, n_packets=len(gold), invalid_or_missing=invalid, fields=res,
               note="Qwen's labels change no gold label and no decision")
    (C.R8 / "p8_qwen.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        print(json.dumps(run(), indent=1))
    elif cmd == "score":
        print(json.dumps(score(), indent=1))
    else:
        print(__doc__)
