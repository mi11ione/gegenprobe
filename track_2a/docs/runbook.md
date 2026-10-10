# Runbook: running Gegenprobe at OpenParlData

One page for a two- or three-person data team. Everything here is model-free; the converter's optional Apertus review mode
is out of scope for operations (see `docs/converter.md`).

## Where it runs

| option | when | cost |
|---|---|---|
| **Inside OPD**, next to the export job | recommended | no download: `GP_EXPORTS_DIR` points at OPD's export directory and every exports URL is read from there. A night measured that way took 96.8 s wall (incremental best case on a copied snapshot: no docs/texts file changed, so no rescan; peak memory 2,077.6 MB) plus two canton GETs (~23 MB). A night that re-scans changed files takes longer: about 21.8 min after the 6→9 Oct changes (20.2 min of re-scan, derived; `results/monitor/night_cost.json`) |
| A Swiss or EU VPS (e.g. 4 vCPU / 8 GB RAM / 20 GB disk at a Swiss provider) | if OPD prefers to keep it outside | the exports are full nightly dumps (6.2 GB; 68 of 116 docs/texts files changed between 6 and 9 Oct), so a night is roughly 30–40 min, mostly download and parsing |

It needs Linux, systemd, and either Docker (`deploy/nightly/gegenprobe-nightly.service`) or a Python 3.11 venv with poppler
and tesseract (`deploy/nightly/gegenprobe-nightly-venv.service`, `sh deploy/nightly/install.sh --venv`). No GPU, no model,
no account anywhere.

## Resources and limits

| resource | need | where it is enforced |
|---|---|---|
| memory | peak 2,077.6 MB (census extraction); ceiling **4 GB** | Docker unit: `--memory 4g --memory-swap 4g` (`GP_MEM`); venv unit: `MemoryMax=4G` |
| CPU | one core most of the run; ceiling **2 cores** | Docker: `--cpus 2` (`GP_CPUS`); venv: `CPUQuota=200%`; both `Nice=10` |
| processes | pdftotext / pdftoppm / tesseract children | Docker `--pids-limit 256`; venv `TasksMax=256` |
| disk | state under 1 GB (single exports ~80 MB, scan metadata ~56 MB, canton tables ~26 MB, nightly state and ledger ~26 MB, PDF cache); the 6.2 GB docs exports are streamed, never stored. 20 GB leaves room for the one-off backlogs | `/var/lib/gegenprobe` |
| wall time | `TimeoutStartSec=4h` per night | systemd |
| filesystem | Docker: read-only root (`--read-only`), private `/tmp` tmpfs of 1 GB (pdftoppm/tesseract scratch), writes only to the two mounted directories | Docker unit |

A night killed for memory exits 137; raise `GP_MEM` / `MemoryMax`. The image never runs as root (uid 10001, all
capabilities dropped, `no-new-privileges`); the venv unit runs as the `gegenprobe` system user that `install.sh --venv`
creates, with the checkout read-only (`ProtectSystem=strict`) and writes confined to `/var/lib/gegenprobe`.

## Operator settings

