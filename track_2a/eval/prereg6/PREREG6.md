# Pre-registration P5: per-question Q/A pairing, people, recommendation and reasoning on fresh parliaments

Status: FROZEN by `eval/prereg6/LOCK6` (sha256 of this file and of every file listed under "Frozen"). The commit that adds
LOCK6 is the registration time. At that commit no P5 affair has been drawn, no P5 document fetched, no P5 label exists.

## Why
P1-P3b measure dates and single-valued affair fields. The challenge also asks to pull out the question, the answer and its
reasoning, question/answer pairs, people and decisions. Schema v0.1 has `QAPair.items` (`QAItem`: question n <-> answer n)
but no converter filled it. `src/gegenprobe/qa/` (new; no earlier locked module is changed) fills, with a page + character
span for every value: (a) the member's numbered questions and the passage of the executive's answer that replies to each
(`QAItem`), (b) the submitter and co-signatories (`Actor`), (c) the executive's recommendation (`GovRecommendation`, with
the printed sentence as evidence), (d) the reasoning span (the executive's substantive reply). Rules decide first; Apertus
is used only as a closed-set pointer where the rules leave a residue (which numbered question an answer paragraph replies
to, or none; which printed candidate sentence states the recommendation, or none; which printed name is the submitter, or
none). P5 measures this on affairs drawn after this lock, from parliaments outside the development set.

## Development (before this lock; in-sample, reported as such)
- Dev set: 38 affairs, 14 parliaments, drawn by `eval/gold6/dev6.py` (seed 20261020, plus a type-targeted top-up after
  robots/OCR failures, logged in `data/gold6/p5dev_fetch_log.jsonl`): BS, ZH, LU, Zürich city (261), BE, VD, GE, Vernier
  (6643), TI. Excluded: P1 dev + held-out (+ spikes, dev-id sources), P2, P3, P3b, P4 (+ transfer).
- Labels: blind A1 (Claude Opus) and A2 (Claude Sonnet) with `eval/gold6/GUIDE_P5.md`, A3 (Claude Opus) on the 6 disputed
  fields in 5 affairs (`results/eval6/p5dev_agreement.json`). One A2 session printed about 20 lines of `annotate6.py` while
  debugging its self-check (no labels or extractor output were shown); noted for the audit.
- The rules were written and the pointer prompts and θ were fitted on these labels by the same agent; dev numbers
  (`results/eval6/p5dev__*.json`, `results/eval6/hypotheses6__p5dev__*.json`) are in-sample. Only P5 measures the
  extractor.
- Dev results (in-sample; `results/eval6/hypotheses6__p5dev__publicai_swiss-ai_apertus-v1.5-8b.json`), 38 affairs,
  148 gold non-null answers, 24 gold-null answers:

  | arm | Q/A recall | Q/A precision | spans on gold-null | submitter | recommendation | reasoning (IoU >= 0.5) |
  |---|---|---|---|---|---|---|
  | R (rules) | 130/148 (0.88, CI 0.82-0.92) | 130/135 (0.96, 0.92-0.98) | 0 | 36/38 | 37/38 | 36/38 (mean IoU 0.91) |
  | RA (θ fitted, see below) | 130/148 | 130/135 | 0 | 36/38 | 37/38 | 36/38 |
  | RA0 (secondary arm: θ_pair = 0) | 132/148 | 132/151 | 10 | 36/38 | 37/38 | 36/38 |
  | G (free generation, null allowed) | 40/148 | 40/80 | 4 | 34/38 | 7/38 | 6/38 (mean IoU 0.17) |
  | B_order | 18/148 | 18/164 | 24 | 4/38 | 29/38 | 29/38 |
  | B_whole | 12/148 | 12/166 | 24 | 4/38 | 29/38 | 29/38 |

  Questions (R): recall 161/174, precision 161/166. Co-signatories (R): recall 95/106, precision 96/142 (most false
  positives are Lucerne signature lists that the dev gold keeps for one Lucerne affair and drops, by the A1 ∩ A2 rule, for
  three). R Q/A recall by language: de 78/79, fr 29/43, it 23/26. G: 109 values whose quotes are not in the documents, 3
  unparsable replies. Span re-check (H5) on dev: 555/555 R values, 557/557 RA values, 573/573 RA0 values.
  RA0 on the dev residue (`results/eval6/p5dev_ra0_secondary.json`, replayed from cached scores without rewriting the
  hashed dev results file): residue recall 2/14 (Wilson 0.04-0.40), suggestion precision 2/16 (0.03-0.36), 11
  suggestions where the gold answer is null.
- θ (`eval/gold6/tune6.py`, objective = correct minus wrong pointer values on the dev residue, from cached scores): the
  dev residue for pairing is 6 affairs, 5 of which the gold marks as answered globally or not answered, so every suggestion
  there is a false span; the objective is maximal (0) for θ <= -34 and θ_pair = -47 (midpoint of the optimal interval on
  the grid -60..20): the pairing pointer abstains on every dev paragraph. θ_recommendation = θ_submitter = 0 (one residue
  case each, flat objective; declared). The pointer therefore enters P5 as a registered, conservative suggestion arm; P5
  measures whether it ever fires and whether it is right when it does. The unfitted pairing pointer (θ_pair = 0) is
  registered as a **secondary** arm RA0 (added at the coordinator's request before the lock; decision-free).

## Sample (drawn after the LOCK6 commit; seed 20261030; `eval/gold6/sample6.py`)
Qualification exactly as P3 (`eval/gold3/sample.py` pairing rule, scope Interpellation / Motion / Postulate / Question,
OPD text status ok, 1,500-30,000 characters, lowest-id document of each role), fetched politely with OCR fallback and
accepted with >= 1,000 characters (`eval/gold2/sample.py:fetch_one`). Excluded: every affair and document of P1 dev +
held-out (+ spikes, dev-id sources), P2, P3, P3b, P4 (+ transfer) and the P5 dev set. **No P5 body is a P5 dev body**
(asserted by the sampler). A failed fetch is replaced by the next affair of the same cell in seeded order; a cell that
cannot be filled is topped up from its reserve body (same type, else any type). Every attempt is logged
(`data/gold6/p5_fetch_log.jsonl`). Pools counted from metadata before this lock (no draw, no text read).

| cell (body, language, type) | level | pool | n | reserve |
|---|---|---|---|---|
| BL Basel-Landschaft, any | canton | 684 | 4 | AR |
| SH Schaffhausen, any | canton | 287 | 4 | AR |
| 1061 Luzern city, Interpellation | commune | 229 | 2 | 4082 Wohlen |
| 1061 Luzern city, Motion | commune | 147 | 2 | 4082 Wohlen |
| 2703 Riehen, any | commune | 235 | 4 | 306 Lyss |
| 293 Wädenswil, any | commune | 213 | 3 | 3427 Wil |
| 293 Wädenswil, Postulate | commune | 17 | 1 | 3427 Wil |
| 5586 Lausanne, Interpellation | commune | 165 | 2 | 6152 Collombey-Muraz |
| 5586 Lausanne, Postulate | commune | 56 | 2 | 6152 Collombey-Muraz |
| VS Valais (French documents), any | canton | 50 | 4 | 6152 Collombey-Muraz |
| 2196 Fribourg city, Postulate | commune | 33 | 4 | 6152 Collombey-Muraz |
| 5192 Lugano, Question | commune | 374 | 2 | 5113 Locarno |
| 5192 Lugano, Motion | commune | 54 | 2 | 5113 Locarno |
| GR Graubünden (Italian documents), any | canton | 140 | 4 | 5113 Locarno |
| **total** | canton 16 · commune 24 | | **40** | de 20 · fr 12 · it 8 |

Robots.txt of every P5 and reserve host except `api.i-web.ch` (a minority host of Luzern city) answered before this lock.

## Gold
No human labels (by design). A1 (Claude Opus) and A2 (Claude Sonnet) label every P5 affair blind from its packet only
(`.work/p5/packets/<affair_id>.txt`, never committed) with `eval/gold6/GUIDE_P5.md` (unchanged from dev); every quote is
resolved to a character span by code (`eval/gold6/annotate6.py`, whitespace-insensitive, otherwise verbatim). A3 (Claude
Opus) decides only disputed fields, seeing both labels as X/Y in seeded random order (seed 20261031). Disputed (decided
before any label): question count or any question span IoU < 0.5; answer style; any answer pair with one null and one
span or IoU < 0.5; submitter surname; recommendation; reasoning IoU < 0.5 or one null. Co-signatories are a set: the
intersection of A1 and A2. Annotators see no extractor output, no metadata, no dev result. Raw annotator files are
committed (`data/gold6/annotations/p5/`).

**Independent non-Anthropic check (registered).** Qwen-SEA-LION-v4-32B-IT (AI Singapore; Qwen family) labels every P5
affair blind from the same packet and the same guide (`eval/gold6/qwen6.py`, gateway tag `2a-p5-qwen`, cap USD 0.6, served
model checked). Reported: agreement with the gold on question count, answer style, submitter, recommendation and answer
spans (IoU >= 0.5); H1 recomputed (i) with the Qwen labels as gold and (ii) on the consensus subset (gold answers whose
Qwen span matches). No decision depends on it; a sensitivity flip of H1 is reported in the result text.

## Arms (`eval/gold6/run6.py`)
| arm | what |
|---|---|
| R | rules only (`src/gegenprobe/qa`, no model); the residue stays a typed null — the unattended default |
| RA | R + the Apertus closed-set pointer on the residue, every suggestion accepted (review mode, scored as if accepted); θ as fitted on dev (θ_pair = -47) — the **primary** pointer arm |
| RA0 | **secondary:** as RA with the pairing pointer at θ_pair = 0 (recommendation and submitter as RA); the same cached model scores as RA, no extra call |
| G | free-generation Apertus, null allowed, all fields in one JSON (`eval/gold6/freegen6.py`); values count only if their verbatim quotes are found in the documents (receipt check) |
| B_order | trivial: R's question list and reply span; answer n = the n-th paragraph of the reply |
| B_whole | trivial: answer n = the whole reply for every question |
B_* also fix: submitter = first person-name-like string of the question document; no co-signatories; recommendation =
not_applicable (most frequent dev label); reasoning = the whole answer document.
Model: the build used in P1-P3b, `gateway:swiss-ai/apertus-v1.5-8b:2a-p5-test:1.5` (the name serves the 70B weights; one
user message, never a system message; prefill only to this name; the response model is checked on every call), θ per
pointer field from `data/gold6/theta_p5dev.json`, frozen in `src/gegenprobe/qa/extract.py` (`THETAS`: pair -47.0, recommendation 0.0, submitter 0.0).
Failed or partial runs are reported.

## Metrics (`eval/gold6/score6.py`; spans = character intervals of one document, pages joined with "\n")
IoU(A, B) = |A ∩ B| / |A ∪ B| on character offsets; a span **matches** when both lie in the same document and IoU >= 0.5.
- **qa_pairs (headline).** Over gold questions whose gold answer span is non-null: correct when the predicted answer with
  the same n is non-null and matches. Recall = correct / gold non-null answers. Precision = correct / predicted non-null
  answers (every predicted non-null answer counts). false_span = predicted non-null answers where the gold has the question
  with a null answer (global or unlinked answers).
- **questions.** Per gold question n: matched by predicted question n. Recall = matched / gold questions; precision =
  matched / predicted questions; count_exact = affairs whose predicted question count equals the gold count.
- **submitter.** Per affair: correct when both are null, or the gold surname (last token, accent- and case-folded) is a
  token of the predicted name, or the predicted last token is a token of the gold name.
- **co_signatories.** Micro precision / recall with the same name rule.
- **recommendation.** Per affair: exact label among accept, reject, partial, convert, none, not_applicable (an abstention
  is wrong).
- **reasoning.** Per affair: correct when both are null, or both are spans that match; mean IoU reported.
All rates with Wilson 95% intervals.

## Hypotheses (thresholds fixed now; `eval/gold6/hypotheses6.py`)
- **H1 (primary) — rules-only Q/A pairing transfers.** Arm R on qa_pairs: "per-question pairing extractable unattended" if
  the precision Wilson lower bound >= 0.85 and the recall lower bound >= 0.60; "partial" if precision LB >= 0.70 and recall
  LB >= 0.40; else "not yet". H1 holds if the tier is not "not yet".
- **H2 — the rules beat a trivial pairing.** On gold non-null answers, R vs B_order, exact one-sided McNemar on discordant
  pairs, alpha 0.05.
- **H3 — the pointer on the residue.** Residue = gold non-null answers whose question R leaves without a span. (a) RA
  recall on the residue, Wilson LB >= 0.50; (b) precision of the pointer's suggestions (answer spans RA adds), Wilson LB
  >= 0.70. Both -> "pointer adds answers unattended"; (a) only -> "review gate"; neither -> "no measurable gain". Fewer
  than 10 residue answers -> "inconclusive (underpowered)". The recommendation residue (R abstains) is reported apart
  (count and RA correct).
- **H3b (secondary; no verdict depends on it) — the unfitted pairing pointer.** For RA0, with the H3 definitions: residue
  recall and suggestion precision with Wilson 95% intervals, the number of suggestions, and spans_on_gold_null (RA0
  suggestions where the gold answer is null or the question is not in the gold); the same category labels as H3, reported
  as descriptive. Also reported: RA0's qa_pairs recall / precision / false_span next to R and RA.
- **H4 — closed-set pointer vs free generation.** On gold non-null answers, RA vs G, exact one-sided McNemar (RA better),
  alpha 0.05; reported with both precisions, G's unlocatable values and parse failures.
- **H5 — provenance.** Every value of the R and RA schema records (`QAItem`, `Actor`, recommendation, reasoning) validates
  with the Pydantic models and re-checks against its span (`gegenprobe.validate.spans.recheck`): 0 failures (RA0
  reported alongside).
- **Descriptive (no verdict):** per-field tiers for R and RA (questions, submitter, co-signatories, recommendation,
  reasoning) with P3's bars (lower bound >= 0.80 "extractable unattended", >= 0.50 "partial"); results per language and per
  body; the same tables on dev (in-sample) next to P5.

## Success criteria (fixed now)
- **S1** = H1 holds. **S2** = H2 holds.
- **Verdict** for the claim "the converter extracts per-question Q/A pairs with spans on parliaments it was not developed
  on": "supported" if S1 and S2; "partially supported" if exactly one; "not supported" otherwise. H3-H5 and the
  descriptive tables are reported without changing the verdict.

## Frozen (hashed in LOCK6; `python -m eval.prereg6.lock6 check`)
LOCK6 also carries every LOCK5 hash (which includes P1's), so one check covers the whole frozen system.
- Registration: this file, `eval/prereg6/{__init__,lock6}.py`, `eval/gold6/GUIDE_P5.md`.
- P5 tooling: `eval/gold6/{__init__,common6,dev6,sample6,annotate6,run6,score6,baselines6,freegen6,hypotheses6,qwen6,tune6}.py`.
- Extractor: `src/gegenprobe/qa/{__init__,text,questions,answers,people,rec,pointer,extract}.py`, prompts
  `src/prompts/{de,fr,it}/qa_*.txt` (pointer prompts and the free-generation prompt `qa_freegen.txt`) and
  `src/prompts/qa_freegen_schema.txt`; span re-check `src/gegenprobe/validate/{__init__,spans,dates}.py`.
- Dev set, labels, θ and the dev results θ was fitted on: `data/gold6/p5dev_affairs.jsonl`, `data/gold6/p5dev_labels.jsonl`,
  `data/gold6/theta_p5dev.json`, `results/eval6/p5dev_ra0_secondary.json`,
  `results/eval6/p5dev__publicai_swiss-ai_apertus-v1.5-8b.json`.
Written after the lock by frozen code (not hashed, committed): `data/gold6/p5_affairs.jsonl`, `p5_fetch_log.jsonl`,
`p5_labels.jsonl`, `annotations/p5/`, `results/eval6/p5__*.json`, `hypotheses6__p5__*.json`, `p5_qwen_check.json`.

## Not allowed after the lock
Changing any frozen file, the seed, cells, quotas or reserves, the guide, θ, the prompts, the metrics, the hypotheses or the
success criteria. Any change is a reported deviation in `eval/prereg6/DEVIATIONS6.md`; fetch failures, shortfalls,
reserve use and failed runs are reported.
