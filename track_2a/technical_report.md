# Technical report — Gegenprobe: where Swiss parliamentary answers go missing, how to put them back, and a converter that cannot invent

**Track 2A — OpenParlData** · Online · Team 444 — Roman (+ Claude Code agents, §9) · Evidence site https://gegenprobe.mi11ion.io · `make run` re-scores every headline and re-derives the rules arm from source PDFs (§8) · **Maturity:** census, repair lists, nightly job = *deployable prototype*; PDF-to-schema extraction = *feasibility study*.

## 1. Summary

**Promise and reality.** OpenParlData (OPD) publishes the affairs of 89 Swiss parliaments with affairs in scope (it scrapes 90) "to create transparency, promote participation and enable data-based political education". Of 91,268 interventions whose events record a written government answer, **16,749 (18.4%) have no answer text in OPD** (2024–25: 1,855, 14.3%); we type every one by cause. In Bern the canton publishes 3,532 answers and OPD attaches 229 (6.5%), although 96.1% are already in OPD and linkable; OPD confirmed the bug (correspondence, 10 Oct 2026) and our relink list is the best interim workaround until its fix ships.
**Schema.** The concepts are shared; what differs is where the value lives, the vocabulary and the date roles. Of 17 fields, **4 are feasible** from OPD metadata alone, **13 partial**, **0 fundamentally different** at our thresholds; 42 raw affair-type labels mean different harmonised types in different parliaments, and "answer date" is at least three dates.
**Converter.** Apertus may only *point* at a value printed in the document, or say null; every value carries page and character span. Four pre-registered tests show where it earns its place. On the parliaments our rules were written for, rules are exact on 135/154 and Apertus adds nothing significant, so rules run unattended. On **15 parliaments the rules never saw, the rules find 2/29 answer dates and Apertus finds 24/29** (exact McNemar p = 4.8 × 10⁻⁷). On 29 whole affairs from 10 parliaments, metadata and rules fill most fields and Apertus finds the addressed body (rules 4/28, with Apertus 23/28). For a commune that publishes only minutes, rules derive 99 virtual affairs with item precision 99/99 and no invented decision. Apertus's values are review suggestions, because it still dates 4/33 documents that carry no answer.

## 2. Architecture

