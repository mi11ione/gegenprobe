"""`python -m gegenprobe affair`: the operator command, writing the record the project publishes.

    python -m gegenprobe affair --opd-affair 39369 [--schema v0.2] [...]     (options: gegenprobe.affair_cli.add_parser)
    python -m gegenprobe.affair_product p5 [--check] [--refresh-rows]        the 40 P5 records through this path (offline)
    python -m gegenprobe.affair_product samples [--check]                     the command vs the published records ->
                                                                              results/affair_cli/product_check.json

gegenprobe.affair_cli (frozen under eval/p11/LOCKP11, not edited) builds one validated v0.2 record from OPD's export rows
and the affair's documents: affair.build, affair_post.finalize, v0_2_all.carry_v0_1 and with_roles, the document parts,
role consistency and the Q/A pairing. The committed records (results/schema/v0_2/) then pass the post-processing layers
of `make schema-v02` (gegenprobe.schema.v0_2_parts). This module runs the same layers on the command's record, in the
same order, from the same functions, so the command writes what the published records and the README sample show:
  1 typed gaps          gegenprobe.schema.v0_2_gaps.with_gaps: a typed reason for every role the record leaves silent
                        (co-signatories, addressed body, instrument); the addressed-body rule re-read on the question
                        text the command fetched (v0_2_gaps.addressed), as `make schema-v02` reads it from
                        addressed_body_rule.jsonl
  2 OPD metadata        gegenprobe.schema.v0_2_meta.with_metadata: answering body (OPD's bodies export: executive_name,
                        else OPD's events, else data/schema/body_executives.json), decision, procedural state and type
                        from the affair's own OPD rows (route metadata, never replacing a value)
  3 answer-date roles   gegenprobe.schema.v0_2_dates.with_date_roles: answer_decided / answer_dispatched / answered with
                        its typed reason, from the decision and dispatch anchors of the answer text the command fetched
                        (v0_2_dates.anchors), as `make schema-v02` reads them from answer_date_anchors.jsonl
The record is validated again after the layers (an invalid record is the typed failure invalid_record). The changes the
metadata layer made are listed in `changes`, the layers in `sources.post_layers`.

OPD rows: as affair_cli, plus what the layers need: the events' actor_fr / actor_it (affair_cli keeps actor_de only;
Vernier's executive is named in actor_fr) and the bodies' rows (executive names) from OPD's bodies export (GP_OPD_RAW
when local, else the exports, through gegenprobe.net; offline: the committed slice data/schema/v0_2_meta_slice.json).
A slice saved with --save-rows keeps them (`bodies`, and for a federal affair `texts`).

Federal affairs (body CHE): the Federal Council's answers are rows of OPD's texts export, not documents (the docs export
holds Federal Gazette publications), so affair_cli stops with no_documents. Here a federal affair is built the way the
federal cell's 15 records were (eval.fed.arms offline): the affair's rows of texts_CHE (the lowest-id "Eingereichter
Text", "Begründung", "Antwort BR / Büro" and title rows; streamed once through gegenprobe.net, about 250 MB, or read from
a --rows slice), one language version chosen by the federal cell's rule (eval.fed.common: a genuine version is an answer
of 200-40,000 characters and a member's text of >= 200 characters whose language guess is that language; among several,
the cell's seeded choice eval.fed.common.stratum; with none genuine, the first of de/fr/it where both texts exist, said in
`review`), the texts converted by the frozen eval.fed.common.plain, affair.build.run_affair on them (link status
attached), affair_post.finalize, v0_2_all.carry_v0_1, the parts detector on the HTML (convert.parts.detect_html), role
consistency and the layers above with the federal cell's set semantics. Without an answer row in the texts export the
affair is the typed failure no_documents (with the reason).

`make run` step affair_cli (`step`): the command on the affairs of the three committed v0.2 samples, compared with each
sample field by field; besides affair_cli's checks (documents, language of each text, answer date, Q/A items) it
compares the author and other actor roles, the date roles (and the answer date's role), the answering body and the title.

`p5`: the P5 affairs (data/gold6/p5_affairs.jsonl) built by this command on the documents P5 drew (--question-doc /
--answer-doc), offline: OPD's rows from the committed slice data/affair_cli/opd_rows_p5.json (written once from the
census snapshot in GP_OPD_RAW / GP_DOCS_META with --refresh-rows), each document read from the PDF cache by its sha256
(a missing one is fetched through pdftext.fetch_pdf and must have that sha256). The command's records before the post
layers go to results/schema/v0_2/p5_affair_cli.jsonl; `make schema-v02` (gegenprobe.schema.v0_2_parts) carries them
through the layers as the P5 set, in place of the P5 rules arm's assembly (gegenprobe.schema.v0_2_all.p5_affair). --check
rebuilds them and compares (the timestamp aside); SKIP when a document is not cached.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import gzip
import json
import os
import re
import sys
import time
from pathlib import Path

from . import affair_cli as AC
from . import net
from .compliance import fetchguard
from .paths import OPD_RAW, ROOT

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

CLI_SET = "cli"
FED_SET = "fed"
EXTRA_EVENT_KEYS = ("actor_fr", "actor_it")
LAYERS = ("gegenprobe.schema.v0_2_gaps.with_gaps", "gegenprobe.schema.v0_2_meta.with_metadata",
          "gegenprobe.schema.v0_2_dates.with_date_roles")
BODIES_EXPORT = "bodies.ndjson.gz"
P5_AFFAIRS = ROOT / "data" / "gold6" / "p5_affairs.jsonl"
P5_ROWS = ROOT / "data" / "affair_cli" / "opd_rows_p5.json"
P5_OUT = ROOT / "results" / "schema" / "v0_2" / "p5_affair_cli.jsonl"
FED_SLICE = ROOT / "data" / "affair_cli" / "opd_rows_fed_157601.json"
CHECK_OUT = ROOT / "results" / "affair_cli" / "product_check.json"
_AFFAIR_ID = re.compile(r'"affair_id"\s*:\s*(\d+)')


# ------------------------------------------------------------------------------------------------ OPD rows
@contextlib.contextmanager
def _full_events():
    """affair_cli keeps the events' actor_de only (gegenprobe.affair.meta.EVENT_KEYS); the metadata layer also reads
    actor_fr / actor_it. Scoped: the frozen tuple is restored on exit."""
    from .affair import meta as M

    old = M.EVENT_KEYS
    M.EVENT_KEYS = old + tuple(k for k in EXTRA_EVENT_KEYS if k not in old)
    try:
        yield
    finally:
        M.EVENT_KEYS = old


def _bodies(keys: set[str], source: str) -> tuple[dict, dict]:
    """({body key: OPD bodies row (v0_2_meta.BODY_KEYS)}, provenance): GP_OPD_RAW when local, else the bodies export;
    when neither can be read, the committed slice data/schema/v0_2_meta_slice.json (its bodies)."""
    from .schema import v0_2_meta as VM

    out: dict[str, dict] = {}
    if not keys:
        return out, {}
    local = OPD_RAW / BODIES_EXPORT
    try:
        if source == "local" and local.exists():
            f = gzip.open(local, "rt", encoding="utf-8")
            where = "GP_OPD_RAW"
        else:
            f = net.stream_ndjson_gz(net.EXPORTS_PREFIX + BODIES_EXPORT)
            where = "GP_EXPORTS_DIR" if os.environ.get("GP_EXPORTS_DIR") else net.EXPORTS_PREFIX
        try:
            for line in f:
                if line.strip():
                    b = json.loads(line)
                    if b.get("body_key") in keys:
                        out[b["body_key"]] = {k: b.get(k) for k in VM.BODY_KEYS}
        finally:
            close = getattr(f, "close", None)
            if close:
                close()
        return out, dict(source=where, file=BODIES_EXPORT)
    except (OSError, net.Disallowed, ValueError, EOFError) as e:
        sl = VM.load()["bodies"] if VM.SLICE.exists() else {}
        out = {k: v for k, v in sl.items() if k in keys}
        return out, dict(source="data/schema/v0_2_meta_slice.json (committed)",
                         bodies_error=f"{type(e).__name__}: {e}"[:200])


def _texts_rows(ids: set[int]) -> dict[int, list[dict]]:
    """The federal affairs' rows of OPD's texts export (texts_CHE): one streamed pass through gegenprobe.net (GP_EXPORTS_DIR
    when it mirrors the exports), only the member's text, reasoning, answer and title rows, all language slots."""
    from eval.fed import common as C

    want = C.TYPE_MEMBER | C.TYPE_REASON | C.TYPE_ANSWER | C.TYPE_TITLE
    out: dict[int, list[dict]] = {a: [] for a in ids}
    for line in AC._guarded(net.stream_ndjson_gz(C.TEXTS_URL), "texts_CHE export"):
        m = _AFFAIR_ID.search(line)
        if not (m and int(m.group(1)) in ids):
            continue
        d = json.loads(line)
        if d.get("affair_id") in out and C.row_type(d) in want:
            out[d["affair_id"]].append({k: d.get(k) for k in ("id", "affair_id", "type_de", "type_fr", "type_it",
                                                              "text_de", "text_fr", "text_it")})
    for v in out.values():
        v.sort(key=lambda r: r["id"])
    return out


