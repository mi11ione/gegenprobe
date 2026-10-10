"""python -m gegenprobe.virtual derive --agenda <pdf|url> [--minutes <pdf|url>] --body 2125 [--name Bulle] [--lang fr]
                                    [--mode rules_only|review] [--backend ...] [--theta 0]
Prints {meeting, items, affairs} — every affair schema v0.1 (virtual=true, derived_from=<agenda doc>), values with spans."""
from __future__ import annotations

import argparse
import json
import sys

import re
import shutil
from pathlib import Path

from .. import pdftext
from ..paths import PDF_CACHE
from . import derive


def load(src: str):
    """URL -> polite fetch (sha256-cached); local path -> copied into the cache by sha256."""
    if re.match(r"https?://", src):
        return pdftext.fetch_pdf(src)
    b = Path(src).read_bytes()
    sha = pdftext.sha256_bytes(b)
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    dest = PDF_CACHE / f"{sha}.pdf"
    if not dest.exists():
        shutil.copyfile(src, dest)
    return sha, dest


def _doc(src: str, opd_id: str | None) -> tuple[dict, list[str]]:
    sha, path = load(src)
    t = pdftext.extract(sha, path)
    did = f"opd:{opd_id}" if opd_id else f"sha256:{sha[:16]}"
    return dict(doc_id=did, url=src if src.startswith("http") else None, sha256=sha, extractor=t["extractor"]), t["pages"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gegenprobe.virtual")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("derive")
    d.add_argument("--agenda", required=True)
    d.add_argument("--agenda-opd-id")
    d.add_argument("--minutes")
    d.add_argument("--minutes-opd-id")
    d.add_argument("--body", required=True)
    d.add_argument("--name")
    d.add_argument("--lang", default="fr", choices=["fr", "de"])
    d.add_argument("--mode", default="rules_only", choices=["rules_only", "review"])
    d.add_argument("--backend", default="gguf")
    d.add_argument("--theta", type=float, default=0.0)
    a = ap.parse_args(argv)
    adoc, apages = _doc(a.agenda, a.agenda_opd_id)
    mdoc, mpages = _doc(a.minutes, a.minutes_opd_id) if a.minutes else (None, None)
    be = None
    if a.mode == "review":
        from eval.arms import backend
        be = backend(a.backend)
    out = derive.derive(dict(key=a.body, name=a.name, languages=[a.lang]), adoc, apages, mdoc, mpages, a.mode, be, a.theta,
                        a.lang)
    out["affairs"] = [json.loads(x.model_dump_json(exclude_none=True)) for x in out["affairs"]]
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1, default=str)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
