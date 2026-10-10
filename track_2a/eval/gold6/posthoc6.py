"""P5 post-hoc breakdowns (NOT pre-registered; descriptive only): per language and per body for every arm, the kinds
of rules-only submitter errors, and the dev-vs-P5 drop per field.

    python -m eval.gold6.posthoc6   -> results/eval6/p5_posthoc.json
"""

from __future__ import annotations

import collections
import json

from eval.gold6.run6 import labels
from eval.gold6.score6 import name_match, score
from gegenprobe.paths import DATA, RESULTS

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
LANG = {"BL": "de", "SH": "de", "1061": "de", "2703": "de", "293": "de", "5192": "it"}
ARMS = ("R", "RA", "RA0", "G")


def _brief(s: dict) -> dict:
    return dict(qa_recall=[s["qa_pairs"]["recall"]["k"], s["qa_pairs"]["recall"]["n"]],
                qa_precision=[s["qa_pairs"]["precision"]["k"], s["qa_pairs"]["precision"]["n"]],
                submitter=[s["submitter"]["k"], s["submitter"]["n"]],
                recommendation=[s["recommendation"]["k"], s["recommendation"]["n"]],
                reasoning=[s["reasoning"]["match"]["k"], s["reasoning"]["match"]["n"]])


def main() -> dict:
    res = json.loads((RESULTS / "eval6" / f"p5__{BUILD}.json").read_text())
    gold = labels("p5")
    rows = {r["affair_id"]: r for r in map(json.loads, open(DATA / "gold6" / "p5_affairs.jsonl"))}
    lang = {a: rows[a]["lang"] or LANG.get(rows[a]["body"], "?") for a in rows}
    out: dict = dict(label="POST HOC (not pre-registered): descriptive breakdowns of P5", build=BUILD)
    for key in ("language", "body"):
        by = collections.defaultdict(list)
        for p in res["per_affair"]:
            by[lang[p["affair_id"]] if key == "language" else rows[p["affair_id"]]["body"]].append(p)
        out[key] = {k: dict(n=len(ps), **{arm: _brief(score({p["affair_id"]: p[arm]["view"] for p in ps},
                                                                {p["affair_id"]: gold[p["affair_id"]] for p in ps}))
                                          for arm in ARMS})
                    for k, ps in sorted(by.items())}
    kinds = collections.Counter()
    for p in res["per_affair"]:
        g, s = gold[p["affair_id"]]["submitter"], p["R"]["view"]["submitter"]
        if not ((g is None and not s) or (s and name_match(g, s["name"]))):
            kinds["no value" if not s else ("value where gold is null" if g is None else "wrong person")] += 1
    out["R_submitter_errors"] = dict(kinds)
    dev = json.loads((RESULTS / "eval6" / f"hypotheses6__p5dev__{BUILD}.json").read_text())["scores"]["R"]
    p5 = json.loads((RESULTS / "eval6" / f"hypotheses6__p5__{BUILD}.json").read_text())["scores"]["R"]
    out["R_dev_vs_p5"] = {f: dict(dev=[dev[f][m]["k"], dev[f][m]["n"]], p5=[p5[f][m]["k"], p5[f][m]["n"]])
                          for f, m in (("qa_pairs", "recall"), ("questions", "recall"), ("reasoning", "match"))}
    out["R_dev_vs_p5"].update({f: dict(dev=[dev[f]["k"], dev[f]["n"]], p5=[p5[f]["k"], p5[f]["n"]])
                               for f in ("submitter", "recommendation")})
    out["R_dev_vs_p5"]["qa_precision"] = dict(dev=[dev["qa_pairs"]["precision"]["k"], dev["qa_pairs"]["precision"]["n"]],
                                              p5=[p5["qa_pairs"]["precision"]["k"], p5["qa_pairs"]["precision"]["n"]])
    (RESULTS / "eval6" / "p5_posthoc.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = main()
    print(json.dumps(o["R_dev_vs_p5"]), o["R_submitter_errors"])
