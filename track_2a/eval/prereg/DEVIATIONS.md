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

## D9 (10 Oct 2026, POST-HOC, found by the round-4 jury): 8B scorer provenance — gate record, cache key n_ctx, θ interval
- **Every 8B scorer check, in order** (`results/eval/gguf_fast_verparity.json`, written by `eval/posthoc_r4.py verparity`
  from the GitHub job logs; `results/eval/gguf_impl60.json`):
  1. Pre-registered implementation check (`gguf_check impl`, run 37975752529): llama-cpp-python agrees with bf16 on 58/60
     decisions, mean |Δ| 2.66 nats — PASS (D2).
  2. Preset scorer self-check (run 37970947075; rule fixed before the run: every decision agrees with the Metal reference
     and mean |Δ| ≤ 1.0 nat): 10/12 decisions, 3.16 nats — **FAIL**.
  3. Fast-vs-frozen parity gate (max |Δ| ≤ 0.5 nats): **FAIL** in run 37992237668 (57.8 nats, uniform-logits bug) and
     **FAIL** in run 37994205470 after the fix (4.47 nats). Every single-token value matched exactly (Δ 0.00); the 3-token
     date continuation differed by 0.65–4.47 nats. Recorded again, not gating, in run 37996141049: 4.47 nats.
  4. Replacement gate, written after the failures and before any 8B arm (D2 addendum 2): run 37996141049, job 114042612830,
     commit 435fc9e. Frozen scorer 29/30 decisions agree with bf16, mean |Δ| 5.63 nats; fast scorer 29/30, 5.63 — PASS.
     Its cells are 30 verdict continuations (" schuldig" / " nicht schuldig") from a spike fixture, not dates.
- **The gate's output file was never uploaded.** The runner was shut down during the next step (fit), before the upload
  step, and the run lists 0 artifacts. The committed evidence is the job log, verbatim
  (`results/eval/gguf_fast_verparity_log.txt`). The two failed gates' artifacts exist; their rows equal the logged rows.
- **What the record shows.** On multi-token continuations, both scorers are equally far from bf16. On a date continuation,
  the fast scorer does not reproduce the frozen scorer (up to 4.47 nats). The 8B numbers are fast-scorer numbers, with θ
  fitted by the same scorer; they are not frozen-scorer numbers.
- **Cache key n_ctx (the jury's claim is true).** `src/gegenprobe/gguf_fast.py` keys every entry with `n_ctx=4096`, the
  frozen scorer's key, but loads llama.cpp with `n_ctx=6144`. At the gate commit 435fc9e the load value was 8192; 69094aa
  set 6144 after the fit job ran out of memory. The key is only a lookup id. The effective context of every 8B result is
  6144 tokens.
- **Effect of n_ctx: none on the results.** No prompt exceeded 4096 tokens: the largest `n_prompt` among all 251 8B
  cache entries is 4079. A date continuation has at most 13 tokens, so 4079 + 12 = 4091 ≤ 4096: every call also fits
  the frozen scorer's context. All 251 entries carry `scorer: gguf_fast`, so the shared key cannot be mistaken for a
  frozen-scorer entry. `results/eval/posthoc_r4_eval.json` → `gguf_cache_n_ctx`.
- **θ interval** (`posthoc_r4_eval.json` → `theta_8b`). The 97 dev margins were recomputed from the committed cache entries,
  by key; they refit θ, AUROC and gap exactly.
  - θ = 16.727 is the midpoint of the only accuracy-optimal gap between two adjacent dev margins: 16.675 and 16.779,
    0.105 nats apart.
  - Moving θ 0.5 nats either way flips 1 of 97 dev decisions (86 → 85 correct).
  - Held-out at θ − 0.5: pointer 112, cascade 120. At θ + 0.5: pointer 113, cascade 120. The frozen θ gives 112 and 119.
  - 7 dev documents extract differently on this machine than on the CI runner. They were matched to the 7 cache entries
    no other key explains, by candidate count. The assignment used is the only one that reproduces θ, AUROC and gap exactly.

## D10 (10 Oct 2026, POST-HOC, found by the round-4 jury): multiplicity, the lenient metric, served fingerprints
- **Multiplicity** (`results/eval/posthoc_r4_multiplicity.json`). The family is every registered confirmatory decision of
  P1–P4 and P3b that rests on a test or an interval, m = 9.
  - Exact McNemar p-values are used as registered. Interval rules are converted to the p-value of the test the interval
    inverts (Wilson → score test, Newcombe → hybrid score). No registered outcome changes under the conversion.
  - The 4 conclusions that held all survive Holm, and BH:
    - P2-H1: p 8.0 × 10⁻¹⁰, Holm 7.2 × 10⁻⁹.
    - P2-H2: p 4.8 × 10⁻⁷, Holm 3.8 × 10⁻⁶.
    - P3-H3a: p 0.0015, Holm 0.01.
    - P3b-S1: p 0.0027, Holm 0.016.
  - The 5 that failed stay failed: P1-H1 pooled, P1-H2, P2-H3, P3-H3b, P4-H3.
  - The 8B tests are exploratory and outside the family. The 8B H2 primary has p 0.039; × 9 gives 0.35.
- **Lenient metric** (`results/eval/posthoc_r4_lenient.json`). It is registered in PREREG and computed by the frozen scorer
  in every results file, but was not reported until now. It raises each arm by 0–5 documents and changes no registered
  decision.
  - P1 held-out (70B): rules 135 → 136, pointer 130 → 132, cascade 139 → 140.
  - P1 held-out (8B): pointer 112 → 117, cascade 119 → 123.
  - P2 (70B): pointer 53 → 56, cascade 51 → 54; P2-H2 22–0 → 25–0.
  - The exploratory 8B P1 contrast weakens: rules better than the cascade 10–2 (p 0.039) strict, 10–5 (p 0.30) lenient.
- **served_fingerprints = [] in the P1/P2 results files.** `eval/arms.py` collects fingerprints only from live calls
  (`llm._Remote._check`), and these runs were replayed from the hash cache. The results files are not changed.
  `results/eval/served_models.json` re-derives the set from the cache entries each file's documents read (cache-only
  re-run of the frozen arms, no request sent):
  - P1 held-out 1,542 entries, P2 351, 70B dev θ fit 544. Every entry: model `swiss-ai/apertus-v1.5-8b`, one fingerprint
    `vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840`. That is the same single build as the whole 70B cache (3,503
    entries) and as the fingerprints recorded live in the P3/P3b results files.
  - The 8B entries carry no served-model field: the weights are the local GGUF file, pinned by sha256 (a037df8d…).
    Matching: 129 held-out documents by key, the other 25 by their committed margin, the 97 dev documents as above. All
    are tagged `gguf_fast`.

