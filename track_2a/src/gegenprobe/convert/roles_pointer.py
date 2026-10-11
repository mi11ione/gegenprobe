"""Apertus as a closed-set reader of author ROLES: code locates the candidates, the model answers closed questions about
each one, and code composes the role from the answers by the P8 guide's definitions.

    roles_pointer.read(backend, q_pages, a_pages, cands, lang, config) -> dict(actors=[...], decisions=[...])

Division of labour (P10, eval/prereg10/PREREG10.md):
  * WHO: `convert.role_candidates.candidates` (no model) returns every person or body the documents print that could be
    an author, each with its located span. The model never adds, edits or spells a name.
  * WHAT: one user message per question and candidate shows excerpts of the two documents (the VIEW: head and tail of
    the member's text, head of the answer), the list of printed candidates and the lines where this candidate is
    printed. The assistant message is prefilled with a JSON prefix and the log-probability of the next token is read.
    Two modes (config `mode`):

    staged (questions true/false; src/prompts/<lang>/role_author.txt, role_first.txt)
        author  every candidate: did it lodge or co-sign THIS intervention (author, signatory, co-signatory, supporter,
                a group or committee that lodges it, or who signs for one)?  p_author = P(true) / (P(true) + P(false))
        first   every person candidate: do the documents designate it as THE first signatory ("Erstunterzeichner/in",
                "X und Mitunterzeichnende", "X et consorts", "primo firmatario X", a heading that names it alone before
                a list of further signatures)?  Asked in each wording the config lists (`prompt_first`); p_first = the
                geometric mean of their P(true)
        (optional, `prompt_neg`) the negated author question; p_author = mean(P(true), 1 - P(true | negated))
        Composition in code (the P8 guide, eval/p8/GUIDE_P8.md §2; thresholds tau, tau_first from the config):
          authors = candidates with p_author >= tau; G = the groups/committees among them, P = the persons;
          G: one -> sole_author; several -> the first printed first_signatory, the others co_signatory;
          P with G: if some person has p_first >= tau_first, the one with the highest p_first is first_signatory and
            the other persons co_signatory; else every person is spokesperson (signs or speaks for the group);
          P without G: some p_first >= tau_first -> that person (highest p_first) first_signatory, the others
            co_signatory (also when it is the only person: "X et consorts" with no consort listed, which with
            `lone_first_needs_cue` requires a printed co-signing cue, COSIGN_CUE, in the documents); else one person
            -> sole_author, several -> joint_author.
        A supporter is not composed (no question asks for it); the P8 guide's `supporter` and `other` stay misses.

    letters (one seven-way choice per candidate; src/prompts/<lang>/role_pointer.txt; kept as the first development
        variant): A sole_author B joint_author C first_signatory D co_signatory E supporter F spokesperson
        G not_an_author; author iff 1 - p(G) >= tau, the role of highest p among A-F, then the coherence rules in the
        config (sole_to_joint, single_joint, spokes_needs_body).

  * Reading the next token. Remote backends (gateway, OpenAI-compatible vLLM): one request with max_tokens=1, logprobs
    and top_logprobs=TOP_K; an option's log-probability is that of the token equal to it (else equal after stripping
    whitespace); an option outside the top TOP_K gets the smallest returned log-probability (an upper bound) and is
    flagged. For single-token options this equals the exact forced-choice log-probability of `llm.score`, read in one
    request. Local GGUF: `backend.score(user, prefix, options)`, the exact forced choice.
  * Every output names one candidate, so its value is the printed text at the span code located (doc, page, char_start,
    char_end, quote_sha256). Nothing is generated.

Only a single user message plus an assistant prefill is ever sent, and only to names on `llm.PREFILL_OK` (the Public AI
name `swiss-ai/apertus-v1.5-8b`, which serves the 70B weights; a prefill to the -70b name is answered by another model).
The served model is checked on every live response (`llm._Remote._check`: ServedModelMismatch); every response is kept
in the hash-keyed model cache (llm.ModelCache), so a run replays offline (GP_OFFLINE=1).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
from functools import lru_cache

from .. import llm
from ..paths import PROMPTS

POINTER_VERSION = "rolepointer-2"
LANGS = ("de", "fr", "it")
ROLES = ("sole_author", "joint_author", "first_signatory", "co_signatory", "supporter", "spokesperson", "not_an_author")
AUTHOR_ROLES = ROLES[:-1]
LETTERS = "ABCDEFG"
PREFIX = {"de": '{"wahl": "', "fr": '{"choix": "', "it": '{"scelta": "'}
BOOL_PREFIX = {
    "role_author": {"de": '{"eingereicht":', "fr": '{"depose":', "it": '{"presentato":'},
    "role_first": {"de": '{"erstunterzeichnend":', "fr": '{"premier_signataire":', "it": '{"primo_firmatario":'},
    "role_author_v2": {"de": '{"eingereicht":', "fr": '{"depose":', "it": '{"presentato":'},
    "role_notauthor_v2": {"de": '{"nur_erwaehnt":', "fr": '{"seulement_cite":', "it": '{"solo_citato":'},
    "role_first_v2": {"de": '{"hervorgehoben":', "fr": '{"mis_en_avant":', "it": '{"messo_in_evidenza":'},
}
BOOL = ("true", "false")
WHERE = {"de": ("Vorstoss", "Antwort", "S."), "fr": ("intervention", "réponse", "p."), "it": ("atto", "risposta", "p.")}
TOP_K = 20
LINE_CHARS = 220
DEFAULT_CONFIG = dict(mode="staged", prompt="role_author", prompt_neg=None, prompt_first="role_first", tau=0.5,
                      tau_first=0.5, lone_first_needs_cue=False, coherence=[], q_head=2500, q_tail=1500, a_head=1000,
                      max_lines=2)
# a printed cue that someone co-signs: only with it can a person alone be a first signatory ("X et consorts")
COSIGN_CUE = re.compile(r"(?i)erstunterzeichn|mitunterzeichn|konsorten|consorts|cosignataire|premi(?:er|ère)\s+signataire|"
                        r"cofirmatari|prim[oa]\s+firmatari")


def _lang(lang: str | None) -> str:
    return lang if lang in LANGS else "de"


@lru_cache(maxsize=None)
def template(lang: str, name: str) -> tuple[str, str]:
    t = (PROMPTS / _lang(lang) / f"{name}.txt").read_text(encoding="utf-8")
    return t, f"{_lang(lang)}/{name}.txt@{hashlib.sha256(t.encode()).hexdigest()[:12]}"


# ------------------------------------------------------------------------------------------------------------ the view
def view(q: list[str], a: list[str], cfg: dict) -> dict:
    """Excerpts every candidate of the affair sees: the head and the tail of the member's text, the head of the answer."""
    qt, at = "\n".join(q or []), "\n".join(a or [])
    h, t = cfg["q_head"], cfg["q_tail"]
    q_head, q_tail = (qt, "") if len(qt) <= h + t else (qt[:h], qt[-t:])
    return dict(q_head=q_head.strip(), q_tail=q_tail.strip(), a_head=at[:cfg["a_head"]].strip())


