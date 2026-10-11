"""claims.tsv: every number in README / report / form notes maps to a results file, a JSON path and the command that produced it.

Fragments live in claims.d/<area>.tsv (one per workstream); `python -m gegenprobe.claims merge` concatenates them into
claims.tsv, `check` fails (exit 1) when
  * the value recomputed from the results file, rendered with `fmt`, differs from the `shown` column, or
  * a document listed in `where` does not contain the `shown` string as a whole token (a match inside a longer number,
    e.g. "459" inside "2,459", "4" inside "4.5" or "10" in "10⁻⁷", does not count), or
  * the `shown` string has 3 characters or fewer and the claim carries no `context` for that document, or the context
    phrase is not found within CONTEXT_WINDOW characters of a token match of `shown` in that document.

Short values ("4", "13", "0.9") occur all over a report, so a bare match proves nothing: the context pins the claim to one
place in each document (for a table cell, the phrase is the row label: it pins the row, not the column). Contexts come
from the optional `context` column (a JSON object {document: phrase}) or from claims_context.json (same shape, keyed by
claim id; `python -m gegenprobe.claims context` proposes missing ones). When you rewrite the text around a short number,
update its context.

Columns (tab-separated, header required):
  id       unique claim id (area.slug)
  shown    the string exactly as printed in the documents, e.g. 16,749 | 18.4% | 40/40 | [91.2, 100]
  file     results file relative to track_2a/ (.json, or .csv with path "row:<key>=<val>;col:<name>")
  path     dotted JSON path; list indices as numbers (e.g. national.gap, rows.3.verified); "a/b" = ratio of two paths
  fmt      int | pct1 (ratio -> 18.4%) | pct0 | f1 | f2 | frac (a/b -> 40/40) | ci (list -> [91.2, 100]) | str
  command  the command that writes the file
  where    comma-separated documents that print it (README.md, technical_report.md, docs/form_notes.md, ...) or '-'
  context  optional JSON object {document: literal phrase} required for shown strings of <= 3 characters
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
from pathlib import Path

from .paths import ROOT

COLS = ["id", "shown", "file", "path", "fmt", "command", "where", "context"]
SHORT = 3            # shown strings of at most this many characters need a context
CONTEXT_WINDOW = 120  # the context phrase must sit within this many characters of the value
CONTEXT_FILE = ROOT / "claims_context.json"
SUPERSCRIPT = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻"


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


def token_spans(text: str, shown: str) -> list[tuple[int, int]]:
    """Occurrences of `shown` that are whole tokens: not glued to letters/digits, not part of a longer number
    ("459" in "2,459", "4" in "4.5" or "1.4"), not a negated value ("1.4" in "−1.4") and not a power base ("10" in "10⁻⁷")."""
    out = []
    for m in re.finditer(re.escape(shown), text):
        i, j = m.start(), m.end()
        prev = text[i - 1] if i > 0 else ""
        prev2 = text[i - 2] if i > 1 else ""
        nxt = text[j] if j < len(text) else ""
        nxt2 = text[j + 1] if j + 1 < len(text) else ""
        if shown[:1].isalnum() and (prev.isalnum() or prev == "_"):
            continue
        if shown[:1].isdigit() and ((prev in ".,'" and prev2.isdigit()) or prev == "\u2212"):
            continue
        if shown[-1:].isalnum() and (nxt.isalnum() or nxt == "_"):
            continue
        if shown[-1:].isdigit() and ((nxt in ".,'" and nxt2.isdigit()) or nxt in SUPERSCRIPT):
            continue
        out.append((i, j))
    return out


def contexts() -> dict[str, dict[str, str]]:
    return json.loads(CONTEXT_FILE.read_text(encoding="utf-8")) if CONTEXT_FILE.exists() else {}


def context_of(row: dict, side: dict[str, dict[str, str]]) -> dict[str, str]:
    c = row.get("context") or ""
    if c.strip():
        return json.loads(c)
    return side.get(row["id"], {})


def context_ok(text: str, shown: str, phrase: str) -> bool:
    spans = token_spans(text, shown)
    for m in re.finditer(re.escape(phrase), text):
        lo, hi = m.start() - CONTEXT_WINDOW, m.end() + CONTEXT_WINDOW
        if any(i >= lo and j <= hi for i, j in spans):
            return True
    return False


def load(path: Path) -> list[dict]:
    txt = path.read_text(encoding="utf-8")
    return [r for r in csv.DictReader(io.StringIO(txt), delimiter="\t") if r["id"] and not r["id"].startswith("#")]


def merge() -> list[dict]:
    rows, seen, side = [], set(), contexts()
    for f in sorted((ROOT / "claims.d").glob("*.tsv")):
        for r in load(f):
            assert r["id"] not in seen, f"duplicate claim id {r['id']}"
            seen.add(r["id"])
            ctx = context_of(r, side)
            r["context"] = json.dumps(ctx, ensure_ascii=False, sort_keys=True) if ctx else ""
            rows.append(r)
    with open(ROOT / "claims.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS})
    return rows


def check(rows: list[dict] | None = None) -> list[str]:
    rows = rows if rows is not None else load(ROOT / "claims.tsv")
    errs, docs, side = [], {}, contexts()
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
                # documents outside the project (the repository-root README) are not in the Docker build context; the host
                # CI job checks them. Anything inside the project must exist.
                if doc.startswith("../") and not os.environ.get("GP_CLAIMS_STRICT"):
                    continue
                errs.append(f"{r['id']}: document {doc} missing")
                continue
            if not token_spans(docs[doc], r["shown"]):
                errs.append(f"{r['id']}: {r['shown']!r} not found as a whole token in {doc}")
                continue
            if len(r["shown"]) <= SHORT:
                phrase = context_of(r, side).get(doc)
                if not phrase:
                    errs.append(f"{r['id']}: short value {r['shown']!r} in {doc} has no context")
                elif not context_ok(docs[doc], r["shown"], phrase):
                    errs.append(f"{r['id']}: context {phrase!r} not within {CONTEXT_WINDOW} chars of {r['shown']!r} in {doc}")
    return errs


STOP = {"eval", "results", "json", "report", "claims", "the", "and", "with", "arms", "strict", "counts", "publicai", "swiss",
        "apertus", "build", "summary", "numbers", "file", "path", "all", "data", "docs", "tsv", "per", "p34", "robust"}
SYN = {  # claim-path words -> words that name the same thing in the documents (tables and prose)
    "cascade": ["rules + apertus", "cascade", "every suggestion accepted"], "pointer": ["pointer alone", "apertus pointer"],
    "rules": ["rules only", "rules alone", "rules"], "naive_plain": ["plain"], "naive_null": ["null-allowed", "null allowed"],
    "correct_null": ["right null", "correct null"], "false_null": ["missed", "false null"],
    "misattributed": ["wrong printed", "wrong date", "misattributed"], "fabricated": ["invented", "fabricated"],
    "invented_on_null": ["without answer", "without an answer", "answerless", "on null"], "exact": ["exact"],
    "correct": ["right date", "dates found", "correct"], "recall": ["recall", "found"], "precision": ["precision"],
}


def _keywords(row: dict) -> set[str]:
    words = re.split(r"[^a-z0-9]+", f"{row['id']} {row['path']} {Path(row['file']).stem}".lower())
    return {w[:5] for w in words if len(w) >= 3 and not w.isdigit() and w not in STOP}


def _synonyms(row: dict) -> list[str]:
    key = f"{row['id']}.{row['path']}".lower()
    return [w for k, ws in SYN.items() if re.search(rf"(^|[._]){re.escape(k)}($|[._])", key) for w in ws]


def _table_label(text: str, i: int) -> str | None:
    """For an offset inside a markdown table row: '<column header> <row label>' (lowercase), else None."""
    ls = text.rfind("\n", 0, i) + 1
    le = text.find("\n", i)
    line = text[ls: le if le >= 0 else len(text)]
    if not line.lstrip().startswith("|"):
        return None
    col = line[: i - ls].count("|") - 1
    k, header = ls, None
    while k > 0:  # walk up to the header row (the row above the |---| separator)
        pls = text.rfind("\n", 0, k - 1) + 1
        prev = text[pls: k - 1]
        if not prev.lstrip().startswith("|"):
            break
        if re.match(r"^\s*\|[\s:|-]+\|\s*$", prev):
            hls = text.rfind("\n", 0, pls - 1) + 1
            header = text[hls: pls - 1]
            break
        k = pls
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    hcells = [c.strip() for c in header.strip().strip("|").split("|")] if header else []
    return f"{hcells[col] if 0 <= col < len(hcells) else ''} {cells[0] if cells else ''}".lower()


def _propose(text: str, row: dict) -> tuple[str | None, bool]:
    """(phrase, ambiguous): pin `shown` to the occurrence whose surroundings best match the claim (table column header +
    row label for table cells, nearby words otherwise), with the nearest unique phrase on the same line."""
    shown, spans = row["shown"], token_spans(text, row["shown"])
    if not spans:
        return None, False
    kw, syn = _keywords(row), _synonyms(row)
    low = text.lower()

    def score(sp):
        lab = _table_label(text, sp[0])
        if lab is not None:
            return 3 * sum(w in lab for w in syn) + sum(k in lab for k in kw)
        w = low[max(0, sp[0] - 80): sp[1] + 80]
        return 2 * sum(s_ in w for s_ in syn) + sum(k in w for k in kw)
    ranked = sorted(spans, key=lambda sp: -score(sp))
    best = ranked[0]
    ambiguous = len(ranked) > 1 and score(ranked[1]) >= score(best)
    i, j = best
    ls = text.rfind("\n", 0, i) + 1
    le = text.find("\n", j)
    le = len(text) if le < 0 else le
    lo, hi = max(ls, i - CONTEXT_WINDOW + 10), min(le, j + CONTEXT_WINDOW - 10)
    toks = [(m.start(), m.end()) for m in re.finditer(r"\S+", text[lo:hi])]
    for allow_digits in (False, True):
        cands = []
        for a in range(len(toks)):
            for b in range(a + 1, min(a + 7, len(toks))):
                st, en = lo + toks[a][0], lo + toks[b][1]
                ph = text[st:en]
                if (st < j and en > i) or len(ph) < 12 or (not allow_digits and re.search(r"\d", ph)):
                    continue
                if text.count(ph) != 1 or not context_ok(text, shown, ph):
                    continue
                gap = i - en if en <= i else st - j
                cands.append((gap, -len(ph), ph))
        if cands:
            return min(cands)[2], ambiguous
    return None, ambiguous


def backfill() -> dict:
    """Propose contexts for every short claim/document pair that has none; write them to claims_context.json."""
    side, docs, report = contexts(), {}, dict(added=0, ambiguous=[], none=[])
    for r in merge():
        if len(r["shown"]) > SHORT:
            continue
        have = context_of(r, side)
        for doc in [w.strip() for w in r["where"].split(",") if w.strip() and w.strip() != "-"]:
            if doc in have:
                continue
            p = ROOT / doc
            docs.setdefault(doc, p.read_text(encoding="utf-8") if p.exists() else "")
            phrase, amb = _propose(docs[doc], r)
            if phrase is None:
                report["none"].append(f"{r['id']} in {doc} ({r['shown']!r})")
                continue
            side.setdefault(r["id"], {})[doc] = phrase
            report["added"] += 1
            if amb:
                report["ambiguous"].append(f"{r['id']} in {doc}: {r['shown']!r} pinned near {phrase!r}")
    CONTEXT_FILE.write_text(json.dumps(side, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd == "context":
        rep = backfill()
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0
    rows = merge() if cmd in ("merge", "check") and (ROOT / "claims.d").exists() else None
    errs = check(rows)
    for e in errs:
        print("CLAIM FAIL", e)
    print(f"claims: {len(rows if rows is not None else load(ROOT / 'claims.tsv'))} checked, {len(errs)} failing")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
