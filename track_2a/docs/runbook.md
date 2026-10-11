# Runbook: running Gegenprobe at OpenParlData

The operations guide for a two- or three-person data team; the tables are the quick reference. The nightly job is
model-free. The converter's optional Apertus review mode is the one part that uses a model; "Review mode in operation"
below covers its refit procedure, owner and cost.

## Operator sheet

| | |
|---|---|
| **Data protection (nDSG)** | *Personal data in the documents:* parliamentary documents are public and name members of parliament and of the government in their public office (authors, signatories, signers). An answer can also name other people, for example officials or people concerned by a matter. *Where text goes, by route:* **default (rules only: nightly job, `convert` without `--mode review`, `make run`)**: nowhere. Documents are read from their public source and processed on the machine that runs the job. **Review mode with a model you host** (local Apertus 8B GGUF with `GP_GGUF=1`, or your own vLLM in Switzerland): the text stays on your infrastructure. **Review mode through the Public AI gateway** (`LLM_BASE_URL`): the text of each residue document goes to that provider, which may process it outside Switzerland. That is a disclosure abroad under nDSG Art. 16: check the provider's terms and processing locations before use. *Retention:* PDFs and extracted text are cached under `GP_WORK` (`pdf/`, `text/`, keyed by sha256; nightly: `/var/lib/gegenprobe/work`; `make run`: `.work/make-run`). They expire after `GP_CACHE_MAX_AGE_DAYS` days (default 30, counted from when the file was written; `0` disables expiry). The nightly job enforces this at the start of every network night, before its first request (both units; run.json `cache_retention`). Elsewhere, `make cache-clean` does the same (`DRY=1` lists without deleting). Only `pdf/<sha256>.pdf` and `text/<sha256>.*.json` are deleted. Exports, scan metadata, nightly state, GGUF weights and the committed `data/` are not touched (`src/gegenprobe/cache_retention.py`). Committed results hold ids, URLs, hashes, dates, short quotations and the names of office holders, but no contact data and no full document texts. *Recommendation for public bodies:* run rules only (the default), or review mode with the local 8B, so that no document text leaves your infrastructure. |
| **Hardware** | Nightly job: Linux, systemd, Docker or a Python 3.11 venv; one core most of the run, ceilings 4 GB memory and 2 CPU (peak 2,077.6 MB), state under 1 GB, 20 GB disk; no GPU, no model. Optional local Apertus 8B (review mode only): 9.3 GB peak memory, 180 s per document on 4 vCPUs. |
| **Time** | First network night 83 and 86 min on 4-vCPU GitHub runners, the incremental next night 6.6 min; inside OPD with `GP_EXPORTS_DIR` and no changed export, 96.8 s. `TimeoutStartSec=4h`. |
| **External hosts** | files.openparldata.ch (GET of the exports; none with `GP_EXPORTS_DIR`) · ogd.parl.apps.be.ch, rrgr-service.apps.be.ch (GET; an affair number) · fedlex.data.admin.ch, www.fedlex.admin.ch (a citation such as "BBl 2014 9657") · the document hosts OPD lists and the parliaments' sites (GET of public pages, PDFs and robots.txt; one canary per adapter source each network night) · huggingface.co only with `GP_GGUF=1` (the pinned GGUF, once) · the LLM endpoint you set (`LLM_BASE_URL`: text of public documents, review mode only) · your webhook or SMTP relay (`GP_ALERT_*`: the night's alerts). Every request Gegenprobe sends carries `GP_USER_AGENT`: document and export fetches and robots.txt (`gegenprobe.net`), the OCR model download, the model endpoint (`llm.py`, `roles_pointer.py`), the GGUF download and the alert webhook. The one exception is the development budget gateway (`gw.py`, outside this repository), which sends the default `hackapertus-research/0.1` and is not a runtime route; `compliance/ci_repeats.py` sends no request (it judges past CI runs under the default User-Agent they sent). Every fetch keeps 1.2 s per host and obeys robots.txt (RFC 9309, fail-closed). |
| **Exit codes** | 0 quiet night · 3 alerts delivered (`GP_ALERT_EXIT`) · 1 job or delivery failure (undelivered alerts stay in `work/nightly/outbox.json` and go out the next night) · 2 nothing to work on yet · 137 killed for memory. Review mode exits 3 on a served build its θ was not fitted on. |
| **Alerts** | to the webhook or SMTP relay in `/etc/gegenprobe/alerts.env`; the systemd failure notifier posts on exit 1 or 2, a crash, a timeout or an OOM kill ([Alerts](#alerts)); `python -m gegenprobe.monitor.notify test` checks the channel. |
| **Licences** | code Apache-2.0; data and results CDLA-Permissive-2.0, derived from OpenParlData.ch (CC BY 4.0, "Source: OpenParlData.ch"); report CC-BY-4.0; Apertus 8B and its GGUF chain Apache-2.0 ([Checked in CI](#checked-in-ci)); Python dependencies installed with `--require-hashes` from `requirements.lock`. |

## Where it runs

| option | when | cost |
|---|---|---|
| **Inside OPD**, next to the export job | recommended | no download: `GP_EXPORTS_DIR` points at OPD's export directory and every exports URL is read from there (the Docker unit bind-mounts that directory read-only at the same path; CI job `nightly-smoke` runs a night that way inside the image). A night measured that way took 96.8 s wall (incremental best case on a copied snapshot: no docs/texts file changed, so no rescan; peak memory 2,077.6 MB) plus two canton GETs (~23 MB). A night that re-scans changed files takes longer: about 21.8 min after the 6→9 Oct changes (20.2 min of re-scan, derived; `results/monitor/night_cost.json`) |
| A Swiss or EU VPS (e.g. 4 vCPU / 16 GB RAM / 20 GB disk at a Swiss provider; 16 GB also holds the optional local Apertus 8B review mode, 9.3 GB peak) | if OPD prefers to keep it outside | the exports are full nightly dumps (6.2 GB; 68 of 116 docs/texts files changed between 6 and 9 Oct), so the first night is long and later nights are short. Measured on 4-vCPU GitHub runners: first nights took 83 and 86 min, about 50 min of which was the one-time BE triple check. The following night took 6.6 min: 14 of 116 docs/texts files had changed overnight, 1.19 GB (`results/monitor/two_nights_docker_38098822336/`) |

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
| wall time | `TimeoutStartSec=4h` per night; the first night re-scans every export and checks all ~2,508 BE rows once (~51 min at 1.2 s per request): roughly 1.3 h at OPD, 1.5 h outside (estimate, `docs/nightly.md`) | systemd |
| filesystem | Docker: read-only root (`--read-only`), private `/tmp` tmpfs of 1 GB (pdftoppm/tesseract scratch), writes only to the two mounted directories | Docker unit |

A night killed for memory exits 137; raise `GP_MEM` / `MemoryMax`. The image never runs as root (uid 10001, all
capabilities dropped, `no-new-privileges`); the venv unit runs as the `gegenprobe` system user that `install.sh --venv`
creates, with the checkout read-only (`ProtectSystem=strict`) and writes confined to `/var/lib/gegenprobe`. `make run`
uses the same container flags: the caller's uid, or 10001 when the caller is root (uid 0 is never passed to the
container; `out/` and `.work/make-run` are handed to 10001 first), `--read-only`, a 2 GB tmpfs `/tmp`, `--cap-drop ALL`,
`--security-opt no-new-privileges`, and two writable mounts: `out/` and `.work/make-run` (`GP_WORK`: caches and the
optional GGUF weights, kept between runs; delete it for a cold run).

## Operator settings

All optional, in `/etc/gegenprobe/alerts.env` (template with every key: `deploy/nightly/alerts.env.example`; comments on
their own lines, because Docker's `--env-file` keeps a trailing `# …` as part of the value).

| setting | default | what it does |
|---|---|---|
| `GP_USER_AGENT` | `hackapertus-research/0.1` | User-Agent of every request Gegenprobe sends (the development gateway `gw.py` aside, [External hosts](#operator-sheet)). **Set it**: your own product token and a contact **URL**, e.g. `opd-gegenprobe/0.1 (+https://openparldata.ch)`, so the hosts we fetch from can reach you. **Never an e-mail address**: the User-Agent is sent to every host and kept in their logs, so a personal address would be personal data. A value with an e-mail address (or `mailto:`) is refused: every fetch fails closed (`Disallowed`, kind `user_agent_email`) and a network night exits 1 before its first request. The default names no contact; a network night then prints a note on stderr and records `user_agent.has_contact: false` in `run.json` |
| `GP_OPD_TEXT` | `auto` | converter only (the environment of `python -m gegenprobe convert --opd-doc-id …`; the nightly job does not convert): a value found in OPD's own stored text also gets its span there (`opd_text_span`); the text is found by OPD's document id in the local cache, a docs snapshot or OPD's export (through `GP_EXPORTS_DIR` when set). The first lookup for a body can stream its docs export up to the document (0.47 GB for Bern), then the text is cached. `local`: no network; `off` (or `--no-opd-text`): no OPD spans |
| `GP_EXPORTS_DIR` | unset | read `files.openparldata.ch/exports/…` from this local directory (same layout: `index.json`, `affairs.ndjson.gz`, `docs/docs_<body>.ndjson.gz`, …); no export transfer. Docker unit: the directory is mounted read-only into the container at the same path (`--mount …,readonly`), so it must exist on the host (a missing path fails the night instead of downloading) and be readable by uid 10001. Leave the line commented out rather than empty |
| `GP_ADAPTER_CANARY` | `1` in the template | re-check one known affair per external adapter source each network night (operating plan below); `0` turns it off |
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

Rules are matched under **RFC 9309 §2.2.2**: the longest matching path wins, an `Allow` wins a tie, `*` and a final `$` are
wildcards. Python's `urllib.robotparser` applies the first match instead; until 11 Oct 2026 that let 147 requests to
disallowed www4.ti.ch paths through (`Allow: /` before `Disallow: /user_librerie/php/GC/allegato.php`; gold samplers,
`make run`, adapters, a census spot check; `docs/incidents.md`, `results/compliance/robots_audit_all.json`). Those
documents are now requested from OPD's own copy on files.openparldata.ch (`data/compliance/mirror_urls.json`, applied by
`src/sitecustomize.py` to `gegenprobe.net`). Since 11 Oct 2026 `src/sitecustomize.py` installs the RFC 9309 matcher
(`src/gegenprobe/robots9309.py`) into `urllib.robotparser` at interpreter start. Python loads it only when `src/` is on
`PYTHONPATH`, which both units provide: the Docker unit through the image's `ENV PYTHONPATH=/app/src:/app`, the venv unit
through `Environment=PYTHONPATH=/opt/gegenprobe/track_2a/src`. **Keep that line if you write your own unit or wrapper.**
To check a host, from the checkout: `PYTHONPATH=src python -c 'import urllib.robotparser as r; print(r.RobotFileParser.can_fetch.__module__)'`
prints `_gegenprobe_robots9309`. If it prints `urllib.robotparser` instead, the patch is not active. The OPD-copy routing:
`PYTHONPATH=src python -c 'import sys; from gegenprobe import net; print(sys.modules["_gegenprobe_mirror"].installed(net))'`
prints `True`.

**Fail-closed once the guard is loaded.** Earlier, a matcher that could not be installed printed a warning, and
fetching went on under `urllib.robotparser`'s first match. Now, in a process where the guard is loaded, every request
checks at request time that the RFC 9309 matcher is active, and is refused before any byte is sent when it is not
(`net.Disallowed`, kind `robots_matcher_inactive`; a `convert` row gets that status). The check lives in
`src/gegenprobe/compliance/fetchguard.py`, which wraps `gegenprobe.net`'s `open_url` and `allowed` (`net.py` stays
locked). Three things load it:
- `src/sitecustomize.py` (`src/` on `PYTHONPATH`, as above);
- `gegenprobe-robots9309.pth`, which `pip install -e .` (and `pip install .`) puts into site-packages (`setup.py`), so
  an installed checkout needs no `PYTHONPATH`. `make dev-install` does this for the development `.venv`
  (`--no-deps`, no dependency changes);
- `fetchguard.ensure()`, called at import by every unlocked module that imports `gegenprobe.net` or
  `gegenprobe.pdftext` (adapters, repair, census, monitor, `convert`, `qa_cli`, the viewer, the eval drivers;
  `tests/test_fetchguard.py` fails if one is missing).

**When it is not loaded.** A process that starts with none of the three, and then imports `gegenprobe.net` or the locked
`gegenprobe.pdftext` directly, fetches under `urllib.robotparser`'s first match: `python -S`; `python -I` in an
interpreter whose site-packages has no `gegenprobe-robots9309.pth`; or importing `gegenprobe.net` with `src/` on
`sys.path` only through the current directory (`cd src && python -c "import gegenprobe.net"`), where `site` never sees
`src/sitecustomize.py`. The locked samplers (`eval/gold/sample.py`, `eval/gold2/sample.py`) and `pdftext.fetch_pdf`
cannot call `ensure()`; they are covered only by the first two. Use the documented entry points (`make …`, the units,
the image) or install the checkout. To check the guard:
`PYTHONPATH=src python -c 'import sys; from gegenprobe import net; print(sys.modules["_gegenprobe_fetchguard"].installed(net))'`
prints `True`. Re-run the project-wide audit with `python -m gegenprobe.compliance.audit --offline` (stored robots.txt
copies) or `--refresh` (one robots.txt request per host).

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
| `results/repair_BE_ledger.tsv` | every row ever proposed, with `first_seen` / `last_seen` and a status: `pending` (checked), `review` (check failed), `unchecked` (never checked: seen only on offline nights; a row checked once keeps that verdict on later nights), `resolved` (left the list because OPD now has the answer), `dropped` (left the list, still unanswered) |
| `results/run.json` | timings, bytes read by source (`bytes`: single exports, docs/texts streamed, index, canton tables, total, over the network; `transfer_bytes` is the older single-exports-only field), peak memory, counts, delivery result of the night |
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
| `repair_<body>.tsv` (`ocr`) | OCR the scan (deu+fra+ita) and store the text; skip affairs the adapter list names (it wins, `results/repair/MANIFEST.json`) | batch job, once |
| `adapters_<body>.tsv` (`counted=true`, `tag_answer`) | set `category_harmonized` of `opd_doc_id` to `target_category` (`response_text`); the text is already in OPD | data engineer (bulk; 2,177 rows) |
| `adapters_<body>.tsv` (`counted=true`, `extract_tag`) | extract (OCR) OPD document `opd_doc_id`, check `text_sha256`, set the category | OCR batch job (852 rows) |
| `adapters_<body>.tsv` (`counted=true`, `fetch`) | fetch `source_url` (robots.txt allows it), attach to the affair, set the category | scraper owner (3,584 rows; new sources for ZH, SG, SO, LU, VS, Aarau) |
| `adapters_<body>.tsv` (`tier=review`, `tier=identity_wording_only`) | `review_reason` says what to check; Jura's 282 need a date | data engineer |

**Acceptance test of the staging fix:** `python -m gegenprobe.repair.acceptance --fetch` (or a local `docs_BE.ndjson.gz`;
with `GP_EXPORTS_DIR` set, `--fetch` reads the local file) counts how many of the 2,459 relink documents are attached to the
affair the list names. 6 Oct 2026 snapshot: none; all 2,459 are still parentless.
After the fix it should be 2,459 of 2,459. It exits 0 when that holds and 1 otherwise, so it can gate a deployment, and
writes one dated file per check (`results/repair/acceptance_<live|file>_<YYYY-MM-DD>.json`). Under the venv unit the
checkout is read-only: add `--out /var/lib/gegenprobe/results` (checked before the 470 MB export is streamed; exit 2 if
the directory is not writable).

**Applying the BE lists:** `python -m gegenprobe.repair.apply_be --fetch --out DIR` (or `--docs-export
docs_BE.ndjson.gz`) writes the apply plan: per relink the document's current parent, `hash` and file URL and the values
after the relink, per begin_date row the before and after value, and guarded `UPDATE` statements as text. It changes
nothing anywhere. Re-parenting changes OPD's document identifier (`hash` = sha256(body_key + parent_type + url)) and so
the document's `files.openparldata.ch/doc` URL; `--hash keep` plans the relink without that change (`docs/repair.md`).

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
| `adapter_canary_failed` | (with `GP_ADAPTER_CANARY=1`) a known counted affair of an external source no longer verifies; `reason` says where (http_404, not_found, robots_disallowed, empty_text, date_mismatch, ...) | the adapter's owner: open the source, fix the adapter, re-run that body (operating plan below) |
| `adapter_canary_text_changed` | the canary still verifies but its extracted text changed (file re-published, extractor update) | none unless it repeats; re-run `canary select` after the next monthly run |
| `adapter_counted_drop` | a parliament's counted adapter rows fell by more than max(5, 2 %) since the last canary run | compare the new `adapters_summary.json` with the previous one before publishing the lists |
| `adapter_canary_error` | the canary step itself failed (the night continues) | run `python -m gegenprobe.repair.adapters.canary run` by hand |
| `outbox_corrupt` / `state_corrupt` | the outbox or the night-over-night state could not be parsed; moved to `work/nightly/<name>.corrupt-<UTC>` | read the quarantined file for undelivered alerts; after `state_corrupt` the next night re-scans everything once |
| unit failed (exit 1) | the job crashed, or the alert channel failed | `journalctl -u gegenprobe-nightly`; the next night retries from scratch |
| unit failed (exit 2) | nothing to work on yet (an `offline` / `index` run on an empty cache) | run the command the message names (a network night first) |

**Delivery before state.** Alerts are written to `work/nightly/outbox.json`, sent, and removed from the outbox only when
the send succeeded; only then is the night's state committed. A webhook or mail server that is down costs nothing: the
alerts stay in the outbox, the unit exits 1, and the next night sends them again (listed as
`undelivered_from_previous_nights` in `alerts.json`). The outbox and `state.json` are written atomically (tmp + fsync +
rename). A corrupt outbox or state file is moved to `<name>.corrupt-<UTC>` and reported (`outbox_corrupt` /
`state_corrupt`); the night continues. Deleting `work/` deletes undelivered alerts too. Exit codes: 0 quiet night, `GP_ALERT_EXIT` (default 3) alerts,
1 job or delivery failure, 2 nothing to work on yet (`nightly offline` / `nightly index` on an empty cache: the message
names the command to run first). **One alert per event:** the job delivers its alerts itself; the failure notifier
(`OnFailure=`) posts to the webhook only when the night failed (exit 1, 2, a crash, a timeout, an OOM kill), not on a
night that exited `GP_ALERT_EXIT` after delivering (it reads `MONITOR_EXIT_STATUS`, systemd ≥ 251; older systemd posts on
every failure). `python -m gegenprobe.monitor.notify test` exits 0 when sent, 2 when no channel is configured,
1 when sending failed.

## Adapters: operating plan

The source adapters (`docs/adapters.md`) are a batch, not part of the nightly job: they read 50 parliaments' sources
(7 external hosts plus OPD's own copies) and write the lists OPD applies (`results/repair/adapters/adapters_<BODY>.tsv`).

| what | when | who | command |
|---|---|---|---|
| re-run every adapter on the new targets | monthly (first week), and after an adapter change | adapter owner (data engineer, repair workstream) | `python -m gegenprobe.repair.adapters.targets`, `... opd_docs`, `... run BODY ...` (resumable, polite), then `make adapters-write` |
| check before publishing a re-run | after every re-run | adapter owner | `make test` (list hygiene: tier, counted = verified, opd_doc_id, text_sha256, target_category); compare `adapters_summary.json` per parliament with the previous run (`adapter_counted_drop` fires on a drop); `python -m gegenprobe.repair.adapters.canary select` |
| canaries: one known counted affair per external source, re-checked live | nightly (`GP_ADAPTER_CANARY=1` in `/etc/gegenprobe/alerts.env`), or by hand | the nightly's alert channel; first responder = adapter owner | `python -m gegenprobe.repair.adapters.canary run` (exit 3 on alerts) |
| blind audit of the counted tiers | after a re-run that changes a tier's rule or adds an adapter | adapter owner + two auditors from different vendors | `python -m gegenprobe.repair.adapters.audit3 draw`, then the second auditor with `qwen --backend openai` (any OpenAI-compatible server: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_NAME`; never an Apertus model), then `score`. Plain `qwen` is development-only: it calls Qwen through the developer's budget gateway (`GP_GATEWAY_DIR`) |
| robots.txt re-audit of every URL fetched | after every re-run | adapter owner | `python -m gegenprobe.repair.adapters.robots_audit` |

**Canaries** (`results/repair/adapters/canary.json`, `src/gegenprobe/repair/adapters/canary.py`): Kantonsrat Zürich CDWS
(ZH, a `fetch` row), RIS St. Gallen and RIS Solothurn, the Valais front-end API, Luzern's affair pages, Aarau's yearly
pages, and OPD's own file copies (`files.openparldata.ch`, an `extract_tag` row through OCR). Each canary runs its
adapter's whole path (the source's API or index, a fresh download that bypasses the URL cache, extraction, the checks) and
compares the outcome and the text hash with the committed list; its excerpt goes to `work/canary/`, never over the run's
own. About 45 requests and 70 seconds a night (estimate; Aarau's nine yearly index pages are 14 of the requests). The live
run of 11 Oct 2026 is committed: `results/repair/adapters/canary_runs/2026-10-11.json`, 7 of 7 verified with the committed
text hash, no alert, 67.6 s wall. Requests go one at a time per host, through the same RFC 9309 robots check and
OPD-mirror fallback as every fetch. `GP_ADAPTER_CANARY=1` is set in the template (`deploy/nightly/alerts.env.example`),
so an installed night runs the canaries unless the operator sets `0`. `canary check` (offline, in `make test`) asserts that every canary is a counted row of its committed list
with the committed text hash. Offline drills: `canary run --fixtures DIR` reads `DIR/<BODY>_<affair_id>.txt` instead of
the network. A failed canary blocks publishing that parliament's next list until the adapter is fixed and the canary
verifies again.

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
earlier a shared 120 s let P1 use all of it and CI reached 0 of 62 P2 documents); worst case 240 + 2 × 180 s of
re-derivation on top of the replay steps.

**OCR models are pinned; OCR fails loudly.** The OCR numbers in `docs/repair.md` and the scanned strata of P1/P2 were
measured with Tesseract 5.5.3 and the tessdata_fast models at commit `8741641` (`TESSDATA_COMMIT`, sha256 per language in
`TESSDATA_SHA256`, both in `src/gegenprobe/ocrguard.py`). The image downloads exactly those `deu`, `fra`, `ita` and `eng`
files at build time, checks each sha256 (a mismatch fails the build), and points tesseract at them
(`TESSDATA_PREFIX=/usr/local/share/tessdata-pinned`). It installs no Debian language packages. The tesseract binary is
still Debian's (bookworm ships 5.3.0), so only the binary differs from the measured setup, not the models.
`GP_OCR_REQUIRE_PINNED=1` (set in the image) makes every OCR call refuse models that differ from the pins.

Outside Docker, run `python -m gegenprobe.ocrguard` to check whether OCR can run on the host and with which models. It
exits 1 when tesseract or a language is missing. To use the measured models on a host (venv unit, `python -m gegenprobe
run`, `convert`), install the tesseract binary from the distribution (Debian/Ubuntu `apt install tesseract-ocr`,
Homebrew `brew install tesseract`), then run `make ocr-models`. It puts the four pinned files into
`TESSDATA_DIR` (default `<GP_WORK>/tessdata-pinned`) and keeps a file that is already there with the pinned sha256. It
downloads only what is missing or different, through `ocrguard.install_pinned`, which refuses a mismatch. It then checks
every sha256 against `TESSDATA_SHA256`. Last, it asks tesseract, with `GP_OCR_REQUIRE_PINNED=1`, whether it reads
deu+fra+ita with exactly those models. It exits 1 if any check fails. The last line it prints is the export to use:

```bash
make ocr-models                       # ... tesseract 5.5.3 reads deu+fra+ita from .../tessdata-pinned with the pinned models
export TESSDATA_PREFIX=$PWD/.work/tessdata-pinned GP_OCR_REQUIRE_PINNED=1
```

For the venv unit, put both variables into `/etc/gegenprobe/alerts.env` (with `TESSDATA_DIR` under `/var/lib/gegenprobe`).
`python -m gegenprobe.ocrguard install-pinned DIR` remains the installer the Dockerfile runs.
OCR never fails silently. A missing language pack, a non-zero tesseract exit or a scan with no recognised text raises
the typed failure `ocr_failed` (a `convert` failure row, a counted line in `make run`'s rederive step). Such a result is
never cached. Earlier, a host without the deu/fra/ita data cached empty pages and turned scans into typed nulls.
Measured on the development Mac: with Homebrew's tesseract (eng/osd only), rederive now reports "22 scans skipped (OCR not
ready: … no language data for deu+fra+ita)" instead of 22 silent differences. With the pinned models and an empty text
cache, all 154 of 154 held-out documents re-derive, the 22 Ticino scans re-OCR'd from scratch included (313 s). The
nightly job reads text layers first and uses OCR only for image-only scans of new rows.

## Sandboxing

Both units are sandboxed by systemd; `systemd-analyze security` scores what remains exposed (0 = nothing, 10 = nothing
restricted). CI job `systemd-units` prints the score of both units (`systemd-analyze security --offline=true`) and fails
when a unit scores above its threshold:

| unit | what it confines | threshold | not set, and why |
|---|---|---|---|
| venv (`gegenprobe-nightly-venv.service`) | the job itself: user `gegenprobe` in its own user namespace, no capabilities (`CapabilityBoundingSet=`), `NoNewPrivileges`, read-only OS and checkout (`ProtectSystem=strict`), writes only to `/var/lib/gegenprobe` (`ReadWritePaths`), no `/home`, private `/tmp` and `/dev`, kernel tunables/modules/logs/clock/cgroups/hostname protected, `/proc` shows only its own processes, sockets `AF_INET AF_INET6 AF_UNIX` only, native system calls from `@system-service` without `@privileged`, `UMask=0027` | **2.0** | `PrivateNetwork=`/`IPAddressDeny=` (it fetches from OPD, the canton and the source sites), `MemoryDenyWriteExecute=` (libffi trampolines on some Python builds), `ProcSubset=pid` (tesseract/OpenMP read `/proc` system files on some platforms) |
| Docker (`gegenprobe-nightly.service`) | the root docker **client** that starts the container: `NoNewPrivileges`, private `/tmp` and `/dev`, kernel and namespace protections, Unix sockets only, `@system-service` system calls. The job runs in the container (uid 10001, read-only root, no capabilities, no-new-privileges, memory/CPU/pids ceilings), which `systemd-analyze` cannot see | **5.0** | `User=` (the docker socket), `ProtectSystem=`/`ProtectHome=`/`CapabilityBoundingSet=` (`ExecStartPre` creates and chowns the state directories and touches `alerts.env`) |

Everything the venv job writes goes to `/var/lib/gegenprobe` (`GP_WORK=…/work`, `GP_MONITOR_OUT=…/results`,
`HOME=/var/lib/gegenprobe`, `PYTHONDONTWRITEBYTECODE=1`) or the private `/tmp` (pdftoppm/tesseract scratch); the checkout
under `/opt/gegenprobe` is never written. A night that fails with `Permission denied`, `Read-only file system` or
`Operation not permitted` after a change of the job points at the sandbox: `journalctl -u gegenprobe-nightly` names the
path or system call, and `systemctl edit gegenprobe-nightly` can relax one setting locally.

## Review mode in operation

The nightly job never calls a model. Review mode is a converter option (`python -m gegenprobe convert … --mode review`):
on the documents the frozen rules leave open (the residue: 97 of the 154 held-out documents, `results/report/cost.json`)
the Apertus pointer attaches a suggested answer date with page, span, margin and θ, flagged `needs_review`; it is never
written into the field (`docs/converter.md`).

**θ belongs to one served build.** θ is a margin threshold fitted on dev labels for one build
(`data/convert/theta/<build>.json`). It does not transfer across builds, quantisations or prompts, and a host can change
the weights or the inference stack behind an unchanged model name. The θ file records the `system_fingerprint`s the
server answered from during the fit (`served_fingerprints`; the evaluation fingerprints are also in
`results/eval/served_models.json`). In review mode the backend is wrapped in a guard (`convert/build_guard.py`): the
first response from any other fingerprint stops the run with exit code 3 before a suggestion from it is attached; a θ
file without fingerprints is refused up front; for the local GGUF build the weights file is the build (sha256 pinned in
`served_models.json` `gguf_pin`; `llm.fetch_gguf` refuses any other file). `--allow-build-mismatch` turns the refusal into
a warning and marks every suggestion `build_mismatch` (fitted vs served), for a reviewer who wants suggestions anyway
during a refit. A θ given with `--theta` is the operator's own choice and is not checked.

**Refitting θ** (when the guard stops a run, or when the host announces a new model or inference build), from a checkout
with network access to the model server:

```sh
# 1. confirm: the run stops and names the served fingerprint (exit 3)
python -m gegenprobe convert <answer.pdf> --mode review --backend openai
# 2. the committed dev documents (polite fetch by URL into .work/pdf, each checked against its committed sha256)
make gold-dev-fetch
# 3. fit θ on the dev labels (data/gold/dev_labels.jsonl) for the build the server now serves
LLM_BASE_URL=https://<server>/v1 LLM_NAME=<model> LLM_API_KEY=<key> make theta BACKEND=openai
#    -> data/convert/theta/<build>.json: theta, leave-one-out accuracy, AUROC, n, and served_fingerprints
# 4. check before use: compare loo.acc / auroc with the fit it replaces (committed 70B fit: LOO 124/127, AUROC 0.993);
#    a markedly worse fit means the new build is not a drop-in: re-run the held-out arms before deploying it
make arms SPLIT=heldout BACKEND=openai
# 5. deploy the new θ file with the converter; the guard now accepts the fingerprints it records
```

Notes: `make theta` writes into the checkout's `data/convert/theta/`. In this repository those files are the evaluation
record and are hash-locked (`eval/prereg/LOCK`), so refit in the deployment's own copy, not here. 30 of the 127 dev
labels are spike documents whose texts live outside the repository (`SPIKES` in the locked `eval/arms.py`). `make
theta` runs it through `eval/devrun.py`, which takes that folder from `GP_SPIKES_DIR`; without the folder, set
`GP_SPIKES_DIR=none` and θ is fitted on the 97 committed dev documents (a dev-split command without either stops with
that message before any model call). A fit
costs one pointer run over the dev set (3.5 calls per document on average).

**Who reviews.** The data engineer who runs the nightly job owns review mode (refits, the guard's exit 3). Suggestions go
to the person who already handles `repair_BE_review.tsv`: `--queue FILE` writes the rows that need review, strongest
band first. Post hoc, 26 of 33 `strong`-band suggestions (margin ≤ −5) and 3 of 11 `weak`-band ones were right
(`results/convert/band_precision.json`). Reviewer time per suggestion has not been measured.

**Cost per 1,000 residue documents** (committed measurements, `results/report/cost_end_to_end.json`): on Public AI's
served build, 3.5 calls and 5,905 billed prompt tokens per residue document, **USD 0.59** at the list price of USD 0.10
per million prompt tokens; with the local 8B GGUF on one 4-vCPU machine, 179.6 s wall per document (PDF fetch, text and
model load included), **49.9 machine-hours** and 9.3 GB peak memory. 1,000 converted documents contain about 630 residue
documents at the held-out residue share (97/154; not measured on the corpus mix).

## Checked in CI

`.github/workflows/ci.yml` job `systemd-units` runs `systemd-analyze verify` on both unit variants with the timer and the
failure notifier, prints and gates both units' `systemd-analyze security` exposure (thresholds above, "Sandboxing"),
then starts the failure notifier under real systemd behind two stand-in units (one exits 3, one exits 1)
and checks that exactly one webhook post with valid JSON arrives; job `test` and job `nightly-smoke` (inside the built image)
assert that robots.txt is matched under RFC 9309 and that a process without the matcher fetches nothing
(`src/sitecustomize.py`, `tests/test_fetchguard.py`, see Operator settings); job `nightly-smoke` builds
the image and runs three offline nights on fixture exports inside it with the unit's container flags and no network (`docs/nightly.md` "Verified
in CI"), then one network-mode night (`nightly run`) whose exports come from a root-owned, read-only fixture directory in
OPD's layout, passed exactly as the Docker unit passes it (`--env-file` with `GP_EXPORTS_DIR`, `--mount
type=bind,…,readonly` at the same path, `--network none`; `gegenprobe.monitor.smoke local-exports-check`; the same
night runs under pytest, `tests/test_monitor_smoke.py`). `.github/workflows/nightly-real.yml` (manual: `gh workflow run nightly-real.yml`) installs the venv variant with
`install.sh --venv` on a GitHub-hosted Ubuntu runner and runs one real network night under systemd, with a contact
User-Agent; it uploads `run.json`, the journal and the wall time. One run is committed (`results/monitor/night_real_38062530586/`:
a first night, 83 min wall, 0 alerts, the BE list reproduced on live data; its run.json predates the streamed-bytes
counter, so the bytes it read are reconstructed from the index it read: `results/monitor/night_real_bytes.json`, 6.2 GB
of docs/texts streamed plus 198 MB of single exports). `.github/workflows/nightly-real-docker.yml` (manual:
`gh workflow run nightly-real-docker.yml -f wait_for_new_index=true -f max_wait_min=180`) runs the recommended Docker
variant: it builds the image and installs the Docker unit with `install.sh`, runs night 1, waits for OPD's next export
(optional), then runs night 2 on night 1's persisted state, so the index diff, the ledger, retries, outbox redelivery
and the drop/trend alerts run against a real previous night; it uploads both nights' `run.json`, journal excerpts and
wall times and `two_nights.json`.

## Development-only paths

Two directories outside the repository served development and are never needed in operation. Both come from the
environment (`src/gegenprobe/devpaths.py`); the default is a sibling of the checkout (`<checkout>/../spikes`,
`<checkout>/../gateway`), not a fixed home path.

| variable | what it holds | who reads it | without it |
|---|---|---|---|
| `GP_SPIKES_DIR` | the exploration spikes: texts of the 30 spike dev items, the recovery spike's cached PDFs, canton tables and funnel | `make convert` (`eval.replay_spikes`, `eval.dev_rules`), `make theta` / `make arms` on the dev split, `make gold-dev` / `gold-heldout` (re-draws), `repair.be verify40`, `repair.ocr probe`, `repair.che reproduce`, `make census` when `GP_BE_OGD` is unset (the nightly job sets it) | a clear error names the variable; `GP_SPIKES_DIR=none` fits θ on the 97 committed dev documents; `census` and `compliance.audit` skip their spike comparisons |
| `GP_GATEWAY_DIR` | the developer's budget gateway (`gw.py`: per-tag spending caps, ledger, cache) | backend `gateway:<model>:<tag>:<cap>` of `make theta` / `make arms`, `audit3 qwen` (plain), `eval/posthoc_r5.py`, `eval/gold6/qwen6.py` | a clear error that names the operator backends: `openai` (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_NAME`) or `gguf` |

The locked modules (`eval/arms.py`, `eval/gold/sample.py`, `eval/gold6/qwen6.py`, `src/gegenprobe/llm.py`'s `Gateway`)
name the developer's layout literally and cannot be edited. Run them as `python -m eval.devrun <module> …` (the Makefile
does): it redirects exactly the two literal prefixes to `GP_SPIKES_DIR` / `GP_GATEWAY_DIR` and runs the module
unchanged. Everything an operator runs (the nightly job, `make run`, the adapters, the canaries, review mode with
`openai` or `gguf`) reads neither directory. The gateway's requests carry the default User-Agent
`hackapertus-research/0.1`, not `GP_USER_AGENT`: it is the one request path that does not read the variable.

## Swiss / EU hosting

The job processes only public parliamentary data and sends nothing anywhere unless an alert channel is configured by the
operator. It runs on any Swiss or EU Linux host; nothing in it depends on a particular provider.
The evidence viewer is static files only and makes no third-party request: its two fonts are served from `site/fonts/`
(SIL OFL 1.1), not from Google Fonts.

## Supply chain

Base image `python:3.11.14-slim-bookworm` pinned by digest (`Dockerfile`); Python dependencies installed with
`--require-hashes` from `requirements.lock`. CI: every GitHub Action is pinned to a full commit SHA (version in a comment),
the gitleaks binary is checked against the sha256 from its release's checksum file before it runs, and the test job
installs `requirements.lock` + `requirements-dev.lock` (ruff) with `--require-hashes`. The 8B workflows install
`requirements.lock` with `--require-hashes` too; their llama-cpp-python step (CPU wheel index, with a source build as
fallback) is not hash-pinned, because a source build has no fixed file hash: the hash-pinned path for that wheel is
`requirements-gguf.lock` (`docker build --build-arg GGUF=1`). The optional 8B path pins the llama-cpp-python 0.3.35 CPU wheels by sha256
(`requirements-gguf.lock`) and the model file by sha256 (`llm.GGUF_PINS`). The model is a community Q4_K_M quant
(`Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF`, Apache-2.0) of a text-only export (`andreasmartin/apertus-v1.5-8b-text`,
Apache-2.0) of `swiss-ai/Apertus-v1.5-8B` (Apache-2.0). An operator who wants the whole chain under its control can
re-quantise from the official weights with llama.cpp (`convert_hf_to_gguf.py`, then `llama-quantize … Q4_K_M`), keep
the file on its own storage and set `GP_GGUF_FILE` and `GP_GGUF_SHA256` (both required, fail-closed; no code edit).
**Load guard** (`src/gegenprobe/gguf_guard.py`): the weights file is hashed against its pin each time it is loaded (a
mismatch stops the load), and the GGUF's built-in chat template is rendered in a Jinja sandbox
(`ImmutableSandboxedEnvironment`; byte-identical prompts on the pinned file). A file that matches no pin is its own
build with its own cache and θ, so review mode refuses it until a θ is fitted for it. The nightly job does not use a model at all.
