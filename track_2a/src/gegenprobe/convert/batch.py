"""Convert one document or a batch of documents into reviewer-ready rows (see convert/output.py for the row format).

  convert_pages(...)   the conversion proper, on page texts already extracted (used by the CLI and by tests)
  convert_one(...)     get the document (URL or path), extract text, convert; any failure becomes a typed row
  run_batch(...)       many inputs from a .tsv/.csv (header with url|path|source, optional opd_doc_id, body,
                       affair_number, affair_type, lang, doc_category) or a .txt (one URL or path per line); JSONL out,
                       resumable. affair_type is normalised to OPD's harmonised name (convert/affair_types.py); an
                       unknown value is an error (UnknownAffairType), never silently ignored
  queue_nulls          (convert_pages / convert_one / run_batch) a rules-only null answer date on a document that is
                       an answer (doc_role `answer`, or OPD's category says answer: category_harmonized `response_text`,
                       or a category label the census counts as an answer document) is flagged needs_review, so it
                       reaches the review queue with its candidates instead of staying an unattended null
  resolve_review(...)  the backend and the per-build θ for review mode, with a clear message when none is fitted; the
                       backend comes wrapped in convert.build_guard (stops on a served build θ was not fitted on)
  anchors_review       (convert_pages / convert_one / run_batch) a value from a user anchor keeps needs_review true
                       (--anchors-review), for anchors you have not measured yet
  letter-line hint     no answer heading, but a letter address to the parliament followed by a place-date line
                       (convert/hints.py): that date goes first among the candidates, marked suggested_by_letter_line,
                       and the field is flagged; it is never written into the field
  resume               every batch row stores `options` (anchors file sha256, mode, affair type, queue_nulls,
                       anchors_review, explain, review build and θ, the input row) and their hash; a re-run skips an
                       input only when its last row has the same hash, otherwise it converts it again and appends the new
                       row. The last row per input wins (write_queue reads only the last). A row written before
                       options were recorded is skipped and counted as such (use a fresh --out to redo it)

The frozen converter (cascade, rules, pointer) is used unchanged; this module only wraps it.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

from .. import pdftext
from ..paths import PDF_CACHE
from . import cascade, hints, modes, output, overlay, pointer, rules

INPUT_KEYS = ("source", "opd_doc_id", "body", "affair_number", "affair_type", "lang", "doc_category")
STOP = {
    "de": r"\b(der|die|das|und|nicht|Regierungsrat|wird|werden|vom)\b",
    "fr": r"\b(le|la|les|et|des|du|Conseil|est|pour)\b",
    "it": r"\b(il|la|che|e|del|della|Consiglio|per|sono)\b",
}
ROLE_TO_DOCROLE = {"answer": "answer", "question": "question", "other": "other"}


def guess_lang(text: str) -> str:
    counts = {lg: len(re.findall(rx, text[:20000])) for lg, rx in STOP.items()}
    return max(counts, key=counts.get)


# --------------------------------------------------------------------------------------------------- getting the PDF
def get_document(source: str, timeout: int = 60, tries: int = 2) -> tuple[str, Path]:
    """URL -> polite fetch into the cache; local path -> copied into the cache. Raises typed errors (output.classify)."""
    if re.match(r"https?://", source):
        return pdftext.fetch_pdf(source, timeout=timeout, tries=tries)
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {source}")
    b = p.read_bytes()
    if b"%PDF" not in b[:1024]:
        raise pdftext.FetchError("not_a_pdf", f"{source} has no PDF header")
    sha = pdftext.sha256_bytes(b)
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    dest = PDF_CACHE / f"{sha}.pdf"
    if not dest.exists():
        shutil.copyfile(p, dest)
    return sha, dest


# --------------------------------------------------------------------------------------------------- review mode
def fitted_builds() -> list[str]:
    from eval.arms import THETA_DIR
    out = []
    for f in sorted(THETA_DIR.glob("*.json")):
        try:
            out.append(json.loads(f.read_text())["build"])
        except (KeyError, ValueError):
            continue
    return out


def make_backend(spec: str):
    """openai (LLM_BASE_URL / LLM_NAME / LLM_API_KEY) | gguf (local Apertus 8B, CPU) | gateway:<model>:<tag>:<cap> (dev)."""
    import os
    if spec == "gguf":
        from ..gguf_fast import GGUFFast
        return GGUFFast()
    if spec == "openai":
        from ..llm import OpenAICompat
        base, name = os.environ.get("LLM_BASE_URL", ""), os.environ.get("LLM_NAME", "")
        if not (base and name):
            raise SystemExit("review mode with --backend openai needs LLM_BASE_URL and LLM_NAME (and LLM_API_KEY) set")
        host = urllib.parse.urlsplit(base).netloc
        build = f"publicai:{name}" if host == "api.publicai.co" else name   # θ files are keyed by served build
        return OpenAICompat(build=build)
    from eval.arms import backend
    return backend(spec)


def resolve_review(spec: str, theta_override: float | None = None, allow_build_mismatch: bool = False):
    """-> (backend, θ). θ is per build (it does not transfer across builds, quantisations or prompts): the backend comes
    wrapped in convert.build_guard.BuildGuard, which stops the run when the served model is not the build θ was fitted on
    (unless allow_build_mismatch). A θ given explicitly (theta_override) is not checked."""
    from eval.arms import theta_path

    from .build_guard import BuildGuard, fitted
    be = make_backend(spec)
    if theta_override is not None:
        return be, float(theta_override)
    tp = theta_path(be.build)
    if not tp.exists():
        have = fitted_builds()
        raise SystemExit(
            f"review mode needs a threshold θ fitted for the build '{be.build}', and none is in data/convert/theta/.\n"
            f"Fitted builds: {', '.join(have) or 'none'}.\n"
            "Fit one on the dev set (make theta BACKEND=...), or choose a backend whose build is listed. "
            "Note: publicai:* builds were used for evaluation only; they are not a runtime target."
        )
    return BuildGuard(be, fitted(tp), allow_mismatch=allow_build_mismatch), json.loads(tp.read_text())["answer_date"]["theta"]


# --------------------------------------------------------------------------------------------------- conversion
def answer_doc_evidence(role: dict, inp: dict) -> str | None:
    """Why this document counts as an answer for --queue-nulls: the converter's own doc_role, or OPD's category."""
    from ..census import defs

    if role.get("value") == "answer":
        return f"doc_role answer: {role.get('basis')}"
    cat = (inp.get("doc_category") or "").strip()
    if cat and (cat == "response_text" or defs.ANS_DOC.search(cat)):
        return f"OPD document category '{cat}'"
    return None


def convert_pages(pages: list[str], *, sha: str, extractor: str, image_only: bool, inp: dict, mode: str = "rules_only",
                  backend=None, theta: float | None = None, url: str | None = None, anchors: dict | None = None,
                  explain: bool = False, queue_nulls: bool = False, anchors_review: bool = False) -> dict:
    from ..schema import schema_v0_1 as schema

    lang = inp.get("lang") or guess_lang("\n".join(pages))
    doc_id = f"opd:{inp['opd_doc_id']}" if inp.get("opd_doc_id") else f"sha256:{sha[:16]}"
    doc = dict(pages=pages, lang=lang, image_only=image_only, extractor=extractor, affair_type=inp.get("affair_type"),
               doc_id=doc_id, sha256=sha)
    rec = cascade.convert(doc)  # backend-free: rules, typed nulls for the residue
    ad = modes.answer_date(doc, mode, backend, theta, use_metadata=False)
    suggestion = ad.pop("suggestion", None)
    rec["fields"]["answer_date"] = {k: v for k, v in ad.items() if k not in ("mode", "needs_review")}
    # ---- unlocked overlay (convert/overlay.py): runs on the frozen result, never inside it
    flags: dict[str, str] = {}  # field -> why a person must look at it
    traces: dict[str, list] = {}
    cov = overlay.coverage(inp.get("body"), anchors)
    specs = overlay.anchors_for(anchors, inp.get("body"))
    afile = (anchors or {}).get("file")
    fa = rec["fields"]["answer_date"]
    if explain:
        traces["answer_date"] = overlay.trace_answer_date(pages, image_only)
        traces["recommendation"] = overlay.trace_recommendation(pages, inp.get("affair_type"))
    if fa.get("value") is None and fa.get("residue") and specs.get("answer_date"):
        hit, tr = overlay.apply_date_anchors(pages, specs["answer_date"], afile)
        traces.setdefault("answer_date", []).extend(tr)
        if hit:
            if hit.pop("needs_review"):
                flags["answer_date"] = hit.pop("review_reason")
            elif anchors_review:
                flags["answer_date"] = (f"value from your anchor {hit['rule'].split(':', 1)[-1]} (--anchors-review: values "
                                        "from user anchors stay flagged until you have measured the anchors)")
            rec["fields"]["answer_date"] = fa = hit
            if suggestion and suggestion.get("value") == hit["value"]:
                suggestion = None  # Apertus agrees with the user's anchor: nothing to review
            elif suggestion:
                flags.setdefault("answer_date", "Apertus suggests a different date than your anchor")
    heading = None
    if fa.get("value") is None and fa.get("rule") == "heading_without_date":
        heading = overlay.heading_date(pages)
        if heading:
            flags["answer_date"] = (f"answer heading '{heading['heading']}' is followed by the date {heading['quote']!r}, "
                                    "but no frozen rule anchors this layout: check candidates[0] "
                                    "(suggested_by_heading_proximity); the field is not filled")
            traces.setdefault("answer_date", []).append(dict(
                step="heading proximity", result=f"date {heading['value']} at p{heading['page']}"
                f"[{heading['char_start']}:{heading['char_end']}] right after '{heading['heading']}' (not written)"))
        else:
            traces.setdefault("answer_date", []).append(dict(step="heading proximity",
                                                             result="no date right after an answer heading"))
    letter = None
    if fa.get("value") is None and fa.get("rule") == "no_anchor":
        letter = hints.letter_line_date(pages)
        if letter:
            flags.setdefault("answer_date", (
                f"no answer heading, but a letter to the parliament ('{letter['address']}') is followed by the place-date "
                f"line {letter['quote']!r}: check candidates[0] (suggested_by_letter_line); the field is not filled"))
        traces.setdefault("answer_date", []).append(dict(
            step="letter-line hint", result=(f"date {letter['value']} at p{letter['page']}[{letter['char_start']}:"
                                             f"{letter['char_end']}] under '{letter['address']}' (not written)") if letter
            else "no place-date line under a letter address to the parliament"))
    fr = rec["fields"].get("recommendation")
    if fr is not None and fr.get("value") is not None and fr.get("route") in ("rule", "ocr+rule"):
        q = overlay.qualify_recommendation(pages, fr)
        if q:
            t = pages[fr["page"] - 1]
            fr.update(value=q["value"], char_end=q["char_end"], quote=re.sub(r"\s+", " ", t[fr["char_start"]:q["char_end"]]),
                      qualifier=q["qualifier"], rule=fr["rule"] + ("+qualifier_partial" if q["value"] == "partial" else ""))
            if q["needs_review"]:
                flags["recommendation"] = q["reason"]
        traces.setdefault("recommendation", []).append(dict(
            step="qualifier", result=(f"'{q['qualifier']['text']}' -> {q['qualifier']['effect']}" if q else
                                      "no qualifier (partiellement, teilweise, im Sinne der Erwägungen, ...) in the sentence")))
    elif fr is not None and fr.get("value") is None and fr.get("null_reason") == "present_unanchored" and \
            specs.get("recommendation"):
        hit, tr = overlay.apply_rec_anchors(pages, specs["recommendation"], afile)
        traces.setdefault("recommendation", []).extend(tr)
        if hit:
            if hit.pop("needs_review"):
                flags["recommendation"] = hit.pop("review_reason")
            elif anchors_review:
                flags["recommendation"] = (f"value from your anchor {str(hit.get('rule', '')).split(':', 1)[-1]} "
                                           "(--anchors-review: values from user anchors stay flagged until you have "
                                           "measured the anchors)")
            rec["fields"]["recommendation"] = fr = hit
    if cov["status"] in ("not_covered", "user_anchors"):
        for name in ("answer_date", "recommendation"):
            f = rec["fields"].get(name)
            if f is None:
                continue
            if f.get("value") is None and f.get("null_reason") == "present_unanchored":
                rec["fields"][name] = dict(f, null_reason="no_rules_for_body",
                                           evidence=f"{f.get('rule')}; body {cov['body']} is not in rules_coverage.json")
                flags.setdefault(name, f"no frozen rules for body {cov['body']} and none of them fired: "
                                       "read the document or use review mode / --anchors")
            elif f.get("value") is not None and f.get("route") in ("rule", "ocr+rule"):
                q = f" (overlay qualifier '{f['qualifier']['text']}' -> {f['value']})" if f.get("qualifier") else ""
                flags.setdefault(name, f"frozen rule {f.get('rule', '').split('+')[0]} fired{q} on body {cov['body']}, "
                                       "whose layouts the rules were never written or measured on")
    role = output.doc_role(pages, rec["fields"]["answer_date"])
    if queue_nulls and not suggestion and "answer_date" not in flags and rec["fields"]["answer_date"].get("value") is None:
        why = answer_doc_evidence(role, inp)
        if why:
            flags["answer_date"] = (f"rules-only null on an answer document ({why}): pick the answer date from candidates "
                                    "or confirm the null (--queue-nulls)")
    record = schema.from_converter(rec, pages, dict(
        source="opd" if inp.get("opd_doc_id") else "other", url=url, language=lang, n_pages=len(pages),
        image_only=image_only, role=ROLE_TO_DOCROLE[role["value"]]))
    rd = json.loads(record.model_dump_json(exclude_none=True))
    ans = rd.get("answer_date") or {}
    if ans.get("kind") == "value" and ans.get("page") is not None:  # the record's context: the anchor, not just the date
        ans["context"] = output.anchor_context(pages, ans["page"], ans["char_start"], ans["char_end"])
    if suggestion and suggestion.get("page") is not None:
        suggestion = dict(suggestion, context=output.anchor_context(pages, suggestion["page"], suggestion["char_start"],
                                                                    suggestion["char_end"]))
    fields = {name: output.flat_field(rec["fields"].get(name), rd.get(name), pages, name)
              for name in ("answer_date", "recommendation", "related_affair") if rec["fields"].get(name) is not None}
    # the closed set a reviewer chooses from, with Apertus' probability shares in review mode
    shares = None
    if mode == "review" and backend is not None and theta is not None and ad.get("residue"):
        p = pointer.answer_date(backend, pages, lang, theta, anchors=rules.anchors(pages))
        shares = output.pointer_shares(p)
    ad_field = fields.get("answer_date")
    if ad_field is not None:
        chosen = ad_field.get("value") or (suggestion or {}).get("value")
        ad_field["candidates"] = output.date_candidates(pages, chosen, shares)
        if heading:
            _promote_heading_candidate(ad_field["candidates"], heading, pages)
        if letter:
            _promote_candidate(ad_field["candidates"], letter, pages, dict(suggested_by_letter_line=True,
                                                                           address=letter["address"]))
        if shares is not None:
            ad_field["null_share"] = round(shares.get(None, 0.0), 4)
    if suggestion:
        suggestion["band"] = output.band_info(suggestion.get("margin"), suggestion.get("theta"))
        if getattr(backend, "mismatch", None):  # --allow-build-mismatch: the reviewer sees that θ is from another build
            suggestion["build_mismatch"] = backend.mismatch
    if "recommendation" in fields and fields["recommendation"] is not None:
        rp = output.recommendation_phrases(pages)
        fields["recommendation"]["recommendation_phrases"] = rp["labels"]
        fields["recommendation"]["multiple_recommendations"] = rp["multiple"]
    for name, why in flags.items():
        if fields.get(name) is not None:
            fields[name].update(needs_review=True, review_reason=why)
    reasons = [dict(field=n, reason=w) for n, w in flags.items()]
    if suggestion:
        reasons.append(dict(field="answer_date", reason="Apertus suggests a value for what the rules left open"))
    row = dict(status="ok", input=inp, mode=mode, language=lang, doc_role=role, fields=fields,
               needs_review=bool(suggestion) or bool(flags), review_reasons=reasons, review_suggestion=suggestion,
               rules_coverage=cov, record=rd)
    if explain:
        row["explain"] = dict(cache=overlay.cache_info(), rules_coverage=cov, **traces)
    return row


def _promote_heading_candidate(cands: list[dict], h: dict, pages: list[str]) -> None:
    """Move the date printed right after the answer heading to the front, with the heading's occurrence as its span."""
    _promote_candidate(cands, h, pages, dict(suggested_by_heading_proximity=True, heading=h["heading"]))


