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
