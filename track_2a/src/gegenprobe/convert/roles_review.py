"""Opt-in review route for author roles: the frozen P10 reader (Apertus) on one affair, alone by default. Used by
`python -m gegenprobe affair --roles apertus`; the default (`--roles rules`) runs no model.

    read(record, entry, meta, names, backend, fallback=None) -> the `suggestions.actors` block of the affair command

What runs, unchanged from the registered P10 test (eval/prereg10/PREREG10.md, LOCK10):
  candidates  gegenprobe.convert.role_candidates.candidates(question pages, answer pages, the body's OPD roster): every
              person or body the two documents print that could be an author, each located (page, span, sha256 of the
              printed text). No model.
  reader      gegenprobe.convert.roles_pointer.read with the frozen configuration data/p10/p10_config.json (`pointer`:
              staged questions, tau 0.98, tau_first 0.3, the cue rule); the model answers closed true/false questions
              about each candidate and code composes the role by the P8 guide. The model never writes a name.
  fallback    OFF by default; only with `--roles-fallback opd` (fallback="opd"): where the reader abstains (no candidate
              passes tau), OPD's contributor list for the affair, mapped to roles as P10's opd_first arm does
              (eval.p10.arms.opd_pairs, 'first_and_co'). No model; names are OPD's, not located in the documents.
              Why off: post hoc on P10's committed arms (primary cell, 34 affairs), the reader alone gives 50/96 pairs
              (precision 0.52, recall 0.355, F1 0.42); with the fallback 50/128 (precision 0.39, F1 0.37): it fired on
              2 affairs and added 32 pairs, none correct.

Never into the record: the block travels next to the record (`suggestions.actors`), every entry carries `review: true`
and its `route` (`apertus_role_pointer`; `opd_contributors` only with the fallback on), and the rules' printed roles
in `record.actors` are left as they are (`applied: false`). Where the rules printed the same person, the entry says
which role the rules gave (`rules_role`) and whether they agree; a disagreement is for a reviewer to settle, never
resolved in code.

Evidence (README / technical_report, P10): on unseen layouts the frozen reader on the Public AI route (70B weights under
the -8b name) found 50/141 gold (name, role) pairs against the frozen rules' 17/141 (H1, Holm p 0.032); against OPD's
list it is not shown better (H3a not confirmed). Any other build (the local GGUF 8B, another server) is outside that
measurement: the block says so (`same_build_as_p10`).
"""
from __future__ import annotations

import hashlib
import json

from ..paths import ROOT
from . import role_candidates as RC
from . import roles_pointer as RP

CONFIG = ROOT / "data" / "p10" / "p10_config.json"
P10_BUILD = "publicai:swiss-ai/apertus-v1.5-8b"  # the build P10 measured (gateway:swiss-ai/apertus-v1.5-8b:...)
ROUTE_MODEL = "apertus_role_pointer"
ROUTE_OPD = "opd_contributors"


def config() -> tuple[dict, str]:
    raw = CONFIG.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def lang_of(record: dict) -> str:
    """The prompt language as P10 chose it: the language of the member's text (DE/FR/IT), else the body's, else de."""
    for d in record.get("documents") or []:
        if d.get("role") == "question":
            for lg in d.get("language_of_text") or []:
                if lg in RP.LANGS:
                    return lg
    for lg in (record.get("body") or {}).get("languages") or []:
        if lg in RP.LANGS:
            return lg
    return "de"


def _pages(entry: dict) -> dict[str, list[str]]:
    from ..schema.v0_2_roles import pages_of

    out = {}
    for d in entry.get("docs") or []:
        got = pages_of(d["sha256"], bool(d.get("image_only")))
        out[d["role"]] = got[0] if got else []
    return out


def _rule_roles(record: dict) -> list[tuple[str, str]]:
    return [(str(a["name"].get("value")), a["role"]) for a in record.get("actors") or []
            if (a.get("name") or {}).get("route") in ("rule", "ocr+rule") and a["name"].get("kind") == "value"]


def _rules_role(value: str, rules: list[tuple[str, str]]) -> str | None:
    from .roles import same_person

    return next((r for n, r in rules if same_person(n, value)), None)


FALLBACKS = ("none", "opd")


