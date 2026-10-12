# Nightly monitor and repair job

`python -m gegenprobe.monitor.nightly run` is one night. It is the census plus the BE repair, re-run on that night's exports,
with a diff against the previous night (`WORK/nightly/state.json`).

1. One GET of `files.openparldata.ch/exports/index.json`. Each export's size is compared with last night's.
   With `GP_EXPORTS_DIR` set (the job runs next to OPD's export job), every exports URL is read from that directory
   instead: no export is downloaded and steps 2–3 read local files.
2. The single-file exports the census needs (affairs, events, agendas, bodies) are downloaded when they changed.
3. The split `docs_<body>` / `texts_<body>` exports are re-scanned (metadata only, `census.scan`) only for bodies whose file
   changed size; every other body keeps last night's metadata.
4. The canton of Bern's OGD tables (two GETs).
5. `census.extract` → `census.funnel.compute` on the snapshot → the answer-linking rate of every body.
6. `repair.be.join` on the snapshot → relink/fetch rows; rows not seen the night before go to `results/monitor/repair_BE_new.tsv`,
   each **triple-checked before it is emitted** (affair number printed, answer heading, RRB date = OPD answer event; network
   mode). A new row that fails becomes action `review`. A row whose check failed for a transient reason (network error,
   timeout, HTTP 5xx, unreadable robots.txt) is checked again the next night; one that failed for a property of the
   document (`too_large`, `not_a_pdf`, 404) is not. Each document has a time budget (`GP_DOC_BUDGET_S`, 600 s), each
   pdftotext/tesseract call a timeout (`GP_SUBPROCESS_TIMEOUT`, 300 s), each PDF a size cap (`GP_MAX_PDF_MB`, 50).
7. `results/monitor/repair_BE_ledger.tsv`: every row ever proposed, keyed by affair + action + canton document, with
   `first_seen`, `last_seen` and a status (`pending`, `review`, `unchecked`, `resolved` = OPD has the answer now,
   `dropped` = left the list unanswered). The nightly TSV says what is new; the ledger says what is still open.
   A row seen again on a later night and not re-checked keeps its stored verdict and check summary (only `last_seen`
   moves); a row whose check failed stays `review` and is not handed on again as a relink/fetch (`run.json`
   `be_repair_carried_review`). Earlier, `be.join`'s `verified=None` overwrote the stored verdict, so every second
   night showed all rows `unchecked` (two Docker nights, run 38098822336; `results/monitor/two_nights_docker_38098822336/README.md`).
   On the fixed code a real two-night pair kept night 1's verdicts on night 2 (run 38187596786;
   `results/monitor/two_nights_docker_38187596786/README.md`).
8. `results/monitor/alerts.json`, then delivery (below), then the night's state. Exit code: 0 = quiet night,
   `GP_ALERT_EXIT` (default 3) = alerts, 1 = the job itself or the alert delivery failed, 2 = nothing to work on yet.

**Empty cache.** `nightly offline` computes steps 5–7 on cached inputs. It uses the first complete set of inputs:
`GP_OPD_RAW` + `GP_DOCS_META` (default `work/opd`, `work/docs_meta`), then `GP_EXPORTS_DIR` + `work/nightly/docs_meta`,
then the last network night's `work/nightly/opd` + `work/nightly/docs_meta`. It also needs the canton tables in
`work/be_ogd`. `nightly index` compares with `GP_OPD_RAW/index.json`, or else with the index stored in the last night's
`state.json`. If none of these exists, both commands print what is missing and the command to run first (a network night,
`python -m gegenprobe.monitor.nightly run`, or `python -m gegenprobe.repair.be fetch-ogd` for the canton tables) and
exit 2, without a traceback.

**User-Agent.** Every request carries `GP_USER_AGENT` (default `hackapertus-research/0.1`). Set it to your own product
token and a contact URL (never an e-mail address: such a value is refused, every fetch fails closed), e.g. `GP_USER_AGENT=opd-gegenprobe/0.1 (+https://openparldata.ch)` in
`/etc/gegenprobe/alerts.env`. A network night refuses to start (exit 1, before any request) until `GP_USER_AGENT` names
your product and a contact URL (`http(s)://` and a real host; reserved example and placeholder hosts are refused). The
shipped template's placeholder fails closed, and `install.sh --user-agent '…'` writes the line. `offline` sends nothing
and is not checked. Every `run.json` records `user_agent` (`value`, `has_contact`, `source`). No personal data is
hard-coded.

