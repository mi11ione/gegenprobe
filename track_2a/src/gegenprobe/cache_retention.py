"""Retention of the document caches: cached PDFs and extracted texts expire after GP_CACHE_MAX_AGE_DAYS.

    python -m gegenprobe.cache_retention [--dry-run] [--max-age-days N]     (make cache-clean)

What expires: GP_WORK/pdf/<sha256>.pdf (the downloaded documents) and GP_WORK/text/<sha256>.<extractor>.json (their
extracted text, pdftotext or OCR), when the file's modification time (when it was written) is more than N days ago.
N = GP_CACHE_MAX_AGE_DAYS, default 30; 0 disables expiry. A document needed again later is fetched and extracted again.
Nothing else is touched: only regular files with those names directly in those two directories (no symlink is followed),
never the OPD exports and scan metadata, the nightly state and ledger, the GGUF weights (GP_WORK/models), the OCR models,
or anything under the checkout's data/ and results/ (the committed model cache data/model_cache included); a cache
directory that resolves inside data/ or results/ is refused.

Enforced: every network night of the nightly job (monitor/nightly.py `run`, both systemd units) before its first
request, reported in run.json `cache_retention`; by hand or from cron with `make cache-clean`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from . import paths

DEFAULT_DAYS = 30
ENV = "GP_CACHE_MAX_AGE_DAYS"
PDF_NAME = re.compile(r"[0-9a-f]{64}\.pdf")
TEXT_NAME = re.compile(r"[0-9a-f]{64}\..+\.json")


def max_age_days(value: str | None = None) -> int:
    """GP_CACHE_MAX_AGE_DAYS as a whole number of days >= 0 (0 = never expire). Raises ValueError on anything else."""
    v = os.environ.get(ENV) if value is None else value
    if v is None or str(v).strip() == "":
        return DEFAULT_DAYS
    try:
        n = int(str(v).strip())
    except ValueError:
        raise ValueError(f"{ENV}={v!r}: expected a whole number of days (0 disables expiry)") from None
    if n < 0:
        raise ValueError(f"{ENV}={v!r}: expected a whole number of days >= 0 (0 disables expiry)")
    return n


def cache_dirs() -> list[tuple[Path, re.Pattern]]:
    return [(paths.PDF_CACHE, PDF_NAME), (paths.TEXT_CACHE, TEXT_NAME)]


def _protected(d: Path) -> bool:
    r = d.resolve()
    return any(r == p or p in r.parents for p in (paths.DATA.resolve(), paths.RESULTS.resolve()))


def enforce(days: int | None = None, dry_run: bool = False, now: float | None = None,
            dirs: list[tuple[Path, re.Pattern]] | None = None) -> dict:
    """Delete (or with dry_run list) the expired cache files. -> {"max_age_days", "disabled", "dry_run", "dirs",
    "deleted", "bytes", "kept", "errors"}"""
    days = max_age_days() if days is None else days
    if days < 0:
        raise ValueError(f"{ENV}: expected >= 0, got {days}")
    dirs = cache_dirs() if dirs is None else dirs
    r = dict(max_age_days=days, disabled=days == 0, dry_run=dry_run, dirs=[str(d) for d, _ in dirs], deleted=0, bytes=0,
             kept=0, errors=[])
    if days == 0:
        return r
    for d, _ in dirs:
        if _protected(d):
            raise ValueError(f"refusing to expire files in {d}: it is inside the checkout's data/ or results/")
    cutoff = (time.time() if now is None else now) - days * 86400
    for d, name in dirs:
        if not d.is_dir():
            continue
        with os.scandir(d) as it:
            for e in it:
                if not name.fullmatch(e.name) or not e.is_file(follow_symlinks=False):
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                    if st.st_mtime >= cutoff:
                        r["kept"] += 1
                        continue
                    if not dry_run:
                        os.unlink(e.path)
                    r["deleted"] += 1
                    r["bytes"] += st.st_size
                except OSError as ex:
                    r["errors"].append(f"{e.path}: {type(ex).__name__}: {ex}"[:300])
    return r


def summary(r: dict) -> str:
    if r["disabled"]:
        return f"cache retention: disabled ({ENV}=0); nothing expires"
    verb = "would delete" if r["dry_run"] else "deleted"
    return (f"cache retention ({r['max_age_days']} days, {', '.join(r['dirs'])}): {verb} {r['deleted']} files "
            f"({r['bytes'] / 1e6:.1f} MB), kept {r['kept']}" + (f", {len(r['errors'])} errors" if r["errors"] else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gegenprobe.cache_retention", description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="list what would be deleted, delete nothing")
    ap.add_argument("--max-age-days", type=int, help=f"override {ENV} (default {DEFAULT_DAYS}; 0 disables expiry)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    a = ap.parse_args(argv)
    try:
        r = enforce(days=a.max_age_days if a.max_age_days is not None else max_age_days(), dry_run=a.dry_run)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1) if a.json else summary(r))
    for err in r["errors"]:
        print(err, file=sys.stderr)
    return 1 if r["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