def enrich(rows: dict, source: str = "auto") -> dict:
    """Add what the layers need to rows read by affair_cli (or loaded from an older slice): the bodies' rows, and for
    federal affairs their texts-export rows (`texts`)."""
    found = {a: v for a, v in rows["affairs"].items() if v.get("affair")}
    keys = {v["affair"]["body_key"] for v in found.values()}
    have = rows.get("bodies") or {}
    if keys - set(have):
        src = source if source != "auto" else ((rows.get("sources") or {}).get("single_exports") or {}).get("source", "auto")
        got, prov = _bodies(keys - set(have), "local" if src == "local" else "exports")
        rows["bodies"] = dict(sorted({**have, **got}.items()))
        rows.setdefault("sources", {})["bodies"] = prov
    fed = {a for a, v in found.items() if v["affair"]["body_key"] == "CHE"}
    texts = rows.get("texts") or {}
    need = {a for a in fed if str(a) not in texts}
    if need:
        got = _texts_rows(need)
        rows["texts"] = dict(sorted({**texts, **{str(a): v for a, v in got.items()}}.items()))
        from eval.fed import common as C

        rows.setdefault("sources", {})["texts"] = dict(source=C.TEXTS_URL, location=(
            "GP_EXPORTS_DIR" if os.environ.get("GP_EXPORTS_DIR") else net.EXPORTS_PREFIX) + "texts/texts_CHE.ndjson.gz")
    return rows


