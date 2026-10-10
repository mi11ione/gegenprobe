"""P5 trivial baselines (no model). Both reuse the rules' question list and reply span, so they isolate the pairing step,
and share the same trivial people / recommendation / reasoning choices:
  B_order  answer n = the n-th paragraph of the reply (paragraph i <-> question i, the rest unassigned)
  B_whole  answer n = the whole reply for every question
  submitter = the first person-name-like string printed in the question document; co-signatories = none;
  recommendation = not_applicable (the most frequent dev label); reasoning = the whole answer document.
"""

from __future__ import annotations

from gegenprobe.qa import people
from gegenprobe.qa.text import Doc, boilerplate_lines, paragraphs


def all_baselines(tx: dict, rview: dict) -> dict:
    q = Doc("question", "q", tx["question"]) if tx.get("question") else None
    a = Doc("answer", "a", tx["answer"]) if tx.get("answer") else None
    cands = people.name_candidates(q) if q else []
    sub = dict(name=cands[0][0], span=dict(doc="question", g_start=cands[0][1], g_end=cands[0][2])) if cands else None
    whole = dict(doc="answer", g_start=0, g_end=len(a.text)) if a else None
    common = dict(questions=rview["questions"], question_style=rview["question_style"], submitter=sub,
                  co_signatories=[], recommendation="not_applicable", reasoning=whole)
    reply = rview["reasoning"]
    paras = []
    if a and reply:
        paras = [p for p in paragraphs(a, reply["g_start"], reply["g_end"], boilerplate_lines(a)) if len(p.text) >= 40]
    order = [dict(n=x["n"], span=(dict(doc="answer", g_start=paras[i].g0, g_end=paras[i].g1) if i < len(paras) else None))
             for i, x in enumerate(rview["questions"])]
    whole_reply = [dict(n=x["n"], span=reply) for x in rview["questions"]]
    return dict(B_order=dict(common, answers=order), B_whole=dict(common, answers=whole_reply))
