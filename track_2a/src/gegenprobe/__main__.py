"""Command line.

  python -m gegenprobe convert <pdf path or URL> [options]
  python -m gegenprobe convert --batch inputs.tsv [--out results.jsonl] [options]
      Convert parliamentary PDFs. Each document gives one row: the answer date and the government's recommendation
      with page + character span + the rule that decided, or a typed null; the full schema v0.1 record under `record`.
      In `review` mode the Apertus closed-set pointer adds a suggestion for what the rules left open, flagged
      needs_review; it is never written into the field. A document that cannot be fetched or read becomes a typed
      failure row (robots_disallowed, robots_unreachable, http_error, timeout, network_error, not_a_pdf, sha_mismatch,
      file_not_found, text_failed, too_large, text_timeout, ocr_failed). Exit codes: 0 all ok; 2 a failure row (single
      file) or any failure row in a batch (unless --allow-failures), or a malformed --anchors file; 3 review mode refused
      because the served model or fingerprint is not the build θ was fitted on (--allow-build-mismatch overrides, marking
      suggestions). A --body outside data/convert/rules_coverage.json prints a warning and marks the row needs_review.
      --anchors FILE adds your own per-body regex anchors after the frozen rules (--anchors-review keeps their values
      flagged); --explain lists every rule/anchor tried and the cache path.
      With --opd-doc-id (and --body) every value also gets opd_text_span, offsets into OPD's stored text, when that text
      exists (convert/opd_store.py; --no-opd-text or GP_OPD_TEXT=off skips the lookup; --opd-text FILE names it).
      --affair-type accepts the vocabulary keys, their DE/FR/IT/EN labels and OPD's harmonised names (an unknown value
      is an error, exit 2); --queue-nulls sends a rules-only null answer date on an answer document (doc_role answer, or
      --doc-category / batch column doc_category says answer) to review with its candidates.
      Docs: docs/convert-your-own.md.
  python -m gegenprobe convert <pdf path or URL> --schema v0.2 --body KEY [--level L] [--doc-role question|answer]
                               [--affair-number N] [--affair-type T] [--out FILE]
      One bare PDF (no OPD affair id) -> one validated schema v0.2 record (rules_only): the rules' values with page,
      span and rule; every field only OPD's metadata supplies is a typed null not_in_corpus (convert/v02_pdf.py).
  python -m gegenprobe affair --opd-affair <id> [--schema v0.2] [--mode rules_only|review] [--roles rules|apertus]
                             [--out FILE]
      One OPD affair -> one validated schema v0.2 record: OPD's export rows (affair, events, contributors, document rows)
      plus the affair's question and answer documents, through the converter's record pipeline (affair.build,
      affair_post, schema.v0_2_all); typed nulls, needs_review as affair_post. A typed failure exits 2. --roles apertus
      (opt-in) adds the frozen P10 role reader's roles under suggestions.actors, each review: true; never applied;
      --roles-fallback opd (off by default) offers OPD's contributor list where the reader suggests no author.
      Docs: docs/affair.md (gegenprobe/affair_cli.py).
  python -m gegenprobe run       the `make run` replay (same as python -m gegenprobe.run)
"""
from __future__ import annotations

import argparse
import json
import sys

from . import gguf_guard, ocrguard
from .convert import affair_types
from .convert.batch import guess_lang  # noqa: F401  (re-exported: tests and older callers import it from here)


