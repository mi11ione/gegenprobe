# Census and schema-feasibility matrix

Everything here is computed by `src/gegenprobe/census/` from the OpenParlData bulk exports (files.openparldata.ch/exports,
snapshot of 6–8 Oct 2026; contributors/meetings/external_links 9 Oct 2026; exact files and dates in
`data/census/meta.json`). No model is involved. `make census` rebuilds everything; `python -m gegenprobe.census.replay`
recomputes it from the committed compact tables in `data/census/` and fails on any difference.

## 0. Pipeline

| step | module | input | output |
|---|---|---|---|
| scan | `census.scan` | 97 `docs_*` + 19 `texts_*` exports, streamed (≈6 GB, never stored) | per-row metadata: text status, length, answer-marker flags (no text) |
| extract | `census.extract` | single-file exports + scan output + BE canton OGD | `data/census/*.tsv.gz` (≈26 MB) |
| funnel | `census.funnel` | `data/census` | `results/census/{funnel,summary}.json` |
| matrix | `census.matrix` | `data/census` | `results/census/matrix.{csv,json}`, `fields.json` |
| question | `census.question` | `data/census` | `results/census/question.json` |
| findings | `census.findings` | `data/census` (+ cited spike files) | `results/census/findings.json` |
| replay | `census.replay` | `data/census` | asserts equality with `results/census/*` |

What the compact tables keep and drop (`census/extract.py` docstring): raw event titles, document names and categories and
`texts` types are kept so the frozen patterns in `census/defs.py` are re-applied at replay. Reduced: document full text
(status, length, three answer-marker flags only — no full text is ever committed), contributors (distinct-person/group counts
per affair × harmonised role; no names), `texts` (type plus longest non-placeholder language version), and documents outside
the answer census (counts per affair × status × usable × language × category). The trade-off: a change to the *text*
patterns (`defs.TEXT_FLAGS`, `defs.text_status`) needs a re-scan of the exports; every other pattern replays offline.

## 1. Answer funnel (definitions frozen, ported from the 8 Oct spike)

In scope: affairs whose OPD harmonised type is Interpellation, Motion, Postulate, Question or Question time.

