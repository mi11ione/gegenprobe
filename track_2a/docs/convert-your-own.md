# Convert your own parliamentary PDFs

`python -m gegenprobe convert` reads a parliamentary PDF (born-digital or scanned) and returns the government's
**answer date** and its **recommendation** to parliament, each with the page and character span it was read from and
the rule that decided, or a typed null that says why there is no value. The default mode uses no model and sends nothing
anywhere except the request for the PDF itself.

## Install

Locally (Python 3.11, poppler and tesseract with `deu`, `fra`, `ita` installed), from the hash-pinned lock, so you get
exactly the versions that were tested (`requirements.txt` only lists the top-level names):

```bash
cd track_2a
python3.11 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements.lock
export PYTHONPATH=src:.
```

`PYTHONPATH=src` also loads `src/sitecustomize.py`, which installs the RFC 9309 robots.txt matcher before anything is
fetched. If you would rather not set `PYTHONPATH`, install the checkout in editable mode:
`.venv/bin/pip install --no-deps -e .`. That puts `gegenprobe-robots9309.pth` into the venv, and it does the same at
every start. Use the editable install: the package reads its data from the checkout. Either way, fetching is fail-closed:
if the matcher is not active, no request is made, and every URL ends as a `robots_matcher_inactive` failure row.
`.venv/bin/python -m pytest -q` runs the tests from `track_2a` without `PYTHONPATH` (`tests/conftest.py` sets it up).

Or with the Docker image that `make run` builds (everything included; it runs as an unprivileged user, so pass your own
uid when it writes into a mounted directory):

```bash
docker run --rm gegenprobe:latest python -m gegenprobe convert <url>
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" gegenprobe:latest \
  python -m gegenprobe convert --batch /work/inputs.tsv --out /work/out.jsonl
```

Untrusted input is bounded: a PDF above `GP_MAX_PDF_MB` (default 50) is refused before it is read, and every
pdftotext / pdftoppm / tesseract call has a timeout (`GP_SUBPROCESS_TIMEOUT`, default 300 s); both end as a typed failure
row (`too_large`, `text_timeout`), not a hung batch. Requests carry the User-Agent `GP_USER_AGENT` (set your own).

**Where files go.** Fetched PDFs and extracted texts are cached under `GP_WORK`. If `GP_WORK` is unset, the cache is
the repository's own `.work/` directory (`track_2a/.work/pdf/<sha256>.pdf`, `track_2a/.work/text/<sha256>.<extractor>.json`),
also when you run the tool from somewhere else. Set `GP_WORK=/path/to/cache` to keep it elsewhere. `--verbose` (or
`--explain`) prints the cache path in use. Local PDFs are copied into the cache too, keyed by their sha256.

## One document

```bash
python -m gegenprobe convert https://ogd.parl.apps.be.ch/pdf-upload/0778ef860e7d4e5c8ab89d1fe2922a42-332.pdf \
    --opd-doc-id 404590 --body BE --affair-number 2024.RRGR.91
python -m gegenprobe convert ./answer.pdf --lang fr --affair-type Motion
```

The command prints one JSON row and exits 0; if the document cannot be fetched or read it prints a failure row, a one-line
reason on stderr, and exits 2. Fetching is polite: one fixed User-Agent, at least 1.2 s between requests to the same host,
robots.txt honoured, and `--timeout` / `--tries` (default 60 s, 2 tries). robots.txt follows RFC 9309: a path the host's
rules disallow is never fetched (`robots_disallowed`). A robots.txt that answers a 4xx (403, 404, …) means "no
restrictions". One that cannot be read (5xx, 429, DNS, timeout) blocks the host for the run (`robots_unreachable`,
fail-closed).

Always pass `--body` (the OPD body key). A parliament outside `data/convert/rules_coverage.json` triggers a warning on
stderr, and the row is marked `needs_review` (see "Parliaments without rules").

