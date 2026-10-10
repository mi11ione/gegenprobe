# Deviations from the pre-registration

Every change to a file listed in `LOCK` after the lock commit (812030f, 2026-10-09T21:38:02+02:00), and every defect found
in frozen code after the lock, is listed here with its effect on the frozen result.

## D1 (found 2026-10-09, after the lock, before any held-out label): OCR cell prompted in German
`eval/arms.py:load_split` sets the prompt language from the OPD `language` field, falling back on the cell prefix
(`it`/`fr`, else `de`). The OCR cell is named `ocr_ti`, and its documents carry no OPD language tag, so the Italian scans of
the Ticino government are scored with the **German** pointer and naive prompts. The same mapping applied to the 5 OCR
documents of the dev θ fit, so θ and the held-out run are consistent with each other.
- **Headline:** the frozen code is run unchanged (German prompt on the OCR cell).
- **Post-hoc, labelled as such:** the OCR cell is re-scored with the Italian prompt and θ unchanged, and both rows are
  reported.

## D2 (2026-10-09, before any 8B run): speed-optimised GGUF scorer for the 8B arms
The frozen `llm.GGUF.score` uses `logits_all=True` and runs at ~7 prompt tokens/s on a 4-vCPU CI runner, too slow for
the dev fit plus 154 held-out documents. `src/gegenprobe/gguf_fast.py` computes the same summed continuation
log-probabilities from last-token logits (same file, rendering, tokens and cache keys). It runs only after a parity gate
against the frozen scorer on CI (max |Δ| ≤ 0.5 nats, `out/gguf_fast_parity.json`). The pre-registered implementation check
(`gegenprobe.gguf_check impl`, 60 cells vs bf16) passed its condition: llama-cpp-python agrees with bf16 on 58/60
decisions (mean |Δ| 2.66 nats), as close as or closer than the spike's Metal build (57/60, 2.87).

## D3 (2026-10-09, before any 8B run): 8B arms run on the CI runner's text extraction and without the spike dev items
- The 30 spike dev items have no texts in the repository (full texts are never committed), so the 8B θ is fitted on the 97
  sampler dev documents only; the 70B θ used all 127.
- The runner extracts text with Ubuntu 24.04's poppler and tesseract, not the macOS builds the 70B arm and the labels used,
  so 8B inputs can differ in whitespace and OCR noise; labels are ISO dates, which these differences rarely move.
- 8B arms: rules, pointer, cascade on `answer_date`. The exploratory recommendation and naive arms are not run on 8B
  (runner minutes); the naive 8B contrast is cited from round 7 (local 8B, 15/15 invented).
- D2 addendum: the first parity gate (CI run 37992237668) FAILED (max |Δ| 57.8 nats): the fast scorer read an unfilled
  `scores` row (uniform logits, −11.79 = log 1/131,272 for every token). Fixed to read the context's last-token logits with
  a flat-row guard; no 8B arm had run. The gate is re-run unchanged.
- D2 addendum 2: the re-run gate (CI run 37994205470) FAILED again at its 0.5-nat threshold (max |Δ| 4.47 nats). All 24
  single-token values now match the frozen scorer exactly (Δ = 0.00); only the 3-token continuation differs (0.6–4.5
  nats on a −90-nat continuation), because the fast scorer feeds continuation tokens one at a time while the frozen scorer
  evaluates them as one batch, which takes a different llama.cpp CPU kernel path. The threshold is NOT relaxed. Instead,
  before any 8B arm runs, both scorers are compared against the bf16 reference on 30 multi-token verdict cells
  (`gguf_fast verparity`, fixture `tests/fixtures/gguf_ver30.json`, seed 20261010). Rule fixed now: the fast scorer is
  used iff its decision agreement with bf16 ≥ frozen − 1 and its mean |Δ| vs bf16 ≤ frozen + 0.5 nats; otherwise the 8B
  arms are reported as not run.
- D3 addendum (2026-10-10): GitHub Actions minutes for the then-private repository ran out and its 2-vCPU/8 GB runners
  were killed by memory pressure; the repository was made public (4 vCPU/16 GB runners). Some cantonal/communal PDF hosts
  do not answer CI runner IPs; such documents are skipped in the 8B arms and listed in
  `results/eval/shards/unreachable_{dev,heldout}.json`, so the 8B arms are evaluated on the reachable subset (n reported).

## D4 (2026-10-10, found by the round-1 jury review after the frozen result; no result changes)
- **Stale sentence in a locked file.** `data/gold/README.md:43` (LOCK-hashed) still says "Roman adjudicates every
  disagreement". The protocol was changed to no human labels or adjudication before any held-out label existed
  (`docs/gold_protocol.md`, PREREG "Labels", commit 812030f); the README sentence was not updated before the lock and is
  left unchanged so the lock stays verifiable. No human labelled or adjudicated any held-out document.
- **H3 population.** PREREG H3 names "the length-matched held-out set"; `eval/hypotheses.py` computed it on all
  documents, including the OCR cell, which is not length-matched. Without the OCR cell the AUROC is 0.972 (frozen: 0.969;
  `results/eval/robustness.json` → `h3_excluding_ocr_cell`). Passes either way.
- **Text extraction not hashed.** `src/gegenprobe/pdftext.py` (and `net.py`) are not in the LOCK file list. Neither has
  changed since the lock (`git log 812030f..HEAD` is empty for both files); every held-out document records its extractor
  and version (`data/gold/heldout_docs.jsonl` → `extractor`).
- **`eval/hypotheses.py` written after the labels** (first committed in bc66dd9, 2026-10-10T00:41, after the labels in
  ded0033). It computes H1–H4 exactly as worded in PREREG; the only later change (da6e69c) is formatting — the file is
  identical to bc66dd9 modulo whitespace and trailing commas (checked by code).
- **Tie-break order not randomised.** A3 always saw A1's label as "X" and A2's as "Y"; A3 chose A1's label in 36 of 41
  tie-breaks (34 of the 41 differ only in recommendation, none vs not_applicable). Any further tie-break randomises the order.

## D4 corrections (2026-10-10, found by the round-2 jury review)
- **Correction to "Text extraction not hashed".** The D4 sentence "Neither has changed since the lock" is wrong for
  `src/gegenprobe/pdftext.py`: commit 7dd269b (2026-10-10T09:40) changed it. The diff touches only `fetch_pdf` (typed
  `FetchError` for not-a-PDF and sha mismatch, configurable timeout/tries); `extract`, `_pdftotext_pages` and `_ocr_pages`
  are byte-identical, so no extracted text and no held-out result changes (the rules arm re-derived from source PDFs after
  the change still matches 154/154, `results/eval/rederive_local.json`). `net.py` is unchanged since the lock. LOCK2–LOCK4
  hash the post-7dd269b version.
- **Correction to "H3 population".** The registered population is the length-matched set (1,000–2,000 estimated tokens),
  not "all documents except the OCR cell" as D4 substituted. On the registered population the AUROC is **0.966**
  (68 gold-null vs 57 gold-value documents with candidates; `results/eval/baselines_dates.json` →
  `P1_H3_length_matched`, written by `eval/baselines.py`). H3 passes on every population (all 0.969; without OCR 0.972;
  length-matched 0.966).