def _line_at(page: str, s: int, e: int) -> str:
    """The printed line holding the span, with the line before it (labels often stand above the names)."""
    a = page.rfind("\n", 0, s) + 1
    a0 = page.rfind("\n", 0, max(0, a - 1)) + 1 if a > 0 else a
    b = page.find("\n", e)
    b = len(page) if b < 0 else b
    prev = re.sub(r"\s+", " ", page[a0:a]).strip()
    ln = re.sub(r"\s+", " ", page[a:b]).strip()
    if len(ln) > LINE_CHARS:
        mid = (s - a) + (e - s) // 2
        lo = max(0, mid - LINE_CHARS // 2)
        ln = "…" + ln[lo:lo + LINE_CHARS] + "…"
    return f"{prev} / {ln}" if prev and len(prev) <= 120 else ln


def occurrence_lines(c: dict, q: list[str], a: list[str], lang: str, n: int) -> str:
    wq, wa, pg = WHERE[_lang(lang)]
    out = []
    for o in c["occurrences"][:n]:
        pages = q if o["doc"] == "question" else a
        if not pages or o["page"] > len(pages):
            continue
        where = wq if o["doc"] == "question" else wa
        out.append(f"- ({where}, {pg} {o['page']}) «{_line_at(pages[o['page'] - 1], o['char_start'], o['char_end'])}»")
    return "\n".join(out)


def prompt(c: dict, cands: list[dict], v: dict, q: list[str], a: list[str], lang: str, cfg: dict,
           name: str | None = None) -> tuple[str, str]:
    tmpl, pid = template(lang, name or cfg["prompt"])
    names = "; ".join(f"{i}. {x['value']}" for i, x in enumerate(cands, 1))
    user = (tmpl.replace("{q_head}", v["q_head"]).replace("{q_tail}", v["q_tail"] or "—")
            .replace("{a_head}", v["a_head"] or "—").replace("{names}", names)
            .replace("{lines}", occurrence_lines(c, q, a, lang, cfg["max_lines"]))
            .replace("{name}", c["value"]))
    return user, pid


# ------------------------------------------------------------------------------------------------------------ tokens
def _option_lps(top: dict[str, float], options) -> tuple[list[float], list[str]]:
    floor = min(top.values()) if top else -1e9
    lps, missing = [], []
    for o in options:
        if o in top:
            lps.append(top[o])
            continue
        alt = [v for k, v in top.items() if k.strip() == o]
        if alt:
            lps.append(max(alt))
        else:
            lps.append(floor)
            missing.append(o)
    return lps, missing


def _post_openai(backend, payload: dict) -> tuple[dict, dict]:
    body = {k: v for k, v in payload.items() if not k.startswith("_")}
    req = urllib.request.Request(backend.base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {backend.key}", "Content-Type": "application/json",
                                          "User-Agent": "hackapertus-research/0.1"})
    for i in range(6):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < 5:
                time.sleep(15 * (i + 1))
                continue
            raise
    return d["choices"][0], {k: v for k, v in d.items() if k not in ("choices", "usage")}


