"""Bern apply plan (repair/apply_be.py) on fixtures: before/after state, OPD's identifier rule, guards, dry run."""
import csv
import gzip
import hashlib
import json

from gegenprobe.repair import apply_be

URL = "https://www.rrgr-service.apps.be.ch/api/rr/documents/document/{}-332/1/x.pdf"


def h(pt, url):
    return hashlib.sha256(f"BE{pt}{url}".encode()).hexdigest()


def _doc(i, pt="agenda", affair=None, agenda=None, bad_hash=False):
    url = URL.format(f"{i:032x}")
    hh = "0" * 64 if bad_hash else h(pt, url)
    return dict(id=i, body_key="BE", parent_type=pt, url=url, hash=hh, url_oparl=f"https://files.openparldata.ch/doc/BE/{hh}",
                affair_id=affair, agenda_id=agenda, meeting_id=None, text="(dropped)")


def _fixture(tmp_path):
    docs = [_doc(1), _doc(2, pt="affair", affair=20), _doc(3, pt="affair", affair=99), _doc(5, bad_hash=True),
            _doc(6, agenda=7)]
    exp = tmp_path / "docs_BE.ndjson.gz"
    with gzip.open(exp, "wt", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d) + "\n")
    rel = tmp_path / "relink.tsv"
    rows = [(1, 10), (2, 20), (3, 30), (4, 40), (5, 50), (6, 60)]
    rel.write_text("body\taffair_id\taffair_number\taction\topd_doc_id\tsource_doc_uid\tverified\n" +
                   "".join(f"BE\t{a}\t2014.RRGR.{a}\trelink\t{d}\tuid{d}\ttrue\n" for d, a in rows))
    bd = tmp_path / "begin.tsv"
    bd.write_text("body\taffair_id\taffair_number\taction\tgroup\topd_group\tcurrent_begin_date\tproposed_begin_date\t"
                  "evidence_event_id\tevidence_event_date\tevidence_event_title\tsnapshot\tnote\n"
                  "BE\t10\t2011.RRGR.1\tset_begin_date\tload_2024_10_28\tload_2024_10_28\t2024-10-28\t2011-03-28\t7\t2011-03-28\tEingereicht\ts\t\n"
                  "BE\t11\t2011.RRGR.2\treview\tno_events\tlater_load\t2023-05-07\t\t\t\t\ts\tno events in OPD\n"
                  "BE\t12\t2011.RRGR.3\tset_begin_date\tload_2024_10_28\tload_2024_10_28\t2024-10-28\t2011-04-01\t8\t2011-04-01\tEingereicht\ts\t\n")
    return exp, rel, bd


def _run(tmp_path, *extra):
    exp, rel, bd = _fixture(tmp_path)
    out = tmp_path / "plan"
    rc = apply_be.main(["--docs-export", str(exp), "--relink", str(rel), "--begin-date", str(bd), "--out", str(out), *extra])
    assert rc == 0
    rows = {int(r["opd_doc_id"]): r for r in csv.DictReader(open(out / "apply_BE_relink_plan.csv", encoding="utf-8"))}
    begin = {int(r["affair_id"]): r for r in csv.DictReader(open(out / "apply_BE_begin_date_plan.csv", encoding="utf-8"))}
    return out, rows, begin


def test_relink_statuses_and_recomputed_identifier(tmp_path):
    out, rows, _ = _run(tmp_path)
    assert {d: r["status"] for d, r in rows.items()} == {
        1: "apply", 2: "already_attached", 3: "attached_elsewhere", 4: "not_in_export", 5: "hash_rule_mismatch",
        6: "attached_elsewhere"}
    r = rows[1]
    assert (r["before_parent_type"], r["before_affair_id"], r["hash_rule_holds"]) == ("agenda", "", "true")
    assert r["before_hash"] == h("agenda", r["url"])
    assert r["after_hash"] == h("affair", r["url"]) and r["identifier_changes"] == "true"
    assert r["after_url_oparl"] == f"https://files.openparldata.ch/doc/BE/{r['after_hash']}"
    summary = json.loads((out / "apply_BE_plan.json").read_text())
    assert summary["dry_run"] is True and summary["export_identifier_rule"]["rows"] == 5
    assert summary["export_identifier_rule"]["follow_rule"] == 4  # doc 5 carries a hash that is not the rule's


def test_statements_are_guarded_by_the_before_state(tmp_path):
    out, rows, _ = _run(tmp_path)
    sql = (out / "apply_BE_plan.sql.txt").read_text().splitlines()
    ups = [s for s in sql if s.startswith("UPDATE")]
    assert len(ups) == 1 + 2  # one relink (doc 1), two begin dates (affairs 10, 12)
    doc = next(s for s in ups if "UPDATE docs" in s)
    assert f"hash = '{rows[1]['after_hash']}'" in doc and f"AND hash = '{rows[1]['before_hash']}'" in doc
    assert "WHERE id = 1 AND body_key = 'BE' AND parent_type = 'agenda' AND affair_id IS NULL" in doc
    assert sql[4] == "BEGIN;" and sql[-1] == "COMMIT;"
    assert all("begin_date::date = '2024-10-28'" in s for s in ups if "UPDATE affairs" in s)


def test_keep_hash_mode(tmp_path):
    out, rows, _ = _run(tmp_path, "--hash", "keep")
    assert rows[1]["after_hash"] == rows[1]["before_hash"] and rows[1]["identifier_changes"] == "false"
    assert rows[5]["status"] == "apply"  # keeping the identifier does not need the rule
    doc = [s for s in (out / "apply_BE_plan.sql.txt").read_text().splitlines() if s.startswith("UPDATE docs")]
    assert len(doc) == 2 and all("SET parent_type = 'affair', affair_id =" in s and ", hash =" not in s for s in doc)


def test_begin_date_before_state_from_an_affairs_export(tmp_path):
    aff = tmp_path / "affairs.ndjson.gz"
    with gzip.open(aff, "wt", encoding="utf-8") as f:
        for a in (dict(id=10, begin_date="2024-10-28T00:00:00"), dict(id=12, begin_date="2011-04-01T00:00:00")):
            f.write(json.dumps(a) + "\n")
    _, _, begin = _run(tmp_path, "--affairs-export", str(aff))
    assert {a: r["status"] for a, r in begin.items()} == {10: "apply", 11: "affair_not_in_export", 12: "already_set"}
    assert begin[10]["before_source"] == "affairs export"


def test_default_is_a_dry_run_that_writes_nothing(tmp_path, capsys):
    exp, rel, bd = _fixture(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert apply_be.main(["--docs-export", str(exp), "--relink", str(rel), "--begin-date", str(bd)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    cap = capsys.readouterr()
    assert "dry run" in cap.err and json.loads(cap.out)["relink"]["by_status"]["apply"] == 1


def test_committed_plan_matches_the_list():
    """The committed plan (10 Oct 2026 docs_BE export) covers every verified relink and every begin_date row."""
    from gegenprobe.paths import RESULTS
    s = json.loads((RESULTS / "repair" / "apply_be" / "apply_BE_plan.json").read_text())
    n_rel = sum(1 for _ in open(RESULTS / "repair" / "repair_BE_relink.tsv", encoding="utf-8")) - 1
    assert s["relink"]["rows"] == n_rel == sum(s["relink"]["by_status"].values())
    assert s["export_identifier_rule"]["rows"] == s["export_identifier_rule"]["follow_rule"]
    assert s["relink"]["before_parent_type"] == {"agenda": s["relink"]["checked"]}