def _promote_candidate(cands: list[dict], h: dict, pages: list[str], mark: dict) -> None:
    """Move a hinted date to the front of the candidates, with the hinted occurrence as its span and the hint's mark."""
    ctx = output.anchor_context(pages, h["page"], h["char_start"], h["char_end"], before=100, limit=160)
    for i, c in enumerate(cands):
        if c["value"] == h["value"]:
            c = cands.pop(i)
            break
    else:
        c = dict(value=h["value"], occurrences=1)
    c.update(page=h["page"], char_start=h["char_start"], char_end=h["char_end"], context=ctx, **mark)
    cands.insert(0, c)


def convert_one(source: str, inp: dict | None = None, *, mode: str = "rules_only", backend=None, theta=None,
                timeout: int = 60, tries: int = 2, anchors: dict | None = None, explain: bool = False,
                queue_nulls: bool = False, anchors_review: bool = False) -> dict:
    inp = {k: v for k, v in dict(source=source, **(inp or {})).items() if v not in (None, "")}
    try:
        sha, path = get_document(source, timeout=timeout, tries=tries)
        t = pdftext.extract(sha, path)
    except subprocess.CalledProcessError as e:
        return output.failure_row("text_failed", f"pdftotext/tesseract failed: {e}", inp)
    except SystemExit:
        raise
    except Exception as e:  # every other way of not getting the document becomes a typed row
        kind, reason = output.classify(e)
        return output.failure_row(kind, reason, inp)
    url = source if re.match(r"https?://", source) else None
    return convert_pages(t["pages"], sha=sha, extractor=t["extractor"], image_only=t["image_only"], inp=inp, mode=mode,
                         backend=backend, theta=theta, url=url, anchors=anchors, explain=explain, queue_nulls=queue_nulls,
                         anchors_review=anchors_review)


