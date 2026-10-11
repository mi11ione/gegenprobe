"""claims.tsv: every number in README / report / form notes maps to a results file, a JSON path and the command that produced it.

Fragments live in claims.d/<area>.tsv (one per workstream); `python -m gegenprobe.claims merge` concatenates them into
claims.tsv, `check` fails (exit 1) when
  * the value recomputed from the results file, rendered with `fmt`, differs from the `shown` column, or
  * a document listed in `where` does not contain the `shown` string as a whole token (a match inside a longer number,
    e.g. "459" inside "2,459", "4" inside "4.5" or "10" in "10⁻⁷", does not count), or
  * the `shown` string has 3 characters or fewer and the claim carries no `context` for that document, or the context
    phrase is not found within CONTEXT_WINDOW characters of a token match of `shown` in that document, or
  * an anchor (claims_anchor.json: {claim id: {document: [phrase, ...]}}) is not found in its document, does not contain
    the claim's `shown` value as a whole token, or names a document the claim's `where` does not list, or
  * a numeric token inside a strict zone (claims_strict.json: since round 13 the README, the technical report and the
    form notes, each end to end) is not bound to a claim: no anchor of a
    claim whose `where` lists that document covers that exact token, i.e. no occurrence of an anchor phrase holds the
    claim's `shown` value at the token's position. Numeric tokens: integers >= 10, every decimal, percentage, ratio
    (120/120) and interval ([96.9, 100]); integers below 10 are free. Non-claims (team number, dates, the form's character
    limit) are listed one by one in claims_strict.json as literal phrases; a token is exempt only inside an occurrence of
    such a phrase. In the result tables listed under `small_int_tables` (the P1, P2 and P6 arm tables of the report)
    integers below 10 are numeric tokens too, or
  * a scope word in a strict zone (post hoc, registered, exploratory, in-sample, held out, weighted, unweighted; not
    "pre-registered") lies outside every anchor phrase and every allowlisted phrase: it is bound to the claim it
    qualifies by an anchor that contains both (`python -m gegenprobe.claims scope` proposes them), so flipping
    "post hoc" to "registered" breaks the anchor, or
  * a pinned phrase (claims_strict.json `pinned`: statements without a number such as "blind AI annotators" or "OPD
    confirmed") does not occur exactly its pinned number of times, or
  * a wording pin fails (claims_pins.json, gegenprobe.claims_pins; round 16): a verdict, multiplier or comparative bound
    to the result it states ("is not confirmed" bound to P10's H3a verdict, "about three times" to 50/17), or a safety,
    sovereignty or coding-assistant sentence, no longer occurs exactly as pinned; or a verdict, quantifier or safety
    word appears outside every pinned or allowlisted phrase.

The repository-root README (../README.md) is a strict zone too (round 16). It is outside the Docker build context, so
inside the image it is skipped; the host CI job sets GP_CLAIMS_STRICT=1 and checks it.

Binding by anchor is positional: an anchor phrase is the number together with the words that name its claim ("24/29**
| answer dates Apertus finds", "Claude Opus judged 197/200"), so swapping two numbers that are both valid claims for the
document (24/29 <-> 22/29) breaks the anchor and leaves the swapped token unbound. `python -m gegenprobe.claims anchors`
proposes an anchor for every unbound token (the claim whose words best match the token's surroundings, and the token
with its neighbouring words on the same line) and prints them; `--write` adds them to claims_anchor.json for review in
the diff. A token no claim carries is listed as such: it needs a claim, not an anchor.

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
STRICT_NAME = "claims_strict.json"  # at ROOT; read at call time
ANCHOR_NAME = "claims_anchor.json"  # at ROOT; read at call time
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
        prev = text[i - 1] if i > 0 else " "  # never "": "" is in every string ("" in SUPERSCRIPT is True)
        prev2 = text[i - 2] if i > 1 else " "
        nxt = text[j] if j < len(text) else " "
        nxt2 = text[j + 1] if j + 1 < len(text) else " "
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


# ---------------------------------------------------------------------------------------------------- strict zones
_N = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_SN = rf"[−-]?(?:{_N})%?"
NUMERIC = re.compile(
    rf"\[\s*{_SN}\s*,\s*{_SN}\s*\]"           # interval  [96.9, 100] | [-0.02, 0.54] | [33.3%, 75.0%]
    rf"|(?:{_N})/(?:{_N})"                          # ratio     120/120
    rf"|[+−-]?(?:{_N})\s?%"                    # percent   92.3% | +3.6%
    rf"|[+−-]?(?:{_N})")                        # number    9,720 | 0.83 | +22.7


def numeric_tokens(text: str, small: bool = False) -> list[tuple[int, int, str]]:
    """(start, end, token) for every numeric token that a strict zone must back with a claim: intervals, ratios,
    percentages, decimals and integers >= 10 (with `small`, integers below 10 as well: the cells of the result tables
    listed under `small_int_tables`). Skipped: numbers glued to letters or identifiers (P8, v0.1, 8B, fig1,
    run_38098822336, #1-the-schema), power bases (10 in 10⁻⁴) and, without `small`, plain integers below 10."""
    out = []
    for m in NUMERIC.finditer(text):
        i, j, tok = m.start(), m.end(), m.group(0)
        prev = text[i - 1] if i > 0 else " "  # never "": "" is in every string
        nxt = text[j] if j < len(text) else " "
        if tok[0] in "+-−" and (prev.isalnum() or prev in "_-/"):   # a hyphen after a word, id or number: no sign
            i, tok = i + 1, tok[1:]
            k = i - 1                                                      # the hyphen; the word before it decides
            while k > 0 and (text[k - 1].isalnum() or text[k - 1] == "_"):
                k -= 1
            if any(c.isalpha() or c == "_" for c in text[k:i - 1]):     # an id (D2-4, P1-H1): skip
                continue
            prev = " "                                                     # a range (10-20): the second number counts
        if prev.isalpha() or prev in "_#./\\" or prev.isdigit():
            continue
        if nxt.isalpha() or nxt == "_" or nxt in SUPERSCRIPT:
            continue
        plain = re.fullmatch(r"[+−-]?\d+", tok.replace(",", ""))
        if plain and abs(int(tok.lstrip("+-−").replace(",", ""))) < 10 and not small:
            continue
        out.append((i, j, tok))
    return out


def strict_config() -> dict:
    p = ROOT / STRICT_NAME
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def zones_of(text: str, spec) -> list[tuple[int, int]]:
    """A document's strict zones: one spec {start, end} or a list of them."""
    return [zone_of(text, sp) for sp in (spec if isinstance(spec, list) else [spec])]


def zone_of(text: str, spec: dict) -> tuple[int, int]:
    """[start, end) of a strict zone: from `start` (a literal, default the top) up to `end` (a literal, default the end)."""
    lo = 0
    if spec.get("start"):
        lo = text.find(spec["start"])
        if lo < 0:
            raise ValueError(f"zone start {spec['start']!r} not found")
    hi = len(text)
    if spec.get("end"):
        hi = text.find(spec["end"], lo)
        if hi < 0:
            raise ValueError(f"zone end {spec['end']!r} not found")
    return lo, hi


def _norm(tok: str) -> str:
    return re.sub(r"\s+", " ", tok.replace("−", "-")).replace(" %", "%")


def anchor_config() -> dict[str, dict[str, list[str]]]:
    p = ROOT / ANCHOR_NAME
    return json.loads(p.read_text(encoding="utf-8")).get("anchors", {}) if p.exists() else {}


def _where(row: dict) -> list[str]:
    return [w.strip() for w in row["where"].split(",") if w.strip() and w.strip() != "-"]


def anchor_spans(rows: list[dict], anchors: dict, doc: str, text: str, errs: list[str] | None = None) -> set:
    """{(start, end, normalised shown)}: every position in `text` where an anchor of a claim listing `doc` holds the
    claim's shown value. With `errs`, report anchors that are not found, do not contain the value, or name a document
    the claim does not list."""
    by_id = {r["id"]: r for r in rows}
    out = set()
    for cid, per_doc in anchors.items():
        phrases = per_doc.get(doc)
        if not phrases:
            continue
        r = by_id.get(cid)
        if r is None:
            if errs is not None:
                errs.append(f"anchor {cid}: no such claim")
            continue
        if doc not in _where(r):
            if errs is not None:
                errs.append(f"anchor {cid}: {doc} is not in the claim's where")
            continue
        for ph in phrases:
            inner = token_spans(ph, r["shown"])
            if not inner:
                if errs is not None:
                    errs.append(f"anchor {cid}: {ph!r} does not contain {r['shown']!r} as a whole token")
                continue
            hits = [m.start() for m in re.finditer(re.escape(ph), text)]
            if not hits and errs is not None:
                errs.append(f"anchor {cid}: {ph!r} not found in {doc}")
            for h in hits:
                for i, j in inner:
                    out.add((h + i, h + j, _norm(r["shown"])))
    return out


def anchor_check(rows: list[dict], anchors: dict | None = None, docs: dict[str, str] | None = None) -> list[str]:
    """Every anchor is found in its document, holds its claim's value and names a document the claim lists."""
    anchors = anchor_config() if anchors is None else anchors
    errs: list[str] = []
    for doc in sorted({d for per in anchors.values() for d in per}):
        text = docs[doc] if docs is not None and doc in docs else (
            (ROOT / doc).read_text(encoding="utf-8") if (ROOT / doc).exists() else None)
        if text is None:
            if doc.startswith("../") and not os.environ.get("GP_CLAIMS_STRICT"):
                continue
            errs.append(f"anchor: document {doc} missing")
            continue
        anchor_spans(rows, anchors, doc, text, errs)
    return errs


# Scope words: the words that say how far a result reaches. In a strict zone each must sit inside an anchor phrase (so it
# is bound to the claim next to it: flipping "post hoc" to "registered" breaks that anchor) or inside an allowlisted
# phrase; "pre-registered" (the design, not a result's status) is not one of them.
SCOPE = re.compile(r"(?<![\w-])(post[ -]hoc|registered|exploratory|in-sample|held[ -]out|unweighted|weighted)(?![\w-])",
                   re.I)


def scope_tokens(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in SCOPE.finditer(text)]


def table_lines(text: str, prefixes: list[str]) -> list[tuple[int, int]]:
    """[start, end) of every body row of the markdown tables whose header row starts with one of `prefixes`."""
    out, lines, pos = [], text.split("\n"), 0
    starts = []
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    k = 0
    while k < len(lines):
        if any(lines[k].startswith(px) for px in prefixes):
            k += 2  # header + |---| separator
            while k < len(lines) and lines[k].lstrip().startswith("|"):
                out.append((starts[k], starts[k] + len(lines[k])))
                k += 1
            continue
        k += 1
    return out


def anchor_extents(rows: list[dict], anchors: dict, doc: str, text: str) -> list[tuple[int, int]]:
    """[start, end) of every occurrence of a valid anchor phrase (one that holds its claim's value) in `text`."""
    by_id = {r["id"]: r for r in rows}
    out = []
    for cid, per_doc in anchors.items():
        r = by_id.get(cid)
        if r is None or doc not in _where(r):
            continue
        for ph in per_doc.get(doc) or []:
            if not token_spans(ph, r["shown"]):
                continue
            out += [(m.start(), m.end()) for m in re.finditer(re.escape(ph), text)]
    return out


def _outside_skipped(doc: str) -> bool:
    """A document outside the project (the repository-root README) that is absent: skipped inside the Docker build
    context, an error under GP_CLAIMS_STRICT (the host CI job)."""
    return doc.startswith("../") and not os.environ.get("GP_CLAIMS_STRICT")


def pinned_check(cfg: dict | None = None, docs: dict[str, str] | None = None) -> list[str]:
    """claims_strict.json `pinned`: {document: [{phrase, count, why}]}: a phrase that states a fact without a number
    ("blind AI annotators", "OPD confirmed") must occur exactly `count` times, so rewording one occurrence fails."""
    cfg = strict_config() if cfg is None else cfg
    errs = []
    for doc, items in (cfg.get("pinned") or {}).items():
        text = docs[doc] if docs is not None and doc in docs else (
            (ROOT / doc).read_text(encoding="utf-8") if (ROOT / doc).exists() else None)
        if text is None:
            if not _outside_skipped(doc):
                errs.append(f"pinned: document {doc} missing")
            continue
        for it in items:
            n = text.count(it["phrase"])
            if n != it["count"]:
                errs.append(f"pinned {doc}: {it['phrase']!r} occurs {n} times, pinned at {it['count']} ({it['why']})")
    return errs


def _bound(spans: set, i: int, j: int, tok: str) -> bool:
    t = _norm(tok)
    if (i, j, t) in spans:
        return True
    return t.startswith("+") and (i + 1, j, t[1:]) in spans  # "+22.7" bound by a claim shown "22.7"


def zone_check(rows: list[dict], cfg: dict | None = None, docs: dict[str, str] | None = None,
               anchors: dict | None = None) -> list[str]:
    """Every numeric token in each strict zone is bound to a claim whose `where` lists that document (an anchor phrase
    of that claim holds the claim's shown value at exactly that position), or sits inside an allowlisted literal phrase
    of that document. A token with a leading '+' may be bound by the unsigned value; a leading minus must be claimed
    with its sign."""
    cfg = strict_config() if cfg is None else cfg
    anchors = anchor_config() if anchors is None else anchors
    errs = []
    for doc, spec in (cfg.get("zones") or {}).items():
        if docs is not None and doc in docs:
            text = docs[doc]
        else:
            p = ROOT / doc
            if not p.exists():
                if not _outside_skipped(doc):
                    errs.append(f"strict zone: document {doc} missing")
                continue
            text = p.read_text(encoding="utf-8")
        try:
            zones = zones_of(text, spec)
        except ValueError as e:
            errs.append(f"strict zone {doc}: {e}")
            continue
        allowed = []
        for a in (cfg.get("allow") or {}).get(doc, []):
            hits = [(m.start(), m.end()) for m in re.finditer(re.escape(a["phrase"]), text)]
            if not hits:
                errs.append(f"strict zone {doc}: allowlisted phrase {a['phrase']!r} not found (remove it)")
            allowed += hits
        spans = anchor_spans(rows, anchors, doc, text)
        extents = anchor_extents(rows, anchors, doc, text)
        tables = table_lines(text, (cfg.get("small_int_tables") or {}).get(doc, []))
        for lo, hi in zones:
            toks = numeric_tokens(text[lo:hi])
            seen = {(i, j) for i, j, _ in toks}
            for a, b in tables:  # result-table rows: integers below 10 are claims too
                if lo <= a and b <= hi:
                    toks += [(i + a - lo, j + a - lo, t) for i, j, t in numeric_tokens(text[a:b], small=True)
                             if (i + a - lo, j + a - lo) not in seen]
            for i, j, tok in sorted(toks):
                i, j = i + lo, j + lo
                if any(a <= i and j <= b for a, b in allowed):
                    continue
                if _bound(spans, i, j, tok):
                    continue
                line = text.count("\n", 0, i) + 1
                errs.append(f"strict zone {doc}:{line}: {tok!r} is not bound to a claim for {doc} "
                            "(no anchor of a claim with this value covers it)")
            for i, j, w in scope_tokens(text[lo:hi]):
                i, j = i + lo, j + lo
                if any(a <= i and j <= b for a, b in allowed) or any(a <= i and j <= b for a, b in extents):
                    continue
                line = text.count("\n", 0, i) + 1
                errs.append(f"strict zone {doc}:{line}: scope word {w!r} is not inside an anchor phrase or an "
                            "allowlisted phrase (bind it to the claim it qualifies)")
    return errs


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
    from .claims_pins import check as pins_check
    return errs + anchor_check(rows) + zone_check(rows) + pinned_check() + pins_check()


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


def _anchor_phrase(text: str, i: int, j: int, prev_end: int, next_start: int) -> str:
    """The token with its neighbouring words on the same line: up to 5 words after it (stopping before the next numeric
    token), and, when fewer than 2 words follow, up to 5 words before it as well."""
    ls = text.rfind("\n", 0, i) + 1
    le = text.find("\n", j)
    le = len(text) if le < 0 else le
    end = j
    for n, m in enumerate(re.finditer(r"\S+", text[j:min(le, next_start)])):
        if n == 5:
            break
        end = j + m.end()
    start = i
    starts = [ls + m.start() for m in re.finditer(r"\S+", text[ls:i])]
    if len(re.findall(r"[A-Za-zÀ-ÿ]{2,}", text[j:end])) < 2:
        seg = [k for k in starts if k >= prev_end]
        if seg:
            start = seg[-5] if len(seg) >= 5 else seg[0]
    # extend to the left (same line) until the phrase is unique in the document, so that it names one position
    left = [k for k in starts if k < start]
    while text.count(text[start:end]) > 1 and left:
        start = left.pop()
    return text[start:end]


def propose_anchors(rows: list[dict] | None = None, write: bool = False) -> dict:
    rows = rows if rows is not None else load(ROOT / "claims.tsv")
    cfg, anchors = strict_config(), anchor_config()
    side = contexts()
    report = dict(added=[], no_claim=[], ambiguous=[])
    for doc, spec in (cfg.get("zones") or {}).items():
        text = (ROOT / doc).read_text(encoding="utf-8")
        allowed = []
        for a in (cfg.get("allow") or {}).get(doc, []):
            allowed += [(m.start(), m.end()) for m in re.finditer(re.escape(a["phrase"]), text)]
        spans = anchor_spans(rows, anchors, doc, text)
        cands_by_val: dict[str, list[dict]] = {}
        for r in rows:
            if doc in _where(r):
                cands_by_val.setdefault(_norm(r["shown"]), []).append(r)
        tables = table_lines(text, (cfg.get("small_int_tables") or {}).get(doc, []))
        for lo, hi in zones_of(text, spec):
            toks = [(a + lo, b + lo, t) for a, b, t in numeric_tokens(text[lo:hi])]
            seen = {(a, b) for a, b, _ in toks}
            for ta, tb in tables:
                if lo <= ta and tb <= hi:
                    toks += [(a + ta, b + ta, t) for a, b, t in numeric_tokens(text[ta:tb], small=True)
                             if (a + ta, b + ta) not in seen]
            toks.sort()
            for k, (i, j, tok) in enumerate(toks):
                if any(a <= i and j <= b for a, b in allowed) or _bound(spans, i, j, tok):
                    continue
                t = _norm(tok)
                cands = cands_by_val.get(t) or (cands_by_val.get(t[1:]) if t.startswith("+") else None)
                line = text.count("\n", 0, i) + 1
                if not cands:
                    report["no_claim"].append(f"{doc}:{line}: {tok!r}")
                    continue
                low = text.lower()
                ls_, le_ = text.rfind("\n", 0, i) + 1, text.find("\n", j)
                in_table = text[ls_:i].lstrip().startswith("|")
                win = low[ls_:le_] if in_table else low[max(0, i - 100): j + 100]

                def score(r, doc=doc, win=win):
                    ctx = context_of(r, side).get(doc, "").lower()
                    return (3 * (bool(ctx) and ctx in win) + 2 * sum(w in win for w in _synonyms(r))
                            + sum(w in win for w in _keywords(r)))
                ranked = sorted(cands, key=lambda r: (-score(r), r["id"]))
                best = ranked[0]
                if in_table and score(best) == 0:
                    report["no_claim"].append(f"{doc}:{line}: {tok!r} (table cell; no claim whose words match its row)")
                    continue
                if len(ranked) > 1 and score(ranked[1]) == score(best) and ranked[1]["path"] != best["path"]:
                    report["ambiguous"].append(f"{doc}:{line}: {tok!r} -> {best['id']} (tie with {ranked[1]['id']})")
                prev_end = toks[k - 1][1] if k else lo
                next_start = toks[k + 1][0] if k + 1 < len(toks) else hi
                ph = _anchor_phrase(text, i + (1 if t.startswith("+") and _norm(best["shown"]) == t[1:] else 0), j,
                                    prev_end, next_start)
                anchors.setdefault(best["id"], {}).setdefault(doc, [])
                if ph not in anchors[best["id"]][doc]:
                    anchors[best["id"]][doc].append(ph)
                spans |= {(i, j, t)}
                report["added"].append(f"{doc}:{line}: {tok!r} -> {best['id']}: {ph!r}")
    if write:
        p = ROOT / ANCHOR_NAME
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        cur.setdefault("_doc", "Anchors for `make claims`: {claim id: {document: [phrase, ...]}}. A phrase holds the "
                               "claim's shown value with the words that name it; in a strict zone every numeric token "
                               "must sit inside such a phrase at its position (gegenprobe.claims.zone_check).")
        cur["anchors"] = {k: {d: sorted(v) for d, v in sorted(anchors[k].items())} for k in sorted(anchors)}
        p.write_text(json.dumps(cur, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def propose_scope(rows: list[dict] | None = None, write: bool = False) -> dict:
    """For every scope word in a strict zone outside an anchor or allowlisted phrase: extend the anchor of the nearest
    bound numeric token on the same line (or the next/previous line within CONTEXT_WINDOW characters) so that it covers
    the word: a new anchor phrase for that token's claim, from the earlier to the later of the two. Words with no bound
    number nearby are listed (`unbound`): allowlist them with a reason or reword."""
    rows = rows if rows is not None else load(ROOT / "claims.tsv")
    cfg, anchors = strict_config(), anchor_config()
    report = dict(added=[], unbound=[])
    for doc, spec in (cfg.get("zones") or {}).items():
        text = (ROOT / doc).read_text(encoding="utf-8")
        allowed = []
        for a in (cfg.get("allow") or {}).get(doc, []):
            allowed += [(m.start(), m.end()) for m in re.finditer(re.escape(a["phrase"]), text)]
        by_pos = {}
        for cid, per in anchors.items():
            r = next((x for x in rows if x["id"] == cid), None)
            if r is None or doc not in _where(r):
                continue
            for ph in per.get(doc) or []:
                for m in re.finditer(re.escape(ph), text):
                    for i, j in token_spans(ph, r["shown"]):
                        by_pos[(m.start() + i, m.start() + j)] = cid
        for lo, hi in zones_of(text, spec):
            for i, j, w in scope_tokens(text[lo:hi]):
                i, j = i + lo, j + lo
                ext = anchor_extents(rows, anchors, doc, text)
                if any(a <= i and j <= b for a, b in allowed + ext):
                    continue
                cands = sorted(((min(abs(a - j), abs(i - b)), a, b) for (a, b) in by_pos
                                if abs(a - j) <= CONTEXT_WINDOW or abs(i - b) <= CONTEXT_WINDOW), key=lambda x: x[0])
                cands = [c for c in cands if text.count("\n", min(c[1], i), max(c[2], j)) <= 1]
                line = text.count("\n", 0, i) + 1
                if not cands:
                    report["unbound"].append(f"{doc}:{line}: {w!r}: {text[max(0, i - 50):j + 50]!r}")
                    continue
                _, a, b = cands[0]
                cid = by_pos[(a, b)]
                st, en = min(a, i), max(b, j)
                ph = text[st:en]
                while text.count(ph) > 1 and st > 0 and text[st - 1] != "\n":
                    st -= 1
                    ph = text[st:en]
                anchors.setdefault(cid, {}).setdefault(doc, [])
                if ph not in anchors[cid][doc]:
                    anchors[cid][doc].append(ph)
                report["added"].append(f"{doc}:{line}: {w!r} -> {cid}: {ph!r}")
    if write:
        p = ROOT / ANCHOR_NAME
        cur = json.loads(p.read_text(encoding="utf-8"))
        cur["anchors"] = {k: {d: sorted(v) for d, v in sorted(anchors[k].items())} for k in sorted(anchors)}
        p.write_text(json.dumps(cur, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd == "scope":
        rep = propose_scope(merge(), write="--write" in argv)
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0
    if cmd == "anchors":
        rep = propose_anchors(merge(), write="--write" in argv)
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0
    if cmd == "context":
        rep = backfill()
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0
    rows = merge() if cmd in ("merge", "check") and (ROOT / "claims.d").exists() else None
    errs = check(rows)
    for e in errs:
        print("CLAIM FAIL", e)
    from .claims_pins import summary as pins_summary
    print(f"claims: {len(rows if rows is not None else load(ROOT / 'claims.tsv'))} checked, {len(errs)} failing "
          f"(with {pins_summary()})")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
