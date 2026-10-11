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
| answer times by date tier | `census.days_by_trust` | `results/census/interventions.tsv.gz` | `results/census/answer_days_by_trust.json` (not replayed; asserts the same 90,556 durations as `question.json`) |
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
- The gap counts what OPD holds, not what the parliaments publish. It is reported as **no answer text** (16,749 over all
  years) and includes 1,422 answers given **orally** in the sitting, for which no written text is expected: 1,016 Valais
  answers filed as an `_ANT` oral-answer stub document (§4) and 406 question-time answers (Graubünden's Fragestunde 367 of
  them) with no answer document. Both are typed `oral` (§2); typing changes the cause, not the gap count. When a sentence
  is about *missing* answers, use **written answers missing** = no answer text − oral (15,327 of 89,846 answered in writing,
  17.1%; 2024–25: 1,488 of 12,632, 11.8%); the site table, `site/parliaments.csv` (`*_written_missing`, `*_in_writing`) and
  its "safe to say" sentences do.
- Valais oral counts, one definition each: **1,017** typed `oral` in the table and the dataset = 1,016 stubs + 1
  question-time answer (affair 3.163); **1,016** = the stubs found by the census length proxy; **1,008** = the stubs the
  repair's exact text rule confirms, i.e. the `retype_oral` list OPD gets (8 documents where proxy and rule disagree,
  `results/census/vs_reconcile.json`).

## 2. Answer-link status (new schema field `answer_link_status`)

Assigned to every in-scope affair, first match wins:

