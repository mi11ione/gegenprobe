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
                                                            lo < 0, ...) equals `is`;
                     a pin without `results` is a pinned sentence (a statement no results file holds: the safety,
                     sovereignty and coding-assistant sentences)
           docs      {document: [phrase | {phrase, count}]}: each phrase must occur exactly `count` times (default 1)
           polarity  "neg" (every phrase must carry a negation: not, no, none, failed, ...) or "pos" (none may): so a
                     verdict pin cannot be "updated" to the opposite wording while its result stays negative
  guards   {name: regex}: in every document of `docs`, each match (a verdict word, a multiplier or quantifier word, a
           safety/sovereignty/declaration phrase) must lie inside an occurrence of a pin phrase or of an `allow` phrase;
           an inserted "five times" or "Apertus runs unattended" fails even where no pin existed before
  allow    {document: [{phrase, why}]}: guard words that are not claims ("fails on any mismatch" describes the checker)
  docs     the documents the guards scan (README.md, technical_report.md, docs/form_notes.md, ../README.md)

Documents outside the project (../README.md, the repository root) are not in the Docker build context; inside the image
they are skipped unless GP_CLAIMS_STRICT=1, which the host CI job sets (as gegenprobe.claims does).

    PYTHONPATH=src:. python -m gegenprobe.claims_pins            check (also part of `python -m gegenprobe.claims check`)
    PYTHONPATH=src:. python -m gegenprobe.claims_pins uncovered  every guard match outside a pin or allow phrase, in context
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
NEG = re.compile(r"(?i)(?<![\w-])(not|no|none|never|nothing|failed|fail|fails|below|without)(?![\w-])")


def config(path: Path | None = None) -> dict:
    p = path or ROOT / PINS_NAME
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _get(obj, path: str):
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
        ast.UAdd: operator.pos, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
        ast.And: all, ast.Or: any, ast.Not: operator.not_}
_FUNCS = {"round": round, "abs": abs, "min": min, "max": max, "len": len, "sum": sum, "int": int}


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


def condition_value(c: dict, root: Path = ROOT):
    d = json.loads((root / c["file"]).read_text(encoding="utf-8"))
    if "expr" in c:
        return evaluate(c["expr"], {k: _get(d, p) for k, p in (c.get("vars") or {}).items()})
    return _get(d, c["path"])


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
    out = []
    for name, rx in (cfg.get("guards") or {}).items():
        out += [(m.start(), m.end(), m.group(0), name) for m in re.finditer(rx, text)]
    return sorted(out)


def covered_spans(cfg: dict, doc: str, text: str) -> list[tuple[int, int]]:
    spans = []
    for pin in cfg.get("pins") or []:
        for ph, _ in _phrases((pin.get("docs") or {}).get(doc) or []):
            spans += [(m.start(), m.end()) for m in re.finditer(re.escape(ph), text)]
    for a in (cfg.get("allow") or {}).get(doc) or []:
        spans += [(m.start(), m.end()) for m in re.finditer(re.escape(a["phrase"]), text)]
    return spans


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
                got = condition_value(c, root)
            except Exception as e:  # missing file / path / bad expression
                errs.append(f"pin {pid}: cannot evaluate {c.get('file')}:{c.get('path') or c.get('expr')} "
                            f"({type(e).__name__}: {e})")
                continue
            if got != c["is"]:
                errs.append(f"pin {pid}: {c['file']}:{c.get('path') or c.get('expr')} is {got!r}, the wording states "
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
                neg = bool(NEG.search(ph))
                if pol == "neg" and not neg:
                    errs.append(f"pin {pid} {doc}: {ph!r} states no negation but its result is negative")
                if pol == "pos" and neg:
                    errs.append(f"pin {pid} {doc}: {ph!r} carries a negation but its result is positive")
    for doc in cfg.get("docs") or []:
        text = text_of(doc)
        if text is None:
            if not _skippable(doc):
                errs.append(f"pins: document {doc} missing")
            continue
        spans = covered_spans(cfg, doc, text)
        for a in (cfg.get("allow") or {}).get(doc) or []:
            if a["phrase"] not in text:
                errs.append(f"pins {doc}: allowlisted phrase {a['phrase']!r} not found (remove it)")
        for i, j, w, name in guard_matches(cfg, text):
            if any(a <= i and j <= b for a, b in spans):
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
            f"phrases), {len(cfg.get('guards') or {})} guards over {len(cfg.get('docs') or [])} documents")


def uncovered(cfg: dict | None = None, root: Path = ROOT) -> list[str]:
    cfg = config() if cfg is None else cfg
    out = []
    for doc in cfg.get("docs") or []:
        text = _doc_text(doc, None, root)
        if text is None:
            continue
        spans = covered_spans(cfg, doc, text)
        for i, j, w, name in guard_matches(cfg, text):
            if not any(a <= i and j <= b for a, b in spans):
                line = text.count("\n", 0, i) + 1
                ls, le = text.rfind("\n", 0, i) + 1, text.find("\n", j)
                out.append(f"{doc}:{line} [{name}] {w!r}: {text[max(ls, i - 90):(le if le >= 0 else len(text))][:220]}")
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["uncovered"]:
        for x in uncovered():
            print(x)
        return 0
    errs = check()
    for e in errs:
        print("PIN FAIL", e)
    print(f"pins: {summary()}, {len(errs)} failing")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
