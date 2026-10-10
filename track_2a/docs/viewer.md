# Evidence viewer

A static page (`site/index.html`, no server, no external scripts, no third-party requests: fonts are self-hosted) that shows the evidence a reviewer or juror needs:

| View | What it shows | Source files |
|---|---|---|
| 01 Parliaments (opens first) | per parliament: written answers, share with text, missing answers by typed cause, median days to answer, repair actions; date trust; per body the list of affairs without attached text (OPD + source links, CSV); answer times by type; Bern reconciliation; research dataset download | `results/census/{summary,question,matrix}.json`, `results/repair/{summary,be_reconcile,be_verify_all}.json`, `results/census/{interventions.tsv.gz,date_trust.json,answer_rule_alt.json}` |
| 02 Documents | browse: the 154 held-out documents: gold label, default converter (rules only), Apertus review suggestion, naive free generation; every value with page, character span and a highlighted excerpt; typed nulls as states; the closed set of printed dates Apertus could choose from, with its probability share; the null margin against θ ; **workbench**: the 93 documents the rules leave open as a keyboard review queue (demo, gold shown after each decision) | `data/gold/heldout_*.jsonl`, `results/eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json`, cached texts and the committed model cache (replayed, no calls) |
| 03 Evaluation | five pre-registered tests (P1, P2, P3, P3b, P4): scoreboards, hypotheses as computed, order of events from git, gold-label agreement, post-hoc θ curve (labelled) | `results/eval*/*`, `eval/prereg*/{LOCK*,DEVIATIONS*.md}` |
| 04 Method | pipeline and schema v0.1 fields with feasibility tiers | `results/census/matrix.json` |

## Commands
```bash
make site                                   # collect site/data.json from results + build site/index.html (dev)
python -m gegenprobe.viewer build --out DIR # render from the committed site/data.json only (what `make run` does)
python -m gegenprobe.viewer build --full-text --out .work/site   # local only: adds full page texts; never commit
```
`make run` renders the viewer into `out/site/index.html` as a final, non-failing step.

## Downloads (OPD box, round 5)

