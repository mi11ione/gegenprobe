# Technical report — Gegenprobe: one schema and a converter for Swiss parliamentary answers

**Track 2A — OpenParlData** · Online · Team 444 — Roman (+ Claude Code agents, §7) · Evidence site https://gegenprobe.mi11ion.io

| maturity | components |
|---|---|
| *ready to apply* · *ready to deploy* | census and Bern repair lists (relinks: one OPD decision, its hash rule) · nightly job (three real nights on standard GitHub runners: one with the venv unit, 10 Oct, and two consecutive with the Docker unit, 11 Oct) |
| *audited* · *tested prototype* | source-adapter lists · rules-only converter |
| *feasibility study* · *drafts for the eCH group* | review mode, whole and virtual affairs · schema v0.1 and v0.2 (P8's roles) |

## 1. Summary

**Abstract.** *Question:* can one schema hold the business of Switzerland's communal, cantonal and federal parliaments, in German, French and Italian? *Answer:* **Yes, if each field says which role its value plays** (e.g. "answer date" = the government's decision, its letter or the submission date), for the 17-field skeleton of OPD's five intervention types (198,594 of its 325,691 affairs); outside interventions the skeleton does not carry over as is (P11, exploratory). *Delivered:* repairs for 9,580 answers keyed on OPD ids, every one from model-free rules; schema v0.2 with the roles; a converter that gives every value its page and span; a nightly job. *Apertus's role:* Apertus only picks values printed in the document, and code locates them; where nobody wrote rules it finds 24/29 answer dates, against 18/29 for the model-free baseline of the date test (P2), and a reviewer confirms each; the default runs no model. *Cost:* the rules take about 0.5 CPU-hours for all 902,754 documents in OPD's export, about 5 at ten times OPD's volume; review mode costs USD 0.59 per 1,000 residue documents on the 70B (§3).

