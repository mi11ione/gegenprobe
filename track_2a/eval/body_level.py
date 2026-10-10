"""POST-HOC body-level analysis of P2-H2 (documents are nested in parliaments; the registered document-level McNemar treats
them as independent). Asked for by the round-2 jury; labelled post-hoc everywhere.

  per body: on gold-value documents, pointer-only correct vs rules-only correct (discordant pairs)
  sign test across bodies with a nonzero difference (two-sided, exact)
  cluster permutation test: flip the arm labels of all documents of a body jointly; statistic = sum(pointer_only - rules_only);
      exact over all 2^k flips (k = bodies with discordant pairs), two-sided
  within-body AUROC of the pointer null margin (gold-null vs gold-value) where a body has both classes

    python -m eval.body_level   -> results/eval2/body_level.json
"""

from __future__ import annotations

import collections
import itertools
import json
import math

from eval.score import outcome
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import auroc

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"


def main() -> dict:
    res = json.loads((RESULTS / "eval2" / f"p2__{BUILD}.json").read_text())
    body = {d["doc_id"]: d["body"] for d in map(json.loads, open(DATA / "gold2" / "p2_docs.jsonl"))}
    per = collections.defaultdict(lambda: dict(pointer_only=0, rules_only=0, n_value=0, null_m=[], value_m=[]))
    for r in res["per_doc"]:
        b = per[body[r["doc_id"]]]
        m = r["pointer"].get("margin")
        if r["gold"] is None:
            if m is not None and r["pointer"].get("n_cands"):
                b["null_m"].append(m)
            continue
        b["n_value"] += 1
        if m is not None and r["pointer"].get("n_cands"):
            b["value_m"].append(m)
        ok = {
            a: outcome(r[a].get("value"), r["gold"], set(r["doc_dates"]), r.get("lenient"), True) == "correct"
            for a in ("pointer", "rules")
        }
        b["pointer_only"] += ok["pointer"] and not ok["rules"]
        b["rules_only"] += ok["rules"] and not ok["pointer"]
    bodies = {}
    for k, v in sorted(per.items()):
        bodies[k] = dict(
            n_value=v["n_value"],
            pointer_only=v["pointer_only"],
            rules_only=v["rules_only"],
            auroc_within=(auroc(v["null_m"], v["value_m"]) if v["null_m"] and v["value_m"] else None),
            n_null=len(v["null_m"]),
            n_value_scored=len(v["value_m"]),
        )
    diffs = [v["pointer_only"] - v["rules_only"] for v in bodies.values() if v["pointer_only"] or v["rules_only"]]
    pos, neg, ties = (
        sum(d > 0 for d in diffs),
        sum(d < 0 for d in diffs),
        sum(1 for v in bodies.values() if v["n_value"] and not (v["pointer_only"] or v["rules_only"])),
    )
    n = pos + neg
    sign_p = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(pos, neg) + 1)) / 2**n) if n else 1.0
    obs = sum(diffs)
    flips = [sum(s * d for s, d in zip(signs, diffs)) for signs in itertools.product((1, -1), repeat=len(diffs))]
    perm_p = sum(abs(f) >= abs(obs) for f in flips) / len(flips)
    doc_level = json.loads((RESULTS / "eval2" / f"hypotheses2__{BUILD}.json").read_text())["subsets"]["all"]["theta_10_40"]
    out = dict(
        label="POST-HOC (not pre-registered): body-level analysis of P2-H2",
        bodies=bodies,
        bodies_favouring_pointer=pos,
        bodies_favouring_rules=neg,
        bodies_with_answers_but_no_discordance=ties,
        sign_test_p_two_sided=sign_p,
        cluster_permutation_p_two_sided=perm_p,
        n_permutations=len(flips),
        document_level_registered=doc_level["H2_pointer_vs_rules"],
    )
    (RESULTS / "eval2" / "body_level.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