`python -m gegenprobe.viewer collect` (part of `make site`) copies the files listed in `viewer/data.py` `DOWNLOADS`
byte for byte into `site/downloads/`, and `build --out DIR` copies that folder next to `DIR/index.html`. The "For OPD's
data team" box lists them under the three steps, each with its row count and size, plus the repository URL
(https://github.com/mi11ione/gegenprobe):

| group | files (source) |
|---|---|
| Bern lists | `repair_BE_relink.tsv`, `repair_BE_fetch.tsv`, `repair_BE_review.tsv`, `repair_BE_begin_date.tsv` (`results/repair/`) |
| Apply plan (dry run) | `apply_BE_plan.sql.txt`, `apply_BE_relink_plan.csv`, `apply_BE_begin_date_plan.csv`, `apply_BE_plan.json` (`results/repair/apply_be/`) |
| JSON Schemas (v0.1) | `affair.schema.json`, `doc_extraction.schema.json` (`results/schema/`) |

They add about 3.7 MB to the site (the relink TSV, the SQL text and the relink plan CSV are about 1 MB each; Cloudflare
compresses text on the wire). The links are relative (`downloads/<file>`); before round 5, `/repair_BE_relink.tsv` was not
served and the single-page fallback returned the index page instead. `tests/test_r5_ops.py` checks that the copies are
byte-identical to the results files and that a build into another directory carries them.

The schema sample record (top of the page) is the P3b record after the product post-processing
(`gegenprobe.affair_post`, `docs/affair.md`): `qa[0].answering_body` is left out with a note instead of a false
`present_unanchored`, and the interpellation's `decision` is `not_applicable`.

## Numbers and texts
Every number on the page is read from the files above when the page is built; none is typed by hand, so the page is
traced by construction (the README and report numbers are traced separately in `claims.tsv`). The committed copy carries
document text only as excerpt windows of at most 280 characters around the cited spans and up to ten short candidate
contexts per document (`tests/test_viewer.py` asserts this); the original PDFs are linked by URL and sha256.

## Design
Swiss grid (12 columns, flush left, one signal red) with a technical-manual idiom for data: monospace for every datum,
part-number style identifiers, hairline rules. Light and dark themes follow the system setting (toggle in the header);
works from 500 px up to wide screens; keyboard focusable; no motion beyond an optional smooth scroll.

## Parliaments view: one denominator (v2)

Every per-body number uses one population: interventions whose events record a **written** government answer (the census
funnel's `ev_w`), in the chosen period (all years / since 2015 / 2024–25, by the year in the affair number, else the begin
date). Each of them has exactly one answer-link status, so

    attached + agenda + parentless + image_only + oral + absent = written     (asserted in tests/test_viewer.py)

- **Text attached** = attached / written; **Missing** = written − attached (nationally 16,749, as in the README).
- **After repair** = (attached + agenda join + Bern parentless relink + Bern fetch from the canton) / written. OCR candidates and
  oral answers are typed, not counted as text.
- **Median days** (all years) is hidden ("—†") for the 7 parliaments whose "answer" event mostly equals the submission date,
  and for parliaments with fewer than 20 durations.
- **Bern** also shows the canton's own list (3,532 answers; 229 attached, 3,394 linkable within OPD) in its detail panel, as a
  separate, labelled denominator (the same numbers as fig. 3).
- **Labels**: "Bern (canton)" vs "Bern (city)"; OPD's German body names are kept as proper nouns.
- **Safe to say**: one generated sentence per parliament with its caveat (`viewer/data.py:safe_say`).
- **Findings**: every data-quality finding with OPD's response status; attribution text comes from
  `census/opd_status.py:ATTRIBUTION` (one switch).
- **CSV**: `site/parliaments.csv`, written by `collect`, all three periods.

The Documents view marks a printed date on a document whose gold label says it carries no answer as "date, no answer"
(not "wrong date"), and flags the three contested gold labels (28271, 862297, 300277) with the reason. The Evaluation view
adds the always-null baseline (90/154), dates found per arm (of 64) and the precision of Apertus review suggestions (9 of 16).

## v3: census first, research dataset, workbench

- **Opens on Parliaments.** A persistent banner in the header: *Not in OpenParlData ≠ not published by the parliament.*
  Under the hero, a 3-step strip (v5: addressed to OPD's data team) and a 6-term glossary (OPD, typed null, closed set,
  pointer, θ · margin band, P1–P4 · P3b).
- **One period for the whole page.** The switch (all years / since 2015 / 2024–25) sits in the hero and above the table
  and drives both; the headline is `headline.periods[period]`, the sum of the table rows (asserted). Default: all years
  (16,749 of 91,268). Each "safe to say" line is labelled with the period(s) it uses.
- **Drill-down.** Opening a row loads `site/missing.json` (fetched on first use, so the page stays small): every affair
  without attached text in the chosen period, newest first, with its cause, its OPD page
  (`https://openparldata.ch/item/affairs/{id}`) and the parliament's own page (OPD `url_external_*`), plus a CSV for that
  parliament (made in the browser). Over `file://` the list is not fetched and the panel points to the dataset.
- **Answer times** by intervention type per body (n ≥ 10), with "not a ranking" next to the column and in the panel;
  **Dates** (date trust) per body from `results/census/date_trust.json`: verified (Bern) · sitting day (≥ 80 % of answer
  dates on one weekday) · mixed · diffuse · same day · too few (v5: Ticino is verified too, by the publisher's answer title).
- **+ OCR** is its own state, shown only where a body has answers whose copy in OPD has no text (Ticino 67.5 % → 100.0 %,
  all years); OCR was probed (15/15), not run on all of them (v5 wording: "would recover").
- **Bern, every number in one place** (`#bern-numbers`): the canton's list (3,532; 229 attached; 3,303 not attached; 527
  agenda; 2,638 parentless; 138 absent; 3,394 linkable), the relink list (2,459 + 155 already answered + 24 without an
  answer event; 49 to fetch), the OPD-event denominators per period (3,409 / 3,114 / 593), and the verified dates
  (2,421 of 2,459). Linked from the hero fact and the Bern panel.
- **Research dataset** (`results/census/interventions.tsv.gz`, copied to the site with its README): 91,268 rows, one per
  intervention with a written-answer event, CDLA-Permissive-2.0. Built by `python -m gegenprobe.census.interventions`.
- **Workbench** (Documents → Workbench): the documents where the rules abstain and the closed set is not empty (93),
  ordered strong suggestion (margin ≤ −5) → weak (−5 < margin ≤ θ) → no suggestion, leaned null (margin > θ). Keys:
  j/k move, a accept, r reject (value stays open), 1–9 pick a printed date, 0 null. Decisions are kept in
  `localStorage` (`gp-wb-v1`, wrapped in try/catch) and exported as a JSON decision log through a download link. Labelled
  "demo on held-out documents": the gold label is revealed after each decision.
- **P2 error profile in words** per arm, and a data-driven line on why rules + Apertus (51) trails the pointer alone (53):
  on 2 documents a rule fired with a wrong date, so Apertus was never asked; no document goes the other way
  (`p2.cascade_vs_pointer`, computed from the per-document rows).

## v4 (round 3): newsroom fixes, self-hosted fonts

- **No third-party requests.** Archivo (variable, wght 100–900, wdth 62–125) and IBM Plex Mono (400/500/600), latin and
  latin-ext woff2 subsets, are served from `site/fonts/` with their SIL OFL 1.1 licence texts; sources (exact
  `@fontsource` versions on cdn.jsdelivr.net) and sha256 in `site/fonts/SOURCES.txt`. `build --out DIR` copies the
  fonts next to `index.html`. `tests/test_viewer.py::test_fonts_self_hosted` fails if the template references
  fonts.googleapis.com or fonts.gstatic.com again.
- **Oral question time is not "missing".** Question-time answers (Fragestunde, heure des questions, question orale) with
  no answer document in OPD are typed `oral` by the census (406; Graubünden 367 of them, `docs/census.md` §2, §4), like
  the Valais oral stubs. "Safe to say" names them separately wherever there are any in the period it quotes, and states
  the rate over answers given in writing (Graubünden 2024–25: all 62 without text are question time; every written
  answer has its text). Since round 5 the table splits them out too (below).
- **Answer time within one type.** The table column and the drawer show the median days to the first written-answer
  event for one intervention type at a time (selector above the table; default interpellation), in the chosen period,
  with the interquartile range; n ≥ 10 per type and period; hidden for same-day bodies. No mixed-type median is shown.
  The CSV adds per-type medians and counts per period (`*_median_days_{type}`, `*_n_{type}`; round 5).
- **Coverage gaps are a status.** A parliament for which OPD holds ≥ 20 in-scope interventions but records a written
  government answer for fewer than 20 of them and for under 10% (all years) is a `coverage gap` (31: among the cantons
  SZ, UR, GL, AI, NW, GE): a chip in the table, a strip above it, a "Coverage" filter, a generated "safe to say" ("a gap
  in OPD's coverage of answers, not evidence that the parliament leaves questions unanswered") and a `coverage` column
  in the CSV. `no_affairs` (meeting documents only) and `few` are the other non-measured states.
- **Cantons only.** A "Show" filter: all · cantons · cities & communes.


## v5 (round 4): OPD's data team first, five tests, schema record near the top, Ticino

- **Audience.** The strip under the hero is addressed to OPD's data team: (1) apply the Bern lists (2,459 relinks + 49
  fetches, keyed on OPD ids), (2) fix the rest by cause, per parliament, (3) take the data. Journalists are pointed to
  each row's "safe to say" sentence. No newsroom framing.
- **Schema v0.1 near the top** (`#schema-top`, always visible; `viewer/data.py:schema_view`): one real converter record,
  not a hand-made sample: P3b affair 301273 (Basel-Landschaft, interpellation 2013/436) from
  `results/eval5/p3b__publicai_swiss-ai_apertus-v1.5-8b.json`. Metadata values carry their OPD record
  (`opd:events/…`); the answer date read from the answer carries page 2, characters 177–194 and the quote
  "18. November 2014" (it agrees with the blind gold label); empty fields are typed nulls with their reason
  (`government_recommendation: not_applicable`, `decision: not_in_corpus`); the Apertus suggestion for the addressed body
  is shown apart, as a review suggestion without a span (document-level choice). The whole record is in a `<details>`.
  Below it, the 17 fields with their meaning class (12 shared, 5 shared with a role split; the field-to-class map is the
  README table, `viewer/data.py:FIELD_CLASS`; definitions `data/schema/field_verdict_classes.json`), the tier, where the
  value lives (metadata · partly · only in the PDF · not in OPD's data, counted over the parliaments where the field
  applies) and the evidence (`results/census/comparability.json`), then the three body-specific concepts (oral answers in
  question time, councils that publish only meeting documents, executive business answering no member's affair).
- **Five tests everywhere.** Evaluation heading, intro and glossary name P1, P2, P3, P3b, P4. New P3b section
  (`viewer/data.py:p3b`, from `results/eval5/{hypotheses_p3b__…,p3b__…,gold5_agreement,annotation_audit}.json`): the
  verdict by the registered criteria (replicated: S1 14/16, S2 one of five fields below, the answer date), the per-field
  board (metadata · rules · default · + Apertus · constant · P3 · within/below/above P3's CI · registered tier), why the
  answer date is below P3 (data-driven: on 3 Luzern affairs a frozen rule replaced OPD's correct answer date with another
  printed date), H1 (type 35/36 is the one field that reaches the unattended tier) and H3 (recall 14/16 holds, precision
  14/20 below the bar: reviewer gate; answer-date suggestions 11/11). The 8B note no longer says "invents no date": it
  picks no unprinted date but dates 25 of 90 answerless documents (70B: 7).
- **Canton names.** Cantons by their official name in the language of their majority (Ticino, Vaud, Genève, Valais,
  Fribourg; Graubünden, Bern, Luzern); cities and communes by OPD's name, which is already the local one. OPD's German
  name stays searchable and is shown in the drawer ("OPD: Tessin"). `viewer/data.py:CANTON_NAME`, also used for the
  P2/P3/P3b body lists.
- **No text, not "scan".** The `image_only` state is labelled "OPD's copy has no text" (an answer document is attached,
  but OPD's copy has no text layer or OPD's extraction failed); "safe to say" says OCR *would* recover them and that
  re-taking a text version the parliament publishes is cheaper. Spot check, not a count
  (`python -m gegenprobe.census.source_formats` → `results/census/source_formats_ti.json`, 3 requests on 10 Oct 2026):
  Ticino publishes the answer to interrogazione 100.19 as `r100.19.doc` and `r100.19.pdf`; OPD holds one copy, without
  text.
- **"All years" = the years OPD holds.** Each row carries the first and last year of its written-answer interventions
  (`years`; CSV `first_year`, `last_year`): Ticino 2016–2026. "Safe to say" reads "over all years OPD holds (2016–2026)".
- **Not in OPD's data.** The field status `no_source` reads "not in OPD's data"; for co-signatories the drawer adds "the
  parliament may list them on its own page".
- **List pages.** A source URL that OPD gives for more than one affair of a parliament is that parliament's list page,
  not the affair's page: the row is flagged (6th element in `missing.json`, CSV column `source_is_list_page`) and the link
  reads "list page ↗" (Lugano: all 201 affairs point at one "Mozioni" page).
- **Answer times.** A warning above the table ("not a league table": procedures differ between parliaments). The default
  type is each parliament's own most-answered type, named next to the median ("Most answers"; Ticino: questions, 76
  days, all years); one type for all is still selectable. CSV: `all_main_type`, `all_median_days_main_type`.
- **Ticino's dates are verified.** `census/interventions.py` adds a publisher-title check to the date-trust tiers: a
  body is `verified` (`verified_by: title`) when at least 90% of its dated answers carry a publisher title naming the
  decision date ("Risposta del CdS del dd.mm.yyyy", "RRB-dd.mm.yyyy") and at least 99% of those equal OPD's answer date.
  Ticino: 2,379 of its 2,386 dated answers carry such a title and all 2,379 equal OPD's answer date (73% of the dates fall
  on a Wednesday, a weekly-sitting pattern; below the 80% sitting-day bar, hence "mixed" before); on 20 of 20 P1 held-out
  Ticino answers the title date is the date printed in the answer
  (`results/eval/posthoc_r3_gold_oracle.json`). Bern stays `verified_by: printed`. Tier counts: verified 2, mixed 14. Only
  the `date_trust` column of the 2,386 Ticino rows of `interventions.tsv.gz` changed.

## Round 5: census consistency (data desk U2, OPD partner J1)

- **Oral answers are not "missing".** Each period carries `missing` (no answer text attached: the census gap, 16,749 all
  years, *including* oral answers), `oral`, `in_writing` (= written − oral), `written_missing` (= missing − oral = agenda
  + parentless + image_only + absent) and `written_missing_share` (`viewer/data.py:parliaments`). The table shows **No
  answer text** (muted, the registered total) = **Oral** + **Written missing** (red, with its share of answers given in
  writing); the old "Missing" column is gone and "No text" is now "Scan, no text". Hero and intro add the split: 1,422
  of the 16,749 were answered orally; 15,327 of 89,846 answers given in writing (17.1%) are missing; 2024–25: 367 oral,
  1,488 of 12,632 (11.8%). Valais 2024–25: 315 without text = 305 oral + 10 written missing of 271 (4%).
- **"Safe to say" uses the written-missing figure** (`safe_say`): "X of Y written government answers" counts only answers
  given in writing; where a parliament has oral answers in the period, the sentence first says how many were answered
  orally ("no written text is expected and they are not missing"), then the written-missing rate. The all-years
  comparison and the cause sentence ("most of the missing written answers …") use written-missing too.
- **Valais oral counts reconciled** (`viewer/data.py:oral_reconcile` → `parliaments.oral_reconcile`, shown in the Valais
  drawer): 1,017 typed `oral` (table, dataset) = 1,016 `_ANT` stubs (census length proxy) + 1 question-time answer (3.163);
  1,008 = the stubs the repair's exact text rule confirms (`retype_oral`; `results/census/vs_reconcile.json`). The
  function asserts 1,017 = 1,016 + 1.
- **CSV** (`write_csv`): `*_missing` → `*_no_answer_text`; new `*_in_writing`, `*_written_missing`,
  `*_written_missing_share`; `median_days` → `median_days_all_types` (pools every type; caution in the column dictionary);
  per-type `*_median_days_{interpellation,question,motion,postulate,question_time}` and `*_n_{type}` (n ≥ 10). Column
  dictionary for `parliaments.csv` appended to `interventions_README.md` (shipped next to the CSV).
- **One naming rule everywhere.** `CANTON_NAME` / `CANTON_RULE` moved to `census/presentation.py`; `results/census/question.json`
  now names cantons by it (`name`; OPD's German name in `opd_name`), so does the generated part of `docs/census.md`
  (Valais, Neuchâtel instead of Wallis, Neuenburg).
- **Stale Bern verification removed.** `question.json` caveat, `matrix.json` (date: answer note) and
  `answer_days_robust.json` said "39/39"; they now read the current counts from the committed results
  (`presentation.answer_date_caveat`: Bern 2,421 of 2,459 relink answers by the printed RRB date, 38 to review; Ticino
  2,379 of 2,379 by the publisher's title). `make census-replay` still matches.
- **"Meaning tested?" in the schema table.** `data/schema/field_verdict_classes.json` lists per field `meaning_tested`
  (`measured` + the `comparability.json` key, or `by definition, untested`); `schema_view` adds `tested`, `tested_in`,
  `tested_counts`. Of the 12 shared fields 1 is measured (government recommendation, 0 of 183 labels ambiguous), 11 are
  shared by definition; all 5 role-split fields are measured.
- **Answer times by date tier.** `census/days_by_trust.py` → `results/census/answer_days_by_trust.json`: the pooled 68
  days split by what OPD's "answer" date is (verified 112 days, 2 bodies; sitting day 79, 24; mixed 62, 14; diffuse 39, 7;
  same day 0, 7) and by type; run by `make census`.