def _convert(a) -> int:
    from .convert import batch, body_settings, overlay

    anchors = None
    if a.anchors:
        try:
            anchors = body_settings.load(a.anchors)
        except overlay.AnchorError as e:
            print(str(e), file=sys.stderr)
            return 2
    if a.verbose or (a.explain and a.batch):  # single-document --explain prints it in its own block
        c = overlay.cache_info()
        print(f"cache: {c['work']} ({c['note']})", file=sys.stderr)
    be, theta = (None, None)
    if a.mode == "review":
        be, theta = batch.resolve_review(a.backend, a.theta, allow_build_mismatch=a.allow_build_mismatch)
    opd_policy = "off" if a.no_opd_text else None  # None: GP_OPD_TEXT, default auto (convert/opd_store.py)
    if a.batch:
        from .convert import opd_store
        from .convert.affair_types import UnknownAffairType
        try:
            inputs = batch.read_inputs(a.batch, anchors)
        except UnknownAffairType as e:
            print(str(e), file=sys.stderr)
            return 2
        opd_store.prefetch(inputs, opd_policy)
        one = batch.convert_one  # rows get opd_text_span where OPD's stored text exists
        batch.convert_one = lambda *x, **k: opd_store.annotate(one(*x, **k), opd_policy)
        try:
            counts = batch.run_batch(inputs, a.out, mode=a.mode, backend=be, theta=theta, retry_failed=a.retry_failed,
                                     timeout=a.timeout, tries=a.tries, anchors=anchors, explain=a.explain,
                                     queue_nulls=a.queue_nulls, anchors_review=a.anchors_review)
        finally:
            batch.convert_one = one
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        print(f"{len(inputs)} inputs: {summary or 'nothing to do'}" + (f" -> {a.out}" if a.out else ""), file=sys.stderr)
        if a.queue:
            if not a.out:
                print("--queue needs --out (the queue is built from the rows file)", file=sys.stderr)
                return 2
            n = batch.write_queue(a.out, a.queue)
            print(f"review queue: {n} rows needing review, Apertus suggestions strongest first -> {a.queue}", file=sys.stderr)
        elif a.queue_nulls:
            print("note: --queue-nulls flags rows needs_review; add --queue FILE to write them to a review queue",
                  file=sys.stderr)
        if batch.has_failures(counts) and not a.allow_failures:
            print("some inputs failed (typed failure rows written); exit 2. Use --allow-failures to exit 0.", file=sys.stderr)
            return 2
        return 0
    if not a.source:
        print("give a PDF path or URL, or --batch FILE", file=sys.stderr)
        return 2
    inp = dict(opd_doc_id=a.opd_doc_id, body=a.body, affair_number=a.affair_number, affair_type=a.affair_type, lang=a.lang,
               doc_category=a.doc_category)
    row = batch.convert_one(a.source, inp, mode=a.mode, backend=be, theta=theta, timeout=a.timeout, tries=a.tries,
                            anchors=anchors, explain=a.explain, queue_nulls=a.queue_nulls, anchors_review=a.anchors_review)
    if row["status"] == "ok" and overlay.coverage_warning(row["rules_coverage"]):
        print(overlay.coverage_warning(row["rules_coverage"]), file=sys.stderr)
    elif row["status"] == "ok" and not a.body:
        print("note: no --body given, so rule coverage (data/convert/rules_coverage.json) was not checked", file=sys.stderr)
    if a.opd_text and row["status"] == "ok":
        from .convert import opdtext
        row["opd_text_alignment"] = opdtext.annotate(row, opdtext.load(a.opd_text))
        row["opd_text_source"] = dict(source=f"--opd-text {a.opd_text}")
    elif row["status"] == "ok":  # OPD's stored text by --opd-doc-id (+ --body), without a flag (convert/opd_store.py)
        from .convert import opd_store
        opd_store.annotate(row, opd_policy)
    json.dump(row, sys.stdout, ensure_ascii=False, indent=1)
    print()
    if a.explain and row["status"] == "ok":
        print(overlay.render_explain(row["explain"]), file=sys.stderr)
    if row["status"] == "ok" and row["needs_review"]:
        for r in row["review_reasons"]:
            print(f"needs review ({r['field']}): {r['reason']}", file=sys.stderr)
    if row["status"] != "ok":
        print(f"{row['status']}: {row['reason']}", file=sys.stderr)
        return 2
    return 0



