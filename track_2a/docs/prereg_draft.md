# Pre-registration (DRAFT — becomes eval/prereg/PREREG.md when frozen; sha256 in eval/prereg/LOCK)

Frozen before any held-out label exists: the rules baseline, the pointer prompts, θ per build (fitted on the dev set only),
the date-role definitions below, the scoring script `eval/score.py`, and every threshold in this file. The LOCK commit's
timestamp must precede the first commit that adds held-out labels (`git log -- data/gold/heldout_labels*`).

## Unit of evaluation
One (document, field) pair from `data/gold/heldout_docs.jsonl`. Fields:

| field | value space | gold |
|---|---|---|
| `answer_date` | ISO date that occurs in the document, or null | the date the executive **decided** its answer (RRB/ACE/risoluzione date, "Sitzung vom", "séance du", "seduta del"); null when the document contains no government answer |
| `answer_date_lenient` | as above | decided date **or** the dispatch/letter date of the answer ("Basel, 3. März 2025") |
| `recommendation` | accept / reject / convert / partial / none / null | the executive's recommendation to parliament, only where the document states one |

Date roles (frozen): `submitted` (lodged by the member), `answer_decided` (executive decision), `answer_dispatched`
(letter/publication of the answer), `debated` (parliament session), `decided` (parliament decision), `admin` (footer,
"Letzte Bearbeitung", version, print, filing). A footer/admin date is never a correct `answer_date`.

## Arms (all on the same frozen documents and prompts)
| arm | what | where it runs |
|---|---|---|
| R | frozen rules baseline only | CPU |
| P70 | closed-set pointer (S-SHAPE arm a), θ fitted on dev | Public AI `swiss-ai/apertus-v1.5-8b` name, which serves the **70B** weights (spikes/live), via the budget gateway; every response's `model` field checked |
| C70 | cascade = R, then P70 on the residue (the shipped converter) | as above |
| N70 | naive free generation, plain prompt (round-7 S-NULL `P_PLAIN`), user message only, seeded | Public AI `swiss-ai/apertus-v1.5-70b`, gateway |
| N70-null | naive free generation, null-allowed prompt (`P_NULL`) + verbatim-quote check | as above |
| P8 / N8 | the same on Apertus v1.5 **8B** (GGUF Q4_K_M, sha256 a037df8d…, llama.cpp CPU) | CI CPU runner; reported only if run before the deadline, otherwise listed as not run |

## Metrics (per cell = language × level, plus the OCR cell; and pooled)
- exact (strict and lenient) on answered documents; **invented** = a value where gold is null, or a value that does not occur
  in the document; **wrong** = a value that occurs in the document but is not gold; correct null; false null.
- Wilson 95% intervals for every proportion. Model share N/M = values decided by Apertus / all non-null values.
- Margin separation: AUROC of the null margin, answered vs answerless, on the **length-matched** held-out set (both classes
  1,000–2,000 tokens, approximated as chars/4) — the F2 length confound is broken by design.

## Hypotheses and decision rules (frozen)
1. **H1 null safety.** C70 invents on ≤ 1 of the gold-null documents per cell and ≤ 2% pooled (upper Wilson bound reported).
   N70 is expected to invent on most gold-null documents (round 7: 14–15/15). Reported as the contrast; no threshold.
2. **H2 does Apertus add anything over rules?** Primary comparison C70 vs R on answered documents, exact (strict),
   pooled over FR + IT + OCR cells. **Branch A** if a paired exact McNemar test (two-sided α = 0.05) on correct-vs-not per
   document shows C70 > R. Otherwise **Branch B**: Apertus is kept only where it measurably adds null-safety, and the
   report says so.
3. **H3 margin separation.** Length-matched AUROC of the P70 null margin ≥ 0.80; if below, the pointer becomes review-only
   (it proposes, a human confirms) and the report says so.
4. **H4 unanchored FR/IT.** If C70 is wrong on > 1 of 40 unanchored FR/IT values, θ is raised post hoc **as a separately
   labelled analysis**, and the precision/coverage curve is published; the frozen result stays the headline.

## What is not allowed after the freeze
Changing rules, prompts, θ, candidate extraction, truncation or the scorer. Any later change is reported as a deviation
with its effect on the frozen result. Failed and null runs are reported.
