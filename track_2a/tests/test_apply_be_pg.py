"""The Bern apply plan on a real PostgreSQL (gegenprobe/repair/apply_be_pg.py; CI job apply-be-postgres). Offline here:
the before-state built from the committed join matches the plan's guards row for row; the committed result of the
local run (PostgreSQL 16) holds all four checks. With PGHOST set and psql on PATH, the full check runs."""
from __future__ import annotations

import json
import os
import re
import shutil

import pytest

from gegenprobe.repair import apply_be_pg as pg

PLAN = pg.PLAN_DIR / "apply_BE_plan.sql.txt"


def test_before_state_covers_every_guard():
    sql = pg.before_state_sql()
    plan = PLAN.read_text()
    docs = dict(re.findall(r"\((\d+), 'BE', 'agenda', NULL, NULL, NULL, '([0-9a-f]{64})'", sql))
    guards = re.findall(r"UPDATE docs SET .*? WHERE id = (\d+) AND body_key = 'BE' AND parent_type = 'agenda' "
                        r"AND affair_id IS NULL AND agenda_id IS NULL AND meeting_id IS NULL AND hash = '([0-9a-f]{64})'", plan)
    assert len(guards) == 2421 and all(docs.get(i) == h for i, h in guards)
    affairs = dict(re.findall(r"\((\d+), 'BE', '(\d{4}-\d{2}-\d{2})'\)", sql))
    bguards = re.findall(r"UPDATE affairs SET begin_date = '[\d-]+' WHERE id = (\d+) AND body_key = 'BE' "
                         r"AND begin_date::date = '([\d-]+)'", plan)
    assert len(bguards) == 554 and all(affairs.get(i) == d for i, d in bguards)
    assert len(affairs) == 727  # the 173 review rows are loaded too: the plan must leave them alone
    assert int(re.search(r"expected_rows_changed: (\d+)", plan).group(1)) == 2421 + 554 == 2975


@pytest.mark.parametrize("perturb", ["doc", "affair"])
def test_perturbation_breaks_exactly_one_guard(perturb):
    a, b = pg.before_state_sql(), pg.before_state_sql(perturb)
    diff = [x for x, y in zip(a.splitlines(), b.splitlines()) if x != y]
    assert len(diff) == 1


def test_committed_local_run_holds():
    r = json.loads((pg.PLAN_DIR / "apply_BE_pg_check.json").read_text())
    assert r["ok"] and r["expected_rows_changed"] == 2975
    c = r["checks"]
    assert c["1_apply"]["docs_changed"] == 2421 and c["1_apply"]["affairs_changed"] == 554
    assert c["1_apply"]["review_rows_changed"] == 0
    assert c["2_rerun"]["psql_exit"] != 0 and c["2_rerun"]["unchanged"]
    for k in ("3_perturbed_doc", "4_perturbed_affair"):
        assert c[k]["rows_changed_before_rollback"] == 2974 and c[k]["unchanged"] and c[k]["docs_changed"] == 0
    assert "/Users/" not in json.dumps(r) and "/home/" not in json.dumps(r)


@pytest.mark.skipif(not (os.environ.get("PGHOST") and shutil.which("psql")), reason="no PostgreSQL (CI job apply-be-postgres)")
def test_plan_on_postgres():
    r = pg.check(pg.Psql(), PLAN)
    assert r["ok"], json.dumps(r["checks"], indent=1)
