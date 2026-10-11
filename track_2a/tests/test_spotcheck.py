"""The OPD spot-check kit (results/opd_spotcheck/) and its scorer (eval/spotcheck.py)."""
import csv

from eval import spotcheck


def _rows():
    return list(csv.DictReader(open(spotcheck.KIT, encoding="utf-8")))


def test_kit_shape():
    rows = _rows()
    assert len(rows) == 30
    assert list(rows[0].keys()) == spotcheck.COLS
    assert {s: sum(r["set"] == s for r in rows) for s in ("dates", "p7", "p8")} == {"dates": 10, "p7": 10, "p8": 10}
    assert all(len(r["quoted_text"]) <= spotcheck.MAXQ for r in rows)
    assert all(r["reviewer_agrees"] == "" for r in rows)
    assert all(r["document_url"].startswith("https://") for r in rows)
    assert len({r["item_id"] for r in rows}) == 30


def test_score_unfilled_and_filled(tmp_path):
    r = spotcheck.score(spotcheck.KIT)
    assert r["overall"]["items"] == 30 and r["overall"]["reviewed"] == 0 and r["overall"]["agreement"] is None
    rows = _rows()
    for i, row in enumerate(rows):
        row["reviewer_agrees"] = "no" if i == 0 else ("" if i == 1 else "yes")
    p = tmp_path / "filled.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, spotcheck.COLS)
        w.writeheader()
        w.writerows(rows)
    r = spotcheck.score(p)
    assert r["overall"]["reviewed"] == 29 and r["overall"]["agree"] == 28 and r["overall"]["disagree"] == 1
    lo, hi = r["overall"]["wilson95_pct"]
    assert lo < 100 * 28 / 29 < hi
    assert r["invalid"] == []


def test_score_flags_invalid(tmp_path):
    rows = _rows()
    rows[0]["reviewer_agrees"] = "maybe"
    p = tmp_path / "bad.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, spotcheck.COLS)
        w.writeheader()
        w.writerows(rows)
    assert spotcheck.score(p)["invalid"]
