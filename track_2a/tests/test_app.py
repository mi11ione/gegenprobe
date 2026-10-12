"""The app (gegenprobe.app; site/): built from committed files only, reproducible byte for byte, the committed site/ is a
fresh build, every census intervention and every counted repair is in it, files stay small, and no document text beyond
the short quotes the committed lists and records carry. Offline, no model."""
import json
import re

import pytest

from gegenprobe.app import build as A
from gegenprobe.app import titles as T
from gegenprobe.paths import ROOT, RESULTS

SITE = ROOT / "site"
MiB = 1024 * 1024


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    one, two = tmp_path_factory.mktemp("one"), tmp_path_factory.mktemp("two")
    A.write(one)
    A.write(two)
    return one, two


def _j(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_build_is_reproducible_and_the_committed_site_is_a_fresh_build(built):
    """make site twice -> byte-identical; site/ as committed is exactly that build (no stale or hand-edited file)."""
    one, two = built
    assert A.tree_hash(one) == A.tree_hash(two)
    assert A.tree_hash(SITE) == A.tree_hash(one), "site/ is not a fresh build: run make site"


def test_every_intervention_and_every_repair(built):
    one = built[0]
    core, ix, q = _j(one / "data" / "core.json"), _j(one / "data" / "index.json"), _j(one / "data" / "queue.json")
    b = core["bound"]
    assert core["census_rows"] == b["written"] == 91268
    assert len(ix["id"]) == len(ix["num"]) == len(ix["st"]) == len(ix["ty"]) == len(ix["yr"]) == core["rows"]
    assert core["rows"] - core["census_rows"] == ix["st"].count("n")  # affairs shown only for their v0.2 record
    assert len(set(ix["id"])) == len(ix["id"])
    assert len(q["i"]) == b["repaired"] == 9580 and len(set(q["i"])) == len(q["i"])
    steps = {s: q["step"].count(s) for s in ("now", "after_hash", "fetch")}
    assert steps == {"now": b["now"], "after_hash": b["after_hash"], "fetch": b["fetch"]} == \
        {"now": 3621, "after_hash": 2459, "fetch": 3500}
    # the Bern relinks after the hash decision: the 2,421 verified relinks of the plan + 38 review rows
    be = [k for k in range(len(q["i"])) if q["step"][k] == "after_hash"]
    assert sum(q["p"][k] for k in be) == 2421 and sum(q["r"][k] for k in be) == 38 and all(q["h"][k] for k in be)
    # each parliament's rows are contiguous and its counts are the derived census layer's
    corr = _j(RESULTS / "census" / "corrected.json")["by_body"]
    for body in core["bodies"]:
        st = ix["st"][body["start"]:body["start"] + body["n"]]
        c = corr.get(body["key"], {}).get("all")
        if c:
            assert st.count("a") == c["attached"] and st.count("o") == c["oral"], body["key"]
            assert sum(st.count(x) for x in "RBbTXFf") == c["repaired"], body["key"]


def test_parliament_counts_are_the_queue_rows_per_action_and_step(built):
    """The Parliaments table and a parliament's page count exactly the repair queue's rows of that parliament, per
    action and per step; Bern's relink 2,976 = 517 agenda joins (apply now) + 2,459 relinks after the hash decision
    (2,421 in the plan + 38 review); the plan's 554 begin_date corrections (another field) are not repairs."""
    one = built[0]
    core, q = _j(one / "data" / "core.json"), _j(one / "data" / "queue.json")
    key_of = {r: b["key"] for b in core["bodies"] for r in range(b["start"], b["start"] + b["n"])}
    acts, steps = {}, {}
    for r, a, s in zip(q["i"], q["a"], q["step"]):
        k = key_of[r]
        acts.setdefault(k, {}).setdefault(core["actions"][a], 0)
        acts[k][core["actions"][a]] += 1
        steps.setdefault(k, {}).setdefault(s, 0)
        steps[k][s] += 1
    for b in core["bodies"]:
        assert b["by_action"] == acts.get(b["key"], {}), b["key"]
        assert b["by_step"] == steps.get(b["key"], {}), b["key"]
        assert sum(b["by_action"].values()) == sum(b["by_step"].values()) == b["repaired"], b["key"]
    bd = core["bound"]
    for s in ("now", "after_hash", "fetch"):
        assert sum(b["by_step"].get(s, 0) for b in core["bodies"]) == bd[s], s
    assert A.queue_counts(core["bodies"], q) == {b["key"]: (b["by_action"], b["by_step"]) for b in core["bodies"]}
    be = next(b for b in core["bodies"] if b["key"] == "BE")
    assert be["by_action"] == {"relink": 2976, "fetch": 49} and be["repaired"] == 3025
    assert be["by_step"] == {"now": 517, "after_hash": 2459, "fetch": 49} and be["by_code"]["R"] == 517
    # the SQL plan: 2,975 statements = 2,421 relinks (queue rows marked p) + 554 begin_date corrections, not counted
    plan = (SITE / "downloads" / "apply_BE_plan.sql.txt").read_text(encoding="utf-8")
    begin = re.findall(r"^WITH u AS \(UPDATE affairs SET begin_date = ", plan, re.M)
    assert len(begin) == 554 and "expected_rows_changed: 2975" in plan
    assert sum(q["p"]) == 2975 - len(begin) == 2421


def test_lookup_finds_the_example_affair(built):
    one = built[0]
    core, ix = _j(one / "data" / "core.json"), _j(one / "data" / "index.json")
    r = ix["id"].index(39369)
    assert ix["num"][r] == "2021.RRGR.388" and ix["st"][r] == "a"
    body = next(b for b in core["bodies"] if b["start"] <= r < b["start"] + b["n"])
    assert body["key"] == "BE" and body["name"] == "Bern (canton)"
    shard = _j(one / "data" / "s" / f"{body['shard'] + (r - body['start']) // core['shard_rows']}.json")
    row = shard[(r - body["start"]) % core["shard_rows"]]
    assert row[0] == 39369 and row[1] == "Nachhaltige Bewirtschaftung im Berner Wald" and row[12] & 2  # has a record
    rec = _j(one / "data" / "r" / "39369.json")
    located = [c for c in rec["cells"] if c.get("bb")]
    assert located and all(c["pg"] and c["ce"] > c["cs"] for c in located if c.get("cs") is not None)
    assert any(c["k"] == "n" and c.get("nr") for c in rec["cells"])  # typed gaps with their reason
    # a title word finds it through its bucket
    tok = _j(one / "data" / "t" / "be.json")
    k = tok["w"].index("bewirtschaftung")
    rows, acc = [], 0
    for j, d in enumerate(tok["p"][k]):
        acc = d if j == 0 else acc + d
        rows.append(acc)
    assert r in rows


def test_bern_relink_rows_carry_the_hash_decision_and_the_plan(built):
    one = built[0]
    core, ix = _j(one / "data" / "core.json"), _j(one / "data" / "index.json")
    r = ix["id"].index(127848)  # 2013.RRGR.10100: a verified Bern relink
    body = next(b for b in core["bodies"] if b["start"] <= r < b["start"] + b["n"])
    row = _j(one / "data" / "s" / f"{body['shard'] + (r - body['start']) // core['shard_rows']}.json")[
        (r - body["start"]) % core["shard_rows"]]
    fix = row[10]
    assert ix["st"][r] == "B" and fix["a"] == "relink" and fix["h"] == 1 and fix["p"] == 1 and fix["d"] == "402692"
    assert fix["hb"] != fix["ha"] and fix["f"] == "results/repair/repair_BE_relink.tsv"


def test_bern_sql_subset_is_extractable_per_row():
    """The queue's Bern SQL export copies the plan's statements verbatim: one statement line per relink, found by the
    affair id the app's regular expression reads (app.js exportSQL)."""
    plan = (SITE / "downloads" / "apply_BE_plan.sql.txt").read_text(encoding="utf-8")
    js = (A.APP / "app.js").read_text(encoding="utf-8")
    assert "^WITH u AS \\(UPDATE docs SET parent_type = 'affair', affair_id = (\\d+)," in js
    ids = re.findall(r"^WITH u AS \(UPDATE docs SET parent_type = 'affair', affair_id = (\d+),", plan, re.M)
    relink = {int(x["affair_id"]) for x in A._rows_csv(RESULTS / "repair" / "apply_be" / "apply_BE_relink_plan.csv")}
    assert len(ids) == len(set(ids)) == len(relink) == 2421 and {int(x) for x in ids} == relink
    assert "expected_rows_changed: 2975" in plan and plan.count("DO $$") == 1


def test_sizes_upfront_and_per_file(built):
    one = built[0]
    s = A.sizes(one)
    assert s["upfront_kb"] <= 2600, s["upfront"]  # index.html + app.js + app.css + core.json + index.json
    assert all(p.stat().st_size < 25 * MiB for p in one.rglob("*") if p.is_file())  # Cloudflare's per-file limit
    assert s["shard_max_kb"] <= 512 and s["token_max_kb"] <= 512 and s["files"] < 20000


def test_no_document_text_beyond_short_quotes(built):
    one = built[0]
    for p in (one / "data" / "s").glob("*.json"):
        for row in _j(p):
            for fix in (row[10], row[11]):
                if fix:
                    assert len(fix.get("q", "")) <= A.QUOTE_MAX and len(fix.get("rr", "")) <= 240
    for p in (one / "data" / "r").glob("*.json"):
        for c in _j(p)["cells"]:
            assert len(c.get("v", "")) <= A.VALUE_MAX and len(c.get("q", "")) <= A.VALUE_MAX


def test_titles_slice_covers_every_row():
    t = T.load()
    with __import__("gzip").open(RESULTS / "census" / "interventions.tsv.gz", "rt", encoding="utf-8") as f:
        ids = {int(line.split("\t")[1]) for line in list(f)[1:]}
    assert ids <= set(t) and T.record_ids() <= set(t)
    assert t[39369]["title_de"] == "Nachhaltige Bewirtschaftung im Berner Wald"


def test_fonts_self_hosted_and_licensed():
    css = (A.APP / "app.css").read_text(encoding="utf-8")
    assert "googleapis" not in css and "gstatic" not in css
    urls = set(re.findall(r'url\("(fonts/[^"]+)"\)', css))
    assert urls and all((SITE / u).exists() for u in urls), urls
    assert all((SITE / "fonts" / f).exists() for f in ("OFL-Archivo.txt", "OFL-IBM-Plex-Mono.txt", "SOURCES.txt"))


def test_routes_and_views():
    js = (A.APP / "app.js").read_text(encoding="utf-8")
    page = (A.APP / "index.html").read_text(encoding="utf-8")
    for v in ("lookup", "parliaments", "parliament", "queue", "about"):
        assert f'id="v-{v}"' in page, v
    for r in ("#/affair/", "#/parliament/", "#/parliaments", "#/queue", "#/about"):
        assert r in js or r in page, r
    assert 'data-claims="about"' in js and 'data-claims="queue"' in js and 'data-claims="lookup"' in js
