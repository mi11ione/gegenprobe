"""Readers for the compact census tables in data/census/ (written by census/extract.py)."""

from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

from ..paths import DATA

CENSUS = DATA / "census"


def rows(name: str, root: Path = CENSUS):
    """Yield dicts from <root>/<name>.tsv.gz (tab-separated, no quoting: tabs/newlines were stripped at extract time)."""
    with gzip.open(root / f"{name}.tsv.gz", "rb") as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)


def i(x: str):
    return int(x) if x not in ("", None) else None
