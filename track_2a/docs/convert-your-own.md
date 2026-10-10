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

## One document

```bash
python -m gegenprobe convert https://ogd.parl.apps.be.ch/pdf-upload/0778ef860e7d4e5c8ab89d1fe2922a42-332.pdf \
    --opd-doc-id 404590 --body BE --affair-number 2024.RRGR.91
python -m gegenprobe convert ./answer.pdf --lang fr --affair-type Motion
```

The command prints one JSON row and exits 0; if the document cannot be fetched or read it prints a failure row, a one-line
reason on stderr, and exits 2. Fetching is polite: one fixed User-Agent, at least 1.2 s between requests to the same host,
robots.txt honoured (a host that forbids the path is never fetched), and `--timeout` / `--tries` (default 60 s, 2 tries).

## Many documents

```bash
python -m gegenprobe convert --batch inputs.tsv --out results.jsonl
```

`inputs.tsv` (or `.csv`) needs a header with a `url`, `path` or `source` column; optional columns `opd_doc_id`, `body`,
`affair_number`, `affair_type`, `lang` are passed through. A `.txt` file with one URL or path per line also works. Each
input gives one JSONL line, failures included, and a summary goes to stderr. Run the same command again to resume: inputs
already in `results.jsonl` are skipped (keyed by `opd_doc_id` when given, else by URL/path); add `--retry-failed` to try
the failed ones again.

Exit codes: `0` when every input converted, `2` when at least one input became a failure row (so a CI job or a cron
wrapper can notice), unless `--allow-failures` is given. `--queue review.jsonl` additionally writes only the rows that
carry a review suggestion, strongest band first (see "Review aids" below).

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
- **Which parliaments have rules:** `data/convert/rules_coverage.json` lists the parliaments whose layouts the rules
  were written on. Route documents of any other parliament to review mode.

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
 "needs_review": false, "review_suggestion": null,
 "record": { "…": "the full schema v0.1 DocExtraction" }}
```

(Actual output of the first command above, `context` shortened; the Bern answer form prints its labels in one column
and the values in the next, so the anchor "RRB-Nr.:" sits a few labels before "879/2024 vom 28. August 2024".)

| key | meaning |
|---|---|
| `fields.<name>.value` | the value, or `null` (then `null_reason` and `evidence` say why) |
| `route` | `rule` (frozen deterministic rule), `ocr+rule` (the same, on OCR text of a scan), `apertus` / `ocr+apertus` (only in a review suggestion) |
| `role` | for dates: `answer_decided` (the executive decided its answer that day: RRB, ACE, RG n., séance du …) or `answer_dispatched` (letter / place-date line) |
| `rule_id` | which rule decided; `docs/converter.md` lists them |
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
| `not_in_document` | the document was read and does not contain the value, e.g. a member's text with an empty "RRB-Nr.: … vom" answer template. Says nothing about other documents |
| `not_applicable` | the field does not apply, e.g. no recommendation on an interpellation or question |
| `oral` | the document says the answer was given orally |
| `image_only` | a scan without a text layer and OCR was unavailable |
| `text_failed` | the PDF has no usable text |
| `unlinked`, `not_in_corpus` | affair-level reasons set by the census and repair lists, not by single-document conversion |

### Failure rows

`{"status": <kind>, "reason": "...", "input": {...}}` with kind `robots_disallowed` (the host's robots.txt forbids the
path; we never fetch it), `http_error`, `timeout`, `network_error`, `not_a_pdf` (the URL returns an HTML page: a document
viewer or a dead-link landing page), `sha_mismatch`, `file_not_found` or `text_failed`.

## Review mode (optional, uses Apertus)

```bash
python -m gegenprobe convert answer.pdf --mode review --backend gguf
```

For what the rules leave open, the Apertus closed-set pointer chooses among the dates printed in the document, or null.
Its choice is never written into the field: it appears as `review_suggestion` (value, span, context, margin, θ, build)
with `needs_review: true`, for a person to accept or reject. It needs a threshold θ fitted for the exact build that runs
(θ does not transfer across builds, quantisations or prompts); the command lists the fitted builds when none matches.

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
  open (`present_unanchored`) rather than guess.
