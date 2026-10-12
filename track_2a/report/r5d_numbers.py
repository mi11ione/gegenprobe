"""Display-ready numbers for the docs pass, derived only from committed files, so claims.tsv can trace them:

  * the census at a glance (Bern 2024-25 answers in OPD but unlinked = agenda + parentless, from
    results/evidence/parliaments.csv);
  * the independent-annotator check (how many of the 7 P1-H1 values fall on documents OPD types as reports; the number of
    listed disagreements per test) from results/eval/posthoc_r5_independent_gold.json;
  * the pointer vs the ungated latest printed date on P2's answered documents, p rounded half up (0.625 -> "0.63");
  * the parallel layout in the served build's fingerprint (results/eval/served_models.json), the basis of the inference
    that Public AI's `swiss-ai/apertus-v1.5-8b` name serves the 70B weights.

    PYTHONPATH=src:. python -m report.r5d_numbers   -> results/report/r5d_numbers.json
"""
from __future__ import annotations

import csv
import json
import re
from decimal import ROUND_HALF_UP, Decimal

from gegenprobe.paths import ROOT, RESULTS


def census() -> dict:
    rows = {r["key"]: r for r in csv.DictReader(open(ROOT / "results" / "evidence" / "parliaments.csv", encoding="utf-8"))}
    be = rows["BE"]
    return dict(be_y2425_unlinked=int(be["y2425_agenda"]) + int(be["y2425_parentless"]),
                be_y2425_agenda=int(be["y2425_agenda"]), be_y2425_parentless=int(be["y2425_parentless"]))


def gold() -> dict:
    d = json.loads((RESULTS / "eval" / "posthoc_r5_independent_gold.json").read_text())
    seven = d["p1_h1_j2_recompute"]["the_7_committed"]
    return dict(h1_values=len(seven), h1_values_on_reports=sum(x["dtype"] == "report" for x in seven),
                p1_disagreements=len(d["p1"]["agreement"]["disagreements"]),
                p2_disagreements=len(d["p2"]["agreement"]["disagreements"]))


def p2() -> dict:
    c = json.loads((RESULTS / "eval2" / "posthoc_r5_p2_table.json").read_text())["comparisons"]
    x = c["70b_pointer_vs_latest_printed_date_answered_29"]
    return dict(ptr_vs_latest_29_p=str(Decimal(str(x["p"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                ptr_vs_latest_29=f"{x['a_only']} vs {x['b_only']}")


def served() -> dict:
    d = json.loads((RESULTS / "eval" / "served_models.json").read_text())
    fps = sorted({fp for v in d["recorded_in_results_files"].values() for fp in v})
    layouts = sorted({m.group(0) for fp in fps for m in [re.search(r"tp\d+-pp\d+", fp)] if m})
    return dict(fingerprints=fps, layouts=layouts, layout=layouts[0] if len(layouts) == 1 else None)


def main() -> None:
    out = dict(label="docs pass: display numbers derived from committed files (no new measurement)",
               census=census(), gold=gold(), p2=p2(), served=served())
    p = RESULTS / "report" / "r5d_numbers.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(p)


if __name__ == "__main__":
    main()
