"""Round 11 (J5): the strict zones of `make claims`. A wrong number printed next to a right one must fail."""
import pytest

from gegenprobe import claims
from gegenprobe.claims import numeric_tokens
from gegenprobe.paths import ROOT


@pytest.mark.parametrize("text,tokens", [
    ("92.3% of 91,268", ["92.3%", "91,268"]),
    ("120/120 judged (Wilson [96.9, 100])", ["120/120", "[96.9, 100]"]),
    ("+22.7 points, unweighted +7.5", ["+22.7", "+7.5"]),
    ("gain [-0.02, 0.54] and [33.3%, 75.0%]", ["[-0.02, 0.54]", "[33.3%, 75.0%]"]),
    ("P8, v0.1, 8B, fig1, run_38098822336, #1-the-schema, D2-4", []),   # identifiers
    ("4 of 33 documents, 7 parliaments", ["33"]),                       # integers below 10 are free
    ("p = 5.3 × 10⁻⁴", ["5.3"]),                                        # power base skipped
    ("a 30-row kit, 2 to 28 days, 10-20 rows", ["30", "28", "10", "20"]),
])
def test_numeric_tokens(text, tokens):
    assert [t for _, _, t in numeric_tokens(text)] == tokens


@pytest.fixture(scope="module")
def rows():
    return claims.load(ROOT / "claims.tsv")


@pytest.fixture(scope="module")
def cfg():
    return claims.strict_config()


def _text(doc):
    return (ROOT / doc).read_text(encoding="utf-8")


def test_strict_zones_cover_the_headline_documents(cfg):
    assert set(cfg["zones"]) >= {"README.md", "technical_report.md", "docs/form_notes.md"}
    for a in sum(cfg["allow"].values(), []):
        assert a["why"] and a["phrase"]


def test_committed_documents_pass(rows, cfg):
    assert claims.zone_check(rows, cfg) == []


def test_altered_readme_fails(rows, cfg):
    """J5's mutation: 92.3% -> 97.3% and 9,720 -> 9,920 in the headline table, each next to correct copies elsewhere."""
    t = _text("README.md")
    assert "| **92.3%** |" in t and "| **9,720** |" in t
    bad = t.replace("| **92.3%** |", "| **97.3%** |").replace("| **9,720** |", "| **9,920** |")
    errs = claims.zone_check(rows, cfg, docs={"README.md": bad})
    assert any("'97.3%'" in e for e in errs) and any("'9,920'" in e for e in errs), errs


def test_wrong_number_next_to_a_right_one_fails(rows, cfg):
    t = _text("docs/form_notes.md")
    assert "92.3% would have" in t
    bad = t.replace("92.3% would have", "92.3% (93.1% with Jura) would have", 1)
    errs = claims.zone_check(rows, cfg, docs={"docs/form_notes.md": bad})
    assert len(errs) == 1 and "'93.1%'" in errs[0], errs


def test_altered_report_summary_fails_but_body_is_outside_the_zone(rows, cfg):
    t = _text("technical_report.md")
    head, sep, body = t.partition("\n## 2.")
    assert sep
    in_zone = head.replace("**120/120**", "**119/120**", 1) + sep + body
    assert any("'119/120'" in e for e in claims.zone_check(rows, cfg, docs={"technical_report.md": in_zone}))
    out_of_zone = head + sep + body + "\nA stray 12.34% after the summary.\n"
    assert claims.zone_check(rows, cfg, docs={"technical_report.md": out_of_zone}) == []


def test_allowlist_exempts_only_inside_its_phrase(rows, cfg):
    t = _text("README.md")
    assert "Team 444" in t
    bad = t.replace("Team 444", "Team 444 (445 members)", 1)
    errs = claims.zone_check(rows, cfg, docs={"README.md": bad})
    assert len(errs) == 1 and "'445'" in errs[0], errs


def test_check_includes_the_zone_check(monkeypatch, rows):
    monkeypatch.setattr(claims, "zone_check", lambda rows, cfg=None, docs=None: ["strict zone X:1: '1.5' is not ..."])
    assert "strict zone X:1: '1.5' is not ..." in claims.check(rows[:1])
