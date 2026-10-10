"""Closed-set answer-date reader v2: a presence question, then a date that must be printed in the document, or null.

v1 (convert/pointer.py) scores ' null' against every printed date string after one question and abstains when the null
margin exceeds a fitted θ. On P1 dev and P2 its errors were mostly role errors between two printed dates (decision vs
letter date) and dates given to answerless documents. v2 keeps the output closed (a printed date with its span, or null):

  stage 1  presence   document + "does this document contain the executive's answer?" (src/prompts/<lang>/answer_present.txt)
                      forced choice ' "ja"' / ' "nein"' (FR oui/non, IT sì/no); m_absent = lp(no) − lp(yes)
                      null iff m_absent > θ_presence (θ fitted on P1 dev, frozen per build)
  stage 2  date       pick 'gen_then_role' (the frozen P6 configuration, data/p6/v2_config.json):
                      (a) free generation with the guide-derived instructions (src/prompts/<lang>/naive_guided.txt); the
                          answer is kept only if it is one of the printed dates (lattice), and gets that date's span;
                      (b) otherwise the role choices, two lettered closed-set choices over the printed dates shown with
                          their lines: decision date (answer_decision_mcq) or none, then letter date
                          (answer_dispatch_mcq) or none; the gold guide's precedence (decision, else letter) is applied
                          in code; if neither names a date, the answer-date choice (answer_date_mcq), argmax over dates.
                      picks 'role' and 'answer' are the development alternatives (results/p6/dev_variants__*.txt).

The configuration was chosen on DEV2 by a rule written before its labels (eval/p6/DEV2_SELECTION.md,
results/p6/dev2_selection.json). Every forced choice is one user message plus an assistant prefill, sent only to a name on
llm.PREFILL_OK; generation is one plain user message; llm.py checks the served model on every call.
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


# ------------------------------------------------------------------------------- guided generation, then point (stage 2, C)
_MON = {}
for _names in (
    ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"],
    ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre",
     "dicembre"],
):
    for _i, _n in enumerate(_names):
        _MON[_n] = _i + 1
        _MON[_n.translate(str.maketrans("äàâéèêëîïôöûüç", "aaaeeeeiioouuc"))] = _i + 1
_NULLISH = {"", "null", "none", "nicht angegeben", "keine angabe", "unbekannt", "non indiqué", "non indicato", "n/a"}


def _json_field(g: str, key: str = "antwort_datum"):
    """The value of `key` in a generated JSON object (same reading as eval/naive_baseline.parse)."""
    import json

    s = re.sub(r"^```(json)?|```$", "", (g or "").strip()).strip()
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict):
                return d.get(key)
        except Exception:
            pass
    m = re.search(rf'"{key}"\s*:\s*(null|"((?:[^"\\]|\\.)*)")', s)
    return None if not m or m.group(1) == "null" else m.group(2)


def read_date(v) -> str | None:
    """ISO date from a generated value, or None (same reading as eval/posthoc_r3.to_iso_fixed)."""
    import datetime as _dt

    if v is None or (isinstance(v, str) and v.strip().lower() in _NULLISH):
        return None
    s = str(v).strip()

    def mk(y, mo, d):
        try:
            return _dt.date(y, mo, d).isoformat()
        except ValueError:
            return None

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s[:10]):
        return s[:10]
    m = re.fullmatch(r"(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{4})", s)
    if m:
        return mk(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"(\d{1,2})(?:er|\.)?[\s\-]+([^\W\d_]+)[\s\-.]+(\d{4})", s)
    if m and m.group(2).lower() in _MON:
        return mk(int(m.group(3)), _MON[m.group(2).lower()], int(m.group(1)))
    c = lattice.dates([s])
    return c[0]["value"] if c else None


def generate_then_point(backend, pages: list[str], lang: str, seed: int = 0, budget: int = CHAR_BUDGET,
                        max_tokens: int = 60) -> dict:
    """Free generation with the guided prompt; the answer is kept only if it is one of the dates printed in the document
    (visible part), so the value always has a span. Returns {date (printed ISO or None), raw, printed: bool}."""
    values, _, _ = options(pages, budget)
    text, _, _ = doc_text(pages, budget)
    tmpl, pid = template("naive_guided", _lang(lang))
    g = backend.generate(tmpl.replace("{doc}", text), max_tokens=max_tokens, seed=seed)
    raw = _json_field(g)
    iso = read_date(raw)
    return dict(date=iso if iso in values else None, raw=raw, iso=iso, printed=iso in values, prompt_id=pid)


@dataclass
class Config:
    """A frozen v2 configuration.
    gate   'presence': null iff m_absent > theta_presence (stage 1); 'none': no gate (every document with a date gets one).
    pick   'role': the gold guide's precedence applied in code: the decision-date choice if its best date letter beats
           its 'none' letter, else the dispatch-date choice if it does, else the answer-date choice (argmax over dates);
           'answer': the answer-date choice only (argmax over dates);
           'gen_then_role': guided free generation, kept only if it names a printed date, else the 'role' pick.
    gen_max_tokens: generation budget of 'gen_then_role'."""
    gate: str = "presence"
    theta_presence: float = 0.0
    pick: str = "role"
    gen_max_tokens: int = 60
    name: str = "v2"


@dataclass
class V2Result:
    value: str | None
    m_absent: float
    stage: str  # which step decided: 'no_dates' | 'presence' | 'generation' | 'decision' | 'dispatch' | 'answer'
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


def answer_date(backend, pages: list[str], lang: str, cfg: Config, anchors=None, budget: int = CHAR_BUDGET,
                seed: int = 0) -> V2Result:
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
    if cfg.pick == "gen_then_role":
        g = generate_then_point(backend, pages, lang, seed=seed, budget=budget, max_tokens=cfg.gen_max_tokens)
        pids.append(g["prompt_id"])
        calls += 1
        if g["date"]:
            return V2Result(g["date"], m_absent, "generation", [], locate(g["date"], cands, pages, anchors), pids, build,
                            False, calls)
    choices = {}
    names = (*ROLE_TEMPLATES, "answer_date_mcq") if cfg.pick in ("role", "gen_then_role") else ("answer_date_mcq",)
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
