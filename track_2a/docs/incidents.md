# Incidents

Operational incidents of Gegenprobe: what happened, what was affected, what was done. Newest first.

## 2026-10-09 to 2026-10-11: 147 requests to paths that www4.ti.ch's robots.txt disallows

**Summary.** Until commit `099f416` (11 Oct 2026, 00:48 CEST), `gegenprobe.net` judged robots.txt with Python's
`urllib.robotparser`, which applies the *first* matching rule. RFC 9309 applies the *longest*. www4.ti.ch (Canton
Ticino) lists `Allow: /` before its `Disallow` lines, so every path it disallows looked allowed to us. OPD records the
parliament's own URL for each document (`url` in the docs exports), and our gold-set samplers fetched those recorded
URLs. Between 9 and 11 Oct 2026 the project requested **147 distinct www4.ti.ch URLs on disallowed paths: 133 downloads,
11 bodies read and discarded, 2 header-only requests and 1 HTML page**. Automated runs on GitHub's servers re-downloaded them: at most 4,942 downloads before the fix, counted per executed
fetching step of the 112 runs created before it (at most 22,268 HTTP requests if every download had used all the retries
the code allows; `results/compliance/ci_repeats.json`). Each process kept at least 1.2 s between its own requests to
www4.ti.ch. Processes on separate runners did not coordinate: at most 8 fetching steps ran at once (10 Oct, 13:37 UTC:
six `arms-8b-par` shards and two CI runs), so at most 8 requests could arrive within any 1.2 s. No other host
was affected. Every document used in evaluation that we could compare (126 of 130) is byte-identical to OPD's own public
copy on files.openparldata.ch. The other 4 were downloaded without logging their sha256. All re-fetches now go to OPD's
copy. A first version of this entry (10 Oct) said three files were involved. That was wrong: it covered only the
source-adapter run.

### What happened

- **The parser.** `net.allowed()` (`src/gegenprobe/net.py`, locked by LOCK2/LOCK5) has called
  `urllib.robotparser.RobotFileParser` since the first fetches on 9 Oct. www4.ti.ch's robots.txt reads:

      User-agent: *
      Allow: /
      Disallow: /poteri/gc/ricerca-messaggi-e-atti/ricerca/
      …
      Disallow: /user_librerie/php/GC/allegato.php

  For `/user_librerie/php/GC/allegato.php?allid=…`, urllib stops at `Allow: /` (1 octet). RFC 9309 §2.2.2 picks
  `Disallow: /user_librerie/php/GC/allegato.php` (34 octets) and disallows the URL. The same rules were in force when
  the adapters read the file on 10 Oct (`tests/test_robots9309.py`), and they are unchanged today.
- **Why the samplers asked the parliament.** Gold-set samplers fetch the URL OPD records for a document, and OPD
  records the parliament's URL. For Ticino that is `allegato.php`. OPD also keeps its own copy at
  `files.openparldata.ch/doc/TI/<hash>` (`url_oparl`), but the samplers did not use it.
- **Where.** In `eval/gold/sample.py` (P1, 9 Oct) and `eval/gold2/sample.py:fetch_one`, which P3, P5 dev and the later
  samplers reuse (10 Oct). Also in `make run`, which re-fetches the held-out and demo documents from their recorded URLs,
  in CI and on the CI workflows that fetch gold documents. Also in the source adapters (10 Oct), and in
  `census/source_formats.py` (10 Oct: one page and two header requests).
- **Before the repository.** The recovery spike (`spikes/recovery`, 8 Oct) used the same stdlib parser and downloaded 20
  further www4.ti.ch files. The project read those files later: `repair/ocr.py` probe and `repair/be.py verify40`.

### Scope (audit of every recorded request)