def read(record: dict, entry: dict, meta: dict | None, names, backend, *, cfg: dict | None = None,
         fallback: str | None = None) -> dict:
    """The review block (module docstring). `entry`: the affair command's document entry (docs with role, doc_id,
    sha256, image_only); `meta`: OPD's affair, events and contributors; `names`: the body's roster [(first, last)]."""
    if backend is None:
        raise ValueError("--roles apertus needs a model backend (--backend gguf | openai | gateway:...)")
    fallback = fallback or "none"
    if fallback not in FALLBACKS:
        raise ValueError(f"fallback must be one of {FALLBACKS}, got {fallback!r}")
    full, sha = config()
    pcfg = dict(full["pointer"], **(cfg or {}))
    pages = _pages(entry)
    q, a = pages.get("question") or [], pages.get("answer") or []
    doc_ids = {d["role"]: f"opd:{d['doc_id']}" for d in entry.get("docs") or []}
    cands = RC.candidates(q, a, [tuple(x) for x in names or []])
    lang = lang_of(record)
    res = RP.read(backend, q, a, cands["candidates"], lang, pcfg)
    rules = _rule_roles(record)
    by_value = {d["value"]: d for d in res["decisions"]}
    actors = []
    for x in res["actors"]:
        n = x["name"]
        d = by_value.get(n["value"], {})
        rr = _rules_role(n["value"], rules)
        actors.append(dict(
            role=x["role"], kind=x["kind"], route=ROUTE_MODEL, review=True,
            name=dict(value=n["value"], doc=doc_ids.get(n["doc"], n["doc"]), page=n["page"], char_start=n["char_start"],
                      char_end=n["char_end"], quote_sha256=n["quote_sha256"], rule=n["rule"]),
            p_author=d.get("p_author"), p_first=d.get("p_first"), rules_role=rr,
            agrees_with_rules=None if rr is None else rr == x["role"]))
    source = "apertus" if actors else "none"
    if not actors and fallback == "opd":
        from eval.p10.arms import _opd_name, opd_pairs

        kinds = {_opd_name(c): ("person" if c.get("type") == "person" else "parliamentary_group")
                 for c in (meta or {}).get("contributors") or []}
        for value, role in opd_pairs(meta, "first_and_co"):
            rr = _rules_role(value, rules)
            actors.append(dict(role=role, kind=kinds.get(value, "person"), route=ROUTE_OPD,
                               review=True, name=dict(value=value, located=False), rules_role=rr,
                               agrees_with_rules=None if rr is None else rr == role))
        if actors:
            source = "opd_contributors"
    build = getattr(backend, "build", "?")
    same = build == P10_BUILD
    n_dis = sum(1 for x in actors if x["agrees_with_rules"] is False)
    reason = ("author roles read by the P10 reader (Apertus, closed questions on located candidates)" if source == "apertus"
              else "the P10 reader abstained; OPD's contributor list is offered instead (not located in the documents)"
              if source == "opd_contributors" else "the P10 reader abstained and OPD lists no author"
              if fallback == "opd" else "the P10 reader abstained (no author suggested; --roles-fallback opd offers "
              "OPD's contributor list)")
    reason += f"; {n_dis} role(s) differ from the rules'" if n_dis else ""
    reason += "" if same else f"; build {build} is not the build P10 measured ({P10_BUILD}): exploratory"
    return dict(
        route="--roles apertus", fallback=fallback, source=source, applied=False, review=True, actors=actors,
        review_reason=reason,
        build=build, same_build_as_p10=same, served=sorted(getattr(backend, "served", set()) or []),
        pointer_version=res["version"], candidates_version=cands["version"], prompt_ids=res["prompt_ids"], lang=lang,
        config=dict(file=CONFIG.relative_to(ROOT).as_posix(), sha256=sha, frozen_backend=full.get("backend")),
        n_candidates=len(cands["candidates"]), candidates_dropped=cands["dropped"],
        decisions=[dict(value=d["value"], kind=d["kind"], role=d["role"], p_author=d.get("p_author"),
                        p_first=d.get("p_first")) for d in res["decisions"]],
        note=("suggestions only: record.actors keep the rules' printed roles; a reviewer accepts or rejects each entry"),
    )
