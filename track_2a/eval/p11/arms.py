"""P11 arms (eval/p11/PROTOCOL.md §4). The arms read the same cached texts the packets show, never a label, and run only
after the cell's gold is merged (and committed); no annotator sees their output.

    PYTHONPATH=src:. .venv/bin/python -m eval.p11.arms it-offline
        no network, no model -> results/p11/it_arms_offline.json, results/p11/it_records_v0_2.jsonl,
        data/p11/it_candidates.jsonl
    PYTHONPATH=src:. .venv/bin/python -m eval.p11.arms it-pointer --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p11:1.0
        Apertus through the project's budget gateway (tag 2a-p11, cap USD 1.00 for both model arms together): the date
        pointer first, then the role reader -> results/p11/it_arms_pointer.json (+ the hash-keyed model cache)
    PYTHONPATH=src:. .venv/bin/python -m eval.p11.arms ni-offline
        no network, no model -> results/p11/ni_arms_offline.json, results/p11/ni_records_v0_2.jsonl

The converter (both cells) is the existing whole-affair command, `gegenprobe.affair_cli.build` in rules_only mode (OPD
metadata first, the frozen rules and P1 answer-date cascade on the documents, product post-processing, the v0.2 carry, the
role rules, Q/A pairing, document parts, validation by the v0.2 model), unchanged, with two inputs pinned so that it
reads exactly what the annotators read and makes no request: OPD's rows are the vendored snapshot rows
(data/p11/opd_meta_p11.jsonl + the document rows in data/p11/p11_affairs.jsonl), and `affair_cli.fetch_doc` returns the
documents fetched in the draw (sha256-checked cache; a document whose fetch failed raises the recorded typed failure).
IT names the two documents (--question-doc / --answer-doc); NI lets the converter pick them by its own pairing rule.

IT arms:
  answer date  rules     the frozen P1 rules arm `convert.rules.answer_date(answer pages)` (value if status "value")
               record    the converter record's `qa[0].answer_date` (the frozen P1 cascade)
               latest    no model: the latest date the converter's date lattice finds in the document typed as the answer
               pointer   the frozen P1 pointer `convert.pointer.answer_date(backend, answer pages, "it", θ,
                         anchors=rules.anchors(...))`, θ from data/convert/theta/<build>.json (10.395 for the gateway
                         build), the backend wrapped in the review mode's BuildGuard
  author roles rules     the frozen role rules `convert.roles.extract(q, a, body)["actors"]` (P10's arm b)
               record    the converter record's actors with one of P8's authorship roles (role rules +
                         role_consistency; an actor OPD's metadata gives the v0.1 role `submitter` is not a pair)
               reader    the frozen P10 role reader `convert.roles_pointer.read` on `convert.role_candidates` candidates
                         with data/p10/p10_config.json (tau 0.98, tau_first 0.30, cue rule), prompt language it
               doc_order no model: P10's post hoc document-order baseline (`eval.p10.posthoc_baselines.order_pairs` on the
                         candidates in document order: one -> sole_author; several -> the first first_signatory, the rest
                         co_signatory)
               opd_first reference, no document: OPD's contributor list mapped by P10's `opd_pairs(..., "first_and_co")`
  instrument   record    the record's type.instrument_function / instrument_named
  language     record    the record's documents[].language_of_text
NI arm: the converter's status (a valid v0.2 record, or the typed failure), and per schema field what the record carries
(a value, a typed null and its reason, an empty list and its reason, or nothing).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: affair_cli and pdftext import gegenprobe.net (compliance/fetchguard.py)

from eval.p10 import common as C10  # noqa: E402
from eval.p11 import common as C  # noqa: E402
from eval.p11 import packets as P  # noqa: E402
from gegenprobe.paths import DATA, PDF_CACHE  # noqa: E402

THETA_DIR = DATA / "convert" / "theta"
IT_OFF = C.R11 / "it_arms_offline.json"
IT_PTR = C.R11 / "it_arms_pointer.json"
NI_OFF = C.R11 / "ni_arms_offline.json"
IT_REC = C.R11 / "it_records_v0_2.jsonl"
NI_REC = C.R11 / "ni_records_v0_2.jsonl"
CANDS = C.D11 / "it_candidates.jsonl"
BACKEND = "gateway:swiss-ai/apertus-v1.5-8b:2a-p11:1.0"
LABEL = "EXPLORATORY P11 (eval/p11/PROTOCOL.md)"
FETCH_KEYS = ("doc_id", "name", "url", "opd_text_status", "opd_chars", "sha256", "pages", "chars", "extractor",
              "image_only", "fetched_from", "copy_url", "source_error")


def affairs(cell: str) -> list[dict]:
    rows = [r for r in C._jsonl(C.AFFAIRS) if r["cell"] == cell]
    if not rows:
        raise SystemExit(f"{C.AFFAIRS} has no {cell} affair: run `eval.p11.draw fetch` first")
    return rows


def gold_first(cell: str) -> None:
    """Order of operations (PROTOCOL §9): the arms run only after the cell's merged gold exists (and is committed)."""
    if not C.GOLD[cell].exists():
        raise SystemExit(f"{C.GOLD[cell]} missing: merge and commit the {cell} gold before running any arm")


