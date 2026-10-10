"""Display numbers derived from committed results files for the round-2 wording (README / report / form notes), so
claims.tsv can trace every number those documents print. No model, no network.

    python -m report.r2_numbers   -> results/report/r2_numbers.json
"""
from __future__ import annotations

import gzip
import json

from gegenprobe.paths import RESULTS


def main() -> dict:
    ver = json.loads((RESULTS / "repair" / "be_verify_all.json").read_text())["by_action"]["relink"]
    v1, v2 = ver["v1_registered"], ver["v2"]
    with gzip.open(RESULTS / "census" / "interventions.tsv.gz", "rt", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
    out = dict(
        label="derived display numbers (round-2 wording); every value is a difference or count over a committed results file",
        bern_relink_n=v2["n"],
        bern_relink_date_registered_parser=v1["date_eq_event"],
        bern_relink_date_posthoc_parser=v2["date_eq_event"],
        bern_relink_to_review=v2["n"] - v2["date_eq_event"],
        dataset_columns=len(header),
    )
    (RESULTS / "report" / "r2_numbers.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