def _served_refusal(e: Exception) -> str:
    """Exit 3 message when the server answers under another model label than the one requested (the label check runs
    before the fingerprint guard, so a host that swaps the build and its label behind an unchanged name lands here)."""
    return (f"review mode: {e}. The served build is not the one θ (or the role reader's configuration) was fitted on; "
            "θ does not transfer across builds. Refit θ for this build (docs/runbook.md, \"Review mode in operation\").")

def main(argv: list[str] | None = None) -> int:
    ocrguard.ensure()  # OCR fails loudly (typed ocr_failed row), also in an installed checkout without sitecustomize
    gguf_guard.ensure()  # local 8B: weights re-hashed at load, sandboxed chat template, GP_USER_AGENT (gguf_guard.py)
    ap = argparse.ArgumentParser(prog="gegenprobe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert PDFs (path or URL, or a batch file) into rows with provenance",
                       description="Convert parliamentary PDFs. See docs/convert-your-own.md.")
    c.add_argument("source", nargs="?", help="PDF path or URL (omit with --batch)")
    c.add_argument("--batch", metavar="FILE", help=".tsv/.csv with a url|path|source column (optional opd_doc_id, body, "
                   "affair_number, affair_type, lang, doc_category) or .txt with one URL/path per line")
    c.add_argument("--out", metavar="JSONL", help="batch: append rows here; inputs already in the file are skipped")
    c.add_argument("--retry-failed", action="store_true", help="batch: retry inputs whose earlier row is a failure")
    c.add_argument("--allow-failures", action="store_true",
                   help="batch: exit 0 even if some inputs became failure rows (default: exit 2 so CI can gate on it)")
    c.add_argument("--queue", metavar="JSONL", help="batch: also write the rows with review suggestions, strongest band first")
    c.add_argument("--queue-nulls", action="store_true",
                   help="flag a rules-only null answer date on an answer document (doc_role answer, or --doc-category / "
                   "batch column doc_category says answer, e.g. OPD category_harmonized response_text) needs_review, so "
                   "it goes to the review queue with its candidates")
    c.add_argument("--doc-category", help="OPD document category of this document (category_harmonized, e.g. "
                   "response_text, or the category label, e.g. Réponse); used by --queue-nulls")
    c.add_argument("--opd-text", metavar="FILE", help="OPD's stored text of this document (plain text, or a docs-export "
                   "JSON row with a 'text' field): every value also gets opd_text_span, offsets into that text. Without "
                   "it, OPD's stored text is looked up by --opd-doc-id (+ --body) in the work cache, the docs-export "
                   "snapshots and OPD's docs export (GP_OPD_TEXT=auto|local|off; convert/opd_store.py)")
    c.add_argument("--no-opd-text", action="store_true", help="do not look up OPD's stored text (no opd_text_span unless "
                   "--opd-text is given)")
    c.add_argument("--mode", choices=["rules_only", "review"], default="rules_only",
                   help="rules_only (default, no model) | review (adds Apertus suggestions, needs a fitted θ)")
    c.add_argument("--lang", choices=["de", "fr", "it"], help="document language (guessed if omitted)")
    c.add_argument("--affair-type", metavar="TYPE",
                   help="affair type: a vocabulary key (" + ", ".join(affair_types.KEYS) + "), one of their DE/FR/IT/EN "
                   "labels, or OPD's harmonised name (Interpellation, Question, Question time, ...); case-insensitive. "
                   "Interpellation / Question / Question time make the recommendation not_applicable. OPD type names "
                   "such as Auftrag are accepted (data/convert/affair_type_aliases.json), and a settings file's "
                   "affair_types for --body. Unknown: error")
    c.add_argument("--opd-doc-id", help="OPD document id: the record's doc_id becomes opd:<id>")
    c.add_argument("--body", help="OPD body key, e.g. BE, ZH, 261 (passed through)")
    c.add_argument("--affair-number", help="affair number as printed, e.g. 2024.RRGR.91 (passed through)")
    c.add_argument("--backend", default="gguf",
                   help="review mode: gguf (local Apertus 8B, CPU; default) | openai (LLM_BASE_URL/LLM_NAME/LLM_API_KEY) | "
                   "gateway:<model>:<tag>:<cap>")
    c.add_argument("--theta", type=float, help="review mode: override θ (not recommended: θ does not transfer across builds)")
    c.add_argument("--allow-build-mismatch", action="store_true",
                   help="review mode: attach suggestions even when the served model/fingerprint is not the build θ was "
                   "fitted on (default: stop with exit 3); each suggestion is then marked build_mismatch")
    c.add_argument("--anchors", metavar="JSON", help="your own per-body regex anchors for the answer date and recommendation "
                   "phrases, tried only after the frozen rules return null (route user_anchor); docs/examples/anchors_SG.json. "
                   "The same file may list confirm_rules (frozen rule ids checked on that body: not flagged for coverage) "
                   "and affair_types aliases; qa_cli reads it too")
    c.add_argument("--anchors-review", action="store_true", help="values from your --anchors keep needs_review true "
                   "(for anchors you have not measured yet; default: a user-anchor value is not flagged, route user_anchor)")
    c.add_argument("--explain", action="store_true", help="list every rule and anchor tried per field and why it did not "
                   "decide, plus the cache path (stderr; batch rows get an 'explain' key)")
    c.add_argument("-v", "--verbose", action="store_true", help="print the cache path (GP_WORK, default the repo's .work/)")
    c.add_argument("--timeout", type=int, default=60, help="seconds per HTTP request (default 60)")
    c.add_argument("--tries", type=int, default=2, help="HTTP attempts per document (default 2)")
    c.add_argument("--schema", choices=["v0.1", "v0.2"], default="v0.1",
                   help="v0.1 (default): the document row with its v0.1 record; v0.2: one validated schema v0.2 affair "
                   "record from this PDF alone, without an OPD affair id (fields only OPD's metadata supplies are typed "
                   "not_in_corpus; needs --body, and --level for a parliament outside OPD's bodies table; "
                   "convert/v02_pdf.py)")
    c.add_argument("--level", choices=["cantonal", "communal", "federal"],
                   help="--schema v0.2: the parliament's level when --body is not an OPD body key")
    c.add_argument("--doc-role", choices=["question", "answer"],
                   help="--schema v0.2: the member's text or the answer (default: the converter's own doc_role)")
    from . import affair_cli
    from .llm import ServedModelMismatch
    affair_cli.add_parser(sub)
    sub.add_parser("run", help="the make-run replay")
    a = ap.parse_args(argv)
    if a.cmd == "affair":
        from .convert.build_guard import BuildMismatch
        try:
            return affair_cli.main_args(a)
        except BuildMismatch as e:  # review mode: the served model is not the build θ was fitted on
            print(str(e), file=sys.stderr)
            return 3
        except ServedModelMismatch as e:  # the server answered under another model label (llm._Remote._check)
            print(_served_refusal(e), file=sys.stderr)
            return 3
    if a.cmd == "convert":
        from .convert import body_settings, overlay
        from .convert.build_guard import BuildMismatch
        aliases = {}
        if a.anchors:  # the settings file's per-body affair_types apply to --affair-type (a malformed file: _convert)
            try:
                aliases = body_settings.type_aliases(body_settings.load(a.anchors), a.body)
            except overlay.AnchorError:
                pass
        try:
            a.affair_type = affair_types.normalize(a.affair_type, aliases)
        except affair_types.UnknownAffairType as e:
            c.error(f"argument --affair-type: {e}")
        if a.schema == "v0.2":
            from .convert import v02_pdf
            return v02_pdf.main_args(a)
        try:
            return _convert(a)
        except BuildMismatch as e:  # review mode: the served model is not the build θ was fitted on
            print(str(e), file=sys.stderr)
            return 3
        except ServedModelMismatch as e:  # the server answered under another model label (llm._Remote._check)
            print(_served_refusal(e), file=sys.stderr)
            return 3
    from .run import main as run_main
    return run_main()


if __name__ == "__main__":
    sys.exit(main())
