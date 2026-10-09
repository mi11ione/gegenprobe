"""README samples: trimmed, provenance-annotated converter outputs copied from a `make run` convert step
(out/convert_samples/*.json, or GP_OUT/convert_samples) into docs/samples/. Dev documents only (never held-out).

    python -m report.samples [convert_samples_dir]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from gegenprobe.paths import DOCS, ROOT

PICK = {
    "be_rrb_rule": "be_2024_RRGR_91_rrb",          # BE government decision, relinked canton document: rule route with span
    "ti_answer_rule_and_pointer": "it_canton_answer_110047",  # TI answer: rule value; Apertus pointer agrees (replayed scores)
    "ti_question_typed_null": "it_canton_intervention_166615",  # TI question as lodged: typed null; pointer abstains
}


def trim(d: dict) -> dict:
    casc = d.get("answer_date") or {}
    rules = d["rules"]
    doc = rules["doc"]
    out = {
        "document": {k: doc[k] for k in ("doc_id", "url", "sha256", "language", "n_pages", "extractor")},
        "answer_date_rules": {k: v for k, v in rules["answer_date"].items() if v is not None},
        "answer_date_cascade": {k: v for k, v in casc.items() if v is not None} if isinstance(casc, dict) else casc,
        "recommendation": {k: v for k, v in (rules.get("recommendation") or {}).items() if v is not None},
        "apertus_pointer": d.get("pointer_replay"),
        "checks": [{k: c[k] for k in ("check", "code")} for c in d["checks"]],
    }
    return out


def main(argv: list[str]) -> None:
    src = Path(argv[0]) if argv else ROOT / "out" / "convert_samples"
    dst = DOCS / "samples"
    dst.mkdir(parents=True, exist_ok=True)
    for name, f in PICK.items():
        d = json.loads((src / f"{f}.json").read_text())
        (dst / f"{name}.json").write_text(json.dumps(trim(d), indent=1, ensure_ascii=False) + "\n")
        print(dst / f"{name}.json")


if __name__ == "__main__":
    main(sys.argv[1:])
