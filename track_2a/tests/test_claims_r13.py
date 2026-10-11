"""Round 13 (J5): the nine single-number edits that got past `make claims` in round 12, each now caught.

Round 12 made only the headline blocks strict; the README, the technical report and the form notes are now strict end to
end, so a number edited anywhere in them, or a new number in a new sentence, must be bound to its claim by an anchor at
its position. Each test edits one committed document in memory and expects the check to name the edited token.
"""
import pytest

from gegenprobe import claims
from gegenprobe.paths import ROOT


@pytest.fixture(scope="module")
def rows():
    return claims.load(ROOT / "claims.tsv")


@pytest.fixture(scope="module")
def cfg():
    return claims.strict_config()


def _text(doc):
    return (ROOT / doc).read_text(encoding="utf-8")


def _errs(rows, cfg, doc, old, new):
    t = _text(doc)
    assert old in t, (doc, old)
    bad = t.replace(old, new, 1)
    return claims.zone_check(rows, cfg, docs={doc: bad}) + claims.anchor_check(rows, docs={doc: bad})


@pytest.mark.parametrize("doc,old,new,token", [
    # a number still printed correctly elsewhere in the same document
    ("README.md", "the rules (12/40 → 24/40)", "the rules (12/40 → 29/40)", "29/40"),
    ("README.md", "κ 0.80–0.93 on P1 and P2", "κ 0.85–0.93 on P1 and P2", "0.85"),
    ("technical_report.md", "| **pointer** | **53/62** [74.7, 92.2] | **24/29**",
     "| **pointer** | **53/62** [74.7, 92.2] | **29/29**", "29/29"),
    # a number round 12 bound to no claim in the README
    ("README.md", "9.3 GB peak", "8.3 GB peak", "8.3"),
    # report numbers round 12 left unchecked: a cascade cell, an interval, a count
    ("technical_report.md", "| cascade | 139/154 [84.6, 94] | 56 |", "| cascade | 139/154 [84.6, 94] | 58 |", "58"),
    ("technical_report.md", "**53/62** [74.7, 92.2]", "**53/62** [76.7, 92.2]", "[76.7, 92.2]"),
    ("technical_report.md", "no decision invented (0/36)", "no decision invented (1/36)", "1/36"),
])
def test_r13_single_number_edit_fails(rows, cfg, doc, old, new, token):
    errs = _errs(rows, cfg, doc, old, new)
    assert any(f"'{token}'" in e for e in errs), errs


@pytest.mark.parametrize("doc,anchor", [
    ("README.md", "### 2. The census: where the answers are\n"),
    ("technical_report.md", "## 3. Use of Apertus\n"),
])
def test_r13_new_false_sentence_in_the_body_fails(rows, cfg, doc, anchor):
    """J5 added a new false sentence to the README body and the report body; both passed in round 12."""
    errs = _errs(rows, cfg, doc, anchor, anchor + "\nApertus also dates 97.5% of the 412 Jura answers.\n")
    assert any("'97.5%'" in e for e in errs) and any("'412'" in e for e in errs), errs


def test_r13_p7_lead_numbers_are_bound(rows):
    """The P7 lead (120/120; 113/120 (94%) vs 127/146 (87%)) is anchored in README, report and form notes."""
    anchors = claims.anchor_config()
    for cid in ("p7.h1.correct", "r13.p7_hit_pct", "r13.p7_trivial_hit", "r13.p7_trivial_pct"):
        assert {"README.md", "technical_report.md", "docs/form_notes.md"} <= set(anchors[cid]), cid


def test_r13_best_no_model_rule_is_the_best(rows):
    """'the best no-model rule' (127/146) must have the highest date-hit share among the no-model arms."""
    import json
    arms = json.loads((ROOT / "results/p7/p7_posthoc_r8.json").read_text())["ablation"]["arms"]
    share = {k: a["annotated"]["date_hit"] / a["annotated"]["n"] for k, a in arms.items()
             if k in ("trivial", "rule_any_view") and a["annotated"].get("date_hit") is not None}
    assert max(share, key=share.get) == "trivial"
    assert (arms["trivial"]["annotated"]["date_hit"], arms["trivial"]["annotated"]["n"]) == (127, 146)


def test_r13_form_notes_fit_the_form():
    assert len(_text("docs/form_notes.md")) <= 5000
