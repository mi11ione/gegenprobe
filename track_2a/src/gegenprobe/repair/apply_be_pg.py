"""Run the Bern apply plan (results/repair/apply_be/apply_BE_plan.sql.txt) on a real PostgreSQL, not just as text.

The plan is generated as text and never executed by Gegenprobe against OPD. This check executes it, unchanged, against a
throw-away database whose `docs` and `affairs` tables hold exactly the plan's before-state, rebuilt from the committed
join (apply_BE_relink_plan.csv, apply_BE_begin_date_plan.csv). Table and column names are the ones the plan assumes (the
export's field names; COLUMN_MAPPING.md next to the plan maps them to OPD's schema). Four checks:

  1 apply        psql -v ON_ERROR_STOP=1 -f <plan> succeeds; exactly 2,975 rows differ from the before-state
                 (2,421 docs relinks + 554 affairs begin_date), each now holding the plan's after-value; the 173 begin_date
                 rows the plan leaves to review are untouched
  2 re-run       the same plan on the applied state: every guard misses, the DO block raises, psql fails, nothing changes
  3 perturbed    before-state with ONE row changed (one document's hash): the statement for it changes 0 rows, the DO block
                 raises ("2974 rows changed"), and the whole transaction rolls back: all 2,975 other rows unchanged
  4 perturbed    the same with one affair's begin_date changed

Connection: the usual libpq variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE) for `psql`; the tables are created
in a schema of their own (`gp_apply_be_check`, dropped first), so the check never touches anything else.

    python -m gegenprobe.repair.apply_be_pg [--out results.json] [--psql psql]   exit 0 = all four checks hold

CI: job `apply-be-postgres` in .github/workflows/ci.yml (PostgreSQL service container).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

from ..paths import RESULTS

PLAN_DIR = RESULTS / "repair" / "apply_be"
SCHEMA = "gp_apply_be_check"
HEX64 = re.compile(r"[0-9a-f]{64}")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def _rows(name: str) -> list[dict]:
    with open(PLAN_DIR / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _int(v: str) -> str:
    return "NULL" if v in ("", None) else str(int(v))


def _lit(v: str, pat: re.Pattern | None = None) -> str:
    if v in ("", None):
        return "NULL"
    if pat is not None:
        assert pat.fullmatch(v), v
    return "'" + v.replace("'", "''") + "'"


def before_state_sql(perturb: str | None = None) -> str:
    """CREATE + INSERT of the plan's before-state. perturb: None | "doc" (one document's hash changed) | "affair" (one
    affair's begin_date changed by a day)."""
    relink = _rows("apply_BE_relink_plan.csv")
    begin = _rows("apply_BE_begin_date_plan.csv")
    out = [f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;", f"CREATE SCHEMA {SCHEMA};", f"SET search_path TO {SCHEMA};",
           "CREATE TABLE docs (id bigint PRIMARY KEY, body_key text NOT NULL, parent_type text, affair_id bigint, "
           "agenda_id bigint, meeting_id bigint, hash text, url text, url_oparl text);",
           "CREATE TABLE affairs (id bigint PRIMARY KEY, body_key text NOT NULL, begin_date date);"]
    vals = []
    for i, r in enumerate(relink):
        h = r["before_hash"]
        if perturb == "doc" and i == len(relink) // 2:
            h = h[:-1] + ("0" if h[-1] != "0" else "1")
        vals.append(f"({_int(r['opd_doc_id'])}, 'BE', {_lit(r['before_parent_type'])}, {_int(r['before_affair_id'])}, "
                    f"{_int(r['before_agenda_id'])}, {_int(r['before_meeting_id'])}, {_lit(h, HEX64)}, {_lit(r['url'])}, "
                    f"{_lit(r['before_url_oparl'])})")
    out.append("INSERT INTO docs VALUES\n" + ",\n".join(vals) + ";")
    vals = []
    applied = [r for r in begin if r["status"] == "apply"]
    for r in begin:
        d = r["before_begin_date"]
        if perturb == "affair" and r is applied[len(applied) // 2]:
            d = f"{d[:8]}{int(d[8:]) % 28 + 1:02d}"  # another day of the same month
        vals.append(f"({_int(r['affair_id'])}, 'BE', {_lit(d, ISO)})")
    out.append("INSERT INTO affairs VALUES\n" + ",\n".join(vals) + ";")
    out += ["CREATE TABLE docs_before AS SELECT * FROM docs;", "CREATE TABLE affairs_before AS SELECT * FROM affairs;"]
    return "\n".join(out) + "\n"


def expected_after_sql() -> str:
    relink = [r for r in _rows("apply_BE_relink_plan.csv") if r["status"] == "apply"]
    begin = [r for r in _rows("apply_BE_begin_date_plan.csv") if r["status"] == "apply"]
    out = [f"SET search_path TO {SCHEMA};",
           "CREATE TABLE docs_want (id bigint PRIMARY KEY, parent_type text, affair_id bigint, hash text);",
           "CREATE TABLE affairs_want (id bigint PRIMARY KEY, begin_date date);"]
    out.append("INSERT INTO docs_want VALUES\n" + ",\n".join(
        f"({_int(r['opd_doc_id'])}, {_lit(r['after_parent_type'])}, {_int(r['after_affair_id'])}, "
        f"{_lit(r['after_hash'] if r['identifier_changes'] == 'true' else r['before_hash'], HEX64)})" for r in relink) + ";")
    out.append("INSERT INTO affairs_want VALUES\n" + ",\n".join(
        f"({_int(r['affair_id'])}, {_lit(r['after_begin_date'], ISO)})" for r in begin) + ";")
    return "\n".join(out) + "\n"


# one row of numbers: rows that differ from the before-state, rows that hold the planned after-value, review rows touched
MEASURE = f"""SET search_path TO {SCHEMA};
SELECT
 (SELECT count(*) FROM docs d JOIN docs_before b USING (id)
   WHERE (d.parent_type, d.affair_id, d.agenda_id, d.meeting_id, d.hash, d.body_key)
         IS DISTINCT FROM (b.parent_type, b.affair_id, b.agenda_id, b.meeting_id, b.hash, b.body_key)),
 (SELECT count(*) FROM affairs a JOIN affairs_before b USING (id) WHERE a.begin_date IS DISTINCT FROM b.begin_date),
 (SELECT count(*) FROM docs d JOIN docs_want w USING (id)
   WHERE (d.parent_type, d.affair_id, d.hash) = (w.parent_type, w.affair_id, w.hash)),
 (SELECT count(*) FROM affairs a JOIN affairs_want w USING (id) WHERE a.begin_date = w.begin_date),
 (SELECT count(*) FROM affairs a JOIN affairs_before b USING (id)
   WHERE a.id NOT IN (SELECT id FROM affairs_want) AND a.begin_date IS DISTINCT FROM b.begin_date),
 (SELECT md5(string_agg(d::text, '|' ORDER BY id)) FROM docs d),
 (SELECT md5(string_agg(a::text, '|' ORDER BY id)) FROM affairs a);
"""


class Psql:
    def __init__(self, exe: str = "psql"):
        self.exe = exe

    def run(self, sql: str | None = None, file: Path | None = None, search_path: bool = False) -> subprocess.CompletedProcess:
        args = [self.exe, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-At", "-F", ","]
        env = None
        if search_path:  # the plan has unqualified table names: point the session at the check schema
            import os
            env = dict(os.environ, PGOPTIONS=f"-c search_path={SCHEMA}")
        if file is not None:
            return subprocess.run(args + ["-f", str(file)], capture_output=True, text=True, env=env)
        return subprocess.run(args, input=sql, capture_output=True, text=True, env=env)

    def ok(self, sql: str) -> str:
        r = self.run(sql)
        if r.returncode != 0:
            raise RuntimeError(f"psql failed ({r.returncode}): {r.stderr.strip()[:2000]}")
        return r.stdout.strip()

    def measure(self) -> dict:
        v = self.ok(MEASURE).splitlines()[-1].split(",")
        return dict(docs_changed=int(v[0]), affairs_changed=int(v[1]), docs_at_after_value=int(v[2]),
                    affairs_at_after_value=int(v[3]), review_rows_changed=int(v[4]), docs_md5=v[5], affairs_md5=v[6])


def check(psql: Psql, plan: Path) -> dict:
    expected = int(re.search(r"expected_rows_changed: (\d+)", plan.read_text()).group(1))
    n_rel = sum(r["status"] == "apply" for r in _rows("apply_BE_relink_plan.csv"))
    n_beg = sum(r["status"] == "apply" for r in _rows("apply_BE_begin_date_plan.csv"))
    n_review = sum(r["status"] != "apply" for r in _rows("apply_BE_begin_date_plan.csv"))
    res = dict(plan=str(plan.relative_to(PLAN_DIR.parents[2])) if plan.is_relative_to(PLAN_DIR.parents[2]) else str(plan),
               expected_rows_changed=expected, relinks=n_rel, begin_dates=n_beg, begin_date_review_rows=n_review,
               server=psql.ok("SHOW server_version;"), checks={})

    def setup(perturb=None):
        psql.ok(before_state_sql(perturb))
        psql.ok(expected_after_sql())
        return psql.measure()

    def stage(perturb):
        before = setup(perturb)
        r = psql.run(file=plan, search_path=True)
        return before, r, psql.measure()

    # 1 apply
    b0, r, a = stage(None)
    c1 = dict(psql_exit=r.returncode, stderr=r.stderr.strip()[-300:], **{k: a[k] for k in a if not k.endswith("md5")})
    c1["ok"] = (r.returncode == 0 and a["docs_changed"] + a["affairs_changed"] == expected
                and a["docs_changed"] == n_rel and a["affairs_changed"] == n_beg
                and a["docs_at_after_value"] == n_rel and a["affairs_at_after_value"] == n_beg
                and a["review_rows_changed"] == 0 and b0["docs_changed"] == 0)
    res["checks"]["1_apply"] = c1
    # 2 re-run on the applied state
    r2 = psql.run(file=plan, search_path=True)
    a2 = psql.measure()
    res["checks"]["2_rerun"] = dict(psql_exit=r2.returncode, stderr=r2.stderr.strip()[-300:],
                                    unchanged=(a2["docs_md5"], a2["affairs_md5"]) == (a["docs_md5"], a["affairs_md5"]))
    res["checks"]["2_rerun"]["ok"] = r2.returncode != 0 and "rolled back" in r2.stderr and res["checks"]["2_rerun"]["unchanged"]
    # 3/4 one perturbed row: full rollback
    for key, perturb in (("3_perturbed_doc", "doc"), ("4_perturbed_affair", "affair")):
        b, r, a = stage(perturb)
        m = re.search(r"(\d+) rows changed by (\d+) statements \((\d+) not exactly 1\)", r.stderr)
        res["checks"][key] = dict(psql_exit=r.returncode, stderr=r.stderr.strip()[-300:],
                                  rows_changed_before_rollback=int(m.group(1)) if m else None,
                                  statements_off=int(m.group(3)) if m else None,
                                  unchanged=(a["docs_md5"], a["affairs_md5"]) == (b["docs_md5"], b["affairs_md5"]),
                                  docs_changed=a["docs_changed"], affairs_changed=a["affairs_changed"])
        c = res["checks"][key]
        c["ok"] = (r.returncode != 0 and c["unchanged"] and a["docs_changed"] == 0 and a["affairs_changed"] == 0
                   and c["rows_changed_before_rollback"] == expected - 1 and c["statements_off"] == 1)
    psql.ok(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;")
    res["ok"] = all(c["ok"] for c in res["checks"].values())
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", default=str(PLAN_DIR / "apply_BE_plan.sql.txt"))
    ap.add_argument("--psql", default="psql")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    plan = Path(a.plan).resolve()
    res = check(Psql(a.psql), plan)
    txt = json.dumps(res, indent=1).replace(str(plan.parent) + "/", "")  # no local paths in the committed result
    if a.out:
        Path(a.out).write_text(txt + "\n")
    print(txt)
    for k, c in res["checks"].items():
        print(f"{'PASS' if c['ok'] else 'FAIL'} {k}", file=sys.stderr)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