def _post_gateway(backend, payload: dict) -> tuple[dict, dict]:
    extra = {k: v for k, v in payload.items() if k not in ("model", "messages", "max_tokens", "temperature")}
    for i in range(6):
        try:
            choice, meta = backend.gw.chat(payload["messages"], model=payload["model"], max_tokens=payload["max_tokens"],
                                           temperature=payload["temperature"], tag=backend.tag, tag_cap_usd=backend.cap,
                                           full=True, nocache=True, **extra)
            return choice, meta["resp"]
        except Exception as e:  # 429 / disconnects; never retry a budget refusal
            if "BUDGET" in str(e) or i == 5:
                raise
            time.sleep(20 * (i + 1))
    raise RuntimeError("unreachable")


def next_token_top(backend, user: str, prefix: str) -> dict:
    """One remote request: the top-K next tokens after the prefilled prefix (cached; served model checked)."""
    if backend.model not in llm.PREFILL_OK:
        raise ValueError(f"{backend.model} does not accept an assistant prefill (another model answers); no forced choice")
    payload = dict(model=backend.model, temperature=0.0, max_tokens=1,
                   messages=[{"role": "user", "content": user}, {"role": "assistant", "content": prefix}],
                   continue_final_message=True, add_generation_prompt=False, logprobs=True, top_logprobs=TOP_K)
    k = llm.ModelCache.key(backend.build, "next_top", payload)
    hit = backend.cache.get(k)
    if hit is not None:
        return hit
    if backend.offline:
        raise llm.CacheMiss(k)
    choice, resp = (_post_gateway if backend.kind == "gateway" else _post_openai)(backend, payload)
    backend._check(resp)  # the served model must be the requested one (ServedModelMismatch otherwise)
    content = ((choice.get("logprobs") or {}).get("content") or [{}])[0]
    top = {t["token"]: t["logprob"] for t in content.get("top_logprobs") or []}
    if not top:
        raise RuntimeError("the server returned no top_logprobs")
    out = dict(resp={x: resp.get(x) for x in ("id", "model", "system_fingerprint")}, top=top, token=content.get("token"),
               ts=round(time.time()))
    backend.cache.put(k, out)
    return out


