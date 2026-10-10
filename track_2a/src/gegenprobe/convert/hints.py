"""Unlocked hints next to the frozen rules (convert/rules.py stays as pre-registered). A hint never fills a field: it moves
one date to the front of the candidates with a `suggested_by_*` mark and flags the field for review.

letter_line_date  A common Swiss letter layout of a government answer: an address block to the parliament ("An den
                  Kantonsrat", "An die Mitglieder des Grossen Rates", "Au Grand Conseil", "Al Gran Consiglio", ...) and
                  directly under it the place-date line ("Schaffhausen, 21. Dezember 2021"). The frozen place-date rule
                  only fires on a document with an executive answer heading ("Antwort des Regierungsrates", ...), so on
                  this layout it is never tried. Addressees that name an executive in some places (Gemeinderat, Stadtrat,
                  Conseil communal / municipal) are not used, and nor is "An den Regierungsrat" (a member's own text,
                  dated on submission).
"""
from __future__ import annotations

import re

from . import rules

_RAT = r"(?:Kantonsrat|Grossen?\s+Rat|Grosser\s+Rat|Landrat|Einwohnerrat)(?:e?s)?"
ADDRESS = re.compile(
    r"^[ \t]*(?:"
    r"An\s+(?:den|die|das)\s+(?:Mitglieder\s+des\s+)?" + _RAT +
    r"|Au\s+Grand\s+Conseil|Aux\s+(?:membres|d[ée]put[ée]e?s)\s+du\s+Grand\s+Conseil|Au\s+Conseil\s+g[ée]n[ée]ral"
    r"|Al\s+Gran\s+Consiglio|Ai\s+(?:membri|deputati)\s+del\s+Gran\s+Consiglio|Al\s+Consiglio\s+comunale"
    r")\b",
    re.M | re.I,
)
PLACE_DATE = dict(rules.DISPATCH)["place_date"]
HEAD = 4000  # the address block sits in the letterhead
WINDOW = 400  # the place-date line follows the address block within this many characters


def letter_line_date(pages: list[str]) -> dict | None:
    """-> {value, page, char_start, char_end, quote, address} for the first place-date line under a letter address to the
    parliament on the first two pages, or None."""
    for pi, t in enumerate(pages[:2], start=1):
        for a in ADDRESS.finditer(t, 0, min(len(t), HEAD)):
            for m in PLACE_DATE.finditer(t, a.end(), min(len(t), a.end() + WINDOW)):
                ln = rules._line(t, m.start("date"))
                if rules.FOOTER.search(ln) or rules.SUBMISSION.search(ln):
                    continue
                v = rules._date_of(m)
                if v:
                    s, e = m.span("date")
                    return dict(value=v, page=pi, char_start=s, char_end=e, quote=re.sub(r"\s+", " ", ln.strip())[:200],
                                address=re.sub(r"\s+", " ", a.group(0).strip()))
    return None


def check() -> dict:
    """POST-HOC: where the letter-line hint fires on the committed gold documents (P1 dev + held-out, P2), from the local
    text cache. In the converter it is tried only when the rules found no answer heading (rule `no_anchor`).
    -> results/convert/letter_hint_check.json"""
    import json

    from .. import pdftext
    from ..paths import DATA, RESULTS

    sets = (("P1 dev", DATA / "gold" / "dev_docs.jsonl"), ("P1 held-out", DATA / "gold" / "heldout_docs.jsonl"),
            ("P2", DATA / "gold2" / "p2_docs.jsonl"))
    out = dict(label="POST-HOC (round 5): letter-line hint (convert/hints.py) on the committed gold documents; the hint "
                     "never fills a field", sets={})
    for name, path in sets:
        r = dict(documents=0, no_text=0, no_anchor=0, fired=[])
        for d in map(json.loads, open(path, encoding="utf-8")):
            try:
                pages = pdftext.extract(d["sha256"], ocr=bool(d.get("image_only")))["pages"]
            except Exception:  # not in the local cache
                r["no_text"] += 1
                continue
            r["documents"] += 1
            if rules.answer_date(pages).get("rule") != "no_anchor":
                continue
            r["no_anchor"] += 1
            h = letter_line_date(pages)
            if h:
                r["fired"].append(dict(doc_id=d["doc_id"], body=d.get("body"), value=h["value"], address=h["address"]))
        out["sets"][name] = r
    out["fired_total"] = sum(len(r["fired"]) for r in out["sets"].values())
    out["documents_total"] = sum(r["documents"] for r in out["sets"].values())
    (RESULTS / "convert" / "letter_hint_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["check"]:
        r = check()
        print({k: {kk: (vv if not isinstance(vv, list) else len(vv)) for kk, vv in v.items()} for k, v in r["sets"].items()})