| verdict | fields | example |
|---|---|---|
| needs roles | **10** (8 robust + 2 fragile; 6 from the role test P8, registered, 4 from OPD's labels, post hoc) | "answer date" is the decision, the letter or, in 7 parliaments, mostly the submission date |
| body-specific | **1 field and 2 constructs** | submission date printed in neither document in Vernier (5/5 affairs) and Lausanne (3/5); oral answers; minutes-only councils |
| untested | **6**, defined once in v0.1 | decision and dispatch dates, Q/A pairing, related affairs, usable text, answer-link status |
| outside interventions | 7 fit, 4 do not apply, 6 need new roles (P11, exploratory, 15 affairs) | the executive as proposer: adopting, endorsing and signing its own proposal |

Every value carries its role and source (page and span, or the OPD record), every gap a typed reason. **What would have meant No** (proposed in review): a field body-specific in 2 or more parliaments for reasons of practice rather than OPD's data, or values outside every named role; the one body-specific field is a split between OPD's date and the documents. The statements inside an answer are a layer of their own (45.9% had no schema account in an inventory over 12 bodies).

| | |
|---|---|
| **92.1%** | of interventions with a recorded government answer would have answer text once the proposed repairs are applied, up from 81.6% today: 91.5% from row-checked repairs + 0.6 points from the 592 agenda joins and 39 review rows |
| **9,580** | answers with a model-free repair proposed to OPD, keyed on OPD ids: 3,621 apply now, 2,459 Bern relinks follow OPD's hash decision, 3,500 are fetched; the Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation |
| **186** | v0.2 records from 26 parliaments validate: the converter's 120 (105 cantonal and communal + 15 federal, 23 parliaments) and P8's 66 gold records (11 parliaments); the converter's records hold a value in 1,149 of their 2,040 field-record pairs (`field_completeness.json`) |

*Glossary.* **P1–P8, P10**: the ten tests (P3b replicates P3), each frozen by hash before its labels (§6). **D-numbers**: logged deviations from a registration. **Post hoc**: analysed after the labels, often proposed in review; **registered**: decided by the frozen rule.

**Schema.** P8 finds roles in authorship, co-signatory lists, the instrument behind a harmonised type and the language (text, OPD's tag and the affair's can differ). The converter fills v0.2's roles with fixed rules (75 of its 105 records carry printed authors with their role); on 5 parliaments its rules never saw, the language is right on 60/60 documents and author (name, role) pairs reach precision 39/49 at recall 39/137 (exploratory).

## 2. Architecture

**Census** (`census/`) streams the OPD exports once into a per-affair *answer-link status*, the feasibility matrix and a comparability measure, and places every registered gap row once the repair routes have looked (Fig. 1). **Repair** (`repair/`): deterministic routes per cause, each row checked, as lists keyed on OPD ids; a nightly job re-runs the Bern route. **Converter** (`convert/`, `qa/`): OPD metadata and events, then frozen DE/FR/IT anchor rules, then the Apertus closed-set pointer on the residue; modes `rules_only` (default, no model) and `review` (suggestions with page, span and margin, flagged `needs_review`). **Schema and validator** (`schema/`, `validate/`): Pydantic schema v0.1, normative; a value carries its role, page, span, quote hash, route and rule, a null its typed reason (`data/schema/null_reasons.json`); `QAItem` pairs question *n* with its answer passage.

<img alt="fig1" src="docs/figures/fig1_funnel.png" style="width:74%;max-height:none;display:block;margin:0 auto">
*Figure 1. The registered 16,749 placed once each (`results/census/corrected.json`). Still to find: 5,213 (1,079 of them already waiting for a person).*

## 3. Use of Apertus

| Apertus result | what Apertus adds | what the model-free baseline reaches |
|---|---|---|
| **24/29** answer dates on new layouts (the date test, P2; 15 parliaments without rules) | exact on 53/62 documents against the baseline's 44/62: right on 10 where it is wrong, the reverse on 1 (exact McNemar p = 0.0117, post hoc) | the latest date on answer-typed documents: 18/29 answer dates, 44/62 exact; registered: the rules 2/29 |
| **50/141** author roles in 14 parliaments without rules (the author test, P10) | Apertus adds precision deciding who is an author (+7.3 points, post hoc) | Rules 17/141; most of the gain comes from the model-free candidate finder (document order 52/141) |
| **139/154** answer dates where rules exist (P1; rules, then Apertus) | about one document | a model-free cascade (post hoc): 138/154 |
| **120/120** sampled review-queue promotions are answers (P7, registered) | the date: the gold answer date on 113/120 of its promotions, the rule's on 127/146 (post hoc, not paired) | a no-model exact-date match: answers on 146/146, 206 of the 478 frame rows promoted against Apertus's 135 (post hoc) |
| **12/12** Italian answer dates (P11, exploratory) | author roles: the role reader F1 0.32 | latest date on the answer 9/12; roles: the converter's record F1 0.30, document order 0.22 |

*Sources: 24/29 from P2, registered against the rules (the baselines post hoc, proposed in review); 50/141 from P10, registered (recall +23.4 points over the rules, Holm p = 0.032), level with OPD's contributor list (37/141; H3a, Holm p = 0.17); the author filter's +7.3 points: one-sided p = 0.012, uncorrected.*

**Closed form only.** Apertus never writes a value. (i) *Verifier* (P7, `repair/adapters/adjudicate.py`): for an adapter review row it answers "does this document print the executive's answer to this intervention (number, title)?" (yes vs no scored after a JSON prefix, θ_A = 8) and picks the answer date among the printed dates or none (θ_B = 10); a row is promoted only if both pass and the date passes the adapters' own date rule. (ii) *Pointer* (`convert/pointer.py`, prompts `src/prompts/{de,fr,it}`): the document (first 12,000 characters) and the question in the user message, the assistant turn prefilled with a JSON prefix, `null` and every distinct printed date scored by summed log-probability; null if `lp(null) − logsumexp(lp(dates)) > θ`. Code locates every span (`pointer.locate`). θ does not transfer across builds, so it is fitted per build on dev documents and frozen (θ = 10.40, AUROC 0.99). **Why closed:** asked freely, Apertus dates 15/15 (8B) and 14/15 (70B) Bern interventions that have no answer.

**Which model.** Every committed gateway response (17,720) comes from one build, Apertus 70B by inference (label `swiss-ai/apertus-v1.5-8b`, fingerprint `…tp8-pp2-dd237840`); the response `model` is checked on every call. On 12 Oct 2026 Public AI switched the route to another build (label `swiss-ai/Apertus-v1.5-70B`, fingerprint `…tp2-bfd70257`, other log-probabilities) and, the same night, back. The build guard caught the switch live and stopped P11's role reader, so no result mixes builds; on the registered build again the reader read all 12 affairs (D2). Review mode refused the other build (exit 3) and runs again on the registered θ: a live `convert --mode review` and `affair --mode review --roles apertus` both exited 0 (`results/refit_bfd70257/e2e_live.json`); a θ refit for the other build had 40 of 97 dev documents when the route switched back, and a deployment θ applies only once a preflight request shows its build. The **8B** (`swiss-ai/Apertus-v1.5-8B`, a community 4-bit GGUF, sha256-pinned) runs locally on CPU with its own θ = 16.73 (exploratory): on P2's unseen parliaments the registered P2-H2 test over the rules gives 13 vs 0; its reader v2 cuts dates on answerless documents from 18/34 to 5/34 (P6). As P7's verifier (88 of the 190 annotated rows scored) no θ meets the dev rule, so it promotes nothing. As P10's author-role reader (exploratory) it reads 30/141 pairs right, F1 0.27 against the rules' 0.17 (document order 0.41, the 70B 0.42). **Recommendation:** `rules_only` unattended; local 8B: date suggestions only, where no text may leave the machine; the review-queue verifier and the role reader need the 70B, for accuracy on infrastructure the operator chooses (bf16 weights about 140 GB; `docs/runbook.md`).

## 4. Data and operations

**Data.** OPD bulk exports (snapshot 6 Oct 2026; CC BY 4.0, "Source: OpenParlData.ch"), Bern open data, Fedlex, parliament sites, fetched politely (≥ 1.2 s per host and process). `data/` and `results/` are CDLA-Permissive-2.0 and carry OPD's attribution. **Sovereignty and data protection.** No third-party processor by default; besides the public sources, Hugging Face once for the pinned 8B, and a review-model endpoint (Public AI, or the local 8B, where no text leaves the machine) and an alert relay only if the operator sets them. The operator sheet's nDSG row names the personal data (office holders named in public documents), the route that discloses text abroad (Public AI: by its published terms a US nonprofit offering no data processing agreement and no storage outside the US) and the cache retention (default 30 days); for public bodies it recommends rules only or the local 8B. A body that may not disclose text abroad goes without only the review-queue verifier and the role reader; a Swiss-hosted 70B is an estimated 1.64 GPU-hours per 1,000 residue documents (`docs/runbook.md`). **Supply chain** (`docs/licences.md`): 8 Python packages in the image under permissive licences, every lock hash-pinned, poppler (GPL) run as a separate program; CycloneDX SBOMs; CI scans every lock for known vulnerabilities (0 failing; 1 accepted with its reason, in the optional local 8B's lock). **Operations.** `make run` and the nightly unit run the image read-only, as a non-root uid, with `--cap-drop ALL`; A network night refuses to start without a contact URL in `GP_USER_AGENT`. **robots.txt:** we found, audited and fixed our own robots.txt bug; every fetch path now fails closed (disclosure: `docs/incidents.md`).

## 5. Results without a model: schema verdict, census, repair

**Table 1. The 17 fields.** *Class*: role split = one label covers several roles, measured on OPD's labels (`results/census/comparability.json`) or on the documents (P8, `results/p8/`); fragile = not under both P8 checks; untested = one v0.1 definition, meaning not yet measured. *Source* of the split (committed results only): practice (parliaments differ; the standard encodes the role), OPD (likely a data or tagging error OPD can correct), both, or open (the labels cannot tell). *Where it lives*: parliaments where OPD metadata carries it · carries it for part of the affairs · only the PDF · not in OPD's data (`results/census/matrix.json`).

| field | class | source | evidence | where it lives (meta · mixed · PDF · none) |
|---|---|---|---|---|
| answer date | role split | both | decided, dispatched or registered; in 7 of 54 bodies the submission date | **metadata**: 53 · 1 · 0 · 0 |
| procedural history | role split | open | 35 event labels, several date roles | **metadata**: 78 · 9 · 1 · 1 |
| type | role split | both | 42 of 1,038 raw labels map to two types; P8: the instrument | partly: 61 · 24 · 2 · 2 |
| procedural state | role split | open | 32 labels ambiguous | partly: 41 · 27 · 18 · 3 |
| decision outcome | role split | practice | 3 labels ambiguous | partly: 7 · 31 · 33 · 6 |
| submitter | role split | practice; OPD in GR | P8: sole, joint or group author | partly: 23 · 61 · 5 · 0 |
| co-signatories | role split | practice | P8: includes authors of record | PDF only: 0 · 2 · 72 · 12 |
| language | role split | both | P8: tag names the other language; text, tag and affair differ | partly: 14 · 53 · 20 · 2 |
| addressed body | split, fragile | practice | P8: the council (Bellinzona) | partly: 12 · 10 · 54 · 10 |
| government recommendation | split, fragile | both | P8: by stage | partly: 3 · 8 · 56 · 10 |
| submission date | body-specific in 2 | OPD | P8: OPD's date printed in neither document (Vernier 5/5 affairs, Lausanne 3/5); a data-source split | **metadata**: 89 · 0 · 0 · 0 |
| answer-link status | untested | — | one v0.1 definition; meaning test next | **metadata**: 54 · 0 · 0 · 0 |
| decision date | untested | — | one v0.1 definition; meaning test next | partly: 7 · 30 · 34 · 6 |
| Q/A pairing | untested | — | one v0.1 definition; meaning test next | partly: 22 · 25 · 4 · 3 |
| usable text | untested | — | one v0.1 definition; meaning test next | partly: 41 · 42 · 0 · 6 |
| dispatch date | untested | — | one v0.1 definition; meaning test next | PDF only: 0 · 0 · 47 · 7 |
| related affairs | untested | — | one v0.1 definition; meaning test next | PDF only: 0 · 0 · 76 · 13 |

Of the 10 role splits, 6 come from the role test (P8, registered) and 4 from OPD's label vocabularies (post hoc); by source of the split 4 parliamentary practice, 4 partly OPD's tagging (which OPD can correct), 2 open. *Do v0.2's roles fit gold labelled after they were frozen?* On interventions every determinable value beyond authorship falls into a named v0.2 role, 58/58 (answer-date role, instrument function, instrument name; 27 interventions from 6 parliaments, P11's Italian cell and the federal cell), and 267/267 author roles (P10, P11; exploratory, post hoc, `oos_role_fit.json`); outside interventions 36/43 (misses: 5 'cited' submission dates, 2 instrument functions). On P8's own gold, 302/302 is an exhaustiveness check (post hoc; the roles were written from its categories). 4 fields are in OPD's metadata almost everywhere, 13 partly or only in the PDF. Two further *concepts* are body-specific: oral answers in question time (23.6% of question-time answers) and councils that publish only meeting documents (16 bodies; v0.1 marks affairs rebuilt from minutes `virtual`, P4).

**Cross-parliamentary question.** Of the 91,268 interventions with a recorded government answer, 81.6% have answer text attached in OPD (the registered count); 82.3% also count the 592 answers OPD files under an agenda item of the affair (not sample-checked); 85.6% with the repairs from what OPD already holds, 88.3% after the Bern relinks, 92.1% with the checked fetches (`results/report/r9_numbers.json`). *Answer times* (post hoc, 17 parliaments with at least 20 durations, `results/findings/answer_times.json`): on the same affairs OPD's answer dates and the documents' dates rank the parliaments almost identically (Spearman 0.997), so rankings do not hinge on the date's role; OPD's plain medians agree with them at 0.884 (OPD's own dates on these affairs at 0.86), since the verified answers are the census gap, with their own type mix. The role decides where OPD's answer event is the submission date: in Kriens the verified answers give 26.5 days on 68 affairs, OPD's date 0.

<img alt="fig2" src="docs/figures/fig2_matrix.png" style="width:74%;max-height:none;display:block;margin:0 auto">
*Figure 2. Where each field comes from, per parliament. Orange = not in OPD's data for that parliament (the parliament may still publish it).*

**Repair.** *Bern* (a linking bug OPD confirmed; correspondence, 10 Oct 2026): of 3,532 answers the canton publishes OPD attaches 229 (6.5%), although 96.1% are in OPD and linkable without a model. 2,459 relink candidates = 2,421 that pass every check against OPD's own copy (affair number, heading, decision date = OPD's answer event [97.9, 98.9]) + 38 to review. The document `hash` is sha256(body_key + parent_type + url) (49,810 of 49,810 rows), so relinking changes each identifier and file URL unless OPD keeps the old one; the plan carries both values. *Source adapters* (`docs/adapters.md`): readers for 50 parliaments (27 yield counted rows) verify 6,473 answers by affair number or title, the parliament's answer formula and a date check; Valais's 140 date-window rows moved to review: OPD's Valais answer event is the session that debated the motion, after the government's letter (`retier_r18.json`). 2,177 of them are already in OPD with text under a heading the census lexicon does not list: the repair is a category on the document (`tag_answer`). **Blind audit v3** (`results/repair/adapters/audit3/`; 60 decoys, key hashed on GitHub first): on the counted rows the blind AI annotators judged 185/186 the executive's answer (Claude Opus) (3 dates judged wrong, all Solothurn, where the auditor saw the committee's "Beantwortet" date) and Qwen-SEA-LION 186/186 (post hoc re-read over the strata that still count; as run on 200 rows: 197/200). Also for OPD: 9 harmonised vocabulary labels wrong as published, and a Fedlex resolver for 29,946 federal placeholder documents.

