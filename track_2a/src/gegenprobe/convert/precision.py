"""Reviewer aids measured on the pre-registered evaluations (POST-HOC summaries of committed per-document rows; no model
call, no new labels). They tell a reviewer how far to trust a value before checking it.

  rule precision   per rule id: rule-decided values correct / rule-decided values, P1 held-out + P2 unseen parliaments
  band precision   review suggestions by confidence band of the null margin: correct / suggestions, P1 + P2
  rules coverage   which parliaments the rules were written on (their layouts are known) and which are not

    python -m gegenprobe.convert.precision   -> results/convert/{rule_precision,band_precision}.json,
                                                 data/convert/rules_coverage.json
"""
from __future__ import annotations

import collections
import json
from functools import lru_cache

from ..paths import DATA, RESULTS
from ..stats import wilson

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
SOURCES = {"P1": RESULTS / "eval" / f"heldout__{BUILD}.json", "P2": RESULTS / "eval2" / f"p2__{BUILD}.json"}
RULE_FILE = RESULTS / "convert" / "rule_precision.json"
BAND_FILE = RESULTS / "convert" / "band_precision.json"
COVERAGE_FILE = DATA / "convert" / "rules_coverage.json"
STRONG = -5.0  # margin <= STRONG: the model clearly preferred a printed date over null
REC_VALUES = {"accept", "reject", "convert", "partial"}


def band(margin: float | None, theta: float | None) -> str | None:
    """'strong' (margin <= -5) | 'weak' (-5 < margin <= theta: the model leaned toward null but stayed under θ)."""
    if margin is None or theta is None or margin > theta:
        return None
    return "strong" if margin <= STRONG else "weak"


def _correct(value, row) -> bool:
    from eval.score import outcome
    return outcome(value, row["gold"], set(row.get("doc_dates") or []), row.get("lenient"), True) == "correct"


def _rows():
    for name, p in SOURCES.items():
        if p.exists():
            d = json.loads(p.read_text())
            for r in d["per_doc"]:
                yield name, d["theta"], r


def rule_precision() -> dict:
    by = collections.defaultdict(lambda: collections.Counter())
    for name, _, r in _rows():
        ru = r.get("rules") or {}
        if ru.get("status") == "value":
            c = by[("answer_date", ru["rule"])]
            c["n"] += 1
            c["correct"] += _correct(ru.get("value"), r)
            c[f"n_{name}"] += 1
            c[f"correct_{name}"] += _correct(ru.get("value"), r)
        rr = r.get("rec_rules") or {}
        if rr.get("status") == "value":
            c = by[("recommendation", rr["rule"])]
            ok = rr.get("value") == r.get("rec_gold") if r.get("rec_gold") in REC_VALUES else False
            c["n"] += 1
            c["correct"] += ok
            c[f"n_{name}"] += 1
            c[f"correct_{name}"] += ok
    out = {}
    for (field, rid), c in sorted(by.items()):
        lo, hi = wilson(c["correct"], c["n"])
        out.setdefault(field, {})[rid] = dict(correct=c["correct"], n=c["n"], ci=[round(lo, 3), round(hi, 3)],
                                              shown=f"{c['correct']}/{c['n']}",
                                              by_test={k: [c[f"correct_{k}"], c[f"n_{k}"]] for k in SOURCES if c[f"n_{k}"]})
    return dict(label="POST-HOC: per-rule precision of rule-decided values on the pre-registered held-out sets "
                      "(P1 154 docs, P2 62 docs; frozen rules, no new labels)", sources=[str(p.name) for p in SOURCES.values()],
                fields=out)


def band_precision() -> dict:
    c = collections.defaultdict(collections.Counter)
    for name, theta, r in _rows():
        ca = r.get("cascade") or {}
        if ca.get("route") != "apertus" or ca.get("value") is None:
            continue
        b = band(ca.get("margin"), theta)
        if b is None:
            continue
        ok = _correct(ca["value"], r)
        for key in (b, f"{b}_{name}"):
            c[key]["n"] += 1
            c[key]["correct"] += ok
            c[key]["on_answerless"] += r["gold"] is None
    out = {}
    for k, v in sorted(c.items()):
        lo, hi = wilson(v["correct"], v["n"])
        out[k] = dict(correct=v["correct"], n=v["n"], on_answerless=v["on_answerless"], ci=[round(lo, 3), round(hi, 3)],
                      shown=f"{v['correct']}/{v['n']}")
    return dict(label="POST-HOC: precision of Apertus review suggestions (cascade residue, frozen θ) by margin band",
                bands={"strong": f"margin <= {STRONG}", "weak": f"{STRONG} < margin <= theta (model leaned toward null)"},
                results=out)


def rules_coverage() -> dict:
    dev = [json.loads(x) for x in open(DATA / "gold" / "dev_docs.jsonl")]
    bodies = sorted({d["body"] for d in dev} | {"BE", "ZH", "BS"})  # + the spike items' bodies (BE, ZH, BS)
    rp = json.loads(RULE_FILE.read_text()) if RULE_FILE.exists() else rule_precision()
    return dict(
        bodies_with_rules=bodies,
        meaning=("The deterministic rules were written on documents of these parliaments; their layouts are known. For any "
                 "other parliament, route documents to review mode: on 15 parliaments the rules never saw (P2), the rules "
                 "found 2 of 29 answer dates and the Apertus pointer 24 of 29."),
        rule_precision={f: {rid: v["shown"] for rid, v in rules.items()} for f, rules in rp["fields"].items()},
        source="data/gold/dev_docs.jsonl (+ spike items BE/ZH/BS); results/convert/rule_precision.json",
    )


@lru_cache(maxsize=1)
def committed_rule_precision() -> dict:
    return json.loads(RULE_FILE.read_text())["fields"] if RULE_FILE.exists() else {}


@lru_cache(maxsize=1)
def committed_band_precision() -> dict:
    return json.loads(BAND_FILE.read_text())["results"] if BAND_FILE.exists() else {}


def main() -> None:
    RULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULE_FILE.write_text(json.dumps(rule_precision(), indent=1))
    BAND_FILE.write_text(json.dumps(band_precision(), indent=1))
    COVERAGE_FILE.write_text(json.dumps(rules_coverage(), indent=1))
    rp = json.loads(RULE_FILE.read_text())
    for f, rules in rp["fields"].items():
        print(f, {k: v["shown"] for k, v in rules.items()})
    print(json.dumps(json.loads(BAND_FILE.read_text())["results"], indent=0))


if __name__ == "__main__":
    main()
