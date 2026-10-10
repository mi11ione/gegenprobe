"""Closed-set pointer for virtual-affair fields (item type, decision outcome): the same mechanics as convert/pointer.py
(forced choice over a closed label set + null, summed continuation log-probabilities, margin = lp(null) - logsumexp(labels),
null iff margin > θ), with its own prompts (src/prompts/<lang>/virtual_*.txt). It never generates free text.
convert/pointer.py is pre-registration-locked and is not edited; the backend protocol is the same (llm.py).
"""
from __future__ import annotations

import hashlib

from ..paths import PROMPTS
from ..stats import logsumexp

PREFIX = {"type": {"fr": '{"type":', "de": '{"art":'}, "decision": {"fr": '{"decision":', "de": '{"beschluss":'}}
NULL = " null"
WINDOW = 6000  # chars of the minutes section given to the decision pointer: its END, where the final vote is recorded


def _template(field: str, lang: str) -> tuple[str, str]:
    t = (PROMPTS / lang / f"virtual_{field}.txt").read_text(encoding="utf-8")
    return t, f"{lang}/virtual_{field}.txt@{hashlib.sha256(t.encode()).hexdigest()[:12]}"


def choose(backend, field: str, lang: str, text: str, labels: dict[str, str], theta: float, title: str = "") -> dict:
    """labels: {key: wording}. Returns {value|None, margin, theta, lps, prompt_id, candidates}."""
    lang = lang if lang in PREFIX[field] else "fr"
    tmpl, pid = _template(field, lang)
    shown = " ou ".join(f'"{w}"' for w in labels.values()) if lang == "fr" else " oder ".join(f'"{w}"' for w in labels.values())
    user = tmpl.replace("{labels}", shown).replace("{title}", title).replace("{doc}", text)
    keys = list(labels)
    lps = backend.score(user, PREFIX[field][lang], [NULL] + [f' "{labels[k]}"' for k in keys])
    lp_null, lp_lab = lps[0], lps[1:]
    margin = lp_null - logsumexp(lp_lab)
    value = None if margin > theta else keys[max(range(len(keys)), key=lambda i: lp_lab[i])]
    return dict(value=value, margin=margin, theta=theta, lps=dict(zip(["null"] + keys, lps)), prompt_id=pid,
                candidates=len(keys), model_build=getattr(backend, "build", "?"))
