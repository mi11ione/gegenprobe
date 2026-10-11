# Pre-registration P7: Apertus as a closed-set verifier for the adapters' review queue (frozen by eval/prereg8/LOCK8)

**Question.** The source adapters leave 917 rows in review (`results/repair/adapters/adapters_<BODY>.tsv`, tier
`review`): identity holds, but the answer heading or the date check does not. Blind audit v3 suggested that many of them
are real answers (the Claude auditor judged 23 of 30 review decoys to be the executive's answer). Can Apertus, asked only
closed-set questions, promote review rows to a separate tier at a precision that a parliament or OPD could act on, and
keep the counted tiers' date semantics?

**Written before any P7 test row is drawn.** Frame, seed, caps, arms, the frozen configuration, metrics and every
threshold are fixed here and in the hashed code. The test arms are run on the whole test frame and the sample is drawn
only after the LOCK8 commit (`python -m eval.p7.test draw`); every arm output is stored (sha256 in
`results/p7/test_sample.json`) before any test label exists; the LOCK8 commit must precede the commit that adds the test
labels. `eval/prereg8/lock8.py write` refuses to run if the test key or `results/p7/test_sample.json` already exists.

## Frozen system
Build: Public AI name `swiss-ai/apertus-v1.5-8b` (serves the **70B** weights) through the budget gateway; tags `2a-p7`
(test, cap USD 2), `2a-p7-queue` (whole queue, cap USD 2); the response `model` is checked on every call, cached or live
(`adjudicate.backend`). Forced choices are one user message plus an assistant prefill; generation is one plain user
message; nothing is sent to `swiss-ai/apertus-v1.5-70b`.

**p7** (the system under test; `src/gegenprobe/repair/adapters/adjudicate.py`, `data/p7/p7_config.json`):
1. Model view: the extracted text the adapters checked (sha256 = the list's `text_sha256`, asserted per row), first 9,000
   and last 3,000 characters.
2. (A) is_answer, prompt `a2`: intervention number, title and type, the view, and three checks (author is the executive,
   not a body of the parliament; subject matches the title; it gives the answer, not the intervention's own text, an
   interim report, a request for more time or minutes). Prefix `{"answer":`, continuations ` "yes"}` / ` "no"}`;
   m_yes = lp(yes) − lp(no); **θ_A = 8.0**.
3. (B) date, prompt `b1`: a lettered choice among the distinct dates the adapters' own parser
   (`repair.common.parse_dates`) finds in the view (at most 25, each with up to two printed lines) plus a `none` letter;
   the argmax date unless m_none = lp(none) − logsumexp(lp(dates)) > **θ_B = 10.0**.
4. Promote iff m_yes > θ_A, (B) names a printed date d, and `base.Adapter.date_check(full text, d, OPD answer events, OPD
   executive events)` of the row's own adapter passes with a counted date class (`eq`, `eq_gov`, `window`, `anywhere`):
   the counted tiers' rules with d in the place of the date the header regex read. The date's span (first occurrence,
   full-text offsets, the printed line) is located by code.
5. Never promoted: `opd_doc_ambiguous`, `no_answer_event`, and the document-type filters `resolution_reply` and
   `wrong_affair` (a filter only moves a row down; no model answer moves it back up): 54 of 917 rows.

**Comparison arms** (run on every test-frame row before the draw):
- **free**: free generation (prompt `free` in `adjudicate.py`, 80 tokens, seed = affair_id mod 100000) asking for
  `{"answer": yes/no, "answer_date": …}`; promoted iff the answer is yes, the date read back (`pointer_v2.read_date`) is
  one of the printed dates of the view, and it passes the same date rule.
- **trivial**: some date printed in the full text equals an OPD answer event date (no model).
- **rules_only**: promote nothing (the adapters as they are).

### How the configuration was chosen (P7 dev, 80 rows; `results/p7/dev_table.json`)
Dev: seed 20261013, 80 eligible review rows outside every audit, stratified by review reason and parliament
(`results/p7/dev_sample.json`); blind labels by A1 Opus + A2 Sonnet, A3 on 7 disputed rows
(`data/p7/dev_annotations/`): 70 yes, 9 no, 1 unclear. The θ_A rule was fixed in `eval/p7/tune.py` before the labels:
the smallest grid value at which no promoted dev row is gold no, unclear or disputed. With the first prompts (a1, θ_B
= 0) the rule gave θ_A = 13: 10 promoted, 10 correct (recall 10 of 25 attainable rows). After reading the labels, on dev
only, two changes were made: the is_answer prompt `a2` spells out the three error kinds the labels showed (an answer by
the parliament's Geschäftsleitung/Bureau, an interim report, a document on another motion with the same number), and
θ_B lets the date choice name its best date when `none` leads by less than 10 log units (the choice said `none` on
answers whose date the annotators found). The configuration was chosen as the most correct promotions at the rule's
θ_A (ties: a1, then smaller θ_B): **a2, θ_A = 8, θ_B = 10** → 16 promoted, 16 gold yes (Wilson 0.81–1.00), 15 of 16
chosen dates equal a gold answer date; recall 16/70 of all gold-yes rows, 15/25 of the rows whose gold answer date passes
the date rule. Dev arms at that setting:

| arm | promoted | gold yes | precision | yes and gold date passes rule |
|---|---|---|---|---|
| rules_only | 0 | – | – | – |
| p7 | 16 | 16 | 1.00 | 15 |
| free generation + printed-date filter | 25 | 23 | 0.92 (1 no, 1 unclear) | 20 |
| trivial (a printed date = an OPD event) | 32 | 31 | 0.97 | 21 |

The trivial baseline promotes more true answers on dev; for 10 of its 31 no gold answer date passes the date rule (the
answer's own date disagrees with OPD, the reason the adapters sent them to review). P7's value has to show on the test
as precision with the date semantics kept.
Every p7 promotion on dev was also promoted by free generation; free generation added 9 rows, 7 correct.

## Test frame and sample
- **Frame T:** every eligible review row of the committed lists outside the design audit (and its backup copy), audit v2,
  audit v3 and P7 dev: 478 rows (558 eligible outside the audits − 80 dev).
- **Arms first:** p7, free and trivial run on all of T; outputs in `WORK/p7test/decisions.jsonl` (sha256 committed).
- **Sampling strata** (seed **20261014**): `p7` = rows p7 promotes: all of them (a census) if at most 120, else a simple
  random sample of 120; `free_only` = rows free promotes and p7 does not: all if at most 30, else 30 at random; `rest` =
  40 rows stratified by review reason (floor 6, proportional, then by parliament: `eval/p7/common.draw`). Weight of a
  packet = N_s / n_s.
- Packets carry only an opaque id, affair number, title, type, OPD answer event dates and the text path (the audit-v3
  view: first 12,000 + last 3,000 characters), shuffled together; no stratum, arm output, parliament or pipeline field.

## Gold labels
Guide `WORK/p7test/GUIDE.md` (the dev guide `eval/p7/common.GUIDE`, unchanged but for the paths and id prefix). Two
blind Claude-agent annotators (A1 Opus, A2 Sonnet) on every packet; A3 (Opus) on packets where A1 and A2 differ in
`is_answer`, the two labels shown as X/Y in seeded order (seed 20261014).
Gold `WORK/p7test/ann/gold.jsonl` `{id, is_answer, dates}`: the common label and the union of A1's and A2's decision
and letter dates where they agree, else A3's label and dates. Quotes are checked
verbatim by code. Independent check: Qwen-SEA-LION-v4-32B-IT (`eval/p7/qwen8.py`, blind, same questions), reported as
agreement and κ; it changes nothing. No human labels.

## Metrics
- correct = gold `yes` (gold `no` and `unclear` are errors); correct_dated = correct and some gold answer date passes the
  row's date rule (the counted tiers' semantics).
- Precision of each arm = weighted correct / weighted promoted; recall = weighted correct promotions / weighted gold-yes
  rows (all) and / weighted correct_dated rows (attainable). Weighted figures: stratified bootstrap 95% intervals
  (10,000 resamples within sampling strata, seed 20261014). The p7 stratum (a census or a simple random sample of the
  p7 promotions in T) gets a Wilson 95% interval.

## Hypotheses (decided now; `eval/p7/hypotheses8.py`)
1. **H1 primary — promotion precision.** On the p7 stratum, the Wilson 95% lower bound of correct / promoted is
   **≥ 0.90**, with **at least 40** promoted rows judged. Fewer than 40: H1 does not hold (reported `underpowered`).
2. **H2 secondary — rows recovered.** The frozen p7 over the whole eligible review queue (863 of 917 rows; run with tag
   `2a-p7-queue`): M promoted rows; recovered = M × the H1 precision, interval M × its Wilson bounds; the same with
   precision_dated. Reported with the promotions by reason, parliament and date tier.
3. **H3 secondary — closed set vs free generation.** The rows free generation + printed-date filter would promote beyond
   p7 (`free_only`) have precision with Wilson 95% upper bound **< 0.90** (supported: free generation's extra rows are not
   good enough to promote). Both arms' weighted precision and recall are reported.
4. **H4 secondary — model vs trivial date match.** precision_dated(p7) − precision_dated(trivial), stratified bootstrap
   95% interval **excludes 0** above (supported). Precision (is_answer only) and recall of both reported.
- Also reported: the p7 decisions by reason (below θ_A, no date chosen, date rule fails, promoted); date hit (p7's
  chosen date is a gold answer date); p7 errors by reason; labels; Qwen κ.

## Consequences (written now)
- **H1 holds:** `results/repair/adapters/p7/promoted.tsv` (tier `promoted_by_apertus`, counted=false in the adapter
  lists) is published as a list OPD can apply, and the headline reports it **next to** the counted total (6,613 counted
  + M promoted by Apertus, the tier named), never merged into it.
- **H1 fails:** the promoted list is published as a review aid (rows ordered by m_yes for a person to check), with no
  headline number; the report says the precision bar was not met, with the counts.
- **H3 not supported:** the report does not claim that the closed set beats free generation on these rows.
- **H4 not supported:** the report does not claim that Apertus adds date-checked precision over the trivial date match.
- Every outcome is reported, including failures, in `results/p7/`, `.work/loops/round7/P7_wording.md` and
  `claims.d/p7.tsv`.

## Not allowed after LOCK8
Any change to the hashed files (prompts, configuration and thresholds, adapters' date rules, lists that define the
frame, sampler, caps, seed, guide, analysis). Later changes are listed in `eval/prereg8/DEVIATIONS8.md` with their
effect.