# ------------------------------------------------------------------------------------------------ the converter
@contextlib.contextmanager
def served(row: dict):
    """affair_cli.fetch_doc returns the documents fetched in the draw (no request); a recorded failure is re-raised."""
    from gegenprobe import affair_cli as AC

    got = {d["doc_id"]: d for d in row["docs"]}
    fails = {}
    for d in (row.get("converter_docs") or {}).values():
        if d.get("error"):
            fails[d["doc_id"]] = d["error"]
        else:
            got.setdefault(d["doc_id"], d)

    def fetch_doc(role: str, d: dict, timeout: int = 60, tries: int = 2) -> dict:
        did = d["id"]
        if did in fails:
            raise AC.AffairError(fails[did]["kind"], fails[did]["detail"])
        e = got.get(did)
        if e is None:
            raise AC.AffairError("not_fetched", f"{role} document opd:{did} was not fetched in the P11 draw")
        if not (PDF_CACHE / f"{e['sha256']}.pdf").exists():
            raise SystemExit(f"document {did}: the fetched PDF {e['sha256']} is not in the cache (WORK/pdf)")
        return dict(role=role, **{k: e[k] for k in FETCH_KEYS if e.get(k) is not None})

    saved = AC.fetch_doc
    AC.fetch_doc = fetch_doc
    try:
        yield
    finally:
        AC.fetch_doc = saved


def converter(row: dict, M: dict, N: dict, names_docs: bool) -> dict:
    """{status, record?, reason?, review?, documents?} from affair_cli.build (rules_only) on the vendored rows."""
    from gegenprobe import affair_cli as AC

    m = M[row["affair_id"]]
    r = dict(affair=m["affair"], events=m["events"], contributors=m["contributors"], docs=row["opd_docs"])
    kw = {}
    if names_docs:
        by = {d["role"]: d["doc_id"] for d in row["docs"]}
        kw = dict(question_doc=by["question"], answer_doc=by["answer"])
    src = dict(single_exports=dict(source="vendored", location="data/p11/opd_meta_p11.jsonl (OPD snapshot in GP_OPD_RAW)"))
    with served(row):
        try:
            out = AC.build(row["affair_id"], r, N.get(row["body"], []), sources=src, mode="rules_only", **kw)
        except AC.AffairError as e:
            return dict(status=e.kind, reason=e.detail[:600])
    return dict(status="ok", record=out["record"], needs_review=out["needs_review"], review=out["review"],
                documents=out["sources"]["documents"], answer_link_status=out["sources"]["answer_link_status"])


def _meta():
    from gegenprobe.affair import meta

    return meta.load(C.META), meta.body_names(C.NAMES)


