"""Per-parliament converter coverage, from committed files only:

For every body of the feasibility matrix (results/census/matrix.json) and every body a test sampled, its converter
status, best first:

  frozen rules     the deterministic DE/FR/IT answer-date rules were written on its documents
                   (data/convert/rules_coverage.json `bodies_with_rules`)
  source adapter   no frozen rules, but a model-free source adapter reads its answers for the repair lists
                   (results/repair/adapters/adapters_<BODY>.json); the converter itself runs with no_rules_for_body and
                   needs_review, or Apertus in review mode
  metadata only    neither: the converter reads OPD's metadata and flags every document value for review

and the tests whose committed samples include it (P1 data/gold/heldout_docs.jsonl, P2 data/gold2/p2_docs.jsonl,
P3 data/gold3, P3b data/gold5, P4 data/gold4 meetings, P5 data/gold6, P6 data/p6, P7 data/p7/test_key.jsonl,
P8 data/p8, federal cell data/fed), and whether its affairs are among the validated schema v0.2 records (P3, P3b, P5,
P8 and the federal cell).

    PYTHONPATH=src:. python -m report.converter_coverage
        -> results/convert/coverage_by_parliament.json, docs/converter-coverage.md
"""
from __future__ import annotations

import csv
import gzip
import json

from gegenprobe.paths import DATA, RESULTS, ROOT

OUT = RESULTS / "convert" / "coverage_by_parliament.json"
DOC = ROOT / "docs" / "converter-coverage.md"
STATUSES = ("frozen rules", "source adapter", "metadata only")
TESTS = {
    "P1": [DATA / "gold" / "heldout_docs.jsonl"],
    "P2": [DATA / "gold2" / "p2_docs.jsonl"],
    "P3": [DATA / "gold3" / "p3_affairs.jsonl"],
    "P3b": [DATA / "gold5" / "p3b_affairs.jsonl"],
    "P4": [DATA / "gold4" / "p4_heldout_meetings.jsonl", DATA / "gold4" / "p4_transfer_meetings.jsonl"],
    "P5": [DATA / "gold6" / "p5_affairs.jsonl"],
    "P6": [DATA / "p6" / "p6_docs.jsonl"],
    "P7": [DATA / "p7" / "test_key.jsonl"],
    "P8": [DATA / "p8" / "p8_affairs.jsonl"],
    "federal": [DATA / "fed" / "fed_affairs.jsonl"],
}
V0_2 = ("P3", "P3b", "P5", "P8", "federal")  # sets whose affairs are validated schema v0.2 records


def _bodies_of(paths) -> set[str]:
    out = set()
    for p in paths:
        for line in open(p, encoding="utf-8"):
            if line.strip():
                out.add(str(json.loads(line)["body"]))
    return out


def _names() -> dict[str, dict]:
    with gzip.open(DATA / "census" / "bodies.tsv.gz", "rt", encoding="utf-8") as f:
        return {r["key"]: r for r in csv.DictReader(f, delimiter="\t")}


def build() -> dict:
    matrix = json.loads((RESULTS / "census" / "matrix.json").read_text(encoding="utf-8"))
    in_matrix = {c["body"] for c in matrix["cells"]}
    tests = {t: _bodies_of(ps) for t, ps in TESTS.items()}
    bodies = sorted(in_matrix.union(*tests.values()))
    rules = set(json.loads((DATA / "convert" / "rules_coverage.json").read_text(encoding="utf-8"))["bodies_with_rules"])
    adapters = set(json.loads((RESULTS / "repair" / "adapters" / "adapters_summary.json").read_text(
        encoding="utf-8"))["bodies"])
    names = _names()
    rows = []
    for b in bodies:
        status = "frozen rules" if b in rules else "source adapter" if b in adapters else "metadata only"
        meta = names.get(b, {})
        tested = [t for t in TESTS if b in tests[t]]
        rows.append(dict(body=b, name=meta.get("name") or b, type=meta.get("type"), canton=meta.get("canton") or None,
                         lang=meta.get("lang") or None, in_matrix=b in in_matrix, status=status, adapter=b in adapters,
                         tests=tested,
                         v0_2_records=any(t in V0_2 for t in tested)))
    by_status = {s: [r["body"] for r in rows if r["status"] == s] for s in STATUSES}
    summary = dict(
        bodies=len(rows),
        bodies_in_matrix=len(in_matrix),
        by_status={s: len(v) for s, v in by_status.items()},
        adapters_total=len(adapters),
        adapters_in_matrix=sum(r["adapter"] for r in rows),
        tested=sum(bool(r["tests"]) for r in rows),
        tested_by_status={s: sum(bool(r["tests"]) for r in rows if r["status"] == s) for s in STATUSES},
        v0_2_parliaments=sum(r["v0_2_records"] for r in rows),
        per_test={t: len(tests[t]) for t in TESTS},
    )
    return dict(
        label="Converter coverage per parliament (descriptive; committed files only)",
        definitions={
            "frozen rules": "the deterministic answer-date rules were written on this parliament's documents "
                            "(data/convert/rules_coverage.json)",
            "source adapter": "no frozen rules; a model-free source adapter reads its answers for the repair lists "
                              "(results/repair/adapters/); the converter marks its documents no_rules_for_body and "
                              "needs_review",
            "metadata only": "no frozen rules and no adapter: the converter reads OPD's metadata; document values go to "
                             "review",
            "tests": "pre-registered tests (P1-P8) and the exploratory federal cell whose committed samples include it",
            "v0_2_records": "its affairs are among the validated schema v0.2 records (P3, P3b, P5, P8, federal cell)",
        },
        summary=summary, by_status=by_status, rows=rows,
        command="PYTHONPATH=src:. python -m report.converter_coverage")


def markdown(d: dict) -> str:
    s = d["summary"]
    lines = [
        "# Converter coverage per parliament",
        "",
        "Generated by `PYTHONPATH=src:. python -m report.converter_coverage` from committed files "
        "(`results/convert/coverage_by_parliament.json`). Status, best first: **frozen rules** (the deterministic "
        "answer-date rules were written on its documents, `data/convert/rules_coverage.json`); **source adapter** (no "
        "frozen rules; a model-free source adapter reads its answers for the repair lists, `results/repair/adapters/`; "
        "the converter marks its documents `no_rules_for_body` and `needs_review`); **metadata only** (the converter "
        "reads OPD's metadata, every document value goes to review). *Tests*: the pre-registered tests and the "
        "exploratory federal cell whose committed samples include the parliament; *v0.2*: its affairs are among the "
        "validated schema v0.2 records.",
        "",
        f"{s['bodies']} bodies: " + ", ".join(f"{s['by_status'][k]} {k}" for k in STATUSES)
        + f"; {s['tested']} appear in at least one test, {s['v0_2_parliaments']} in the validated v0.2 records.",
        "",
        "| body | name | level | status | tests | v0.2 |",
        "|---|---|---|---|---|---|",
    ]
    order = {k: i for i, k in enumerate(STATUSES)}
    for r in sorted(d["rows"], key=lambda r: (order[r["status"]], r["name"])):
        lines.append(f"| {r['body']} | {r['name']} | {r['type'] or ''} | {r['status']} | "
                     f"{', '.join(r['tests']) or '—'} | {'yes' if r['v0_2_records'] else '—'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    d = build()
    OUT.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    DOC.write_text(markdown(d), encoding="utf-8")
    print(json.dumps(d["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