1. **Census** (`census/`): streams the OPD exports once, keeps metadata only, and computes the answer funnel, a per-affair *answer-link status* (`attached | agenda | parentless | absent | image_only | oral`), the feasibility matrix and a comparability measure from OPD's own vocabularies. A vendored extract (`data/census/`) lets `make run` recompute every census number.
2. **Repair** (`repair/`): deterministic routes per cause, verified by a triple check (affair number printed, answer heading present, decision date = OPD's answer event), written in OPD's export layout. A nightly job (`deploy/nightly/`, `docs/runbook.md`) re-runs the joins and raises alerts.
3. **Converter** (`convert/`): per document, (i) OPD metadata and events, (ii) frozen DE/FR/IT anchor rules, (iii) the Apertus closed-set pointer on the residue. Modes: `rules_only` (default, unattended, no model) and `review` (pointer values attached as suggestions with page, span and margin, flagged `needs_review`). CLI with batch mode (`docs/convert-your-own.md`).
4. **Schema and validator** (`schema/`, `validate/`): Pydantic schema v0.1; every field is a value with provenance `{value, role, page, char_start, char_end, quote, route, rule, model_build, θ, margin}` or a *typed null* (`not_in_document | unlinked | image_only | oral | text_failed | present_unanchored | not_applicable`); span re-check, typed-null consistency, footer-distractor and self-deletion tests; a JSON Schema export for OPD's Pydantic-based workbench.

![fig1](docs/figures/fig1_funnel.png)
*Figure 1. National answer funnel with typed causes and repair routes.*

## 3. Use of Apertus

**Closed-set pointer** (`convert/pointer.py`, prompts `src/prompts/{de,fr,it}`). The user message holds the document (first 12,000 characters) and the question; the assistant turn is prefilled with a JSON prefix (`{"antwort_datum":`); `null` and every distinct date printed in the document are scored as continuations by summed log-probability (exact forced choice via `prompt_logprobs`). Null if `lp(null) − logsumexp(lp(dates)) > θ`, else the best date, mapped back to its span. θ does not transfer across builds (spike F2: a θ fitted on RLVR scores 0.25 on the final build), so it is fitted per build on dev documents and frozen: θ = 10.40 for the Public AI build (AUROC 0.99, leave-one-out 124/127 [93.3, 99.2]).

**Why a pointer** (earlier spikes, cited, `results/report/cited_spikes.json`). Asked freely when the government answered, Apertus writes a precise date for 15/15 (local 8B) and 14/15 (70B) Bern interventions that have no answer, often copying the "Letzte Bearbeitung" footer, and a verbatim-quote check approves 10/15 of the local inventions; a null-allowed prompt fixes this on the 70B (0/15) but not on the 8B (14/15). Asking for the *role* of each date failed (AUROC 0.57).

**Which Apertus.** Evaluation ran through a budget gateway (hash cache, call log) on Public AI, and the 8B GGUF on CPU runners. Public AI's `swiss-ai/apertus-v1.5-8b` name serves the **70B** weights (cited: 760/792 greedy outputs byte-identical to the 70B name; MMLU 84.4% vs 70.8% for the v1 8B route), so its results are labelled 70B; a system message or prefill to the `-70b` name is answered by Qwen-SEA-LION (3/3), so forced choice goes only to the `-8b` name and the response `model` field is checked on every call. For the 8B GGUF Q4_K_M, our llama-cpp-python scorer agrees with bf16 on 58/60 decisions (mean |Δ| 2.66 nats), as close as the spike's Metal build (57/60, 2.87); a stricter parity rule fixed in advance failed (10/12, 3.16 nats) because implementations of one file differ from each other by that much (`results/eval/gguf_impl60.json`).

**Where it earns its place.** Where layout varies: on unseen parliaments it is the extraction (§6, P2), and on whole affairs it supplies the field no rule anchors (P3, addressed body). Where structure is regular — known layouts (P1: 16/67 of the cascade's values) and council minutes (P4) — rules suffice. It never writes a value unattended.

**Cost.** Rules only: about 0.5 CPU-hours for all 902,754 documents in OPD's export. Review mode runs the pointer on the rules' residue (97 of 154 held-out documents): 3.5 calls and 5,905 billed prompt tokens per residue document (`results/report/cost.json`).

## 4. Data

OPD bulk exports (affairs, events, agendas, docs, texts, contributors; snapshot 6 Oct 2026, contributors 9 Oct). `api.openparldata.ch/robots.txt` disallows `/v1/` for all agents (its comment says it targets search crawlers); we used the bulk exports, which also makes every number reproducible from a dated snapshot. Bern open data (`ogd.parl.apps.be.ch`), Fedlex SPARQL and filestore, source PDFs fetched politely (one User-Agent without personal data, ≥ 1.2 s per host, robots.txt honoured). `data/` holds ids, URLs, hashes, labels and quotes of ≤ 200 characters; no full texts, no personal contact data. Code Apache-2.0, report CC-BY-4.0, data CDLA-Permissive-2.0.

## 5. Results without a model: schema verdict, census, repair

![fig2](docs/figures/fig2_matrix.png)
*Figure 2. Where each schema field comes from, per parliament (all 89 in `results/census/matrix.csv`).*

**The verdict.** A field is *feasible* if OPD metadata carries it in ≥ 80% of eligible parliaments, *fundamentally different* if ≥ 20% have no written source, else *partial* (written down before computing; criteria and matrix were committed together). **4 feasible** (submission date, answer-event date, procedural history, answer-link status), **13 partial**, **0 fundamentally different**; at a 10% no-source threshold 5 fields would be (`results/census/tier_sensitivity.json`). Type is harmonised for 82.9% of affairs, procedural state for only 278; the government recommendation is in metadata for 34.2% of motions and postulates and PDF-only in 56 bodies.

**Availability is not comparability** (`results/census/comparability.json`). In OPD's vocabularies 42 of 1,038 raw affair-type labels map to different harmonised types in different parliaments ("Antrag" alone to 7), 35 event labels carry different date roles ("Beantwortet" is *answered* in some bodies, *submitted* in others), and 29.1% of events have no harmonised id. **"Answer date" is a split concept:** in 7 of 54 bodies the "answer" event is mostly the submission date, and on our held-out gold OPD's event date equals the date printed in the answer for 37 documents and differs for 7 — later registration or publication dates, once a filing date. A common schema needs date roles (decided, dispatched, registered). Where OPD metadata carries a field it mostly agrees with print (P3: type 17/18, submitter 23/28, submission date 15/21; affair numbers 21/29, format differences). Concepts split where answers are oral (20.7% of Question time; Valais files 1,008 oral answers as stub documents), where the executive acts on its own business, and where communes publish only meeting documents (16 bodies, 8 without any affair; schema v0.1 marks derived affairs as `virtual` with `derived_from`, exercised on 99 real agenda items in P4). A rule-based inventory over 12 bodies found five recurring schema gaps; estimating the *size* of the missing schema with Chao2 failed both pre-registered checks (≈ 57.4 new accounts per body, no saturation).

**Cross-parliamentary question.** Across 54 parliaments, 82.3% of written answers have their text in OPD (85.0% after the measured repairs); the median government answers in 68 days (69 without the 7 same-day bodies; Question time 5).

![fig3](docs/figures/fig3_be_before_after.png)
*Figure 3. Bern: answers attached to their affair today vs linkable within OPD.*

**Repair.** Bern: 229 attached, 527 under an agenda item, 2,638 parentless with the canton's document uid; the relink list holds 2,459 relinks and 49 fetches, the other 179 parentless answers are not missing (155 affairs already have the text, 24 have no answer event). The spike sample verifies 40/40 [91.2, 100] and OPD's answer event equals the decision date 39/39; checked against OPD's own copy, all 2,459 relinks match affair number and heading, and the decision date equals OPD's event for 2,421 [97.9, 98.9] (the rest go to review; a pre-registered sample of 40 had 36/40, three parser misses and one canton typo). A second list corrects 727 Bern `begin_date` load timestamps (557 on 2024-10-28 + 170 from later loads, the groups OPD described; 554 from the affair's own submission event). Federal placeholders (57.3% of federal documents store Fedlex's "JavaScript required" page): Fedlex SPARQL plus filestore recovers 19/20, and 40/50 [67, 88.8] fresh; the 29,946-document backlog takes about 17.5 h once. Scans: 15/30 "text-missing" answers are image-only (13 are Valais stubs); DE+FR+IT OCR recovers 15/15 [79.6, 100], keeping 467 accented characters where English OCR keeps 133. From outside OPD the nightly job re-downloads most exports (68/116 files changed within three days).

## 6. Evaluation: four pre-registrations

**Design.** Every test freezes code, prompts, θ and the scorer by sha256 before any label exists (`eval/prereg/LOCK`, received by GitHub at 2026-10-09T19:38:07Z, labels at 2026-10-09T19:44:06Z; `LOCK2`–`LOCK4`). Unit: one document's answer date, strict. Arms on identical inputs: **rules**; **pointer** (Apertus on every document); **cascade** (rules, then the pointer on the residue = every review suggestion accepted); **naive** free generation, plain and null-allowed, on the same weights. Gold: two blind annotators (Claude Opus, Sonnet), quotes verified by code, a third decides disagreements; no human labels by design; raw annotations committed, κ recomputes. Deviations D1–D4 (`eval/prereg/DEVIATIONS.md`): Ticino scans prompted in German by the frozen code; a faster GGUF scorer behind a parity gate; the 8B θ fitted without spike items; a stale sentence in a locked file, H3 computed on all documents, two unhashed helper files.

**P1 — 154 held-out documents from the parliaments the rules were written for** (DE/FR/IT × canton/commune + Ticino scans; 64 with an answer date, 90 without; κ 0.95 presence, 0.94 date, 148/154 identical; 41 tie-breaks, order not randomised; OPD oracle 37 agree / 7 differ).

| arm | exact [95% CI] | dates found | wrong printed date | fabricated | values on answerless |
|---|---|---|---|---|---|
| **rules only (default mode)** | **135/154 [81.5, 92]** | 47 | 4 | 0 | 2 |
| pointer | 130/154 [77.9, 89.3] | 46 | 16 | 0 | 6 |
| cascade (suggestions accepted) | 139/154 [84.6, 94] | 56 | 11 | 0 | 7 |
| naive, null-allowed | 134/154 [80.8, 91.4] | 47 | 11 | 0 | 3 |
| naive, plain | 98/154 [55.8, 70.8] | 47 | 23 | 24 | 39 |
<!-- SLOT: 8B rows -->

*Outcomes as registered.* **H1 null safety failed**: the cascade dates 7 of 90 answerless documents (upper bound 15.2% vs 10%; 4 in one cell). **H2, Branch B**: on FR+IT+scans (n = 110) the cascade alone is right on 5 documents, the rules alone on 1 (p = 0.22; pooled 9 vs 5, p = 0.42); Apertus does not measurably add null-safety, so rules run unattended and Apertus's answers are review suggestions. **H3 passed**: the null margin separates the classes, AUROC 0.969. **H4 triggered**: 3 of 8 Apertus-decided FR/IT values are wrong.

**P2 — 62 documents from 15 parliaments absent from every dev and held-out set** (29 with an answer date, 33 without; always-null 33/62; annotators agreed on every date, κ 1.0; tie-break order randomised).

| arm | exact | dates found | wrong printed date | fabricated | values on answerless |
|---|---|---|---|---|---|
| rules only | 35/62 | **2/29** | 2 | 0 | 0 |
| **pointer** | **53/62** | **24/29** | 8 | 0 | 4 |
| cascade | 51/62 | 22/29 | 10 | 0 | 4 |
| naive, null-allowed | 52/62 | 22/29 | 7 | 1 | 3 |
| naive, plain | 45/62 | 21/29 | 8 | 4 | 9 |

*Outcomes as registered.* **P2-H1**: the rules' recall drops from 47/64 to 2/29. **P2-H2 (primary) holds**: 22 answered documents only the pointer gets right, 0 only the rules (p = 4.8 × 10⁻⁷); without Bellinzona, whose letterhead one rule happens to match, 17 vs 0 (p = 1.5 × 10⁻⁵); the same at θ = 0. **P2-H3 failed**: the cascade dates 4/33 answerless documents (upper bound 27.3% vs 15%). **P2-H4 holds**: AUROC 0.983. Registered consequence: review mode is recommended for parliaments without rules.

**P3 — whole affairs: 29 affairs (58 PDFs), 10 parliaments (5 with rules, 5 without), DE/FR/IT.** Arms: OPD metadata (M), rules (R), the default metadata + rules (C), C + Apertus suggestions on fields C leaves open (CA); annotators agreed on ≥ 27/29 affairs per field.

| arm | type | number | submitter | submitted | answer date | addressed body | decision no. |
|---|---|---|---|---|---|---|---|
| M | 17/29 | 21/29 | 23/29 | 15/21 | 21/27 | 0/28 | 0/17 |
| R | 26/29 | 14/29 | 5/29 | 4/21 | 16/27 | 4/28 | 5/17 |
| **C** | **27/29** | **21/29** | **23/29** | **15/21** | **22/27** | **4/28** | **0/17** |
| CA | 27/29 | 21/29 | 23/29 | 15/21 | 27/27 | 23/28 | 0/17 |

*Outcomes.* No field reaches the unattended bar (lower bound ≥ 0.80; type closest); number, type, submitter, submission and answer date are partial. Apertus on the open fields: right for 25/32 of those that have a value (recall holds), 25/34 of its suggestions right (precision below 0.70) → suggestions with a reviewer gate.

**P4 — virtual affairs: 6 held-out sittings of Bulle's council, 120 agenda items.** Rules derive 99 items (precision 99/99, titles 99/99, type 91/99), find the decision for 49/63 (46 correct), invent none of 36, and date all 6 sittings. Recall missed the bar (99/120, 82.5%; sub-items, unnumbered lines); Apertus added 2 decisions (n.s.).

![fig5](docs/figures/fig5_scoreboard.png)
*Figure 5. Scoreboards of P1 and P2 (frozen code).*

**What the four tests say.** Apertus earns its place where layout varies (P2; P3 addressed body); where structure is regular (P1, P4) rules suffice, and the system uses Apertus only as reviewed suggestions. A well-prompted 70B is about as accurate on answer dates (P1 134 vs 139; P2 52 vs 53) but can fabricate (1 in P2, 24 with the plain prompt in P1) and returns no span; the pointer cannot fabricate by construction and its margin separates answered from answerless documents in P1 and P2. Its errors are misattributions — real session or publication dates in reports and minutes.

**Post hoc (not registered; `results/eval/robustness.json`).** Always-null scores 90/154 in P1; the cascade's gain over the rules is +3.6 points on FR+IT+scans (95% CI −1.4 to 9.3; detectable effect 6.2): inconclusive, not zero. The cascade is right on 55/60 answer documents vs the rules' 47/60 and loses on reports; asking Apertus only on documents typed as answers would give 143/154 with 2/90 values on answerless documents; θ 0–2.5 would give 142–143. Hypotheses for the next registration, not results. With the Italian prompt the pointer goes from 17/22 to 21/22 on Ticino scans.

## 7. Limitations

Answer dates were tested in P1/P2, whole affairs on 29 (P3), minutes in one commune (P4); recommendation and decision numbers have too little gold to judge. No gold set contains federal documents; the pointer sees at most 12,000 characters. Gold labels come from AI annotators with high agreement and an external oracle check, not from humans. The 70B results come from one provider build (one vLLM fingerprint); θ must be refitted per build. 11,206 missing answers need source adapters that are not built; OCR was measured on a probe. Spans index our own pdftotext/tesseract text, not OPD's stored text.

## 8. Reproducibility

`make run` (Docker, CPU, clean checkout) recomputes the census, replays the Bern join and triple check, converts sample documents with all validator checks, re-scores every evaluation file from its per-document rows, re-derives the rules arm from the source PDFs fetched by sha256 (locally 154/154 identical to the committed predictions) and recomputes every number here from `claims.tsv` (cited spike figures marked as such); CI fails on any drift. Model outputs replay from a hash-keyed cache; with `LLM_BASE_URL` or `GGUF=1` a live slice runs.

## 9. Declarations

Claude Code agents (Anthropic) wrote most code, documentation and the gold labels under the protocols above; numbers were checked by code (spike numbers reproduced cell-for-cell, `claims.tsv`, lock hashes, verbatim quotes, re-derivation), not by reading. No human labelled or adjudicated any gold value, by design. Public AI (which may route outside Switzerland) was used for development and evaluation only. The default mode needs no model and contacts only the sources it repairs; review mode adds a local GGUF or the endpoint the operator chooses.

## 10. Next steps

Hand both Bern lists and the placeholder list to OPD and run the nightly job beside their importer; build source adapters for the 11,206 answers that exist only at the source; date roles and the five schema gaps in schema v0.2 with the eCH group; pre-register θ = 0 and type-gating; rules for decision numbers and sub-item segmentation (the P3 and P4 gaps); virtual affairs for the other bodies on the frontier (`results/census/virtual_affairs.json`).

## License and references

Report CC-BY-4.0 (`docs/LICENSE-report.txt`). OpenParlData exports; Bern Grosser Rat open data; Fedlex; Apertus v1.5 model cards; Chao (1987); Popolo, Akoma Ntoso (`docs/mapping.md`).