def option_logprobs(backend, user: str, prefix: str, options, exact_conts=None) -> dict:
    """Log-probabilities of single-token options after the prefix (remote: one top-K request; GGUF: exact)."""
    if getattr(backend, "kind", None) in ("gateway", "openai"):
        r = next_token_top(backend, user, prefix)
        lps, missing = _option_lps(r["top"], options)
        return dict(lps=lps, missing=missing, method=f"next_token_top{TOP_K}",
                    fingerprint=(r.get("resp") or {}).get("system_fingerprint"))
    lps = backend.score(user, prefix, list(exact_conts or options))
    return dict(lps=lps, missing=[], method="forced_choice", fingerprint=None)


def softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    s = sum(e)
    return [x / s for x in e]


def p_true(backend, user: str, prefix: str) -> dict:
    r = option_logprobs(backend, user, prefix, BOOL, exact_conts=[" true", " false"])
    return dict(r, p=softmax(r["lps"])[0])


# ------------------------------------------------------------------------------------------------------------ staged
def compose(decisions: list[dict], tau: float, tau_first: float, cue: bool = True) -> list[dict]:
    """Roles from p_author / p_first by the P8 guide (module docstring). Decisions are in reading order. `cue` = False
    (lone_first_needs_cue and the documents print no co-signing cue): a person alone is never a first signatory."""
    for d in decisions:
        d["role"] = "not_an_author"
    auth = [d for d in decisions if d["p_author"] >= tau]
    G = [d for d in auth if d["kind"] != "person"]
    P = [d for d in auth if d["kind"] == "person"]
    for i, d in enumerate(G):
        d["role"] = "sole_author" if len(G) == 1 else ("first_signatory" if i == 0 else "co_signatory")
    firsts = [d for d in P if (d.get("p_first") or 0.0) >= tau_first]
    if len(P) == 1 and not G and not cue:
        firsts = []
    if firsts:
        lead = max(firsts, key=lambda d: d["p_first"])
        for d in P:
            d["role"] = "first_signatory" if d is lead else "co_signatory"
    elif G:
        for d in P:
            d["role"] = "spokesperson"
    else:
        for d in P:
            d["role"] = "sole_author" if len(P) == 1 else "joint_author"
    return decisions


# ------------------------------------------------------------------------------------------------------------ letters
def decide_letters(lps: list[float], tau: float) -> tuple[str, dict]:
    p = softmax(lps)
    probs = {r: round(v, 6) for r, v in zip(ROLES, p)}
    best = max(range(6), key=lambda i: p[i])
    return (ROLES[best] if 1.0 - p[6] >= tau else "not_an_author"), probs


def coherence(decisions: list[dict], rules: list[str]) -> list[dict]:
    auth = [d for d in decisions if d["role"] != "not_an_author"]
    bodies = [d for d in auth if d["kind"] != "person"]
    if "spokes_needs_body" in rules and not bodies:
        for d in auth:
            if d["role"] == "spokesperson":
                d["coherence"].append("spokes_needs_body")
                d["role"] = max(AUTHOR_ROLES[:5], key=lambda r: d["probs"][r])
    if "sole_to_joint" in rules and not bodies:
        soles = [d for d in auth if d["role"] == "sole_author" and d["kind"] == "person"]
        if len(soles) >= 2:
            for d in soles:
                d["coherence"].append("sole_to_joint")
                d["role"] = "joint_author"
    if "single_joint" in rules and len(auth) == 1 and auth[0]["role"] == "joint_author":
        auth[0]["coherence"].append("single_joint")
        auth[0]["role"] = "sole_author"
    return decisions


