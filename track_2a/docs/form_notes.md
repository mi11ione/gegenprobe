# Form notes (draft for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData. Every number below is recomputed from a results file by `make run` (claims.tsv).

- **Insight: is a common schema feasible?** Field-by-field over 89 parliaments with criteria fixed before computing: 4
  fields feasible from OPD metadata alone, 13 partial (metadata for some parliaments, PDF-only for others), 0 fundamentally
  different by the pre-declared rule; where the concept itself splits (oral answers, question time) is shown separately.
  Matrix: `results/census/matrix.csv`, figure `docs/figures/fig2_matrix.png`, criteria `docs/census.md` §3.
- **A national census of missing government answers, with typed causes.** 16,749 of 91,268 interventions with a
  written-answer event (18.4%) have no answer text in OPD. Decomposed by cause and repair route in
  `docs/figures/fig1_funnel.png` (`results/census/summary.json`, `results/repair/summary.json`); reproduced cell-for-cell
  from the raw exports and replayable from `data/census/` alone.
- **A verified, drop-in repair job.** Bern: only 229 of 3,532 published answers (6.5%) are attached in OPD; deterministic
  joins on the canton's own document uid bring it to 3,394 (96.1%). Relink list in OPD's export layout:
  `results/repair/repair_BE.tsv` (2,459 relink + 49 fetch, byte-identical to the list sent to OPD). Nightly systemd job:
  `deploy/nightly/`, `docs/nightly.md`.
- **The converter Apertus cannot make invent.** Apertus only chooses among values printed in the document, or null, with
  a threshold θ calibrated per build; every value has page and character span (`docs/samples/`). The naive alternative,
  free JSON generation from a plain prompt, gives an answer date for 15/15 (local 8B) and 14/15 (70B) answerless
  documents (`results/convert/spike_replay.json`, `docs/figures/fig4_naive_contrast.png`).
- **Held-out, pre-registered evaluation.** <!-- PLACEHOLDER: held-out numbers (H1–H4), arms rules / pointer / cascade /
  naive, Wilson CIs --> 154 documents, DE/FR/IT × canton/commune + an OCR cell; registration locked before any label
  existed (`eval/prereg/LOCK`, commit timestamp); labels by blind double annotation (`docs/gold_protocol.md`);
  deviations listed in `eval/prereg/DEVIATIONS.md`.
- **Runs anywhere, sovereign by default.** `make run` in Docker on CPU replays every headline; the model is any
  vLLM-style endpoint or Apertus v1.5 8B GGUF in-process (no document text leaves the machine). Runtime services and
  what each receives: README "Sovereignty". Coding assistants (Claude Code) declared; maturity: census/repair deployable
  prototype, extraction feasibility study.
