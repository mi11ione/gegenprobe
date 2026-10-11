"""POST-HOC round-4 analyses (not pre-registered; labelled as such in every output). No model call: everything is read from
the committed results files, label files, census tables and the committed hash-keyed model cache (data/model_cache).
Frozen files are imported, never changed.

  multiplicity  every registered confirmatory test of P1-P4 and P3b with its p-value; Holm and Benjamini-Hochberg over the
                family; which registered conclusions survive        -> results/eval/posthoc_r4_multiplicity.json
  lenient       the registered lenient answer-date metric next to the strict one, P1 and P2, every arm and build
                                                                    -> results/eval/posthoc_r4_lenient.json
  eval          P2 pointer vs rules per parliament on ALL 62 documents; precision of the residue suggestions (8B vs 70B);
                8B θ fragility (dev margins from the committed cache, by key); 8B cache n_ctx check; P3b Luzern rule
                                                                    -> results/eval/posthoc_r4_eval.json
  served        served model / fingerprint set per results file, from the cache entries the file's documents use
                (cache keys re-derived from the local text cache; needs GP_WORK texts) -> results/eval/served_models.json
  gold          P1 gold dates before OPD's submission date: audit + sensitivity; more non-LLM checks of the P2 gold
                (needs GP_WORK texts and data/census) -> results/eval/posthoc_r4_gold_audit.json,
                                                          results/eval/posthoc_r4_gold_oracle_p2.json

    PYTHONPATH=src:. python -m eval.posthoc_r4 [multiplicity|lenient|eval|served|gold|offline|all]
    (offline = multiplicity + lenient + eval: committed files only)
"""

from __future__ import annotations

import collections
import datetime as dt
import glob
import itertools
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

from eval.score import outcome, summarise
from gegenprobe.paths import DATA, MODEL_CACHE, RESULTS
from gegenprobe.stats import auroc, logsumexp, wilson
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

LABEL = "POST-HOC (not pre-registered): round-4 jury follow-up, 10 Oct 2026"
B70 = "publicai_swiss-ai_apertus-v1.5-8b"  # Public AI name that serves the 70B weights
B8 = "gguf_apertus-v1.5-8b-text-q4_k_m"
BUILD8 = "gguf:apertus-v1.5-8b-text-q4_k_m"
OUT_MULT = RESULTS / "eval" / "posthoc_r4_multiplicity.json"
OUT_LEN = RESULTS / "eval" / "posthoc_r4_lenient.json"
OUT_EVAL = RESULTS / "eval" / "posthoc_r4_eval.json"
OUT_SERVED = RESULTS / "eval" / "served_models.json"
OUT_GOLD = RESULTS / "eval" / "posthoc_r4_gold_audit.json"
OUT_ORACLE2 = RESULTS / "eval" / "posthoc_r4_gold_oracle_p2.json"
ALPHA = 0.05


def _j(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def _write(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------------ statistics
def phi(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2))


def score_test_p(k: int, n: int, p0: float, direction: str) -> dict:
    """One-sided score test of a proportion against p0 (direction 'greater': H1 p > p0; 'less': H1 p < p0).
    The Wilson interval is the inversion of exactly this test, so 'Wilson 95% lower bound >= p0' <=> one-sided p <= 0.025.
    Returned `p_equiv_two_sided` = 2 x one-sided p: the registered decision at alpha 0.05 holds iff it is < 0.05."""
    se = math.sqrt(p0 * (1 - p0) / n)
    z = (k / n - p0) / se if direction == "greater" else (p0 - k / n) / se
    p1 = 1 - phi(z)
    exact = (sum(math.comb(n, i) * p0**i * (1 - p0) ** (n - i) for i in range(k, n + 1)) if direction == "greater"
             else sum(math.comb(n, i) * p0**i * (1 - p0) ** (n - i) for i in range(0, k + 1)))
    return dict(z=z, p_one_sided=p1, p_equiv_two_sided=min(1.0, 2 * p1), exact_binomial_one_sided=exact)


def wilson_z(k: int, n: int, z: float) -> tuple[float, float]:
    return wilson(k, n, z)


def newcombe_z(k1: int, n1: int, k2: int, n2: int, z: float) -> tuple[float, float]:
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson_z(k1, n1, z)
    l2, u2 = wilson_z(k2, n2, z)
    d = p1 - p2
    return d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)


