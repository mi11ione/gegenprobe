"""Round 18 data corrections: the logged re-tiering of Valais's date_window fetch rows, the v0.2 role coverage of P8's
gold (post hoc) and the one count of validated v0.2 records. Committed files only; no network, no model."""
import hashlib
import json

from gegenprobe.census import corrected as cc
from gegenprobe.paths import RESULTS, ROOT
from gegenprobe.repair import manifest
from gegenprobe.repair.adapters import retier
from gegenprobe.schema import v0_2_role_coverage as rc


def _j(*p):
    return json.loads(RESULTS.joinpath(*p).read_text(encoding="utf-8"))


def test_retier_file_is_what_the_module_computes_and_the_locked_list_is_untouched():
    assert retier.OUT.read_text(encoding="utf-8") == json.dumps(retier.build(), ensure_ascii=False, indent=1,
                                                                sort_keys=True) + "\n"
    d = _j("repair", "adapters", "retier", "retier_r18.json")
    lock8 = json.loads((ROOT / "eval" / "prereg8" / "LOCK8").read_text())
    locked = {k: v for x in lock8.values() if isinstance(x, dict) for k, v in x.items()}
    li = d["locked_inputs_unchanged"]
    assert locked[li["list"]] == li["sha256"] == hashlib.sha256((ROOT / li["list"]).read_bytes()).hexdigest()
    # the old audit is kept as committed history
    s = d["audit"]["committed_history"]
    assert hashlib.sha256((ROOT / s["file"]).read_bytes()).hexdigest() == s["sha256"]


def test_retier_selects_the_whole_valais_window_tier_and_explains_the_audit():
    d = _j("repair", "adapters", "retier", "retier_r18.json")
    assert d["n"] == 140 and {x["body"] for x in d["rows"]} == {"VS"}
    assert all(x["old"] == dict(tier="date_window", counted=True, action="fetch") for x in d["rows"])
    a = d["audit"]
    assert (a["moved_stratum_sampled"], a["moved_stratum_frame"]) == (14, 124)
    assert a["claude_in_moved_stratum"] == dict(is_answer_yes=12, date_ok_no=12, not_the_answer=2)
    t = a["tolerance_explains_dates"]
    # Claude's "date wrong" is exactly the offsets beyond the audit prompt's ~30-day tolerance
    assert t["offset_over_tolerance"] == t["offset_over_tolerance_claude_date_no"] == 12
    assert t["offset_within_tolerance"] == t["offset_within_tolerance_claude_date_yes"] == 2
    assert min(t["offsets_over"]) > 30 >= max(t["offsets_within"])
    after = a["after_retier"]["auditors"]
    assert after["claude"]["counted"] == "185/186" and after["claude"]["date_ok_no"] == 3
    assert after["qwen"]["counted"] == "186/186"
    assert (d["lists_before"]["counted"], d["lists_after"]["counted"]) == (6613, 6473)


def test_derived_layer_and_manifest_apply_the_retier():
    ad = cc.adapter_rows()
    moved = [a for a in ad.values() if a.get("retier") == "r18"]
    assert len(moved) == 140 and all(not a["counted"] and a["tier"] == "review" for a in moved)
    m = manifest.build()
    vs = next(f for f in m["files"] if f["file"].endswith("adapters_VS.tsv"))
    assert vs["counted"] - vs["counted_after_retier"] == 140
    assert m["retier"]["rows"] == 140
    assert any(p["wins"] == "retier file" for p in m["precedence"])


def test_v02_role_coverage_file_is_current_and_post_hoc():
    assert rc.OUT.read_text(encoding="utf-8") == json.dumps(rc.compute(), ensure_ascii=False, indent=1,
                                                            sort_keys=True) + "\n"
    d = _j("p8", "p8_v02_role_coverage.json")
    assert d["label"].startswith("POST HOC")
    s = d["summary"]
    assert len(s["role_split_fields"]) == 6 and s["named"] == s["determinable"] == 302
    assert s["cells_fully_named"] == s["cells"] == 58
    assert s["fields_whose_records_do_not_write_the_slot"] == ["addressed_body"]
    assert s["body_specific_field"]["unnamed"] == {"cited": 5, "other_printed": 1}


def test_one_count_of_validated_records():
    v = _j("schema", "v0_2", "validation_all.json")["validated_records"]
    assert (v["n_records"], v["n_parliaments"]) == (186, 26)
    assert (v["converter"]["n_records"], v["converter"]["n_parliaments"]) == (120, 23)
    assert v["converter"]["federal"]["n_records"] == 15 and v["converter"]["cantonal_and_communal"]["n_records"] == 105
    assert (v["p8_gold"]["n_records"], v["p8_gold"]["n_parliaments"]) == (66, 11)
    n = sum(1 for k in ("p3", "p3b", "p5", "fed", "p8")
            for x in (RESULTS / "schema" / "v0_2" / f"{k}_records.jsonl").read_text().splitlines() if x.strip())
    assert n == 186
