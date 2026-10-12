"""results/findings/answer_times.json is recomputed from committed inputs (adapter lists, census interventions) and its
headline numbers hold after the logged re-tiering (retier_r18.json: Valais's 140 date-window rows are review rows):
6,473 counted adapter rows in 27 parliaments, 17 ranked, the Spearman coefficients; Valais keeps 23 durations."""
import json

from gegenprobe.findings import answer_times as at


def test_spearman_ties_and_order():
    assert at._ranks([3, 1, 1, 2]) == [4.0, 1.5, 1.5, 3.0]
    assert at.spearman([1, 2, 3, 4], [10, 20, 30, 40], perm=200)["rho"] == 1.0
    assert at.spearman([1, 2, 3, 4], [4, 3, 2, 1], perm=200)["rho"] == -1.0


def test_committed_file_matches_recomputation():
    r = at.compute()
    committed = json.loads(at.OUT.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(r, ensure_ascii=False)) == committed
    h = r["headline"]
    assert (h["counted_rows"], h["parliaments"]) == (6473, 27)  # 6,613 as committed minus the 140 re-tiered rows
    assert h["durations"] == 6362 and h["ranked_parliaments"] == 17
    assert (h["rho_opd_plain_vs_adapter"], h["rho_without_same_day"], h["rho_same_affairs_vs_adapter"]) == \
        (0.884, 0.832, 0.997)
    assert (h["rho_question_type_matched"], h["question_type_parliaments"]) == (0.966, 13)
    assert (h["vs_motions_submission_after_answer_document"], h["vs_counted_rows"]) == (0, 23)
    assert h["opd_date_differs_from_document_date"] == ["1059", "6153", "SO", "VS"]
    t = {x["body"]: x for x in r["ranking"]["table"]}
    assert (t["VS"]["rank_opd_plain"], t["VS"]["rank_adapter"]) == (1.5, 1.0)
    assert (t["1059"]["opd_plain_median"], t["1059"]["adapter_median"]) == (0, 26.5)
    assert (t["SO"]["opd_plain_median"], t["SO"]["adapter_median"]) == (55, 125)
    rt = r["retiered"]
    assert (rt["rows_moved"], rt["durations_moved"], rt["valais_before"]["n"], rt["valais_before"]["median"]) == \
        (140, 76, 99, 100)
    assert (rt["valais_after"]["n"], rt["valais_after"]["median"]) == (23, 2)
