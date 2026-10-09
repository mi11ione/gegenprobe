"""Closed-set pointer: Apertus may only choose among values that exist in the document (or in OPD), or null.

Mechanics (spikes/round8 S-SHAPE arm (a), recalibrated per build in spikes/inversions F2):
  user message  = prompt template (src/prompts/<lang>/<field>.txt) with the (truncated) document
  assistant     = JSON prefix, e.g. '{"antwort_datum":'
  continuations = ' null' and one ' "DD.MM.YYYY"' per distinct date candidate of the document
  score         = summed log-probability of each continuation (exact forced choice, llm.score)
  margin        = lp(null) − logsumexp(lp(candidates))
  decision      = null if margin > θ else the argmax candidate
θ is fitted per build × prompt on dev documents (convert.calibrate) and frozen; it does not transfer across builds.

Only a single user message is ever sent (a system message or prefill to the Public AI 70B name is answered by another model;
llm.py enforces the served-model check). Free generation is never used to produce values.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from functools import lru_cache

from ..paths import PROMPTS
from ..stats import logsumexp
from . import lattice

# Char budget standing in for the spikes' 3,000 Apertus-token truncation (≈ 4 chars/token on DE/FR/IT parliamentary text;
# measured on the spike docs: 8,643 tokens ↔ 33.8k chars). Recorded in every output as `truncated_at`.
CHAR_BUDGET = 12_000
PREFIX = {
    "answer_date": {"de": '{"antwort_datum":', "fr": '{"date_reponse":', "it": '{"data_risposta":'},
    "recommendation": {"de": '{"antrag":', "fr": '{"proposition":', "it": '{"proposta":'},
    "related_affair": {"de": '{"bezug":', "fr": '{"reference":', "it": '{"riferimento":'},
}
NULL_CONT = " null"


@lru_cache(maxsize=None)
def template(field: str, lang: str, variant: str = "") -> tuple[str, str]:
    """Return (template text, prompt_id). prompt_id = <lang>/<file>@sha256[:12] — θ is keyed by it."""
    lang = lang if lang in ("de", "fr", "it") else "de"
    name = f"{field}{('_' + variant) if variant else ''}.txt"
    t = (PROMPTS / lang / name).read_text(encoding="utf-8")
    return t, f"{lang}/{name}@{hashlib.sha256(t.encode()).hexdigest()[:12]}"


def doc_text(pages: list[str], budget: int = CHAR_BUDGET) -> tuple[str, list[tuple[int, int]], bool]:
    """Join pages with newlines (form feeds dropped) and truncate. Returns (text, page offset table, truncated)."""
    offs, parts, pos = [], [], 0
    for p in pages:
        offs.append((pos, pos + len(p)))
        parts.append(p)
        pos += len(p) + 1
    full = "\n".join(parts)
    return full[:budget], offs, len(full) > budget


def ddmmyyyy(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


def _visible(c: dict, offs: list[tuple[int, int]], budget: int) -> bool:
    return offs[c["page"] - 1][0] + c["char_end"] <= budget


@dataclass
class PointerResult:
    field: str
    value: str | None
    margin: float
    theta: float
    candidates: list  # [(value, lp)]
    lp_null: float
    prompt_id: str
    model_build: str
    truncated: bool
    truncated_at: int
    span: dict | None  # provenance of the chosen value (page, char_start, char_end, quote, occurrence_rule)


def score_field(
    backend,
    field: str,
    lang: str,
    pages: list[str],
    values: list[str],
    conts: list[str],
    fill: dict | None = None,
    variant: str = "",
    budget: int = CHAR_BUDGET,
) -> tuple[list[float], float, str, bool]:
    text, _, trunc = doc_text(pages, budget)
    tmpl, pid = template(field, lang, variant)
    user = tmpl.replace("{doc}", text)
    for k, v in (fill or {}).items():
        user = user.replace("{" + k + "}", v)
    lps = backend.score(user, PREFIX[field][lang if lang in ("de", "fr", "it") else "de"], [NULL_CONT] + conts)
    return lps[1:], lps[0], pid, trunc


def decide(lp_null: float, lps: list[float], theta: float) -> tuple[int | None, float]:
    """Return (index of chosen candidate or None for null, margin)."""
    if not lps:
        return None, math.inf
    margin = lp_null - logsumexp(lps)
    if margin > theta:
        return None, margin
    return max(range(len(lps)), key=lambda i: lps[i]), margin


def locate(iso: str, cands: list[dict], pages: list[str], anchors: list[tuple[int, int]] | None = None) -> dict | None:
    """Map a chosen date back to a span. Several occurrences: nearest to an answer anchor (same page, by char distance),
    else the first occurrence. The rule used is recorded."""
    occ = [c for c in cands if c["value"] == iso]
    if not occ:
        return None
    rule = "only_occurrence" if len(occ) == 1 else "first_occurrence"
    best = occ[0]
    if len(occ) > 1 and anchors:

        def dist(c):
            return min((abs(c["char_start"] - a) if c["page"] == p else 10**9) for p, a in anchors)

        b = min(occ, key=dist)
        if dist(b) < 10**9:
            best, rule = b, "nearest_anchor"
    return dict(
        page=best["page"],
        char_start=best["char_start"],
        char_end=best["char_end"],
        quote=best["line"][:200],
        occurrence_rule=rule,
        n_occurrences=len(occ),
    )


def answer_date(
    backend, pages: list[str], lang: str, theta: float, anchors=None, variant: str = "", budget: int = CHAR_BUDGET
) -> PointerResult:
    text, offs, _ = doc_text(pages, budget)
    cands = [c for c in lattice.dates(pages) if _visible(c, offs, budget)]
    values = lattice.distinct_dates(cands)
    lps, lp_null, pid, trunc = score_field(
        backend, "answer_date", lang, pages, values, [f' "{ddmmyyyy(v)}"' for v in values], variant=variant, budget=budget
    )
    i, margin = decide(lp_null, lps, theta)
    val = None if i is None else values[i]
    return PointerResult(
        "answer_date",
        val,
        margin,
        theta,
        list(zip(values, lps)),
        lp_null,
        pid,
        getattr(backend, "build", "?"),
        trunc,
        budget,
        locate(val, cands, pages, anchors) if val else None,
    )


def recommendation(backend, pages: list[str], lang: str, theta: float, budget: int = CHAR_BUDGET) -> PointerResult:
    labels = lattice.recommendation_labels(lang)
    keys = list(labels)
    lps, lp_null, pid, trunc = score_field(
        backend, "recommendation", lang, pages, keys, [f' "{labels[k]}"' for k in keys], budget=budget
    )
    i, margin = decide(lp_null, lps, theta)
    return PointerResult(
        "recommendation",
        None if i is None else keys[i],
        margin,
        theta,
        list(zip(keys, lps)),
        lp_null,
        pid,
        getattr(backend, "build", "?"),
        trunc,
        budget,
        None,
    )


def related_affair(
    backend, pages: list[str], lang: str, body: str, own_number: str | None, theta: float, index=None, budget: int = CHAR_BUDGET
) -> PointerResult:
    text, offs, _ = doc_text(pages, budget)
    own = lattice._norm_num(own_number) if own_number else None
    cands = [c for c in lattice.affair_numbers(pages, body, index) if _visible(c, offs, budget) and c["value"] != own]
    values = list(dict.fromkeys(c["value"] for c in cands))
    if not values:
        return PointerResult(
            "related_affair", None, math.inf, theta, [], 0.0, "", getattr(backend, "build", "?"), False, budget, None
        )
    lps, lp_null, pid, trunc = score_field(
        backend,
        "related_affair",
        lang,
        pages,
        values,
        [f' "{v}"' for v in values],
        fill={"own": own_number or "?"},
        budget=budget,
    )
    i, margin = decide(lp_null, lps, theta)
    val = None if i is None else values[i]
    span = None
    if val:
        c = next(c for c in cands if c["value"] == val)
        span = dict(
            page=c["page"],
            char_start=c["char_start"],
            char_end=c["char_end"],
            quote=re.sub(r"\s+", " ", c["ctx"])[:200],
            occurrence_rule="first_occurrence",
            n_occurrences=sum(x["value"] == val for x in cands),
        )
    return PointerResult(
        "related_affair",
        val,
        margin,
        theta,
        list(zip(values, lps)),
        lp_null,
        pid,
        getattr(backend, "build", "?"),
        trunc,
        budget,
        span,
    )