# --------------------------------------------------------------------------------------------------- batch
def read_inputs(path: str) -> list[dict]:
    """Raises affair_types.UnknownAffairType (with the line number) for an affair_type outside the vocabulary."""
    from .affair_types import UnknownAffairType, normalize

    p = Path(path)
    rows = []
    if p.suffix.lower() in (".tsv", ".csv"):
        with open(p, newline="", encoding="utf-8") as f:
            for line_no, r in enumerate(csv.DictReader(f, delimiter="\t" if p.suffix.lower() == ".tsv" else ","), start=2):
                src = (r.get("url") or r.get("path") or r.get("source") or "").strip()
                if not src:
                    continue
                row = {k: (r.get(k) or "").strip() for k in INPUT_KEYS if k != "source"} | {"source": src}
                if not row["doc_category"]:  # OPD docs-export column names work too
                    row["doc_category"] = (r.get("category_harmonized") or r.get("category") or "").strip()
                try:
                    row["affair_type"] = normalize(row["affair_type"]) or ""
                except UnknownAffairType as e:
                    raise UnknownAffairType(f"{path}, line {line_no}: {e}") from None
                rows.append(row)
    else:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append({"source": line})
    return rows


def row_key(inp: dict) -> str:
    return f"opd:{inp['opd_doc_id']}" if inp.get("opd_doc_id") else inp["source"]


