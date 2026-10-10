# Pre-registration P6: answer-date reader v2 on fresh parliaments (frozen by eval/prereg7/LOCK7)

**Question.** On documents from parliaments that no existing set contains, does the answer-date reader v2
(`src/gegenprobe/convert/pointer_v2.py`, configuration `data/p6/v2_config.json`) find more correct answer dates and
date fewer answerless documents than free prompting and than the v1 pointer? On P2 (62 documents, unseen parliaments) the
v1 pointer was right on 53, free prompting with null allowed on 54 after re-parsing: a tie.

**Written before any P6 document is drawn.** Seed, bodies, quotas, arms, metrics and every threshold are fixed here and
in the hashed code. The P6 sample is drawn only after the LOCK7 commit (`python -m eval.p6.sample draw`), all arms are run
before any P6 label exists, and the LOCK7 commit must precede the commit that adds `data/p6/p6_labels.jsonl`.
`eval/prereg7/lock7.py write` refuses to run if the P6 document list or the labels already exist.

## Frozen systems
Build: Public AI name `swiss-ai/apertus-v1.5-8b` (serves the **70B** weights), through the budget gateway; the response
`model` field is checked on every call. Forced choices are one user message plus an assistant prefill; generation is one
plain user message.
- **v2** (the system under test), chosen on DEV2 by the rule in `eval/p6/DEV2_SELECTION.md` (committed 6810ee5, before any
  DEV2 label) → candidate C (`results/p6/dev2_selection.json`):
  1. presence gate: forced choice "does this document contain the executive's answer?" (`answer_present.txt`), null iff
     lp(no) − lp(yes) > **θ_presence = −5.888** (fitted on P1 dev, 127 documents; not refitted);
  2. free generation with the guide-derived instructions (`naive_guided.txt`, 60 tokens, seed = doc_id mod 100000),
     kept only if the date it names is printed in the document (then it carries that span);
  3. otherwise the role choices (decision date or none, then letter date or none, lettered closed-set choices over the
     printed dates with their lines), precedence decision > letter applied in code; if neither names a date, the
     answer-date choice. The value is always a printed date or null.
- **v1**: frozen closed-set pointer (LOCK 812030f), θ = 10.40. **rules**: frozen rules. **cascade v1**: frozen cascade
  (rules, then v1 on the residue, no OPD metadata). **cascade v2**: a rules value or rules null is kept, v2 decides the
  rules' residue.
