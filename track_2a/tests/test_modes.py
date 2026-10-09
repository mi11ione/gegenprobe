"""Converter modes: rules_only (default, unattended) never carries an Apertus value; review attaches it as a suggestion."""
import pytest

from gegenprobe.convert import modes
from tests.test_convert import BE_ANSWER, FakeBackend

RESIDUE = "Bericht der Kommission\nDie Kommission tagte am 12. März 2024 und am 3. April 2024.\nText."


def test_default_is_rules_only_and_needs_no_model():
    r = modes.answer_date(dict(pages=[RESIDUE]))
    assert modes.DEFAULT == "rules_only" and r["mode"] == "rules_only"
    assert r["value"] is None and r["null_reason"] == "present_unanchored" and not r["needs_review"] and "suggestion" not in r


def test_review_attaches_pointer_value_as_suggestion_not_as_value():
    be = FakeBackend(lp_null=-20.0, favour="03.04.2024")
    r = modes.answer_date(dict(pages=[RESIDUE]), "review", be, 0.0)
    assert r["value"] is None  # the unattended field is unchanged
    assert r["needs_review"] and r["suggestion"]["value"] == "2024-04-03"
    s = r["suggestion"]
    assert RESIDUE[s["char_start"]:s["char_end"]] == "3. April 2024"


def test_review_leaves_rule_decisions_alone():
    be = FakeBackend(lp_null=-20.0, favour="16.10.2025")  # would pick the footer if asked
    r = modes.answer_date(dict(pages=[BE_ANSWER]), "review", be, 0.0)
    assert r["value"] == "2025-10-15" and r["route"] == "rule" and not r["needs_review"] and not be.calls


def test_review_without_suggestion_when_pointer_abstains():
    r = modes.answer_date(dict(pages=[RESIDUE]), "review", FakeBackend(lp_null=-1.0), 0.0)
    assert not r["needs_review"] and "suggestion" not in r


def test_unknown_mode():
    with pytest.raises(ValueError):
        modes.answer_date(dict(pages=[RESIDUE]), "auto")
