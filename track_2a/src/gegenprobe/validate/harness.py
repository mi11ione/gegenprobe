"""Behavioural tests every converter must pass, independent of how it decides.

A converter is any callable  converter(pages: list[str], field: str) -> Valued | TypedNull  (schema objects, or anything
with .kind / .value / .page / .char_start / .char_end). The converter workstream plugs its cascade in; these functions only
perturb the input and compare outputs.

self_deletion(converter, pages, field)
    Run once. If a value with a span comes back, blank the line holding the span and every other line holding a date that
    normalises to the same value (or matching `anchor`), then run again. PASS iff the field is now a typed null: a converter
    that still answers is producing the value from somewhere other than its anchor (misattribution).
distractor(converter, pages, field)
    Append footer/edit-date lines ("Letzte Bearbeitung: …", "Dernière modification: …", "Ultima modifica: …", print dates)
    with a date that occurs nowhere in the document to every page. PASS iff the distractor date is never chosen and the
    decision (value or null, and the value itself) is unchanged.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field as dc_field

from .dates import find_dates

FOOTERS = {
    "de": ["Letzte Bearbeitung: {d} | Version: 3 | Dok.-Nr.: 000000", "Gedruckt am {d}"],
    "fr": ["Dernière modification: {d} | Version: 3 | Doc. n° 000000", "Imprimé le {d}"],
    "it": ["Ultima modifica: {d} | Versione: 3 | Doc. n. 000000", "Stampato il {d}"],
}
_FMT = {"de": "{d:02d}.{m:02d}.{y}", "fr": "{d:02d}.{m:02d}.{y}", "it": "{d:02d}.{m:02d}.{y}"}


@dataclass
class HarnessResult:
    test: str
    field: str
    result: str               # pass | fail | skipped
    before: str
    after: str
    detail: str = ""
    deleted_lines: list[str] = dc_field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def _show(v) -> str:
    if v is None:
        return "None"
    if getattr(v, "kind", None) == "null":
        return f"null({v.null_reason})"
    val = v.value.isoformat() if isinstance(v.value, dt.date) else str(v.value)
    return f"{val}@p{v.page}:{v.char_start}-{v.char_end}" if v.page else val


def _norm_value(v) -> str | None:
    if v is None or getattr(v, "kind", None) != "value":
        return None
    return v.value.isoformat() if isinstance(v.value, dt.date) else str(v.value)


def _blank_lines(text: str, pred) -> tuple[str, list[str]]:
    out, gone = [], []
    for line in text.split("\n"):
        if pred(line):
            gone.append(line)
            out.append("")
        else:
            out.append(line)
    return "\n".join(out), gone


def self_deletion(converter, pages: list[str], field: str, anchor: str | None = None) -> HarnessResult:
    before = converter(pages, field)
    if getattr(before, "kind", None) != "value" or getattr(before, "page", None) is None:
        return HarnessResult("self_deletion", field, "skipped", _show(before), "", "no span-bearing value to delete")
    target = _norm_value(before)
    page_text = pages[before.page - 1]
    ls = page_text.rfind("\n", 0, before.char_start) + 1
    le = page_text.find("\n", before.char_end)
    span_line = page_text[ls: le if le >= 0 else len(page_text)]
    rx = re.compile(anchor) if anchor else None

    def pred(line: str) -> bool:
        if line == span_line and line.strip():
            return True
        if rx and rx.search(line):
            return True
        return any(d["iso"] == target for d in find_dates(line)) or (target in line if not _is_iso(target) else False)

    new_pages, gone = [], []
    for t in pages:
        t2, g = _blank_lines(t, pred)
        new_pages.append(t2)
        gone += g
    after = converter(new_pages, field)
    ok = getattr(after, "kind", None) == "null"
    return HarnessResult("self_deletion", field, "pass" if ok else "fail", _show(before), _show(after),
                         "" if ok else "value survived deletion of its anchor", [g[:120] for g in gone])


def _is_iso(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d\d-\d\d", s or ""))


def absent_date(pages: list[str], start: dt.date = dt.date(2031, 3, 19)) -> dt.date:
    """A plausible-looking date that occurs nowhere in the document."""
    present = {d["iso"] for t in pages for d in find_dates(t)}
    d = start
    while d.isoformat() in present:
        d += dt.timedelta(days=1)
    return d


def distractor(converter, pages: list[str], field: str, lang: str = "de", date: dt.date | None = None) -> HarnessResult:
    before = converter(pages, field)
    d = date or absent_date(pages)
    ds = _FMT[lang].format(d=d.day, m=d.month, y=d.year)
    lines = [f.format(d=ds) for f in FOOTERS[lang]]
    new_pages = [t.rstrip("\n") + "\n" + "\n".join(lines) + "\n" for t in pages]
    after = converter(new_pages, field)
    chose = _norm_value(after) == d.isoformat()
    same = _norm_value(before) == _norm_value(after) and getattr(before, "kind", None) == getattr(after, "kind", None)
    ok = not chose and same
    detail = "chose the footer date" if chose else ("" if same else "decision changed when a footer was added")
    return HarnessResult("distractor", field, "pass" if ok else "fail", _show(before), _show(after), detail)


def run_suite(converter, docs: dict[str, tuple[list[str], str]], field: str) -> list[dict]:
    """docs: name -> (pages, lang). Runs both tests on each document; returns flat records for report.summarise."""
    out = []
    for name, (pages, lang) in docs.items():
        for r in (self_deletion(converter, pages, field), distractor(converter, pages, field, lang=lang)):
            out.append(dict(doc=name, **r.as_dict()))
    return out
