# Deviations from PREREG2 (unseen parliaments)

PREREG2.md and LOCK2 are frozen (commit 3dde418, before the P2 labels in 2e4a9d6). Later changes and post-hoc analyses:

## D2-1 Unit of the primary test (found by the round-2 jury)
P2-H2 is registered as an exact McNemar test on documents (22 pointer-only vs 0 rules-only, p = 4.8 × 10⁻⁷). The 29
gold-value documents are nested in 7 parliaments (VD alone contributes 8), so documents are not independent. POST-HOC, at
the parliament level: 6 parliaments favour the pointer, 0 favour the rules, 1 has no discordant pair; two-sided sign test
p = 0.031, and an exact cluster permutation test (all 64 joint flips of a parliament's documents) p = 0.031, the smallest
value 6 clusters allow (`results/eval2/body_level.json`, `eval/body_level.py`). The registered result stands; the honest
headline p-value is the parliament-level one.

## D2-2 Trivial baselines (POST-HOC, asked for by the round-2 jury)
On P2, "latest printed date" finds 22/29 answer dates but also puts a date on 31/33 answerless documents (exact 24/62);
gated by OPD's document type (null for member texts) it is exact on 44/62. The pointer is exact on 53/62 (24/29 dates,
4/33 answerless) (`results/eval/baselines_dates.json`). The registered comparison was pointer vs rules; these baselines
show the margin over the strongest one-line alternative (53 vs 44).

## D2-3 Naive arms
PREREG2 lists `naive_null`; the frozen runner (`eval.arms.run`, arm `naive`) also produced `naive_plain` on the same
documents. Both are reported; no decision is attached to either.

