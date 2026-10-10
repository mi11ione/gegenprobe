"""Command line.

  python -m gegenprobe convert <pdf path or URL> [--mode rules_only|review] [--lang de|fr|it] [--affair-type Motion]
                               [--backend openai|gguf|gateway:<model>:<tag>:<cap>]
      Convert one parliamentary PDF. Prints a schema-valid extraction (schema v0.1, DocExtraction) in which every value
      carries page + character span + route, or a typed null; in `review` mode the Apertus closed-set pointer adds a
      suggestion for the rules' residue, flagged needs_review (it is never written into the field).
  python -m gegenprobe run       the `make run` replay (same as python -m gegenprobe.run)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

STOP = {
    "de": r"\b(der|die|das|und|nicht|Regierungsrat|wird|werden|vom)\b",
    "fr": r"\b(le|la|les|et|des|du|Conseil|est|pour)\b",
    "it": r"\b(il|la|che|e|del|della|Consiglio|per|sono)\b",
}


def guess_lang(text: str) -> str:
    counts = {lg: len(re.findall(rx, text[:20000])) for lg, rx in STOP.items()}
    return max(counts, key=counts.get)


def load(src: str) -> tuple[str, Path]:
    from . import pdftext
    from .paths import PDF_CACHE
    if re.match(r"https?://", src):
        return pdftext.fetch_pdf(src)
    p = Path(src)
    b = p.read_bytes()
    if b"%PDF" not in b[:1024]:
        raise SystemExit(f"{src}: not a PDF")
    sha = pdftext.sha256_bytes(b)
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    dest = PDF_CACHE / f"{sha}.pdf"
    if not dest.exists():
        shutil.copyfile(p, dest)
    return sha, dest


def convert(a) -> int:
    from . import pdftext
    from .convert import cascade, modes
    from .schema import schema_v0_1 as schema

    sha, path = load(a.source)
    t = pdftext.extract(sha, path)
    lang = a.lang or guess_lang("\n".join(t["pages"]))
    doc = dict(pages=t["pages"], lang=lang, image_only=t["image_only"], extractor=t["extractor"], affair_type=a.affair_type,
               doc_id=f"sha256:{sha[:16]}", sha256=sha)
    rec = cascade.convert(doc)  # backend-free: metadata/rules, typed nulls for the residue
    be, theta = None, None
    if a.mode == "review":
        from eval.arms import backend, theta_path
        be = backend(a.backend)
        tp = theta_path(be.build)
        if not tp.exists():
            raise SystemExit(f"review mode needs θ fitted for {be.build} (data/convert/theta/); none found")
        theta = json.loads(tp.read_text())["answer_date"]["theta"]
    ad = modes.answer_date(doc, a.mode, be, theta, use_metadata=False)
    suggestion = ad.pop("suggestion", None)
    rec["fields"]["answer_date"] = {k: v for k, v in ad.items() if k not in ("mode", "needs_review")}
    ext = schema.from_converter(rec, t["pages"], dict(source="other", url=a.source if a.source.startswith("http") else None,
                                                      language=lang, n_pages=len(t["pages"]), image_only=t["image_only"]))
    out = dict(mode=a.mode, language=lang, extraction=json.loads(ext.model_dump_json(exclude_none=True)),
               needs_review=bool(suggestion), review_suggestion=suggestion)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gegenprobe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert one PDF (path or URL) into schema v0.1 with provenance")
    c.add_argument("source")
    c.add_argument("--mode", choices=["rules_only", "review"], default="rules_only")
    c.add_argument("--lang", choices=["de", "fr", "it"])
    c.add_argument("--affair-type", default=None)
    c.add_argument("--backend", default="openai", help="review mode: openai (LLM_* env) | gguf | gateway:<model>:<tag>:<cap>")
    sub.add_parser("run", help="the make-run replay")
    a = ap.parse_args(argv)
    if a.cmd == "convert":
        return convert(a)
    from .run import main as run_main
    return run_main()


if __name__ == "__main__":
    sys.exit(main())