def read_rows(affair_ids, source: str = "auto") -> dict:
    """affair_cli.read_rows with the events' actor_fr / actor_it, plus `enrich`."""
    with _full_events():
        rows = AC.read_rows(affair_ids, source)
    try:
        return enrich(rows, source)
    except AC.AffairError:
        raise
    except (OSError, net.Disallowed, ValueError, EOFError) as e:
        kind, reason = AC._classify(e, "exports_")
        raise AC.AffairError(kind, reason) from e


# ------------------------------------------------------------------------------------------------ the post layers
def _slice(affair_id: int, row: dict, bodies: dict) -> dict:
    from .schema import v0_2_meta as VM

    a = row.get("affair") or {}
    return dict(affairs={str(affair_id): dict(affair={k: a.get(k) for k in VM.AFFAIR_KEYS},
                                              events=[{k: e.get(k) for k in VM.EVENT_KEYS} for e in row.get("events") or []])},
                bodies=bodies or {})


def layers(rec: dict, affair_id: int, row: dict, bodies: dict, pages: dict[str, tuple[str, list[str]]],
           set_name: str = CLI_SET) -> tuple[dict, list[dict]]:
    """The post-processing layers of `make schema-v02` on one record (module docstring), in v0_2_parts' order: typed
    gaps, OPD metadata, answer-date roles. pages: role -> (record doc_id, text pages) of the documents the record was
    built from. Returns (record, the metadata layer's changes)."""
    from .schema import v0_2_dates as VD
    from .schema import v0_2_gaps as VG
    from .schema import v0_2_meta as VM

    q, a = pages.get("question"), pages.get("answer")
    inp = VG.Inputs(addressed={(set_name, q[0]): dict(match=VG.addressed(q[1]),
                                                      window=f"page 1, characters 0-{VG.WINDOW}")} if q else {})
    det = {(set_name, a[0]): dict(doc_id=a[0], anchors=VD.anchors(a[1]))} if a else {}
    rec = VG.with_gaps(rec, inp, set_name)
    rec, changes = VM.with_metadata(rec, _slice(affair_id, row, bodies), set_name)
    rec = VD.with_date_roles(rec, det, VD.tiers(), set_name)
    return rec, changes


@contextlib.contextmanager
def _p8_paths_kept():
    """The typed-gap check reads the skeleton's field list from eval.p11.annotate (frozen under LOCKP11), whose import
    re-points eval.p8.common's packet and date-list paths at P11's; the command leaves them as it found them, so a
    process that runs the command and then reads P8 (a test session, `make run`) still reads P8's files."""
    try:
        from eval.p8 import common as C8
    except ImportError:  # the evaluation package is not shipped with a slim install
        yield
        return
    saved = (C8.PACK, C8.DATELISTS)
    try:
        yield
    finally:
        C8.PACK, C8.DATELISTS = saved


def finish(res: dict, affair_id: int, row: dict, bodies: dict, pages: dict, set_name: str = CLI_SET) -> dict:
    """affair_cli's product row with the layers applied to its record, validated again."""
    with _p8_paths_kept():
        return _finish(res, affair_id, row, bodies, pages, set_name)


def _finish(res: dict, affair_id: int, row: dict, bodies: dict, pages: dict, set_name: str = CLI_SET) -> dict:
    from .schema import role_consistency, v0_2_gaps
    from .schema.p8_v0_2 import schema_module

    rec, changes = layers(res["record"], affair_id, row, bodies, pages, set_name)
    try:
        valid = schema_module().validate_affair(rec)
    except Exception as e:  # noqa: BLE001 - pydantic.ValidationError and the model's own ValueErrors
        raise AC.AffairError("invalid_record", f"after the post layers: {type(e).__name__}: {str(e)[:600]}") from e
    out = valid.model_dump(mode="json", exclude_none=True)
    review = [r for r in res.get("review") or [] if not str(r.get("reason", "")).startswith("role_inconsistent")]
    review += [dict(field="actors", reason=f"role_inconsistent: {v} (gegenprobe.schema.role_consistency)")
               for v in role_consistency.violations(out.get("actors") or [])]
    review += [dict(field=c, reason="untyped cell after the post layers (gegenprobe.schema.v0_2_gaps)")
               for c in v0_2_gaps.untyped_cells(out)]
    review += stale_review(out)
    res = dict(res, record=out, review=review, needs_review=bool(res.get("needs_review") or review),
               changes=list(res.get("changes") or []) + [dict(c, layer="gegenprobe.schema.v0_2_meta") for c in changes
                                                         if c.get("now") != "unchanged"])
    res["sources"] = dict(res.get("sources") or {}, post_layers=list(LAYERS), post_layer_set=set_name)
    return res


