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
  workaround. A second list fixes 727 Bern begin dates that are load timestamps. Every relink was checked against
  OPD's own copy: affair number and answer heading 2,459/2,459, decision date = OPD's event 2,421 (the rest go to
  review). Nightly job with alerts and a runbook: `deploy/nightly/`, `docs/runbook.md`.
- **Is a common schema feasible? Partly, and we show where it breaks.** Over 17 fields and 89 parliaments: 4 feasible
  from OPD metadata alone, 13 partial (metadata in some parliaments, only the PDF in others), 0 fundamentally different
  at our thresholds. Availability is not comparability: 42 raw affair-type labels mean different things in different
  parliaments, and "answer date" is at least three dates (decided, dispatched, registered). `docs/census.md`,
  `docs/figures/fig2_matrix.png`, schema v0.1 with typed nulls in `docs/schema.md`.
- **A converter in which Apertus can only point.** Apertus may only choose a date printed in the document, or say null;
  every value carries page and character span. Asked freely instead, it writes an answer date for 15/15 (local 8B) and
  14/15 (70B) documents that have no answer (cited spike).
- **Four pre-registered tests show where Apertus earns its place.** Code, prompts and threshold were frozen by hash
  before any label existed; labels by two blind annotators plus a tie-breaker, no human labels by design, raw
  annotations committed. (1) On 154 documents from parliaments our rules were written for, rules alone are exact on
  135/154 and Apertus adds nothing significant (+3.6 points, 95% CI −1.4 to 9.3), so rules run unattended. (2) On 62
  documents from 15 parliaments the rules never saw, the rules find 2/29 answer dates and Apertus finds 24/29
  (p = 4.8 × 10⁻⁷). Because it still dates 4/33 documents without an answer, its values are review suggestions with page
  and span for OPD's existing review step. Results: `results/eval/`, `results/eval2/`.
- **Whole affairs, not one field.** (3) On 29 affairs from 10 parliaments in German, French and Italian, metadata plus
  rules get type 27/29, submitter 23/29 and answer date 22/27; Apertus suggestions add the addressed body (4/28 → 23/28)
  and complete the answer dates (27/27). No field is reliable enough to run unattended yet; that is stated, field by
  field, with confidence intervals. `docs/affair.md`, `results/eval3/`.
- **Virtual affairs from minutes, as OPD asked.** (4) For Bulle, whose council business exists in OPD only as meeting
  documents, rules turn 6 held-out sittings into 99 affairs (precision 99/99, every title right, decision found for
  49/63 items, invented for none). Rules suffice there; Apertus is not needed. `docs/virtual-affairs.md`, `results/eval4/`.
- **Runs anywhere, sovereign by default.** `make run` in Docker on CPU replays every headline and re-derives the rules
  arm from the source PDFs (154/154 identical locally). The default mode needs no model; review mode runs Apertus v1.5
  8B in-process (no document text leaves the machine) or any endpoint the operator chooses. Maturity: census and repair
  deployable prototype; extraction feasibility study. Coding assistants (Claude Code) declared in the README.
