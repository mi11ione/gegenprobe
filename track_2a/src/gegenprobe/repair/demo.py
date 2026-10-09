"""`make run` step 3: the BE repair on a vendored slice, plus the triple check on the real documents.

data/repair/demo/ holds, for five BE interpellations, exactly the rows the bulk join reads (canton OGD dokument/geschaeft rows,
OPD affair ids and external ids, OPD parentless documents with their canton uid, OPD answer-event dates), the expected join
output (copied from results/repair/repair_BE.tsv) and the sha256 of each answer PDF. The demo
  1. re-runs be.join on the slice and asserts it reproduces the expected rows;
  2. asserts the committed full list still has 2,459 relink + 49 fetch rows and matches the fixture delivered to OPD;
  3. fetches each answer PDF (pinned by sha256; skipped with a message when offline) and prints the triple check.
The five cases: a 2024 relink (2024.RRGR.91, the S-NULL demo affair), a 2024 fetch (2024.RRGR.139, no copy in OPD), two older
relinks, and 2015.RRGR.870, where the check fails on purpose: the canton's own PDF prints "RRB-Nr.: 119/2016 vom 3. Februar
2015", a year typo against OPD's answer event 2016-02-03.

usage: python -m gegenprobe.repair.demo [build]     (build: regenerate the slice from the full caches; development only)
"""

from __future__ import annotations

import csv
import json
import sys

from .. import pdftext
from ..paths import DATA
from . import be
from .common import OUT, canton_uid, iter_docs_meta, iter_ndjson

DEMO = DATA / "repair" / "demo"
CASES = ["2024.RRGR.91", "2024.RRGR.139", "2021.RRGR.201", "2019.RRGR.246", "2015.RRGR.870"]


def build() -> None:
    DEMO.mkdir(parents=True, exist_ok=True)
    full = {r["affair_number"]: r for r in csv.DictReader(open(OUT / "repair_BE.tsv", encoding="utf-8"), delimiter="\t")}
    exp = [full[n] for n in CASES]
    ids = {int(r["affair_id"]) for r in exp}
    aff = {
        a["id"]: dict(id=a["id"], number=a["number"], external_id=a["external_id"])
        for a in iter_ndjson("affairs")
        if a["id"] in ids
    }
    guids = {a["external_id"] for a in aff.values()}
    dok = [d for d in csv.DictReader(open(be.OGD_DIR / "dokument.csv", encoding="utf-8")) if d["dokument_geschaeft_uid"] in guids]
    ges = [g for g in csv.DictReader(open(be.OGD_DIR / "geschaeft.csv", encoding="utf-8")) if g["geschaeft_uid"] in guids]
    uids = {d["dokument_uid"] for d in dok}
    orph = [
        dict(id=d["id"], url=d["url"], uid=canton_uid(d["url"]))
        for d in iter_docs_meta({"BE"})
        if not d["a"] and not d["ag"] and not d["m"] and canton_uid(d.get("url")) in uids
    ]
    ev = be.answer_events(ids)
    v40 = {r["affair_number"]: r for r in json.loads((OUT / "be_verify40.json").read_text())["rows"]}
    smp = {r["affair_number"]: r for r in json.loads((OUT / "be_relink_sample.json").read_text())["rows"]}
    pdfs = {}
    for r in exp:
        n = r["affair_number"]
        if n in smp:  # the OPD copy that would be re-attached
            pdfs[n] = dict(url=smp[n]["opd_url"], sha256=smp[n]["pdf_sha256"], copy="opd_parentless")
        else:  # the canton's source document
            pdfs[n] = dict(url=v40[n]["source_url"], sha256=v40[n]["pdf_sha256"], copy="canton_ogd")
    for name, rows_ in (("ogd_dokument.csv", dok), ("ogd_geschaeft.csv", ges)):
        with open(DEMO / name, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, list(rows_[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(rows_)
    (DEMO / "slice.json").write_text(
        json.dumps(
            dict(
                note="5 BE affairs; every field the bulk join reads, from the 2026-10-06 OPD exports "
                "and 2026-10-08 canton OGD tables",
                affairs=sorted(aff.values(), key=lambda a: a["id"]),
                parentless_docs=orph,
                answer_events={str(k): v for k, v in ev.items()},
                expected=exp,
                pdfs=pdfs,
            ),
            ensure_ascii=False,
            indent=1,
        )
    )
    print("demo slice:", len(dok), "dokument rows,", len(orph), "parentless docs")


def run() -> int:
    s = json.loads((DEMO / "slice.json").read_text())
    answers, geschaeft = be.load_ogd_files(DEMO / "ogd_dokument.csv", DEMO / "ogd_geschaeft.csv")
    affairs = {a["id"]: a for a in s["affairs"]}
    orph = {d["uid"]: d for d in s["parentless_docs"]}
    rows, c = be.join(answers, affairs, orph)
    got = [
        (r["affair_number"], r["action"], "" if r["opd_doc_id"] is None else str(r["opd_doc_id"]), r["source_doc_uid"])
        for r in rows
    ]
    exp = sorted((r["affair_number"], r["action"], r["opd_doc_id"], r["source_doc_uid"]) for r in s["expected"])
    ok_join = sorted(got) == exp
    print(f"[repair] BE bulk join on the vendored slice: {dict(c)}  reproduces expected rows: {'PASS' if ok_join else 'FAIL'}")
    full = list(csv.DictReader(open(OUT / "repair_BE.tsv", encoding="utf-8"), delimiter="\t"))
    n_rel = sum(r["action"] == "relink" for r in full)
    n_fet = sum(r["action"] == "fetch" for r in full)
    reg = be.regress(
        [
            dict(r, affair_id=int(r["affair_id"]), opd_doc_id=int(r["opd_doc_id"]) if r["opd_doc_id"] else None)
            for r in full
            if r["action"] in ("relink", "fetch")
        ]
    )
    ok_full = n_rel == 2459 and n_fet == 49 and reg["identical"]
    print(
        f"[repair] committed BE list: {n_rel} relink + {n_fet} fetch; "
        f"identical to the list delivered to OPD: {reg['identical']}  "
        f"{'PASS' if ok_full else 'FAIL'}"
    )
    by_nr = {g["geschaeft_nr"]: g for g in geschaeft.values()}
    n_checked = 0
    for r in rows:
        n = r["affair_number"]
        p = s["pdfs"][n]
        try:
            sha, path = pdftext.fetch_pdf(p["url"], expect_sha256=p["sha256"])
        except Exception as e:
            print(f"[repair]   {n}: document not fetched ({type(e).__name__}); triple check skipped (offline?)")
            continue
        text = "\n".join(pdftext.extract(sha, path, ocr=False)["pages"])
        chk = be.verify_text(
            text, n, (by_nr.get(n) or {}).get("geschaeft_vorstoss_nummer"), s["answer_events"].get(str(r["affair_id"]), [])
        )
        n_checked += 1
        print(
            f"[repair]   {n:<15} {r['action']:<6} identity={chk['identity']!s:<5} heading={chk['heading']!s:<5} "
            f"RRB {chk['rrb_nr']} vom {chk['rrb_date']} vs OPD event {chk['opd_answer_events']} -> "
            f"{'verified' if chk['triple'] else 'REVIEW (date mismatch)' if chk['identity'] and chk['heading'] else 'REJECT'}"
        )
    expected_fail = {"2015.RRGR.870"}
    print(f"[repair] triple check run on {n_checked}/{len(rows)} documents (expected review: {sorted(expected_fail)})")
    return 0 if ok_join and ok_full else 1


def main(argv: list[str]) -> int:
    if argv and argv[0] == "build":
        build()
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
