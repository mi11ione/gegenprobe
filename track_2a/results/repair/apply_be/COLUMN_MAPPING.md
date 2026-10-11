# Column mapping for `apply_BE_plan.sql.txt`

The plan uses the field names of OPD's public exports (`docs_BE.ndjson.gz`, `affairs` export) as table and column names.
We have not seen OPD's database schema. Map each name below to the real one before running the plan. If a table or column
has another name, a plain search-and-replace on the statement text is enough: every statement has the same shape.

| plan name | export field | role in the plan | check in OPD's schema |
|---|---|---|---|
| `docs` | docs export row | table of documents | the table that holds one row per document |
| `docs.id` | `id` | row key in every guard | the document's primary key |
| `docs.body_key` | `body_key` | guard (`= 'BE'`) | if the body is reached through a foreign key and is not a column, drop this guard: `id` + `hash` still identify the row |
| `docs.parent_type` | `parent_type` | guard `'agenda'`, set to `'affair'` | the polymorphic parent type and its allowed values |
| `docs.affair_id`, `docs.agenda_id`, `docs.meeting_id` | same | guard `IS NULL` (all three), `affair_id` set | foreign-key columns of the parent |
| `docs.hash` | `hash` | guard (before value), set (after value) | the document identifier, sha256 of body_key + parent_type + url |
| `affairs` | affairs export row | table of affairs | the table that holds one row per affair |
| `affairs.id`, `affairs.body_key` | `id`, `body_key` | guard | as for `docs` |
| `affairs.begin_date` | `begin_date` | guard `::date = before`, set | a `date` or `timestamp` column; the `::date` cast works for both |

## Not in the plan, but may matter

- **Stored URL.** The plan changes `hash`, but not `url_oparl`. If OPD stores the public file URL as its own column,
  set it too. Both values are in `apply_BE_relink_plan.csv` (`before_url_oparl`, `after_url_oparl`). If the file under
  `files.openparldata.ch/doc/BE/<hash>` is stored by hash, it has to be copied or moved as well.
- **Identifier rule.** Whether a re-parented document gets a new `hash` is OPD's decision. The plan writes the
  recomputed value (`--hash recompute`). With `--hash keep`, `apply_be` writes a plan that leaves `hash` alone.
- **Privileges.** The plan needs `UPDATE` on both tables and `TEMP` on the database, for the check table
  `gp_apply_be_changed`, which is dropped on commit.
- **Triggers and the next scrape.** Update triggers and audit tables fire as for any other update. Until the
  staging fix ships, a later scrape can undo the relinks, so apply them as a protected override (plan header).

## How it was tested

`python -m gegenprobe.repair.apply_be_pg` runs the unchanged plan on PostgreSQL. It uses exactly these names, with
the before-state rebuilt from the two CSVs. CI job `apply-be-postgres` runs it on PostgreSQL 16.4. The committed run,
`apply_BE_pg_check.json`, used PostgreSQL 16.2. The run makes four checks:

1. The plan applies and exactly 2,975 rows change: 2,421 relinks and 554 begin dates. Each changed row holds its
   planned value, and the 173 review rows stay untouched.
2. A second run on the applied state raises and changes nothing.
3. One document hash is changed beforehand, so one guard misses: 2,974 rows change, the plan raises, and the whole
   transaction rolls back.
4. The same as check 3, with one affair's begin date changed instead.
