# Technical report — Gegenprobe: one schema and a converter for Swiss parliamentary answers

**Track 2A — OpenParlData** · Online · Team 444 — Roman (+ Claude Code agents, §9) · Evidence site https://gegenprobe.mi11ion.io · `make run` re-checks the results (§8) · **Maturity:** census and repair lists = *ready to hand over*; nightly job = *ready to deploy* (not yet running at OPD); rules-only converter = *tested prototype*; review mode, whole and virtual affairs = *feasibility study*; schema v0.1 = *draft*.

## 1. Summary

**The two questions.** *Is a common schema feasible?* Yes, with date roles and typed nulls: of 17 fields, **4 are feasible from metadata, 13 partial, 0 need a different concept**. The concepts are shared; what differs is where the value lives, the vocabulary and the date roles ("answer date" is decided, dispatched or registered). *Can a converter fill it?* Yes, for what the documents print: every value the converter takes from a document is printed there, with page and character span; values from OPD metadata are marked `route: metadata` with their source; a missing value is a typed null that says why. By default frozen DE/FR/IT rules run without a model; where no rule exists, Apertus points at one of the printed dates as a suggestion a person confirms.
**The cross-parliamentary result the schema enables.** OpenParlData (OPD) publishes the affairs of 89 Swiss parliaments with affairs in scope (it scrapes 90). Of 91,268 interventions whose events record a written government answer, **16,749 (18.4%) have no answer text in OPD** (2024–25: 1,855, 14.3%), each typed by cause; 1,008 are Valais oral answers filed as stubs and 406 question-time answers given in the sitting. In Bern the canton publishes 3,532 answers and OPD attaches 229 (6.5%), although 96.1% are already in OPD and linkable; OPD confirmed the bug and that our relink list is the workaround until its fix ships (correspondence, 10 Oct 2026). Deterministic routes propose repairs for 3,107 of the 16,749; 10,800 written answers need per-parliament source adapters.
**Where Apertus earns its place.** On 62 documents from 15 parliaments the rules never saw (the 29 answer dates come from 7 of them), Apertus finds 24/29 answer dates where the rules find 2/29; on all 62 documents it is right on 22 the rules miss and the rules on 4 (p = 5.3 × 10⁻⁴); against the strongest one-line baseline it wins 10 documents to 1 (p = 0.012), 6 parliaments to 0 (p = 0.031). On whole affairs it completes the answer date (22/27 → 27/27; held-out replication 20/35 → 31/35).

## 2. Architecture