| status | definition | repair route |
|---|---|---|
| `attached` | usable answer text on the affair in OPD (document or `texts`) | none |
| `agenda` | usable answer document filed under an agenda item that points to the affair | relink via `agendas.item_affair_id` |
| — the rest only where a written answer is expected (`ev_answer`) — | | |
| `parentless` | BE: the canton OGD lists an answer whose canton document uid sits in OPD with no affair, agenda or meeting | relink by canton uid |
| `oral` | VS `_ANT` document whose OPD text is the 80–95-char stub "cf. réponse orale du Conseil d'Etat"; or question time (OPD type `Question time`, or the parliament's own label Fragestunde / heure des questions / question orale / mündliche Anfrage; `census/defs.is_question_time`) with no answer document anywhere in OPD and no answer event saying the answer was written (tested after `image_only`, so a question-time scan stays `image_only`); or only oral answer events | retype; the answer was given in the sitting and is in the session minutes, no answer document expected |
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

**Meaning classes (added 10 Oct, post hoc; they do not change the tiers).** The tier says where a value lives. Whether it
means the same thing everywhere is classed separately (`data/schema/field_verdict_classes.json`), from the ambiguous raw
labels measured in `results/census/comparability.json`: *shared* (one meaning; only where the value lives differs),
*shared with a role split* (one source label covers several roles: the answer date is decided / dispatched / registered;
type, procedural history, procedural state and decision outcome have labels that map to different harmonised concepts in
different bodies) and *body-specific* (oral answers in question time, executive-own business, councils that publish only
meeting documents). The README's schema section gives the table.

Which classes rest on a measurement (round 5): `field_verdict_classes.json` now says per field whether its meaning was
tested across parliaments. **Measured** (a statistic in `comparability.json`): the 5 role-split fields (type 42 of 1,038
raw labels ambiguous; answer date and procedural history via the date-role labels, 35 of 14,618, plus the held-out
OPD-event-vs-printed check 37/44; procedural state 32; decision outcome 3) and one shared field, the government
recommendation (0 of 183). The other **11 shared fields are shared by definition, untested** (submission, decision and
dispatch dates, submitter, co-signatories, addressed body, Q/A pairing, related affairs, language, usable text,
answer-link status). "12 shared" therefore meant 1 tested + 11 by definition. Since P8 (`eval/prereg9/`,
`results/p8/`) seven fields are measured on documents: submitter, co-signatories, language, addressed body and
recommendation move to the role-split class, type stays there, and the submission date stays shared but is
body-specific in Vernier and Lausanne. The class table now holds 7 shared fields: 1 measured (the submission date,
P8) and 6 by definition, untested; meaning is measured for 11 of the 17.

Answer times (round 5): the pooled cross-parliament median (68 days, `question.json`) mixes date roles and types;
`results/census/answer_days_by_trust.json` (`python -m gegenprobe.census.days_by_trust`) splits it by date-trust tier and
type. `site/parliaments.csv` renames the pooled per-body column to `median_days_all_types` and adds per-type medians.

<!-- BEGIN GENERATED: census results -->

## 4. Results (generated by `python -m gegenprobe.census.doc`)

**Funnel.** 198,594 in-scope affairs in 86 bodies; 91,268 with a written-answer event; **16,749 (18.4%) without answer text**; 16,157 after the in-corpus agenda join (592 re-joined). 2024–25: 1,855 (14.3%).

**Written answers missing vs answered orally.** The 16,749 without answer text include 1,422 answered orally in the sitting (no written text expected: Valais oral-answer stubs and question time); the written answers missing from OPD are the other **15,327 of 89,846 answered in writing (17.1%)**. 2024–25: 1,855 without answer text = 367 oral + 1,488 written answers missing of 12,632 (11.8%). Counted from `link_status` in `results/census/interventions.tsv.gz` (`oral` vs the rest of not-`attached`).

**Reproduction.** The ported funnel reproduces the 8 Oct spike cell for cell: 5,444 body × type × year cells, 0 differing values, document-status table identical: True.

**Answer-link status** (all in-scope affairs): `absent` 10,924, `agenda` 932, `attached` 116,466, `image_only` 1,352, `not_applicable` 61,013, `oral` 5,448, `parentless` 2,459. Of gap′: BE 2,510 (canton lists an answer for 2,508; 2,459 relinkable parentless documents), CHE 75, other bodies with an answer document but no text 2,366 (of which VS oral stubs 1,016 by the length proxy; 1,008 by the exact text rule that the repair list uses, `results/census/vs_reconcile.json`), other bodies with no answer document 11,206 (of which 406 question-time answers typed `oral`: the answer was given in the sitting; 10,800 written answers that need the parliament's own site).

**Typed causes of the gap** (written answer recorded, no answer text; one cause per affair): `absent` 10,924, `agenda` 592, `image_only` 1,352, `oral` 1,422, `parentless` 2,459. `oral` = 1,016 VS stubs (length proxy) + 406 question-time answers with no answer document (Graubünden 367, Pratteln 24, Monthey 6, Basel-Landschaft 5, Thun 3, Valais 1). Their written-answer event is OPD's harmonised 'Beantwortet'; the answer itself is in the session minutes. Valais counts: **1,017** interventions typed `oral` (the table and the dataset) = 1,016 `_ANT` oral-answer stubs found by the census length proxy + 1 question-time answer with no answer document; **1,016** is the stub count alone; **1,008** of those stubs are confirmed by the repair's exact text rule (the `retype_oral` list; 8 documents where proxy and text rule disagree, `results/census/vs_reconcile.json`).

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
- *date: answer*: population = affairs with a written-answer event, so the event date exists by construction; its accuracy is checked against the source as the government's decision date only in Bern (the RRB decision date printed in the answer: 2,421 of 2,459 relink answers, the other 38 go to review; results/repair/be_verify_all.json) and Ticino (the date in the publisher's answer title 'Risposta del CdS del …': 2,379 of 2,379 dated answers that carry one; results/census/date_trust.json).
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
- Question time: 3,320 of 14,087 answered affairs have only an oral answer (23.6%).
- VS files 1,008 oral answers as an `_ANT` stub document, not as an oral event (exact text rule; the census length proxy flags 1,016: proxy precision 99.2% per document, recall 100.0%, `results/census/vs_reconcile.json`).
- In 7 of 54 bodies the 'answer' event date equals the submission date for ≥ 50% of affairs: the date exists in metadata but is not an answer date (Valais 88.6%, Interlaken 53.8%, Kriens 66.2%, Liestal 100.0%, Dübendorf 59.3%, Appenzell Ausserrhoden 62.2%, Schaffhausen 99.7%).

Cited evidence (not recomputed; `data/census/cited_evidence.json`): the S3-BILANZ atom inventory over 12 bodies left 45.9% of atoms without a schema account; five gaps recur across bodies and languages: person roles; comparison amounts; dates and laws of other polities; dates of other affairs; entry-into-force and deadline dates. Estimating the *size* of the missing schema with Chao2 failed both pre-registered checks (no saturation, ≈57.4 new accounts per body): a well-evidenced negative.

### The cross-parliamentary question

Across 54 parliaments with ≥ 20 written-answer interventions, the answer text is in OPD for 82.3% (85.0% after the measured relinks); the pooled median from submission to the answer event is 68 days over 90,556 dated answers, but that pools date roles and intervention types: by what OPD's 'answer' date is, verified decision dates 112 (2 bodies), weekly-sitting dates 79 (24 bodies), mixed 62 (14 bodies), diffuse (publication-like) 39 (7 bodies), same-day artefacts 0 (7 bodies); question time 5. Quote answer times per parliament and type with the body's date tier, not the pooled median (`results/census/answer_days_by_trust.json`). Lowest answer-text shares: Interlaken 0.0%, Collombey-Muraz 0.0%, Münsingen 0.7%, Monthey 0.8%, Lugano 5.2%, Neuchâtel 6.9%. Caveat: the answer date is the OPD event date; it is verified as the government's decision date in Bern (the RRB decision date printed in the answer: 2,421 of 2,459 relink answers, the other 38 go to review; results/repair/be_verify_all.json) and Ticino (the date in the publisher's answer title 'Risposta del CdS del …': 2,379 of 2,379 dated answers that carry one; results/census/date_trust.json), and unverified elsewhere (it may be a registration or publication date; per-body date-trust tiers in results/census/date_trust.json). Submission = the earliest 'Eingereicht'-type event (harmonised ids 1/56/67), else `begin_date`; BE affairs whose begin_date is the 2024-10-28 import artefact and no submission event are excluded; durations < 0 or > 3,650 days are excluded and counted. The national median pools date roles (decision, weekly-sitting, publication dates) and intervention types: see results/census/answer_days_by_trust.json before quoting it. Body names follow the site's rule (`name`; OPD's: `opd_name`).

