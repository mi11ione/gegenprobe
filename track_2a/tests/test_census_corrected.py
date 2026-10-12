"""Census correction: the derived layer over the registered census (census/corrected.py) and its site rows."""
import csv
import json

from gegenprobe.census import corrected
from gegenprobe.paths import RESULTS, ROOT

SITE = ROOT / "site"
EVID = ROOT / "results" / "evidence"


def _c():
    return json.loads((RESULTS / "census" / "corrected.json").read_text(encoding="utf-8"))


def test_committed_layer_is_a_recompute():
    assert corrected.main(["--check"]) == 0


def test_registered_count_stays_and_upper_bound_arithmetic():
    c = _c()
    a, n = c["national"]["all"], c["national"]["y2425"]
    s = json.loads((RESULTS / "census" / "summary.json").read_text())
    assert a["gap"] == s["national"]["gap"] == 16749 and n["gap"] == s["national_2024_25"]["gap"] == 1855
    assert (a["oral"], n["oral"]) == (1422, 367)
    assert a["unrecognised"] == 2177 and a["unrecognised_by_tier"] == {
        "exact_doc_date": 1717, "exact_any_printed_date": 204, "date_window": 256}
    assert a["lack_text_on_affair_at_most"] == 16749 - 2177 == 14572
    assert a["written_lack_text_at_most"] == 14572 - 1422 == 13150
    assert (n["unrecognised"], n["lack_text_on_affair_at_most"], n["written_lack_text_at_most"]) == (150, 1705, 1338)
    # the 2,177 are exactly the counted tag_answer rows of the adapters (tiers.json)
    t = json.loads((RESULTS / "repair" / "adapters" / "tiers.json").read_text())["tiers"]
    assert sum(t[k]["by_action"].get("tag_answer", 0) for k in t if t[k]["counted"]) == a["unrecognised"]


def test_every_gap_row_in_one_place_per_body_and_period():
    c = _c()
    for b, per in list(c["by_body"].items()) + [("national", c["national"])]:
        for p, x in per.items():
            assert x["gap"] == sum(x[k] for k in corrected.CATS), (b, p)
            assert x["image_only"] == sum(x["image_only_parts"].values()), (b, p)
            assert x["open"] == sum(x["open_parts"].values()), (b, p)
            assert x["opd_elsewhere"] == sum(x["opd_elsewhere_parts"].values()), (b, p)
            assert x["written"] == x["attached"] + x["gap"], (b, p)
    assert sum(per["all"]["gap"] for per in c["by_body"].values()) == 16749


def test_repaired_equals_earlier_routes_plus_counted_adapter_rows():
    a = _c()["national"]["all"]
    ad = json.loads((RESULTS / "repair" / "adapters" / "adapters_summary.json").read_text())
    # adapters_summary.json (LOCK8) counts the lists as committed; the r18 re-tiering (repair/adapters/retier.py) moves
    # Valais's 140 date_window fetch rows to review, and only the derived layer applies it
    rt = _c()["retiered"]
    assert rt["n"] == 140 and rt["by_change"] == {"r18": 140}
    assert a["repaired"] + rt["n"] == ad["coverage"]["repairable_deterministic_with_adapters"] == 3107 + ad["totals"]["verified"]
    # Jura's identity + wording rows are listed, never counted
    lu = _c()["listed_unverified"]
    assert lu["n"] == 282 and lu["bodies"] == ["JU"] and a["open_parts"]["listed_unverified"] == 282
    # earlier routes: agenda join 592 + Bern relink 2,459 + Bern fetch 49 + Curia Vista 7
    assert a["opd_elsewhere"] == 592 + 2459
    be = _c()["by_body"]["BE"]["all"]
    assert be["fetchable_parts"]["be_fetch"] + be["image_only_parts"]["fetchable"] == 49
    assert a["fetchable_parts"]["che_curia"] == 7


def test_named_parliaments():
    b = _c()["by_body"]
    assert b["261"]["all"]["unrecognised"] == 1417 and b["261"]["all"]["gap"] == 1457
    assert b["TI"]["all"]["image_only_parts"]["text_verified"] == 719 == b["TI"]["all"]["image_only_ocr"]
    assert b["TI"]["y2425"]["gap"] == 0 and b["TI"]["y2425"]["written"] == 352
    assert (b["4566"]["all"]["unrecognised"], b["1059"]["all"]["unrecognised"], b["NE"]["all"]["unrecognised"],
            b["VD"]["all"]["unrecognised"]) == (14, 69, 237, 91)


