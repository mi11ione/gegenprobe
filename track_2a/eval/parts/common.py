"""Blind check of the document-parts detector (gegenprobe.convert.parts): shared paths and the page-level label set.

EXPLORATORY: the rules were written on the same 210 documents; this check measures, on a stratified sample of them, how
the detector's page-level reading agrees with blind annotators who see only the page images. It is not a pre-registered
test (no lock); the draw rule, the guide and the scorer are fixed before any annotation.
"""
from __future__ import annotations

from gegenprobe.paths import RESULTS, ROOT, WORK

WP = WORK / "parts"           # never committed: page images, the packet key, the annotations
PACK = WP / "packets"         # PRT-NNN/page-NN.png + PRT-NNN/packet.json (number of pages only)
KEY = WP / "key.jsonl"        # packet -> set, affair, role, doc_id, sha256, stratum (kept in WORK until the gold is merged)
ANN = WP / "ann"              # ann/<A>/PRT-NNN.json, one file per packet and annotator
GOLD = WP / "gold.jsonl"      # merged page labels (majority of the annotators)
RP = RESULTS / "parts"
DRAW = RP / "draw.json"       # seed, strata, sizes (no packet -> document mapping)
SCORE = RP / "blind_check.json"
SANITY = RP / "sanity.json"
GUIDE = ROOT / "eval" / "parts" / "GUIDE_PARTS.md"

SEED = 20261011
DPI = 100
# page-level labels: what an annotator marks on each page, and the detector's reading of the same page
LABELS = ("table", "budget_table", "annex", "annex_start", "image", "scanned", "signature")
# strata of the draw (a document's first matching stratum) and how many documents each contributes
STRATA = (("annex", 2), ("table", 6), ("image", 5), ("signature", 4), ("scanned", 4), ("none", 9))


def detector_pages(row: dict) -> dict[int, dict[str, bool]]:
    """The detector's reading of every page of one document (a row of results/schema/v0_2/document_parts.jsonl)."""
    out = {p: {k: False for k in LABELS} for p in range(1, row["n_pages"] + 1)}
    for part in row["parts"]:
        for p in range(part["page_from"], part["page_to"] + 1):
            if p not in out:
                continue
            k, sub = part["kind"], part.get("subtype")
            if k in ("table", "budget_table"):
                out[p]["table"] = True
                out[p]["budget_table"] |= k == "budget_table"
            elif k == "annex":
                out[p]["annex"] = True
                out[p]["annex_start"] |= p == part["page_from"]
            elif k == "image":
                out[p]["scanned" if sub == "scanned_page" else "image"] = True
            elif k == "signature":
                out[p]["signature"] = True
    return out


def stratum(row: dict) -> str:
    pages = detector_pages(row).values()
    for name, _ in STRATA[:-1]:
        if any(pg[name] for pg in pages):
            return name
    return "none"