def stale_review(rec: dict) -> list[dict]:
    """The stale-state check (gegenprobe.findings.stale_states): OPD's last state event says `submitted` while the
    record has an answer attached or dated. The record keeps OPD's state (it is OPD's data); the command flags it."""
    from .findings.stale_states import stale_state

    s = stale_state(rec)
    if not s:
        return []
    what = (f"answer {', '.join(s['answer_docs'])} attached" if s["answer_docs"]
            else f"answer dated {s['answer_dates'][0]['value']}")
    return [dict(field="procedural_state", reason=f"stale_state: OPD's last state event ({s['state_source']}) says "
                 f"{s['state']} while the {what} (an OPD data finding: results/findings/stale_states.json)")]


def _pages_of_docs(res: dict) -> dict[str, tuple[str, list[str]]]:
    from .schema.v0_2_roles import pages_of

    out = {}
    for d in (res.get("sources") or {}).get("documents") or []:
        got = pages_of(d["sha256"], bool(d.get("image_only")))
        if got is not None:
            out[d["role"]] = (f"opd:{d['doc_id']}", got[0])
    return out


# ------------------------------------------------------------------------------------------------ federal affairs
def fed_choice(affair_id: int, trows: list[dict]) -> tuple[dict, str, str | None]:
    """({role: texts row}, language slot, note): the lowest-id row of each type, the slot by the federal cell's rule."""
    from eval.fed import common as C

    kinds = (("member", C.TYPE_MEMBER), ("reason", C.TYPE_REASON), ("answer", C.TYPE_ANSWER), ("title", C.TYPE_TITLE))
    rows = {}
    for role, types in kinds:
        cand = [r for r in trows if C.row_type(r) in types]
        if cand:
            rows[role] = min(cand, key=lambda r: r["id"])
    if "answer" not in rows or "member" not in rows:
        what = ("Federal Council answer row (Antwort BR / Büro)" if "answer" not in rows
                else "submitted-text row (Eingereichter Text)")
        raise AC.AffairError("no_documents", f"OPD's texts export (texts_CHE) holds no {what} for federal affair "
                             f"{affair_id}: the answer is not in OPD's texts")
    meta = {r: C.slot_meta(rows[r]) for r in ("member", "reason", "answer") if r in rows}
    member = {L: dict(n=sum((meta[r].get(L) or {}).get("n", 0) for r in ("member", "reason") if r in meta),
                      lang=next(((meta[r].get(L) or {}).get("lang") for r in ("member", "reason")
                                 if r in meta and (meta[r].get(L) or {}).get("lang")), None)) for L in C.STRATA}
    genuine = {L: C.genuine(dict(slots=meta["answer"]), member, L) for L in C.STRATA}
    slot = C.stratum(affair_id, genuine)
    note = None
    if slot is None:
        slot = next((L for L in C.STRATA if rows["answer"].get(f"text_{L}") and rows["member"].get(f"text_{L}")), None)
        if slot is None:
            raise AC.AffairError("no_documents", f"federal affair {affair_id}: no language version holds both the "
                                 "member's text and the answer in OPD's texts export")
        note = (f"no genuine language version by the federal cell's rule (eval.fed.common.genuine); read the {slot} "
                "version")
    return rows, slot, note