1. **Census** (`census/`): streams the OPD exports once, keeps metadata only, and computes the answer funnel, a per-affair *answer-link status* (`attached | agenda | parentless | absent | image_only | oral`), the feasibility matrix and a comparability measure from OPD's own vocabularies. A vendored extract (`data/census/`) lets `make run` recompute every census number.
2. **Repair** (`repair/`): deterministic routes per cause, verified by a triple check (affair number printed, answer heading present, decision date = OPD's answer event), as lists keyed on OPD ids. A nightly job (`deploy/nightly/`, `docs/runbook.md`) re-runs the joins and raises alerts.
3. **Converter** (`convert/`): per document, (i) OPD metadata and events, (ii) frozen DE/FR/IT anchor rules, (iii) the Apertus closed-set pointer on the residue. Modes: `rules_only` (default, unattended, no model) and `review` (pointer values attached as suggestions with page, span and margin, flagged `needs_review`). An overlay marks unknown layouts (`no_rules_for_body`, `needs_review`) and qualified recommendations (`partial`); user anchors (`--anchors`) run after the frozen rules; `--explain` lists every rule tried.
4. **Schema and validator** (`schema/`, `validate/`): Pydantic schema v0.1, normative; every field is a value with provenance `{value, role, page, char_start, char_end, quote, route, rule, model_build, θ, margin}` or a *typed null* (`not_in_document | unlinked | image_only | oral | text_failed | present_unanchored | no_rules_for_body | not_applicable`); `QAItem` pairs question *n* with answer *n* (not yet filled). The JSON Schema export cannot express the cross-field rules, so validation uses the Pydantic models.

![fig1](docs/figures/fig1_funnel.png)
*Figure 1. National answer funnel with typed causes and repair routes.*

## 3. Use of Apertus

**Closed-set pointer** (`convert/pointer.py`, prompts `src/prompts/{de,fr,it}`). The user message holds the document (first 12,000 characters) and the question; the assistant turn is prefilled with a JSON prefix (`{"antwort_datum":`); `null` and every distinct date printed in the document are scored as continuations by summed log-probability (exact forced choice via `prompt_logprobs`). Null if `lp(null) − logsumexp(lp(dates)) > θ`, else the best date, mapped back to its span. θ does not transfer across builds (spike F2: a θ fitted on RLVR scores 0.25 on the final build), so it is fitted per build on dev documents and frozen: θ = 10.40 for the Public AI build (AUROC 0.99, leave-one-out 124/127 [93.3, 99.2]). **Why a pointer** (spikes, `results/report/cited_spikes.json`): asked freely, Apertus dates 15/15 (8B) and 14/15 (70B) Bern interventions that have no answer; a null-allowed prompt fixes the 70B (0/15), not the 8B (14/15).

**Which Apertus, which size.** Unless marked 8B, Apertus numbers are the **70B** weights, served by Public AI under the name `swiss-ai/apertus-v1.5-8b` (cited: 760/792 greedy outputs byte-identical to the 70B name; MMLU 84.4% vs 70.8% for the v1 8B route); a system message or prefill to the `-70b` name is answered by Qwen-SEA-LION (3/3), so forced choice goes only to the `-8b` name and the response `model` field is checked on every call. The **real 8B** (GGUF Q4_K_M, llama.cpp on one 4-vCPU machine, own θ = 16.73; pre-registered exploratory arms, D2/D3) ran P1: same rules arm, pointer 112/154 and cascade 119/154 vs 130 and 139 on the 70B (McNemar p = 0.0051 and 3.6 × 10⁻⁵); it invents no date (all 85 cascade values are printed) but dates 25 of 90 answerless documents (70B: 7). Its scorer self-check fixed in advance failed (10/12 decisions, 3.16 nats vs ≤ 1.0), an implementation difference: it agrees with a bf16 stand-in on 58/60 decisions, like other llama.cpp builds (`results/eval/gguf_impl60.json`). **Recommendation:** `rules_only` unattended; review suggestions from the 70B on Swiss-hosted infrastructure; the 8B on one CPU machine as the fully local option, less accurate.

**Cost** (`results/report/cost_end_to_end.json`, one core, no GPU). Per document, fetching politely, extracting and checking takes about 2.1 s, plus 6.9 s per page where OCR is needed; the rules process 480 documents per second (0.5 CPU-hours for all 902,754 documents in OPD's export). Review mode adds the pointer on the residue (97 of 154 held-out documents): 3.5 calls and 5,905 billed prompt tokens per residue document on the 70B, USD 0.59 per 1,000 residue documents at Public AI's list price; the 8B takes 180 s per document on 4 vCPUs (692 CPU-seconds, 9.3 GB RAM), 50 machine-hours per 1,000. At ten times OPD's volume: about 5 CPU-hours for the rules, about USD 3,357 for review mode.

## 4. Data and operations

OPD bulk exports (snapshot 6 Oct 2026; OPD's API robots.txt disallows `/v1/`), Bern open data, Fedlex, source PDFs fetched politely (≥ 1.2 s per host; robots.txt per RFC 9309). The container never runs as root (uid 10001, read-only, capabilities dropped); PDFs are capped at 50 MB, each pdftotext/tesseract call at 300 s, each document at 600 s, every hit a typed failure row; failed alerts are re-sent the next night. Inside OPD (`GP_EXPORTS_DIR`) a night with no changed export files took 96.8 s wall on a copied snapshot with 0 bytes of export transfer; a night re-scanning three days of OPD's changes (80.6% of the docs bytes) is about 21.8 min (derived). The evidence site is static and makes no third-party request (fonts self-hosted).

## 5. Results without a model: schema verdict, census, repair

![fig2](docs/figures/fig2_matrix.png)
*Figure 2. Where each schema field comes from, per parliament (all 89 in `results/census/matrix.csv`). Orange = no source in OPD for that parliament, not a different concept.*

**Where the value lives.** A field is *feasible* if OPD metadata carries it in ≥ 80% of eligible parliaments, *fundamentally different* (needing a different concept) if ≥ 20% have no written source, else *partial* (written down before computing). **4 feasible** (submission date, answer-event date, procedural history, answer-link status), **13 partial**, **0 need a different concept**: no field is orange in a fifth of the parliaments; at a 10% threshold 5 fields would be (`results/census/tier_sensitivity.json`). Type is harmonised for 82.9% of affairs, procedural state for only 278; the government recommendation is in metadata for 34.2% of motions and postulates and PDF-only in 56 bodies.

**What the value means** (`results/census/comparability.json`; classes `data/schema/field_verdict_classes.json`):

| class | fields and concepts | evidence |
|---|---|---|
| shared | submission date, submitter, co-signatories, addressed body, recommendation, decision and dispatch dates, Q/A pairing, related affairs, language, usable text, link status | one meaning; only where the value lives differs |
| shared with a role split | **answer date**, procedural history, type, procedural state, decision outcome | in 7 of 54 bodies the "answer" event is mostly the submission date; OPD's event equals the printed date for 37 held-out documents and differs for 7; 35 event labels carry different date roles; 42 of 1,038 type labels map to different harmonised types ("Antrag" alone to 7); 32 state, 3 outcome labels ambiguous |
| body-specific | oral answers, executive-own business, minutes-only councils | 23.6% of question time is oral; 16 bodies publish only meeting documents, 8 without any affair → `virtual` affairs (P4) |

29.1% of events have no harmonised id. Where OPD metadata carries a field it mostly agrees with print (P3: type 17/18, submitter 23/28, submission date 15/21; affair numbers 21/29, format differences). Five schema gaps recur across 12 bodies. **Cross-parliamentary question:** across 54 parliaments, 82.3% of written answers have their text in OPD (85.0% after the measured repairs); the median government answers in 68 days (69 without the 7 same-day bodies; Question time 5). The site compares answer times within one intervention type and shows 31 parliaments with almost no answers in OPD (cantons SZ, UR, GL, AI, NW, GE) as a coverage gap, not as unanswered questions.

![fig3](docs/figures/fig3_be_before_after.png)
*Figure 3. Bern: answers attached to their affair today vs linkable within OPD.*

**Repair.** Bern: 229 attached, 527 under an agenda item, 2,638 parentless with the canton's document uid; 179 parentless answers are not missing (155 affairs already have the text, 24 have no answer event). Checked against OPD's own copy, all 2,459 relink candidates match affair number and heading; the decision date equals OPD's event for 2,332 with the registered parser and 2,421 [97.9, 98.9] with a parser written afterwards (pre-registered sample: 36/40, three parser misses and one canton typo). **Counts per file:** 2,459 relink candidates = 2,421 in `repair_BE_relink.tsv` + 38 in review; 49 fetch candidates = 48 in `repair_BE_fetch.tsv` + 1 in review (`repair_BE_review.tsv`, 39 rows; reconciliation: site `#bern-numbers`). A second list corrects 727 Bern `begin_date` load timestamps (557 on 2024-10-28 + 170 from later loads, the groups OPD described; 554 from the affair's own submission event). Federal placeholders (57.3% of federal documents): Fedlex recovers 40/50 [67, 88.8]. Scans: DE+FR+IT OCR recovers 15/15 [79.6, 100].

## 6. Evaluation: five pre-registrations

**Design.** Every test froze code, prompts, θ and the scorer by sha256 before any label was committed: the LOCK commit precedes the label commit by 6 min 0 s (P1), 2 min 28 s (P2), 3 min 37 s (P3), 4 min 3 s (P4) by commit date (P3b: LOCK5 before the draw), an order GitHub's clock confirms (`results/eval/lock_server_times_all.json`); the annotation files carry no timestamps, so the clock proves order only. Unit: one document's answer date, strict. Arms on identical inputs: **rules**; **pointer** (Apertus on every document); **cascade** (rules, then the pointer on the residue = every review suggestion accepted); **naive** free generation, plain and null-allowed, same weights. **Gold without human labels, by design:** two blind agent annotators (Claude Opus, Sonnet), quotes verified by code, a third breaks ties (order randomised in P2), raw annotations committed, so labels and κ recompute and the protocol reruns on any set. Non-LLM sources agree where they exist: of 64 P1 answer dates, 44 are checkable; OPD's event matches 37/44 and 5 of the 7 others are 1–5 days apart (decision vs dispatch); Ticino titles 20/20; P3 answer dates 18/21. P2 is thin: 6 of 29 checkable, 6/6 agree. **Deviations** (post hoc, `eval/prereg*/DEVIATIONS*.md`): D5 and D2-4, the frozen naive scorer dropped DD-MM-YYYY answers (re-parsed rows below); D6, the Branch-B consequence as carried out; D7, what the lock clock shows; D8, tie-break audit (the Opus tie-breaker sided with the Opus annotator in 36/41 P1 ties, 35 on the recommendation only) and the non-LLM checks; D2-5, the registered test population, the strongest baselines and θ = 0; D3-5, P3 had no development set.

**P1 — 154 held-out documents from the parliaments the rules were written for** (DE/FR/IT × canton/commune + Ticino scans; 64 with an answer date, 90 without; always-null 90/154; κ 0.95 presence, 0.94 date; 41 tie-breaks).

| arm | exact [95% CI] | dates found | wrong printed date | fabricated | values on answerless |
|---|---|---|---|---|---|
| **rules only (default mode)** | **135/154 [81.5, 92]** | 47 | 4 | 0 | 2 |
| pointer | 130/154 [77.9, 89.3] | 46 | 16 | 0 | 6 |
| cascade (suggestions accepted) | 139/154 [84.6, 94] | 56 | 11 | 0 | 7 |
| 8B pointer (CPU, exploratory) | 112/154 [65.2, 79.1] | 50 | 37 | 0 | 28 |
| 8B cascade (CPU, exploratory) | 119/154 [70, 83.2] | 54 | 31 | 0 | 25 |
| naive, null-allowed | 134/154 [80.8, 91.4] | 47 | 11 | 0 | 3 |
| ↳ null-allowed, re-parsed (D5) | 133/154 [80.1, 90.9] | 47 | 13 | 0 | 4 |
| naive, plain | 98/154 [55.8, 70.8] | 47 | 23 | 24 | 39 |
| ↳ plain, re-parsed (D5) | 103/154 [59.1, 73.8] | 54 | 26 | 24 | 41 |

*8B rows* (§3; its registered hypotheses: H1 fails; Branch B, FR+IT+scans rules alone right on 10, cascade alone on 2, p = 0.039; H3 AUROC 0.854). 70B: **H1 null safety failed**: the cascade dates 7 of 90 answerless documents (upper bound 15.2% vs 10%). **H2 gave Branch B** (FR+IT+scans, n = 110: cascade alone right on 5 documents, rules alone on 1, p = 0.22). The registered consequence keeps Apertus only where it measurably adds null safety, and it adds none (cascade 7/90 answerless dated, rules 2/90); we removed it from the unattended path (default `rules_only`) and kept it as an opt-in review suggestion, a departure logged in D6, which P2 then tested on unseen parliaments. **H3 passed**: AUROC 0.969 on all documents, 0.966 on the registered length-matched set. **H4 triggered**: 3 of 8 Apertus-decided FR/IT values are wrong. Post hoc: latest printed date on answer-typed documents 131/154 (vs pointer 11:12 documents, p = 1).

**P2 — 62 documents from 15 parliaments absent from every dev and held-out set** (29 with an answer date, from 7 of the 15: VD 8, NW 6, Bellinzona 5, OW 4, Vernier 3, SZ 2, Schlieren 1; 33 without; always-null 33/62; κ 1.0).

| arm | exact | dates found | wrong printed date | fabricated | values on answerless |
|---|---|---|---|---|---|
| rules only | 35/62 | **2/29** | 2 | 0 | 0 |
| **pointer** | **53/62** | **24/29** | 8 | 0 | 4 |
| cascade | 51/62 | 22/29 | 10 | 0 | 4 |
| naive, null-allowed | 52/62 | 22/29 | 7 | 1 | 3 |
| ↳ null-allowed, re-parsed (D2-4) | 54/62 | 24/29 | 7 | 1 | 3 |
| naive, plain | 45/62 | 21/29 | 8 | 4 | 9 |
| ↳ plain, re-parsed (D2-4) | 49/62 | 25/29 | 9 | 4 | 9 |
| *latest date on answer-typed documents (post hoc)* | *44/62* | *18/29* | *13* | *0* | *7* |

**P2-H1**: the rules' recall drops from 47/64 to 2/29. **P2-H2 holds**: on the 29 answered documents, as registered, 22 only the pointer vs 0 only the rules (McNemar p = 4.8 × 10⁻⁷; without Bellinzona 17 vs 0, p = 1.5 × 10⁻⁵); on all 62, 22 vs 4 (p = 5.3 × 10⁻⁴); by parliament (post hoc, D2-1) 6 vs 0, 1 tie (sign test p = 0.031). Against the strongest one-line baseline (latest printed date, null on member texts): 10 vs 1 documents (p = 0.012), 6 vs 0 parliaments (p = 0.031). **P2-H3 failed**: the cascade dates 4/33 answerless documents (upper bound 27.3% vs 15%). **P2-H4 holds**: AUROC 0.983. θ = 0, PREREG2's registered secondary: 54/62. *Error profile:* rules right 35, wrong printed date 2, answerless dated 0, missed 25; pointer 53, 4, 4, 1; cascade 51, 6, 4, 1. The cascade trails the pointer because on 2 documents a rule (`rrb_vom`) fired with a wrong printed date, so Apertus was never asked.

**P3 — whole affairs: 29 affairs (58 PDFs), 10 parliaments (5 with rules, 5 without), DE/FR/IT.** A feasibility study, not a held-out test: extractor, prompts and sample entered in one commit (D3-5). Arms: OPD metadata (M), rules (R), the default metadata + rules (C), C + Apertus suggestions on fields C leaves open (CA); annotators agreed on ≥ 27/29 affairs per field.

| arm | type | number | submitter | submitted | answer date | addressed body* | decision no.† |
|---|---|---|---|---|---|---|---|
| M | 17/29 | 21/29 | 23/29 | 15/21 | 21/27 | 0/28 | 0/17 |
| R | 26/29 | 14/29 | 5/29 | 4/21 | 16/27 | 4/28 | 5/17 |
| **C** | **27/29** | **21/29** | **23/29** | **15/21** | **22/27** | **4/28** | **0/17** |
| CA | 27/29 | 21/29 | 23/29 | 15/21 | 27/27 | 23/28 | 0/17 |

\*Every gold value is "executive"; a constant scores 28/28 (D3-3). †Defect D3-1: the frozen cascade's metadata branch drops the rule's number; post hoc C = 5/17. No field reaches the unattended bar (lower bound ≥ 0.80). H3 (Apertus on open fields) 25/32 recall, 25/34 precision is dominated by the near-constant field, so the addressed-body claim is withdrawn; without it 6/8 and 6/9. Set fields (C, registered): co-signatories precision 13/16, recall 13/29 (OPD metadata); related affairs 6/9, 6/14 (rules). **P3b, held-out replication** (PREREG5; 36 fresh affairs, 9 parliaments, D5-1; κ ≥ 0.97 per field): *replicated* as registered. Apertus on open fields recall 14/16 [64, 96.5]; 4 of 5 eligible fields within or above P3's CIs, answer date below (C 20/35; with Apertus 31/35, its 11 suggestions 11/11 right); precision 14/20 keeps the reviewer gate; type 35/36 reaches the unattended bar.

**P4 — virtual affairs: 6 held-out sittings of Bulle's council, 120 agenda items.** Rules derive 99 items (precision 99/99, titles 99/99), type 91/99 (H2 holds), the decision for 49/63 (46/63 correct), invent none of 36, and date all 6 sittings (H4 holds). **H1 failed** (recall 99/120, 82.5%; sub-items, unnumbered lines); **H3 failed** (Apertus +2 decisions, p = 0.5). Transfer cell (2 sittings of La Chaux-de-Fonds, D4-4): items 9/9, titles 9/9, decisions 0/9 by rules, 2/9 found with Apertus (1 correct): decision parsing is commune-specific.

![fig5](docs/figures/fig5_scoreboard.png)
*Figure 5. Scoreboards of P1 and P2 (frozen code).*

**What the tests say.** Apertus earns its place where layout varies and no rule exists: unseen parliaments (P2: 24/29 answer dates vs 2/29; 10:1 documents and 6:0 parliaments against the strongest trivial baseline) and the answer date of whole affairs (P3: 22/27 → 27/27; P3b: 20/35 → 31/35). Where structure is regular (P1, P4) rules suffice. **Why the pointer form:** the same Apertus asked freely with a null-allowed prompt is as accurate (P2 re-parsed 54/62 vs 53/62; discordant 1 vs 0, p = 1), but every pointer value is a printed date with page and span (32/32) and its margin orders the review queue (strong band 26/33 right, weak 3/11, post hoc), while the free prompt quotes its date verbatim for 17/32 values and invents dates printed nowhere (1 in P2; the plain prompt 24 in P1).

## 7. Limitations

Answer dates are the field tested in depth; P3/P3b are small (29 + 36 affairs), P4 one commune. No gold set contains federal documents; the pointer sees at most 12,000 characters. No human labelled a gold value; non-LLM sources check 44 of 64 P1 answer dates but only 6 of 29 in P2. θ must be refitted per build. 10,800 missing written answers need source adapters that are not built; spans index our own pdftotext/tesseract text (`--opd-text` maps them onto OPD's).

## 8. Reproducibility

`make run` (Docker, CPU, clean checkout) recomputes the census, replays the Bern join and triple check, converts sample documents with all validator checks, re-scores P1–P4 from the committed predictions and labels, re-runs the four registered hypothesis scripts, verifies the four LOCK files, re-derives the P1 rules arm from the source PDFs fetched by sha256, recomputes P1 and P2 Apertus decisions from the committed model cache within a time budget, and re-checks the 721 numbers listed in `claims.tsv` against their results files (matched as whole tokens; values of ≤ 3 characters pinned by a context phrase). Locally: rules 154/154, Apertus 154/154 (P1) and 62/62 (P2) identical. In CI's Docker run (38049690293, `results/ci/`) 140 of 154 rules re-derivations fit the budget, all identical; recomputed Apertus decisions matched 129/129 (P1; 25 cache misses from the image's older poppler) and 7/7 (P2; 8 hosts unreachable, 46 over budget); 641 claims, 0 failing.

## 9. Declarations

Claude Code agents (Anthropic) wrote most code, documentation and the gold labels; numbers are checked by code (`claims.tsv`, lock hashes, verbatim quotes, re-derivation), not by reading. Public AI (which may route outside Switzerland) was used for development and evaluation only.

## 10. Next steps

Hand the Bern and placeholder lists to OPD and run the nightly job beside their importer; build source adapters for the 10,800 written answers that exist only at the source; date roles, `QAItem` and the five schema gaps in schema v0.2 with the eCH group; per-commune decision parsing and sub-item segmentation (the P4 gaps).

Report CC-BY-4.0 (`docs/LICENSE-report.txt`). References: OpenParlData exports; Bern Grosser Rat open data; Fedlex; Apertus v1.5 model cards; Popolo, Akoma Ntoso (`docs/mapping.md`).