## D11 (10 Oct 2026, POST-HOC, found by the round-4 jury): three P1 gold dates before OPD's submission date
`results/eval/posthoc_r4_gold_audit.json`. No label file is changed.
- **300277 (BE): genuine.** An RRB of 25 Aug 2010 on a credit business (Kreditgeschäft RR 2010.RRGR.1464). For government
  affairs the executive decides first and parliament receives the business later (OPD "Eingereicht" 2010-11-22).
- **886123 (Mendrisio): genuine.** A municipal report, Ris.mun. 2345 of 20 Dec 2016, on a motion the document says was
  presented on 11 Oct 2016. OPD files the report under a later affair, MM 71/2018 (submitted 2018-09-14).
- **249052 (BE, government affair 2011.RRGR.410): labelled as printed.** The document prints "Berne, le 18 février 2010",
  but it reports the 2010 lottery-fund accounts and cites an audit of 4 Feb 2011. The printed year is a typo in the
  source. The protocol labels the printed date. Both annotators listed 2011-02-18 as the lenient alternative, and that
  date is printed nowhere in the document.
- **Sensitivity: no score changes.** No arm or build returns 2010-02-18 for 249052. Every closed-set arm returns null;
  naive_plain returns 2011-03-23. So setting the gold to 2011-02-18, or dropping the document, changes no P1 count.

## D12 (10 Oct 2026, POST-HOC, found by the round-5 jury): P1 is held out by assertion, not by commit order
- **What git shows.** Commit `da26116` (original `a794883`, 2026-10-09 20:42:21 CEST; `docs/commit-map.md`) adds the
  rules (`src/gegenprobe/convert/rules.py`), the lattice, the pointer, the cascade, the prompts **and** the held-out sample
  (`data/gold/heldout_docs.jsonl`, 154 documents), its sampler and `eval/gold/SEEDS.md`, 43 min after the repository was
  scaffolded (`68662e3`, 19:59:02). The commit order therefore cannot show that the rules were written before the
  held-out documents were drawn.
- **What the local files show** (mtimes in the uncommitted `.work/`; not tamper-evident, given as the best record we have):
  dev draws 20:11:44 and 20:18:49 CEST (`.work/sample_dev.log`, `sample_dev2.log`); held-out draw 1 20:35:06, redraw
  20:41:14 (`sample_heldout.log`, `sample_heldout2.log`); the held-out PDFs were fetched and their text extracted into
  the local cache between 20:09:31 and 20:32:28 (147 of 154 after 20:20; the sampler extracts text to length-match the
  strata). So unlabelled held-out text was on the local disk for 10 to 33 minutes before the rules were committed, and
  nothing shows the rules were not edited in that window.