**`--affair-type`** accepts, case-insensitively: the vocabulary keys of `data/schema/affair_types.json` (`motion`,
`postulate`, `interpellation`, `question`, `question_time`, `parliamentary_initiative`, `cantonal_initiative`,
`popular_initiative`, `government_affair`, `petition`, `consultation`, `election`, `amendment`, `naturalisation`,
`report`, `information_document`, `approval_decision`, `budget`, `miscellaneous`, `unknown`), their German, French,
Italian and English labels (`Interpellanza`, `Anfrage`, `Written question`, `Heure des questions`, …), OPD's harmonised
English names (`Interpellation`, `Question`, `Question time`, `Government affairs`, …) and a few common OPD type names
(`Question écrite`, `Schriftliche Anfrage`, `Kleine Anfrage`, `Einfache Anfrage`, `Dringliche Interpellation`,
`Fragestunde. Frage`, `Anzug`, `Vorlage`). Every value is normalised to OPD's harmonised name before the rules see it, so
`--affair-type "Question écrite"` gives recommendation `not_applicable`, like `Question`. Anything else is an error
(exit 2, with the list), never silently ignored; in a batch the error names the line.

## Many documents

```bash
python -m gegenprobe convert --batch inputs.tsv --out results.jsonl
```

`inputs.tsv` (or `.csv`) needs a header with a `url`, `path` or `source` column; optional columns `opd_doc_id`, `body`,
`affair_number`, `affair_type` (checked and normalised as above), `lang`, `doc_category` (OPD's document category; the
docs-export column names `category_harmonized` / `category` work too) are passed through. A `.txt` file with one URL or path per line also works. Each
input gives one JSONL line, failures included, and a summary goes to stderr. Run the same command again to resume: inputs
already in `results.jsonl` are skipped (keyed by `opd_doc_id` when given, else by URL/path); add `--retry-failed` to try
the failed ones again. Every row records the `options` it was made with (sha256 of the `--anchors` file, `--mode`, the
affair type and the other input columns, `--queue-nulls`, `--anchors-review`, `--explain`, and in review mode the build
and θ) and their `hash`. An input is skipped only when its last row has the same hash; when you change the anchors file
or an option, the summary says `re-run (options changed) N` and the new rows are appended. The last row per input wins:
`--queue` reads only the last one. Rows written before options were recorded are skipped and counted as
`skipped (older row, options not recorded)`; use a fresh `--out` to redo them.

Exit codes: `0` when every input converted, `2` when at least one input became a failure row (so a CI job or a cron
wrapper can notice), unless `--allow-failures` is given. `--queue review.jsonl` additionally writes only the rows that
need review: Apertus suggestions first, strongest band first, then the flagged rows (see "Review aids" below). A body
outside `rules_coverage.json` is warned about once per batch on stderr. `--anchors` and `--explain` work in batches too.

**`--queue-nulls`** (single document or batch): by default a rules-only null answer date is an unattended typed null and
does not reach the queue. With `--queue-nulls`, a null answer date on a document that is an answer is flagged
`needs_review` (reason "rules-only null on an answer document …"), so `--queue` picks it up with its `candidates` (the
printed dates, most likely first). A document counts as an answer when the converter's `doc_role` is `answer`, or when
OPD's category says so: `--doc-category` / the `doc_category` column is `response_text` (OPD's `category_harmonized`) or
a label the census counts as an answer document (`Réponse`, `Antwort …`, `Risposta …`, …; `census/defs.py` `ANS_DOC`).
Example: an answer letter that starts "Collombey-Muraz, le 15 juillet 2019" has no answer heading, so `doc_role` is
`other` and the rules leave the date null; with `--queue-nulls --doc-category response_text` it goes to review with
2019-07-15 first in `candidates`. For a parliament without rules (`no_rules_for_body`) every null is flagged already, so
`--queue-nulls` changes nothing there.

## Review aids (what a reviewer sees next to every value)

- **`candidates`** on the answer date: every distinct date printed in the document, with page, character span, 160
  characters of context, how often it occurs, whether it lies inside Apertus' reading window, and which one was
  chosen. In review mode each candidate also carries Apertus' probability `share` (and the field has a `null_share`).
  A reviewer can pick the right date from this list without opening the PDF.
