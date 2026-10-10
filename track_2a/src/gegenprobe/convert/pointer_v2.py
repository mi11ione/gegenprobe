"""Closed-set pointer v2 for the answer date: a presence question, then a choice among dates shown with their printed line.

v1 (convert/pointer.py) scores ' null' against every date string ' "DD.MM.YYYY"' after one question and abstains when the
null margin exceeds a fitted θ. Two weaknesses were seen in the P1/P2 analyses: (i) the date continuations carry no
context, so the model must recall which printed date plays which role (decision, dispatch, deposit, footer), and (ii) the
null decision is entangled with the multi-token date strings (θ ≈ 10 nats largely offsets token length, J5).

v2 keeps the output a closed set (one of the printed dates, or null) and splits the decision in two forced choices:

  stage 1  presence   user = document + "does this document contain the executive's answer?"
                      (src/prompts/<lang>/answer_present.txt)
                      prefix '{"antwort_enthalten":'  continuations ' "ja"' / ' "nein"'  (FR oui/non, IT sì/no)
                      m_absent = lp(no) − lp(yes)
  stage 2  choice     user = document + every distinct printed date as a lettered option with the line(s) it is printed on,
                      plus one option "none" (src/prompts/<lang>/answer_date_mcq.txt)
                      prefix '{"wahl":'  continuations ' "A"', ' "B"', … (one letter each: equal token length)
                      m_mcq = lp(none letter) − logsumexp(lp(date letters))

  decision (config)   null  if  m_absent > θ_presence   (or, for config "presence+mcq_null", also if m_mcq > θ_mcq)
                      else  the date whose letter has the highest log-probability.

The options are built only from the lattice (convert/lattice.dates) on the visible part of the document, so the chosen value
is always a printed date with a span (pointer.locate). Only a single user message is sent per call, with an assistant
prefill, to a name on llm.PREFILL_OK (the served model is checked on every call by llm.py).
"""

from __future__ import annotations

import hashlib
import math
import re
import string
from dataclasses import dataclass, field
from functools import lru_cache

from ..paths import PROMPTS
from ..stats import logsumexp
from . import lattice
from .pointer import CHAR_BUDGET, _visible, ddmmyyyy, doc_text, locate

LANGS = ("de", "fr", "it")
PRESENCE_PREFIX = {"de": '{"antwort_enthalten":', "fr": '{"reponse_presente":', "it": '{"risposta_presente":'}
PRESENCE_CONT = {"de": (' "ja"', ' "nein"'), "fr": (' "oui"', ' "non"'), "it": (' "sì"', ' "no"')}
MCQ_PREFIX = {"de": '{"wahl":', "fr": '{"choix":', "it": '{"scelta":'}
NONE_TEXT = {
    "answer_date_mcq": {
        "de": "keines: das Dokument enthält keine Antwort der Regierung",
        "fr": "aucune : le document ne contient pas de réponse du gouvernement",
        "it": "nessuna: il documento non contiene una risposta del governo",
    },
    "answer_decision_mcq": {
        "de": "keines: im Dokument steht kein Beschlussdatum der Regierung",
        "fr": "aucune : le document ne contient pas de date de décision du gouvernement",
        "it": "nessuna: il documento non contiene una data di decisione del governo",
    },
    "answer_dispatch_mcq": {
        "de": "keines: im Dokument steht kein Datum eines Antwortschreibens der Regierung",
        "fr": "aucune : le document ne contient pas de date d'une lettre de réponse du gouvernement",
        "it": "nessuna: il documento non contiene la data di una lettera di risposta del governo",
    },
}
ROLE_TEMPLATES = ("answer_decision_mcq", "answer_dispatch_mcq")  # precedence: decision, then dispatch (the gold guide)
LETTERS = string.ascii_uppercase  # 26 options; documents with more distinct dates keep the first 25 in reading order
MAX_DATES = len(LETTERS) - 1
LINE_CHARS = 160
LINES_PER_DATE = 2


def _lang(lang: str | None) -> str:
    return lang if lang in LANGS else "de"