## 6. Evaluation: ten pre-registrations

**Design.** Each test froze code, prompts and θ by sha256 before any label was committed (P1's hypothesis script followed its labels, D4). Unit (P1, P2, P6): one document's answer date, strict. Arms on identical inputs: **rules**; **pointer**; **cascade** (rules, then the pointer on the residue); **naive** free generation, plain and null-allowed; trivial baselines. **Gold, no human labelling by design:** two blind agent annotators (Claude Opus, Sonnet), a third breaks ties, quotes verified by code, raw files committed; all 96 annotator sessions (P1–P8, P10, the document-parts check, the federal cell) ended before GitHub received their labels (`results/eval/annotation_sessions.json`). An isolation audit of their own transcripts lists every file the 96 sessions read and every command they ran (3,086 reads, 1,295 commands): none touched a key, gold label, result, text outside its packets, another annotator's folder or the internet (0 violations; post hoc, `results/eval/annotator_isolation.json`).

**Table 2. The ten tests, in registration order.**

| test | n | what it tests | registered result | note |
|---|---|---|---|---|
| P1 | 154 documents, parliaments with rules | answer date: rules vs Apertus | **partial**: H3 held; H1 null safety failed (7/90); H2 Branch B | rules alone 135/154, so no model by default |
| P2 | 62 documents, 15 parliaments without rules | rules transfer; pointer vs rules | **3 of 4 held**; H3 null safety failed (4/33) | pointer 24/29 dates, rules 2/29 |
| P3 | 29 whole affairs, 10 parliaments | 7 fields: metadata, rules, Apertus | **partial**: no field unattended; Apertus recall held, precision below | feasibility study (D3-5) |
| P3b | 36 fresh affairs, 9 parliaments | replication of P3 | **held**: replicated (S1, S2) | S2 lenient; type 35/36; addressed body 2/33 |
| P4 | 120 agenda items, 6 sittings | affairs rebuilt from minutes | **partial**: H2, H4 held; H1, H3 failed | recall 99/120, precision 99/99 |
| P5 | 40 fresh affairs, 10 parliaments | Q/A pairs, people, recommendation | **partial** tier (H1); H2, H5 held; H4 as rules vs free generation; H3 no gain | *not yet* when parliaments are resampled |
| P6 | 68 fresh documents, 8 parliaments | answer-date reader v2 vs free prompting | **no hypothesis held** | free prompt 62/68, v2 59/68 |
| P7 | 478 review rows, 190 blind packets | Apertus as verifier of the review queue | **H1 holds** (120/120); H4 supported; H3 not supported | 214 of 917 rows promoted |
| P8 | 66 fresh affairs, 11 parliaments | meaning of 7 fields in the documents | **none uniform**: 6 role split, 1 body-specific | 5 robust; meaning measured for 11 of 17 |
| P10 | 34 fresh affairs, 14 parliaments without rules | author roles: Apertus reader vs rules, OPD's list | **3 of 4 held**: H1, H2, H3b; H3a not | pairs right 50/141, rules 17/141, OPD 37/141 |

**Unattended** (95% lower bound ≥ 0.80, document-level intervals): the rules' answer date where rules exist (P1, helped by right nulls: dates found 47/64), the type on whole affairs (P3b, 35/36), and in P5 question detection, the reasoning span and co-signatory precision. **Cross-checks.** `Qwen-SEA-LION-v4-32B-IT` (AI Singapore) relabelled P1, P2, P6 and P7 blind: date κ 0.80, 0.87 and 0.86, P7's is-answer labels 185/190; no registered decision changes. Non-LLM checks: OPD's event matches 37 of 44 checkable P1 dates. Holm over all 20 registered confirmatory tests of P1–P7: the 9 that held survive (`results/eval/posthoc_r8_multiplicity.json`); whole parliaments are resampled as well.

| P1 arm (154 documents) | exact [95% CI] | answered: found /64 | wrong printed date | invented | answerless dated /90 |
|---|---|---|---|---|---|
| **rules only (default)** | **135/154 [81.5, 92]** | 47 | 4 | 0 | 2 |
| pointer | 130/154 [77.9, 89.3] | 46 | 16 | 0 | 6 |
| cascade | 139/154 [84.6, 94] | 56 | 11 | 0 | 7 |
| naive, null-allowed | 134/154 [80.8, 91.4] | 47 | 11 | 0 | 3 |
| *trivial: latest date, answer-typed docs* | *131/154 [78.6, 89.8]* | *44* | *16* | *0* | *3* |
| *model-free cascade (post hoc)* | *138/154 [83.8, 93.5]* | *52* | *11* | *0* | *4* |

**P1:** the rules (135) and the latest date on answer-typed documents (131) are level (paired p = 0.48, post hoc; P1's rules entered with its sample, D12), so P2 is the test of transfer. H1 null safety failed (the cascade dates 7 of 90 answerless documents, 6 of them council reports; upper bound 15.2% vs 10%); H2 gave Branch B (cascade alone right on 5, rules alone on 1, p = 0.22), so Apertus left the unattended path for an opt-in review suggestion (D6); H3 held (AUROC 0.969).

| P2 arm (62 documents) | exact [CI] | answered: found /29 [CI] | wrong date | invented | answerless dated /33 |
|---|---|---|---|---|---|
| rules only | 35/62 [44.1, 68.1] | **2/29** [1.9, 22] | 2 | 0 | 0 |
| **pointer** | **53/62** [74.7, 92.2] | **24/29** [65.5, 92.4] | 8 | 0 | 4 |
| naive, null-allowed, re-parsed (D2-4) | 54/62 | 24/29 | 7 | 1 | 3 |
| *trivial: latest printed date* | *24/62* | *22/29* | *38* | *0* | *31* |
| *trivial: latest date, answer-typed docs* | *44/62* | *18/29* | *13* | *0* | *7* |

**P2:** the rules collapse off their home layouts (47/64 → 2/29). H2 held: on all 62 documents the pointer beats the rules on 22 and loses on 4 (p = 5.3 × 10⁻⁴); resampling the 15 parliaments, the gain is [-0.02, 0.54], so it sits in a few parliaments. "Answerless" means no qualifying answer date: the pointer's 4 such dates fall on documents with an answer but no qualifying date; of the 25 with no answer at all it dates none (post hoc). *Post hoc, proposed in review:* a generic DE/FR/IT keyword rule is exact on 45/62 and finds 16/29 answer dates (pointer vs rule: McNemar p = 0.077; on answer dates 0.057).

**P3/P3b/P4.** Default (metadata + rules) on 29 affairs: type 27/29, answer date 22/27, 27/27 with Apertus suggestions. P3b replicated by its registered criteria; answer date 20/35 by default (C), 31/35 with Apertus suggestions. P4: 99 of 120 agenda items as virtual affairs, precision 99/99. **P5.** Rules-only pairing: precision 0.83, recall 0.67, *partial* with document-level intervals, *not yet* when parliaments are resampled; recommendation 34/40 by rules; submitter rules 12/40, pointer 24/40, free generation 34/40.

**P6 — reader v2** (an answer-present gate, then the guide's date rule). No registered hypothesis held: v2 vs free prompting 1:4 (p = 0.38); v2 dates 5/34 answerless documents (upper bound 30.1% vs 15%); v2 vs v1 5:2 (p = 0.45).

**P7 — Apertus as a precision verifier of the review queue** (`eval/prereg8/`, LOCK8 before the draw). Test frame: 478 eligible review rows outside every audit; 190 blind packets. H1 (primary): promotion precision 120/120, Wilson lower bound 96.9% ≥ 0.90: **holds**. H4: dated precision 95.8% vs 73.2% for a trivial exact-date match, +22.7 points [10.2, 34.3], weighted, as registered (unweighted +7.5): **supported**. Base rate: 86.7% of eligible queue rows are answers, but only 40.9% are answers whose own date passes the rule, so the gain is the date check.

**P8 — what the shared fields mean** (`eval/prereg9/`, LOCK9 before the draw). Share in v0.1's meaning, pooled (parliament-cluster 95% interval): submitter 35/65 [33.3%, 75.0%], co-signatories 10/41 [6.8%, 46.3%], submission date 44/57 [57.1%, 91.8%], type 55/64 [76.2%, 95.3%], language 34/36 [83.3%, 100.0%], each verdict unchanged on agreed labels only and on Qwen's labels; addressed body (57/60) and recommendation (31/34) are fragile.

**P10 — Apertus reads author roles where no rules exist** (`eval/prereg10/`, LOCK10 before the draw and the labels; D1). 34 fresh German and French affairs (of 38 planned), 14 parliaments outside every rule set, 141 gold (name, role) pairs. Pairs right / printed: Apertus 50/96 (precision 0.52, recall 0.35, F1 0.42), rules 17/55 (0.31, 0.12, 0.17), OPD's contributor list as first author and co-signers 37/104 (0.36, 0.26, 0.30). Confirmed: H1, recall over the rules, +23.4 points [5.9, 49.0], Holm p = 0.032; H2, precision non-inferior (+0.21); H3b, over the same names with a trivial role. Not confirmed: H3a, over OPD's list (+0.12, Holm p = 0.17): where OPD lists the authors, its order is a strong baseline. *Post hoc, proposed in review:* the same candidates in document order with OPD's registered mapping match 52/141 (F1 0.41). The gain over the rules is the candidate finder plus document order; Apertus's author filter, on the same order rule, keeps recall and adds +7.3 points precision [0.8, 18.2] (uncorrected).

**Federal cell** (exploratory, `eval/fed/`, LOCKFED before draw and labels): 15 Federal Council answers print no answer date and no author; rules, pointer and converter date none (15/15 right nulls), the latest printed date dates an answerless document on 6/15.

**P11** (exploratory, `eval/p11/`, LOCKP11 before draw and labels; D1). *Italian*, 12 interventions from Ticino, Mendrisio, Lugano, Locarno and Bellinzona: the pointer is exact on 12/12 [75.7, 100] (10 printed dates, 2 right nulls, none invented), the latest date on the answer document on 9/12 (it dates both answerless affairs), the rules on 8/12 (in-sample in Ticino, Mendrisio, Lugano); author roles (70 gold pairs): rules precision 0.875 at recall 0.10, the converter's record F1 0.30, document order and OPD's list 0.22, the Apertus role reader 0.32 on all 12 affairs (precision 0.33, recall 0.30; resumed on the registered build after the switch, D2). *Outside interventions*, 15 government-business and initiative affairs: 7 of 17 fields carry over, 4 answer fields do not apply, 6 need new roles, chiefly the executive acting as proposer: adopting, endorsing and signing its own proposal (government business 7 of 8 affairs, initiatives 2 of 7); the frozen converter returns a valid v0.2 record for 3 of 15 (registered arm), a writer from the same metadata and fetched documents 15/15 (post hoc), none typing an answer field `not_applicable` where the gold finds it applies.

**What the tests say.** *Provenance by construction:* no arm that picks from printed dates returned a date printed nowhere (P1, P2, P6). **Null safety** is left to the reviewer: the registered null-safety tests on the 70B failed (P1-H1, P2-H3, P6-H2), which is why the default runs no model.

## 7. Next steps, reproducibility, declarations

**Next steps.** With OPD: its hash decision for the relinks and the 30-row spot-check kit; with the eCH group: `QAItem` and the five gaps. Author rules are per layout; where none exists the candidate finder (it offers 87 of the 141 gold names) is the next lever. *Limits of the answer, each with its next test:* three splits rest on one parliament each (addressed body, recommendation, language): more parliaments per field. Italian rests on P11's exploratory cell (12 affairs; author-role F1 0.32 or lower for every arm): a registered Italian test. Outside interventions: v0.3 roles for the executive as proposer, and the post hoc record writer for affairs without a member's text in the `affair` command. 6 fields are untested: their meaning test. **Reproducibility.** `make run` (Docker, CPU) recomputes the census and the Bern join, re-derives the P1 rules arm from the source PDFs and P1's and P2's Apertus decisions from the model cache (cold cache: P2's 62/62 documents in 90 s, all matching; 8 read from OPD's own copy, sha256-checked), replays P1–P8 and P10 (all locks verified), regenerates the summary-number files byte for byte and runs the claims check, which binds every number and scope word in this report to its claim and checks this PDF against its source. **Declarations.** Claude Code agents (Anthropic) wrote most code, documentation and the gold labels. Public AI (may route outside Switzerland) served evaluation only. Report CC-BY-4.0.
