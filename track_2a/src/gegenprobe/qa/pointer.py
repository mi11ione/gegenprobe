"""Apertus as a closed-set pointer for the Q/A fields (never free generation of values).

Same mechanics as `convert.pointer` (spikes round 8, S-SHAPE arm (a)): one user message with the prompt
(src/prompts/<lang>/qa_<field>.txt), an assistant JSON prefix, and one continuation per member of the closed set plus
` null`; each continuation is scored by its summed log-probability (`backend.score`, exact forced choice). margin =
lp(null) - logsumexp(lp(candidates)); null iff margin > θ, else the argmax candidate. θ per field is fitted on the P5 dev
labels and frozen before P5.

Closed sets:
  pair            for one answer paragraph: the member's question numbers 1..k (questions printed in the prompt), or null
  recommendation  the printed candidate sentences (numbered), or null
  submitter       the person-name strings printed in the question document (numbered), or null
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from functools import lru_cache

from ..paths import PROMPTS
from ..stats import logsumexp

PREFIX = {
    "pair": {"de": '{"frage":', "fr": '{"question":', "it": '{"domanda":'},
    "recommendation": {"de": '{"satz":', "fr": '{"phrase":', "it": '{"frase":'},
    "submitter": {"de": '{"urheber":', "fr": '{"auteur":', "it": '{"autore":'},
}
NULL = " null"
PASSAGE_BUDGET = 2500
QUESTION_BUDGET = 400  # per question in the pair prompt
DOC_BUDGET = 6000


def _lg(lang: str | None) -> str:
    return lang if lang in ("de", "fr", "it") else "de"


@lru_cache(maxsize=None)
def template(field: str, lang: str) -> tuple[str, str]:
    t = (PROMPTS / _lg(lang) / f"qa_{field}.txt").read_text(encoding="utf-8")
    return t, f"{_lg(lang)}/qa_{field}.txt@{hashlib.sha256(t.encode()).hexdigest()[:12]}"


@dataclass
class Choice:
    field: str
    index: int | None  # 0-based index into the closed set, None = null
    margin: float
    theta: float
    lps: list[float]
    lp_null: float
    prompt_id: str
    model_build: str
    n_candidates: int


def decide(lp_null: float, lps: list[float], theta: float) -> tuple[int | None, float]:
    if not lps:
        return None, math.inf
    margin = lp_null - logsumexp(lps)
    if margin > theta:
        return None, margin
    return max(range(len(lps)), key=lambda i: lps[i]), margin


def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def choose(backend, field: str, lang: str, fill: dict[str, str], n: int, theta: float) -> Choice:
    tmpl, pid = template(field, lang)
    user = tmpl
    for k, v in fill.items():
        user = user.replace("{" + k + "}", v)
    conts = [NULL] + [f" {i}" for i in range(1, n + 1)]
    lps = backend.score(user, PREFIX[field][_lg(lang)], conts)
    i, margin = decide(lps[0], lps[1:], theta)
    return Choice(field, i, margin, theta, lps[1:], lps[0], pid, getattr(backend, "build", "?"), n)


def pair(backend, lang: str, questions: list[str], passage: str, theta: float) -> Choice:
    ql = "\n".join(f"{i}. {_clip(q, QUESTION_BUDGET)}" for i, q in enumerate(questions, 1))
    return choose(backend, "pair", lang, dict(questions=ql, passage=_clip(passage, PASSAGE_BUDGET)), len(questions), theta)


def recommendation(backend, lang: str, sentences: list[str], theta: float) -> Choice:
    sl = "\n".join(f"{i}. {_clip(s, 500)}" for i, s in enumerate(sentences, 1))
    return choose(backend, "recommendation", lang, dict(sentences=sl), len(sentences), theta)


def submitter(backend, lang: str, doc: str, names: list[str], theta: float) -> Choice:
    nl = "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    return choose(backend, "submitter", lang, dict(doc=doc[:DOC_BUDGET], names=nl), len(names), theta)