def fed_build(affair_id: int, row: dict, names: list, trows: list[dict], *, sources: dict | None = None,
              mode: str = "rules_only", backend=None, theta=None, bodies: dict | None = None, **_kw) -> dict:
    """One federal affair's product row from OPD's texts export (module docstring)."""
    import copy

    from eval.fed import common as C

    from .affair import build as B
    from .affair_post import finalize
    from .convert import parts as P
    from .schema import role_consistency, v0_2_all
    from .schema import v0_2_parts as VP
    from .schema.p8_v0_2 import schema_module

    a = row.get("affair")
    if not a:
        raise AC.AffairError("affair_not_found", f"OPD affair {affair_id} is not in the affairs export")
    rows, slot, note = fed_choice(affair_id, trows)
    raw = {r: rows[r].get(f"text_{slot}") for r in rows}
    title = raw.get("title") or a.get(f"title_{slot}") or ""
    pages = {"question": [C.plain(title), C.plain(raw["member"])] + ([C.plain(raw["reason"])] if raw.get("reason") else []),
             "answer": [C.plain(raw["answer"])]}
    doc_ids = {"question": f"opd-texts:{rows['member']['id']}", "answer": f"opd-texts:{rows['answer']['id']}"}
    url = {role: f"{C.TEXTS_URL}#row={rows['member' if role == 'question' else 'answer']['id']}&slot={slot}"
           for role in ("question", "answer")}
    entry = dict(split="opd", affair_id=affair_id, number=a.get("number"), body="CHE", level="federal", stratum=slot,
                 lang=slot, affair_type=a.get("type_harmonized_en"),
                 rows={r: (rows[r]["id"] if r in rows else None) for r in ("title", "member", "reason", "answer")},
                 sha={r: C.sha(raw.get(r)) for r in ("member", "reason", "answer")})

    def texts(_entry):
        return {role: (doc_ids[role], pages[role], dict(url=url[role], extractor="eval.fed.common.plain",
                                                         image_only=False)) for role in ("question", "answer")}
    saved = B.texts
    B.texts = texts
    try:
        meta = dict(affair=a, events=row["events"], contributors=row["contributors"])
        res = B.run_affair(entry, meta, names, "attached", backend if mode == "review" else None, theta)
    finally:
        B.texts = saved
    post = finalize(res["affair"])
    rec = v0_2_all.carry_v0_1(post["affair"])
    html = {"question": [None, raw["member"]] + ([raw["reason"]] if raw.get("reason") else []), "answer": [raw["answer"]]}
    det = {(FED_SET, doc_ids[role]): VP._strip_det(P.detect_html(html[role], pages[role])) for role in html}
    rec = VP.with_parts(rec, det, FED_SET)
    rec, _ = role_consistency.harmonise(rec)
    rec, changes = layers(rec, affair_id, row, bodies or {}, {r: (doc_ids[r], pages[r]) for r in pages}, FED_SET)
    ex = rec["extraction"]
    src = sources or {}
    n = (f"built by gegenprobe.affair_product ({mode}) from OPD's export rows and OPD's texts export (texts_CHE rows "
         + ", ".join(f"{r} {rows[r]['id']}" for r in ("title", "member", "reason", "answer") if r in rows)
         + f", language version {slot}, converted by eval.fed.common.plain) as the federal cell's records "
         "(eval.fed.arms offline)" + (f"; {note}" if note else ""))
    ex["notes"] = f"{ex['notes']}; {n}" if ex.get("notes") else n
    try:
        valid = schema_module().validate_affair(rec)
    except Exception as e:  # noqa: BLE001
        raise AC.AffairError("invalid_record", f"{type(e).__name__}: {str(e)[:600]}") from e
    out = valid.model_dump(mode="json", exclude_none=True)
    review = list(post["review"]) + ([dict(field="documents", reason=note)] if note else [])
    review += [dict(field="actors", reason=f"role_inconsistent: {v} (gegenprobe.schema.role_consistency)")
               for v in role_consistency.violations(out.get("actors") or [])]
    review += stale_review(out)
    sugg = res.get("suggestions") or {}
    docs = [dict(role=role, doc_id=doc_ids[role], name=("member's text" if role == "question" else "Federal Council answer"),
                 url=url[role], sha256=C.sha(raw["member" if role == "question" else "answer"]),
                 extractor="eval.fed.common.plain", image_only=False, fetched_from="opd_texts_export", slot=slot)
            for role in ("question", "answer")]
    return dict(opd_affair=affair_id, status="ok", schema_version="0.2.0", record=out,
                needs_review=bool(post["needs_review"] or sugg or review), review=review, suggestions=sugg,
                changes=copy.deepcopy(post["changes"]) + [dict(c, layer="gegenprobe.schema.v0_2_meta") for c in changes
                                                          if c.get("now") != "unchanged"],
                sources=dict(src, documents=docs, answer_link_status="attached", mode=mode, roles="rules",
                             post_layers=list(LAYERS), post_layer_set=FED_SET))


# ------------------------------------------------------------------------------------------------ one affair, many
def build(affair_id: int, row: dict, rows: dict, **kw) -> dict:
    """One affair: a federal affair from OPD's texts export, every other through affair_cli.build; then the layers."""
    body = (row.get("affair") or {}).get("body_key")
    names = rows.get("names", {}).get(body, [])
    bodies = rows.get("bodies") or {}
    if body == "CHE":
        trows = (rows.get("texts") or {}).get(str(affair_id))
        if trows:
            return fed_build(affair_id, row, names, trows, bodies=bodies, **kw)
    res = AC.build(affair_id, row, names, **kw)
    return finish(res, affair_id, row, bodies, _pages_of_docs(res))


def run(affair_ids: list[int], *, source: str = "auto", rows_file: str | None = None, save_rows_file: str | None = None,
        budget_s: float | None = None, **kw) -> list[dict]:
    """affair_cli.run with this module's rows and build (one pass over the exports; one row or typed failure each)."""
    from .deadline import DeadlineExceeded, deadline

    t0 = time.time()
    try:
        if rows_file:
            rows = AC.load_rows(Path(rows_file))
            rows["texts"] = {str(k): v for k, v in (rows.get("texts") or {}).items()}
            enrich(rows, source)
        else:
            rows = read_rows(affair_ids, source)
    except AC.AffairError as e:
        return [AC.failure(a, e) for a in affair_ids]
    except (OSError, net.Disallowed, ValueError, EOFError) as e:
        kind, reason = AC._classify(e, "exports_")
        return [AC.failure(a, AC.AffairError(kind, reason)) for a in affair_ids]
    if rows_file:
        p = Path(rows_file).resolve()
        rows["sources"] = dict(rows.get("sources") or {}, slice=p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT)
                               else p.name)
    if save_rows_file:
        AC.save_rows(rows, Path(save_rows_file))
    out = []
    for aid in affair_ids:
        row = rows["affairs"].get(aid) or dict(affair=None)
        left = None if budget_s is None else budget_s - (time.time() - t0)
        try:
            with deadline(left):
                out.append(build(aid, row, rows, sources=rows.get("sources"), **kw))
        except AC.AffairError as e:
            out.append(AC.failure(aid, e))
        except DeadlineExceeded:
            out.append(AC.failure(aid, AC.AffairError("over_budget", f"not finished within the {budget_s:.0f} s budget "
                                                      "(GP_AFFAIR_CLI_BUDGET)")))
    return out


