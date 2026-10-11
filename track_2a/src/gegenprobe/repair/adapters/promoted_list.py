"""The P7 promoted tier in the adapter lists' own columns.

results/repair/adapters/p7/promoted.tsv is the registered output of the P7 queue run (adjudicate.py, frozen by LOCK8) and
keeps its own columns. This module writes the same 214 rows in the column layout of results/repair/adapters/
adapters_<BODY>.tsv (run.LIST_COLS), so that one reader handles both files:

    python -m gegenprobe.repair.adapters.promoted_list    -> results/repair/adapters/p7/promoted_by_apertus.tsv

Each promoted row is its parliament's adapter-list row (tier review: the adapters' own check did not pass), with
  tier             promoted_by_apertus
  counted          false (the apply filter stays counted=true; this tier is a pre-sorted batch for a reviewer)
  verified         false
  action           review (as in the adapter list, so counted / verified / action != review keep meaning the same)
  proposed_action  the adapter's proposed action (tag_answer, extract_tag, fetch)
  source_url, target_category, target_category_note, text_sha256, opd_doc_id, ...: from the adapter-list row
and P7's own columns appended (p7_answer_date, p7_date_tier, p7_date_class, p7_span_char_start, p7_span_char_end,
p7_span_line, p7_m_yes, p7_m_none, p7_prompt_is_answer, p7_prompt_date, p7_model). A promoted row that does not join to
a review row of its adapter list on (affair_id, opd_doc_id, text_sha256) stops the script.
"""
from __future__ import annotations

import csv
import sys

from . import adjudicate as J
from . import lists, run

OUT = J.OUT / "promoted_by_apertus.tsv"
P7_COLS = ["answer_date", "date_tier", "date_class", "span_char_start", "span_char_end", "span_line", "m_yes", "m_none",
           "prompt_is_answer", "prompt_date", "model"]
COLS = run.LIST_COLS + [f"p7_{c}" for c in P7_COLS]


def _tsv(p) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def build(src=None, lists_dir=None) -> list[dict]:
    src = src or J.OUT / "promoted.tsv"
    lists_dir = lists_dir or lists.OUT
    cache: dict[str, dict] = {}
    out = []
    for r in _tsv(src):
        b = r["body"]
        if b not in cache:
            cache[b] = {x["affair_id"]: x for x in _tsv(lists_dir / f"{lists.PREFIX}{b}.tsv")}
        a = cache[b].get(r["affair_id"])
        if a is None or a["tier"] != "review" or (a["opd_doc_id"], a["text_sha256"]) != (r["opd_doc_id"], r["text_sha256"]):
            raise SystemExit(f"promoted row {b}/{r['affair_id']} does not join to a review row of its adapter list")
        row = {c: a.get(c, "") for c in run.LIST_COLS}
        row.update(tier=J.TIER, counted="false", verified="false", action="review",
                   proposed_action=r["proposed_action"] or a["proposed_action"])
        row.update({f"p7_{c}": r.get(c, "") for c in P7_COLS})
        out.append(row)
    return out


def write(rows: list[dict], path=OUT) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    rows = build()
    write(rows)
    print(f"{OUT}: {len(rows)} rows ({J.TIER}, counted=false, adapter-list columns + {len(P7_COLS)} p7_ columns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