All optional, in `/etc/gegenprobe/alerts.env` (template with every key: `deploy/nightly/alerts.env.example`; comments on
their own lines, because Docker's `--env-file` keeps a trailing `# …` as part of the value).

| setting | default | what it does |
|---|---|---|
| `GP_USER_AGENT` | `hackapertus-research/0.1` | User-Agent of every request. **OPD should set its own** (product token and a contact URL), so cantons see who is fetching |
| `GP_EXPORTS_DIR` | unset | read `files.openparldata.ch/exports/…` from this local directory (same layout: `index.json`, `affairs.ndjson.gz`, `docs/docs_<body>.ndjson.gz`, …); no export transfer |
| `GP_MAX_PDF_MB` | 50 | a document larger than this is refused before it is read (typed `too_large`, row goes to `review`) |
| `GP_MAX_DOWNLOAD_MB` | 100 | the same for other in-memory downloads (the canton tables are ~20 MB) |
| `GP_SUBPROCESS_TIMEOUT` | 300 | seconds per pdftotext / pdftoppm / tesseract call (typed `text_timeout`) |
| `GP_DOC_BUDGET_S` | 600 | seconds per document (fetch + text + OCR) in the nightly check and `repair.verify_all` |
| `GP_STALE_DAYS` | 2 | alert when OPD's `index.json` is older than this |
| `GP_ALERT_*` | unset | routing, see Alerts |

**robots.txt** is honoured on every host, following RFC 9309 §2.3.1. A robots.txt that answers any 4xx (401, 403, 404, 410,
…; except 429) means "no restrictions", as the RFC specifies. One that cannot be read (DNS, timeout, 5xx or 429 after one
retry) makes the host **disallowed for that night** (fail-closed). It is logged to
the journal and listed in `run.json` (`robots_unreadable`); the rows it affects get `fetch_error` and are re-checked the next
night. `api.openparldata.ch/v1/` is refused outright (its robots.txt disallows it).

## What it reads and writes

| reads (runtime) | data sent | purpose |
|---|---|---|
| `files.openparldata.ch/exports/` (index.json, affairs, events, agendas, bodies, changed docs_/texts_ files) | none (GET) | the census snapshot |
| `ogd.parl.apps.be.ch/data/{dokument,geschaeft}.csv` | none (GET) | Bern's own answer register |
| the canton's or OPD's document URLs of **new** relink/fetch rows only | none (GET) | triple check before a row is emitted |

| writes (all under `/var/lib/gegenprobe`) | who reads it |
|---|---|
| `results/rates.json` | per-body answer-linking rates (dashboard / quality panel) |
| `results/alerts.json` | the on-call person, via webhook or mail if configured |
| `results/repair_BE_new.tsv` | the person who applies relinks (see triage): tonight's new rows |
| `results/repair_BE_ledger.tsv` | every row ever proposed, with `first_seen` / `last_seen` and a status: `pending` (checked), `review` (check failed), `unchecked` (seen only on an offline night), `resolved` (left the list because OPD now has the answer), `dropped` (left the list, still unanswered) |
| `results/run.json` | timings, transfer, peak memory, counts, delivery result of the night |
| `work/` | caches, `state.json` (night-over-night diff and 8 nights of rate history) and `nightly/outbox.json` (alerts not yet delivered). Deleting it costs one full re-download; it also resets the history the trend alert needs |

Not runtime: the one-off backlogs (Fedlex placeholder replacement ~17.5 h once; OCR of image-only scans ~7.8 h once; the
Curia Vista probe on `ws.parlament.ch`), the evaluation (Public AI, CI runners) and the evidence site
(`gegenprobe.mi11ion.io`, static, Cloudflare). None of them is contacted by the nightly job.

## Triage: who handles which list

| list | action | who |
|---|---|---|
| `repair_BE_relink.tsv` (`verified=true`) | re-attach the parentless OPD document to the affair | data engineer; **apply as a protected override, or after OPD's staging fix** (until the fix, the next scrape re-attaches the document to the first parent it sees) |
| `repair_BE_review.tsv` | a row that failed its per-row check (identity, heading or decision date); open the PDF, decide | data engineer, ~2 min per row |
| `repair_BE_fetch.tsv` | the canton lists an answer OPD lacks; fetch it from the canton | scraper owner |
| `repair_BE_begin_date.tsv` (`set_begin_date`) | replace the load timestamp by the affair's own "Eingereicht" event (event id given) | data engineer |
| `repair_BE_begin_date.tsv` (`review`) | no Eingereicht event, or a proposal ≥ 2 years after the number's year | data engineer |
| `repair_VS.tsv` (`retype_oral`) | link status `oral`, not missing | data engineer |
| `repair_<body>.tsv` (`ocr`) | OCR the scan (deu+fra+ita) and store the text | batch job, once |

**Acceptance test of the staging fix:** `python -m gegenprobe.repair.acceptance --fetch` (or a local `docs_BE.ndjson.gz`;
with `GP_EXPORTS_DIR` set, `--fetch` reads the local file) counts how many of the 2,459 relink documents are attached to the
affair the list names. 6 Oct 2026 snapshot: none; all 2,459 are still parentless.
After the fix it should be 2,459 of 2,459. It exits 0 when that holds and 1 otherwise, so it can gate a deployment, and
writes one dated file per check (`results/repair/acceptance_<live|file>_<YYYY-MM-DD>.json`).

## Alerts

| alert | meaning | first step |
|---|---|---|
| `linking_rate_drop` | a body's share of written answers with reachable text fell by > 2 points overnight | check that body's scraper run |
| `document_count_drop` | a body lost > 10 % of its documents | scraper or export truncated? |
| `body_gone` / `new_body` | a body disappeared from / appeared in the rated set | export job or body configuration |
| `be_ogd_schema_change` | the canton of Bern renamed a column or answer document type the join uses | update `repair/be.py` (`REQUIRED_*`, `ANSWER_TYPES`) |
| `be_ogd_answers_collapsed` | Bern's answer-document count fell to 0 or by half | the canton's OGD endpoint; do not apply new rows that night |
| `rate_trend_drop` | a body's rate fell by > 5 points over the last 7 nights (slow drift below the nightly threshold) | that body's scraper changes over the week |
| `exports_stale` | OPD's `index.json` is older than `GP_STALE_DAYS` (2) days | OPD's export job; the night's numbers describe old data |
| `outbox_corrupt` / `state_corrupt` | the outbox or the night-over-night state could not be parsed; moved to `work/nightly/<name>.corrupt-<UTC>` | read the quarantined file for undelivered alerts; after `state_corrupt` the next night re-scans everything once |
| unit failed (exit 1) | the job crashed, or the alert channel failed | `journalctl -u gegenprobe-nightly`; the next night retries from scratch |

**Delivery before state.** Alerts are written to `work/nightly/outbox.json`, sent, and removed from the outbox only when
the send succeeded; only then is the night's state committed. A webhook or mail server that is down costs nothing: the
alerts stay in the outbox, the unit exits 1, and the next night sends them again (listed as
`undelivered_from_previous_nights` in `alerts.json`). The outbox and `state.json` are written atomically (tmp + fsync +
rename). A corrupt outbox or state file is moved to `<name>.corrupt-<UTC>` and reported (`outbox_corrupt` /
`state_corrupt`); the night continues. Deleting `work/` deletes undelivered alerts too. Exit codes: 0 quiet night, `GP_ALERT_EXIT` (default 3) alerts,
1 job or delivery failure. `python -m gegenprobe.monitor.notify test` exits 0 when sent, 2 when no channel is configured,
1 when sending failed.

## Failure modes

- **A canton changes its site or tables.** Caught by `be_ogd_schema_change` / `be_ogd_answers_collapsed`; new rows are
  triple-checked before they are emitted, so a bad join produces `review` rows, not wrong relinks.
- **OPD ships the staging fix.** The relink list empties (the acceptance test passes); the monitor keeps its value: it watches
  every body's linking rate.
- **An export is late or partial.** `exports_stale` / `document_count_drop` / `body_gone`; the job never deletes anything
  in OPD, it only writes lists.
- **A night killed at the 4 h timeout (or by an OOM of dockerd).** The Docker unit removes the named container before and
  after every run (`ExecStartPre=-`/`ExecStopPost=-/usr/bin/docker rm -f gegenprobe-nightly`), so the next night does not
  fail on a name conflict.
- **A hostile or broken document.** Downloads are capped (`GP_MAX_PDF_MB`), every pdftotext / pdftoppm / tesseract call has
  a timeout, and each document a time budget; a hit becomes a typed failure on that row (`too_large`, `text_timeout`,
  `TimeBudgetExceeded`), never a hung night. Network-type failures are retried the next night; `too_large`, `not_a_pdf`,
  404 are not.

## Upgrades

Images are tagged (`gegenprobe:0.1.0`, `GP_IMAGE` in the unit); build the new tag, change `GP_IMAGE`, `systemctl
daemon-reload`. The base image is pinned by digest and the Python dependencies by sha256 (`requirements.lock`), so a rebuild
of the same tag gives the same Python software. Rolling back is setting the old tag.

**System packages are the exception.** poppler-utils and tesseract come from Debian bookworm via apt, which installs the
mirror's current version of the release; the image records what it got in `/usr/local/share/gegenprobe-apt-versions.txt`.
To freeze them, pin each package (`apt-get install poppler-utils=<version> …`, versions from that file) or build against
`snapshot.debian.org` for a fixed date. Keep the built image (by digest) rather than rebuilding when exact repeatability
matters.

**poppler in the image (decision, 10 Oct 2026): stay on bookworm's 22.12.** The committed P1/P2 model cache was built on
the development Mac (poppler 26.02.0). The image's poppler-utils `22.12.0-2+deb12u3` extracts some documents differently,
so the prompt hash differs and `make run` counts a cache miss (25 of 154 P1 documents in CI run 38049690293); a miss is
reported, never scored. A newer poppler does not remove this: no Debian release ships 26.02 (trixie 13 has
`25.03.0-5+deb13u4`, forky/testing and sid have 26.07.0; checked on packages.debian.org, 10 Oct 2026), so a trixie base
would trade one version gap for another, change tesseract and the whole system layer at once, and testing/sid packages
cannot be pinned for long. We keep the digest-pinned bookworm base and the recorded versions
(`/usr/local/share/gegenprobe-apt-versions.txt`). To reproduce the cache exactly, run `make run` outside Docker with poppler
26.02.0. The Apertus re-derivation budget is per set (`GP_REDERIVE_APERTUS_BUDGET`, default 180 s each for P1 and P2;
before round 3 a shared 120 s let P1 use all of it and CI reached 0 of 62 P2 documents); worst case 240 + 2 × 180 s of
re-derivation on top of the replay steps.

**OCR language data differs from the measured setup.** The OCR numbers in `docs/repair.md` were measured with Tesseract
5.5.3 and the tessdata_fast models at commit `8741641` (sha256 per language in `repair/ocr.py`, `TESSDATA_SHA256`). The
image uses Debian's Tesseract (bookworm ships 5.3) with the `tesseract-ocr-{deu,fra,ita}` packages, which need not be
the same model files: compare `sha256sum /usr/share/tesseract-ocr/5/tessdata/deu.traineddata` with `TESSDATA_SHA256`. Where
they differ, OCR output can differ in detail. To run with the measured models, download `deu`, `fra`, `ita` (and `eng`)
`.traineddata` from `github.com/tesseract-ocr/tessdata_fast` at that commit, check each sha256 against `TESSDATA_SHA256`,
put them in one directory and set `TESSDATA_PREFIX` to it (Docker: mount it and pass `-e TESSDATA_PREFIX=…`). The nightly
job reads text layers first and uses OCR only for image-only scans of new rows.

## Checked in CI

`.github/workflows/ci.yml` job `systemd-units` runs `systemd-analyze verify` on both unit variants with the timer and the
failure notifier; job `nightly-smoke` builds the image and runs three offline nights on fixture exports inside it with the
unit's container flags and no network (`docs/nightly.md` "Verified in CI"). A real night under systemd on a server has not
been run.

## Swiss / EU hosting

The job processes only public parliamentary data and sends nothing anywhere unless an alert channel is configured by the
operator. It runs on any Swiss or EU Linux host; nothing in it depends on a particular provider.
The evidence viewer is static files only and makes no third-party request: its two fonts are served from `site/fonts/`
(SIL OFL 1.1), not from Google Fonts.

## Supply chain

Base image `python:3.11.14-slim-bookworm` pinned by digest (`Dockerfile`); Python dependencies installed with
`--require-hashes` from `requirements.lock`. The optional 8B path pins the llama-cpp-python 0.3.35 CPU wheels by sha256
(`requirements-gguf.lock`) and the model file by sha256 (`llm.GGUF_PINS`). The model is a community Q4_K_M quant
(`Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF`, Apache-2.0) of a text-only export (`andreasmartin/apertus-v1.5-8b-text`,
Apache-2.0) of `swiss-ai/Apertus-v1.5-8B` (Apache-2.0). An operator who wants the whole chain under its control can
re-quantise from the official weights with llama.cpp (`convert_hf_to_gguf.py`, then `llama-quantize … Q4_K_M`), pin the
new sha256 and keep the file on its own storage. The nightly job does not use a model at all.
