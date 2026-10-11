"""The P7 tier in the adapter-list columns, and adapters_X.tsv marked as a test artefact in the manifest."""
import csv
import json

from gegenprobe.paths import RESULTS
from gegenprobe.repair.adapters import promoted_list, run


def _tsv(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_promoted_tier_in_adapter_list_columns_is_reproducible(tmp_path):
    rows = promoted_list.build()
    out = tmp_path / "p.tsv"
    promoted_list.write(rows, out)
    assert out.read_bytes() == promoted_list.OUT.read_bytes()
    header = open(promoted_list.OUT, encoding="utf-8").readline().rstrip("\n").split("\t")
    assert header[:len(run.LIST_COLS)] == run.LIST_COLS and all(c.startswith("p7_") for c in header[len(run.LIST_COLS):])
    assert len(rows) == len(_tsv(promoted_list.J.OUT / "promoted.tsv"))
    assert {(r["tier"], r["counted"], r["verified"], r["action"]) for r in rows} == {
        ("promoted_by_apertus", "false", "false", "review")}
    assert all(r["source_url"] and r["target_category"] == "response_text" and r["proposed_action"] for r in rows)


def test_manifest_marks_the_header_only_test_list():
    m = json.loads((RESULTS / "repair" / "MANIFEST.json").read_text())
    x = next(f for f in m["files"] if f["file"].endswith("adapters_X.tsv"))
    assert x["kind"].startswith("test artefact") and x["rows"] == 0
    assert not any(o["body"] == "X" for o in m["overlaps"])
    assert {f["file"] for f in m["files"] if f["file"].endswith("p7/promoted_by_apertus.tsv")}
