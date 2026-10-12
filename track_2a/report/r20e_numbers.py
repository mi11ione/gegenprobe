"""Numbers the R20 docs pass states that are differences or sums of committed results (claims.tsv reads JSON paths and
ratios only), derived only from committed files. No network, no model.

  * p2_lead:    the pointer's lead over the strongest model-free rule tried on P2 (post hoc, proposed in review;
                results/eval/p2_posthoc_composite.json): exact documents and answer dates found, pointer minus rule;
  * provenance: the converter's values whose source is a record (an OPD record or another committed table), not a span
                (results/schema/v0_2/field_completeness.json provenance);
  * date_roles: the converter's answer dates that stay `answered` because no role is printed at the date
                (results/schema/v0_2/validation_all.json answer_date_roles: not at an anchor + an unlabelled date line).

    PYTHONPATH=src:. python -m report.r20e_numbers   -> results/report/r20e_numbers.json
"""
from __future__ import annotations

import json

from gegenprobe.paths import RESULTS

OUT = RESULTS / "report" / "r20e_numbers.json"


def _j(p):
    return json.loads(p.read_text(encoding="utf-8"))


def p2_lead() -> dict:
    c = _j(RESULTS / "eval" / "p2_posthoc_composite.json")["arms"]
    ptr, rule = c["pointer"], c["composite"]
    return dict(exact_docs=ptr["exact"] - rule["exact"], n_docs=ptr["n"],
                answer_dates=ptr["value_recall"][0] - rule["value_recall"][0], n_answered=ptr["value_recall"][1])


def date_roles() -> dict:
    r = _j(RESULTS / "schema" / "v0_2" / "validation_all.json")["answer_date_roles"]
    src = r["by_source"]
    return dict(no_role_printed=src["answered:not_at_anchor"] + src["answered:unlabelled_date_line"])


def provenance() -> dict:
    k = _j(RESULTS / "schema" / "v0_2" / "field_completeness.json")["provenance"]["groups"]["converter"]["kinds"]
    return dict(converter_source_record=k["opd_record"] + k["other_record"])


def main() -> dict:
    out = dict(label="R20 docs pass: differences and sums of committed results (post hoc where their inputs are)",
               p2_lead=p2_lead(), date_roles=date_roles(), provenance=provenance())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(OUT)
    return out


if __name__ == "__main__":
    main()
