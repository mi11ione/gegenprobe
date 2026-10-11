"""Post-hoc analyses: the corrected naive date parser and the p-value strings (no model, no cache)."""
from eval import naive_baseline as nb
from eval.posthoc_r3 import mcnemar_exact, pstr, to_iso_fixed


def test_fixed_parser_reads_every_stored_form():
    assert to_iso_fixed("2019-02-19") == ("2019-02-19", "iso")
    assert to_iso_fixed("19-02-2019")[0] == "2019-02-19"
    assert to_iso_fixed("26.10.2016")[0] == "2016-10-26"
    assert to_iso_fixed("15-janvier-2019")[0] == "2019-01-15"
    assert to_iso_fixed("25-ottobre-2012")[0] == "2012-10-25"
    assert to_iso_fixed("1er novembre 2023")[0] == "2023-11-01"
    assert to_iso_fixed("6 febbraio 2024")[0] == "2024-02-06"
    assert to_iso_fixed("Nicht verfügbar") == (None, "verbal_null")
    assert to_iso_fixed("09.2001") == (None, "not_a_day_date")
    assert to_iso_fixed(None) == (None, "null")


def test_registered_parser_defect_is_real():
    assert nb.to_iso("19-02-2019").startswith("unparseable")


def test_pstr_and_mcnemar():
    assert pstr(mcnemar_exact(10, 1)) == "0.012"
    assert pstr(mcnemar_exact(22, 4)) == "5.3 × 10⁻⁴"
    assert pstr(mcnemar_exact(0, 1)) == "1"
