"""Model-free candidate pre-extraction for the annotators (no labels, no rule predictions).

For every gold document: page count, extractor, the full date lattice (value, page, span, the line it sits on), the OPD
affair numbers found in it, and the lines that look like answer headings. The rules' own predictions are deliberately NOT
written to the sheet, so the labels are not anchored on the baseline they will be used to judge; they are kept apart in
WORK/gold/rules_hidden/ for the scorer.

usage: python -m eval.gold.candidates --split heldout|dev
Out: WORK/gold/candidates/<split>/<doc_id>.json and WORK/gold/<split>_label_sheet.tsv (one row per document to fill in)
"""

from __future__ import annotations

import argparse
import csv
import json
import re

from gegenprobe import pdftext
from gegenprobe.convert import lattice, rules
from gegenprobe.paths import DATA, WORK
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

SHEET_COLS = [
    "doc_id",
    "cell",
    "dtype_guess",
    "body",
    "url",
    "pages",
    "answer_present",
    "answer_date",
    "answer_date_page",
    "answer_date_quote",
    "role",
    "answer_date_lenient",
    "decision_number",
    "recommendation",
    "submitters_as_printed",
    "labeller",
    "notes",
]


def main(split: str) -> int:
    docs = [json.loads(line) for line in open(DATA / "gold" / f"{split}_docs.jsonl")]
    out = WORK / "gold" / "candidates" / split
    hidden = WORK / "gold" / "rules_hidden" / split
    out.mkdir(parents=True, exist_ok=True)
    hidden.mkdir(parents=True, exist_ok=True)
    try:
        idx = lattice.affair_index()
    except Exception:
        idx = {}
    n = 0
    with open(WORK / "gold" / f"{split}_label_sheet.tsv", "w", newline="", encoding="utf-8") as fsheet:
        w = csv.DictWriter(fsheet, SHEET_COLS, delimiter="\t")
        w.writeheader()
        for d in docs:
            t = pdftext.extract(d["sha256"])
            pages = t["pages"]
            heads = [
                dict(page=pi, line=re.sub(r"\s+", " ", m.group(0)).strip()[:120])
                for pi, p in enumerate(pages, start=1)
                for m in rules.ANSWER_HEADING.finditer(p)
            ]
            cand = dict(
                doc_id=d["doc_id"],
                sha256=d["sha256"],
                extractor=t["extractor"],
                pages=len(pages),
                image_only=t["image_only"],
                dates=[
                    {k: c[k] for k in ("value", "page", "char_start", "char_end", "raw", "line")} for c in lattice.dates(pages)
                ],
                affair_numbers=[
                    {k: c[k] for k in ("value", "page", "char_start", "char_end")}
                    for c in lattice.affair_numbers(pages, d["body"], idx)
                ],
                heading_lines=heads,
            )
            (out / f"{d['doc_id']}.json").write_text(json.dumps(cand, ensure_ascii=False, indent=1))
            (hidden / f"{d['doc_id']}.json").write_text(
                json.dumps(
                    dict(
                        answer_date=rules.answer_date(pages, t["image_only"]),
                        recommendation=rules.recommendation(pages, d.get("affair_type")),
                    ),
                    ensure_ascii=False,
                )
            )
            w.writerow(
                dict(doc_id=d["doc_id"], cell=d["cell"], dtype_guess=d["dtype"], body=d["body"], url=d["url"], pages=len(pages))
            )
            n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="heldout")
    print("candidates written:", main(ap.parse_args().split))