## D2-4 Naive arms: the frozen date parser drops DD-MM-YYYY answers (10 Oct 2026, POST-HOC, found by the round-3 jury)
The same defect as P1 D5: `eval/naive_baseline.py:to_iso` (LOCK-hashed) does not read `DD-MM-YYYY`, and
`eval/arms.py:169` scores such answers as null. **Registered:** naive_null 52/62, naive_plain 45/62. **Re-parsed**
(`eval/posthoc_r3.py naive`, full generations from the committed model cache, frozen scorer): **naive_null 54/62**
(52151 and 111796, both `01-11-2023`, become correct) and **naive_plain 49/62** (4 become correct, 1 miss becomes a wrong
printed date). Fabricated dates after the re-parse: naive_null 1 (869606, an answerless document), naive_plain 4.
`results/eval/posthoc_r3_naive_reparsed.json`. **Effect:** with a fair parser the null-allowed naive prompt is level
with the pointer on P2. It is right on 54 documents to the pointer's 53. The discordant documents are 1 vs 0 (p = 1), and
on the 29 answered documents both are right on the same 24. At θ = 0 (PREREG2's registered secondary) the pointer is
right on exactly the same 54 documents as re-parsed naive_null. The pointer's P2 case is therefore not accuracy against
the naive prompt. It rests on three things. Every pointer value is a printed candidate with a page and character span:
32 of 32 values printed, against naive_null's 31 of 32, with 1 fabricated. Naive_null gives a verbatim quote containing
the date for only 17 of its 32 values. A quote check would pass 3 of its 8 wrong values.
`results/eval/posthoc_r3_paired.json` → `provenance`.

## D2-5 Scope of the registered test, strongest baselines, θ = 0 (10 Oct 2026, POST-HOC, round-3 jury)
- **Registered population.** P2-H2 counts discordant pairs on the **29 answered documents** (22 pointer-only vs 0
  rules-only). On **all 62** documents the pointer alone is right on 22 and the rules alone on 4 (the pointer dates 4
  answerless documents the rules leave null); McNemar p = 5.3 × 10⁻⁴.
- **Where the 29 answer dates come from.** The 29 gold answer dates come from **7 of the 15** unseen parliaments (VD 8,
  NW 6, Bellinzona 5, OW 4, Vernier 3, SZ 2, Schlieren 1). The other 8 bodies contribute only answerless documents.
  "15 parliaments" describes the sample, not where the answer dates come from.
- **Strongest one-line baseline, paired** (latest printed date, null on documents OPD types as member texts; on P2
  identical to "only on documents typed as answers"): pointer-only 10 vs baseline-only 1 documents (McNemar p = 0.012);
  by parliament 6 favour the pointer, 0 the baseline (sign test p = 0.031, cluster permutation p = 0.031).
- **θ = 0** (registered secondary, no decision attached): pointer 54/62 vs 53/62 at θ = 10.40, with one fewer value on an
  answerless document (3/33 vs 4/33). On P1 the same θ = 0 gives the pointer 119/154 (130 at θ = 10.40) and the cascade
  142/154 (139). θ = 10.40 stays the registered primary.
- **Gold vs non-LLM sources.** 6 of the 29 P2 answer dates have an OPD written-answer event, and 6/6 agree. NW titles
  carry the RRB number, and it agrees with the gold decision number 6/6. No other P2 date can be checked without an LLM:
  the external check covers 6/29. `results/eval/posthoc_r3_gold_oracle.json`.

## D2-6 (10 Oct 2026, POST-HOC, found by the round-4 jury): body level on all 62 documents, the 8B on P2, more gold checks
- **Body level on all documents.** `results/eval2/body_level.json` used answered documents only, where the pointer wins
  6 bodies and the rules 0 (sign test p = 0.031). Here the per-document outcome is exact: a correct value or a correct
  null. On all 62 documents the pointer wins 6 bodies, the rules 2 (2196 Fribourg, 6266) and 7 tie (sign test p = 0.29;
  cluster permutation p = 0.15). In the 2 bodies the rules win, the pointer dates answerless documents that the rules
  leave empty. At document level on all 62 the pointer is still ahead, 22–4 (McNemar p = 5.3 × 10⁻⁴; exact 53 vs 35).
  `results/eval/posthoc_r4_eval.json` → `p2_body_level_all_documents`.
- **8B on P2 (added after the result; PREREG2 lists the 8B arms as exploratory).** Workflow `arms-8b-p2` runs the frozen
  arms rules, pointer and cascade on the 62 documents with the D2-gated fast scorer and the committed 8B θ, in 6 shards
  sliced on the full label order. `python -m eval.run_arms_p2 merge` scores the result with the frozen P2 scorer and
  hypotheses script → `results/eval2/p2__gguf_apertus-v1.5-8b-text-q4_k_m.json`. Not run yet when this entry was written.
- **Gold checks without an LLM** (`results/eval/posthoc_r4_gold_oracle_p2.json`):
  - **The 3 ordering violations are genuine.** In 26192 and 431985 (OW) the document prints its own submission date
    (10 Sep 2012; 26 Jan 2012), and that date is earlier than OPD's "Eingereicht" date. In 895511 (Vernier) the gold
    equals an OPD written-answer event (2017-01-30).
  - **New bounds, none contradicting a gold date:**
    - a printed submission date never follows the answer: 6/6;
    - a printed dispatch date ("Versand:") falls 0–30 days after a decision-role gold: 4/4;
    - the answer never follows OPD's scheduling event ("Traktandiert"): 6/6;
    - decision-role dates fall on one weekday per executive: VD 8/8 Wednesday, NW 6/6 Tuesday, OW 3 Tuesday + 1 Monday.
  - 19 of 29 gold dates now face at least one non-LLM bound. Only 6/29 are confirmed exactly by an outside source.
- **Addendum, 8B on P2 run** (CI run 38062249318, committed in 962e2f7; analysis `python -m report.p2_8b` →
  `results/eval2/p2_8b_analysis.json`). 52 of the 62 documents were scored: the hosts of 10 (VD 8, all of them answered; 6266 1; 62 1)
  were unreachable from the CI runners (`results/eval2/shards/unreachable_p2__*.json`), so Vaud is absent and 21 of
  the 29 answer dates remain. On the 52: rules 33, pointer 35, cascade 33 exact; the pointer finds 15 of 21 answer dates, dates 11 of 31
  answerless documents and returns no unprinted date. P2-H2 on the 8B rows (registered script, unchanged): 13 vs 0,
  p = 2.4 × 10⁻⁴. The 70B on the same 52: pointer 43, cascade 41 (8B vs 70B: 2 vs 10 documents, p = 0.039 for both).