- **free_null** (comparator of the primary hypothesis): the registered free-prompting arm with null allowed
  (`naive_null.txt`, `eval/naive_baseline.run_doc`, seed = doc_id mod 100000), read with the corrected parser
  `eval/posthoc_r3.to_iso_fixed` (the registered parser's value is stored alongside). **free_plain**: the same without
  null instruction (reported). **free_guided**: free generation with v2's instructions, corrected parser, no closed-set
  check (the instruction-matched control).
- Baselines: **latest printed date**; **latest printed date on answer-typed documents only** (metadata type `answer`);
  **always null**.

## Documents
- **Seed 20261013.** Length window: OPD text length 2,000–12,000 characters (P2: 4,000–8,000; widened so that the small
  communes have enough documents; the reader's budget is 12,000 characters). One document per affair; a fetch failure
  (robots.txt disallow, HTTP error, not a PDF, text < 1,000 characters after extraction) is replaced by the next
  candidate of the same body and type in seeded order and logged in `data/p6/p6_fetch_log.jsonl`.
- **Excluded:** every document, affair and body of P1 dev and held-out and their dev-id sources (spikes, recovery audit,
  Bilanz), P2, P3, P3b, P4 (dev, held-out, transfer), **U2's P5 test and P5 dev** (`data/gold6/*.jsonl`: every affair and
  document, and the P5 test bodies Riehen 2703, BL, SH, Luzern city 1061, Wädenswil 293, Lausanne 5586, VS, Collombey-Muraz
  6152, Lugano 5192, GR, asserted by code), and **DEV2** (Wetzikon 121, Kreuzlingen 4671, Vétroz 6025, Yverdon 5938,
  Martigny 6136).
- **Strata** come from OPD metadata only (`eval/p6/common.doctype6` on the document name: names like "Beantwortung",
  "Antwort des Stadtrats", "Réponse" → `answer`; member texts → `intervention`); the label is the annotators'.

| cell | body | answer-typed | intervention-typed |
|---|---|---|---|
| de_canton | Zug canton (ZG) | 8 | 7 |
| de_commune | Zug city (1711) | 4 | 4 |
| de_commune | Wil SG (3427) | 5 | 4 |
| de_commune | Lyss (306) | 5 | 3 |
| de_commune | Neuhausen am Rheinfall (2937) | 5 | 4 |
| de_commune | Interlaken (581) | 3 | 3 |
| fr_commune | Conthey (6023) | 5 | 4 |
| fr_commune | Neuchâtel city (6458) | 5 | 0 |
| fr_commune | Val de Bagnes (6037) | 4 | 4 |

9 parliaments, 77 documents (44 answer-typed, 33 intervention-typed). **Riehen (2703)** was in the plan and was removed
before this lock because U2's P5 test uses it; its 9 documents went to ZG (+2/+2), Zug city (+0/+1), Wil (+1/+0), Lyss
(+1/+0) and Neuhausen (+1/+1).
- **Why these bodies and no Italian:** a probe on 10 Oct 2026 of every unseen body with ≥ 3 answer-typed documents found
  the remaining ones unusable from this machine: connection timeouts (Uri, Uster, Emmen, Olten, Dietikon, Horw, Kriens,
  Wohlen, Wettingen, Pratteln, Lenzburg, Langenthal, Chur, Opfikon, Thun, Gossau, Zollikofen and the ILEF host), robots.txt
  disallowing the document paths (Aargau, Fribourg canton, Locarno, Arbon), or HTTP 404 (Sierre). Locarno was the only
  unseen Italian-language parliament; P6 therefore has **no Italian document**. This is a limitation, reported with
  every result.
- If fewer than 60 documents can be drawn, the hypotheses are still computed, flagged `underpowered`, and reported.

## Labels
Same protocol as P2: guide `eval/gold2/GUIDE.md` (unchanged), two blind Claude-agent annotators (A1 Opus, A2 Sonnet) who
see only the document packets, a third (A3 Opus) on documents where A1 and A2 differ in the **answer date** (the only
field P6 scores), the two labels shown as X/Y in seeded random order (seed 20261013); quotes verified verbatim by code;
κ reported; an independent non-Anthropic check (Qwen-SEA-LION-v4-32B, blind, as in round 5) is reported alongside. No
human labels. The runner reads no label; all arms are run and their results committed before the labels.

## Metrics
Per document, the frozen `eval/score.py` outcome, **strict** (lenient reported): exact = correct date or correct null;
dates found (correct / documents with a gold date); dates on answerless documents (values / gold-null documents);
wrong printed date; fabricated (a date printed nowhere: possible only for free generation); missed. Wilson 95% intervals.

## Hypotheses (decided now)
1. **H1 primary — v2 beats free prompting.** Exact accuracy of v2 vs free_null, all P6 documents, paired exact McNemar,
   two-sided α = 0.05. **Holds** if p < 0.05 and v2 is right on more documents.
   Per-parliament sign test (bodies where v2's exact count is higher vs lower; ties dropped; exact two-sided α = 0.05):
   the wording "across parliaments" is used only if it also holds.
2. **H2 — v2 dates few answerless documents.** Holds if the Wilson 95% upper bound of v2 values on gold-null documents is
   ≤ 15% **and** v2 dates no more gold-null documents than v1 and than free_null (paired counts on gold-null documents
   reported with McNemar p).
3. **H3 — v2 beats v1.** Exact accuracy of v2 vs v1, paired exact McNemar, two-sided α = 0.05; holds if p < 0.05 and v2 is
   right on more documents.
- **Multiplicity:** Holm over the H1 and H3 p-values is reported; H1 is the single primary test.
- **Secondary, reported without a decision:** v2 vs free_guided (the instruction-matched control: does the closed-set
  check and the presence gate add anything beyond the instructions?); cascade v2 vs cascade v1; cascade v2 vs rules on
  documents with a gold date; AUROC of the presence margin (answerless vs answered); how v2 decided (presence /
  generation / role choice / answer choice); exact per language; fabricated values per arm.
- **Exploratory:** the real Apertus 8B (GGUF Q4_K_M, CPU, CI) with v2's presence θ fitted on P1 dev for that build by
  the same rule (`calibrate.fit_theta`); added after this lock, labelled exploratory.

## What DEV2 already suggests (stated before P6, so it cannot be read as a post-hoc excuse)
On DEV2 (31 documents, 5 unseen parliaments) v2 scored 29/31, free_null 30/31, free_guided 31/31, v1 28/31; v2's two
misses were answered documents stopped by the presence gate (θ fitted on P1 dev is strict on new layouts). H1 may
therefore fail. It is registered as asked, unchanged.

## Consequences (written now)
- **H1 holds:** the report says the closed-set reader v2 beats free prompting on unseen parliaments, with the paired
  counts; "across parliaments" only if the sign test also holds.
- **H1 fails:** the report says v2 does not beat free prompting on accuracy; Apertus's added value is then argued only on
  what P6 shows besides accuracy (no fabricated date, a span for every value, null safety under H2, the presence margin
  as a review signal), with the numbers.
- **H2 fails:** v2's null decisions are not presented as safer; the review mode keeps every v2 value as a suggestion.
- **H3 fails:** v2 does not replace v1 in the shipped review mode; both are reported.
- Every outcome is reported, including failures, in `results/p6/` and `.work/loops/upgrades/U3_wording.md`.

## Not allowed after LOCK7
Any change to the hashed files (v2 code, prompts, configuration and θ, sampler, quotas, seed, guide, annotation wrapper,
runner, hypothesis script). Later changes are listed in `eval/prereg7/DEVIATIONS7.md` with their effect.
