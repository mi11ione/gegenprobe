# Nightly monitor and repair job

`python -m gegenprobe.monitor.nightly run` is one night. It is the census plus the BE repair, re-run on that night's exports,
with a diff against the previous night (`WORK/nightly/state.json`).

1. One GET of `files.openparldata.ch/exports/index.json`. Each export's size is compared with last night's.
2. The single-file exports the census needs (affairs, events, agendas, bodies) are downloaded when they changed.
3. The split `docs_<body>` / `texts_<body>` exports are re-scanned (metadata only, `census.scan`) only for bodies whose file
   changed size; every other body keeps last night's metadata.
4. The canton of Bern's OGD tables (two GETs).
5. `census.extract` → `census.funnel.compute` on the snapshot → the answer-linking rate of every body.
6. `repair.be.join` on the snapshot → relink/fetch rows; rows not seen the night before go to `results/monitor/repair_BE_new.tsv`.
7. `results/monitor/alerts.json`.

**Linking rate** of a body = affairs with a written-answer event whose answer text is reachable in OPD (attached document,
`texts` row, or agenda item) ÷ affairs with a written-answer event. Same definitions as the census (`docs/census.md`).

**Alerts** (thresholds in `monitor/nightly.py`):
- `linking_rate_drop`: the rate falls by more than 2 percentage points night over night, for bodies with at least 50
  written-answer affairs. A scraper change that stops attaching answers shows up here the next morning. (BE's linking rate
  is 26.37% today; the 2024 switch to filing answers under agenda items is the kind of change this catches.)
- `document_count_drop`: a body's document count falls by more than 10%.
- `new_body`: a body appears that was not rated the night before.

## Measured cost

Compute on cached inputs (`make nightly-offline`; steps 5–7, no network), on the development Mac while other jobs were
running: 260.5 s wall, of which 228.0 s is the census extraction. A second run on the same inputs reports 0 new BE repair rows
and 0 alerts, as it should.

Transfer depends on where the job runs.

- **At OpenParlData** the exports are local files written by OPD's own export job, so there is no transfer; the job adds the
  compute above plus the two canton GETs (~23 MB).
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
| OCR of image-only answer scans (`repair.ocr`) | 1,351 affairs | 1,351 × 3 pages × 6.9 s per page ≈ 7.8 h on one core, once |
| BE fetch rows | 49 PDFs | about 1 min |

## Install

`make install-nightly` (Linux, systemd, Docker, root) installs `deploy/nightly/gegenprobe-nightly.{service,timer}`: one container
run every day at 07:30 Europe/Zurich, after OPD's exports (dated ~04:45 UTC). State and outputs live under
`/var/lib/gegenprobe`, never in the image. Without systemd or root it prints the commands instead and exits 0.