`python -m gegenprobe.compliance.audit` → `results/compliance/robots_audit_all.json`. The audit collects every URL that
the project fetched or records as fetched: the gold files and fetch logs (doc-level logs joined to OPD's URL by doc id,
affair-level logs to the question/answer pair the sampler chose), the WORK drafts, the converter demo, the repair
results, the adapters' download cache, the census spot check, OPD exports, the nightly job's canton requests, the spike,
and the documents `make run` re-fetched in the four recorded CI runs. That is 14,152 distinct URLs on 75 hosts, 78 with the spike. The
audit then reads each host's robots.txt once on 11 Oct 2026 (copies in `data/compliance/robots/`) and judges every URL
under RFC 9309 (`gegenprobe.robots9309`).

Distinct www4.ti.ch URLs on disallowed paths, by the module that requested them. Rows overlap: the CI and demo documents
are among P1's.

| module | date | downloaded | body discarded | headers only | HTML page | what they are |
|---|---|---:|---:|---:|---:|---|
| P1 sampler (`eval/gold/sample.py`) | 9 Oct | 104 | 7 | | | 21 dev + 40 held-out gold documents; 43 drafted or rejected candidates; 7 non-PDF bodies |
| P3 sampler (`eval/gold3`) | 10 Oct | 6 | | | | 3 gold affairs (question + answer) |
| P5 dev sampler (`eval/gold6`) | 10 Oct | 20 | 4 | | | 8 gold affairs (16 documents); 4 questions of rejected affairs; 4 Word answers (not PDF, discarded) |
| converter demo (`make run` step 4) | 9 Oct | 3 | | | | 3 dev/held-out documents |
| `make run` in CI (cold cache) | 10 Oct | 43 | | | | 40 held-out + 3 demo documents, re-downloaded in each run |
| source adapters | 10 Oct | 3 | | | | `allid=115005, 119023, 137701` (deleted the same day) |
| `census/source_formats.py` | 10 Oct | | | 2 | 1 | atto page 101174 and two answer attachments |
| **project, distinct** | 9-10 Oct | **133** | **11** | **2** | **1** | 147 URLs; the first-match parser allowed all 147 |
| spike (`spikes/recovery`, before the repo) | 8 Oct | 20 | | | | image-only answers re-extracted, gap audit |

The table counts distinct URLs. Repeat downloads come on top of them:

How the bound is counted (`python -m gegenprobe.compliance.ci_repeats`). The input is a snapshot of every GitHub
Actions run created before the fix was pushed (2026-10-10T22:48:08Z), with each job's steps, conclusions and times
(`data/compliance/ci_runs_before_fix.json`, 112 runs). A step that fetches documents is recognised by its command. Each
executed fetching step can have downloaded at most the disallowed www4.ti.ch documents of the sets it reads, each once.
Those are judged under RFC 9309 against the stored robots.txt: dev 21, held-out 40, P2 0, P6 0, converter demo 3.

- **`make run` in CI** (96 runs, every push): held-out, P2 and the demo, at most 43 per run, so at most 4,128. The four
  recorded runs (`results/ci/docker_make_run_*.json`; 38043355800, 38049690293, 38062904003, 38076870082) downloaded 42,
  43, 43 and 43; runs that failed before the re-derivation step made fewer.
- **Manually dispatched 8B workflows** (fresh runners, no PDF cache). Executed fetching steps: `arms-8b` 4 dev and 6
  held-out (324), `arms-8b-par` 9 dev and 6 held-out (429), `arms-8b-fill` 1 held-out (40), `arms-8b-p6` 1 dev + P6 (21).
  Steps that never ran (`skipped`) are not counted.
- **Workflows that made no such request.** `arms-8b-p2` (1 run, 6 shards) fetched only the 62 P2 documents, none on
  www4.ti.ch. `gguf-8b` (4 runs) ran the scorer checks (`selfcheck`, `diag`, `impl`) on committed token-id fixtures and
  downloaded only the model file and llama.cpp sources; its `arms` step, the only one that reads documents, was skipped
  in all 4. `nightly-real` (1 run) read OPD's exports and Bern's sources only.
- **Retries.** `net.open_url` retries a request after a 429, a 5xx or a timeout: up to 5 attempts per document in
  `make run`, 2 in the 8B workflows. No run logged a retry. Counting every allowed attempt gives the 22,268.
