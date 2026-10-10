"""Command line.

  python -m gegenprobe convert <pdf path or URL> [options]
  python -m gegenprobe convert --batch inputs.tsv [--out results.jsonl] [options]
      Convert parliamentary PDFs. Each document gives one row: the answer date and the government's recommendation
      with page + character span + the rule that decided, or a typed null; the full schema v0.1 record under `record`.
      In `review` mode the Apertus closed-set pointer adds a suggestion for what the rules left open, flagged
      needs_review; it is never written into the field. A document that cannot be fetched or read becomes a typed
      failure row (robots_disallowed, http_error, timeout, network_error, not_a_pdf, sha_mismatch, file_not_found,
      text_failed). Exit codes: 0 all ok; 2 a failure row (single file) or any failure row in a batch (unless
      --allow-failures). Docs: docs/convert-your-own.md.
  python -m gegenprobe run       the `make run` replay (same as python -m gegenprobe.run)
"""
from __future__ import annotations

import argparse
import json
import sys

from .convert.batch import guess_lang  # noqa: F401  (re-exported: tests and older callers import it from here)


def _convert(a) -> int:
    from .convert import batch

    be, theta = (None, None)
    if a.mode == "review":
        be, theta = batch.resolve_review(a.backend, a.theta)
    if a.batch:
        inputs = batch.read_inputs(a.batch)
        counts = batch.run_batch(inputs, a.out, mode=a.mode, backend=be, theta=theta, retry_failed=a.retry_failed,
                                 timeout=a.timeout, tries=a.tries)
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        print(f"{len(inputs)} inputs: {summary or 'nothing to do'}" + (f" -> {a.out}" if a.out else ""), file=sys.stderr)
        if a.queue:
            if not a.out:
                print("--queue needs --out (the queue is built from the rows file)", file=sys.stderr)
                return 2
            n = batch.write_queue(a.out, a.queue)
            print(f"review queue: {n} suggestions, strongest first -> {a.queue}", file=sys.stderr)
        if batch.has_failures(counts) and not a.allow_failures:
            print("some inputs failed (typed failure rows written); exit 2. Use --allow-failures to exit 0.", file=sys.stderr)
            return 2
        return 0
    if not a.source:
        print("give a PDF path or URL, or --batch FILE", file=sys.stderr)
        return 2
    inp = dict(opd_doc_id=a.opd_doc_id, body=a.body, affair_number=a.affair_number, affair_type=a.affair_type, lang=a.lang)
    row = batch.convert_one(a.source, inp, mode=a.mode, backend=be, theta=theta, timeout=a.timeout, tries=a.tries)
    if a.opd_text and row["status"] == "ok":
        from .convert import opdtext
        row["opd_text_alignment"] = opdtext.annotate(row, opdtext.load(a.opd_text))
    json.dump(row, sys.stdout, ensure_ascii=False, indent=1)
    print()
    if row["status"] != "ok":
        print(f"{row['status']}: {row['reason']}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gegenprobe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert PDFs (path or URL, or a batch file) into rows with provenance",
                       description="Convert parliamentary PDFs. See docs/convert-your-own.md.")
    c.add_argument("source", nargs="?", help="PDF path or URL (omit with --batch)")
    c.add_argument("--batch", metavar="FILE", help=".tsv/.csv with a url|path|source column (optional opd_doc_id, body, "
                   "affair_number, affair_type, lang) or .txt with one URL/path per line")
    c.add_argument("--out", metavar="JSONL", help="batch: append rows here; inputs already in the file are skipped")
    c.add_argument("--retry-failed", action="store_true", help="batch: retry inputs whose earlier row is a failure")
    c.add_argument("--allow-failures", action="store_true",
                   help="batch: exit 0 even if some inputs became failure rows (default: exit 2 so CI can gate on it)")
    c.add_argument("--queue", metavar="JSONL", help="batch: also write the rows with review suggestions, strongest band first")
    c.add_argument("--opd-text", metavar="FILE", help="OPD's stored text of this document (plain text, or a docs-export "
                   "JSON row with a 'text' field): every value also gets opd_text_span, offsets into that text")
    c.add_argument("--mode", choices=["rules_only", "review"], default="rules_only",
                   help="rules_only (default, no model) | review (adds Apertus suggestions, needs a fitted θ)")
    c.add_argument("--lang", choices=["de", "fr", "it"], help="document language (guessed if omitted)")
    c.add_argument("--affair-type", help="OPD harmonised type, e.g. Motion, Interpellation (recommendation n/a for some)")
    c.add_argument("--opd-doc-id", help="OPD document id: the record's doc_id becomes opd:<id>")
    c.add_argument("--body", help="OPD body key, e.g. BE, ZH, 261 (passed through)")
    c.add_argument("--affair-number", help="affair number as printed, e.g. 2024.RRGR.91 (passed through)")
    c.add_argument("--backend", default="gguf",
                   help="review mode: gguf (local Apertus 8B, CPU; default) | openai (LLM_BASE_URL/LLM_NAME/LLM_API_KEY) | "
                   "gateway:<model>:<tag>:<cap>")
    c.add_argument("--theta", type=float, help="review mode: override θ (not recommended: θ does not transfer across builds)")
    c.add_argument("--timeout", type=int, default=60, help="seconds per HTTP request (default 60)")
    c.add_argument("--tries", type=int, default=2, help="HTTP attempts per document (default 2)")
    sub.add_parser("run", help="the make-run replay")
    a = ap.parse_args(argv)
    if a.cmd == "convert":
        return _convert(a)
    from .run import main as run_main
    return run_main()


if __name__ == "__main__":
    sys.exit(main())
