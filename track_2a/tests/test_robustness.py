import math

from eval import robustness as rb


def test_newcombe_paired_brackets_point_estimate_and_matches_known_case():
    d, lo, hi = rb.newcombe_paired(97, 5, 1, 7)
    assert lo < d < hi
    assert math.isclose(d, 4 / 110)
    # a=8, b=5, c=4, d=3: ad - bc = 4 < n/2, so the corrected phi is 0 and method 10 reduces to the square-and-add of the
    # Wilson margins: delta -/+ sqrt((p1 - l1)^2 + (u2 - p2)^2) and delta + sqrt((u1 - p1)^2 + (p2 - l2)^2)
    d2, lo2, hi2 = rb.newcombe_paired(8, 5, 4, 3)
    l1, u1 = rb.wilson(13, 20, 1.959964)
    l2, u2 = rb.wilson(12, 20, 1.959964)
    assert math.isclose(d2, 0.05)
    assert math.isclose(lo2, 0.05 - math.sqrt((0.65 - l1) ** 2 + (u2 - 0.6) ** 2))
    assert math.isclose(hi2, 0.05 + math.sqrt((u1 - 0.65) ** 2 + (0.6 - l2) ** 2))


def test_mcnemar_and_mde():
    assert math.isclose(rb.mcnemar_exact(5, 1), 0.21875)
    assert rb.mde_paired(110, 6 / 110) > 0.05
    assert rb.mde_paired(10, 0.0) is None


def test_raw_annotations_reproduce_committed_agreement(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "OUT", tmp_path)  # write the recomputed agreement to a temp dir, not into results/
    a = rb.agreement()
    assert a["reproduces_gold_agreement_json"]
    assert a["n_disagreements_sent_to_A3"] == a["n_A3_labels"] == 41
