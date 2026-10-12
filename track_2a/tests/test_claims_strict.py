"""Rounds 11-13: the strict zones of `make claims`. A wrong number printed next to a right one must fail, and so must
a number swapped for another valid claim of the same document (binding by anchor)."""
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
    """A review mutation: 92.1% -> 97.1% and 9,580 -> 9,780 in the headline table, each next to correct copies elsewhere."""
    t = _text("README.md")
    assert "| **81.6% → 92.1%** |" in t and "once the 9,580 model-free" in t
    bad = t.replace("| **81.6% → 92.1%** |", "| **81.6% → 97.1%** |")
    bad = bad.replace("once the 9,580 model-free", "once the 9,780 model-free")
    errs = claims.zone_check(rows, cfg, docs={"README.md": bad})
    assert any("'97.1%'" in e for e in errs) and any("'9,780'" in e for e in errs), errs


def test_wrong_number_next_to_a_right_one_fails(rows, cfg):
    t = _text("docs/form_notes.md")
    assert "**Delivered.** Repairs" in t
    bad = t.replace("**Delivered.** Repairs", "**Delivered.** (93.1% with Jura) Repairs", 1)
    errs = claims.zone_check(rows, cfg, docs={"docs/form_notes.md": bad})
    assert len(errs) == 1 and "'93.1%'" in errs[0], errs


def test_altered_report_fails_in_the_summary_and_in_the_body(rows, cfg):
    """The whole report is a strict zone (it used to stop at "## 2.")."""
    t = _text("technical_report.md")
    head, sep, body = t.partition("\n## 2.")
    assert sep and "it finds 24/29 answer dates, the rules" in head
    in_summary = head.replace("it finds 24/29 answer dates, the rules", "it finds 23/29 answer dates, the rules", 1) + sep + body
    assert any("'23/29'" in e for e in claims.zone_check(rows, cfg, docs={"technical_report.md": in_summary}))
    stray = head + sep + body + "\nA stray 12.34% after the summary.\n"
    assert any("'12.34%'" in e for e in claims.zone_check(rows, cfg, docs={"technical_report.md": stray}))


def test_allowlist_exempts_only_inside_its_phrase(rows, cfg):
    t = _text("README.md")
    assert "Team 444" in t
    bad = t.replace("Team 444", "Team 444 (445 members)", 1)
    errs = claims.zone_check(rows, cfg, docs={"README.md": bad})
    assert len(errs) == 1 and "'445'" in errs[0], errs


def test_check_includes_the_zone_check(monkeypatch, rows):
    monkeypatch.setattr(claims, "zone_check", lambda rows, cfg=None, docs=None: ["strict zone X:1: '1.5' is not ..."])
    assert "strict zone X:1: '1.5' is not ..." in claims.check(rows[:1])


def test_check_includes_the_anchor_check(monkeypatch, rows):
    monkeypatch.setattr(claims, "anchor_check", lambda rows: ["anchor X: 'y' not found in Z"])
    assert "anchor X: 'y' not found in Z" in claims.check(rows[:1])


# ---- a swap between two valid claims of the same document must fail

def test_m3_readme_headline_swap_between_valid_claims_fails(rows, cfg):
    """M3 (headline re-cut in review): 24/29 -> 18/29 in the README's Apertus table. 18/29 is a valid claim for
    README.md (P3b's affair number; R22: the P2 baselines left the README), so a value-set check would pass it; the
    anchor binds 24/29 to its position."""
    t = _text("README.md")
    assert "| **24/29** answer dates" in t
    assert any(r["shown"] == "18/29" and "README.md" in r["where"] for r in rows)
    bad = t.replace("| **24/29** answer dates", "| **18/29** answer dates", 1)
    errs = claims.zone_check(rows, cfg, docs={"README.md": bad})
    assert any("README.md:" in e and "'18/29'" in e for e in errs), errs


def test_m5_report_body_change_with_the_value_elsewhere_fails(rows):
    """M5 (the case moved with the report's summary): "24/29 answer dates, the rules" -> 27/29 in the
    abstract, while 24/29 still appears in the §3 table and 27/29 is a valid report claim elsewhere (R22: P3's type;
    the P2 baselines left the report)."""
    t = _text("technical_report.md")
    assert "24/29 answer dates, the rules" in t and t.count("24/29") >= 2 and "27/29" in t
    bad = t.replace("24/29 answer dates, the rules", "27/29 answer dates, the rules", 1)
    errs = claims.anchor_check(rows, docs={"technical_report.md": bad})
    assert any("'24/29 answer dates, the rules' not found in technical_report.md" in e for e in errs), errs


def test_m17_readme_results_table_swap_fails(rows, cfg):
    """M17: "12/40 → 24/40" -> "12/40 → 12/40" in the README's evaluation table; 12/40 is a valid README claim and
    still appears right next to it (R22: the P5 detail with 34/40 moved to docs/evaluation.md). The README's results
    tables are strict zones."""
    t = _text("README.md")
    assert "submitter 12/40 → 24/40 |" in t
    assert any(r["shown"] == "12/40" and "README.md" in r["where"] for r in rows)
    bad = t.replace("submitter 12/40 → 24/40 |", "submitter 12/40 → 12/40 |", 1)
    errs = claims.zone_check(rows, cfg, docs={"README.md": bad})
    assert any("'12/40'" in e for e in errs), errs


def test_swapped_staging_shares_in_the_report_summary_fail(rows, cfg):
    t = _text("technical_report.md")
    a, b = "up from 81.6% today", "row-checked ones reach 91.5%"
    assert a in t and b in t
    bad = t.replace(a, "up from 91.5% today", 1).replace(b, "row-checked ones reach 81.6%", 1)
    errs = claims.zone_check(rows, cfg, docs={"technical_report.md": bad})
    assert any("'91.5%'" in e for e in errs) and any("'81.6%'" in e for e in errs), errs


def test_readme_report_and_form_notes_are_strict_end_to_end(cfg):
    """Every numeric token of the README, the report and the form notes is in a strict zone."""
    for doc in ("README.md", "technical_report.md", "docs/form_notes.md"):
        t = _text(doc)
        assert claims.zones_of(t, cfg["zones"][doc]) == [(0, len(t))], doc


def test_anchor_must_hold_the_value_and_name_a_listed_document(rows):
    row = next(r for r in rows if r["id"] == "p2.pointer_found")
    errs: list[str] = []
    claims.anchor_spans([row], {"p2.pointer_found": {"README.md": ["answer dates Apertus finds"]}}, "README.md",
                        _text("README.md"), errs)
    assert any("does not contain '24/29'" in e for e in errs), errs
    errs = []
    claims.anchor_spans([row], {"p2.pointer_found": {"docs/qa.md": ["24/29 x"]}}, "docs/qa.md", "24/29 x", errs)
    assert any("not in the claim's where" in e for e in errs), errs


def test_bound_needs_the_exact_position():
    spans = {(10, 15, "24/29")}
    assert claims._bound(spans, 10, 15, "24/29")
    assert not claims._bound(spans, 11, 16, "24/29") and not claims._bound(spans, 10, 15, "22/29")
    assert claims._bound({(11, 15, "22.7")}, 10, 15, "+22.7")  # a leading plus may be bound by the unsigned claim


def test_every_zone_token_is_bound_in_the_committed_documents(rows, cfg):
    assert claims.anchor_check(rows) == []
    assert claims.zone_check(rows, cfg) == []
