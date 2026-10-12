"""Wording pins for `make claims`: the statements a reader takes away that carry no number of their own.

The numeric check (gegenprobe.claims) binds every number and scope word; it cannot see a verdict flipped ("is not
confirmed" -> "is confirmed"), a multiplier changed ("about three times" -> "five times"), or a safety, sovereignty or
declaration sentence rewritten ("The default runs no model" -> "runs Apertus"). This module checks them from ONE file,
claims_pins.json (at track_2a/), so a docs pass updates them in one place:

  pins     [{id, results, docs, polarity?, why?}]
           results   conditions on results files that the wording states; each is
                       {file, path, is}                     the JSON value at `path` equals `is` (a verdict, a bool, a
                                                            count), or
                       {file, vars: {name: path}, expr, is} a small expression over JSON values (round(a / b), a - b,
                                                            lo < 0, ...) equals `is`, or
                       {doc, table, match: {column: regex}, is} the number of rows of a committed document's table
                                                            (by the start of its header row) whose cells match: a count
                                                            stated in prose bound to the table that lists the items
                                                            (`after`: the first such table after a literal heading), or
                       {file: <source>.py, path: NAME, is}  a module-level constant of the code (a default the
                                                            documents state: cache_retention.DEFAULT_DAYS);
                     a path step `[key=value]` selects the one list element whose `key` is `value`;
                     a pin without `results` is a pinned sentence (a statement no results file holds: the safety,
                     sovereignty and coding-assistant sentences)
           docs      {document: [phrase | {phrase, count}]}: each phrase must occur exactly `count` times (default 1)
           polarity  "neg" (every phrase must carry a negation: not, no, none, failed, ...) or "pos" (none may): so a
                     verdict pin cannot be "updated" to the opposite wording while its result stays negative
           must      a regex every phrase must match: the quantifier its result states ("one" open decision, "three"
                     splits on "one parliament each", "five" intervention types), so a count cannot be re-pinned as
                     another
  guards   {name: regex}: in every document of `docs`, each match must lie inside an occurrence of a pin phrase or of
           an `allow` phrase; an inserted "five times", "Apertus runs unattended", "ahead of", "production-ready" or
           "runs locally on a laptop" fails even where no pin existed before. The guards: verdict words, multipliers
           and quantifiers ("about three times"), safety/sovereignty/declaration phrases, comparatives (level, ahead,
           behind, beats, outperforms, better, worse, ties, ...), maturity and role words (ready to deploy,
           deployable, prototype, feasibility study, final, essential, earns its place, reviewer's aid, extractor,
           robust, accurate, unattended, needs_review, recommends, ...), scope quantifiers (every one, most, all,
           never, always, only), deployment words (locally, laptop, CPU, GPU, on-prem, air-gapped), labelling words
           (human, expert, clerk, lawyer, staff, manual, by hand, people, person, ...: who labelled), adoption words
           (shipped, deployed, adopted, applied, in (daily) use, live, rolled out, used by, ...), evaluative words
           (dominates, improves, dramatic, substantial, higher, lower, far, ...), safety claims (guarantee, certified,
           hallucination, GDPR, compliant, secure, safe, error-free, ...) and cost words (free, cheap, low-cost,
           negligible, ...); R20 (J5's round-19 mutation battery, tests/test_claims_battery.py): scope extent
           (inside/outside/within/beyond the tested scope), review (reviewer, confirms, written directly,
           automatically, without review), jurisdiction (Swiss, US, EU, abroad, processing agreement, DPA, nDSG, data
           protection, nonprofit; Public AI's terms bound to results/compliance/publicai_terms.json) and intensifiers
           (decisive, virtually, almost all, key component, the main, entirely, fully, clearly, ...), each with its
           German forms for docs/decision_de.md; R21 (J5's round-20 battery): number words (none, one ... twelve,
           single, both, a few, several, and no/every/all before a counted noun such as split, session, parliament,
           field, document; German zwei ... zwölf, beide, mehrere, kein/jede/alle + noun), which also count as bound
           inside an anchor, allowlisted or pinned phrase of the numeric check (`claims_covered`) and are not prose
           inside code spans or HTML tags (`skip_code`). A comparative
           is pinned with the result that makes it true where one exists ("level with document order" with both
           cluster intervals spanning 0; "beats the rules on 22 and loses on 4" with the discordant pairs)
  allow    {document: [{phrase, why}]}: guard words that are not claims ("fails on any mismatch" describes the checker)
  docs     the documents the guards scan (README.md, technical_report.md, docs/form_notes.md, ../README.md), extended
           by claims_strict.json `strict_docs` (the one list of strict documents)
  zones    {document: [{start, end}]}: a document the guards scan only between two literals (the runbook's operator
           sheet and route table, a zone of claims_strict.json too)

Documents outside the project (../README.md, the repository root) are not in the Docker build context; inside the image
they are skipped unless GP_CLAIMS_STRICT=1, which the host CI job sets (as gegenprobe.claims does).

    PYTHONPATH=src:. python -m gegenprobe.claims_pins            check (also part of `python -m gegenprobe.claims check`)
    PYTHONPATH=src:. python -m gegenprobe.claims_pins uncovered  every guard match outside a pin or allow phrase, in context
    PYTHONPATH=src:. python -m gegenprobe.claims_pins propose    the same, as allow entries to paste ({phrase, why: "TODO"})
"""
from __future__ import annotations

