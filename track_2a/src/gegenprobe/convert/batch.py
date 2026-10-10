"""Convert one document or a batch of documents into reviewer-ready rows (see convert/output.py for the row format).

  convert_pages(...)   the conversion proper, on page texts already extracted (used by the CLI and by tests)
  convert_one(...)     get the document (URL or path), extract text, convert; any failure becomes a typed row
  run_batch(...)       many inputs from a .tsv/.csv (header with url|path|source, optional opd_doc_id, body,
                       affair_number, affair_type, lang) or a .txt (one URL or path per line); JSONL out, resumable
  resolve_review(...)  the backend and the per-build θ for review mode, with a clear message when none is fitted

The frozen converter (cascade, rules, pointer) is used unchanged; this module only wraps it.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

from .. import pdftext
from ..paths import PDF_CACHE
from . import cascade, modes, output

INPUT_KEYS = ("source", "opd_doc_id", "body", "affair_number", "affair_type", "lang")
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


def resolve_review(spec: str, theta_override: float | None = None):
    """-> (backend, θ). θ is per build (it does not transfer across builds, quantisations or prompts)."""
    from eval.arms import theta_path
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
    return be, json.loads(tp.read_text())["answer_date"]["theta"]


# --------------------------------------------------------------------------------------------------- conversion
def convert_pages(pages: list[str], *, sha: str, extractor: str, image_only: bool, inp: dict, mode: str = "rules_only",
                  backend=None, theta: float | None = None, url: str | None = None) -> dict:
    from ..schema import schema_v0_1 as schema

    lang = inp.get("lang") or guess_lang("\n".join(pages))
    doc_id = f"opd:{inp['opd_doc_id']}" if inp.get("opd_doc_id") else f"sha256:{sha[:16]}"
    doc = dict(pages=pages, lang=lang, image_only=image_only, extractor=extractor, affair_type=inp.get("affair_type"),
               doc_id=doc_id, sha256=sha)
    rec = cascade.convert(doc)  # backend-free: rules, typed nulls for the residue
    ad = modes.answer_date(doc, mode, backend, theta, use_metadata=False)
    suggestion = ad.pop("suggestion", None)
    rec["fields"]["answer_date"] = {k: v for k, v in ad.items() if k not in ("mode", "needs_review")}
    role = output.doc_role(pages, rec["fields"]["answer_date"])
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
    fields = {name: output.flat_field(rec["fields"].get(name), rd.get(name), pages)
              for name in ("answer_date", "recommendation", "related_affair") if rec["fields"].get(name) is not None}
    return dict(status="ok", input=inp, mode=mode, language=lang, doc_role=role, fields=fields,
                needs_review=bool(suggestion), review_suggestion=suggestion, record=rd)


def convert_one(source: str, inp: dict | None = None, *, mode: str = "rules_only", backend=None, theta=None,
                timeout: int = 60, tries: int = 2) -> dict:
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
                         backend=backend, theta=theta, url=url)


# --------------------------------------------------------------------------------------------------- batch
def read_inputs(path: str) -> list[dict]:
    p = Path(path)
    rows = []
    if p.suffix.lower() in (".tsv", ".csv"):
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t" if p.suffix.lower() == ".tsv" else ","):
                src = (r.get("url") or r.get("path") or r.get("source") or "").strip()
                if not src:
                    continue
                rows.append({k: (r.get(k) or "").strip() for k in INPUT_KEYS if k != "source"} | {"source": src})
    else:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append({"source": line})
    return rows


def row_key(inp: dict) -> str:
    return f"opd:{inp['opd_doc_id']}" if inp.get("opd_doc_id") else inp["source"]


def run_batch(inputs: list[dict], out_path: str | None, *, mode: str = "rules_only", backend=None, theta=None,
              retry_failed: bool = False, timeout: int = 60, tries: int = 2) -> dict:
    """Append one JSONL row per input; skip inputs already in out_path (failed ones too, unless retry_failed)."""
    done = {}
    if out_path and Path(out_path).exists():
        for line in open(out_path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                done[row_key(r["input"])] = r["status"]
    counts: dict[str, int] = {}
    sink = open(out_path, "a", encoding="utf-8") if out_path else sys.stdout
    try:
        for inp in inputs:
            k = row_key(inp)
            if k in done and (done[k] == "ok" or not retry_failed):
                counts["skipped (already done)"] = counts.get("skipped (already done)", 0) + 1
                continue
            row = convert_one(inp["source"], {x: inp.get(x) for x in INPUT_KEYS if x != "source"}, mode=mode,
                              backend=backend, theta=theta, timeout=timeout, tries=tries)
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            if row["status"] == "ok" and row["needs_review"]:
                counts["needs_review"] = counts.get("needs_review", 0) + 1
    finally:
        if out_path:
            sink.close()
    return counts
