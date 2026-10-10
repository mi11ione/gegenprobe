# Pointer v2: how the configuration is chosen on DEV2 (written 10 Oct 2026, before any DEV2 label exists)

DEV2 (`eval/p6/dev2.py`, 31 documents, 5 bodies in no existing set) is a development set. It is used once, to choose one
v2 configuration among the candidates below; nothing else is tuned on it. P6 is registered afterwards (eval/prereg7).

## What P1 dev showed (results/p6/dev_variants__dev.txt; 127 documents, 55 answered; the rules were written on this set)
- v1 pointer 118/127, registered free prompt (null allowed, corrected parser) 116/127, rules 126/127 (in-sample).
- The errors of v1 and of free prompting are mostly role errors between two printed dates (decision vs dispatch:
  "Regierungsratsbeschluss vom 7. Mai" vs "Basel, 8. Mai"; "ris. mun. 01/02/2012" vs "Lugano, 10 febbraio 2012").
- A presence question ("does this document contain the executive's answer?", yes/no forced choice) separates answerless
  from answered documents perfectly on dev (AUROC 1.00 vs 0.993 for the v1 null margin).
- Applying the gold guide's precedence in code (decision-date choice, else dispatch-date choice, else answer-date choice,
  each a lettered closed-set choice over printed dates shown with their lines) picks the right date on 51/55 answered
  documents (v1: 47/55). Presence gate + role pick: 122/127 (θ by leave-one-out), 120/127 at θ = 0.
- Free generation with the same guide-derived instructions (`src/prompts/*/naive_guided.txt`) scores 125/127. Its
  constrained (closed-set, prefilled) reading scores 119/127. The instructions, not the pointer mechanics, carry most of
  the gain on dev. Dev is in-sample for the instructions (they were written after looking at dev errors).

## Candidates (fixed now)
- **A  pointer**: presence gate (θ fitted on P1 dev, −5.89) → role pick (decision, dispatch, answer choice).
- **B  pointer, parameter-free**: presence gate at θ = 0 → role pick. Transfers to another build (8B) without a fit.
- **C  generate-then-point**: presence gate (θ fitted on P1 dev) → guided free generation, accepted only if the date it
  names is printed in the document (the span is then located), else the role pick. The output is always a printed date
  or null.

## Rule
1. Score A, B, C on DEV2 with θ as fitted on P1 dev (true transfer, no refit on DEV2), strict exact accuracy.
2. Choose the highest DEV2 exact. Ties: fewer dated answerless DEV2 documents; then pooled P1 dev + DEV2 exact; then the
   candidate with fewer model calls (B < A < C).
3. The chosen configuration is frozen into `data/p6/v2_config.json` and hashed by LOCK7. DEV2 results for all
   candidates and the comparison arms (v1, rules, registered free prompt, guided free prompt, latest printed date) are
   reported alongside, whatever they show.
