# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Every number below is
recomputed from a results file in the repository by `make run` (claims.tsv); spike figures are marked as cited.

- **Where Swiss parliamentary answers go missing.** 16,749 of 91,268 interventions with a written government answer
  (18.4%) have no answer text in OpenParlData; each one has a typed cause (agenda item, no parent, scan without text, oral,
  not in OPD). Per-parliament answer rates and answer times, with caveats and a CSV: site → Parliaments.
  Files: `results/census/`, `docs/figures/fig1_funnel.png`.
- **Repair lists OPD can apply.** In Bern, OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet 3,394
  (96.1%) are already in OPD and linkable. OPD confirmed the bug and its root cause (correspondence, 10 Oct 2026); until
  its fix ships, our relink list (2,459 relinks + 49 fetches, `results/repair/repair_BE.tsv`) is the best interim
  workaround. A second list fixes 727 Bern begin dates that are load timestamps. Sample check: affair number and answer
  heading 40/40; decision date 36/40 (three misses are our parser, one a typo in the canton's PDF). Nightly job with
  alerts and a runbook: `deploy/nightly/`, `docs/runbook.md`.
- **Is a common schema feasible? Partly, and we show where it breaks.** Over 17 fields and 89 parliaments: 4 feasible
  from OPD metadata alone, 13 partial (metadata in some parliaments, only the PDF in others), 0 fundamentally different
  at our thresholds. Availability is not comparability: 42 raw affair-type labels mean different things in different
  parliaments, and "answer date" is at least three dates (decided, dispatched, registered). `docs/census.md`,
  `docs/figures/fig2_matrix.png`, schema v0.1 with typed nulls in `docs/schema.md`.
- **A converter in which Apertus can only point.** Apertus may only choose a date printed in the document, or say null;
  every value carries page and character span. Asked freely instead, it writes an answer date for 15/15 (local 8B) and
  14/15 (70B) documents that have no answer (cited spike).
- **Two pre-registered tests, one answer.** Code, prompts and threshold were frozen by hash before any label existed;
  labels by two blind annotators plus a tie-breaker, no human labels by design, raw annotations committed.
  (1) On 154 documents from the parliaments our rules were written for, rules alone are exact on 135/154 and Apertus adds
  nothing significant (+3.6 points, 95% CI −1.4 to 9.3), so rules run unattended. (2) On 62 documents from 15
  parliaments the rules never saw, the rules find 2/29 answer dates and Apertus finds 24/29 (p = 4.8 × 10⁻⁷). So rules
  serve the layouts someone wrote them for, and Apertus is what extends the converter to parliaments without rules (74 of
  the 89; tested on 15 of them). Because it still puts a date on 4/33 documents that carry no answer, its values arrive as review suggestions for
  OPD's existing review step, with page and span. Results: README "Evaluation", `results/eval/`, `results/eval2/`.
- **Runs anywhere, sovereign by default.** `make run` in Docker on CPU replays every headline and re-derives the rules
  arm from the source PDFs (154/154 identical locally). The default mode needs no model; review mode runs Apertus v1.5
  8B in-process (no document text leaves the machine) or any endpoint the operator chooses. Maturity: census and repair
  deployable prototype; extraction feasibility study. Coding assistants (Claude Code) declared in the README.