import ast
import json
import operator
import os
import re
import sys
from pathlib import Path

from .paths import ROOT

PINS_NAME = "claims_pins.json"  # at ROOT; read at call time
NEG = re.compile(r"(?i)(?<![\w-])(not|no|none|never|nothing|failed|fail|fails|below|without|"
                 r"nicht|kein\w*|nie|niemals|nichts|ohne)(?![\w-])")  # English and German (docs/decision_de.md)


STRICT_NAME = "claims_strict.json"  # its `strict_docs` are scanned by the guards too


def config(path: Path | None = None) -> dict:
    """claims_pins.json; its `docs` extended by claims_strict.json's `strict_docs` (one list names the strict
    documents: adding docs/decision.md there puts it under the numbers, scope words, small integers and these guards)."""
    p = path or ROOT / PINS_NAME
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    sp = (path.parent if path else ROOT) / STRICT_NAME
    if cfg and sp.exists():
        extra = json.loads(sp.read_text(encoding="utf-8")).get("strict_docs") or []
        cfg["docs"] = list(cfg.get("docs") or []) + [d for d in extra if d not in (cfg.get("docs") or [])]
    return cfg


def _get(obj, path: str):
    """A dotted JSON path; a list is indexed by number or selected by `[key=value]` (the one element whose `key` is
    `value`, e.g. parliaments.rows.[key=BE].periods), so a pin does not depend on the order of a list. A `*` step maps
    the rest of the path over every element of a list and returns the flat list of the values (sets.*.sessions.*.models.*:
    every model of every annotator session)."""
    parts = path.split(".")
    for k, part in enumerate(parts):
        if part == "*":
            rest = ".".join(parts[k + 1:])
            out = []
            for x in obj:
                v = _get(x, rest) if rest else x
                out += v if isinstance(v, list) and "*" in parts[k + 1:] else [v]
            return out
        if isinstance(obj, list) and part.startswith("[") and part.endswith("]") and "=" in part:
            key, val = part[1:-1].split("=", 1)
            hits = [x for x in obj if isinstance(x, dict) and str(x.get(key)) == val]
            if len(hits) != 1:
                raise KeyError(f"{part}: {len(hits)} elements match")
            obj = hits[0]
        else:
            obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
        ast.UAdd: operator.pos, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
        ast.And: all, ast.Or: any, ast.Not: operator.not_}
_FUNCS = {"round": round, "abs": abs, "min": min, "max": max, "len": len, "sum": sum, "int": int, "float": float,
          "sorted": sorted, "set": set}