### Data-quality findings

| finding | value | verified | OPD response |
|---|---|---|---|
| Bern government answers that the canton publishes but OPD does not attach to their affair | 3,303 / 3,532 (93.5%) | recomputed | confirmed bug |
| Federal (CHE) documents whose stored text is Fedlex's 'JavaScript required' page | 30,033 / 52,450 (57.3%) | recomputed | confirmed |
| bodies.lang tags canton FR as 'DE' | 1 / 1 | recomputed | by design |
| bodies.lang tags canton VS as 'DE' | 1 / 1 | recomputed | by design |
| Documents without a language tag | 525,363 / 902,754 (58.2%) | recomputed | by design |
| Bodies with a docs export but zero affairs | 8 | recomputed | scope pointer |
| Affair numbers that are dates | 5,528 / 325,691 | recomputed | scope pointer |
| BE affairs whose begin_date is > 1 year off the year in their number | 800 / 8,193; 557 on 2024-10-28 | recomputed | confirmed bug |
| The docs `hash` field is an identifier (sha256 of body_key + parent_type + url), not the PDF's sha256 | 386 / 386 | recomputed | explained |
| Document rows that duplicate another row's body, parent and URL | 726 / 902,754 (0.1%) | recomputed | — |
| 2025.GRPARL.384: the canton's open data and the canton's own PDF disagree on the submission date | {"opd_begin": "2025-06-18", "pdf": "19.06.2025"} | recomputed+cited | source discrepancy |
| Affairs without a harmonised type | 55,767 / 325,691 (17.1%) | recomputed | — |
| Affairs with a harmonised procedural state | 278 / 325,691 (0.1%) | recomputed | — |
| The persons export includes contact and birth-date fields of public figures (we stored field names only) | 6 / 60 | recomputed (field names only) | by design |

