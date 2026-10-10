import json

import pytest

from gegenprobe import claims
from gegenprobe.claims import context_ok, token_spans


@pytest.mark.parametrize("text,shown,n", [
    ("relinks 2,459 rows", "459", 0),
    ("relinks 2,459 rows", "2,459", 1),
    ("a 4.5 b", "4", 0),
    ("a 1.4 b", "4", 0),
    ("CI −1.4 to 9.3", "1.4", 0),
    ("recall 82.5% here", "82.5", 1),
    ("p = 4.8 × 10⁻⁷", "10", 0),
    ("10 parliaments", "10", 1),
    ("135/154 exact", "154", 1),
    ("| 47 | 4 | 0 | 2 |", "4", 1),
    ("v4 and 4b", "4", 0),
    ("[81.5, 92]", "92", 1),
])
def test_token_spans(text, shown, n):
    assert len(token_spans(text, shown)) == n


def test_context_ok_requires_proximity():
    text = "the cascade dates 7 of 90 answerless documents." + " filler" * 40 + " Antrag alone to 7."
    assert context_ok(text, "7", "answerless documents")
    assert context_ok(text, "7", "Antrag alone")
    far = "7 is here." + " x" * 200 + " answerless documents"
    assert not context_ok(far, "7", "answerless documents")


def _setup(tmp_path, monkeypatch, doc_text, context=None):
    (tmp_path / "r.json").write_text(json.dumps({"n": 4}))
    (tmp_path / "doc.md").write_text(doc_text)
    monkeypatch.setattr(claims, "ROOT", tmp_path)
    monkeypatch.setattr(claims, "CONTEXT_FILE", tmp_path / "claims_context.json")
    row = dict(id="t.n", shown="4", file="r.json", path="n", fmt="int", command="-", where="doc.md",
               context=json.dumps(context) if context else "")
    return [row]


def test_check_short_claim_needs_context(tmp_path, monkeypatch):
    rows = _setup(tmp_path, monkeypatch, "Of 17 fields, 4 are feasible.")
    assert any("has no context" in e for e in claims.check(rows))


def test_check_short_claim_with_context_passes(tmp_path, monkeypatch):
    rows = _setup(tmp_path, monkeypatch, "Of 17 fields, 4 are feasible.", {"doc.md": "are feasible"})
    assert claims.check(rows) == []


def test_check_context_must_be_near(tmp_path, monkeypatch):
    rows = _setup(tmp_path, monkeypatch, "Of 17 fields, 4 are feasible." + " x" * 200 + " far phrase", {"doc.md": "far phrase"})
    assert any("not within" in e for e in claims.check(rows))


def test_check_rejects_substring_of_longer_number(tmp_path, monkeypatch):
    rows = _setup(tmp_path, monkeypatch, "We saw 4.5 and 14 cases.", {"doc.md": "We saw"})
    assert any("whole token" in e for e in claims.check(rows))


def test_check_reads_side_file(tmp_path, monkeypatch):
    rows = _setup(tmp_path, monkeypatch, "Of 17 fields, 4 are feasible.")
    (tmp_path / "claims_context.json").write_text(json.dumps({"t.n": {"doc.md": "are feasible"}}))
    assert claims.check(rows) == []
