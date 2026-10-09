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