def anchors_sha256(anchors: dict | None) -> str | None:
    if not anchors:
        return None
    try:
        return hashlib.sha256(Path(anchors["file"]).read_bytes()).hexdigest()
    except (KeyError, OSError):  # anchors built in code (tests): hash their patterns instead
        return hashlib.sha256(json.dumps(anchors.get("bodies"), sort_keys=True, default=lambda x: getattr(x, "pattern",
                                                                                                           str(x))).encode()).hexdigest()


def options_of(inp: dict, *, mode: str, backend=None, theta=None, anchors: dict | None = None, explain: bool = False,
               queue_nulls: bool = False, anchors_review: bool = False) -> dict:
    """Everything besides the document that decides a row's content; `hash` is what resume compares."""
    review = mode == "review"
    o = dict(anchors_sha256=anchors_sha256(anchors), mode=mode, affair_type=inp.get("affair_type") or None,
             queue_nulls=bool(queue_nulls), anchors_review=bool(anchors_review), explain=bool(explain),
             review_build=getattr(backend, "build", None) if review else None, theta=theta if review else None,
             input={k: v for k, v in sorted(inp.items()) if v not in (None, "") and k != "source"})  # the key names the doc
    o["hash"] = hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return o


def run_batch(inputs: list[dict], out_path: str | None, *, mode: str = "rules_only", backend=None, theta=None,
              retry_failed: bool = False, timeout: int = 60, tries: int = 2, anchors: dict | None = None,
              explain: bool = False, queue_nulls: bool = False, anchors_review: bool = False) -> dict:
    """Append one JSONL row per input; skip inputs whose last row in out_path was made with the same options (failed ones
    too, unless retry_failed). An input whose options changed (anchors file, mode, affair type, ...) is converted again."""
    done = {}
    if out_path and Path(out_path).exists():
        for line in open(out_path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                done[row_key(r["input"])] = (r["status"], (r.get("options") or {}).get("hash"))
    opt = dict(mode=mode, backend=backend, theta=theta, anchors=anchors, explain=explain, queue_nulls=queue_nulls,
               anchors_review=anchors_review)
    counts: dict[str, int] = {}
    warned: set = set()
    sink = open(out_path, "a", encoding="utf-8") if out_path else sys.stdout
    try:
        for inp in inputs:
            k = row_key(inp)
            options = options_of({x: inp.get(x) for x in INPUT_KEYS}, **opt)
            if k in done:
                status, h = done[k]
                if h is None and (status == "ok" or not retry_failed):  # a row from before options were recorded
                    counts["skipped (older row, options not recorded)"] = \
                        counts.get("skipped (older row, options not recorded)", 0) + 1
                    continue
                if h is not None and h != options["hash"]:
                    counts["re-run (options changed)"] = counts.get("re-run (options changed)", 0) + 1
                elif status == "ok" or not retry_failed:
                    counts["skipped (already done)"] = counts.get("skipped (already done)", 0) + 1
                    continue
            row = convert_one(inp["source"], {x: inp.get(x) for x in INPUT_KEYS if x != "source"}, mode=mode,
                              backend=backend, theta=theta, timeout=timeout, tries=tries, anchors=anchors, explain=explain,
                              queue_nulls=queue_nulls, anchors_review=anchors_review)
            row["options"] = options
            cov = row.get("rules_coverage")
            if cov and cov.get("body") not in warned and overlay.coverage_warning(cov):
                warned.add(cov.get("body"))
                print(overlay.coverage_warning(cov), file=sys.stderr)
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            if row["status"] == "ok" and row["needs_review"]:
                counts["needs_review"] = counts.get("needs_review", 0) + 1
    finally:
        if out_path:
            sink.close()
    return counts


BAND_ORDER = {"strong": 0, "weak": 1}


def write_queue(rows_path: str, queue_path: str) -> int:
    """Review queue: every row that needs review (an Apertus suggestion, or a flag from the overlay: uncovered body,
    qualified recommendation, date next to a heading, ...), suggestions strongest first (band, then margin ascending), so
    a reviewer starts with the suggestions most likely to be right (results/convert/band_precision.json); flagged rows
    without a suggestion follow."""
    last: dict[str, dict] = {}  # a re-run (options changed) appends a newer row for the same input: the last one wins
    for x in open(rows_path, encoding="utf-8"):
        if x.strip():
            r = json.loads(x)
            last[row_key(r["input"])] = r
    q = [r for r in last.values() if r.get("status") == "ok" and r.get("needs_review")]

    def key(r):
        s = r.get("review_suggestion") or {}
        return (BAND_ORDER.get((s.get("band") or {}).get("band"), 9), s.get("margin") if s.get("margin") is not None else 0)
    q.sort(key=key)
    with open(queue_path, "w", encoding="utf-8") as f:
        for r in q:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(q)


def has_failures(counts: dict) -> bool:
    return any(k in output.FAILURE_KINDS and v for k, v in counts.items())
