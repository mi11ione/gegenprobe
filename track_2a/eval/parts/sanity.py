"""Model-free sanity checks of the document-parts detector against signals it does not use.

    PYTHONPATH=src:. .venv/bin/python -m eval.parts.sanity      -> results/parts/sanity.json (ids and counts only)

  1. scans vs the PDF's own metadata: documents whose Creator/Producer names a scanner or an OCR engine (RICOH, Xerox,
     Canon, KONICA MINOLTA, ABBYY, Paper Capture, ...) against documents with a `scanned_page` part (needs WORK/pdf);
  2. scans vs the text-density flag: every `image_only` document (gegenprobe.pdftext: < 30 characters on every page)
     must have scanned pages covering all its pages;
  3. annexes vs the text and OPD: documents whose text refers to an annex ("im Anhang", "voir annexe 2", "allegato 1")
     against documents with an annex part, and against OPD's own list of the affair's documents (data/census/docs.tsv.gz:
     another document of the same affair named Anhang / Beilage / Annexe / Allegato);
  4. attachment lists ("Beilagen:") found, and whether the annex they name is in the document.
EXPLORATORY: these signals are independent of the detector's rules, not a gold standard.
"""
from __future__ import annotations

import collections
import csv
import gzip
import json
import re
import subprocess
import sys

from eval.parts import common as C
from gegenprobe.paths import DATA, PDF_CACHE
from gegenprobe.schema import v0_2_parts as VP

SCANNER = re.compile(r"(?i)\b(RICOH|Xerox|Canon|iR-ADV|KONICA|KM_C|bizhub|NRG|ABBYY|FineReader|Paper Capture|Kyocera|"
                     r"TASKalfa|Lexmark|Epson|Brother|imageRUNNER|OmniPage|Sharp MX|HP Digital Sending|My Image Garden|"
                     r"SC1811|scan)")
ANNEX_NAME = re.compile(r"(?i)\b(anh[aä]ng|beilage|annexe?|allegat|appendi)")


def pdf_meta(sha: str) -> str | None:
    f = PDF_CACHE / f"{sha}.pdf"
    if not f.exists():
        return None
    info = subprocess.run(["pdfinfo", str(f)], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    return " ".join(ln for ln in info.splitlines() if ln.startswith(("Creator:", "Producer:")))


def opd_annex_docs(affairs: set[str], linked: set[str]) -> dict[str, list[str]]:
    out = collections.defaultdict(list)
    with gzip.open(DATA / "census" / "docs.tsv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["affair"] in affairs and f"opd:{r['id']}" not in linked and ANNEX_NAME.search(r["name"] or ""):
                out[r["affair"]].append(f"opd:{r['id']}")
    return dict(out)


def run() -> dict:
    rows = [r for r in VP.load().values() if r["set"] != "fed"]
    ids = lambda rs: sorted(f"{r['set']}:{r['affair_id']}:{r['role']}" for r in rs)  # noqa: E731
    subs = {(r["set"], r["doc_id"]): {p["subtype"] for p in r["parts"]} for r in rows}
    scanned = [r for r in rows if "scanned_page" in subs[(r["set"], r["doc_id"])]]
    # 1. scanner metadata
    meta = {r["doc_id"]: pdf_meta(r["sha256"]) for r in rows}
    have = [r for r in rows if meta[r["doc_id"]] is not None]
    by_meta = [r for r in have if SCANNER.search(meta[r["doc_id"]])]
    sc = {r["doc_id"] for r in scanned}
    one = dict(documents_with_metadata=len(have), scanner_named=len(by_meta),
               scanner_named_and_scanned_pages=sum(r["doc_id"] in sc for r in by_meta),
               scanner_named_without_scanned_pages=ids(r for r in by_meta if r["doc_id"] not in sc),
               scanned_pages_without_scanner_name=ids(r for r in have if r["doc_id"] in sc and r not in by_meta))
    # 2. image-only flag
    io = [r for r in rows if r["image_only"]]
    covered = [r for r in io if {p for x in r["parts"] if x.get("subtype") == "scanned_page"
                                 for p in range(x["page_from"], x["page_to"] + 1)} == set(range(1, r["n_pages"] + 1))]
    two = dict(image_only=len(io), all_pages_scanned=len(covered), not_covered=ids(r for r in io if r not in covered))
    # 3. annex references, annex parts, OPD's annex documents
    with_ref = [r for r in rows if r["signals"]["annex_references"]]
    has_annex = {r["doc_id"] for r in rows if any(p["kind"] == "annex" for p in r["parts"])}
    opd = opd_annex_docs({str(r["affair_id"]) for r in rows}, {r["doc_id"] for r in rows})
    three = dict(
        documents_referring_to_an_annex=len(with_ref),
        of_which_annex_part=sum(r["doc_id"] in has_annex for r in with_ref),
        of_which_opd_lists_an_annex_document=sum(r["doc_id"] not in has_annex and str(r["affair_id"]) in opd
                                                 for r in with_ref),
        of_which_neither=ids(r for r in with_ref if r["doc_id"] not in has_annex and str(r["affair_id"]) not in opd),
        annex_parts_without_a_reference=ids(r for r in rows if r["doc_id"] in has_annex and r not in with_ref),
        opd_annex_documents=dict(sorted(opd.items())))
    # 4. attachment lists
    lists = [r for r in rows if r["signals"]["attachment_lists"]]
    four = dict(documents_with_attachment_list=ids(lists),
                with_annex_part=ids(r for r in lists if r["doc_id"] in has_annex))
    return dict(label="EXPLORATORY model-free sanity checks of gegenprobe.convert.parts (eval/parts/sanity.py)",
                n_documents=len(rows), scans_vs_pdf_metadata=one, scans_vs_image_only_flag=two,
                annexes_vs_references_and_opd=three, attachment_lists=four)


def main(argv: list[str]) -> int:
    out = run()
    C.RP.mkdir(parents=True, exist_ok=True)
    C.SANITY.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