# ------------------------------------------------------------------------------------------------------------ read
def read(backend, q: list[str], a: list[str], cands: list[dict], lang: str, cfg: dict | None = None) -> dict:
    """Roles of the located candidates of one affair. Returns actors (the authors, located) and every decision."""
    cfg = dict(DEFAULT_CONFIG, **(cfg or {}))
    lg = _lang(lang)
    v = view(q, a, cfg)
    decisions, pids = [], set()
    for c in cands:
        d = dict(value=c["value"], kind=c["kind"], sources=c["sources"], coherence=[])
        if cfg["mode"] == "staged":
            user, pid = prompt(c, cands, v, q, a, lg, cfg, cfg["prompt"])
            pids.add(pid)
            ra = p_true(backend, user, BOOL_PREFIX[cfg["prompt"]][lg])
            d.update(p_author_pos=round(ra["p"], 6), lps_author=[round(x, 4) for x in ra["lps"]], missing=ra["missing"],
                     method=ra["method"], fingerprint=ra["fingerprint"], p_first=None, p_author_neg=None)
            if cfg.get("prompt_neg"):
                user, pid = prompt(c, cands, v, q, a, lg, cfg, cfg["prompt_neg"])
                pids.add(pid)
                rn = p_true(backend, user, BOOL_PREFIX[cfg["prompt_neg"]][lg])
                d.update(p_author_neg=round(rn["p"], 6), missing=d["missing"] + rn["missing"])
            if c["kind"] == "person":
                parts = []
                for name in _as_list(cfg["prompt_first"]):
                    user, pid = prompt(c, cands, v, q, a, lg, cfg, name)
                    pids.add(pid)
                    rf = p_true(backend, user, BOOL_PREFIX[name][lg])
                    parts.append(rf["p"])
                    d["missing"] = d["missing"] + rf["missing"]
                d.update(p_first_parts=[round(x, 6) for x in parts], p_first=round(geo_mean(parts), 6))
        else:
            user, pid = prompt(c, cands, v, q, a, lg, cfg)
            pids.add(pid)
            r = option_logprobs(backend, user, PREFIX[lg], LETTERS)
            role, probs = decide_letters(r["lps"], cfg["tau"])
            d.update(role=role, probs=probs, lps=[round(x, 4) for x in r["lps"]], missing=r["missing"],
                     method=r["method"], fingerprint=r["fingerprint"])
        decisions.append(d)
    decide(decisions, cfg, has_cosign_cue(q, a))
    actors = []
    for c, d in zip(cands, decisions):
        if d["role"] == "not_an_author":
            continue
        name = {k: c[k] for k in ("value", "doc", "page", "char_start", "char_end", "quote_sha256")}
        actors.append(dict(role=d["role"], kind=c["kind"], name=dict(name, rule=f"pointer:{POINTER_VERSION}")))
    return dict(version=POINTER_VERSION, prompt_ids=sorted(pids), lang=lg, config=cfg, actors=actors,
                decisions=decisions, build=getattr(backend, "build", "?"))


def _as_list(x) -> list[str]:
    return list(x) if isinstance(x, (list, tuple)) else [x]


def geo_mean(xs: list[float]) -> float:
    """The first-signatory probability when the configuration asks the question in several wordings: their geometric
    mean (one wording's confident 'no' outweighs another's 'yes'; a single wording is returned unchanged)."""
    return math.exp(sum(math.log(max(x, 1e-12)) for x in xs) / len(xs))


def has_cosign_cue(q: list[str], a: list[str]) -> bool:
    return bool(COSIGN_CUE.search("\n".join(q or []))) or bool(COSIGN_CUE.search("\n".join(a or [])[:3000]))


def p_author(d: dict) -> float:
    """The author probability: P(true) of the author question, averaged with P(false) of the negated question when the
    configuration asks both (the two polarities cancel a yes-bias)."""
    pos = d["p_author_pos"] if "p_author_pos" in d else d["p_author"]
    neg = d.get("p_author_neg")
    return pos if neg is None else (pos + 1.0 - neg) / 2.0


def decide(decisions: list[dict], cfg: dict, cue: bool = True) -> list[dict]:
    """(Re-)decide stored model outputs under a configuration (no model call)."""
    if cfg["mode"] == "staged":
        for d in decisions:
            d["p_author"] = round(p_author(d), 6)
        return compose(decisions, cfg["tau"], cfg["tau_first"], cue or not cfg.get("lone_first_needs_cue"))
    for d in decisions:
        d["role"], d["probs"] = decide_letters(d["lps"], cfg["tau"])
        d["coherence"] = []
    return coherence(decisions, cfg["coherence"])