def newcombe_p(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided p of the Newcombe (method 10) interval: 2(1 - Phi(z*)), z* the z at which the lower bound touches 0."""
    lo, hi = 0.0, 40.0
    if newcombe_z(k1, n1, k2, n2, 1e-9)[0] <= 0:
        return 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if newcombe_z(k1, n1, k2, n2, mid)[0] > 0:
            lo = mid
        else:
            hi = mid
    return min(1.0, 2 * (1 - phi(lo)))


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def holm(ps: list[float]) -> list[float]:
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


def bh(ps: list[float]) -> list[float]:
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        run = min(run, min(1.0, m * ps[i] / (rank + 1)))
        adj[i] = run
    return adj


def p_str(p: float) -> str:
    """As the documents print p (same convention as eval/gguf_8b_analysis.p_str)."""
    from eval.gguf_8b_analysis import p_str as f
    return f(p)


def sign_test(pos: int, neg: int) -> float:
    return mcnemar_exact(pos, neg)


# ------------------------------------------------------------------------------------------------ 1 multiplicity
def multiplicity(out_path: Path | None = None) -> dict:
    h1 = _j(RESULTS / "eval" / f"hypotheses__{B70}.json")
    h2 = _j(RESULTS / "eval2" / f"hypotheses2__{B70}.json")["subsets"]["all"]
    h3 = _j(RESULTS / "eval3" / f"hypotheses3__{B70}.json")
    h4 = _j(RESULTS / "eval4" / f"hypotheses4__{B70}.json")
    h5 = _j(RESULTS / "eval5" / f"hypotheses_p3b__{B70}.json")
    tests = []

    def add(tid, prereg, what, rule, p, registered_holds, src, **kw):
        tests.append(dict(id=tid, prereg=prereg, what=what, registered_rule=rule, p=p, registered_outcome=(
            "holds" if registered_holds else "fails"), source=src, **kw))

    k, n = h1["H1"]["pooled"]
    t = score_test_p(k, n, 0.10, "less")
    add("P1-H1 pooled", "eval/prereg/PREREG.md", f"cascade values on gold-null documents {k}/{n}",
        "Wilson 95% upper bound <= 10% (plus <= 1 per cell, a count rule without a test)", t["p_equiv_two_sided"],
        h1["H1"]["pass_pooled"], f"results/eval/hypotheses__{B70}.json H1.pooled", p_kind="CI inversion (score test)",
        detail=t)
    pr = h1["H2"]["primary_fr_it_ocr"]
    add("P1-H2 primary", "eval/prereg/PREREG.md",
        f"cascade vs rules, FR+IT+OCR, discordant {pr['cascade_only']}-{pr['rules_only']}",
        "exact two-sided McNemar, alpha 0.05, cascade > rules", pr["p"], h1["H2"]["branch"] == "A",
        f"results/eval/hypotheses__{B70}.json H2.primary_fr_it_ocr", p_kind="exact McNemar")
    hr = h2["H1_rules_value_recall"]
    p = newcombe_p(*hr["p1"], *hr["p2"])
    add("P2-H1", "eval/prereg2/PREREG2.md", f"rules value recall P1 {hr['p1'][0]}/{hr['p1'][1]} vs P2 "
        f"{hr['p2'][0]}/{hr['p2'][1]}", "95% Newcombe interval of P1 - P2 excludes 0", p, hr["confirmed_drop"],
        f"results/eval2/hypotheses2__{B70}.json subsets.all.H1_rules_value_recall", p_kind="CI inversion (Newcombe)")
    x = h2["theta_10_40"]["H2_pointer_vs_rules"]
    add("P2-H2 primary", "eval/prereg2/PREREG2.md", f"pointer vs rules on gold-value documents, discordant "
        f"{x['pointer_only']}-{x['rules_only']}", "exact two-sided McNemar, alpha 0.05, pointer > rules", x["p"],
        x["holds"], f"results/eval2/hypotheses2__{B70}.json subsets.all.theta_10_40.H2_pointer_vs_rules",
        p_kind="exact McNemar")
    x = h2["theta_10_40"]["H3_cascade_values_on_null"]
    t = score_test_p(x["k"], x["n"], 0.15, "less")
    add("P2-H3", "eval/prereg2/PREREG2.md", f"cascade values on gold-null documents {x['k']}/{x['n']}",
        "Wilson 95% upper bound <= 15%", t["p_equiv_two_sided"], x["holds"],
        f"results/eval2/hypotheses2__{B70}.json subsets.all.theta_10_40.H3_cascade_values_on_null",
        p_kind="CI inversion (score test)", detail=t)
    for part, thr, key in (("a", 0.50, "recall"), ("b", 0.70, "precision")):
        k, n = h3["H3"][key]
        t = score_test_p(k, n, thr, "greater")
        add(f"P3-H3{part}", "eval/prereg3/PREREG3.md", f"Apertus on the residue, {key} {k}/{n}",
            f"Wilson 95% lower bound >= {thr:.2f}", t["p_equiv_two_sided"], h3["H3"][f"{key}_holds"],
            f"results/eval3/hypotheses3__{B70}.json H3.{key}", p_kind="CI inversion (score test)", detail=t)
    x = h4["H3"]
    k, n = x["invented"]
    t = score_test_p(k, n, 0.15, "less")
    p_mc = mcnemar_exact(x["review_only"], x["rules_only"])
    add("P4-H3 primary", "eval/prereg4/PREREG4.md",
        f"review vs rules_only decision recall, discordant {x['review_only']}-{x['rules_only']}; invented {k}/{n}",
        "exact McNemar alpha 0.05 (review > rules_only) AND invented Wilson upper <= 15%; intersection-union test: "
        "p = max of the two component p-values", max(p_mc, t["p_equiv_two_sided"]), x["holds"],
        f"results/eval4/hypotheses4__{B70}.json H3", p_kind="intersection-union (McNemar, CI inversion)",
        components=dict(mcnemar_p=p_mc, invented_bound_p=t["p_equiv_two_sided"]))
    k, n = h5["H3_primary"]["recall"]
    t = score_test_p(k, n, 0.50, "greater")
    add("P3b-S1 primary", "eval/prereg5/PREREG5.md", f"primary H3 recall {k}/{n}", "Wilson 95% lower bound >= 0.50",
        t["p_equiv_two_sided"], h5["replication"]["S1"]["status"] == "holds",
        f"results/eval5/hypotheses_p3b__{B70}.json H3_primary.recall", p_kind="CI inversion (score test)", detail=t)

    ps = [x["p"] for x in tests]
    for x, a, b in zip(tests, holm(ps), bh(ps)):
        x["p_holm"], x["p_bh"] = a, b
        x["holds_after_holm"] = x["registered_outcome"] == "holds" and a < ALPHA
        x["holds_after_bh"] = x["registered_outcome"] == "holds" and b < ALPHA
    # within each pre-registration (each PREREG is its own family)
    by = collections.defaultdict(list)
    for x in tests:
        by[x["prereg"]].append(x)
    for fam in by.values():
        for x, a in zip(fam, holm([y["p"] for y in fam])):
            x["p_holm_within_prereg"] = a

    not_in_family = [
        dict(id="P1-H3", rule="AUROC of the pointer null margin >= 0.80 (point estimate; no test registered)",
             value=h1["H3"]["auroc"], registered_outcome="holds" if h1["H3"]["pass_"] else "fails"),
        dict(id="P1-H4", rule="count trigger (> 1 wrong Apertus FR/IT value -> publish a post-hoc θ curve)",
             value=f"{h1['H4']['wrong']} of {h1['H4']['apertus_decided_fr_it_values']}", registered_outcome="triggered"),
        dict(id="P2-H4", rule="AUROC >= 0.80 (point estimate; no test registered)", value=h2["H4_auroc"]["auroc"],
             registered_outcome="holds" if h2["H4_auroc"]["holds"] else "fails"),
        dict(id="P3-H1, P3-H2, P3-H4", rule="registered as descriptive (per-field tiers, metadata agreement, coverage)"),
        dict(id="P4-H1", rule="rules item recall >= 0.90 (point estimate)", value=h4["H1"]["recall"],
             registered_outcome="holds" if h4["H1"]["holds"] else "fails"),
        dict(id="P4-H2", rule="rules type accuracy >= 0.85 (point estimate)", value=h4["H2"]["accuracy"],
             registered_outcome="holds" if h4["H2"]["holds"] else "fails"),
        dict(id="P4-H4", rule="meeting date matches gold on every held-out meeting (deterministic)",
             value=[h4["H4"]["correct"], h4["H4"]["n"]], registered_outcome="holds" if h4["H4"]["holds"] else "fails"),
        dict(id="P3b H3(b), S2", rule="H3(b) reported against P3 without a verdict; S2 is a below/within/above "
             "classification against P3's interval, no test"),
        dict(id="8B arms (P1)", rule="exploratory by registration (PREREG 'Exploratory'); reported separately below"),
    ]
    h8 = _j(RESULTS / "eval" / f"hypotheses__{B8}.json")
    exploratory_8b = dict(
        note="Exploratory by registration; not in the family. p_times_m = p x %d (the Bonferroni factor of the "
             "registered family), for scale only." % len(tests),
        h2_primary=dict(p=h8["H2"]["primary_fr_it_ocr"]["p"], p_times_m=min(1.0, len(tests) * h8["H2"]["primary_fr_it_ocr"]["p"]),
                        direction="rules better than cascade",
                        discordant=[h8["H2"]["primary_fr_it_ocr"]["cascade_only"], h8["H2"]["primary_fr_it_ocr"]["rules_only"]]),
        h2_pooled=dict(p=h8["H2"]["secondary_pooled_all"]["p"],
                       p_times_m=min(1.0, len(tests) * h8["H2"]["secondary_pooled_all"]["p"]),
                       direction="rules better than cascade"),
    )
    survive = [x["id"] for x in tests if x["holds_after_holm"]]
    out = dict(
        label=LABEL,
        method=("Family = every registered confirmatory decision that rests on a test or an interval (m = %d). Exact "
                "McNemar p-values as registered; interval rules are converted to the p-value of the test the interval "
                "inverts (Wilson = score test, Newcombe hybrid score): the registered decision holds iff that p < 0.05, "
                "so the conversion changes no registered outcome. Holm (FWER) and Benjamini-Hochberg (FDR) at 0.05 over "
                "the family, and Holm within each pre-registration. Document-level tests ignore clustering by parliament "
                "(see results/eval2/body_level.json and posthoc_r4_eval.json for body-level views)." % len(tests)),
        m=len(tests),
        tests=tests,
        survive_holm=survive,
        n_survive_holm=len(survive),
        n_registered_holds=sum(x["registered_outcome"] == "holds" for x in tests),
        display={x["id"]: dict(p=p_str(x["p"]), p_holm=p_str(x["p_holm"]), p_bh=p_str(x["p_bh"])) for x in tests},
        by_id={x["id"]: dict(p=x["p"], p_holm=x["p_holm"], p_bh=x["p_bh"], registered_outcome=x["registered_outcome"],
                             holds_after_holm=x["holds_after_holm"]) for x in tests},
        registered_holds=[x["id"] for x in tests if x["registered_outcome"] == "holds"],
        conclusion=("Every registered conclusion that held survives Holm across all %d tests (%s); the smallest margin is "
                    "%s (Holm p = %.3g). Tests that failed as registered stay failed; no failure turns into a pass."
                    % (len(tests), ", ".join(survive),
                       max((x for x in tests if x["holds_after_holm"]), key=lambda x: x["p_holm"])["id"],
                       max(x["p_holm"] for x in tests if x["holds_after_holm"]))),
        not_in_family=not_in_family,
        exploratory_8b=exploratory_8b,
    )
    _write(out_path or OUT_MULT, out)
    return out


# ------------------------------------------------------------------------------------------------ 2 lenient
LENIENT_FILES = [  # (id, file)
    ("P1_heldout_rules_only", RESULTS / "eval" / "heldout__none.json"),
    ("P1_heldout_70B", RESULTS / "eval" / f"heldout__{B70}.json"),
    ("P1_heldout_8B", RESULTS / "eval" / f"heldout__{B8}.json"),
    ("P1_dev_rules_only", RESULTS / "eval" / "dev__none.json"),
    ("P2_rules_only", RESULTS / "eval2" / "p2__none.json"),
    ("P2_70B", RESULTS / "eval2" / f"p2__{B70}.json"),
    ("P2_8B", RESULTS / "eval2" / f"p2__{B8}.json"),
]


def _pairs(rows, a, b, strict, sel=lambda r: True):
    def ok(r, arm):
        v = r[arm].get("value") if arm != "rules" else (r["rules"].get("value") if r["rules"].get("status") == "value"
                                                        else None)
        return outcome(v, r["gold"], set(r["doc_dates"]), r.get("lenient"), strict) in ("correct", "correct_null")
    rs = [r for r in rows if sel(r)]
    x = sum(ok(r, a) and not ok(r, b) for r in rs)
    y = sum(ok(r, b) and not ok(r, a) for r in rs)
    return dict(n=len(rs), **{f"{a}_only": x, f"{b}_only": y}, p=mcnemar_exact(x, y))


def lenient(out_path: Path | None = None) -> dict:
    out = dict(label=LABEL, metric=(
        "Registered in eval/prereg/PREREG.md (field table) and computed by the frozen eval/score.py summarise(strict="
        "False) into every results file since the first run: a value is also correct if it is one of the alternative "
        "dates the annotators listed as defensible (answer_date_lenient, e.g. the letter date next to the RRB date). "
        "Nulls are scored identically. This file only tabulates what the results files already hold."), files={})
    for split, f in LENIENT_FILES:
        if not f.exists():
            out["files"][split] = "not present (8B on P2: workflow arms-8b-p2 not yet run)"
            continue
        d = _j(f)
        arms_ = {}
        for a, v in d["arms"].items():
            s, le = v["strict"]["ALL"], v["lenient"]["ALL"]
            arms_[a] = dict(strict=[s["exact"], s["n"]], lenient=[le["exact"], le["n"]], strict_correct=s["correct"],
                            lenient_correct=le["correct"], strict_ci=s["exact_ci"], lenient_ci=le["exact_ci"],
                            gain=le["exact"] - s["exact"],
                            per_cell={c: [v["strict"][c]["exact"], v["lenient"][c]["exact"], v["strict"][c]["n"]]
                                      for c in v["strict"] if c != "ALL"})
        out["files"][split] = dict(file=str(f.relative_to(RESULTS.parent)), build=d["build"],
                                                  n=d["n_docs"], arms=arms_)
    out["n_documents_with_lenient_alternatives"] = {
        "P1 held-out": sum(bool(x.get("answer_date_lenient")) for x in _jsonl(DATA / "gold" / "heldout_labels.jsonl")),
        "P2": sum(bool(x.get("answer_date_lenient")) for x in _jsonl(DATA / "gold2" / "p2_labels.jsonl")),
    }
    # the primary paired tests under the lenient metric (sensitivity)
    from eval.hypotheses import FR_IT_OCR
    p1 = _j(RESULTS / "eval" / f"heldout__{B70}.json")["per_doc"]
    p2 = _j(RESULTS / "eval2" / f"p2__{B70}.json")["per_doc"]
    sens = dict(
        P1_H2_primary=dict(strict=_pairs(p1, "cascade", "rules", True, lambda r: r["cell"] in FR_IT_OCR),
                           lenient=_pairs(p1, "cascade", "rules", False, lambda r: r["cell"] in FR_IT_OCR)),
        P2_H2_primary=dict(strict=_pairs(p2, "pointer", "rules", True, lambda r: r["gold"] is not None),
                           lenient=_pairs(p2, "pointer", "rules", False, lambda r: r["gold"] is not None)),
    )
    p8 = RESULTS / "eval" / f"heldout__{B8}.json"
    if p8.exists():
        r8 = _j(p8)["per_doc"]
        sens["P1_H2_primary_8B"] = dict(strict=_pairs(r8, "cascade", "rules", True, lambda r: r["cell"] in FR_IT_OCR),
                                        lenient=_pairs(r8, "cascade", "rules", False, lambda r: r["cell"] in FR_IT_OCR))
    out["primary_tests_strict_vs_lenient"] = sens
    gains = [a["gain"] for f in out["files"].values() if isinstance(f, dict) for a in f["arms"].values()]
    out["conclusion"] = ("The lenient metric raises each arm by %d-%d documents and changes no registered decision (P1-H2 "
                         "5-1 either way; P2-H2 22-0 strict, 25-0 lenient). The exploratory 8B P1-H2 contrast weakens: "
                         "rules better than the cascade 10-2 (p = 0.039) strict, 10-5 (p = 0.30) lenient."
                         % (min(gains), max(gains)))
    _write(out_path or OUT_LEN, out)
    return out


# ------------------------------------------------------------------------------------------------ 4/5/7 eval section
def _ok(pred, r, strict=True) -> bool:
    return outcome(pred, r["gold"], set(r["doc_dates"]), r.get("lenient"), strict) in ("correct", "correct_null")


def _rules_pred(r):
    return r["rules"].get("value") if r["rules"].get("status") == "value" else None


def p2_body_level_all() -> dict:
    res = _j(RESULTS / "eval2" / f"p2__{B70}.json")
    body = {d["doc_id"]: d["body"] for d in _jsonl(DATA / "gold2" / "p2_docs.jsonl")}
    per = collections.defaultdict(lambda: dict(n=0, n_value=0, pointer_only=0, rules_only=0, pointer_exact=0,
                                               rules_exact=0))
    for r in res["per_doc"]:
        b = per[body[r["doc_id"]]]
        p, q = _ok(r["pointer"].get("value"), r), _ok(_rules_pred(r), r)
        b["n"] += 1
        b["n_value"] += r["gold"] is not None
        b["pointer_exact"] += p
        b["rules_exact"] += q
        b["pointer_only"] += p and not q
        b["rules_only"] += q and not p
    bodies = dict(sorted(per.items()))
    diffs = {k: v["pointer_only"] - v["rules_only"] for k, v in bodies.items()}
    pos, neg = sum(d > 0 for d in diffs.values()), sum(d < 0 for d in diffs.values())
    ties = sum(d == 0 for d in diffs.values())
    nz = [d for d in diffs.values() if d]
    obs = sum(nz)
    flips = [sum(s * d for s, d in zip(signs, nz)) for signs in itertools.product((1, -1), repeat=len(nz))]
    perm = sum(abs(f) >= abs(obs) for f in flips) / len(flips)
    docs_b = sum(v["pointer_only"] for v in bodies.values())
    docs_c = sum(v["rules_only"] for v in bodies.values())
    answered = _j(RESULTS / "eval2" / "body_level.json")
    return dict(
        population="all 62 P2 documents; per document correct-or-not = exact (correct value or correct null), strict",
        bodies=bodies,
        bodies_favouring_pointer=pos,
        bodies_favouring_rules=neg,
        bodies_tied=ties,
        bodies_favouring_rules_ids=[k for k, d in diffs.items() if d < 0],
        sign_test_p_two_sided=sign_test(pos, neg),
        cluster_permutation_p_two_sided=perm,
        documents_pointer_only=docs_b,
        documents_rules_only=docs_c,
        document_mcnemar_p=mcnemar_exact(docs_b, docs_c),
        exact_all_62=dict(pointer=sum(v["pointer_exact"] for v in bodies.values()),
                          rules=sum(v["rules_exact"] for v in bodies.values())),
        answered_documents_only=dict(source="results/eval2/body_level.json",
                                     favouring_pointer=answered["bodies_favouring_pointer"],
                                     favouring_rules=answered["bodies_favouring_rules"],
                                     sign_test_p=answered["sign_test_p_two_sided"]),
        display=dict(sign_p=p_str(sign_test(pos, neg)), perm_p=p_str(perm), doc_p=p_str(mcnemar_exact(docs_b, docs_c))),
        reading=("On answered documents the pointer wins 6 bodies and the rules 0; on all 62 documents the rules win "
                 "the bodies where the pointer dates answerless documents (gold null) the rules leave empty."),
    )


def residue_precision() -> dict:
    out = {}
    for name, b in (("8B", B8), ("70B", B70)):
        rows = _j(RESULTS / "eval" / f"heldout__{b}.json")["per_doc"]
        sel = [r for r in rows if r["cascade"].get("route") == "apertus" and r["cascade"].get("value")]
        ok = [r for r in sel if _ok(r["cascade"]["value"], r)]
        on_null = [r for r in sel if r["gold"] is None]
        out[name] = dict(suggestions=len(sel), correct=len(ok), precision=len(ok) / len(sel) if sel else None,
                         precision_ci=list(wilson(len(ok), len(sel))), on_answerless=len(on_null),
                         wrong_date_on_answered=len(sel) - len(ok) - len(on_null),
                         file=f"results/eval/heldout__{b}.json")
    out["definition"] = ("P1 held-out, cascade arm: values the cascade took from Apertus (route apertus, non-null) on "
                         "the rules' residue, i.e. what review mode would show a reviewer; correct = strict gold.")
    a, b = out["8B"], out["70B"]
    out["fisher_two_sided_p"] = _fisher(a["correct"], a["suggestions"] - a["correct"], b["correct"],
                                        b["suggestions"] - b["correct"])
    out["fisher_display"] = p_str(out["fisher_two_sided_p"])
    return out


def _fisher(a: int, b: int, c: int, d: int) -> float:
    n1, n2, k = a + b, c + d, a + c
    n = n1 + n2

    def pr(x):
        return math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n, k)
    p0 = pr(a)
    return min(1.0, sum(pr(x) for x in range(max(0, k - n2), min(k, n1) + 1) if pr(x) <= p0 * (1 + 1e-9)))


def _cache8() -> dict[str, dict]:
    return {Path(f).stem: _j(f) for f in glob.glob(str(MODEL_CACHE / B8 / "*" / "*.json"))}


def _margin(lps: list[float]) -> float | None:
    return lps[0] - logsumexp(lps[1:]) if len(lps) > 1 else None


def derive_dev_margins_8b() -> list[dict]:
    """Needs the local text cache. Re-derives each 8B dev cache key from the document text (frozen pointer prompt); the
    documents whose local extraction differs from the CI runner's (key miss) are matched to the cache entries no other
    dev/held-out key explains, by candidate count; the assignment is accepted only if the refitted θ, AUROC and gap equal
    the committed θ file exactly."""
    from eval import arms
    from gegenprobe import llm, pdftext
    from gegenprobe.convert import lattice, pointer
    from gegenprobe.gguf_fast import GGUFFast

    os.environ["GP_OFFLINE"] = "1"
    be = GGUFFast(cache_readonly=True)
    be.offline = True
    seen: dict[str, str] = {}
    last: list[str] = [""]
    orig = llm.ModelCache.get

    def get(self, k):
        v = orig(self, k)
        last[0] = k
        if v is not None:
            seen[k] = k
        return v

    th = _j(DATA / "convert" / "theta" / f"{B8}.json")["answer_date"]
    labs = {x["doc_id"]: x for x in _jsonl(DATA / "gold" / "dev_labels.jsonl") if not x["source"].startswith("spike")}
    docs = {d["doc_id"]: d for d in _jsonl(DATA / "gold" / "dev_docs.jsonl")}
    held = {r["doc_id"]: r for r in _j(RESULTS / "eval" / f"heldout__{B8}.json")["per_doc"]}
    cache = _cache8()
    rows, miss = [], []
    llm.ModelCache.get = get
    try:
        for i in th["fitted_on"]:
            d = docs[i]
            t = pdftext.extract(d["sha256"])
            lg = arms._lang(dict(lang=d.get("lang") or {"it": "it", "fr": "fr"}.get(d["cell"][:2], "de"), cell=d["cell"]))
            text, offs, _ = pointer.doc_text(t["pages"])
            nc = len(lattice.distinct_dates([c for c in lattice.dates(t["pages"])
                                             if pointer._visible(c, offs, pointer.CHAR_BUDGET)]))
            try:
                pointer.answer_date(be, t["pages"], lg, theta=0.0)
                rows.append(dict(doc_id=i, cache_entry=last[0], gold_null=labs[i]["answer_date"] is None, matched="key"))
            except llm.CacheMiss:
                miss.append((i, nc))
        # held-out keys, so the leftover entries are the dev misses
        held_miss = []
        for d in _jsonl(DATA / "gold" / "heldout_docs.jsonl"):
            t = pdftext.extract(d["sha256"])
            lg = arms._lang(dict(lang=d.get("lang") or {"it": "it", "fr": "fr"}.get(d["cell"][:2], "de"), cell=d["cell"]))
            try:
                pointer.answer_date(be, t["pages"], lg, theta=0.0)
            except llm.CacheMiss:
                held_miss.append(held[d["doc_id"]]["pointer"]["margin"])
        for m in held_miss:  # a held-out document missed locally: its committed margin identifies its entry
            for k, v in cache.items():
                if k in seen:
                    continue
                mv = _margin(v["lps"])
                if (mv is None and m in (None, math.inf)) or (mv is not None and m is not None and abs(mv - m) < 1e-9):
                    seen[k] = k
                    break
    finally:
        llm.ModelCache.get = orig
    left = {k: v for k, v in cache.items() if k not in seen}
    by_nc = collections.defaultdict(list)
    for k, v in left.items():
        by_nc[len(v["lps"]) - 1].append(k)
    groups = collections.defaultdict(list)
    for i, nc in miss:
        groups[nc].append(i)
    if sorted((n, len(v)) for n, v in groups.items()) != sorted((n, len(v)) for n, v in by_nc.items()):
        raise RuntimeError(f"unmatched dev misses {groups} vs leftover entries {dict(by_nc)}")
    base = {r["doc_id"]: r for r in rows}
    ids = th["fitted_on"]
    for perm in itertools.product(*[list(itertools.permutations(by_nc[n])) for n in sorted(groups)]):
        cand = dict(base)
        for n, keys in zip(sorted(groups), perm):
            for i, k in zip(groups[n], keys):
                cand[i] = dict(doc_id=i, cache_entry=k, gold_null=labs[i]["answer_date"] is None,
                               matched="candidate count + exact θ/AUROC/gap reproduction (local extraction differs)")
        out = [cand[i] for i in ids]
        if _refit(out, cache) == (th["theta"], th["auroc"], th["gap"]):
            return out
    raise RuntimeError("no assignment reproduces the committed θ")


def _refit(rows: list[dict], cache: dict) -> tuple:
    from gegenprobe.convert import calibrate
    m = [_margin(cache[r["cache_entry"]]["lps"]) for r in rows]
    y = [r["gold_null"] for r in rows]
    t, _ = calibrate.fit_theta(m, y)
    pos = [a for a, b in zip(m, y) if b]
    neg = [a for a, b in zip(m, y) if not b]
    return t, auroc(pos, neg), min(pos) - max(neg)


def argmax_8b(doc_ids: list[int]) -> dict:
    """Argmax candidate of the 8B pointer for held-out documents (needs the local text; cache-only)."""
    from eval import arms
    from gegenprobe import llm, pdftext
    from gegenprobe.convert import pointer
    from gegenprobe.gguf_fast import GGUFFast
    os.environ["GP_OFFLINE"] = "1"
    be = GGUFFast(cache_readonly=True)
    be.offline = True
    docs = {d["doc_id"]: d for d in _jsonl(DATA / "gold" / "heldout_docs.jsonl")}
    out = {}
    for i in doc_ids:
        d = docs[i]
        try:
            t = pdftext.extract(d["sha256"])
            lg = arms._lang(dict(lang=d.get("lang") or {"it": "it", "fr": "fr"}.get(d["cell"][:2], "de"), cell=d["cell"]))
            out[str(i)] = pointer.answer_date(be, t["pages"], lg, theta=math.inf).value
        except (llm.CacheMiss, Exception):  # noqa: BLE001 - unknown without the run's text
            out[str(i)] = None
    return out


def theta_fragility_8b(dev_rows: list[dict], argmax: dict | None = None) -> dict:
    from gegenprobe.convert import calibrate
    cache = _cache8()
    th = _j(DATA / "convert" / "theta" / f"{B8}.json")["answer_date"]
    m = [_margin(cache[r["cache_entry"]]["lps"]) for r in dev_rows]
    y = [r["gold_null"] for r in dev_rows]
    refit = _refit(dev_rows, cache)
    t = th["theta"]
    cands = calibrate._cands(m)
    acc = [sum((mi > c) == yi for mi, yi in zip(m, y)) for c in cands]
    best = max(acc)
    srt = sorted(m)
    below, above = max(x for x in srt if x <= t), min(x for x in srt if x > t)

    def dev_at(tt):
        return sum((mi > tt) == yi for mi, yi in zip(m, y))

    def flips(tt):
        return sum((mi > tt) != (mi > t) for mi in m)

    held = _j(RESULTS / "eval" / f"heldout__{B8}.json")["per_doc"]

    def held_at(tt):
        """Re-decide the pointer and the cascade at θ' from the committed margins. A document whose decision would turn
        from null into a value needs its argmax candidate; those are listed (value unknown without the CI text unless
        the committed row already carries it)."""
        ex_p = ex_c = 0
        changed, unknown = [], []
        for r in held:
            mg = r["pointer"].get("margin")
            pv = r["pointer"].get("value")
            if mg is None or mg == math.inf or not r["pointer"].get("n_cands"):
                newp = pv
            elif mg > tt:
                newp = None
            else:
                newp = pv if pv is not None else (argmax or {}).get(str(r["doc_id"])) or "?"
            if newp == "?":
                unknown.append(r["doc_id"])
            if newp != pv:
                changed.append(dict(doc_id=r["doc_id"], margin=mg, gold=r["gold"], committed=pv,
                                    at_theta=newp if newp != "?" else "argmax candidate (unknown)"))
            pred_p = pv if newp == "?" else newp
            ex_p += _ok(pred_p, r)
            c = r["cascade"]
            if c.get("route") == "apertus":
                pred_c = pred_p
            else:
                pred_c = c.get("value")
            ex_c += _ok(pred_c, r)
        return dict(theta=tt, pointer_exact=ex_p, cascade_exact=ex_c, changed=changed, argmax_unknown=unknown)

    grid = {f"{'plus' if d >= 0 else 'minus'}_{abs(d):.2f}".replace(".", "_"): dict(dev_correct=dev_at(t + d),
                                                                                    dev_flips=flips(t + d)) for d in
            (-2.0, -1.0, -0.5, -0.25, -0.05, 0.0, 0.05, 0.25, 0.5, 1.0, 2.0)}
    return dict(
        dev_margins_from="committed 8B model cache entries, by cache key (dev_rows); refitted θ/AUROC/gap equal the "
                         "θ file: %s" % (refit == (th["theta"], th["auroc"], th["gap"])),
        theta=t,
        optimal_interval=[below, above],
        optimal_interval_width_nats=above - below,
        optimal_interval_width_display=f"{above - below:.3f}",
        dev_correct_at_theta=dev_at(t),
        dev_n=len(m),
        dev_best_correct=best,
        optimal_candidates=sum(a == best for a in acc),
        grid=grid,
        heldout_argmax_resolved=argmax or {},
        heldout=dict(
            frozen=held_at(t),
            minus_0_5=held_at(t - 0.5),
            plus_0_5=held_at(t + 0.5),
        ),
        reading=("θ is the midpoint of the only accuracy-optimal gap between two adjacent dev margins (width %.3f nats). "
                 "Moving θ by 0.5 nats either way flips 1 of 97 dev decisions (86 -> 85 correct)." % (above - below)),
        dev_rows=[dict(r, margin=mm) for r, mm in zip(dev_rows, m)],
    )


def gguf_n_ctx() -> dict:
    cache = _cache8()
    nps = [v["n_prompt"] for v in cache.values()]
    cont_chars = len(' "DD.MM.YYYY"')
    return dict(
        finding=("TRUE: src/gegenprobe/gguf_fast.py builds the cache key with n_ctx=4096 (line 'payload = dict(... "
                 "n_ctx=4096)  # key identical to the frozen scorer') while GGUFFast loads llama.cpp with n_ctx=6144."),
        entries=len(cache),
        scorer_tags=dict(collections.Counter(v.get("scorer") for v in cache.values())),
        max_n_prompt=max(nps),
        n_prompt_over_4096=sum(x > 4096 for x in nps),
        n_prompt_over_4096_minus_continuation=sum(x + cont_chars - 1 > 4096 for x in nps),
        bound=("a date continuation ' \"DD.MM.YYYY\"' is 13 characters, so at most 13 tokens; the frozen scorer evaluates "
               "the prompt plus all but the last continuation token: max %d + 12 = %d <= 4096, so every 8B call would "
               "also fit the frozen scorer's 4096-token context; n_ctx only sizes the KV cache and does not change the "
               "logits of a sequence that fits" % (max(nps), max(nps) + 12)),
    )


def p3b_luzern() -> dict:
    from eval.gold3.score3 import score_all
    from eval.gold5.run_p3b import LABELS5, affairs
    res = _j(RESULTS / "eval5" / f"p3b__{B70}.json")
    gold = {g["affair_id"]: g for g in _jsonl(LABELS5)}
    ent = {r["affair_id"]: r for r in affairs()}
    cases = []
    for r in res["per_affair"]:
        for q in r["affair"].get("qa", []):
            ad = q.get("answer_date") or {}
            if ad.get("rule") == "lu_antrag":
                cases.append(dict(affair_id=r["affair_id"], body=ent[r["affair_id"]]["body"],
                                  rule_value=ad.get("value"), rule_quote=ad.get("quote"),
                                  opd_answer_event=r["arms"]["M"]["answer_date"], opd_submitted=r["arms"]["M"]["submitted"],
                                  gold=gold[r["affair_id"]].get("answer_date"),
                                  gold_quote=gold[r["affair_id"]].get("answer_date_quote"),
                                  C=r["arms"]["C"]["answer_date"], CA=r["arms"]["CA"]["answer_date"]))
    wrong = [c for c in cases if c["C"] != c["gold"] and c["opd_answer_event"] == c["gold"]]
    fixed = json.loads(json.dumps(res["per_affair"]))
    ids = {c["affair_id"] for c in wrong}
    for r in fixed:
        if r["affair_id"] in ids:
            for arm in ("C", "CA"):
                r["arms"][arm]["answer_date"] = r["arms"]["M"]["answer_date"]
    s0 = score_all(res["per_affair"], gold, ent)["fields"]["answer_date"]
    s1 = score_all(fixed, gold, ent)["fields"]["answer_date"]
    p3_lo, p3_hi = wilson(22, 27)
    k1, n1 = s1["C"]["correct"], s1["C"]["n"]
    return dict(
        rule="lu_antrag (src/gegenprobe/convert/rules.py, LOCK-frozen): 'Antrag Regierungsrat:' then the first date "
             "within 300 characters. In these Luzern answer documents pdftotext prints the header labels (Nummer / "
             "Eröffnet / Antrag Regierungsrat / Protokoll-Nr.) as one column and the values as the next, so the first "
             "date after the label is the 'Eröffnet' (submission) value; the decision date is the next line.",
        why_c_used_it="arm C takes answer_date from the document rules whenever a rule fires (src/gegenprobe/affair/"
                      "build.py: answer_date is a document-route field) and falls back to OPD metadata only when none "
                      "fires, so the rule's value replaced OPD's correct answer event.",
        dev_history="the rule was written on one dev document (517948), where it is correct (results/eval/dev__none.json).",
        cases=cases,
        n_wrong_with_correct_metadata=len(wrong),
        registered=dict(C=[s0["C"]["correct"], s0["C"]["n"]], CA=[s0["CA"]["correct"], s0["CA"]["n"]]),
        if_metadata_kept=dict(C=[k1, n1], CA=[s1["CA"]["correct"], s1["CA"]["n"]], C_ci=list(wilson(k1, n1))),
        s2_effect=("answer_date C: registered %d/%d (below P3's CI [%.2f, %.2f]); with OPD's answer event kept in "
                   "these %d affairs %d/%d = %.2f, within P3's CI; S2 would then have 0 fields below instead of 1. The "
                   "registered verdict (replicated) is unchanged either way."
                   % (s0["C"]["correct"], s0["C"]["n"], p3_lo, p3_hi, len(wrong), k1, n1, k1 / n1)),
    )


def eval_section(out_path: Path | None = None) -> dict:
    """Reads the committed dev-margin keys and argmax candidates from OUT_EVAL if present (they need the local text cache
    to derive), recomputes everything else from committed files, writes to out_path (default OUT_EVAL)."""
    prev = _j(OUT_EVAL) if OUT_EVAL.exists() else {}
    dev_rows = prev.get("theta_8b", {}).get("dev_rows")
    if dev_rows:
        dev_rows = [{k: v for k, v in r.items() if k != "margin"} for r in dev_rows]
    else:
        dev_rows = derive_dev_margins_8b()
    argmax = prev.get("theta_8b", {}).get("heldout_argmax_resolved")
    if not argmax:
        held = _j(RESULTS / "eval" / f"heldout__{B8}.json")
        th = held["theta"]
        near = [r["doc_id"] for r in held["per_doc"] if r["pointer"].get("value") is None and r["pointer"].get("n_cands")
                and r["pointer"].get("margin") is not None and th < r["pointer"]["margin"] <= th + 2.0]
        argmax = argmax_8b(near)
    out = dict(
        label=LABEL,
        p2_body_level_all_documents=p2_body_level_all(),
        residue_suggestion_precision=residue_precision(),
        theta_8b=theta_fragility_8b(dev_rows, argmax),
        gguf_cache_n_ctx=gguf_n_ctx(),
        p3b_luzern_rule=p3b_luzern(),
    )
    _write(out_path or OUT_EVAL, out)
    return out


# ------------------------------------------------------------------------------------------------ 3 served models
class _Recorder:
    def __init__(self):
        from gegenprobe import llm
        self.llm, self.keys, self.miss = llm, collections.defaultdict(set), collections.Counter()
        self.orig = llm.ModelCache.get
        self.tag = None

    def __enter__(self):
        rec = self

        def get(cache, k):
            v = rec.orig(cache, k)
            if rec.tag:
                if v is not None:
                    rec.keys[rec.tag].add((cache.dir.name, k))
                else:
                    rec.miss[rec.tag] += 1
            return v
        self.llm.ModelCache.get = get
        return self

    def __exit__(self, *a):
        self.llm.ModelCache.get = self.orig


def _offline70():
    from gegenprobe import llm
    be = llm.OpenAICompat(base_url="", api_key="", model="swiss-ai/apertus-v1.5-8b",
                          build="publicai:swiss-ai/apertus-v1.5-8b", cache_readonly=True)
    be.offline = True
    return be


class _Tolerant:
    """Wraps an offline backend: a cache miss (local extraction differs from the run's) yields a neutral answer so the
    frozen code keeps going; misses are counted, hits are recorded by the recorder."""

    def __init__(self, be):
        self.be, self.build, self.misses = be, be.build, 0

    def score(self, user, prefix, conts):
        try:
            return self.be.score(user, prefix, conts)
        except Exception:
            self.misses += 1
            return [0.0] * len(conts)

    def generate(self, user, max_tokens=200, seed=0):
        try:
            return self.be.generate(user, max_tokens=max_tokens, seed=seed)
        except Exception:
            self.misses += 1
            return ""


def served() -> dict:
    from eval import arms
    from eval.gold2 import run_p2
    from gegenprobe.gguf_fast import GGUFFast

    os.environ["GP_OFFLINE"] = "1"
    tmp = Path(tempfile.mkdtemp(prefix="served_"))
    out = dict(label=LABEL, method=(
        "Each results file's documents are re-run through the frozen arms (eval.arms.run) with a cache-only backend "
        "(GP_OFFLINE=1; no request leaves the machine) on the local text cache, and every cache entry the run reads is "
        "recorded. The served model and system_fingerprint are read from those entries' stored response ('resp'). A "
        "document whose local text differs from the run's (other extractor version) misses the cache; misses are "
        "counted, and the build-level set (every committed entry of that build) is given next to it. The results files "
        "themselves are not modified: their served_fingerprints field is [] because eval/arms.py only collects "
        "fingerprints from live calls (llm._Remote._check), and these runs were replayed from the cache."),
        files={})
    rec = _Recorder()

    def summarise_keys(tag, misses):
        ks = rec.keys[tag]
        models, fps, scorers = collections.Counter(), collections.Counter(), collections.Counter()
        for build_dir, k in ks:
            v = _j(MODEL_CACHE / build_dir / k[:2] / f"{k}.json")
            r = v.get("resp") or {}
            models[r.get("model")] += 1
            fps[r.get("system_fingerprint")] += 1
            scorers[v.get("scorer")] += 1
        return dict(cache_entries_used=len(ks), cache_miss_calls=misses, served_models=dict(models),
                    system_fingerprints=dict(fps), scorer_tags=dict(scorers))

    with rec:
        # P1 held-out, 70B (all registered arms incl. naive and recommendation)
        be = _Tolerant(_offline70())
        arms.RESULTS = tmp
        rec.tag = f"results/eval/heldout__{B70}.json"
        arms.run(be, "heldout", ["rules", "pointer", "cascade", "naive", "recommendation"],
                 _j(RESULTS / "eval" / f"heldout__{B70}.json")["theta"])
        out["files"][rec.tag] = summarise_keys(rec.tag, be.misses)
        # θ fit of the 70B on dev (127 documents incl. the 30 spike items, θ = 0 scoring)
        be = _Tolerant(_offline70())
        rec.tag = f"data/convert/theta/{B70}.json"
        from gegenprobe.convert import pointer
        for d in arms.load_split("dev"):
            pointer.answer_date(be, d["pages"], arms._lang(d), theta=0.0, variant="")
        out["files"][rec.tag] = summarise_keys(rec.tag, be.misses)
        # P2, 70B
        be = _Tolerant(_offline70())
        rec.tag = f"results/eval2/p2__{B70}.json"
        arms.DATA = run_p2.staged_data()
        try:
            arms.run(be, "heldout", ["rules", "pointer", "cascade", "naive"], _j(RESULTS / "eval2" / f"p2__{B70}.json")["theta"])
        finally:
            arms.DATA = DATA
        out["files"][rec.tag] = summarise_keys(rec.tag, be.misses)
        # P1 held-out and dev fit, 8B (GGUF): entries carry no served-model field; the file is pinned by sha256
        g = GGUFFast(cache_readonly=True)
        g.offline = True
        be = _Tolerant(g)
        rec.tag = f"results/eval/heldout__{B8}.json"
        arms.run(be, "heldout", ["rules", "pointer", "cascade"], _j(RESULTS / "eval" / f"heldout__{B8}.json")["theta"])
        out["files"][rec.tag] = summarise_keys(rec.tag, be.misses)
        arms.RESULTS = RESULTS
    for f, v in out["files"].items():
        v["build_level"] = _build_level(B8 if B8 in f else B70)
    short = {f"results/eval/heldout__{B70}.json": "P1_heldout_70B", f"data/convert/theta/{B70}.json": "P1_dev_theta_70B",
             f"results/eval2/p2__{B70}.json": "P2_70B", f"results/eval/heldout__{B8}.json": "P1_heldout_8B"}
    out["by_set"] = {short[k]: dict(entries=v["cache_entries_used"], miss_calls=v["cache_miss_calls"],
                                    n_fingerprints=len([x for x in v["system_fingerprints"] if x not in (None, "null")]))
                     for k, v in out["files"].items() if k in short}
    if (OUT_EVAL).exists():
        ev = _j(OUT_EVAL)
        out["files"][f"data/convert/theta/{B8}.json"] = dict(
            cache_entries_used=len(ev["theta_8b"]["dev_rows"]), cache_miss_calls=0,
            note="dev keys re-derived in results/eval/posthoc_r4_eval.json theta_8b.dev_rows (7 by candidate count)",
            build_level=_build_level(B8))
    out["recorded_in_results_files"] = {
        f"results/eval3/p3__{B70}.json": _j(RESULTS / "eval3" / f"p3__{B70}.json")["served_fingerprints"],
        f"results/eval5/p3b__{B70}.json": _j(RESULTS / "eval5" / f"p3b__{B70}.json")["served_fingerprints"],
        f"data/convert/theta/{B70}.json": _j(DATA / "convert" / "theta" / f"{B70}.json")["served_fingerprints"],
    }
    from gegenprobe.llm import GGUF_PINS
    out["gguf_pin"] = dict(GGUF_PINS["apertus-v1.5-8b-text-q4_k_m"],
                           note="llm.fetch_gguf refuses a file whose sha256 differs; GGUF cache entries record no "
                                "served-model field because the weights are the pinned local file")
    _write(OUT_SERVED, out)
    return out


def _build_level(b: str) -> dict:
    models, fps, scorers = collections.Counter(), collections.Counter(), collections.Counter()
    n = 0
    for f in glob.glob(str(MODEL_CACHE / b / "*" / "*.json")):
        v = _j(f)
        n += 1
        r = v.get("resp") or {}
        models[r.get("model")] += 1
        fps[r.get("system_fingerprint")] += 1
        scorers[v.get("scorer")] += 1
    return dict(entries=n, served_models=dict(models), system_fingerprints=dict(fps), scorer_tags=dict(scorers))


# ------------------------------------------------------------------------------------------------ 6 gold
def _opd(affairs: set[int]):
    from gegenprobe.census import defs, tables
    meta, ev = {}, collections.defaultdict(list)
    for a in tables.rows("affairs"):
        i = tables.i(a["id"])
        if i in affairs:
            meta[i] = dict(number=a["number"], type_raw=a["type_raw"], type_h=a["type_h"], begin=a["begin"][:10])
    for e in tables.rows("events"):
        i = tables.i(e["affair"])
        if i in affairs and e["date"]:
            ev[i].append(dict(date=e["date"][:10], hid=tables.i(e["hid"]), title=e["title"][:60],
                              cls=defs.classify_event(e["title"], tables.i(e["hid"]))))
    return meta, ev


def _texts(doc: dict):
    from gegenprobe import pdftext
    try:
        return pdftext.extract(doc["sha256"])["pages"]
    except Exception:
        return None


def _date_lines(pages) -> list[dict]:
    from gegenprobe.convert import lattice
    return [dict(value=c["value"], line=c["line"][:160]) for c in lattice.dates(pages)] if pages else []


AUDIT_P1 = {
    249052: dict(
        verdict="genuine as printed (protocol), document typo",
        explanation=(
            "Bern Grand Council government affair (Kreditgeschäft RR 2011.RRGR.410, 'Approbation du compte 2010' of the "
            "lottery fund). The report prints 'Berne, le 18 février 2010', yet it reports the 2010 accounts and cites "
            "the audit report of 4 February 2011, so the printed year is a typo for 2011. The strict gold follows the "
            "protocol (the date as printed); both annotators also listed 2011-02-18 as the lenient alternative. OPD's "
            "'submission' (2011-06-06) is the date the government business went to parliament, which follows the "
            "executive's report for government affairs, so the ordering check does not apply to this affair type.")),
    300277: dict(
        verdict="genuine",
        explanation=(
            "Bern executive decision (RRB, 'Auszug aus dem Protokoll des Regierungsrates', 25 August 2010) on a credit "
            "business (Kreditgeschäft RR 2010.RRGR.1464). For government affairs the executive decides first and the "
            "business is then submitted to parliament (OPD 'Eingereicht' 2010-11-22), so an answer date before OPD's "
            "submission date is expected. Side note: the document's OCR'd text layer prints the RRB number as '1014', "
            "the publisher's title says 1214 (decision_number is not a scored P1 field).")),
    886123: dict(
        verdict="genuine",
        explanation=(
            "Mendrisio municipal preliminary report ('rapporto preliminare del Municipio', Ris.mun. 2345 del 20 "
            "dicembre 2016) on a motion the document says was presented on 11 October 2016. OPD files it under a later "
            "affair, the municipal message MM 71/2018 (OPD 'Eingereicht' 2018-09-14), which carries the 2016 report as "
            "an attachment. The gold is the printed decision date of this document; the ordering check compares it "
            "with a different (later) affair's submission date.")),
}


def gold() -> dict:
    from eval.posthoc_r3 import _title_date
    p1d = {d["doc_id"]: d for d in _jsonl(DATA / "gold" / "heldout_docs.jsonl")}
    p1l = {x["doc_id"]: x for x in _jsonl(DATA / "gold" / "heldout_labels.jsonl")}
    p2d = {d["doc_id"]: d for d in _jsonl(DATA / "gold2" / "p2_docs.jsonl")}
    p2l = {x["doc_id"]: x for x in _jsonl(DATA / "gold2" / "p2_labels.jsonl")}
    affairs = {d.get("affair_id") for d in list(p1d.values()) + list(p2d.values()) if d.get("affair_id")}
    meta, ev = _opd(affairs)
    oracle = _j(RESULTS / "eval" / "posthoc_r3_gold_oracle.json")
    viol = oracle["splits"]["P1"]["answer_not_before_opd_submission"]["violations"]
    items = []
    for v in viol:
        i = v["doc_id"]
        d, lab = p1d[i], p1l[i]
        pages = _texts(d)
        items.append(dict(
            doc_id=i, body=d["body"], cell=d["cell"], dtype=d["dtype"], name=d["name"], affair_id=d.get("affair_id"),
            opd_affair=meta.get(d.get("affair_id")), opd_events=sorted(ev.get(d.get("affair_id"), []), key=lambda e: e["date"]),
            gold=lab["answer_date"], gold_role=lab.get("role"), gold_quote=lab.get("answer_date_quote"),
            gold_lenient=lab.get("answer_date_lenient"), labeller=lab.get("labeller"),
            printed_dates=_date_lines(pages)[:12], **AUDIT_P1.get(i, dict(verdict="not audited", explanation="")),
        ))
    # sensitivity: 249052 scored against the date the document evidently means (2011-02-18, printed nowhere)
    sens = {}
    for b in ("none", B70, B8):
        f = RESULTS / "eval" / f"heldout__{b}.json"
        if not f.exists():
            continue
        res = _j(f)
        s = {}
        for arm in res["arms"]:
            rows0, rows1, rows2 = [], [], []
            for r in res["per_doc"]:
                pred = _rules_pred(r) if arm == "rules" else (r[arm].get("date") if arm.startswith("naive") else
                                                              r[arm].get("value"))
                if arm.startswith("naive") and pred and str(pred).startswith("unparseable"):
                    pred = None
                base = dict(cell=r["cell"], gold=r["gold"], lenient=r.get("lenient") or [], doc_dates=r["doc_dates"],
                            pred=pred)
                rows0.append(base)
                if r["doc_id"] == 249052:
                    rows1.append(dict(base, gold="2011-02-18"))
                else:
                    rows1.append(base)
                    rows2.append(base)
            a0, a1, a2 = (summarise(x, True)["ALL"] for x in (rows0, rows1, rows2))
            s[arm] = dict(registered=[a0["exact"], a0["n"]], gold_2011_02_18=[a1["exact"], a1["n"]],
                          doc_excluded=[a2["exact"], a2["n"]],
                          prediction_249052=next(x["pred"] for x, r in zip(rows0, res["per_doc"]) if r["doc_id"] == 249052))
        sens[res["build"]] = s
    audit = dict(
        label=LABEL,
        question="J5: 3 P1 gold answer dates fall before OPD's submission date (249052, 300277, 886123).",
        source="results/eval/posthoc_r3_gold_oracle.json splits.P1.answer_not_before_opd_submission (already listed there)",
        items=items,
        n_checked=len(items),
        n_gold_errors=sum(it["verdict"].startswith("error") for it in items),
        result=("0 of 3 are gold errors under the labelling protocol. 300277 and 886123 are genuine: an executive "
                "decision on a government business that precedes its submission to parliament, and a 2016 report that "
                "OPD files under a 2018 affair. 249052 is labelled as printed, but the printed year is a typo in the "
                "source (the report on the 2010 accounts cites a February 2011 audit); the evident date 2011-02-18 is "
                "printed nowhere in the document and is already the lenient alternative."),
        sensitivity_249052=dict(
            note="P1 exact (strict) per arm: registered gold, gold set to 2011-02-18, and the document excluded.",
            by_build=sens),
        p2_same_check=_p2_order(p2d, p2l, meta, ev, oracle),
    )
    _write(OUT_GOLD, audit)
    o2 = p2_oracle(p2d, p2l, meta, ev, oracle, _title_date)
    _write(OUT_ORACLE2, o2)
    return dict(audit=audit, oracle2=o2)


def _p2_order(p2d, p2l, meta, ev, oracle) -> dict:
    viol = oracle["splits"]["P2"]["answer_not_before_opd_submission"]["violations"]
    out = []
    for v in viol:
        i = v["doc_id"]
        d, lab = p2d[i], p2l[i]
        lines = _date_lines(_texts(d))
        sub = [x for x in lines if re.search(r"eingereicht|déposée?|presentat|eröffnet", x["line"], re.I)]
        ans_ev = [e["date"] for e in ev.get(d.get("affair_id"), []) if e["cls"] == "written"]
        out.append(dict(doc_id=i, body=d["body"], gold=lab["answer_date"], gold_quote=lab.get("answer_date_quote"),
                        opd_submitted=v["opd_submitted"], opd_affair=meta.get(d.get("affair_id")),
                        printed_submission=sub[:3], opd_written_answer_events=ans_ev,
                        gold_equals_opd_answer_event=lab["answer_date"] in ans_ev,
                        verdict=("genuine: the document prints its own earlier submission date" if sub and
                                 all(x["value"] <= lab["answer_date"] for x in sub) else
                                 "genuine: gold equals an OPD written-answer event" if lab["answer_date"] in ans_ev
                                 else "unresolved")))
    return dict(violations=out, result="%d of %d resolved as genuine (OPD submission date later than the document's own "
                "submission date, or the gold equals an OPD answer event)" % (sum(x["verdict"] != "unresolved"
                                                                                   for x in out), len(out)))


SUBMIT_RX = re.compile(r"eingereicht|eröffnet|déposée?|deposée?|presentat[ao]|inoltrat[ao]", re.I)
DISPATCH_RX = re.compile(r"^\s*(Versand|Envoi|Invio)\b", re.I)


def p2_oracle(p2d, p2l, meta, ev, oracle, title_date) -> dict:
    """Further non-LLM checks of the P2 gold answer dates (none was used to set a label)."""
    val = [x for x in p2l.values() if x["answer_date"]]
    sub_c, disp_c, sched_c = collections.Counter(), collections.Counter(), collections.Counter()
    sub_bad, disp_bad, sched_bad, any_ev = [], [], [], []
    for x in val:
        d = p2d[x["doc_id"]]
        lines = _date_lines(_texts(d))
        # (a) printed submission date (same document, regex) must not follow the answer
        subs = [y["value"] for y in lines if SUBMIT_RX.search(y["line"]) and y["value"] != x["answer_date"]]
        if subs:
            sub_c["checked"] += 1
            if max(subs) <= x["answer_date"]:
                sub_c["holds"] += 1
            else:
                sub_bad.append(dict(doc_id=x["doc_id"], gold=x["answer_date"], printed_submission=subs))
        # (b) printed dispatch date ('Versand:') is on or after a decision-role gold and within 30 days
        disp = [y["value"] for y in lines if DISPATCH_RX.search(y["line"])]
        if disp and x.get("role") == "decision":
            disp_c["checked"] += 1
            gap = (dt.date.fromisoformat(min(disp)) - dt.date.fromisoformat(x["answer_date"])).days
            if 0 <= gap <= 30:
                disp_c["holds"] += 1
            else:
                disp_bad.append(dict(doc_id=x["doc_id"], gold=x["answer_date"], dispatch=disp, gap_days=gap))
        # (c) OPD scheduling event ('Traktandiert', hid 24) after OPD submission: the answer precedes the debate
        evs = ev.get(d.get("affair_id"), [])
        sched = [e["date"] for e in evs if e["hid"] == 24]
        if sched:
            sched_c["checked"] += 1
            if x["answer_date"] <= max(sched):
                sched_c["holds"] += 1
            else:
                sched_bad.append(dict(doc_id=x["doc_id"], gold=x["answer_date"], scheduled=sched))
        # (d) the gold equals ANY OPD event date of the affair (weak: any event type)
        if evs:
            any_ev.append(x["answer_date"] in {e["date"] for e in evs})
    # (e) weekday: decision-role gold dates per body (executive sitting day regularity), no reference needed
    wd = collections.defaultdict(collections.Counter)
    for x in val:
        if x.get("role") == "decision":
            wd[p2d[x["doc_id"]]["body"]][dt.date.fromisoformat(x["answer_date"]).strftime("%a")] += 1
    o3 = oracle["splits"]["P2"]
    checked_any = set()
    for x in val:
        d = p2d[x["doc_id"]]
        lines = _date_lines(_texts(d))
        if any(SUBMIT_RX.search(y["line"]) and y["value"] != x["answer_date"] for y in lines) or \
           ev.get(d.get("affair_id")) or (x.get("role") == "decision" and any(DISPATCH_RX.search(y["line"]) for y in lines)):
            checked_any.add(x["doc_id"])
    return dict(
        label=LABEL,
        scope=("More non-LLM checks of the 29 P2 gold answer dates, next to results/eval/posthoc_r3_gold_oracle.json "
               "(OPD written-answer events 6/6 exact, publisher decision numbers 6/6, OPD submission ordering 14/17). "
               "(a) and (b) are consistency checks inside the same document (deterministic regex on the printed "
               "dates, not an independent source); (c) and (d) use OPD's event table; none was used to set a label."),
        n_gold_value=len(val),
        previous=dict(opd_written_answer_event=[o3["answer_date_vs_opd_written_answer_event"]["agree"],
                                                o3["answer_date_vs_opd_written_answer_event"]["checked"]],
                      title_decision_number=[o3["decision_number_vs_publisher_title"]["agree"],
                                             o3["decision_number_vs_publisher_title"]["checked"]],
                      opd_submission_order=[o3["answer_not_before_opd_submission"]["holds"],
                                            o3["answer_not_before_opd_submission"]["checked"]]),
        a_printed_submission_not_after_answer=dict(checked=sub_c["checked"], holds=sub_c["holds"], violations=sub_bad),
        b_printed_dispatch_within_30_days_after_decision=dict(checked=disp_c["checked"], holds=disp_c["holds"],
                                                              violations=disp_bad),
        c_answer_not_after_opd_scheduling=dict(checked=sched_c["checked"], holds=sched_c["holds"], violations=sched_bad),
        d_gold_equals_some_opd_event=[sum(any_ev), len(any_ev)],
        e_decision_weekday_by_body={b: dict(c) for b, c in sorted(wd.items())},
        gold_value_documents_with_any_check=[len(checked_any), len(val)],
        reading=("No check contradicts a P2 gold date. Exact external confirmation stays at 6 of 29 (OPD answer "
                 "events); the new checks are ordering and consistency bounds, not confirmations of the exact day."),
    )


# ------------------------------------------------------------------------------------------------ 5a gate evidence
REPO = "mi11ione/gegenprobe"
GATE_RUNS = (  # (run, job, what)
    (37992237668, 114029116738, "first parity gate"),
    (37994205470, 114035932274, "parity gate re-run after the last-token-logits fix"),
    (37996141049, 114042612830, "parity recorded (not gating) + replacement gate 'verparity' against bf16"),
)
OUT_VERPARITY = RESULTS / "eval" / "gguf_fast_verparity.json"
OUT_VERPARITY_LOG = RESULTS / "eval" / "gguf_fast_verparity_log.txt"


def verparity() -> dict:
    """Network (gh). The gate's JSON artifact was never uploaded: the job's runner was shut down during the later fit step,
    before the upload step (GitHub lists 0 artifacts for run 37996141049). The committed evidence is therefore the job
    logs: the parity rows and the gate's printed summary line, verbatim."""
    import ast
    import subprocess

    def gh(*a):
        return subprocess.run(["gh", *a], check=True, capture_output=True, text=True).stdout

    runs, excerpt = [], []
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    for run, job, what in GATE_RUNS:
        meta = json.loads(gh("run", "view", str(run), "-R", REPO, "--json", "headSha,createdAt,conclusion"))
        arts = json.loads(gh("api", f"repos/{REPO}/actions/runs/{run}/artifacts"))["total_count"]
        log = ansi.sub("", gh("api", f"repos/{REPO}/actions/jobs/{job}/logs"))
        rows, summary, ver = [], None, None
        for line in log.splitlines():
            body = re.sub(r"^\S+Z\s", "", line)
            if body.startswith("{'key'"):
                rows.append(ast.literal_eval(body))
                excerpt.append(f"[run {run}] {line}")
            elif body.startswith("fast vs frozen GGUF scorer"):
                summary = body
                excerpt.append(f"[run {run}] {line}")
            elif body.startswith("{'frozen'"):
                ver = body
                excerpt.append(f"[run {run}] {line}")
            elif "##[group]Run" in body and "gguf_fast" in body:
                excerpt.append(f"[run {run}] {line}")
            elif "##[error]" in body:
                excerpt.append(f"[run {run}] {line}")
        r = dict(run=run, job=job, what=what, head_sha=meta["headSha"], created=meta["createdAt"],
                 run_conclusion=meta["conclusion"], artifacts=arts, parity_rows=rows, parity_summary=summary,
                 parity_max_abs_delta=max((x["max_abs"] for x in rows), default=None))
        if arts:
            with tempfile.TemporaryDirectory() as tmp:
                gh("run", "download", str(run), "-R", REPO, "-D", tmp)
                art = [_j(f) for f in glob.glob(f"{tmp}/**/gguf_fast_parity.json", recursive=True)]
            r["artifact_gguf_fast_parity_json"] = dict(
                present=bool(art), max_abs_delta=art[0]["max_abs_delta"] if art else None,
                verdict=art[0]["verdict"] if art else None,
                rows_equal_log=bool(art) and [x["max_abs"] for x in art[0]["rows"]] == [x["max_abs"] for x in rows])
        if ver:
            d, verdict = ver.rsplit(" ", 1)
            v = ast.literal_eval(d)
            r["verparity"] = dict(printed=ver, verdict=verdict,
                                  frozen=dict(decisions_agree_bf16=v["frozen"][0], n=30, mean_abs_delta_bf16=v["frozen"][1]),
                                  fast=dict(decisions_agree_bf16=v["fast"][0], n=30, mean_abs_delta_bf16=v["fast"][1]))
        runs.append(r)
    impl = _j(RESULTS / "eval" / "gguf_impl60.json")
    gate = runs[-1]["verparity"]
    out = dict(
        label="Evidence for DEVIATIONS.md D2 (addenda): the replacement gate that cleared the fast 8B scorer",
        source=("GitHub Actions job logs (gh api repos/%s/actions/jobs/<job>/logs); the gate's JSON output "
                "(out/gguf_fast_verparity.json) was never uploaded as an artifact: the runner of job %d was shut down "
                "during the following fit step, before the upload step. Values below are the job's printed lines, "
                "verbatim; per-cell log-odds were not printed and are not recoverable." % (REPO, GATE_RUNS[-1][1])),
        gate=dict(run=GATE_RUNS[-1][0], job=GATE_RUNS[-1][1], head_sha=runs[-1]["head_sha"],
                  fixture="tests/fixtures/gguf_ver30.json (30 verdict cells, ' schuldig' / ' nicht schuldig', seed 20261010)",
                  rule="fast scorer used iff decisions agree with bf16 >= frozen - 1 and mean |delta| vs bf16 <= frozen + "
                       "0.5 nats (D2 addendum 2, fixed before running)",
                  **gate),
        n_ctx_at_gate=dict(frozen=4096, fast=8192, note="GGUFFast default n_ctx was 8192 at 435fc9e; 69094aa set 6144 "
                                                       "for the arms after the fit job ran out of memory"),
        history=runs,
        preset_selfcheck=impl["preset_selfcheck"],
        implementation_check=impl["table"] if isinstance(impl["table"], dict) else impl["table"],
    )
    _write(OUT_VERPARITY, out)
    OUT_VERPARITY_LOG.write_text("\n".join(excerpt) + "\n", encoding="utf-8")
    return out


def main(cmd: str) -> None:
    if cmd in ("multiplicity", "offline", "all"):
        r = multiplicity()
        print("multiplicity:", r["conclusion"])
    if cmd in ("lenient", "offline", "all"):
        r = lenient()
        print("lenient:", {k: {a: (v["strict"], v["lenient"]) for a, v in f["arms"].items()} for k, f in r["files"].items()
                           if isinstance(f, dict)})
    if cmd in ("eval", "offline", "all"):
        r = eval_section()
        b = r["p2_body_level_all_documents"]
        print("eval: P2 bodies all docs", b["bodies_favouring_pointer"], b["bodies_favouring_rules"], b["bodies_tied"],
              "p", b["sign_test_p_two_sided"], "| residue", {k: (v["correct"], v["suggestions"]) for k, v in
                                                            r["residue_suggestion_precision"].items() if isinstance(v, dict)})
    if cmd in ("served", "all"):
        r = served()
        print("served:", {k: (v.get("cache_entries_used"), v.get("cache_miss_calls"), v.get("system_fingerprints"))
                          for k, v in r["files"].items()})
    if cmd == "verparity":
        r = verparity()
        print("verparity:", r["gate"]["printed"])
    if cmd in ("gold", "all"):
        r = gold()
        print("gold:", r["audit"]["result"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "offline")
