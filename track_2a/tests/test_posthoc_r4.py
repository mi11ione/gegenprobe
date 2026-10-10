"""Post-hoc round-4 analyses: multiplicity helpers, CI-inversion p-values, 8B θ from committed cache keys, and the
offline outputs reproduce the committed files (no model, no network, no texts)."""
import json

from eval import posthoc_r4 as P
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import wilson


def test_holm_and_bh():
    ps = [0.01, 0.04, 0.03, 0.005]
    assert [round(x, 4) for x in P.holm(ps)] == [0.03, 0.06, 0.06, 0.02]
    assert [round(x, 4) for x in P.bh(ps)] == [0.02, 0.04, 0.04, 0.02]


def test_ci_inversion_matches_the_wilson_decision():
    for k, n, p0 in ((25, 32, 0.5), (14, 16, 0.5), (25, 34, 0.7), (11, 20, 0.5), (5, 9, 0.5)):
        lo = wilson(k, n)[0]
        assert (P.score_test_p(k, n, p0, "greater")["p_equiv_two_sided"] < 0.05) == (lo > p0)
    for k, n, p0 in ((7, 90, 0.10), (0, 36, 0.15), (4, 33, 0.15)):
        hi = wilson(k, n)[1]
        assert (P.score_test_p(k, n, p0, "less")["p_equiv_two_sided"] < 0.05) == (hi < p0)
    # Newcombe: P2-H1 excludes 0 with a tiny p
    assert P.newcombe_p(47, 64, 2, 29) < 1e-6


def test_registered_outcomes_unchanged_and_survivors():
    m = json.loads((RESULTS / "eval" / "posthoc_r4_multiplicity.json").read_text())
    for t in m["tests"]:
        assert (t["p"] < 0.05) == (t["registered_outcome"] == "holds"), t["id"]
    assert set(m["survive_holm"]) == set(m["registered_holds"])


def test_offline_outputs_reproduce(tmp_path):
    for fn, name in ((P.multiplicity, "posthoc_r4_multiplicity.json"), (P.lenient, "posthoc_r4_lenient.json"),
                     (P.eval_section, "posthoc_r4_eval.json")):
        fn(tmp_path / name)
        assert json.loads((tmp_path / name).read_text()) == json.loads((RESULTS / "eval" / name).read_text()), name


def test_8b_theta_refits_from_committed_cache_keys():
    ev = json.loads((RESULTS / "eval" / "posthoc_r4_eval.json").read_text())["theta_8b"]
    rows = [{k: v for k, v in r.items() if k != "margin"} for r in ev["dev_rows"]]
    th = json.loads((DATA / "convert" / "theta" / f"{P.B8}.json").read_text())["answer_date"]
    assert [r["doc_id"] for r in rows] == th["fitted_on"]
    assert P._refit(rows, P._cache8()) == (th["theta"], th["auroc"], th["gap"])
    assert ev["optimal_interval_width_nats"] < 0.11 and ev["grid"]["plus_0_50"]["dev_flips"] == 1
