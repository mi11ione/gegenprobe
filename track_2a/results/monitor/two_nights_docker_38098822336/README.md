# Two Docker nights, run 38098822336: a ledger bug in night 2

These files are kept as they were uploaded by the workflow (`.github/workflows/nightly-real-docker.yml`, run 38098822336).
They show a bug that was found in round 8 and has since been fixed.

**The bug.** `repair.be.join` emits every relink/fetch row with `checks=None, verified=None`. Only rows that are new tonight
(or that are retried after a transient fetch error) go through the per-row check (`monitor.nightly.verify_new`).
`update_ledger` read the join's `verified=None` as tonight's check result. So every row seen again on a later night lost
its stored verdict and became `unchecked`, a status that `docs/runbook.md` reserves for rows that were never checked.

**Its effect on night 2.**

| | night 1 (first night) | night 2 (on night 1's state) |
|---|---|---|
| BE rows (`be_repair`) | 2,459 relink + 49 fetch | 2,459 relink + 49 fetch (unchanged) |
| new rows, checked tonight | 2,508 | 0 |
| ledger (`run.json` `ledger`) | pending 2,468, review 40 | **unchecked 2,508** (should be pending 2,468, review 40) |

Night 2's row counts, timings, bytes and alerts (0) are correct. Its ledger statuses are wrong. The 40 rows that failed
their check on night 1 still showed their proposed action (`relink`/`fetch`) in the ledger, with status `unchecked`
instead of `review`. No row was re-emitted in `repair_BE_new.tsv`: that file holds only new rows, and night 2 had none.

**The fix** is in `src/gegenprobe/monitor/nightly.py`, in the commit that adds this README
(`git log -1 -- track_2a/results/monitor/two_nights_docker_38098822336/README.md`).
- `verify_new` marks each row it checked (`checked_tonight`).
- `update_ledger` keeps the stored `verified`, `check_summary` and status for every row that was not checked tonight;
  only `last_seen` moves.
- `carry_verdicts` turns a row whose stored check failed back into action `review` (with its `proposed_action`), so it is
  not handed on again as a relink/fetch. `run.json` reports the count as `be_repair_carried_review`.

The tests are in `tests/test_ledger_two_nights.py`. One test builds rows with the real `be.join` (the `verified` key is
present), and the other runs two network nights of the real job end to end on a local exports mirror. Both tests fail on
the code that produced this run: night 2 shows `{"unchecked": 50}` instead of `{"pending": 40, "review": 10}`.

**Re-run.** Dispatch the same workflow on the fixed commit:
`gh workflow run nightly-real-docker.yml -R mi11ione/gegenprobe --ref main -f wait_for_new_index=true -f max_wait_min=180`.
On a fixed run, night 2's `ledger` equals night 1's (apart from rows that are resolved or dropped in between), and
`be_repair_carried_review` equals night 1's review count, less any rows retried after a transient failure.