@lru_cache(maxsize=None)
def template(name: str, lang: str) -> tuple[str, str]:
    t = (PROMPTS / _lang(lang) / f"{name}.txt").read_text(encoding="utf-8")
    return t, f"{_lang(lang)}/{name}.txt@{hashlib.sha256(t.encode()).hexdigest()[:12]}"


def _clip(line: str, raw: str) -> str:
    """One printed line, whitespace-collapsed, at most LINE_CHARS characters, centred on the date if it is longer."""
    s = re.sub(r"\s+", " ", line).strip()
    if len(s) <= LINE_CHARS:
        return s
    r = re.sub(r"\s+", " ", raw)
    i = max(0, s.find(r))
    a = max(0, min(i - LINE_CHARS // 2, len(s) - LINE_CHARS))
    return ("…" if a > 0 else "") + s[a : a + LINE_CHARS] + ("…" if a + LINE_CHARS < len(s) else "")


def options(pages: list[str], budget: int = CHAR_BUDGET) -> tuple[list[str], list[str], list[dict]]:
    """(distinct ISO values in reading order, one option line per value, visible candidates). An option line is
    'DD.MM.YYYY — «line» | «other line»' with up to LINES_PER_DATE distinct printed lines of that date."""
    _, offs, _ = doc_text(pages, budget)
    cands = [c for c in lattice.dates(pages) if _visible(c, offs, budget)]
    values = lattice.distinct_dates(cands)[:MAX_DATES]
    lines = []
    for v in values:
        seen: list[str] = []
        for c in cands:
            if c["value"] == v:
                s = _clip(c["line"], c["raw"])
                if s and s not in seen:
                    seen.append(s)
            if len(seen) >= LINES_PER_DATE:
                break
        lines.append(f"{ddmmyyyy(v)} — " + " | ".join(f"«{s}»" for s in seen))
    return values, lines, cands


def presence(backend, pages: list[str], lang: str, budget: int = CHAR_BUDGET) -> dict:
    lg = _lang(lang)
    text, _, trunc = doc_text(pages, budget)
    tmpl, pid = template("answer_present", lg)
    yes, no = PRESENCE_CONT[lg]
    lp_yes, lp_no = backend.score(tmpl.replace("{doc}", text), PRESENCE_PREFIX[lg], [yes, no])
    return dict(lp_yes=lp_yes, lp_no=lp_no, m_absent=lp_no - lp_yes, prompt_id=pid, truncated=trunc)


def mcq(backend, pages: list[str], lang: str, budget: int = CHAR_BUDGET, name: str = "answer_date_mcq") -> dict:
    """Lettered choice among the printed dates (with their lines) plus one 'none' option, prompt `name`."""
    lg = _lang(lang)
    values, lines, cands = options(pages, budget)
    if not values:
        return dict(values=[], lps=[], lp_none=0.0, m_mcq=math.inf, prompt_id="", cands=cands)
    text, _, trunc = doc_text(pages, budget)
    tmpl, pid = template(name, lg)
    none_label = LETTERS[len(values)]
    opts = "\n".join(f"{LETTERS[i]}: {s}" for i, s in enumerate(lines)) + f"\n{none_label}: {NONE_TEXT[name][lg]}"
    user = tmpl.replace("{doc}", text).replace("{options}", opts).replace("{null_label}", none_label)
    conts = [f' "{LETTERS[i]}"' for i in range(len(values) + 1)]
    lps = backend.score(user, MCQ_PREFIX[lg], conts)
    return dict(values=values, lps=lps[:-1], lp_none=lps[-1], m_mcq=lps[-1] - logsumexp(lps[:-1]), prompt_id=pid,
                truncated=trunc, cands=cands, n_options=len(values) + 1)


GUIDED_PREFIX = '{"antwort_datum":'  # the guided prompt asks for this key in every language


def guided(backend, pages: list[str], lang: str, budget: int = CHAR_BUDGET) -> dict:
    """Closed-set reading of the guided prompt (src/prompts/<lang>/naive_guided.txt): after the prefix '{"antwort_datum":',
    score ' null' and one ' "YYYY-MM-DD"' per distinct printed date (the format the prompt asks for). Argmax with margin
    θ = 0 is constrained greedy decoding of that prompt; m_guided = lp(null) − logsumexp(lp(dates))."""
    lg = _lang(lang)
    values, _, cands = options(pages, budget)
    if not values:
        return dict(values=[], lps=[], lp_null=0.0, m_guided=math.inf, prompt_id="", cands=cands, truncated=False)
    text, _, trunc = doc_text(pages, budget)
    tmpl, pid = template("naive_guided", lg)
    lps = backend.score(tmpl.replace("{doc}", text), GUIDED_PREFIX, [" null"] + [f' "{v}"' for v in values])
    return dict(values=values, lps=lps[1:], lp_null=lps[0], m_guided=lps[0] - logsumexp(lps[1:]), prompt_id=pid,
                cands=cands, truncated=trunc)


@dataclass
class Config:
    """A frozen v2 configuration.
    gate   'presence': null iff m_absent > theta_presence (stage 1); 'none': no gate (every document with a date gets one).
    pick   'role': the gold guide's precedence applied in code: the decision-date choice if its best date letter beats
           its 'none' letter, else the dispatch-date choice if it does, else the answer-date choice (argmax over dates);
           'answer': the answer-date choice only (argmax over dates)."""
    gate: str = "presence"
    theta_presence: float = 0.0
    pick: str = "role"
    name: str = "v2"


@dataclass
class V2Result:
    value: str | None
    m_absent: float
    stage: str  # which step decided: 'no_dates' | 'presence' | 'decision' | 'dispatch' | 'answer'
    candidates: list  # [(ISO, lp of its letter)] of the deciding choice
    span: dict | None
    prompt_ids: list = field(default_factory=list)
    model_build: str = "?"
    truncated: bool = False
    calls: int = 0


def pick_from(choices: dict) -> tuple[str | None, str]:
    """choices: {template name: mcq() output}. Returns (value, stage) by the role precedence (see Config.pick)."""
    for name, stage in zip(ROLE_TEMPLATES, ("decision", "dispatch")):
        q = choices.get(name)
        if q and q["values"] and max(q["lps"]) > q["lp_none"]:
            return q["values"][max(range(len(q["values"])), key=lambda i: q["lps"][i])], stage
    q = choices.get("answer_date_mcq")
    if q and q["values"]:
        return q["values"][max(range(len(q["values"])), key=lambda i: q["lps"][i])], "answer"
    return None, "answer"


def answer_date(backend, pages: list[str], lang: str, cfg: Config, anchors=None, budget: int = CHAR_BUDGET) -> V2Result:
    """Stage 1 (presence) then stage 2 (role choices, answer choice only if neither role names a date). Calls are made
    lazily in that order, so a document stopped by the gate costs two calls."""
    build = getattr(backend, "build", "?")
    values, _, cands = options(pages, budget)
    if not values:  # nothing printed to point at: no model call
        return V2Result(None, math.inf, "no_dates", [], None, model_build=build)
    pids, calls = [], 0
    m_absent = -math.inf
    if cfg.gate == "presence":
        p = presence(backend, pages, lang, budget)
        pids.append(p["prompt_id"])
        calls += 2
        m_absent = p["m_absent"]
        if m_absent > cfg.theta_presence:
            return V2Result(None, m_absent, "presence", [], None, pids, build, p["truncated"], calls)
    choices = {}
    names = (*ROLE_TEMPLATES, "answer_date_mcq") if cfg.pick == "role" else ("answer_date_mcq",)
    for name in names:
        q = mcq(backend, pages, lang, budget, name=name)
        choices[name] = q
        pids.append(q["prompt_id"])
        calls += q["n_options"]
        val, stage = pick_from(choices)
        if stage != "answer" or name == "answer_date_mcq":
            break
    q = choices["answer_date_mcq" if stage == "answer" else ROLE_TEMPLATES[stage == "dispatch"]]
    return V2Result(val, m_absent, stage, list(zip(q["values"], q["lps"])),
                    locate(val, cands, pages, anchors) if val else None, pids, build, q["truncated"], calls)