def test_report_share_after_every_counted_repair():
    r = _c()["report"]
    q = json.loads((RESULTS / "census" / "question.json").read_text())["national"]
    assert r["registered_text_share"] == q["text_share_now"] and r["registered_after_relink"] == q["text_share_after_relink"]
    assert r["after_all_counted_repairs"] == 0.921451 and r["repaired"] == 9580 and r["verified_fetches"] == 3500
    a = _c()["national"]["all"]
    assert r["written"] == a["attached"] + r["repaired"] + r["still_without_text"]
    assert r["still_without_text_written"] == r["still_without_text"] - a["oral"] == a["still_open"]
    # the sentence rounds the counts once (84,099 / 91,268 = 92.145%), not the 4-decimal field again
    assert "92.1% after every counted repair" in _c()["sentences"]["report"]


def test_site_rows_never_say_not_in_opd_for_answers_found_in_opd():
    d = json.loads((EVID / "data.json").read_text(encoding="utf-8"))
    rows = {r["key"]: r for r in d["parliaments"]["rows"]}
    zc = rows["261"]
    assert "1,417 are in OpenParlData with text on the intervention" in zc["safe_say"]
    assert "are not in OpenParlData" not in zc["safe_say"]
    for k in ("4566", "1059", "NE", "VD"):
        assert "under a heading the census does not recognise" in rows[k]["safe_say"], k
    ti = rows["TI"]["safe_say"]
    assert "OCR of OPD's own copies would recover 719" in ti and "0 of 352" in ti and "not yet run" not in ti
    for r in rows.values():
        a = r["periods"]["all"]
        assert a["after_repair"] is None or a["with_text"] <= a["after_repair"] <= 1
        assert a["written_missing"] == (a["agenda"] + a["parentless"] + a["unrecognised"] + a["opd_image_only"]
                                        + a["fetchable"] + a["still_open"]), r["key"]
    assert d["headline"]["at_most"]["all"]["lack_text"] == 14572 and d["headline"]["periods"]["all"]["missing"] == 16749
    with open(EVID / "parliaments.csv", encoding="utf-8") as f:
        csvrows = {r["key"]: r for r in csv.DictReader(f)}
    z = csvrows["261"]
    assert z["all_in_opd_unrecognised_heading"] == "1417" and z["all_no_answer_text"] == "1457"
    assert float(z["all_after_repair"]) == 0.9856


def test_adapter_lists_on_the_site():
    m = json.loads((SITE / "downloads" / corrected.MANIFEST).read_text(encoding="utf-8"))
    assert m["totals"]["counted"] == 6613 and m["totals"]["not_counted_verified"] == 282
    # verified equals counted in every list row; Jura's identity + wording rows are verified=false, action=review
    with open(SITE / "downloads" / "adapters_JU.tsv", encoding="utf-8") as f:
        ju = list(csv.DictReader(f, delimiter="\t"))
    assert sum(r["tier"] == "identity_wording_only" for r in ju) == 282
    assert all(r["verified"] == r["counted"] for r in ju)
    assert all(r["action"] == "review" and r["verified"] == "false" for r in ju if r["tier"] == "identity_wording_only")
    with open(SITE / "downloads" / "adapters_TI.tsv", encoding="utf-8") as f:
        ti = list(csv.DictReader(f, delimiter="\t"))
    assert sum(r["counted"] == "true" and r["census_category"] == "image_only:text_verified" for r in ti) == 719
    # the site copy is the committed list, byte for byte
    assert (SITE / "downloads" / "adapters_TI.tsv").read_bytes() == (RESULTS / "repair" / "adapters" / "adapters_TI.tsv"
                                                                     ).read_bytes()
    listed = {d["f"] for d in json.loads((SITE / "data" / "core.json").read_text(encoding="utf-8"))["downloads"]}
    assert {"adapters_manifest.json", "adapters_TI.tsv", "adapters_JU.tsv"} <= listed  # the app's About lists them