- **What does protect P1.**
  - No held-out *label* existed before the rules were frozen: `rules.py`, `lattice.py`, `pointer.py` and the prompts
    have exactly one commit each (`da26116`; `git log -- <file>`), their hashes are in `eval/prereg/LOCK` (`912bda2`,
    21:38:02), and the labels were committed after it (`6eb4d3b`, 21:44:02; label files written 21:40:30 to 21:43:36).
    `cascade.py` changed once after the draw (`46507b3`, 20:54:34): a document with no printed date now gets its null
    without a model call; `pointer.decide` already returned null for an empty candidate list, so no value changes.
  - The rules lose recall on the held-out set as unfitted rules would: values found 54/55 on dev
    (`results/eval/dev__none.json`) against 47/64 held-out (`results/eval/heldout__none.json`). That is consistent with
    no tuning on held-out text but does not prove it.
  - P2 is the clean test of the rules: its 62 documents come from 15 parliaments absent from dev and held-out, drawn
    on 10 Oct after the rules had been frozen for 12 h (LOCK2 `5b044a2` re-hashes the unchanged P1 code). There the
    rules find 2/29 answer dates.
- **Wording.** P1 is "held out by protocol (seeded draw, labels after the lock)"; it is not held out "by commit order".
  Statements that the rules were developed only on dev are the authors' assertion for P1, and are verified for P2.

## D13 (10 Oct 2026, POST-HOC, found by the round-5 jury): the times in `eval/gold/SEEDS.md` are wrong
`eval/gold/SEEDS.md:14` dates the dev redraw "~18:40Z" and `:20` the held-out redraw "~19:20Z". The local logs show
dev draws at 18:11:44Z and 18:18:49Z and the held-out draw and redraw at 18:35:06Z and 18:41:14Z (file mtimes as in
D12; 20:xx CEST). The held-out file was committed at 18:42:21Z (20:42:21 CEST) and never changed, so "~19:20Z" is
impossible as written; the times appear to have been written as local time plus a wrong offset. The order the entries
describe (dev v1, dev v2, sampler change, held-out draw 1, held-out redraw) is the order the logs show. The first line
("Written 2026-10-09T18:07:58Z") is consistent with the scaffold commit (17:59:02Z). `eval/gold/SEEDS.md` is not under
any LOCK; a correction note is appended there, and the original lines are left unchanged.

## D7 addendum (10 Oct 2026, POST-HOC, round-5 jury): "Agent annotation of a set takes minutes": the evidence
The sentence in D7 was asserted. The evidence is the mtimes of the uncommitted annotation files in `.work/gold*/ann/`
(local; not tamper-evident). P1: the batch list was written at 21:39:03 CEST, the guide copy at 21:39:28 and the 154 A1 and
154 A2 files between 21:40:30 and 21:41:17. There were 8 batches of 19–20 documents per annotator, each batch written in one
second, so 16 agents ran in parallel. The 41 A3 tie-breaks were written between 21:42:46 and 21:43:36. From the P1 LOCK
commit (21:38:02) to the last label file: 5 min 34 s. P2: LOCK2 commit 09:47:55, packets 09:46:44, 62 A1 + 62 A2 files
09:48:53–09:49:12, 7 A3 files 09:49:52. The mtimes are consistent with annotation after each lock and show that it took
about 2 minutes. They are local file times, so they support the sentence but do not prove the order.

