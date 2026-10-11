"""The blind check of the document-parts detector (eval/parts): the draw is fixed and blind, the scorer works on
synthetic annotators, and the guide names exactly the labels the scorer reads."""
import json

from eval.parts import common as C
from eval.parts import packets as PK
from eval.parts import score as S


def test_scorer_selftest():
    assert S.selftest() == []


def test_draw_is_seeded_stratified_and_carries_no_detector_output():
    a, b = PK.draw(), PK.draw()
    assert [x["doc_id"] for x in a] == [x["doc_id"] for x in b]
    sizes = dict(C.STRATA)
    got = {}
    for x in a:
        got[x["stratum"]] = got.get(x["stratum"], 0) + 1
    assert all(got.get(k, 0) <= n for k, n in sizes.items()) and len(a) == 30
    if C.DRAW.exists():
        d = json.loads(C.DRAW.read_text(encoding="utf-8"))
        assert d["strata_drawn"] == {k: got.get(k, 0) for k in sizes} and d["seed"] == C.SEED
        assert "PRT-" not in json.dumps(d)  # no packet -> document mapping is committed


def test_detector_pages_reads_every_kind():
    row = dict(n_pages=4, parts=[
        dict(kind="annex", page_from=3, page_to=4, subtype="heading"),
        dict(kind="budget_table", page_from=2, page_to=2, subtype="aligned_columns"),
        dict(kind="image", page_from=1, page_to=2, subtype="scanned_page"),
        dict(kind="image", page_from=4, page_to=4, subtype="embedded"),
        dict(kind="signature", page_from=4, page_to=4, subtype="signature_block")])
    p = C.detector_pages(row)
    assert p[2]["table"] and p[2]["budget_table"] and p[1]["scanned"] and p[2]["scanned"] and not p[3]["scanned"]
    assert p[3]["annex_start"] and p[4]["annex"] and not p[4]["annex_start"] and p[4]["image"] and p[4]["signature"]
    assert C.stratum(row) == "annex"


def test_guide_names_the_labels():
    g = C.GUIDE.read_text(encoding="utf-8")
    for k in C.LABELS:
        assert f"**{k}**" in g and f'"{k}"' in g
