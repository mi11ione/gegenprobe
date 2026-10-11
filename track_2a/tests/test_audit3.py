"""Blind audit v3 of the counted adapter rows (repair/adapters/audit3.py): sample design, blindness of the committed
packets, parsing and the stratified estimator. Offline."""
import json

from gegenprobe.repair.adapters import audit3


def test_allocation_floor_and_total():
    sizes = {"a": 3255, "b": 1602, "c": 718, "d": 59, "e": 51}
    al = audit3.allocate(sizes, n=200, floor=12)
    assert sum(al.values()) == 200 and min(al.values()) >= 12 and al["a"] > al["b"] > al["c"]
    assert audit3.allocate({"a": 5, "b": 500}, n=50, floor=12)["a"] == 5  # a stratum smaller than the floor: all of it


def test_committed_packets_are_blind():
    smp = json.loads((audit3.OUT / "sample.json").read_text())
    pk = audit3.packets()
    assert len(pk) == smp["packets"] == smp["n_counted"] + smp["n_decoys"] == 260
    assert sum(smp["allocation"].values()) == 200 and smp["seed"] == 20261212
    allowed = {"id", "affair_number", "title", "type", "answer_event_dates", "excerpt_path", "text_sha256",
               "excerpt_sha256"}
    for p in pk:
        assert set(p) == allowed, set(p) - allowed
        assert p["excerpt_path"].startswith(".work/adapters/audit3/texts/") and p["id"] in p["excerpt_path"]
    prompt = (audit3.OUT / "PROMPT.md").read_text()
    for leak in ("outcome", "verified", "tier", "proposed_action", "counted"):
        assert leak not in audit3.ITEM
    assert audit3.TEMPLATE in prompt
    if audit3.KEY.exists():  # the key stays in WORK until the verdicts are in; its hash is committed
        import hashlib
        assert hashlib.sha256(audit3.KEY.read_bytes()).hexdigest() == smp["key_sha256"]


def test_parse_tolerates_fences_and_flags_bad_labels():
    v = audit3.parse('```json\n{"is_answer": "Yes", "date_ok": "unclear", "quote": "Il Consiglio di Stato", '
                     '"note": "x"}\n```')
    assert (v["is_answer"], v["date_ok"], v["quote"]) == ("yes", "unclear", "Il Consiglio di Stato")
    assert audit3.parse("no json here")["is_answer"] == "invalid"
    assert audit3.parse('{"is_answer": "probably", "date_ok": "no"}')["is_answer"] == "invalid"


def test_quote_check_normalises_whitespace_and_elisions():
    text = "Der Stadtrat beantwortet die An-\nfrage wie folgt:\n\nZu Frage 1: Ja."
    assert audit3.quote_found("Der Stadtrat beantwortet die Anfrage wie folgt", text) is True
    assert audit3.quote_found("Der Stadtrat beantwortet ... Zu Frage 1: Ja.", text) is True
    assert audit3.quote_found("Der Regierungsrat lehnt die Motion ab", text) is False
    assert audit3.quote_found("Ja.", text) is None  # too short to check


def test_stratified_estimate_weights_strata_by_frame_size():
    est = audit3.stratified({"big": (90, 100), "small": (10, 10)}, {"big": 900, "small": 100}, draws=4000)
    assert est["estimate"] == round(0.9 * 0.9 + 0.1 * 1.0, 4)
    lo, hi = est["ci95"]
    assert lo < est["estimate"] < hi <= 1
    perfect = audit3.stratified({"a": (20, 20), "b": (12, 12)}, {"a": 1000, "b": 50}, draws=4000)
    assert perfect["estimate"] == 1 and perfect["ci95"][1] <= 1 and perfect["ci95"][0] < 1  # no degenerate interval