# ------------------------------------------------------------------------------------------------ record views
def record_pairs(rec: dict | None) -> list[tuple[str, str]]:
    return [(x["name"]["value"], x["role"]) for x in (rec or {}).get("actors") or []
            if x.get("role") in C10.ROLES and (x.get("name") or {}).get("kind") == "value"]


def _vs(v: dict | None) -> str:
    """value / null:<reason> / absent of one provenance-bearing field."""
    if not v:
        return "absent"
    return "value" if v.get("kind") == "value" else f"null:{v.get('null_reason')}"


def _empty(rec: dict, path: str) -> str:
    r = (rec.get("empty_reasons") or {}).get(path)
    return f"empty:{r['reason']}" if r else "absent"


SUBMISSION_DATE_ROLES = {"submitted", "signed", "lodged", "received", "announced"}
AUTHOR_ROLES = {"sole_author", "first_signatory", "joint_author", "spokesperson", "submitter"}
COSIGN_ROLES = {"co_signatory", "supporter"}


def record_status(rec: dict, f: str) -> str:
    """What a v0.2 record carries for one of the 17 schema fields (GUIDE_P11_NI.md §3 names the same fields)."""
    dates, actors, qa = rec.get("dates") or [], rec.get("actors") or [], rec.get("qa") or []
    roles = {d.get("role") for d in dates}
    ad = qa[0].get("answer_date") if qa else None
    if f == "date_submission":
        return "value" if roles & SUBMISSION_DATE_ROLES else _empty(rec, "dates") if not dates else "absent"
    if f in ("date_decision", "date_dispatch"):
        want = "answer_decided" if f == "date_decision" else "answer_dispatched"
        if want in roles or (ad or {}).get("role") == want:
            return "value"
        if not qa:
            return _empty(rec, "qa")
        return "value_role_unsplit" if (ad or {}).get("kind") == "value" else _vs(ad)
    if f == "date_answer":
        return _vs(ad) if qa else _empty(rec, "qa")
    if f == "qa_pairing":
        return ("value" if qa[0].get("items") else _empty(rec, "qa.0.items")) if qa else _empty(rec, "qa")
    if f == "related_affairs":
        return "value" if rec.get("related_affairs") else _empty(rec, "related_affairs")
    if f == "documents_usable_text":
        docs = rec.get("documents") or []
        return ("value" if all(d.get("extractor") for d in docs) else "partial") if docs else _empty(rec, "documents")
    if f == "answer_link_status":
        v = rec.get("answer_link_status")
        return f"value:{v}" if v else "absent"
    if f == "procedural_history":
        return "value" if dates else _empty(rec, "dates")
    if f == "type":
        return _vs((rec.get("type") or {}).get("instrument_function"))
    if f == "procedural_state":
        return _vs(rec.get("procedural_state"))
    if f == "decision_outcome":
        return _vs(rec.get("decision"))
    if f == "government_recommendation":
        return _vs(rec.get("government_recommendation"))
    if f == "submitter":
        return "value" if any(a.get("role") in AUTHOR_ROLES for a in actors) else _empty(rec, "actors") if not actors \
            else "absent"
    if f == "co_signatories":
        return "value" if any(a.get("role") in COSIGN_ROLES for a in actors) else _empty(rec, "actors") if not actors \
            else "absent"
    if f == "addressed_body":
        return "value" if any(a.get("role") == "addressed_body" for a in actors) else "absent"
    if f == "language":
        docs = rec.get("documents") or []
        return "value" if docs and all(d.get("language_of_text") for d in docs) else "partial" if docs else \
            _empty(rec, "documents")
    raise ValueError(f)


def _doc_lang(rec: dict | None, doc_id: int) -> list[str] | None:
    for d in (rec or {}).get("documents") or []:
        if d.get("doc_id") == f"opd:{doc_id}":
            return d.get("language_of_text") or []
    return None