def main_args(a) -> int:
    """affair_cli.main_args with this module's run: the same options, output and exit codes."""
    if len(a.opd_affair) > 1 and (a.question_doc or a.answer_doc):
        print("--question-doc / --answer-doc apply to a single --opd-affair", file=sys.stderr)
        return 2
    from . import gguf_guard

    gguf_guard.ensure()
    be = theta = role_be = None
    if a.mode == "review":
        from .convert import batch

        be, theta = batch.resolve_review(a.backend, a.theta, allow_build_mismatch=a.allow_build_mismatch)
    if getattr(a, "roles_fallback", "none") != "none" and getattr(a, "roles", "rules") != "apertus":
        print("--roles-fallback applies to --roles apertus", file=sys.stderr)
        return 2
    if getattr(a, "roles", "rules") == "apertus":
        from .convert import batch

        role_be = be if be is not None else batch.make_backend(a.backend)
    rows = run(a.opd_affair, source=a.source, rows_file=a.rows, save_rows_file=a.save_rows, mode=a.mode, backend=be,
               theta=theta, question_doc=a.question_doc, answer_doc=a.answer_doc, timeout=a.timeout, tries=a.tries,
               roles=getattr(a, "roles", "rules"), role_backend=role_be,
               roles_fallback=getattr(a, "roles_fallback", "none"))
    many = len(rows) > 1

    def show(r):
        x = r["record"] if (a.record_only and r["status"] == "ok") else r
        return json.dumps(x, ensure_ascii=False, **({} if many else dict(indent=1))) + "\n"
    text = "".join(show(r) for r in rows)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    bad = 0
    for r in rows:
        if r["status"] != "ok":
            bad += 1
            print(f"affair {r['opd_affair']}: {r['status']}: {r['reason']}", file=sys.stderr)
        elif r["needs_review"]:
            for x in r["review"]:
                print(f"affair {r['opd_affair']}: needs review ({x['field']}): {x['reason']}", file=sys.stderr)
            for k in r["suggestions"]:
                if k != "actors":  # the role block's reason is in `review`
                    print(f"affair {r['opd_affair']}: needs review ({k}): Apertus suggestion", file=sys.stderr)
    return 2 if bad else 0


# ------------------------------------------------------------------------------------------------ make run step
def _v(x: dict | None) -> str:
    x = x or {}
    return f"value:{x.get('value')}" if x.get("kind") == "value" else f"null:{x.get('null_reason')}"


def compare(rec: dict, sample: dict) -> dict:
    """affair_cli.compare plus the roles, the answering body and the title (the fields the layers write)."""
    c = AC.compare(rec, sample)

    def actors(r):
        return sorted(f"{a['role']}={_v(a.get('name'))}" for a in r.get("actors") or [])

    def date_roles(r):
        q = (r.get("qa") or [{}])[0].get("answer_date") or {}
        return sorted(f"{d['role']}={_v(d.get('date'))}" for d in r.get("dates") or []) + [
            f"qa.answer_date={q.get('role')}:{_v(q)}"]

    def body(r):
        return [_v(q.get("answering_body")) for q in r.get("qa") or []]
    extra = dict(actor_roles=(actors(rec), actors(sample)), date_roles=(date_roles(rec), date_roles(sample)),
                 answering_body=(body(rec), body(sample)), title=(rec.get("title"), sample.get("title")))
    c["checks"].update({k: a == b for k, (a, b) in extra.items()})
    c["detail"] = {k: dict(command=a, sample=b) for k, (a, b) in extra.items() if a != b}
    c["answering_body"] = body(rec)
    c["n_actors"], c["n_dates"] = len(rec.get("actors") or []), len(rec.get("dates") or [])
    return c