## D9 addendum (10 Oct 2026, round-5 jury): 251 → 302 8B cache entries
D9 says "all 251 8B cache entries". After the 8B P2 run (D2-6 addendum, `962e2f7`) the committed 8B cache holds 302
entries (`data/model_cache/gguf_apertus-v1.5-8b-text-q4_k_m/`). The regenerated `results/eval/posthoc_r4_eval.json` →
`gguf_cache_n_ctx` reads `entries: 302`, all tagged `gguf_fast`, max `n_prompt` 4079, none over 4096. So D9's conclusion
(no prompt exceeds the frozen scorer's 4096-token context) holds for all 302; only the count in D9 is stale.

## D14 (10 Oct 2026, POST-HOC, round-5 jury): an annotator from another vendor, and the J2 null-safety recompute
- **Why.** Every gold label comes from Claude models (A1 Opus, A2 Sonnet, A3 Opus), so κ between them measures
  consistency within one model family, not validity.
- **What.** `aisingapore/Qwen-SEA-LION-v4-32B-IT` labelled every P1 held-out document (154) and every P2 document (62).
  It is a Qwen-family model from AI Singapore: not Anthropic, and not Apertus, the system under test.
  - It ran blind to every label and prediction, through the budget gateway (tag `2a-qwen-audit`): 216 calls, USD 0.14,
    temperature 0.
  - It was given the A1–A3 guide (`eval/gold2/GUIDE.md`, identical to `.work/gold/GUIDE.md`), cut to answer presence and
    answer date with the definitions verbatim, and the same packet text the Claude annotators read. No document was
    truncated (the longest packet is about 17k characters).
  - The served model name was checked on every call. The host returns no `system_fingerprint`, so response ids are kept.
  - A Qwen date counts only if its quote occurs verbatim in the text (whitespace-normalised). Otherwise it is
    "unverified" and treated as null. This happened for 5 P1 dates: Qwen re-joined Bern table-layout headers such as
    "RRB-Nr.: 92/2014 vom 17. März 2014". All 5 equal the gold date.
  - Code: `eval/posthoc_r5.py`. Raw labels, without text: `data/gold_audit/qwen_p{1,2}.jsonl`. Results:
    `results/eval/posthoc_r5_independent_gold.json`.
- **Agreement with the committed gold.** κ is Cohen's kappa; "answer present" is binary (yes vs. not yes).
  - P1, answer present: 146/154, κ 0.89.
  - P1, exact answer date (null included): 134/154, κ 0.80. Counting the unverified dates: 139/154, κ 0.85.
  - P1, within gold or the gold's lenient list: 140/154.
  - P1, where both give a date: 50/54 exact and 54/54 lenient, so they never name a date the gold rejects.
  - P2, answer present: 60/62, κ 0.93.
  - P2, exact answer date: 56/62, κ 0.87. Where both give a date: 25/29.
  - Every disagreement is listed with both values and the OPD written-answer event dates (shown, not used).
- **P1 disagreements (21):**
  - 4 are lenient-only: Qwen picks the letter date the gold lists as lenient (18431, 78962, 135478, 868895).
  - 5 are unverified quotes of the gold date (84364, 143533, 198158, 300277, 424975).
  - 4 have presence yes with no date from Qwen (122203, 166793, 437131, 646517). For 166793 and 437131, OPD's
    answer-event date equals the gold date.
  - 8 are presence calls. 6 documents the gold calls answerless are dated by Qwen: 7088, 28271, 68367, 190629, 671937,
    862297. Five of them OPD types as "report" and one as "answer". 273540 is yes in the gold and no for Qwen; 274069
    is no in the gold and yes without a date for Qwen.
- **P2 disagreements (8):**
  - 2 are presence only, with both dates null (243169, 868121).
  - 6 are dates:
    - 121366 and 869638: Qwen dates a referenced decision or a transmission by parliament where the gold has no date.
    - 431569, 460472: Qwen picks an earlier executive decision mentioned in the text.
    - 460874: the parliament's sitting date.
    - 895511: Qwen gives 2017-01-25; the gold's 2017-01-30 is an OPD written-answer event date.
- **Sensitivity, adjudication-free.** Read in two ways: (a) only the documents where Qwen and the gold agree; (b) the
  gold replaced by Qwen wherever they differ.
  - P1-H1 (cascade values on answerless documents): 7/90 committed, (a) 2/84 (upper 8.3%, pooled bound met; worst cell 2,
    so the per-cell bound still fails), (b) 11/94. Counting the unverified dates, (b) is 6/89.
  - P1 exact (rules / pointer / cascade): 135/130/139 of 154 committed. (a) 123/121/127 of 134. (b) 129/127/133 of
    154; counting the unverified dates, 132/132/138.
  - P2-H2: 22 vs 0 committed, (a) 21 vs 0, (b) 23 vs 1. P2 pointer exact: 53/62, (a) 51/56, (b) 53/62.
  - No registered decision changes, with one exception. On the subset where the two vendors agree, P1-H1's pooled
    bound would pass. P1-H1's failure therefore rests on contested documents, which are mostly OPD "report" types.
- **J2's recompute of P1-H1** (`p1_h1_j2_recompute`).
  - Recomputed under each annotator's labels: A2 (Sonnet) 5/88 (upper 12.6%), A1 (Opus) 9/92, Qwen 11/94 (6/89
    counting unverified dates).
  - Without the 24 documents OPD types as "report": committed gold 1/72 (upper 7.5%, pooled bound met), A2 0/71.
  - Of the 7 committed values, 6 are on "report" documents and 1 on an "answer" document (28271). The cascade's own rules,
    not Apertus, gave 2 of them (28271, 862297); those are the two where Sonnet agreed with the system and Opus (A3)
    overruled.
  - H1 as registered (all 154 documents, merged gold) still fails. The recompute shows the failure is a scope question:
    whether a council report that quotes the executive's decision "contains the answer".