OPD response column, source: OPD confirmed (correspondence, 10 Oct 2026); per-finding detail in `results/census/findings.json` (`opd_response`).

Virtual-affairs frontier (`results/census/virtual_affairs.json`): 16 bodies whose documents hang on meetings rather than affairs (8 with no affairs at all; 5,887 meeting-only documents). Deriving affairs from those meeting documents ('virtual affairs', schema `AffairRef.virtual` / `derived_from`) is the next frontier of the common schema.

## 5. Known limitations

- The answer patterns are hand-written regexes; their precision is checked only through the 40-affair gap audit (27/35 true gaps) and the BE canton join (spikes/recovery).
- `be_rrb_filled` (scan-time flag) expects the year first; the current BE format "RRB-Nr.: 879/2024" is not flagged. BE answers are still found by name/heading; the flag is kept frozen because changing it needs a re-scan.
- Year comes from the affair number where it starts with a year, else from `begin_date` (affected by the BE 2024-10-28 import date).
- Parentless counts do not check `news_id` (not kept by the scan).
- `co-signatories` is a lower bound (no co-signers vs. unrecorded is indistinguishable in metadata).
- The `accuracy` column stays empty: measured extraction accuracy exists only for the answer date, per language x level cell of the held-out gold set rather than per body (`results/census/matrix_accuracy.json`; no federal documents in the gold set). `pdf` cells say a converter *can* work there, not that it does.

<!-- END GENERATED: census results -->

## 6. Answer times on the answer documents' own dates (post hoc finding)

*Not part of the generated section above, which `python -m gegenprobe.census.doc` rewrites. Computed by
`python -m gegenprobe.findings.answer_times` → `results/findings/answer_times.json` from committed files only (no model,
no network); `tests/test_findings_answer_times.py` recomputes it.*

