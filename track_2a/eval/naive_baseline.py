"""The naive converter most teams ship: free-generation JSON from Apertus ("LLM reads PDF, outputs JSON").
Port of spikes/round7 S-NULL (spike7.py prompts, analyze_null.py definitions) generalised to DE/FR/IT.

Arms: plain (no abstention instruction) and null (abstention allowed + a verbatim receipt `beleg`), plus the
"pointer check" a careful team would add: accept a date only if `beleg` occurs verbatim (whitespace-normalised) in the
document and contains that date. The spike showed that check approves 10/15 wrong dates (footer "Letzte Bearbeitung").

Outcome per document for the answer date, against gold (ISO date or None):
  correct        value == gold (or in the lenient set)
  correct_null   null and gold null
  false_null     null but gold has a value
  misattributed  wrong value that occurs in the document as a date (copied from the wrong place, e.g. a footer)
  fabricated     wrong value that occurs nowhere in the document
Only free generation produces `fabricated`; the closed-set pointer cannot, by construction.
"""

from __future__ import annotations

import json
import re

from gegenprobe.convert import lattice
from gegenprobe.convert.pointer import doc_text
from gegenprobe.paths import PROMPTS

MON = {
    "de": ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"],
    "fr": [
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ],
    "it": [
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
    ],
}
NULLISH = {"", "null", "none", "nicht angegeben", "keine angabe", "unbekannt", "non indiqué", "non indicato", "n/a"}


def prompt(lang: str, arm: str, variant: str = "") -> str:
    lang = lang if lang in ("de", "fr", "it") else "de"
    return (PROMPTS / lang / f"naive_{arm}{('_' + variant) if variant else ''}.txt").read_text(encoding="utf-8")


def parse(g: str) -> dict:
    s = re.sub(r"^```(json)?|```$", "", (g or "").strip()).strip()
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    d = {}
    for k in ("antwort_datum", "rrb_nr", "beschluss_nr", "antwort_zusammenfassung", "beleg"):
        m = re.search(rf'"{k}"\s*:\s*(null|"((?:[^"\\]|\\.)*)")', s)
        if m:
            d[k] = None if m.group(1) == "null" else m.group(2)
    return d


def isnull(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in NULLISH)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def to_iso(v) -> str | None:
    """Accept ISO or any lattice-parsable date string from the model."""
    if isnull(v):
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s[:10]):
        return s[:10]
    c = lattice.dates([s])
    return c[0]["value"] if c else "unparseable:" + s[:40]


def date_forms(iso: str) -> set[str]:
    y, m, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    f = {f"{d:02d}.{m:02d}.{y}", f"{d}.{m}.{y}", iso}
    for names in MON.values():
        f |= {f"{d}. {names[m - 1]} {y}", f"{d:02d}. {names[m - 1]} {y}", f"{d} {names[m - 1]} {y}"}
    return f


def receipt_ok(o: dict, text: str) -> bool:
    """The naive 'pointer check': quote verbatim in the document and containing the claimed date."""
    iso, b = to_iso(o.get("antwort_datum")), o.get("beleg")
    if iso is None or iso.startswith("unparseable") or isnull(b):
        return False
    nb = norm(b)
    return nb in norm(text) and any(f in nb for f in date_forms(iso))


def outcome(pred: str | None, gold: str | None, doc_dates: set[str], lenient: list | None = None) -> str:
    ok = {gold} | set(lenient or []) if gold else set()
    if pred is None:
        return "correct_null" if gold is None else "false_null"
    if pred in ok:
        return "correct"
    return "misattributed" if pred in doc_dates else "fabricated"


def run_doc(backend, pages: list[str], lang: str, arm: str, variant: str = "", seed: int = 0) -> dict:
    text, _, trunc = doc_text(pages)
    g = backend.generate(prompt(lang, arm, variant).replace("{doc}", text), max_tokens=200, seed=seed)
    o = parse(g)
    return dict(
        arm=arm,
        gen=g,
        parsed=o,
        date=to_iso(o.get("antwort_datum")),
        number=o.get("beschluss_nr", o.get("rrb_nr")),
        receipt_ok=receipt_ok(o, text),
        truncated=trunc,
        seed=seed,
        model_build=getattr(backend, "build", "?"),
    )


def score(rows: list[dict]) -> dict:
    """rows: {pred, gold, doc_dates, lenient, receipt_ok}. Returns counts per outcome, and the receipt-check view."""
    c: dict = {
        k: 0
        for k in (
            "correct",
            "correct_null",
            "false_null",
            "misattributed",
            "fabricated",
            "invented_on_null_docs",
            "invented_passing_receipt_check",
        )
    }
    c["n_gold_null"] = sum(r["gold"] is None for r in rows)
    for r in rows:
        o = outcome(r["pred"], r["gold"], set(r["doc_dates"]), r.get("lenient"))
        c[o] = c.get(o, 0) + 1
        if r["gold"] is None and r["pred"] is not None:
            c["invented_on_null_docs"] = c.get("invented_on_null_docs", 0) + 1
            c["invented_passing_receipt_check"] = c.get("invented_passing_receipt_check", 0) + bool(r.get("receipt_ok"))
    c["n"] = len(rows)
    return c