def step(ctx: dict) -> dict:
    """`make run` step affair_cli: affair_cli.step's run with this module's record and comparison (module docstring)."""
    if not ctx.get("online"):
        return dict(status="SKIP", summary="offline: the affair command fetches the documents from their sources")
    samples = AC._samples()
    if not samples:
        return dict(status="SKIP", summary=f"no committed samples in {AC.SAMPLES_DIR}")
    ids = [s["ref"]["opd_id"] for _, s in samples]
    live = os.environ.get("GP_AFFAIR_LIVE_EXPORTS") == "1"
    rows_file = None if live or not AC.SAMPLE_ROWS.exists() else str(AC.SAMPLE_ROWS)
    from .deadline import request_timeout

    budget = float(os.environ.get("GP_AFFAIR_CLI_BUDGET", "240"))
    rows = run(ids, source="exports" if live else "auto", rows_file=rows_file, budget_s=budget,
               timeout=request_timeout(), tries=2)
    out_dir = Path(ctx.get("out") or "out") / "affair_cli"
    out_dir.mkdir(parents=True, exist_ok=True)
    per, failed, unreachable = [], [], []
    for (p, sample), r in zip(samples, rows):
        tag = f"{sample['ref']['body_key']}:{sample['ref']['opd_id']}"
        (out_dir / f"{sample['ref']['body_key']}_{sample['ref']['opd_id']}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if r["status"] == "ok":
            r = AC._copies_match(r, sample)
        if r["status"] != "ok":
            (unreachable if r["status"] in AC.UNREACHABLE else failed).append(f"{tag} {r['status']}")
            per.append(dict(affair=tag, status=r["status"], reason=r["reason"][:300]))
            continue
        c = compare(r["record"], sample)
        ok = all(c["checks"].values())
        if not ok:
            failed.append(f"{tag} differs from {p.name} in {', '.join(k for k, v in c['checks'].items() if not v)}")
        copies = [f"{d['role']} from OPD's copy (source: {d['source_error'].split(' ', 1)[0]})"
                  for d in ((r.get("sources") or {}).get("documents") or []) if d.get("fetched_from") == "opd_copy"]
        per.append(dict(affair=tag, sample=p.relative_to(ROOT).as_posix(), status="ok" if ok else "differs",
                        documents_from_opd_copy=copies, qa_items=c["qa_items"], sample_qa_items=c["sample_qa_items"],
                        needs_review=r["needs_review"], answer_date=c["answer_date"],
                        sample_answer_date=c["sample_answer_date"], answering_body=c["answering_body"],
                        n_actors=c["n_actors"], n_dates=c["n_dates"], fields_compared=c["compared"],
                        fields_equal=c["equal"], fields_differ=c["differ"], checks=c["checks"], detail=c["detail"]))
    done = [x for x in per if x["status"] in ("ok", "differs")]
    src = "committed export slice" if rows_file else "live exports"
    summary = (f"affair command on {len(samples)} sample affairs (rows: {src}; documents fetched; post layers applied): "
               + "; ".join(f"{x['affair']} " + (
                   f"valid, answer date {x['answer_date']}, {x['n_actors']} actors, {x['n_dates']} dates, answering body "
                   f"{', '.join(x['answering_body']) or 'none'}, {x['qa_items'][0]} Q/A items ({x['qa_items'][1]} answers "
                   f"located), roles {'=' if x['checks']['actor_roles'] and x['checks']['date_roles'] else '!='} sample, "
                   f"{x['fields_equal']}/{x['fields_compared']} comparable fields equal to the "
                   f"{x['sample'].rsplit('/', 1)[-1].split('_', 1)[0].upper()} sample"
                   + (f" ({'; '.join(x['documents_from_opd_copy'])})" if x["documents_from_opd_copy"] else "")
                   if x in done else x["status"]) for x in per))
    if failed:
        return dict(status="FAIL", summary=summary + f"; FAIL: {'; '.join(failed)}", affairs=per)
    if not done:
        return dict(status="SKIP", summary=f"no source reachable ({'; '.join(unreachable)})", affairs=per,
                    reasons=[x for x in per if x["status"] in AC.UNREACHABLE])
    return dict(status="PASS", summary=summary + (f"; unreachable: {'; '.join(unreachable)}" if unreachable else ""),
                affairs=per)


# ------------------------------------------------------------------------------------------------ P5 through the command
def p5_inputs() -> list[dict]:
    return [json.loads(x) for x in P5_AFFAIRS.read_text(encoding="utf-8").splitlines() if x.strip()]


@contextlib.contextmanager
def _cached_documents(sha_by_url: dict[str, str]):
    """affair_cli fetches by URL; here each document is read from the PDF cache by the sha256 P5 recorded (a missing
    one is fetched through pdftext.fetch_pdf, which checks that sha256)."""
    from . import pdftext

    saved = AC._fetch_text

    def fetch(url: str, timeout: int, tries: int):
        sha, path = pdftext.fetch_pdf(url, expect_sha256=sha_by_url.get(url), timeout=timeout, tries=tries)
        return sha, pdftext.extract(sha, path, ocr=True)
    AC._fetch_text = fetch
    try:
        yield
    finally:
        AC._fetch_text = saved


def p5_rows(refresh: bool = False) -> dict:
    """OPD's rows of the P5 affairs: the committed slice, or (refresh) read once from the census snapshot (GP_OPD_RAW,
    GP_DOCS_META) and saved."""
    if P5_ROWS.exists() and not refresh:
        rows = AC.load_rows(P5_ROWS)
        rows["sources"] = dict(rows.get("sources") or {}, slice=P5_ROWS.relative_to(ROOT).as_posix())
        return rows
    rows = read_rows([r["affair_id"] for r in p5_inputs()], "local")
    AC.save_rows(rows, P5_ROWS)
    rows["sources"] = dict(rows.get("sources") or {}, slice=P5_ROWS.relative_to(ROOT).as_posix())
    return rows


def p5_build(refresh_rows: bool = False, created: str | None = None) -> list[dict]:
    """The P5 affairs through affair_cli.build on P5's documents (pre-layer product rows); raises on a failure."""
    rows = p5_rows(refresh_rows)
    out = []
    for e in p5_inputs():
        docs = {d["role"]: d for d in e["docs"]}
        sha_by_url = {d["url"]: d["sha256"] for d in e["docs"]}
        row = rows["affairs"][e["affair_id"]]
        body = row["affair"]["body_key"]
        with _cached_documents(sha_by_url):
            r = AC.build(e["affair_id"], row, rows["names"].get(body, []), sources=rows.get("sources"),
                         question_doc=(docs.get("question") or {}).get("doc_id"),
                         answer_doc=(docs.get("answer") or {}).get("doc_id"))
        if created:
            r["record"]["extraction"]["created"] = created
        out.append(r)
    return out


def _norm(r: dict) -> dict:
    r = json.loads(json.dumps(r))
    r["record"]["extraction"].pop("created", None)
    return r


def p5_check() -> dict:
    """Rebuild the P5 rows and compare with the committed file (the timestamp aside); SKIP when not cached."""
    from .schema.v0_2_roles import pages_of

    missing = [f"{e['affair_id']}:{d['role']}" for e in p5_inputs() for d in e["docs"]
               if pages_of(d["sha256"], bool(d.get("image_only"))) is None]
    if missing or not P5_OUT.exists():
        return dict(status="SKIP", summary=f"P5 command records not rebuilt: {len(missing)} documents not cached")
    old = [json.loads(x) for x in P5_OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    new = p5_build()
    same = [_norm(a) for a in old] == [_norm(b) for b in new]
    return dict(status="PASS" if same else "FAIL",
                summary=f"P5 records rebuilt by the affair command from {len(new)} cached affairs: "
                        + ("identical to the committed file" if same else "DIFFER from the committed file"))


def load_p5() -> list[dict]:
    """The committed P5 records made by the affair command (before the post layers)."""
    return [json.loads(x)["record"] for x in P5_OUT.read_text(encoding="utf-8").splitlines() if x.strip()]


def published_summary() -> dict:
    """Offline: the federal affair of the committed slice through the command vs its published record, and what the
    published P5 records (made by the command) carry."""
    out = {}
    recs = {json.loads(x)["ref"]["opd_id"]: json.loads(x) for x in
            (ROOT / "results" / "schema" / "v0_2" / "fed_records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
    r = run([157601], rows_file=str(FED_SLICE))[0]
    if r["status"] == "ok":
        c = compare(r["record"], recs[157601])
        out["federal"] = dict(affair="CHE:157601", slice=FED_SLICE.relative_to(ROOT).as_posix(), status="ok",
                              fields_compared=c["compared"], fields_equal=c["equal"], checks=c["checks"])
    else:
        out["federal"] = dict(affair="CHE:157601", status=r["status"], reason=r.get("reason"))
    p5 = [json.loads(x) for x in (ROOT / "results" / "schema" / "v0_2" / "p5_records.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]

    def located(v):
        return bool(v) and v.get("kind") == "value" and v.get("page") is not None and v.get("char_start") is not None
    out["p5"] = dict(n_records=len(p5),
                     with_title=sum(1 for x in p5 if isinstance(x.get("title"), dict) and any(
                         isinstance(v, str) and v.strip() for v in x["title"].values())),
                     answer_date_located=sum(1 for x in p5 if located(((x.get("qa") or [{}])[0]).get("answer_date"))))
    return out


def samples(check: bool = False) -> int:
    """The `make run` step affair_cli (network: the documents are fetched from their sources) plus published_summary,
    written to results/affair_cli/product_check.json (--check: compare the per-affair field counts with the file)."""
    st = step(dict(online=True, out=os.environ.get("GP_OUT", "out")))
    res = dict(label="the operator command (python -m gegenprobe affair) vs the published records; no model",
               command="PYTHONPATH=src:. python -m gegenprobe.affair_product samples",
               step_status=st["status"],
               samples={x["affair"]: dict(status=x["status"], fields_compared=x.get("fields_compared"),
                                          fields_equal=x.get("fields_equal"), answer_date=x.get("answer_date"),
                                          answering_body=x.get("answering_body"), n_actors=x.get("n_actors"),
                                          n_dates=x.get("n_dates"), checks=x.get("checks"))
                        for x in st.get("affairs") or []},
               **published_summary())
    if check:
        old = json.loads(CHECK_OUT.read_text(encoding="utf-8"))
        keep = ("samples", "federal", "p5")
        same = {k: old.get(k) for k in keep} == {k: res.get(k) for k in keep}
        print(("PASS" if same else "FAIL") + f": {st['summary']}")
        return 0 if same else 1
    CHECK_OUT.parent.mkdir(parents=True, exist_ok=True)
    CHECK_OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{st['status']}: {st['summary']}")
    return 0 if st["status"] == "PASS" else 1


def main(argv: list[str]) -> int:
    if argv[:1] == ["samples"]:
        return samples("--check" in argv)
    ap = argparse.ArgumentParser(prog="python -m gegenprobe.affair_product")
    ap.add_argument("what", choices=["p5"])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--refresh-rows", action="store_true", help="re-read the P5 affairs' OPD rows from GP_OPD_RAW / "
                    "GP_DOCS_META and rewrite data/affair_cli/opd_rows_p5.json")
    a = ap.parse_args(argv)
    if a.check:
        r = p5_check()
        print(f"{r['status']}: {r['summary']}")
        return 1 if r["status"] == "FAIL" else 0
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows = p5_build(a.refresh_rows, created)
    P5_OUT.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    c = collections.Counter(r["status"] for r in rows)
    print(f"{P5_OUT.relative_to(ROOT)}: {len(rows)} P5 affairs ({dict(c)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