- **`rule_precision`** on every rule-decided value: how often that rule was right on the pre-registered held-out
  documents, e.g. `ti_header_date_head` 13/13, `place_date_head` 10/11, `rrb_vom` 3/5, `datum_rr_sitzung` 0/2
  (`results/convert/rule_precision.json`; small counts, read them as a warning light, not a guarantee).
- **`band`** on every review suggestion, from Apertus' null margin: `strong` (margin ≤ −5: the model clearly preferred
  a printed date) or `weak` (−5 < margin ≤ θ: it leaned toward null but stayed under θ). Measured on the two
  pre-registered tests (post-hoc): strong suggestions were correct 26/33, weak ones 3/11
  (`results/convert/band_precision.json`). Review strong ones first; treat weak ones as "probably no answer date".
- **`multiple_recommendations`** on the recommendation: true when the document contains more than one recommendation
  phrase with different labels (e.g. reject point 1, adopt points 2–3); then read the context before accepting.
- **`opd_text_span`** (with `--opd-text FILE`): the same value as character offsets into OpenParlData's stored text of
  the document (the `text` field of the docs export), so the value can be highlighted in OPD's own workbench. The
  anchor context is matched first, then the quote inside it; a match must be unique (`ambiguous` / `not_found`
  otherwise). On 30 held-out documents of Collombey-Muraz, Lausanne and Lugano every converter value aligned uniquely
  (7/7; `results/convert/opdtext_alignment.json`).
- **`qualifier`** on the recommendation: a recommendation rule matched "accept" or "reject", but a qualifier follows
  in the same sentence. An unambiguous partial qualifier (`partiellement`, `en partie`, `teilweise`,
  `teilweise erheblich`, `partiell`, `parzialmente`, `in parte`) turns the value into `partial`. Example (Fribourg):
  "invite donc le Grand Conseil à accepter partiellement la motion" gives `partial`, rule
  `rec_accept+qualifier_partial`. Other qualifiers keep the value and set `needs_review` with a reason:
  `im Sinne der Erwägungen`, `dans le sens des considérants`, `mit geändertem Wortlaut`, `Nichteintreten`,
  `sous réserve`, `unter Vorbehalt`. In both cases the quote span is extended to include the qualifier.
- **`suggested_by_heading_proximity`** on the first answer-date candidate. Sometimes the rules find an answer heading but
  no anchored date (`evidence: heading_without_date`), while a date is printed right after the heading, e.g.
  "Antwort der Regierung vom 1. September 2026" or "Réponse du Conseil d'Etat : 06.05.2025". That date is then moved
  to the front of `candidates`, with its span, and the row is marked `needs_review`. The field itself stays null: no
  frozen rule vouches for the layout. Headings that name the instrument ("Réponse à l'interpellation du …") are
  skipped, because the date that follows is the instrument's own.