- **The earlier bound.** Round 6 multiplied each workflow's run count by its full per-invocation fetch (6,655: ci
  4,128, `arms-8b` 6 × 261, `arms-8b-par` 2 × 387, fill 40, `arms-8b-p6` 147) and left out `arms-8b-p2` and `gguf-8b`.
  Both made no request to www4.ti.ch, so 6,655 is also an upper bound on downloads, a looser one.
- **Local log records.** Counting each logged event once, the project made 450 requests to disallowed www4.ti.ch paths,
  436 of them downloads (`totals.project`).

Other hosts:

- **No other host has a disallowed path among the requests that were sent.**
- **Refused at the time.** 90 further URLs on disallowed paths were refused by `net` when they were requested: www.sz.ch
  45, www.locarno.ch 28, www.gl.ch 17. No request was sent for them.
- **The adapters' own audit** (`results/repair/adapters/robots_audit.json`). Of the 7,463 documents in the adapters'
  download cache, the 7,393 on hosts whose robots.txt could be read include no disallowed path; the three files above
  had been deleted from that cache on 10 Oct. 70 (www.ilef.ch, www.pratteln.ch) could not be re-checked. The 1,157
  disallowed parliament URLs that audit lists are URLs OPD records next to its own copy; the adapters did not request
  them.
- **Not re-checkable today.** robots.txt does not answer from our network today on 11 hosts (www.ilef.ch, www.nw.ch,
  www.ow.ch, www.stadtluzern.ch, www.waedenswil.ch, www.pratteln.ch, sieldocs.vd.ch 503, and others; 139 downloaded
  URLs). `net` fails closed: it fetched from these hosts only at times when their robots.txt could be read.

### What was derived from them

- **Gold labels.** All 21 dev and 40 held-out labels of the Ticino documents (`data/gold/{dev,heldout}_labels.jsonl`).
  The P3 labels of 3 affairs, and the P5 dev labels of 8 affairs.
- **Evaluation results that score those labels.** P1 dev tuning (θ), P1 held-out (40 of 154 documents), P3 and P5 dev.
  Also the post-hoc publisher-title check, whose 20 documents are all Ticino.
- **Converter demo outputs** for 3 documents.
- **Local work files.** Extracted texts in WORK (`text/`) and annotation packets in WORK (`gold*/packets`, `p5dev/`).
- **Census spot check.** The 10 Oct spot check (`r100.19.doc`), now withdrawn (see remediation 4).
- **What is committed.** No document text: only ids, URLs, sha256 hashes, page numbers and short quotes in labels.

### Remediation

1. **One RFC 9309 matcher for every entry point** (commit `099f416`, 11 Oct 2026). `src/gegenprobe/robots9309.py`
   implements the longest match, allow wins ties, `*` and a final `$`, merged groups and normalized percent escapes.
   `src/sitecustomize.py` installs it into `urllib.robotparser` at interpreter start. `net.py` is unchanged (locked),
   and `net.allowed()` now decides by RFC 9309. Each entry point puts `src/` on `PYTHONPATH`:

   | entry point | how `src/` gets on sys.path |
   |---|---|
   | `make test`, `make claims`, every host `make` target | Makefile `export PYTHONPATH := src:.` |
   | `make run` (Docker), Docker nightly unit, CI `nightly-smoke` | Dockerfile `ENV PYTHONPATH=/app/src:/app` |
   | venv nightly unit | `Environment=PYTHONPATH=/opt/gegenprobe/track_2a/src` |
   | subprocesses of the nightly job and its smoke test | `monitor/nightly.py`, `monitor/smoke.py` set `PYTHONPATH` |
   | CLI, CI `test` job | `export PYTHONPATH=src:.` |
   | bare `pytest` | `tests/conftest.py` installs the same patches |

   CI asserts the patch on the runner and inside the image. From that commit on, every request to these paths is
   refused, including requests from the locked samplers and the CI workflows.