- **`ev_answer`** (a written answer exists): an event harmonised as *Beantwortet*/*Beantwortung* (ids 6, 76) or whose title
  matches an answer pattern (Antwort / Stellungnahme RR / "Der Bundesrat beantragt" / Réponse / Risposta …); referrals
  ("zur Stellungnahme", "Überweisung") excluded. Oral answer events (mündlich, Fragestunde, "Réponse de M. …") count as
  `ev_oral_only` when no written-answer event exists.
- **`doc_answer`**: a document attached to the affair whose name/category matches an answer pattern or whose text carries an
  answer heading; **`doc_answer_txt`**: and its text is usable (not null/blank/`[extraction_failed]`/placeholder, ≥200 chars).
- **`text_answer`**: an answer-type row (Antwort, Réponse, Risposta, Stellungnahme) in the `texts` export with ≥50 chars.
- **gap** = `ev_answer` ∧ no answer text; **gap′** = gap after re-attaching answer documents filed under an agenda item
  (`agendas.item_affair_id`).

## 2. Answer-link status (new schema field `answer_link_status`)

Assigned to every in-scope affair, first match wins:

| status | definition | repair route |
|---|---|---|
| `attached` | usable answer text on the affair in OPD (document or `texts`) | none |
| `agenda` | usable answer document filed under an agenda item that points to the affair | relink via `agendas.item_affair_id` |
| — the rest only where a written answer is expected (`ev_answer`) — | | |
| `parentless` | BE: the canton OGD lists an answer whose canton document uid sits in OPD with no affair, agenda or meeting | relink by canton uid |
| `oral` | VS `_ANT` document whose OPD text is the 80–95-char stub "cf. réponse orale du Conseil d'Etat"; or only oral answer events | retype; no document expected |
| `image_only` | an answer document is attached but OPD holds no usable text (a re-fetch of 30 sampled documents found 15 image-only scans, 13 VS oral-answer pointers with a text layer and 2 others, `results/repair/ocr_probe.json`) | OCR deu+fra+ita |
| `absent` | no answer document in OPD | body-specific source adapter (BE: canton fetch) |
| `not_applicable` | no answer event and no answer text | — |

## 3. Feasibility matrix: criteria (written before the table was computed; criteria and matrix were committed together)

**Unit.** Field × body. A body is *eligible* for a field when it has at least 20 applicable affairs (below that the cell is
`n/a`, shown but not used for tiers). The 89 bodies are those with in-scope affairs.

**Applicable affairs per field.** All affairs of the body for type, submitter, submission date, procedural state, related
affairs and usable documents; in-scope types for addressed body; in-scope affairs with `ev_answer` for Q/A pairing, answer
date, dispatch date and answer-link status; Motion + Postulate (the types parliament decides on) for decision date, decision
outcome and government recommendation; all documents for language.

**Per cell** (affairs applicable to the field in that body):
- `meta` = share whose value is present in OPD metadata (definition per field in `census/matrix.py:FIELDS`);
- `doc` = share with at least one document with usable text (≥200 chars) — the population a PDF converter can work on;
- `status` = `metadata` if meta ≥ 0.90; `mixed` if 0.10 ≤ meta < 0.90; `pdf` if meta < 0.10 and doc ≥ 0.50;
  `no_source` if meta < 0.10 and doc < 0.50;
- `route` = metadata | metadata+<extraction route> | <extraction route> | not representable (no source), where the
  extraction route is fixed per field: `rule` (anchored dates, affair numbers that exist in OPD, addressed-body headings) or
  `apertus` (closed-set pointer: government-recommendation enum, unanchored dates, OCR'd text), always with `null` allowed;
- `accuracy` = measured extraction accuracy for the route in this cell — left empty; the held-out evaluation measured the answer date per language × level cell, not per body (`results/census/matrix_accuracy.json`).

**Per-field tier**, applied by code over eligible bodies:
1. **feasible** — the field is `metadata` in ≥ 80% of eligible bodies: a common schema can carry it today.
2. **fundamentally different** — the field is `no_source` in ≥ 20% of eligible bodies: for a material share of parliaments
   the information does not exist in a comparable written form (oral answers, unscanned or unpublished documents, concepts
   the body does not have), so a common schema can only carry a typed null there.
3. **partial** — otherwise: the concept is shared, but availability is uneven; the schema is feasible with a converter
   (PDF route) and per-body vocabulary mapping, at the accuracy the evaluation measures.

Vocabulary is reported next to availability (harmonised-vocabulary coverage per body, number of raw labels) but does not
change the tier: a raw label without a harmonised mapping is a lookup-table problem, not a schema problem.

<!-- BEGIN GENERATED: census results -->

## 4. Results (generated by `python -m gegenprobe.census.doc`)

**Funnel.** 198,594 in-scope affairs in 86 bodies; 91,268 with a written-answer event; **16,749 (18.4%) without answer text**; 16,157 after the in-corpus agenda join (592 re-joined). 2024–25: 1,855 (14.3%).

**Reproduction.** The ported funnel reproduces the 8 Oct spike cell for cell: 5,444 body × type × year cells, 0 differing values, document-status table identical: True.

**Answer-link status** (all in-scope affairs): `absent` 11,330, `agenda` 932, `attached` 116,466, `image_only` 1,352, `not_applicable` 61,013, `oral` 5,042, `parentless` 2,459. Of gap′: BE 2,510 (canton lists an answer for 2,508; 2,459 relinkable parentless documents), CHE 75, other bodies with an answer document but no text 2,366 (of which VS oral stubs 1,016 by the length proxy; 1,008 by the exact text rule that the repair list uses, `results/census/vs_reconcile.json`), other bodies with no answer document 11,206.

### Field-tier table

Status counts are over eligible bodies (≥ 20 applicable affairs). `meta`/`doc` are pooled over applicable affairs.

| field | tier | bodies | metadata | mixed | pdf | no source | meta (pooled) | usable doc (pooled) | route if not in metadata |
|---|---|---|---|---|---|---|---|---|---|
| addressed body (department) | **partial** | 86 | 12 | 10 | 54 | 10 | 55.2% | 53.8% | rule |
| answer-link status (new) | **feasible** | 54 | 54 | 0 | 0 | 0 | 100.0% | 62.5% | census |
| co-signatories | **partial** | 86 | 0 | 2 | 72 | 12 | 12.0% | 53.8% | rule |
| date: answer | **feasible** | 54 | 53 | 1 | 0 | 0 | 99.6% | 62.5% | rule+apertus |
| date: decision | **partial** | 77 | 7 | 30 | 34 | 6 | 51.8% | 58.1% | rule |
| date: dispatch | **partial** | 54 | 0 | 0 | 47 | 7 | 0.0% | 62.5% | apertus |
| date: submission | **feasible** | 89 | 89 | 0 | 0 | 0 | 99.9% | 61.2% | rule |
| decision outcome | **partial** | 77 | 7 | 31 | 33 | 6 | 52.0% | 58.1% | rule |
| documents with usable text | **partial** | 89 | 41 | 42 | 0 | 6 | 61.2% | 61.2% | repair |
| government recommendation | **partial** | 77 | 3 | 8 | 56 | 10 | 34.2% | 58.1% | apertus |
| language (documents) | **partial** | 89 | 14 | 53 | 20 | 2 | 41.5% | 83.2% | rule |
| procedural history (harmonised events) | **feasible** | 89 | 78 | 9 | 1 | 1 | 69.8% | 61.2% | rule |
| procedural state (state field) | **partial** | 89 | 41 | 27 | 18 | 3 | 75.1% | 61.2% | rule |
| question/answer pairing | **partial** | 54 | 22 | 25 | 4 | 3 | 82.3% | 62.5% | repair |
| related affairs | **partial** | 89 | 0 | 0 | 76 | 13 | 0.0% | 61.2% | rule |
| submitter | **partial** | 89 | 23 | 61 | 5 | 0 | 75.0% | 61.2% | rule |
| type | **partial** | 89 | 61 | 24 | 2 | 2 | 82.9% | 61.2% | rule |

- *answer-link status (new)*: derived by this census for every affair (census/funnel.py); feasible by construction.
- *co-signatories*: lower bound: an affair without co-signers is indistinguishable from an unrecorded list.
- *date: answer*: population = affairs with a written-answer event, so the event date exists by construction; its accuracy is checked against the source only for BE (event date == RRB date 39/39, spikes/recovery).
- *date: dispatch*: no dispatch/Versand date anywhere in the exports.
- *decision outcome*: harmonised outcome event or frozen outcome-title rule; Motion+Postulate numbered/begun before 2024.
- *government recommendation*: government 'Antrag' event (harmonised ids 29-33 or frozen title rule, government actor only).
- *language (documents)*: share of documents with a language tag; affairs carry no language field; doc = documents with usable text.
- *related affairs*: no related-affair field in the exports; only cross-references inside documents.

**Verdict by the pre-declared rule:** 4 fields feasible, 13 partial, 0 fundamentally different. No field lacks a written source in ≥ 20% of parliaments; what varies is where the value lives (metadata in some bodies, only in PDFs in others) and the vocabulary.

### Where the concept itself differs (post hoc, descriptive; does not change tiers)

- Interpellation: 640 of 40,221 answered affairs have only an oral answer (1.6%).
- Motion: 42 of 23,921 answered affairs have only an oral answer (0.2%).
- Postulate: 250 of 20,528 answered affairs have only an oral answer (1.2%).
- Question: 1,196 of 38,824 answered affairs have only an oral answer (3.1%).
- Question time: 2,914 of 14,087 answered affairs have only an oral answer (20.7%).
- VS files 1,008 oral answers as an `_ANT` stub document, not as an oral event (exact text rule; the census length proxy flags 1,016: proxy precision 99.2% per document, recall 100.0%, `results/census/vs_reconcile.json`).
- In 7 of 54 bodies the 'answer' event date equals the submission date for ≥ 50% of affairs: the date exists in metadata but is not an answer date (Wallis 88.6%, Interlaken 53.8%, Kriens 66.2%, Liestal 100.0%, Dübendorf 59.3%, Appenzell Ausserrhoden 62.2%, Schaffhausen 99.7%).

Cited evidence (not recomputed; `data/census/cited_evidence.json`): the S3-BILANZ atom inventory over 12 bodies left 45.9% of atoms without a schema account; five gaps recur across bodies and languages: person roles; comparison amounts; dates and laws of other polities; dates of other affairs; entry-into-force and deadline dates. Estimating the *size* of the missing schema with Chao2 failed both pre-registered checks (no saturation, ≈57.4 new accounts per body): a well-evidenced negative.

### The cross-parliamentary question

Across 54 parliaments with ≥ 20 written-answer interventions, the answer text is in OPD for 82.3% (85.0% after the measured relinks); the median time from submission to the answer event is 68 days (Question time 5). Lowest answer-text shares: Interlaken 0.0%, Collombey-Muraz 0.0%, Münsingen 0.7%, Monthey 0.8%, Lugano 5.2%, Neuenburg 6.9%. Caveat: the answer date is the OPD event date; it equals the government decision (RRB) date for BE in 39/39 verified cases (spikes/recovery/be_recovery.json) and is unverified elsewhere (it may be a publication date). Submission = the earliest 'Eingereicht'-type event (harmonised ids 1/56/67), else `begin_date`; BE affairs whose begin_date is the 2024-10-28 import artefact and no submission event are excluded; durations < 0 or > 3,650 days are excluded and counted.

### Data-quality findings

| finding | value | verified |
|---|---|---|
| Federal (CHE) documents whose stored text is Fedlex's 'JavaScript required' page | 30,033 / 52,450 (57.3%) | recomputed |
| bodies.lang tags canton FR as 'DE' | 1 / 1 | recomputed |
| bodies.lang tags canton VS as 'DE' | 1 / 1 | recomputed |
| Documents without a language tag | 525,363 / 902,754 (58.2%) | recomputed |
| Bodies with a docs export but zero affairs | 8 | recomputed |
| Affair numbers that are dates | 5,528 / 325,691 | recomputed |
| BE affairs whose begin_date is > 1 year off the year in their number | 800 / 8,193; 557 on 2024-10-28 | recomputed |
| The docs `hash` field is not the PDF's sha256 (0/2 matched); `size` matches the bytes | 0 / 2 | cited |
| 2025.GRPARL.384: OPD begin_date vs the date printed in the PDF | {"opd_begin": "2025-06-18", "pdf": "19.06.2025"} | recomputed+cited |
| Affairs without a harmonised type | 55,767 / 325,691 (17.1%) | recomputed |
| Affairs with a harmonised procedural state | 278 / 325,691 (0.1%) | recomputed |
| The public persons export carries contact/birth fields | 6 / 60 | recomputed (field names only) |

## 5. Known limitations

- The answer patterns are hand-written regexes; their precision is checked only through the 40-affair gap audit (27/35 true gaps) and the BE canton join (spikes/recovery).
- `be_rrb_filled` (scan-time flag) expects the year first; the current BE format "RRB-Nr.: 879/2024" is not flagged. BE answers are still found by name/heading; the flag is kept frozen because changing it needs a re-scan.
- Year comes from the affair number where it starts with a year, else from `begin_date` (affected by the BE 2024-10-28 import date).
- Parentless counts do not check `news_id` (not kept by the scan).
- `co-signatories` is a lower bound (no co-signers vs. unrecorded is indistinguishable in metadata).
- The `accuracy` column stays empty: measured extraction accuracy exists only for the answer date, per language x level cell of the held-out gold set rather than per body (`results/census/matrix_accuracy.json`; no federal documents in the gold set). `pdf` cells say a converter *can* work there, not that it does.

<!-- END GENERATED: census results -->