**Linking rate** of a body = affairs with a written-answer event whose answer text is reachable in OPD (attached document,
`texts` row, or agenda item) ÷ affairs with a written-answer event. Same definitions as the census (`docs/census.md`).

**Alerts** (thresholds in `monitor/nightly.py`):
- `linking_rate_drop`: the rate falls by more than 2 percentage points night over night, for bodies with at least 50
  written-answer affairs. A scraper change that stops attaching answers shows up here the next morning. (BE's linking rate
  is 26.37% today; the 2024 switch to filing answers under agenda items is the kind of change this catches.)
- `document_count_drop`: a body's document count falls by more than 10%.
- `new_body` / `body_gone`: a body appears in, or disappears from, the rated set (a scraper that stops delivering a whole
  parliament shows up as `body_gone`, not as silence).
- `be_ogd_schema_change`: the canton of Bern's tables lost a column the join uses (`dokument_uid`, `dokument_typ_deutsch`,
  `dokument_geschaeft_uid`, …) or an answer document type (`RRB`, `Vorstossantwort`). Without this check a renamed column or
  type would make the join produce zero rows, silently.
- `be_ogd_answers_collapsed`: the canton's answer-document count is 0, or less than half of the previous night's (9,577
  answer documents in the 2026-10-08 tables).
- `rate_trend_drop`: the rate fell by more than 5 points over the last 7 nights (the state keeps 8 nights of rates). It
  catches a slow drift that never crosses the 2-point nightly threshold.
- `exports_stale`: OPD's `index.json` is older than `GP_STALE_DAYS` (default 2) days, i.e. the export job did not run and
  tonight's numbers describe old data. Not raised in offline mode.
- `outbox_corrupt` / `state_corrupt`: `work/nightly/outbox.json` or `state.json` could not be parsed (edited by hand, disk
  error). The file is moved aside to `<name>.corrupt-<UTC timestamp>` and the night continues; after `state_corrupt` it runs
  as a first night (no night-over-night diff; in network mode every docs/texts body is re-scanned).

Every alert carries the body key and its name (e.g. `5586 Lausanne`).

## Alert routing

Nothing leaves the machine unless configured (`/etc/gegenprobe/alerts.env`, template `deploy/nightly/alerts.env.example`):
- `GP_ALERT_WEBHOOK`: one JSON POST per night with alerts (`text` for Slack/Teams/Matrix bridges, plus the structured alerts);
- `GP_ALERT_SMTP_HOST` + `GP_ALERT_MAIL_TO` (…): one mail per night with alerts (STARTTLS);
- `GP_ALERT_EXIT` (default 3): the exit code on alerts, so systemd's `OnFailure=gegenprobe-nightly-failure.service`, a
  CI job or any scheduler reacts; `0` keeps the unit green.
`python -m gegenprobe.monitor.notify test` sends a test message through every configured channel (exit 0 sent, 2 no channel
configured, 1 send failed).

**One alert per event.** The job sends its alerts itself. The systemd failure notifier (`gegenprobe-nightly-failure.service`,
`OnFailure=`) fires on every non-zero exit, including `GP_ALERT_EXIT`; on that exit it only writes a journal line, because
the job exits `GP_ALERT_EXIT` only after its own delivery succeeded (a failed delivery exits 1). It posts to
`GP_ALERT_WEBHOOK` only when the night failed: exit 1 or 2, a crash, a timeout, an OOM kill. It reads the failed unit's
exit status from `MONITOR_EXIT_STATUS`, which systemd ≥ 251 passes to `OnFailure=` units (Debian 12: 252, Ubuntu 24.04:
255); an older systemd passes nothing, and the notifier then posts on every failure. Earlier it posted on every
night with alerts, on top of the job's own message. Its JSON body was also quoted so that systemd's own unescaping
turned it into a shell syntax error, so that post never went out. The CI job `systemd-units` now runs the notifier under
real systemd and checks for exactly one valid post.