2. **OPD's copy instead of the parliament's URL** (11 Oct 2026). `data/compliance/mirror_urls.json` maps 165 of the 167
   URLs (147 project + 20 spike) to OPD's copy, `files.openparldata.ch/doc/TI/<hash>`. The two unmapped URLs belong to
   the census spot check: OPD has no record of them. For each mapped URL the file records whether OPD's copy is
   byte-identical (`sha256_match`):
   - true for 144: all 126 evaluation documents whose sha256 was recorded, and 18 spike PDFs;
   - false for none;
   - null for 21: 11 bodies were discarded and 1 request read headers only, so nothing was kept to compare; 7
     downloads (4 P5 dev questions, 3 adapter files) were made without logging their sha256, and WORK holds OPD's bytes
     for each of them; 2 spike Word files were kept only as extracted text.

   `src/sitecustomize.py` patches `gegenprobe.net.open_url` as soon as `gegenprobe.net` is imported
   (`gegenprobe/compliance/mirror.py`). That function is what `net.get`, `pdftext.fetch_pdf`, the samplers,
   `eval/rederive.py`, `eval/replay_all.py`, `eval/run_arms.py`, `eval/run_arms_p2.py` and `eval/p6/run_8b.py` fetch
   through, so a mapped URL is requested from OPD and never from www4.ti.ch, with no change to locked code. A re-fetch
   that pins the sha256 (re-derivation) verifies OPD's copy against the committed hash. `tests/test_compliance.py` covers
   the routing (locked `pdftext.fetch_pdf`, the drivers' direct `net.open_url`, and the sitecustomize hook under the
   Makefile and Docker `PYTHONPATH`) and checks that every disallowed evaluation document has a mapping.
3. **Local copies deleted** (`python -m gegenprobe.compliance.mirror purge --apply` → `results/compliance/purged.json`).
   The rule: delete every local copy of a disallowed download unless OPD's copy is byte-identical. Two files met it:
   `spikes/recovery/data/audit_docs/838680.txt` and `839528.txt`, text extracted from two Word answers. On 10 Oct, the
   adapters' three files and their caches were deleted (the earlier entry). All other copies are byte-identical to OPD's
   public copies and stay.
4. **The `r100.19.doc` example is withdrawn.** It came from the atto page and an attachment header on disallowed paths.
   OPD's records hold the answer to interrogazione 100.19 only as a PDF without text (doc 375518) and hold no Word copy,
   so the example cannot be re-sourced. `census/source_formats.py` now reads OPD's records only (no network), the
   results file records the withdrawal, and the claim `r4c.ti_word_file` is removed.
5. **The adapters' own check.** Since commit `6a3ba3c`, `repair/adapters/robots.py` reads robots.txt again before every
   adapter request with the same matcher. The Ticino Word/PDF route stays off.

### What remains

- **Labels and results stay in the evaluation.** The labels and results derived from these documents remain, and so do
  the committed URLs, which name the parliament's original. 126 of the 130 evaluation documents are byte-identical to
  OPD's public copy, so a re-derivation from OPD gives the same text. The other 4 (P5 dev questions) are in WORK only as
  OPD's bytes.
- **The requests themselves cannot be undone.** That covers the local downloads (9-10 Oct), the CI re-downloads from
  GitHub runners, and the spike's downloads (8 Oct). A draft notice to the Ticino operator is in WORK
  (`compliance/notice_draft.md`); whether and how to send it is the lead's decision.
- **Hosts whose robots.txt cannot be read from our network today** cannot be re-judged. They are listed in the audit
  under `not_recheckable`.

### Re-check

```
python -m gegenprobe.compliance.audit --offline      # re-judge with the stored robots.txt copies (no network)
python -m gegenprobe.compliance.audit --refresh      # read every host's robots.txt again (one request per host)
python -m gegenprobe.compliance.mirror match         # re-compare OPD copies with recorded hashes and local copies
pytest tests/test_compliance.py tests/test_robots9309.py
```

**Lesson.** A standard-library parser does not necessarily implement the standard. Also: a URL taken from an aggregator's
records belongs to the publisher, so ask the aggregator's own copy first.
