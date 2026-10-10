# Runbook: running Gegenprobe at OpenParlData

One page for a two- or three-person data team. Everything here is model-free; the converter's optional Apertus review mode
is out of scope for operations (see `docs/converter.md`).

## Where it runs

| option | when | cost |
|---|---|---|
| **Inside OPD**, next to the export job | recommended | no download: the exports are local files; the nightly job adds ~4–5 min of one CPU core (233.0 s on cached inputs, 215.8 s of it census extraction) and two canton GETs (~23 MB) |
| A Swiss or EU VPS (e.g. a 4 vCPU / 8 GB / 40 GB disk instance at a Swiss provider) | if OPD prefers to keep it outside | the exports are full nightly dumps (6.2 GB; 68 of 116 docs/texts files changed between 6 and 9 Oct), so a night is roughly 30–40 min, mostly download and parsing |

It needs Linux, systemd, and either Docker (`deploy/nightly/gegenprobe-nightly.service`) or a Python 3.11 venv with poppler
and tesseract (`deploy/nightly/gegenprobe-nightly-venv.service`). No GPU, no model, no account anywhere.

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
| `results/repair_BE_new.tsv` | the person who applies relinks (see triage) |
| `work/` | caches and `state.json` (night-over-night diff); safe to delete, the next night rebuilds it |

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

**Acceptance test of the staging fix:** `python -m gegenprobe.repair.acceptance --fetch` (or a local `docs_BE.ndjson.gz`)
counts how many of the 2,459 relink documents are attached to the affair the list names. 6 Oct 2026 snapshot: none; all 2,459 are still parentless.
After the fix it should be 2,459 of 2,459.

## Alerts

| alert | meaning | first step |
|---|---|---|
| `linking_rate_drop` | a body's share of written answers with reachable text fell by > 2 points overnight | check that body's scraper run |
| `document_count_drop` | a body lost > 10 % of its documents | scraper or export truncated? |
| `body_gone` / `new_body` | a body disappeared from / appeared in the rated set | export job or body configuration |
| `be_ogd_schema_change` | the canton of Bern renamed a column or answer document type the join uses | update `repair/be.py` (`REQUIRED_*`, `ANSWER_TYPES`) |
| `be_ogd_answers_collapsed` | Bern's answer-document count fell to 0 or by half | the canton's OGD endpoint; do not apply new rows that night |
| unit failed (exit 1) | the job crashed | `journalctl -u gegenprobe-nightly`; the next night retries from scratch |

## Failure modes

- **A canton changes its site or tables.** Caught by `be_ogd_schema_change` / `be_ogd_answers_collapsed`; new rows are
  triple-checked before they are emitted, so a bad join produces `review` rows, not wrong relinks.
- **OPD ships the staging fix.** The relink list empties (the acceptance test passes); the monitor keeps its value: it watches
  every body's linking rate.
- **An export is late or partial.** `document_count_drop` / `body_gone`; the job never deletes anything in OPD, it only writes
  lists.

## Upgrades

Images are tagged (`gegenprobe:0.1.0`, `GP_IMAGE` in the unit); build the new tag, change `GP_IMAGE`, `systemctl
daemon-reload`. The base image is pinned by digest and the Python dependencies by sha256 (`requirements.lock`), so a rebuild
of the same tag gives the same software. Rolling back is setting the old tag.

## Swiss / EU hosting

The job processes only public parliamentary data and sends nothing anywhere unless an alert channel is configured by the
operator. It runs on any Swiss or EU Linux host; nothing in it depends on a particular provider.

## Supply chain

Base image `python:3.11.14-slim-bookworm` pinned by digest (`Dockerfile`); Python dependencies installed with
`--require-hashes` from `requirements.lock`. The optional 8B path pins the llama-cpp-python 0.3.35 CPU wheels by sha256
(`requirements-gguf.lock`) and the model file by sha256 (`llm.GGUF_PINS`). The model is a community Q4_K_M quant
(`Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF`, Apache-2.0) of a text-only export (`andreasmartin/apertus-v1.5-8b-text`,
Apache-2.0) of `swiss-ai/Apertus-v1.5-8B` (Apache-2.0). An operator who wants the whole chain under its control can
re-quantise from the official weights with llama.cpp (`convert_hf_to_gguf.py`, then `llama-quantize … Q4_K_M`), pin the
new sha256 and keep the file on its own storage. The nightly job does not use a model at all.
