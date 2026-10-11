"""POST HOC breadth table: P1 and P2 answer-date results by language x level x born-digital/scanned, from committed files.

    python -m eval.breadth            write results/eval/breadth_p1_p2.json
    python -m eval.breadth --check    exit 1 if a fresh run differs from the committed file

No network, no model. Inputs (all committed):
  results/eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json   P1 per-document predictions (rules, pointer, cascade)
  results/eval2/p2__publicai_swiss-ai_apertus-v1.5-8b.json       P2 per-document predictions (same arms)
  data/gold/heldout_docs.jsonl, data/gold2/p2_docs.jsonl          per-document metadata

What decides each attribute:
  language  the stratum `cell` of the seeded draw (de_/fr_/it_ prefix; ocr_ti = Ticino, Italian). OPD's `lang` tag is
            empty on most documents, so the stratum is the record of the language.
  level     the stratum `cell` (_canton/_commune suffix; ocr_ti = canton Ticino); P2's `level` field agrees on all 62.
  scanned   `extractor` starts with "tesseract" and `image_only` is true (OCR); every other document is born-digital
            (pdftotext). In both sets this coincides with the ocr_ti stratum (asserted).

Each cell is re-scored here with the frozen scorer (eval/score.py, strict) from the per-document values and asserted
equal to the per-cell counts the results files already carry, so the table adds a view, not a new measurement.
"""
from __future__ import annotations

import json
import sys

from eval.score import summarise
from gegenprobe.paths import ROOT

OUT = ROOT / "results" / "eval" / "breadth_p1_p2.json"
SETS = {
    "P1": ("results/eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json", "data/gold/heldout_docs.jsonl"),
    "P2": ("results/eval2/p2__publicai_swiss-ai_apertus-v1.5-8b.json", "data/gold2/p2_docs.jsonl"),
}
ARMS = ("rules", "pointer", "cascade")
LANG = {"de": "DE", "fr": "FR", "it": "IT"}


def attributes(doc: dict) -> dict:
    cell = doc["cell"]
    scanned = doc["extractor"].startswith("tesseract") and bool(doc["image_only"])
    if cell == "ocr_ti":
        lang, level = "IT", "canton"
    else:
        lg, level = cell.split("_")
        lang = LANG[lg]
    if "level" in doc:
        assert doc["level"] == level, (doc["doc_id"], doc["level"], level)
    assert scanned == (cell == "ocr_ti"), (doc["doc_id"], cell, doc["extractor"])
    return dict(language=lang, level=level, source="scanned (OCR)" if scanned else "born-digital")


def _jsonl(rel: str) -> dict[int, dict]:
    return {d["doc_id"]: d for d in map(json.loads, (ROOT / rel).read_text(encoding="utf-8").splitlines()) if d}


def build() -> dict:
    out = dict(
        label="POST HOC (not pre-registered): P1/P2 answer-date results per stratum, re-scored from committed predictions",
        command="PYTHONPATH=src:. python -m eval.breadth",
        attributes=dict(language="stratum cell prefix (ocr_ti = Italian)", level="stratum cell suffix (ocr_ti = canton)",
                        scanned="extractor tesseract and image_only true (= stratum ocr_ti)"),
        sets={},
    )
    for name, (res_rel, docs_rel) in SETS.items():
        res, docs = json.loads((ROOT / res_rel).read_text(encoding="utf-8")), _jsonl(docs_rel)
        attrs = {r["doc_id"]: attributes(docs[r["doc_id"]]) for r in res["per_doc"]}
        cells = {}
        for arm in ARMS:
            rows = [dict(cell=r["cell"], pred=(r[arm] or {}).get("value"), gold=r["gold"], doc_dates=r["doc_dates"])
                    for r in res["per_doc"]]
            s = summarise(rows)
            for cell, v in s.items():
                stored = res["arms"][arm]["strict"][cell]
                assert (v["exact"], v["n"], v["correct"]) == (stored["exact"], stored["n"], stored["correct"]), (name, arm, cell)
                c = cells.setdefault(cell, dict(n=v["n"], n_answered=v["n_gold_value"], n_answerless=v["n_gold_null"]))
                c[arm] = dict(exact=v["exact"], found=v["correct"], answerless_dated=v["invented_on_null"])
        for cell, c in cells.items():
            if cell != "ALL":
                a = {attrs[r["doc_id"]]["language"] + attrs[r["doc_id"]]["level"] + attrs[r["doc_id"]]["source"]
                     for r in res["per_doc"] if r["cell"] == cell}
                assert len(a) == 1, (name, cell, a)
                c.update(next(attrs[r["doc_id"]] for r in res["per_doc"] if r["cell"] == cell))
                c["bodies"] = sorted({str(docs[r["doc_id"]]["body"]) for r in res["per_doc"] if r["cell"] == cell})
        by: dict = {}
        for attr in ("language", "level", "source"):
            for cell, c in cells.items():
                if cell == "ALL":
                    continue
                g = by.setdefault(attr, {}).setdefault(c[attr], dict(n=0, n_answered=0, n_answerless=0))
                for k in ("n", "n_answered", "n_answerless"):
                    g[k] += c[k]
                for arm in ARMS:
                    ga = g.setdefault(arm, dict(exact=0, found=0, answerless_dated=0))
                    for k in ga:
                        ga[k] += c[arm][k]
            by[attr] = dict(sorted(by[attr].items()))
        cells["ALL"]["bodies"] = sorted({str(docs[r["doc_id"]]["body"]) for r in res["per_doc"]})
        for c in cells.values():
            c["n_parliaments"] = len(c["bodies"])
        out["sets"][name] = dict(results=res_rel, docs=docs_rel, cells=dict(sorted(cells.items())), by=by)
    return out


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str]) -> int:
    s = render()
    if "--check" in argv:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == s
        print("breadth:", "committed file current" if ok else "differs")
        return 0 if ok else 1
    OUT.write_text(s, encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
