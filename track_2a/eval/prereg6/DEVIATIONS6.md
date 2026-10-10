# Deviations and reported events for P5 (eval/prereg6/PREREG6.md, LOCK6 at db339eb)

LOCK6 stayed intact through the draw, the runs and the scoring (`python -m eval.prereg6.lock6 check`).

## Reported events (by protocol; not deviations)
- **D6-1 Fribourg city replaced by its reserve.** All 33 Fribourg-city postulates in the pool link to HTML pages
  (`ville-fribourg.ch/actualites/...`), not PDFs; 33 attempts failed `not_a_pdf` and the cell "2196 Postulate" was filled
  from the registered reserve, Collombey-Muraz (6152, 4 postulates). French P5 documents therefore come from Lausanne, VS
  and Collombey-Muraz; Fribourg city is not measured. All attempts: `data/gold6/p5_fetch_log.jsonl`.
- **D6-2 Replacements within a cell.** GR (Italian documents): 13 affairs whose member text resolved to an HTML page
  (`ris.gr.ch/cdws/files/.../pdf`) were skipped and replaced by the next GR affairs in seeded order; Riehen: one affair
  (`not_a_pdf`) replaced the same way. No other fetch failed; every accepted document has a text layer (no OCR).
- **Arms run before the labels.** All arms were run (frozen code, results written) before any P5 label existed; the
  coordinator's transcript audit found that no annotator read predictions or results.
- **A3** decided 2 disputed submitter fields (affairs 280476, 29393); all other fields agreed between A1 and A2
  (`results/eval6/p5_agreement.json`).

## Deviations
- **D6-3 Qwen check: retry wrapper.** The frozen `eval/gold6/qwen6.py:annotate` stops at the first HTTP 429 from Public
  AI (it did, after 2 completed calls). The check was run with `eval/gold6/qwen6_run.py`, a new wrapper that calls the
  frozen `qwen6.call` one affair at a time with back-off on 429 / disconnects and writes the same output file in the same
  format. Prompt, model, parameters, tag and cap are unchanged; the frozen file is unchanged.
- **D6-4 Post-hoc breakdowns.** `eval/gold6/posthoc6.py` (new, not registered) writes per-language and per-body tables,
  the kinds of rules-only submitter errors and the dev-vs-P5 drop per field (`results/eval6/p5_posthoc.json`). Labelled
  post hoc wherever cited; no registered number or verdict depends on it.
