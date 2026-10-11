# P6 deviations and run notes (after LOCK7, dfd1e72)

## N1 (10 Oct 2026, 23:4x): the draw, by the registered rule (no deviation)
`python -m eval.p6.sample draw` after the LOCK7 commit gave **68 of 77 documents from 8 of 9 parliaments** (≥ 60: not
flagged underpowered). Replacements and shortfalls followed PREREG7 and are logged in `data/p6/p6_fetch_log.jsonl`:
- **Val de Bagnes (6037): 0 of 8.** Its host did not answer from this machine at draw time (robots.txt unreachable,
  fail-closed in `gegenprobe.net`, 54 candidates tried). It had answered a probe hours earlier.
- **Conthey (6023): answers 4 of 5.** 23 answer PDFs extracted to 0 characters (pdftotext and OCR) and were replaced by the
  next candidate, as registered, until the pool was exhausted.
- Zug city: 4 HTTP 404 replaced; Lyss: 1 non-PDF replaced.
Result: 55 German, 13 French documents; 44 answer-typed, 24 intervention-typed (strata by metadata; labels decide).
Packets: `.work/p6/packets/` (68). No label existed at draw time.

## N2 (10 Oct 2026, 23:50): one response refused by the served-model check (no effect on results)
During the first run of `eval.p6.run_p6`, one response to a request for `swiss-ai/apertus-v1.5-8b` carried the model
field `swiss-ai/Apertus-v1.5-70B`. `llm._Remote._check` raised `ServedModelMismatch` and the response was not cached; the
run stopped. Two probes a minute later (one generation, one prefill) returned `swiss-ai/apertus-v1.5-8b` with the usual
fingerprint `vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840`. The runner was started again unchanged: cached
responses replay, and only responses that pass the check are stored. Every P6 cache entry carries the model field and
fingerprint above (`results/p6/p6__publicai_swiss-ai_apertus-v1.5-8b.json` → `served_fingerprints`, re-derived from the
cache in `results/p6/p6_served.json`).

## N3 (10/11 Oct 2026, annotation; reported, no change to labels)
Annotation ran in four blind sessions (A1 Opus ×2, A2 Sonnet ×2, 34 documents each) and one A3 (Opus) tie-break on the single
disputed document (329356, decided 'no answer'). One A2 session reported two slips: it saw the file names and first five lines
(no labels) of an A1 helper script in a scratch directory shared between sessions, and a directory listing of the A2 folder
showed summary fields of the other A2 session's files (same annotator role, not A1). It labelled its own 34 documents from its
own notes. A1 and A2 disagreed on 1 of 68 documents.

## D1 (11 Oct 2026, post hoc): candidate C's code was committed after the DEV2 labels
Order of the commits, with GitHub's server time of each push (`results/eval/annotation_sessions.json`):
- **6810ee5** (pushed 21:16:30 UTC, 10 Oct): the selection rule as prose (`eval/p6/DEV2_SELECTION.md`, candidates A, B, C
  described), the DEV2 draw, `pointer_v2.py` with the presence gate and role pick (candidates A and B) and the guided
  free-generation call (`pointer_v2.guided`), and `eval/p6/dev.py` with its dev scoring (`pick_guided`) but no `select()`.
- **854bb3d** (pushed 21:18:15 UTC): the DEV2 labels. The two annotator sessions ran 21:16:56–21:18:06 UTC (transcripts).
- **dfd1e72** (pushed 21:37:32 UTC, LOCK7): the first commit of candidate C's code (`pointer_v2.generate_then_point`:
  reading the generated date, keeping it only if it is printed, else falling back to the role pick; the `gen_then_role`
  configuration), of `dev.select()`, of `results/p6/dev2_selection.json` and of `data/p6/v2_config.json`.

So only the rule's wording, not C's implementation, provably preceded the DEV2 labels. The commit message of dfd1e72
("candidate C chosen on DEV2 by the rule committed in 6810ee5") is true of the rule, not of the code. The gateway ledger
shows 3,404 of the 3,439 model calls tagged for DEV2 development before the 6810ee5 push and 35 between 21:34 and 21:50
UTC, after the DEV2 labels; the ledger does not record which candidate those 35 served.

C won DEV2 with 29 of 31 documents correct, against 28 for v1 (a comparison arm, not a candidate), 27 for B and 26 for A.
Wilson 95% intervals: C [0.79, 0.98], v1 [0.75, 0.97], B [0.71, 0.95], A [0.67, 0.93]. A gap of one or two documents out
of 31 is within noise.

What it means:
- DEV2 does not show that C is better than A or B. It shows only that C was not worse on 31 documents. The choice of C
  rests on the written rule's tie-free ranking of three nearly equal candidates, and C's code could have been adjusted
  after the labels existed. Nothing in the repository rules this out.
- P6 is unaffected as a test of the frozen v2. LOCK7 (dfd1e72) hashes `pointer_v2.py` and `v2_config.json`, and the P6
  draw (6faf8ac, 21:56:39 UTC) and the P6 labels (75167ac, 21:59:32 UTC) came after it. P6 found no advantage for v2: 59/68
  against 62/68 for free prompting with null allowed, and 56/68 for v1.
- Any claim that v2 was "chosen blind on DEV2" should read: "chosen by a rule written before the DEV2 labels; the
  chosen candidate's code was committed after them".

## D2 (11 Oct 2026, post hoc) — context length of the exploratory 8B run on P6
The 8B run on P6 (CI run 38089554021, dispatched 2026-10-10T21:56:50Z) used the fast scorer (GGUFFast, n_ctx = 6144). Of its
232 scoring prompts, 3 exceed 4,096 tokens (max 4,673): every call fit the context it ran with, but those 3 would not fit the
frozen 4,096-token scorer, so the P6 8B numbers are fast-scorer results only (`results/eval/posthoc_r4_eval.json`,
`gguf_cache_n_ctx_p6`). The P1/P2 8B finding (302 entries, max 4,079 tokens, all within 4,096) is unchanged.

## D3 (11 Oct 2026, post hoc) — the "no answer at all" split of the answerless documents
The README's "of the 53 documents with no answer at all, Apertus dated 0" uses a split defined on 11 Oct 2026, after the
P6 results were known (`report/r7docs_numbers.py`). PREREG7 does not register it; H2 (v2 dates 5/34 answerless documents,
Wilson upper bound 30.1% > 15%, and more than free_null's 4) failed as registered and still fails.
Definition (from `data/p6/p6_labels.jsonl`): of the 34 answerless documents (gold `answer_date` null), 28 have no answer at
all (`answer_present` = no: 25, oral: 3) and 6 contain an answer that prints no qualifying date (`answer_present` = yes).
70B: v2 dates 0 of the 28 and 5 of the 6; free_null 1 of the 28, free_guided 1, free_plain 8. With P2 (DEVIATIONS2 D2-8):
0 of 53 [Wilson 0, 6.8%], and the 9 dates the two arms put on answerless documents are all wrong under the registered scorer.
8B (exploratory): v2 1 of 28, v1 13, free_null 6, free_guided 1. `results/eval/posthoc_r8_noanswer.json`.
