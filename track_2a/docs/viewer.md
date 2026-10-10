# Evidence viewer

A static page (`site/index.html`, no server, no external scripts) that shows the evidence a reviewer or juror needs:

| View | What it shows | Source files |
|---|---|---|
| 01 Documents | the 154 held-out documents: gold label, default converter (rules only), Apertus review suggestion, naive free generation; every value with page, character span and a highlighted excerpt; typed nulls as states; the closed set of printed dates Apertus could choose from, with its probability share; the null margin against θ | `data/gold/heldout_*.jsonl`, `results/eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json`, cached texts and the committed model cache (replayed, no calls) |
| 02 Parliaments | per parliament: written answers, share with text, missing answers by typed cause, median days to answer, repair actions; per-body schema-feasibility row | `results/census/{summary,question,matrix}.json`, `results/repair/summary.json` |
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