def _type_field(rec: dict | None, k: str) -> str | None:
    v = ((rec or {}).get("type") or {}).get(k) or {}
    return v.get("value") if v.get("kind") == "value" else None


# ------------------------------------------------------------------------------------------------ IT
def date_arms(pages_a: list[str], image_only: bool) -> dict:
    from gegenprobe.convert import lattice, rules

    dd = [c["value"] for c in lattice.dates(pages_a)]
    r = rules.answer_date(pages_a, image_only)
    return dict(doc_dates=sorted(set(dd)), latest=max(dd) if dd else None,
                rules=dict(status=r["status"], value=r.get("value") if r["status"] == "value" else None,
                           rule=r.get("rule")))


def it_offline() -> dict:
    from eval.p10 import arms as A10
    from eval.p10 import posthoc_baselines as PB
    from gegenprobe.convert import role_candidates as RC

    gold_first("it")
    rows = affairs("it")
    M, N = _meta()
    per, recs, cands = [], [], []
    for row in rows:
        pages = P.pages_of(row)
        q, a = pages["question"], pages["answer"]
        img = next(bool(d.get("image_only")) for d in row["docs"] if d["role"] == "answer")
        conv = converter(row, M, N, names_docs=True)
        rec = conv.get("record")
        if rec:
            recs.append(rec)
        cd = RC.candidates(q, a, N.get(row["body"], []))
        cands.append(dict(affair_id=row["affair_id"], **cd))
        ad = ((rec or {}).get("qa") or [{}])[0].get("answer_date") or {}
        per.append(dict(
            affair_id=row["affair_id"], body=row["body"], stratum=row["stratum"], affair_type=row["affair_type"],
            converter_status=conv["status"], converter_reason=conv.get("reason"),
            answer_date=dict(date_arms(a, img), record=ad.get("value") if ad.get("kind") == "value" else None,
                             record_status=_vs(ad) if rec else conv["status"]),
            roles=dict(rules=A10.rules_pairs(q, a, row["body"]), record=record_pairs(rec),
                       doc_order=PB.order_pairs(PB.cand_names(cd["candidates"])),
                       opd_first=A10.opd_pairs(M.get(row["affair_id"]), "first_and_co"),
                       n_candidates=len(cd["candidates"])),
            instrument=dict(function=_type_field(rec, "instrument_function"),
                            named=_type_field(rec, "instrument_named"),
                            harmonised=((rec or {}).get("type") or {}).get("harmonised")),
            language={d["role"]: _doc_lang(rec, d["doc_id"]) for d in row["docs"]},
            fetched_from={d["role"]: d["fetched_from"] for d in row["docs"]}))
    C.R11.mkdir(parents=True, exist_ok=True)
    with open(CANDS, "w", encoding="utf-8") as f:
        for x in cands:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    IT_REC.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs), encoding="utf-8")
    out = dict(label=LABEL + ": IT cell, no-model arms", n=len(per), records_valid=len(recs), per_affair=per)
    IT_OFF.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return dict(n=len(per), records_valid=len(recs), candidates=str(CANDS))


