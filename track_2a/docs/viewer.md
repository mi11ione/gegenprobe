# Evidence viewer

A static page (`site/index.html`, no server, no external scripts) that shows the evidence a reviewer or juror needs:

| View | What it shows | Source files |
|---|---|---|
| 01 Parliaments (opens first) | per parliament: written answers, share with text, missing answers by typed cause, median days to answer, repair actions; date trust; per body the list of affairs without attached text (OPD + source links, CSV); answer times by type; Bern reconciliation; research dataset download | `results/census/{summary,question,matrix}.json`, `results/repair/{summary,be_reconcile,be_verify_all}.json`, `results/census/{interventions.tsv.gz,date_trust.json,answer_rule_alt.json}` |
| 02 Documents | browse: the 154 held-out documents: gold label, default converter (rules only), Apertus review suggestion, naive free generation; every value with page, character span and a highlighted excerpt; typed nulls as states; the closed set of printed dates Apertus could choose from, with its probability share; the null margin against θ ; **workbench**: the 93 documents the rules leave open as a keyboard review queue (demo, gold shown after each decision) | `data/gold/heldout_*.jsonl`, `results/eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json`, cached texts and the committed model cache (replayed, no calls) |
| 03 Evaluation | pre-registered scoreboard, H1–H4 as computed, order of events from git, gold-label agreement, post-hoc θ curve (labelled) | `results/eval/*`, `eval/prereg/{LOCK,DEVIATIONS.md}` |
| 04 Method | pipeline and schema v0.1 fields with feasibility tiers | `results/census/matrix.json` |

## Commands
```bash
make site                                   # collect site/data.json from results + build site/index.html (dev)
python -m gegenprobe.viewer build --out DIR # render from the committed site/data.json only (what `make run` does)
python -m gegenprobe.viewer build --full-text --out .work/site   # local only: adds full page texts; never commit
```
`make run` renders the viewer into `out/site/index.html` as a final, non-failing step.

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
  Under the hero, a 3-step "where to look" strip and a 6-term glossary (OPD, typed null, closed set, pointer,
  θ · margin band, P1–P4).
- **One period for the whole page.** The switch (all years / since 2015 / 2024–25) sits in the hero and above the table
  and drives both; the headline is `headline.periods[period]`, the sum of the table rows (asserted). Default: all years
  (16,749 of 91,268). Each "safe to say" line is labelled with the period(s) it uses.
- **Drill-down.** Opening a row loads `site/missing.json` (fetched on first use, so the page stays small): every affair
  without attached text in the chosen period, newest first, with its cause, its OPD page
  (`https://openparldata.ch/item/affairs/{id}`) and the parliament's own page (OPD `url_external_*`), plus a CSV for that
  parliament (made in the browser). Over `file://` the list is not fetched and the panel points to the dataset.
- **Answer times** by intervention type per body (n ≥ 10), with "not a ranking" next to the column and in the panel;
  **Dates** (date trust) per body from `results/census/date_trust.json`: verified (Bern) · sitting day (≥ 80 % of answer
  dates on one weekday) · mixed · diffuse · same day · too few.
- **+ OCR** is its own state, shown only where a body has scans without text (Ticino 67.5 % → 100.0 %, all years); OCR was
  probed (15/15), not run on every scan.
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
