"""repair.apply_tags (round 8): the guarded plan for the adapter lists' tag rows, on a small export and list."""
import csv
import gzip
import hashlib
import json

from gegenprobe.repair import apply_tags
from gegenprobe.repair.adapters import run

TEXT = "Antwort des Regierungsrates vom 3. März 2025"


def _sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


def _list(tmp_path, rows):
    d = tmp_path / "lists"
    d.mkdir()
    with open(d / "adapters_NE.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, run.LIST_COLS, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(dict(dict(body="NE", counted="true", tier="exact_doc_date", check_detail="extractor=opd_export",
                                 affair_number=f"26.{r['affair_id']}", source_url=f"https://ne/{r['opd_doc_id']}.pdf"), **r))
    (d / "adapters_X.tsv").write_text("\t".join(run.LIST_COLS) + "\n")  # header-only lists contribute nothing
    return d


def _export(tmp_path, docs):
    p = tmp_path / "exports" / "docs" / "docs_NE.ndjson.gz"
    p.parent.mkdir(parents=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(dict(dict(body_key="NE", category_harmonized=None), **d)) + "\n")
    return tmp_path / "exports"


def test_plan_statuses_and_guards(tmp_path):
    rows = [
        dict(affair_id=1, opd_doc_id=11, action="tag_answer", text_sha256=_sha(TEXT)),      # apply
        dict(affair_id=2, opd_doc_id=12, action="tag_answer", text_sha256=_sha(TEXT)),      # text changed
        dict(affair_id=3, opd_doc_id=13, action="tag_answer", text_sha256=_sha(TEXT)),      # scraper-set category
        dict(affair_id=4, opd_doc_id=14, action="extract_tag", text_sha256=_sha("ocr")),    # apply (no text yet)
        dict(affair_id=5, opd_doc_id=15, action="extract_tag", text_sha256=_sha("ocr")),    # OPD has text now
        dict(affair_id=6, opd_doc_id=16, action="tag_answer", text_sha256=_sha(TEXT)),      # moved to another affair
        dict(affair_id=7, opd_doc_id=17, action="tag_answer", text_sha256=_sha(TEXT)),      # not in the export
        dict(affair_id=8, opd_doc_id=18, action="tag_answer", text_sha256=_sha("ours"),     # our own extraction, same url
             check_detail="extractor=pdftotext-26.02.0", source_url="https://zh/it's.pdf"),
        dict(affair_id=9, opd_doc_id=19, action="fetch", text_sha256=_sha(TEXT)),           # not a tag row
        dict(affair_id=10, opd_doc_id=20, action="tag_answer", text_sha256=_sha(TEXT), counted="false"),
    ]
    docs = [
        dict(id=11, affair_id=1, text=TEXT, url="https://ne/11.pdf"),
        dict(id=12, affair_id=2, text=TEXT + " (corrigé)", url="https://ne/12.pdf"),
        dict(id=13, affair_id=3, text=TEXT, url="https://ne/13.pdf", category_harmonized="recording_video"),
        dict(id=14, affair_id=4, text="", url="https://ne/14.pdf"),
        dict(id=15, affair_id=5, text="now OCRed", url="https://ne/15.pdf"),
        dict(id=16, affair_id=99, text=TEXT, url="https://ne/16.pdf"),
        dict(id=18, affair_id=8, text="OPD's own text", url="https://zh/it's.pdf"),
    ]
    lists, ex = _list(tmp_path, rows), _export(tmp_path, docs)
    out = tmp_path / "plan"
    assert apply_tags.main(["--exports-dir", str(ex), "--lists", str(lists), "--out", str(out)]) == 0
    plan = {int(r["affair_id"]): r for r in csv.DictReader(open(out / "apply_tags_plan.csv", encoding="utf-8"))}
    assert {a: r["status"] for a, r in plan.items()} == {
        1: "apply", 2: "text_changed", 3: "category_set", 4: "apply", 5: "text_now_present", 6: "affair_changed",
        7: "not_in_export", 8: "apply"}
    assert plan[3]["before_category_harmonized"] == "recording_video"  # never overwritten
    sql = (out / "apply_tags_plan.sql.txt").read_text().splitlines()
    ups = [s for s in sql if s.startswith("UPDATE")]
    assert len(ups) == 3 and sql[-1] == "COMMIT;" and any("PROTECTED OVERRIDE" in s for s in sql)
    assert all("category_harmonized IS NULL" in s and "body_key = 'NE'" in s for s in ups)
    assert f"= '{_sha(TEXT)}'" in ups[0] and "id = 11 " in ups[0]
    assert "(text IS NULL OR text = '')" in ups[1] and "url = 'https://ne/14.pdf'" in ups[1]
    assert "url = 'https://zh/it''s.pdf'" in ups[2] and _sha("OPD's own text") in ups[2]  # quote doubled
    summary = json.loads((out / "apply_tags_plan.json").read_text())
    assert summary["rows"] == 8 and summary["statements"] == 3 and summary["dry_run"] is True


def test_a_body_key_that_is_not_alphanumeric_is_refused():
    p = dict(status="apply", body="NE'; DROP", opd_doc_id=1, affair_id=1, list_action="tag_answer", guard="text_sha256",
             list_text_sha256="0" * 64, affair_number="x")
    try:
        apply_tags.statements([p])
    except AssertionError:
        return
    raise AssertionError("a malformed body key must not reach the SQL text")