def evaluate(expr: str, env: dict):
    """A small arithmetic/comparison expression over named JSON values (no attribute access, no calls but _FUNCS)."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in env:
                raise KeyError(f"unknown name {n.id!r}")
            return env[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.BoolOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(v) for v in n.values)
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, c in zip(n.ops, n.comparators):
                right = ev(c)
                if type(op) not in _OPS or not _OPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        if isinstance(n, ast.List):
            return [ev(x) for x in n.elts]
        raise ValueError(f"unsupported expression element {type(n).__name__}")
    return ev(ast.parse(expr, mode="eval"))


def table_count(text: str, header: str, match: dict[str, str], after: str | None = None) -> int:
    """Rows of the markdown table whose header row starts with `header` in which every column named in `match` matches
    its regex (re.search): a count stated in prose bound to the table that lists the items one by one. With `after` (a
    literal, e.g. a section heading), the first such table after it (documents with several tables of one header)."""
    if after is not None:
        k = text.find(after)
        if k < 0:
            raise KeyError(f"{after!r} not found")
        text = text[k:]
    lines = text.split("\n")
    for k, ln in enumerate(lines):
        if ln.startswith(header):
            cols = [c.strip() for c in ln.strip().strip("|").split("|")]
            n, r = 0, k + 2
            while r < len(lines) and lines[r].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[r].strip().strip("|").split("|")]
                row = dict(zip(cols, cells))
                n += all(re.search(rx, row.get(col, "")) for col, rx in match.items())
                r += 1
            return n
    raise KeyError(f"no table with header {header!r}")


def condition_value(c: dict, root: Path = ROOT, docs: dict[str, str] | None = None):
    if "table" in c:  # {doc, table, match: {column: regex}, is}: a count over a committed document's table
        text = _doc_text(c["doc"], docs, root)
        if text is None:
            raise FileNotFoundError(c["doc"])
        return table_count(text, c["table"], c["match"], c.get("after"))
    if c["file"].endswith(".py"):  # {file: <source>.py, path: <module-level constant>, is}: a code default
        from .claims import py_const
        return py_const(root / c["file"], c["path"])
    d = json.loads((root / c["file"]).read_text(encoding="utf-8"))
    if "expr" in c:
        return evaluate(c["expr"], {k: _get(d, p) for k, p in (c.get("vars") or {}).items()})
    return _get(d, c["path"])


def _cond_name(c: dict) -> str:
    if "table" in c:
        return f"{c['doc']} table {c['table']!r} rows matching {c['match']}"
    return f"{c.get('file')}:{c.get('path') or c.get('expr')}"


def _phrases(spec) -> list[tuple[str, int]]:
    return [(x, 1) if isinstance(x, str) else (x["phrase"], int(x.get("count", 1))) for x in spec]


def _doc_text(doc: str, docs: dict[str, str] | None, root: Path) -> str | None:
    if docs is not None and doc in docs:
        return docs[doc]
    p = root / doc
    return p.read_text(encoding="utf-8") if p.exists() else None


def _skippable(doc: str) -> bool:
    return doc.startswith("../") and not os.environ.get("GP_CLAIMS_STRICT")


def guard_matches(cfg: dict, text: str) -> list[tuple[int, int, str, str]]:
    """(start, end, word, guard) of every guard match; for the guards listed under `skip_code` (the number words) a match
    inside an inline code span, a fenced block or an HTML tag (`--hash keep`, style="max-height:none") is not prose."""
    out, code = [], None
    for name, rx in (cfg.get("guards") or {}).items():
        ms = [(m.start(), m.end(), m.group(0), name) for m in re.finditer(rx, text)]
        if name in (cfg.get("skip_code") or []):
            if code is None:
                from .claims import _code_spans
                code = _code_spans(text)
            ms = [x for x in ms if not any(a <= x[0] and x[1] <= b for a, b in code)]
        out += ms
    return sorted(out)


def _literal(text: str, s: str) -> list[tuple[int, int]]:
    """The non-overlapping occurrences of `s` (as re.finditer(re.escape(s), text), without a compiled pattern each)."""
    from .claims import _literal as lit
    return list(lit(text, s))


def claim_spans(doc: str, text: str) -> list[tuple[int, int]]:
    """The literal phrases of the numeric check that cover `text`: every valid anchor phrase of a claim listing `doc`
    (claims_anchor.json), every allowlisted and every pinned phrase of claims_strict.json. Each fails when its words
    change (the anchor is not found, the allowlisted phrase is not found, the pinned count changes), so a guard word
    inside one is bound as firmly as inside a pin phrase."""
    from .claims import ANCHOR_NAME, anchor_extents, load
    # read from this module's ROOT (the documents' root), not gegenprobe.claims.ROOT, which tests may point elsewhere
    rows = load(ROOT / "claims.tsv") if (ROOT / "claims.tsv").exists() else []
    ap, sp = ROOT / ANCHOR_NAME, ROOT / STRICT_NAME
    anchors = json.loads(ap.read_text(encoding="utf-8")).get("anchors", {}) if ap.exists() else {}
    scfg = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    spans = anchor_extents(rows, anchors, doc, text)
    for it in list((scfg.get("allow") or {}).get(doc) or []) + list((scfg.get("pinned") or {}).get(doc) or []):
        spans += _literal(text, it["phrase"])
    return spans


def covered_spans(cfg: dict, doc: str, text: str) -> list[tuple[int, int]]:
    spans = []
    for pin in cfg.get("pins") or []:
        for ph, _ in _phrases((pin.get("docs") or {}).get(doc) or []):
            spans += list(_literal(text, ph))
    for a in (cfg.get("allow") or {}).get(doc) or []:
        spans += list(_literal(text, a["phrase"]))
    return spans


def scanned_docs(cfg: dict) -> list[str]:
    """The documents the guards scan: `docs` end to end, and the documents of `zones` within their zones."""
    docs = list(cfg.get("docs") or [])
    return docs + [d for d in (cfg.get("zones") or {}) if d not in docs]


def doc_matches(cfg: dict, doc: str, text: str) -> list[tuple[int, int, str, str]]:
    """The guard matches of `doc`: all of them for a document of `docs`; for a document listed only under `zones`
    ({document: [{start, end}]}, as claims_strict.json zones: the operator sheet of docs/runbook.md), those inside a
    zone."""
    ms = guard_matches(cfg, text)
    if doc in (cfg.get("docs") or []) or doc not in (cfg.get("zones") or {}):
        return ms
    from .claims import zones_of
    zs = zones_of(text, cfg["zones"][doc])
    return [m for m in ms if any(lo <= m[0] and m[1] <= hi for lo, hi in zs)]


def _claims_covered(cfg: dict, doc: str, text: str) -> dict[str, list[tuple[int, int]]]:
    """{guard name: spans}: for the guards listed under `claims_covered` (the number words), the phrases of the numeric
    check count as cover too (claim_spans)."""
    names = cfg.get("claims_covered") or []
    if not names:
        return {}
    spans = claim_spans(doc, text)
    return {n: spans for n in names}


def check(cfg: dict | None = None, docs: dict[str, str] | None = None, root: Path = ROOT) -> list[str]:
    """Every pin's results conditions hold, every pin phrase occurs exactly its count, polarity agrees, and every guard
    match in the scanned documents lies inside a pin or allow phrase."""
    cfg = config() if cfg is None else cfg
    errs: list[str] = []
    seen = set()
    texts: dict[str, str | None] = {}

    def text_of(doc):
        if doc not in texts:
            texts[doc] = _doc_text(doc, docs, root)
        return texts[doc]

    for pin in cfg.get("pins") or []:
        pid = pin.get("id", "?")
        if pid in seen:
            errs.append(f"pin {pid}: duplicate id")
        seen.add(pid)
        for c in pin.get("results") or []:
            try:
                got = condition_value(c, root, docs)
            except Exception as e:  # missing file / path / bad expression
                errs.append(f"pin {pid}: cannot evaluate {_cond_name(c)} "
                            f"({type(e).__name__}: {e})")
                continue
            if got != c["is"]:
                errs.append(f"pin {pid}: {_cond_name(c)} is {got!r}, the wording states "
                            f"{c['is']!r} (the result changed: rewrite the sentence and update the pin)")
        pol = pin.get("polarity")
        for doc, spec in (pin.get("docs") or {}).items():
            text = text_of(doc)
            if text is None:
                if not _skippable(doc):
                    errs.append(f"pin {pid}: document {doc} missing")
                continue
            for ph, count in _phrases(spec):
                n = text.count(ph)
                if n != count:
                    errs.append(f"pin {pid} {doc}: {ph!r} occurs {n} times, pinned at {count}"
                                + (f" ({pin['why']})" if pin.get("why") else ""))
                if pin.get("must") and not re.search(pin["must"], ph):
                    errs.append(f"pin {pid} {doc}: {ph!r} lacks {pin['must']!r}, the quantifier or negation its result "
                                "states")
                neg = bool(NEG.search(ph))
                if pol == "neg" and not neg:
                    errs.append(f"pin {pid} {doc}: {ph!r} states no negation but its result is negative")
                if pol == "pos" and neg:
                    errs.append(f"pin {pid} {doc}: {ph!r} carries a negation but its result is positive")
    for doc in scanned_docs(cfg):
        text = text_of(doc)
        if text is None:
            if not _skippable(doc):
                errs.append(f"pins: document {doc} missing")
            continue
        spans = covered_spans(cfg, doc, text)
        wide = _claims_covered(cfg, doc, text)
        for a in (cfg.get("allow") or {}).get(doc) or []:
            if a["phrase"] not in text:
                errs.append(f"pins {doc}: allowlisted phrase {a['phrase']!r} not found (remove it)")
        try:
            matches = doc_matches(cfg, doc, text)
        except ValueError as e:
            errs.append(f"pins {doc}: {e}")
            continue
        for i, j, w, name in matches:
            if any(a <= i and j <= b for a, b in spans):
                continue
            if name in wide and any(a <= i and j <= b for a, b in wide[name]):
                continue
            line = text.count("\n", 0, i) + 1
            errs.append(f"pins {doc}:{line}: {name} word {w!r} is not inside a pinned or allowlisted phrase "
                        f"(claims_pins.json): {text[max(0, i - 60):j + 60]!r}")
    return errs


def summary(cfg: dict | None = None) -> str:
    cfg = config() if cfg is None else cfg
    pins = cfg.get("pins") or []
    bound = sum(1 for p in pins if p.get("results"))
    phrases = sum(len(_phrases(v)) for p in pins for v in (p.get("docs") or {}).values())
    return (f"{len(pins)} wording pins ({bound} bound to results, {len(pins) - bound} pinned sentences; {phrases} "
            f"phrases), {len(cfg.get('guards') or {})} guards over {len(cfg.get('docs') or [])} documents"
            + (f" and {len(cfg['zones'])} zone(s)" if cfg.get("zones") else ""))


def uncovered(cfg: dict | None = None, root: Path = ROOT) -> list[str]:
    cfg = config() if cfg is None else cfg
    out = []
    for doc in scanned_docs(cfg):
        text = _doc_text(doc, None, root)
        if text is None:
            continue
        spans = covered_spans(cfg, doc, text)
        wide = _claims_covered(cfg, doc, text)
        for i, j, w, name in doc_matches(cfg, doc, text):
            if not any(a <= i and j <= b for a, b in spans + wide.get(name, [])):
                line = text.count("\n", 0, i) + 1
                ls, le = text.rfind("\n", 0, i) + 1, text.find("\n", j)
                out.append(f"{doc}:{line} [{name}] {w!r}: {text[max(ls, i - 90):(le if le >= 0 else len(text))][:220]}")
    return out


def propose(cfg: dict | None = None, root: Path = ROOT) -> dict[str, list[dict]]:
    """Allow-entry drafts for every uncovered guard match: the clause around the word (to the nearest , ; : . ( ) or
    line end, widened until it is unique in the document). Review each: a claim gets a pin (bound to its result where
    one exists), a non-claim an allow entry with its reason."""
    cfg = config() if cfg is None else cfg
    out: dict[str, list[dict]] = {}
    for doc in scanned_docs(cfg):
        text = _doc_text(doc, None, root)
        if text is None:
            continue
        spans = covered_spans(cfg, doc, text)
        wide = _claims_covered(cfg, doc, text)
        for i, j, w, name in doc_matches(cfg, doc, text):
            if any(a <= i and j <= b for a, b in spans + wide.get(name, [])):
                continue
            lo = max(text.rfind(c, 0, i) for c in ",;:.()\n") + 1
            his = [k for k in (text.find(c, j) for c in ",;:.()\n") if k >= 0]
            hi = min(his) if his else len(text)
            ph = text[lo:hi].strip()
            while text.count(ph) > 1 and hi < len(text):
                hi += 1
                ph = text[lo:hi].strip()
            item = dict(phrase=ph, why=f"TODO ({name} word {w!r}): a reason, or a pin bound to its result")
            if item not in out.setdefault(doc, []):
                out[doc].append(item)
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["uncovered"]:
        for x in uncovered():
            print(x)
        return 0
    if argv[:1] == ["propose"]:
        print(json.dumps(propose(), ensure_ascii=False, indent=1))
        return 0
    errs = check()
    for e in errs:
        print("PIN FAIL", e)
    print(f"pins: {summary()}, {len(errs)} failing")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