Alerts are delivered **before** the night's state is committed: they go to `WORK/nightly/outbox.json`, are sent, and leave
the outbox only when the send succeeded. If the webhook or mail server is down, the job exits 1, the outbox stays, and the
next night sends the old alerts with the new ones (`undelivered_from_previous_nights` in `alerts.json`). A failed send does
not drop an alert. The outbox and `state.json` are written atomically (temporary file in the same directory, fsync,
rename), so a crash or a full disk mid-write leaves the previous file, not a truncated one; a file that is corrupt anyway is
quarantined and reported (`outbox_corrupt` / `state_corrupt`) instead of failing every following night. The outbox lives in
`work/`: deleting `work/` deletes undelivered alerts with it (they are still in that night's `results/alerts.json`).

## Measured cost

**The first night is the longest.** With no previous state, every docs/texts export is re-scanned (about 25 min of one
core, cited below) and every row of the BE list is new, so each one is triple-checked once: fetch the PDF, extract the
text, check. The same check over the same rows (`repair.verify_all`, 10 Oct 2026, development Mac) took 3,054 s for 2,500
rows, about 1.2 s per row, bounded by the 1.2 s per-host request gap. That gives about 51 min for the 2,508 rows. A first
night is therefore roughly 1.3 h at OPD with `GP_EXPORTS_DIR` (25 min rescan + ~4 min extraction + ~51 min checks), and
about 1.5 h on an external host, which also downloads the exports (estimates from those measurements, not a measured
night). Both fit the unit's `TimeoutStartSec=4h`. After the first night only new rows are checked.

Compute on cached inputs (`make nightly-offline`; steps 5–7, no network), on the development Mac while other jobs were
running: 233.0 s wall, of which 215.8 s is the census extraction. A second run on the same inputs reports 0 new BE repair rows
and 0 alerts, as it should.

What the 96.8 s night below is, and is not (`python -m gegenprobe.monitor.nightly cost` → `results/monitor/night_cost.json`):
it is an **incremental night with nothing to re-scan**, measured on a local copy of the 6 Oct exports with a previous night's
state on the same copy, so no docs/texts file had changed size and no body was re-scanned. It is wall time on the
development Mac, not CPU time. A **full re-scan** of all 116 docs/texts exports (6.2 GB) takes about 25 min of one core
(cited: the 8 Oct metadata scan, `spikes/recovery/results.md` §6). Between the 6 and 9 Oct snapshots 68 of 116 files
(80.6% of the bytes) changed size; re-scanning those adds about 20.2 min, so a night after three days of OPD changes is
about 21.8 min even with the exports read in place (derived: 96.8 s + 80.6% × 25 min; scanning is parsing-bound, so time
scales with bytes).

Transfer depends on where the job runs.

- **At OpenParlData** the exports are local files written by OPD's own export job, so there is no transfer; the job adds the
  compute above plus the two canton GETs (~23 MB). Measured with `GP_EXPORTS_DIR` pointing at a local copy of the 6 Oct
  exports (`results/monitor/run_local_exports.json`): 96.8 s wall for a night with no changed docs/texts file (index read,
  canton tables, census extraction, rates, repair join, ledger), no body rescanned, 0 bytes of export transfer, peak memory
  2,077.6 MB. The one alert it raised was `exports_stale`, correctly: the copied index was four days old. Nights on which
  OPD changed documents add the re-scan of the changed files (about 20.2 min for the 6→9 Oct changes, above).
- **Outside OPD** the exports have to be downloaded. They are full dumps regenerated every night, not deltas. Between the
  2026-10-06 and 2026-10-09 snapshots, 68/116 docs/texts files changed size (5.0 of 6.2 GB), so the per-body skip in
  step 3 saves little over three days. The single-file exports are 137 MB. Parsing a full docs scan is about 25 min of one
  CPU core (Python, parsing-bound; measured in the spike). An external deployment is a 20 GB CPU VPS job. Measured on
  4-vCPU GitHub runners: first nights took 83 and 86 min, and the following night on the next export took 6.6 min (14
  files changed overnight; `results/monitor/two_nights_docker_38098822336/`). A night after several days of changes
  lies in between. The job needs only a standard Linux host; nothing in it is tied to one provider.

The `index_diff.json` numbers come from `python -m gegenprobe.monitor.nightly index`, one request to the index.

## One-off backlogs (not nightly)

| backlog | size | cost |
|---|---|---|
| CHE placeholder documents (`repair.che backlog`) | 29,946 documents | 2.1 s per document at ≥ 1.2 s per host → about 17.5 h, once |
| OCR of image-only answer scans (`repair.ocr`) | 1,350 affairs | 1,350 × 3 pages × 6.9 s per page ≈ 7.8 h on one core, once |
| BE fetch rows | 49 PDFs | about 1 min |

## Verified in CI

- `nightly-smoke` (`.github/workflows/ci.yml`): builds the Docker image and runs `python -m gegenprobe.monitor.smoke` in
  it with the unit's container flags (`--read-only`, `--tmpfs /tmp`, uid 10001, `--cap-drop ALL`, `no-new-privileges`)
  and `--network none`: three offline nights on synthetic fixture exports (two parliaments, Bern's two canton tables).
  Night 1 is quiet (exit 0, 40 relink + 10 fetch rows); before night 2 the outbox is truncated, which must give
  `outbox_corrupt`, a quarantined file and exit 3; night 3 loses 20 Zürich answer documents, which must give
  `linking_rate_drop` and `document_count_drop` (exit 3). Locally: `make nightly-smoke` (seconds); the same run is a
  pytest test (`tests/test_monitor_smoke.py`). A further step runs the recommended "Inside OPD" setup the way the Docker
  unit does: a fixture exports directory in OPD's layout, owned by root and read-only, passed with the unit's
  `--env-file` (`GP_EXPORTS_DIR`) and its `--mount type=bind,…,readonly` at the same path; one `nightly run`
  (network mode, `--network none`) must read every export from it, send nothing, rate both parliaments and build the
  BE list (`python -m gegenprobe.monitor.smoke local-exports-check`; locally `smoke local-exports`, also under pytest).
- `systemd-units`: `systemd-analyze verify` on the Docker variant and on the venv variant, each together with the timer
  and the failure notifier, under the name `install.sh` gives it (`gegenprobe-nightly.service`). On the runner the venv's
  interpreter `/opt/gegenprobe/.venv/bin/python` is a symlink to the runner's python3, so verify can resolve it. The step
  fails on a non-zero exit and on any unknown-key/ignored/invalid warning that names one of the units.

- `systemd-units`, second step: `systemd-analyze security --offline=true` on both units; it prints each exposure score
  and fails above 2.0 (venv unit) or 5.0 (Docker unit, which scores only the docker client; `docs/runbook.md`
  "Sandboxing").
- `systemd-units`, third step: the failure notifier under real systemd, behind two stand-in units (exit 3 = alerts, exit
  1 = failure) and a local webhook. It must post exactly once, for the failure, with valid JSON.
- `tests/test_nightly_network.py` (pytest, every CI run): a **first network-mode night end to end** on a local mirror of
  the exports built from the smoke fixture. Index read, a `census.scan` subprocess per body, `census.extract`, rates, the
  BE join, the per-row check of all 50 new rows (the PDF fetch fails on purpose, with a typed network error), ledger and
  state. It runs in both modes: the exports read in place (`GP_EXPORTS_DIR`) and the single exports downloaded (the job
  outside OPD). It found two bugs that would have stopped the first real night outside OPD, both fixed:
  `census.extract` needs `contributors.ndjson.gz`, which the job did not download (it now downloads the five single
  exports the extraction reads, about 198 MB instead of 137 MB). And the per-row check read OPD's answer events from
  `GP_OPD_RAW` instead of the night's own events export.

None of these is a real night against OPD under systemd on a server. `.github/workflows/nightly-real.yml` runs one on a
GitHub-hosted Ubuntu runner: manual only, `install.sh --venv`, `systemctl start`, User-Agent
`hackapertus-research/0.1 (+https://github.com/mi11ione/gegenprobe)`. It uploads `run.json`, `alerts.json`, the ledger,
the journal and the wall time (`night.json`). One run is committed: run 38062530586, `results/monitor/night_real_38062530586/`
(a first night: 4,997 s wall, of which 1,892 s downloading and streaming the exports and about 50 min the one-time triple
check of all 2,508 BE rows; 28 min CPU, peak memory 2,078 MB, 0 alerts; BE list 2,459 relink + 49 fetch, as committed).
In those 1,892 s the night downloaded the five single exports (198 MB, run.json `transfer_bytes`) and, as a first night,
streamed every docs_/texts_ export once without storing it: 116 files, 6.2 GB (6,196,117,045 bytes), plus the 123 KB
index and the canton tables (about 23 MB). The streamed bytes are reconstructed, not counted: that run.json predates the
counter, so `python -m gegenprobe.monitor.night_bytes` reads the sizes of the files it streamed from the index it read
(`results/monitor/index_2026-10-10.json`, generated 04:22 UTC that day; the five single-export sizes in it sum to exactly
the night's 198,074,501 bytes) into `results/monitor/night_real_bytes.json`. Every night since counts them:
`census.scan` reads each file through a counter (`<part>/stream_bytes.json`) and run.json carries `bytes`
(`single_exports`, `docs_texts_streamed`, `docs_texts_declared`, `index`, `be_ogd`, `total`, `over_network`).
`transfer_bytes` keeps its old meaning (single exports only) for compatibility. It tests the install and the job on a
standard GitHub-hosted runner: provider-independent, the same unit runs on any Linux host.

`.github/workflows/nightly-real-docker.yml` (manual) runs **two consecutive real nights in the recommended Docker
setup**: it builds the image and installs the Docker unit with `install.sh`, runs night 1 under systemd, optionally waits
for OPD's next export (polls `index.json` every 10 min through `gegenprobe.net` until `generated_at` changes, at most
`max_wait_min`), then runs night 2 on night 1's state in `/var/lib/gegenprobe`. Night 2 is the incremental case the
first real night could not show: only changed docs/texts files re-scanned, `be_repair_new_since_last_night` against the
previous night, ledger `resolved`/`dropped`, transient retries, outbox redelivery and the drop/trend alerts against real
previous rates (a local webhook on the runner receives any alert post). It uploads, per night, `run.json`, `alerts.json`,
the ledger, a journal excerpt, `systemctl show` and `night.json` (wall time, exit status, whether state existed, the
index `generated_at` the night read), plus `two_nights.json`. Dispatch around 00:30 UTC so night 2 falls after OPD's
~04:20 UTC export: `gh workflow run nightly-real-docker.yml -f wait_for_new_index=true -f max_wait_min=180`.

## Install

`make install-nightly` (Linux, systemd, Docker, root) installs `deploy/nightly/gegenprobe-nightly.{service,timer}` and
`gegenprobe-nightly-failure.service`: one container run every day at 07:30 Europe/Zurich, after OPD's exports (dated
~04:45 UTC), from a versioned image tag (`gegenprobe:0.1.0`, set in the unit as `GP_IMAGE`). State and outputs live under
`/var/lib/gegenprobe`, never in the image; the container runs as uid 10001 with a 4 GB / 2 CPU ceiling, a read-only root
filesystem and a private 1 GB `/tmp` (tmpfs). `docker rm -f gegenprobe-nightly` runs before (`ExecStartPre=-`) and after
(`ExecStopPost=-`) every night, so a container left over from a night killed at `TimeoutStartSec` cannot block the next one
with a name conflict. Without systemd
or root it prints the commands instead and exits 0. Without Docker: `sh deploy/nightly/install.sh --venv` creates the
`gegenprobe` system user and `/var/lib/gegenprobe`, puts the pinned OCR models into `/opt/gegenprobe/tessdata-pinned`
(`python -m gegenprobe.ocr_models`, sha256 per file; it installs nothing if that fails) and installs
`gegenprobe-nightly-venv.service`, which runs the same job, OCR with the measured models (`TESSDATA_PREFIX`,
`GP_OCR_REQUIRE_PINNED=1`), from a read-only checkout and a hash-pinned venv (`pip install --require-hashes -r requirements.lock`) with
`MemoryMax=4G` / `CPUQuota=200%`. Settings: `deploy/nightly/alerts.env.example`. Operations, triage and failure modes:
`docs/runbook.md`.
