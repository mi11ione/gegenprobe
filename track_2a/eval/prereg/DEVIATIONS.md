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

## D5 (10 Oct 2026, POST-HOC, found by the round-3 jury): the naive arms' date parser drops DD-MM-YYYY answers
- **Defect in frozen code.** `eval/naive_baseline.py:to_iso` (lines 91-99, LOCK-hashed) accepts ISO dates and whatever
  `lattice.dates` reads. `lattice.dates` does not read `DD-MM-YYYY` or `DD-<month>-YYYY`, so `to_iso` returns
  `unparseable:…`, and `eval/arms.py:169` scores the answer as null. The prompts ask for `JJJJ-MM-TT` / `AAAA-MM-JJ` /
  `AAAA-MM-GG`, and Apertus sometimes answered `19-02-2019` or `25-ottobre-2012` instead. Neither file is changed.
- **Registered result, unchanged:** naive_plain 98/154 and naive_null 134/154 exact (`results/eval/heldout__…json`).
- **Post hoc, re-parsed:** `eval/posthoc_r3.py naive` reads the full stored generations from the committed model cache
  (no model call). It re-parses them with a parser that accepts every form that occurs (ISO, D.M.Y, D-M-Y, D/M/Y,
  D[.] month Y, D-month-Y; DE/FR/IT month names) and re-scores them with the frozen `eval/score.py`. The corrected parser
  returns the registered value on every answer the registered parser could read (94/94 plain, 58/58 null). Five answers
  are still not dates: four say in words that the date is not available, and one gives only a month (`09.2001`). All five
  stay null, as registered. Result: **naive_plain 103/154** (+7 correct; 2 answerless documents now carry a wrong printed
  date; 1 miss becomes a wrong printed date) and **naive_null 133/154** (−1: answerless document 136633 now carries a
  printed date; 868895 goes from missed to wrong printed date). Accepting DD-MM-YYYY alone gives 102/154 for
  naive_plain. Dates printed nowhere in the document (fabricated) are unchanged after the re-parse: naive_plain 24,
  naive_null 0. `results/eval/posthoc_r3_naive_reparsed.json`.
- **Effect on conclusions:** on P1 the null-allowed naive arm stays below the cascade (133 vs 139; paired 7 vs 13 documents,
  McNemar p = 0.26, `results/eval/posthoc_r3_paired.json`). It is now level with the pointer (133 vs 130; 10 vs 7, p = 0.63).

## D6 (10 Oct 2026, POST-HOC, found by the round-3 jury): the H2 Branch-B consequence as registered and as carried out
- **Registered** (PREREG H2): "otherwise **Branch B**: Apertus is kept only where it measurably adds null-safety, and the
  report says so in those words."
- **Result:** Branch B (cascade-only 5 vs rules-only 1 on FR+IT+OCR, p = 0.22). On null safety Apertus adds nothing.
  It removes some. The cascade dates 7 of 90 answerless documents, the rules 2 (the other 5 are Apertus
  values on the rules' residue). By construction the cascade never overrides a rule's value or a rule's null; it only
  fills documents where the rules abstain. So Apertus cannot add null safety on any document: compared with the rules
  alone (abstain → null), it can only add values. Read literally, the consequence keeps Apertus nowhere.
- **What was done:** Apertus was dropped from the unattended path. The shipped default is `rules_only`
  (`convert/modes.py`, `convert/batch.py`, `convert/demo.py`). Apertus stays as an **opt-in review mode**: on documents
  where the rules abstain, its pointer value is attached as a suggestion with `needs_review`, and a person confirms it. The
  registration names no such review use. It was chosen after the P1 result, and P2-H2 (registered later, in PREREG2)
  tested it on unseen parliaments. The report described the outcome as "rules run unattended and Apertus's answers are
  review suggestions", not in the registered words. This entry records the registered words and the departure: Apertus is
  kept as a reviewer aid, not for null safety.

## D7 (10 Oct 2026, POST-HOC, found by the round-3 jury): what the lock clock shows
The LOCK commit precedes the commit that adds the labels in every set. `lock.py write` also refuses to write a LOCK
while a label file exists in the working tree. Gaps between the LOCK commit and the label commit (committer dates,
`git log`; SHAs in `docs/commit-map.md`): P1 6 min 0 s (912bda2 → 6eb4d3b), P2 2 min 28 s (5b044a2 → dbf387e), P3 3 min
37 s (a0e4636 → 7750b6c), P4 4 min 3 s (a0e4636 → 8cf32f9). The annotation files (`data/gold*/annotations/A*.jsonl`)
carry no timestamps. The clock therefore proves that the lock was **committed before the labels were committed**. It
does not prove when annotation started. Agent annotation of a set takes minutes, so the gaps are consistent with
annotating after the lock, but they do not prove it. The correct wording is "frozen before any label was committed".
`results/eval/posthoc_r3_gold_oracle.json` → `lock_to_label_commit`.

## D8 (10 Oct 2026, POST-HOC): tie-break audit and non-LLM checks of the gold
- **Tie-breaks (verifies D4).** A3 chose A1's label in **36 of 41** tie-breaks and A2's in 5. 35 of the 41 differ only in
  the recommendation (34 of them none vs not_applicable). In the 6 that differ in the answer date, A3 chose A1 in 4 and A2
  in 2. In P2, where the X/Y order was randomised, A3 chose A1 in 3 of 7 and A2 in 4; all 7 differed only in the recommendation
  (`results/eval/posthoc_r3_paired.json` → `tie_breaks`).
- **Non-LLM checks** (`eval/posthoc_r3.py oracle` → `results/eval/posthoc_r3_gold_oracle.json`; none was used to set a label).
  Of 64 P1 gold answer dates, 44 can be checked against a non-LLM source and 37 are confirmed exactly. Against
  OPD written-answer events: 37 of 44 agree, 5 are 1-5 days apart (decision vs dispatch or publication), and 2 are further
  apart. In 589850, OPD's event is the motion's deposit date, which is printed in the document; in 19243 the gold is the
  OCR'd letter date and OPD has a date 13 days later. Against publisher titles that name the decision date (Ticino
  "Risposta del CdS del …"): 20 of 20 agree. One BE title names an RRB date on a gold-null document (28271); this is a scope
  call (an executive credit decision, not an answer to a member's affair), on which A1 and A2 disagreed. 20 P1 gold dates
  have no non-LLM source.