- **`suggested_by_letter_line`** on the first answer-date candidate. Many answers are letters to the parliament with
  no answer heading: an address block ("An den Kantonsrat", "An die Mitglieder des Grossen Rates", "Au Grand Conseil",
  "Al Gran Consiglio", …) and right under it the place-date line ("Schaffhausen, 21. Dezember 2021"). The frozen rules
  only read such a line on a document with an answer heading, so the field stays null. That date is moved to the front of
  `candidates` with its span and the addressee (`address`), and the row is marked `needs_review`; the field is never
  filled, in rules_only or review mode. Addressees that are the executive in some places (`Gemeinderat`, `Stadtrat`,
  `Conseil communal`, `Conseil municipal`) and "An den Regierungsrat" (a member's own text, dated on submission) are not
  used. On the 313 committed gold documents (P1 dev and held-out, P2; 194 of them without an answer heading) the hint
  never fires (`results/convert/letter_hint_check.json`, post hoc); it was written for the Schaffhausen layout (three of
  three answer letters in a user test, round 5).
- **`needs_review` and `review_reasons`**: the row needs a person when it carries an Apertus suggestion, when a field has
  `needs_review: true` (each with its `review_reason`), or when the parliament has no rules. `review_reasons` lists
  one `{field, reason}` per flag; the CLI also prints them on stderr. `--queue` collects these rows.
- **Which parliaments have rules:** `data/convert/rules_coverage.json` lists the parliaments whose layouts the rules
  were written on. Every row says `rules_coverage.status`: `covered`, `not_covered`, `user_anchors` (not covered, but
  your `--anchors` file has entries for it) or `unknown` (no `--body` given).

## Parliaments without rules

The frozen rules were written on the parliaments in `data/convert/rules_coverage.json` (BE, BS, GE, JU, LU, TI, VS, ZH
and seven communes). For any other `--body`:

- the CLI prints a warning on stderr;
- a field the rules left open gets `null_reason: no_rules_for_body` instead of `present_unanchored`. "No rule knows this
  layout" is not the same statement as "the document is ambiguous";
- a value a frozen rule did find is kept, but flagged `needs_review` (the rule was never measured on that layout);
- the row is `needs_review: true`, so `--queue` picks it up.

Three ways forward: read the `candidates` (the right date is usually among them, with context), run `--mode review`, or
write your own anchors.

## Your own anchors (`--anchors FILE`)

```bash
python -m gegenprobe convert answer.pdf --body SG --anchors docs/examples/anchors_SG.json
```

An anchor file holds regular expressions per OPD body key (JSON; `"*"` applies to every body). They are tried only after
the frozen rules returned null: they can fill a gap, but they never override a rule. `docs/examples/anchors_SG.json`
(Kantonsrat St. Gallen) shows the format:

```json
{"bodies": {"SG": {
  "answer_date": [
    {"id": "sg_antwort_der_regierung_vom", "pattern": "^\\s*Antwort der Regierung vom {DATE}"},
    {"id": "sg_antrag_der_regierung_vom", "pattern": "^\\s*Antrag der Regierung vom {DATE}"}],
  "recommendation": [
    {"id": "sg_antrag_nichteintreten", "label": "reject",
     "pattern": "Antrag der Regierung vom {DATE}\\s+(?P<phrase>Nichteintreten)\\b"}]}}}
```

- `{DATE}` expands to the rules' own date expression (numeric and DE/FR/IT month names), with a named group `date`. You
  can also write your own `(?P<date>…)`.
- Patterns are case-insensitive and multi-line. A literal space matches any whitespace, line breaks included, as in the
  frozen rules: every space in your pattern becomes `\s+`.
- **Whitespace inside a look-behind.** Because a space becomes `\s+`, a look-behind with a space in it is no longer
  fixed-width and Python refuses it: `(?<!nicht )` fails with "look-behind requires fixed-width pattern" (the message names
  the entry, e.g. `bodies.SH.recommendation[1]`). Write the space as `\s` inside a look-behind: `(?<!nicht\s)`. The
  same holds for `(?<=…)`.
- An answer-date anchor may set `"role": "decision"` or `"dispatch"`; without one the role is `answered`.
- A recommendation anchor needs a `label` (`accept`, `reject`, `convert`, `partial`, `accept_and_write_off`).
  `(?P<phrase>…)` marks the span to cite; without it, the whole match is cited.

A value found this way carries `route: user_anchor`, `rule_id: user_anchor:<id>`, the page, the span and the quote, in
the flat row and in the schema record. It has `needs_review: false` only when the anchor has a date group that parses.
An anchor without a date group takes the first date within 80 characters after it, and that value is flagged. If
recommendation anchors with different labels all match, the value is flagged too. A malformed file (bad JSON, bad regex,
unknown label) exits 2 with the problem named. The anchors are yours: we have not measured them. Until you have,
`--anchors-review` keeps every value from your anchors `needs_review: true` (reason "value from your anchor <id>
(--anchors-review …)"), so `--queue` collects them for a spot check; drop the flag once a sample has confirmed them.

## `--explain`

```bash
python -m gegenprobe convert answer.pdf --body SG --anchors docs/examples/anchors_SG.json --explain
```

`--explain` prints the cache path, the body's rule coverage, and, per field, every frozen rule in the order the
converter tries them, each with why it did not decide ("no match", "2 match(es), 2 on footer/edit lines", "no executive
answer heading in the first 2500 characters, so the dispatch rules … were not tried"). These are followed by the
qualifier check, your anchors and the heading-proximity check. The trace replays the frozen rules read-only: on 3,398
cached documents the step it marks `fired` was the rule the converter returned every time. In a batch, each row
carries the same trace under `explain`.

## Where to get document URLs

OpenParlData publishes every document with its source URL in the `docs_*` exports at
<https://files.openparldata.ch/exports/> (one `.ndjson.gz` file per body; fields `id`, `url`, `affair_id`, `body_key`,
`name`). Take `id` as `opd_doc_id` and `url` as the source. The census table vendored in this repository
(`data/census/docs.tsv.gz`) holds document metadata but no URLs.

## What a row contains

```json
{"status": "ok",
 "input": {"source": "https://ogd.parl.apps.be.ch/pdf-upload/0778ef860e7d4e5c8ab89d1fe2922a42-332.pdf",
           "opd_doc_id": "404590", "body": "BE", "affair_number": "2024.RRGR.91"},
 "mode": "rules_only", "language": "de",
 "doc_role": {"value": "answer", "basis": "executive answer/decision date found by rule be_rrb_split"},
 "fields": {
   "answer_date": {"value": "2024-08-28", "route": "rule", "role": "answer_decided", "rule_id": "be_rrb_split",
                   "decision_number": "879/2024", "page": 1, "char_start": 437, "char_end": 452,
                   "quote": "28. August 2024",
                   "context": "…Dringlichkeit gewährt: Nein RRB-Nr.: Direktion: Klassifizierung: 879/2024 vom 28. August 2024"},
   "recommendation": {"value": null, "route": "rule", "null_reason": "present_unanchored", "evidence": "no_anchor"}},
 "needs_review": false, "review_reasons": [], "review_suggestion": null,
 "rules_coverage": {"body": "BE", "status": "covered", "note": "the frozen rules were written on documents of this parliament"},
 "record": { "…": "the full schema v0.1 DocExtraction" }}
```

(Actual output of the first command above, `context` shortened; the Bern answer form prints its labels in one column
and the values in the next, so the anchor "RRB-Nr.:" sits a few labels before "879/2024 vom 28. August 2024".)

| key | meaning |
|---|---|
| `fields.<name>.value` | the value, or `null` (then `null_reason` and `evidence` say why) |
| `route` | `rule` (frozen deterministic rule), `ocr+rule` (the same, on OCR text of a scan), `user_anchor` (your `--anchors`), `apertus` / `ocr+apertus` (only in a review suggestion) |
| `role` | for dates: `answer_decided` (the executive decided its answer that day: RRB, ACE, RG n., séance du …) or `answer_dispatched` (letter / place-date line) |
| `rule_id` | which rule decided; `docs/converter.md` lists them. `rec_accept+qualifier_partial`: the frozen rule plus a partial qualifier; `user_anchor:<id>`: your anchor |
| `needs_review`, `review_reason` | on a field: a person must look at it, and why (qualified recommendation, unmeasured layout, date next to a heading, anchor without date group) |
| `decision_number` | the executive's decision number printed with the date, when the rule captured it |
| `page`, `char_start`, `char_end`, `quote` | where the value is printed: `quote` is exactly the text at that span of the extracted page |
| `context` | the text around it (the anchor phrase through the end of the line, ≤ 200 characters) so a reviewer sees *why* |
| `doc_role` | `answer`, `question` (a member's text) or `other`, with the evidence used (a rule, not a model) |
| `record` | the validated schema v0.1 object (`results/schema/doc_extraction.schema.json`); the same spans, plus extractor and sha256 |

Spans index the text this tool extracted (pdftotext for PDFs with a text layer, tesseract `deu+fra+ita` for scans; the
extractor and its version are in `record.doc.extractor`). They do not index OpenParlData's own stored text.

### Why a field is null

| `null_reason` | in plain words |
|---|---|
| `present_unanchored` | the document prints dates (or recommendation-like words), but none sits next to an anchor that marks it as the government's answer (or recommendation). The rules leave it open rather than guess; review mode may suggest one |
| `no_rules_for_body` | the same situation, but on a parliament the rules were never written for (`--body` not in `rules_coverage.json`): the layout is unknown to the rules, which says nothing about the document. The row needs review |
| `not_in_document` | the document was read and does not contain the value, e.g. a member's text with an empty "RRB-Nr.: … vom" answer template. Says nothing about other documents |
| `not_applicable` | the field does not apply, e.g. no recommendation on an interpellation or question |
| `oral` | the document says the answer was given orally |
| `image_only` | a scan without a text layer and OCR was unavailable |
| `text_failed` | the PDF has no usable text |
| `unlinked`, `not_in_corpus` | affair-level reasons set by the census and repair lists, not by single-document conversion |

### Failure rows

`{"status": <kind>, "reason": "...", "input": {...}}` with kind `robots_disallowed` (the host's robots.txt disallows the
path for our User-Agent; we never fetch it), `robots_unreachable` (the host's robots.txt answered 5xx/429 or could not be
reached, so nothing is fetched from that host in this run; RFC 9309 §2.3.1.4), `robots_matcher_inactive` (the RFC 9309
matcher is not active in this Python process, so nothing is fetched; see Install), `http_error`, `timeout`, `network_error`,
`not_a_pdf` (the URL returns an HTML page: a document viewer or a dead-link landing page), `sha_mismatch`,
`file_not_found`, `text_failed`, `too_large` or `text_timeout`.

## Review mode (optional, uses Apertus)

```bash
python -m gegenprobe convert answer.pdf --mode review --backend gguf
```

For what the rules leave open, the Apertus closed-set pointer chooses among the dates printed in the document, or null.
Its choice is never written into the field: it appears as `review_suggestion` (value, span, context, margin, θ, build)
with `needs_review: true`, for a person to accept or reject. It needs a threshold θ fitted for the exact build that runs
(θ does not transfer across builds, quantisations or prompts); the command lists the fitted builds when none matches.
It also checks, on every live response, that the server still serves the build θ was fitted on (the θ file's
`served_fingerprints`; for the GGUF build, the pinned weights' sha256). The first response from another build stops the
run with exit code 3 and names the fingerprint; `--allow-build-mismatch` continues and marks each suggestion
`build_mismatch`. Refitting θ: `docs/runbook.md`, "Review mode in operation".

- `--backend gguf`: Apertus v1.5 8B (GGUF Q4_K_M, sha256-pinned, 5.1 GB download) in-process on CPU. Nothing leaves the
  machine. Needs `data/convert/theta/gguf_apertus-v1.5-8b-text-q4_k_m.json`.
- `--backend openai`: any vLLM-style endpoint serving Apertus (`LLM_BASE_URL`, `LLM_NAME`, `LLM_API_KEY`); the document text
  is sent to that endpoint.
- The Public AI build (`publicai:swiss-ai/apertus-v1.5-8b`, which serves the 70B weights) was used for the evaluation only.
  It is not a runtime target: requests may be routed outside Switzerland.

## Known limits

- **Fetching is often harder than reading.** Some hosts forbid automated access in robots.txt (e.g. `ag.ch/grossrat`), some
  OpenParlData URLs now redirect to listing pages, and some parliaments serve an HTML viewer instead of the PDF. These come
  back as typed failure rows; download the PDF yourself and pass the path.
- Two fields are extracted from text (answer date, government recommendation). Type, submitters, dates of other steps and
  procedural state come from OpenParlData's metadata (`docs/census.md`), not from the PDF.
- The rules were written for the anchors of the parliaments in `docs/converter.md`; on other layouts they leave the field
  open (`no_rules_for_body` when you pass `--body`) rather than guess. Add your own anchors with `--anchors`.