def it_pointer(spec: str) -> dict:
    from eval import arms as EA
    from gegenprobe import llm
    from gegenprobe.convert import build_guard, pointer, rules
    from gegenprobe.convert import roles_pointer as RP

    gold_first("it")
    rows = affairs("it")
    cands = {r["affair_id"]: r for r in C._jsonl(CANDS)}
    if len(cands) != len(rows):
        raise SystemExit("run `arms it-offline` first (the candidates are written there)")
    be = EA.backend(spec)
    if be is None:
        raise SystemExit("the pointer arms need a model backend")
    tp = THETA_DIR / f"{llm._slug(be.build)}.json"
    if not tp.exists():
        raise SystemExit(f"no frozen θ for {be.build} ({tp})")
    theta = json.loads(tp.read_text())["answer_date"]["theta"]
    gbe = build_guard.BuildGuard(be, build_guard.fitted(tp))
    cfg = json.loads(C10.CONFIG.read_text())
    per = {r["affair_id"]: dict(affair_id=r["affair_id"], body=r["body"], stratum=r["stratum"]) for r in rows}
    stop = dict(date_pointer=None, role_reader=None)
    # 1. the date pointer (stop rules: the budget cap; a served build θ was not fitted on)
    for r in rows:
        a = P.pages_of(r)["answer"]
        try:
            p = pointer.answer_date(gbe, a, "it", theta, anchors=rules.anchors(a))
        except build_guard.BuildMismatch as x:
            stop["date_pointer"] = f"BuildMismatch at affair {r['affair_id']}: {x.msg}"
            break
        except RuntimeError as x:
            if "BUDGET" not in str(x):
                raise
            stop["date_pointer"] = f"budget cap reached at affair {r['affair_id']}: {x}"
            break
        per[r["affair_id"]]["date_pointer"] = dict(value=p.value, margin=p.margin, n_cands=len(p.candidates),
                                                   truncated=p.truncated)
    # 2. the role reader (stop rule: the budget cap; P10's ServedModelMismatch stops the run inside llm)
    for r in rows:
        pages = P.pages_of(r)
        try:
            res = RP.read(be, pages["question"], pages["answer"], cands[r["affair_id"]]["candidates"], "it",
                          cfg["pointer"])
        except RuntimeError as x:
            if "BUDGET" not in str(x):
                raise
            stop["role_reader"] = f"budget cap reached at affair {r['affair_id']}: {x}"
            break
        per[r["affair_id"]]["role_reader"] = dict(pairs=[(x["name"]["value"], x["role"]) for x in res["actors"]],
                                                  result=res)
    served = sorted(getattr(be, "served", set()))
    out = dict(label=LABEL + ": IT cell, Apertus arms", build=be.build, theta_answer=theta,
               role_reader_config="data/p10/p10_config.json", served_fingerprints=served,
               fingerprints_not_seen_in_role_reader_development=sorted(set(served) - set(cfg.get("dev_fingerprints") or [])),
               stopped=stop, n_date_pointer=sum("date_pointer" in v for v in per.values()),
               n_role_reader=sum("role_reader" in v for v in per.values()), per_affair=list(per.values()))
    C.R11.mkdir(parents=True, exist_ok=True)
    IT_PTR.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {k: out[k] for k in ("build", "served_fingerprints", "stopped", "n_date_pointer", "n_role_reader")}


# ------------------------------------------------------------------------------------------------ NI
def ni_offline() -> dict:
    from eval.p11.annotate import NI_FIELDS

    gold_first("ni")
    rows = affairs("ni")
    M, N = _meta()
    per, recs = [], []
    for row in rows:
        conv = converter(row, M, N, names_docs=False)
        rec = conv.get("record")
        if rec:
            recs.append(rec)
        per.append(dict(affair_id=row["affair_id"], body=row["body"], stratum=row["stratum"], ni_type=row["ni_type"],
                        lang=row["lang"], type_source=row["type_source"], converter_status=conv["status"],
                        converter_reason=conv.get("reason"),
                        record_type=((rec or {}).get("type") or {}).get("harmonised"),
                        fields={f: record_status(rec, f) for f in NI_FIELDS} if rec else None,
                        converter_documents=conv.get("documents")))
    C.R11.mkdir(parents=True, exist_ok=True)
    NI_REC.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs), encoding="utf-8")
    out = dict(label=LABEL + ": NI cell, the converter", n=len(per), records_valid=len(recs), per_affair=per)
    NI_OFF.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return dict(n=len(per), records_valid=len(recs))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["it-offline", "it-pointer", "ni-offline"])
    ap.add_argument("--backend", default=BACKEND)
    a = ap.parse_args()
    r = it_offline() if a.cmd == "it-offline" else it_pointer(a.backend) if a.cmd == "it-pointer" else ni_offline()
    print(json.dumps(r, indent=1, ensure_ascii=False))
    sys.exit(0)
