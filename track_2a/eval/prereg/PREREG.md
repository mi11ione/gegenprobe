# Pre-registration — Gegenprobe held-out evaluation (frozen by eval/prereg/LOCK)

Frozen before any held-out label exists: the rules baseline, the pointer prompts, θ per build (fitted on the dev set only),
the date-role definitions below, the scoring script `eval/score.py`, and every threshold in this file. The LOCK commit's
timestamp must precede the first commit that adds held-out labels (`git log -- data/gold/heldout_labels*`).

## Unit of evaluation
One (document, field) pair from `data/gold/heldout_docs.jsonl`. Fields:

| field | value space | gold |
|---|---|---|
| `answer_date` (strict) | ISO date, or null | the date the executive **decided** its answer as printed in this document (RRB-Nr. … vom, Sitzung vom, N° ACE … du, séance du, RG n. … del, ris. mun.); if no decision date is printed, the dispatch/letter date of the answer; null when the document contains no executive answer (`data/gold/README.md`) |
| `answer_date` (lenient) | as above | strict gold, or any other printed date the annotators list as a defensible answer date (e.g. the letter date next to the RRB date) |
| `recommendation` (secondary, exploratory) | accept / reject / convert / partial / none / not_applicable | the executive's recommendation to parliament, only where printed |

Labels: two blind Claude-agent annotators (A1 Opus, A2 Sonnet) and a third (A3 Opus) on disagreements only; quotes verified
verbatim by code; κ reported; OPD answer-event dates are an external check, never a label source (`docs/gold_protocol.md`).
No human labels or adjudication.

Date roles (frozen): `submitted` (lodged by the member), `answer_decided` (executive decision), `answer_dispatched`
(letter/publication of the answer), `debated` (parliament session), `decided` (parliament decision), `admin` (footer,
"Letzte Bearbeitung", version, print, filing). A footer/admin date is never a correct `answer_date`.

## Arms (all on the same frozen documents, prompts and θ) — `eval/arms.py run --split heldout`
| arm | what | where it runs |
|---|---|---|
| `rules` | frozen rules baseline only (`convert/rules.py`) | CPU, no model |
| `pointer` | closed-set pointer (S-SHAPE arm a) on every document, θ fitted on dev (`data/convert/theta/`) | Public AI name `swiss-ai/apertus-v1.5-8b`, which serves the **70B** weights (spikes/live), via the budget gateway; the response `model` field is checked on every call |
| `cascade` | rules, then the pointer on the residue only — the shipped converter | as above |
| `naive_plain` | naive free generation, plain prompt (round-7 `P_PLAIN`), single user message, seed = doc id mod 100000 | same endpoint and weights as the pointer (the `-70b` name splits requests over two backends that disagree, spikes/live §e) |
| `naive_null` | free generation with the null-allowed prompt (`P_NULL`) + verbatim-quote receipt check | as above |
| `rec_rules` / `rec_pointer` / `rec_cascade` | government recommendation, **exploratory**: rules / pointer with θ = 0 (declared; dev has only 2 non-null labels, nothing to fit) / rules then pointer | as above |
| 8B arms | the same arms on Apertus v1.5 **8B** (GGUF Q4_K_M, sha256 a037df8d…, llama.cpp CPU), with θ fitted on dev for that build | CI CPU runner; run only if the GGUF implementation check (`gegenprobe.gguf_check impl`) shows the implementation tracks bf16; otherwise reported as not run, with the reason |

## Metrics (per cell = language × level, plus the OCR cell; and pooled) — `eval/score.py`, frozen
- per document: correct · correct_null · false_null · **misattributed** (a wrong date that occurs in the document) ·
  **fabricated** (a date that occurs nowhere in the document); exact = correct + correct_null; wrong values =
  misattributed + fabricated; **invented_on_null** = any value on a document whose gold is null.
- Wilson 95% intervals for every proportion. Model share N/M = values decided by Apertus / all non-null values.
- Margin separation: AUROC of the null margin, answered vs answerless, on the **length-matched** held-out set (both classes
  1,000–2,000 tokens, approximated as chars/4) — the F2 length confound is broken by design.

## Hypotheses and decision rules (frozen)
All on `answer_date`, strict, unless stated. Pooled = all held-out documents.
1. **H1 null safety.** `cascade` gives a value on at most 1 gold-null document per cell, and the pooled invented_on_null
   rate is reported with its Wilson upper bound (target: upper bound ≤ 10% at n ≈ 70 gold-null documents). `naive_plain`
   is expected to give a value on most gold-null documents (round 7: 14–15/15); reported as the contrast, no threshold.
2. **H2 does Apertus add anything over the rules?** Primary: `cascade` vs `rules`, correct-or-not per document, pooled over
   the FR, IT and OCR cells, exact two-sided McNemar test at α = 0.05. **Branch A** if `cascade` > `rules`; otherwise
   **Branch B**: Apertus is kept only where it measurably adds null-safety, and the report says so in those words.
   Secondary (reported, no decision attached): `pointer` vs `rules` on the same documents; `cascade` vs `rules` pooled.
3. **H3 margin separation.** AUROC of the `pointer` null margin, gold-null vs gold-value documents, on the length-matched
   held-out set ≥ 0.80. If below, the pointer becomes review-only (it proposes, a person confirms), and the report says so.
4. **H4 unanchored FR/IT.** If `cascade` is wrong (misattributed or fabricated) on more than 1 of the Apertus-decided FR/IT
   values, a precision/coverage curve over θ is published as a separately labelled post-hoc analysis; the frozen result
   stays the headline.
5. **Exploratory (no decision attached):** recommendation arms; per-cell results; model share N/M; the 8B arms.

## What is not allowed after the freeze
Changing rules, prompts, θ, candidate extraction, truncation or the scorer. Any later change is reported as a deviation
with its effect on the frozen result. Failed and null runs are reported.
