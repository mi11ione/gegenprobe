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
8. `results/monitor/alerts.json`, then delivery (below), then the night's state. Exit code: 0 = quiet night,
   `GP_ALERT_EXIT` (default 3) = alerts, 1 = the job itself or the alert delivery failed.

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

Every alert carries the body key and its name (e.g. `5586 Lausanne`).

## Alert routing

Nothing leaves the machine unless configured (`/etc/gegenprobe/alerts.env`, template `deploy/nightly/alerts.env.example`):
- `GP_ALERT_WEBHOOK`: one JSON POST per night with alerts (`text` for Slack/Teams/Matrix bridges, plus the structured alerts);
- `GP_ALERT_SMTP_HOST` + `GP_ALERT_MAIL_TO` (…): one mail per night with alerts (STARTTLS);
- `GP_ALERT_EXIT` (default 3): the exit code on alerts, so systemd's `OnFailure=gegenprobe-nightly-failure.service`, a
  CI job or any scheduler reacts; `0` keeps the unit green.
`python -m gegenprobe.monitor.notify test` sends a test message through every configured channel (exit 0 sent, 2 no channel
configured, 1 send failed).

Alerts are delivered **before** the night's state is committed: they go to `WORK/nightly/outbox.json`, are sent, and leave
the outbox only when the send succeeded. If the webhook or mail server is down, the job exits 1, the outbox stays, and the
next night sends the old alerts with the new ones (`undelivered_from_previous_nights` in `alerts.json`). Nothing is lost by
a failed send.

## Measured cost

Compute on cached inputs (`make nightly-offline`; steps 5–7, no network), on the development Mac while other jobs were
running: 233.0 s wall, of which 215.8 s is the census extraction. A second run on the same inputs reports 0 new BE repair rows
and 0 alerts, as it should.

Transfer depends on where the job runs.

- **At OpenParlData** the exports are local files written by OPD's own export job, so there is no transfer; the job adds the
  compute above plus the two canton GETs (~23 MB). Measured with `GP_EXPORTS_DIR` pointing at a local copy of the 6 Oct
  exports (`results/monitor/run_local_exports.json`): 96.8 s wall for the whole night (index read, canton tables, census
  extraction, rates, repair join, ledger), no body rescanned, 0 bytes of export transfer, peak memory 2,077.6 MB. The one
  alert it raised was `exports_stale`, correctly: the copied index was four days old.
- **Outside OPD** the exports have to be downloaded. They are full dumps regenerated every night, not deltas. Between the
  2026-10-06 and 2026-10-09 snapshots, 68/116 docs/texts files changed size (5.0 of 6.2 GB), so the per-body skip in
  step 3 saves little over three days. The single-file exports are 137 MB. Parsing a full docs scan is about 25 min of one
  CPU core (Python, parsing-bound; measured in the spike). An external deployment is a 20 GB CPU VPS job of roughly 30–40
  minutes a night, not 5.

The `index_diff.json` numbers come from `python -m gegenprobe.monitor.nightly index`, one request to the index.

## One-off backlogs (not nightly)

| backlog | size | cost |
|---|---|---|
| CHE placeholder documents (`repair.che backlog`) | 29,946 documents | 2.1 s per document at ≥ 1.2 s per host → about 17.5 h, once |
| OCR of image-only answer scans (`repair.ocr`) | 1,350 affairs | 1,350 × 3 pages × 6.9 s per page ≈ 7.8 h on one core, once |
| BE fetch rows | 49 PDFs | about 1 min |

## Install

`make install-nightly` (Linux, systemd, Docker, root) installs `deploy/nightly/gegenprobe-nightly.{service,timer}` and
`gegenprobe-nightly-failure.service`: one container run every day at 07:30 Europe/Zurich, after OPD's exports (dated
~04:45 UTC), from a versioned image tag (`gegenprobe:0.1.0`, set in the unit as `GP_IMAGE`). State and outputs live under
`/var/lib/gegenprobe`, never in the image; the container runs as uid 10001 with a 4 GB / 2 CPU ceiling. Without systemd
or root it prints the commands instead and exits 0. Without Docker: `sh deploy/nightly/install.sh --venv` creates the
`gegenprobe` system user and `/var/lib/gegenprobe` and installs `gegenprobe-nightly-venv.service`, which runs the same job
from a read-only checkout and a hash-pinned venv (`pip install --require-hashes -r requirements.lock`) with
`MemoryMax=4G` / `CPUQuota=200%`. Settings: `deploy/nightly/alerts.env.example`. Operations, triage and failure modes:
`docs/runbook.md`.
