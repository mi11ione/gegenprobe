"""P5 arm G: free-generation Apertus with null allowed — the contrast to the closed-set pointer. One user message (no
system message, no prefill); the model is asked for every P5 field at once, as verbatim start/end quotes; a value counts
only if its quotes are found in the document (whitespace-insensitive), otherwise it is recorded as unlocatable and scored
as null (a "receipt check", as in the P1 naive contrast).
"""

from __future__ import annotations

import json
import re

from eval.gold6.annotate6 import find
from gegenprobe.paths import PROMPTS
from gegenprobe.qa.text import Doc

Q_BUDGET, A_BUDGET = 8000, 14000
MAX_TOKENS = 1800
SEED = 0
# prompt texts live in src/prompts/<lang>/qa_freegen.txt and src/prompts/qa_freegen_schema.txt (read verbatim)
PROMPT = {lg: (PROMPTS / lg / "qa_freegen.txt").read_text(encoding="utf-8") for lg in ("de", "fr", "it")}
SCHEMA = (PROMPTS / "qa_freegen_schema.txt").read_text(encoding="utf-8")


def _span(d: Doc, start, end):
    if not start or not end or not isinstance(start, str) or not isinstance(end, str):
        return None
    st = find(d.text, start)
    if len(st) != 1:
        st = st[:1]
    if not st:
        return None
    en = find(d.text, end, st[0][0])
    if not en:
        return None
    return dict(doc=d.role, g_start=st[0][0], g_end=en[0][1])


def parse(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def run(backend, tx: dict, lang: str) -> dict:
    lg = lang if lang in PROMPT else "de"
    q = Doc("question", "q", tx["question"])
    a = Doc("answer", "a", tx["answer"])
    user = PROMPT[lg].replace("{q}", q.text[:Q_BUDGET]).replace("{a}", a.text[:A_BUDGET]).replace("{schema}", SCHEMA)
    raw = backend.generate(user, max_tokens=MAX_TOKENS, seed=SEED)
    js = parse(raw)
    view = dict(questions=[], answers=[], submitter=None, co_signatories=[], recommendation=None, reasoning=None)
    unloc = 0
    if js is None:
        return dict(view=view, parse_ok=False, unlocatable=0, n_chars=len(raw))
    for x in js.get("questions") or []:
        if isinstance(x, dict) and isinstance(x.get("n"), int):
            sp = _span(q, x.get("start"), x.get("end"))
            unloc += sp is None
            if sp:
                view["questions"].append(dict(n=x["n"], span=sp))
    for x in js.get("answers") or []:
        if isinstance(x, dict) and isinstance(x.get("n"), int):
            sp = _span(a, x.get("start"), x.get("end"))
            unloc += sp is None and bool(x.get("start"))
            view["answers"].append(dict(n=x["n"], span=sp))
    for key in ("submitter",):
        v = js.get(key)
        if isinstance(v, str) and v.strip():
            ok = bool(find(q.text, v) or find(a.text, v))
            unloc += not ok
            view["submitter"] = dict(name=v) if ok else None
    for v in js.get("co_signatories") or []:
        if isinstance(v, str) and (find(q.text, v) or find(a.text, v)):
            view["co_signatories"].append(dict(name=v))
    r = js.get("recommendation")
    view["recommendation"] = r if r in ("accept", "reject", "partial", "convert", "none", "not_applicable") else None
    rs = js.get("reasoning")
    if isinstance(rs, dict):
        view["reasoning"] = _span(a, rs.get("start"), rs.get("end"))
        unloc += view["reasoning"] is None
    return dict(view=view, parse_ok=True, unlocatable=unloc, n_chars=len(raw))
