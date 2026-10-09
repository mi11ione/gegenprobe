"""claims.tsv: every number in README / report / form notes maps to a results file, a JSON path and the command that produced it.

Fragments live in claims.d/<area>.tsv (one per workstream); `python -m gegenprobe.claims merge` concatenates them into
claims.tsv, `check` fails (exit 1) when
  * the value recomputed from the results file, rendered with `fmt`, differs from the `shown` column, or
  * a document listed in `where` does not contain the `shown` string.

Columns (tab-separated, header required):
  id       unique claim id (area.slug)
  shown    the string exactly as printed in the documents, e.g. 16,749 | 18.4% | 40/40 | [91.2, 100]
  file     results file relative to track_2a/ (.json, or .csv with path "row:<key>=<val>;col:<name>")
  path     dotted JSON path; list indices as numbers (e.g. national.gap, rows.3.verified); "a/b" = ratio of two paths
  fmt      int | pct1 (ratio -> 18.4%) | pct0 | f1 | f2 | frac (a/b -> 40/40) | ci (list -> [91.2, 100]) | str
  command  the command that writes the file
  where    comma-separated documents that print it (README.md, technical_report.md, docs/form_notes.md, ...) or '-'
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

from .paths import ROOT

COLS = ["id", "shown", "file", "path", "fmt", "command", "where"]


def _get(obj, path: str):
    for part in path.split("."):
        if isinstance(obj, list):
            obj = obj[int(part)]
        else:
            obj = obj[part]
    return obj


def _csv_get(p: Path, path: str):
    sel = dict(kv.split(":", 1) for kv in path.split(";"))
    k, v = sel["row"].split("=", 1)
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r[k] == v:
            return r[sel["col"]]
    raise KeyError(path)


def _num(x: float, nd: int) -> str:
    s = f"{x:,.{nd}f}"
    return s


def render(value, fmt: str) -> str:
    if fmt == "int":
        return f"{int(round(float(value))):,}"
    if fmt in ("pct1", "pct0"):
        return _num(100 * float(value), 1 if fmt == "pct1" else 0) + "%"
    if fmt in ("f1", "f2"):
        return _num(float(value), int(fmt[1]))
    if fmt == "frac":
        a, b = value
        return f"{int(a)}/{int(b)}"
    if fmt == "ci":
        lo, hi = value
        f = lambda v: (f"{v:.1f}".rstrip("0").rstrip(".") if float(v) != 100 else "100")  # noqa: E731
        return f"[{f(lo)}, {f(hi)}]"
    return str(value)


def value_of(row: dict):
    p = ROOT / row["file"]
    if p.suffix == ".csv":
        return _csv_get(p, row["path"])
    d = json.loads(p.read_text())
    if "/" in row["path"] and row["fmt"] in ("pct1", "pct0", "frac", "f1", "f2"):
        a, b = row["path"].split("/")
        va, vb = float(_get(d, a)), float(_get(d, b))
        return (va, vb) if row["fmt"] == "frac" else va / vb
    return _get(d, row["path"])


def load(path: Path) -> list[dict]:
    txt = path.read_text(encoding="utf-8")
    return [r for r in csv.DictReader(io.StringIO(txt), delimiter="\t") if r["id"] and not r["id"].startswith("#")]


def merge() -> list[dict]:
    rows, seen = [], set()
    for f in sorted((ROOT / "claims.d").glob("*.tsv")):
        for r in load(f):
            assert r["id"] not in seen, f"duplicate claim id {r['id']}"
            seen.add(r["id"])
            rows.append(r)
    with open(ROOT / "claims.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS})
    return rows


def check(rows: list[dict] | None = None) -> list[str]:
    rows = rows if rows is not None else load(ROOT / "claims.tsv")
    errs, docs = [], {}
    for r in rows:
        try:
            got = render(value_of(r), r["fmt"])
        except Exception as e:  # missing file / path
            errs.append(f"{r['id']}: cannot recompute ({type(e).__name__}: {e})")
            continue
        if got != r["shown"]:
            errs.append(f"{r['id']}: shown {r['shown']!r} but {r['file']}:{r['path']} renders {got!r}")
        for doc in [w.strip() for w in r["where"].split(",") if w.strip() and w.strip() != "-"]:
            if doc not in docs:
                p = ROOT / doc
                docs[doc] = p.read_text(encoding="utf-8") if p.exists() else None
            if docs[doc] is None:
                errs.append(f"{r['id']}: document {doc} missing")
            elif r["shown"] not in docs[doc]:
                errs.append(f"{r['id']}: {r['shown']!r} not found in {doc}")
    return errs


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    rows = merge() if cmd in ("merge", "check") and (ROOT / "claims.d").exists() else None
    errs = check(rows)
    for e in errs:
        print("CLAIM FAIL", e)
    print(f"claims: {len(rows if rows is not None else load(ROOT / 'claims.tsv'))} checked, {len(errs)} failing")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