§4 ends on "quote answer times per parliament with the body's date tier": OPD's 'answer' date is a decision date in some
parliaments, a sitting, publication or submission date in others. The source adapters (`docs/adapters.md`) verified 6,613
answers in 27 parliaments and read the date each answer document carries (its header or place-date line; in the cantons
mostly the government's decision date, in Neuchâtel the date the answer was transmitted to the Grand Conseil). This
section recomputes answer times on that date and asks whether the cross-parliament ranking holds.

**Sample.** All 6,613 counted adapter rows (the three tiers with a date check). Answer date: the document's own date as
read (5,428 rows); for rows verified because a printed date equals OPD's answer event and no own date was read (mostly
OCR'd Ticino letters titled 'Risposta del CdS del …'), that event's date when the affair has exactly one (1,010 rows);
98 rows with several answer events are excluded (which one the printed date matched is not recorded). Submission date:
the census rule (`interventions.tsv.gz` `submitted`). Durations below 0 (75) or above 3,650 days (2) are excluded, as in
the census. That leaves 6,438 durations in 27 parliaments; the ranking uses the 17 parliaments with at least 20 durations.
Three medians per parliament: OPD's plain median (§4, every answered intervention), OPD's census date on the same
affairs, and the document date.

| parliament | OPD date tier | n | OPD plain (all affairs) | OPD date, same affairs | document date [IQR] | rank OPD → document |
|---|---|---:|---:|---:|---:|---|
| Kriens | same_day | 68 | 0 | 0 | 26.5 [15, 41.5] | 1.5 → 1 |
| Neuchâtel | diffuse | 232 | 25 | 36 | 36 [28, 88.75] | 3 → 2 |
| Jura | mixed | 72 | 48 | 48 | 48 [41, 83] | 4 → 3 |
| Arbon | sitting_day | 21 | 55 | 55 | 55 [48, 74.5] | 6 → 4.5 |
| Thurgau | sitting_day | 32 | 55 | 55 | 55 [41, 184.5] | 6 → 4.5 |
| Aarau | sitting_day | 71 | 59 | 60 | 60 [35, 141] | 8 → 6 |
| St. Gallen | sitting_day | 1,011 | 64 | 63 | 63 [41, 85] | 10 → 7 |
| Ticino | verified | 719 | 61 | 67 | 67 [37, 116] | 9 → 8 |
| Locarno | diffuse | 119 | 66 | 70 | 70 [38, 174] | 11 → 9 |
| Zürich (canton) | sitting_day | 2,164 | 79 | 79 | 79 [58, 86] | 12 → 10 |
| Zürich (city) | sitting_day | 1,328 | 91 | 85 | 84 [70, 92] | 13 → 11 |
| Illnau-Effretikon | sitting_day | 30 | 105 | 90.5 | 90.5 [74.75, 175.75] | 15 → 12 |
| Monthey | sitting_day | 29 | 98 | 91 | 91 [70, 101.5] | 14 → 13 |
| Valais | same_day | 99 | 0 | 173 | 100 [50, 147] | 1.5 → 14 |
| Solothurn | mixed | 209 | 55 | 169 | 125 [76, 153] | 6 → 15 |
| Luzern | mixed | 104 | 134 | 155 | 155 [119, 222.5] | 16 → 16 |
| Vaud | sitting_day | 90 | 161 | 1,156 | 1,156 [802.5, 1,642.5] | 17 → 17 |

Days from submission; rank 1 = shortest median, ties share the mean rank.

**Finding.**
- The ranking on OPD's plain medians and the ranking on the documents' own dates agree only moderately: Spearman
  ρ = 0.656 over 17 parliaments (permutation p = 0.006). Without the two same-day parliaments, ρ = 0.832 (15).
- The largest moves are where OPD's 'answer' date is not the answer's date. **Valais** moves from fastest (median 0 days,
  OPD's answer event falls on the submission date) to 14th of 17 (100 days). In 61 of its 163 verified answers, all
  motions, OPD's submission event lies after the government's answer letter (54 of them on the same day as OPD's answer
  event), so these rows are excluded and Valais's submission date is itself not reliable in OPD. **Kriens** goes from 0 to
  26.5 days. **Solothurn**: OPD's census date on these affairs is 36 days after the government's statement (median
  difference; OPD's 'Beantwortet' event is the committee's, `docs/adapters.md`).
- Part of every move is the sample, not the date. The adapter sample is the census gap (answers OPD lacks text for), with
  its own type mix: Vaud's 90 are postulates (median 1,156 days on both dates), and Solothurn's are mostly motions (183
  of 209). OPD's plain median and OPD's date on the same affairs rank the parliaments with ρ = 0.584. On the same affairs,
  OPD's date and the document date rank them almost identically (ρ = 0.99). Within one type the rankings agree:
  written questions ρ = 0.966 (13 parliaments), interpellations 0.9 (5), postulates 1.0 (4).
- In 13 of the 17 parliaments, OPD's census answer date equals the document's own date for at least 90% of the verified
  answers. This extends the per-affair date check of §4 (Bern, Ticino) to 11 more parliaments, for the gap affairs. It
  differs in Kriens, Monthey, Solothurn and Valais.

**What this means for the schema.** A cross-parliament comparison of answer times is reliable when each answer carries a
date with its role (the schema's `answer_decided`, `answer_dispatched`, or `answered` when the role is unknown) and the comparison holds the type fixed. Where
OPD's date already is the government's date, the ranking holds. Where it is a submission, session or committee date
(Valais, Kriens, Solothurn), the plain median ranks a parliament in the wrong place. These are the parliaments the
date-tier column (`same_day`, `mixed`) already flags.

**Limits.** The sample covers 27 parliaments and only their gap affairs, not every answer. The 'exact' tiers count a row
only when its date equals an OPD event, so agreement with OPD on those rows partly follows from how they were verified.
What the adapter adds is *which* event: the census rule takes the earliest written-answer event, and in four parliaments
that is not the document's date. Medians pool intervention types unless stated.
