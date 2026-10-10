import json

import pytest

from eval import posthoc_r5 as r5


def test_to_iso_and_reply_parsing():
    assert r5.to_iso("28.08.2024") == "2024-08-28"
    assert r5.to_iso("3.7.2024") == "2024-07-03"
    assert r5.to_iso("2024-08-28") == "2024-08-28"
    assert r5.to_iso(None) is None
    assert r5.to_iso("31.13.2024") == "invalid"
    assert r5.to_iso("28 August 2024") == "invalid"
    assert r5.parse_reply('```json\n{"answer_present": "no", "answer_date": null}\n```') == dict(answer_present="no",
                                                                                                    answer_date=None)
    assert r5.parse_reply('<think>x</think>{"answer_present": "yes"}') == dict(answer_present="yes")
    assert r5.parse_reply("no json here") is None


def test_quote_verification():
    pages = ["Titel\nRRB-Nr.: 879/2024 vom 28. August 2024\nText", "Basel, 3. März 2025"]
    ok = r5.verify(dict(date_iso="2024-08-28", quote="RRB-Nr.: 879/2024   vom 28. August 2024", page=1), pages)
    assert ok == dict(quote_on_page=True, quote_in_doc=True, date_in_quote=True, verified=True)
    wrong_page = r5.verify(dict(date_iso="2025-03-03", quote="Basel, 3. März 2025", page=1), pages)
    assert wrong_page["quote_on_page"] is False and wrong_page["verified"] is True  # found elsewhere in the document
    not_in_text = r5.verify(dict(date_iso="2025-03-04", quote="Basel, 4. März 2025", page=2), pages)
    assert not_in_text["verified"] is False
    ocr = r5.verify(dict(date_iso="2023-04-06", quote="Lausanne, le 6 avrfl 2023", page=1), ["Lausanne, le 6 avrfl 2023"])
    assert ocr["quote_in_doc"] is True and ocr["date_in_quote"] is False and ocr["verified"] is True  # printed, OCR-damaged
    assert r5.verify(dict(date_iso=None, quote=None, page=None), pages)["verified"] is True


def test_q_date_uses_only_verified_dates_of_present_answers():
    base = dict(answer_present="yes", date_iso="2024-08-28", verified=True)
    assert r5.q_date(base) == "2024-08-28"
    assert r5.q_date(dict(base, verified=False)) is None
    assert r5.q_date(dict(base, answer_present="no")) is None
    assert r5.q_date(dict(base, date_iso="invalid")) is None


@pytest.mark.parametrize("s", ["p1", "p2"])
def test_committed_audit_files_carry_no_document_text_and_match_the_gold_ids(s):
    p = r5.OUT / f"qwen_{s}.jsonl"
    if not p.exists():
        pytest.skip("audit not run")
    rows = [json.loads(x) for x in open(p)]
    assert {r["doc_id"] for r in rows} == set(r5.labels(s))
    assert {r["model"] for r in rows} == {r5.MODEL}
    for r in rows:
        assert set(r) >= {"doc_id", "answer_present", "date", "quote", "verified", "model", "fingerprint"}
        assert len(r.get("quote") or "") <= 200 and "text" not in r


def test_committed_agreement_recomputes():
    res = r5.RESULTS / "eval" / "posthoc_r5_independent_gold.json"
    if not res.exists() or not (r5.OUT / "qwen_p1.jsonl").exists():
        pytest.skip("audit not run")
    d = json.loads(res.read_text())
    for s in ("p1", "p2"):
        assert r5.agreement(s)["overall"] == d[s]["agreement"]["overall"]
        assert r5.sensitivity(s) == d[s]["sensitivity"]
