# Technical report — Gegenprobe: one schema and a converter for Swiss parliamentary answers

**Track 2A — OpenParlData** · Online · Team 444 — Roman (+ Claude Code agents, §7) · Evidence site https://gegenprobe.mi11ion.io · **Maturity:** census and Bern repair lists = *ready for OPD to apply* (needs its choice on the document hash); source-adapter lists = *audited prototype*; nightly job = *deployable prototype*; rules-only converter = *tested prototype*; review mode, whole and virtual affairs = *feasibility study*; schema v0.1 = *draft*.

## 1. Summary

1. **Verdict.** The frame of a common schema is feasible: 17 fields, each a value with its source (page and character span, or the OPD record) or a typed null that says why it is empty, with dates kept apart by role. The *meaning* is verified across parliaments for 1 of the 17 fields (the government recommendation); 5 more are measured to need a role split; 11 are shared by definition, untested (Table 1).
2. **What OPD can apply tomorrow.** Bern: 2,421 relinks, 48 fetches and 554 `begin_date` corrections, keyed on OPD ids, with a dry-run SQL plan. OPD confirmed the Bern bug (correspondence, 10 Oct 2026; a published excerpt awaits OPD's consent). Beyond Bern: one list per parliament from 50 model-free source adapters.
3. **Census.** The registered census counts **16,749** of 91,268 interventions with a written government answer without answer text attached in OPD. 2,177 of them are in OPD with text under a heading the census does not recognise, so **at most 14,572** lack answer text (13,150 written answers). Verified repairs are proposed for 9,720; after every counted repair **92.3%** of the 91,268 have answer text (today 82.3%).
4. **What Apertus adds.** On parliaments nobody wrote rules for it finds answer dates the rules miss (P2: 24/29 vs 2/29), and as a closed-set pointer every value is a printed date with page and span. It is not more accurate than the same model asked freely with null allowed (P2, P6), and it still dates 4 of 33 (P2) and 5 of 34 (P6) answerless documents, so its values are review suggestions.
5. **Not done.** Nothing runs at OPD yet (the relinks wait on OPD's hash choice); 5,007 written answers still need adapters; tables, annexes and images are not extracted; only the type on whole affairs and the rules' answer date on parliaments with rules (P1) clear the unattended bar (95% lower bound ≥ 0.80); every gold label comes from LLM agents (no human labelled, by design).

## 2. Architecture

1. **Census** (`census/`): streams the OPD exports once into a per-affair *answer-link status* (`attached | agenda | parentless | absent | image_only | oral`), the feasibility matrix and a comparability measure; a derived layer (`census/corrected.py`) places every registered gap row once the repair routes have looked (Fig. 1).
2. **Repair** (`repair/`): deterministic routes per cause, each row triple-checked (affair number or title, answer heading, date against OPD's answer event), as lists keyed on OPD ids; a nightly job (`deploy/nightly/`) re-runs the Bern route.
3. **Converter** (`convert/`, `qa/`): (i) OPD metadata and events, (ii) frozen DE/FR/IT anchor rules, (iii) the Apertus closed-set pointer on the residue. Modes: `rules_only` (default, no model) and `review` (suggestions with page, span and margin, flagged `needs_review`).
4. **Schema and validator** (`schema/`, `validate/`): Pydantic schema v0.1, normative; a value carries `{value, role, page, char_start, char_end, quote, route, rule, model_build, θ, margin}`, a null its reason (`not_in_document | unlinked | image_only | oral | text_failed | present_unanchored | no_rules_for_body | not_applicable`); `QAItem` pairs question *n* with its answer passage.

<img alt="fig1" src="docs/figures/fig1_funnel.png" style="width:100%;max-height:none">
*Figure 1. The registered 16,749 placed once each by the derived census layer (`results/census/corrected.json`).*

## 3. Use of Apertus

**Closed-set pointer** (`convert/pointer.py`, prompts `src/prompts/{de,fr,it}`). The document (first 12,000 characters) and the question go in the user message, the assistant turn is prefilled with a JSON prefix, and `null` and every distinct date printed in the document are scored as continuations by summed log-probability. Null if `lp(null) − logsumexp(lp(dates)) > θ`, else the best date, mapped back to its span. θ does not transfer across builds (a θ fitted on RLVR scores 0.25 on the final build), so it is fitted per build on dev documents and frozen (θ = 10.40, AUROC 0.99). The same form picks labels and, in `qa/`, the question a paragraph answers, the recommendation sentence or the submitter's printed name. **Why a pointer:** asked freely, Apertus dates 15/15 (8B) and 14/15 (70B) Bern interventions that have no answer; a null-allowed prompt fixes the 70B (0/15), not the 8B (14/15).

**Which model.** Evaluation used **Apertus v1.5 70B weights served by Public AI** (inferred from the served fingerprint `tp8-pp2-…` and the behaviour, 760/792 greedy outputs byte-identical to the `-70b` name; the endpoint name says `8b`). The response `model` is checked on every call, and every cached P1/P2 answer comes from one served build. The real **8B** (`swiss-ai/Apertus-v1.5-8B`, a community 4-bit GGUF, sha256-pinned; not an official release) ran in-process on CPU with llama.cpp, own θ = 16.73, on P1 and P2 (52 reachable documents); its P6 run is still running. It finds answer dates nearly as well (P2: 15 of 21 vs 70B 16) but dates more answerless documents (P1 25 of 90, 70B 7; P2 11 of 31, 70B 4); its fast scorer passed a replacement gate written after two failed parity gates (D9). **Recommendation:** `rules_only` unattended; for review suggestions the 8B as the sovereign option (a reviewer rejects more), the 70B for accuracy on infrastructure the operator chooses. Review mode stops (exit 3) on a served build θ was not fitted on.

**Cost** (`results/report/cost_end_to_end.json`, one core, no GPU). Fetch, extraction and checks about 2.1 s per document plus 6.9 s per OCR page; the rules process 480 documents per second (0.5 CPU-hours for all 902,754 documents in OPD's export). Review mode: 3.5 calls and 5,905 billed prompt tokens per residue document on the 70B, USD 0.59 per 1,000 residue documents at Public AI's list price; the 8B takes 180 s per document on 4 vCPUs.

## 4. Data and operations

OPD bulk exports (snapshot 6 Oct 2026; OPD's API robots.txt disallows `/v1/`), Bern open data, Fedlex, parliament sites, fetched politely (≥ 1.2 s per host). `make run` and the nightly unit run the image read-only, as a non-root uid, with `--cap-drop ALL`; PDFs are capped at 50 MB and 600 s, every hit a typed failure row. **One real night** (`results/monitor/night_real_38062530586/`) under systemd on a GitHub 4-vCPU runner against OPD's live exports: 83 min, 2,078 MB peak, the Bern list reproduced on live data (2,459 relink, 49 fetch). A two-night run of the Docker setup (Actions run 38098822336) is running; the job does not run at OPD yet. **Incident** (`docs/incidents.md`): our network layer judged robots.txt with Python's first-match parser, where RFC 9309 requires the longest match. Between 9 and 11 Oct the project requested 147 distinct URLs on paths www4.ti.ch (Canton Ticino) disallows, 133 of them downloads, mostly by the gold-set samplers that fetched the parliament's URL OPD records; CI runs repeated at most 6,655 requests before the fix. No other host was affected. Since 11 Oct an RFC 9309 matcher (`robots9309.py`) judges every fetch, and every fetch path requests a mapped URL from OPD's own copy on files.openparldata.ch instead; 126 of the 130 evaluation documents are byte-identical to that copy.

## 5. Results without a model: schema verdict, census, repair

**Table 1. The 17 fields.** *Class*: does the field mean the same thing in every parliament (`results/census/comparability.json`, `data/schema/field_verdict_classes.json`)? *Where it lives*: parliaments where OPD metadata carries it · carries it for part of the affairs · only the PDF · not in OPD's data (`results/census/matrix.json`, thresholds in `docs/census.md` §3).

| field | class | meaning tested? | where it lives (metadata · mixed · PDF only · none) |
|---|---|---|---|
| answer date | role split | measured: decided, dispatched or registered; in 7 of 54 bodies mostly the submission date | **metadata**: 53 · 1 · 0 · 0 |
| procedural history | role split | measured: 35 event labels carry different date roles | **metadata**: 78 · 9 · 1 · 1 |
| type | role split | measured: 42 of 1,038 raw labels map to different types | partly: 61 · 24 · 2 · 2 |
| procedural state | role split | measured: 32 labels ambiguous | partly: 41 · 27 · 18 · 3 |
| decision outcome | role split | measured: 3 labels ambiguous | partly: 7 · 31 · 33 · 6 |
| government recommendation | shared | **tested**: 0 of 183 raw labels map to different concepts | partly: 3 · 8 · 56 · 10 |
| submission date | shared | by definition, untested | **metadata**: 89 · 0 · 0 · 0 |
| answer-link status | shared | by definition, untested | **metadata**: 54 · 0 · 0 · 0 |
| submitter | shared | by definition, untested | partly: 23 · 61 · 5 · 0 |
| addressed body | shared | by definition, untested | partly: 12 · 10 · 54 · 10 |
| decision date | shared | by definition, untested | partly: 7 · 30 · 34 · 6 |
| Q/A pairing | shared | by definition, untested | partly: 22 · 25 · 4 · 3 |
| language | shared | by definition, untested | partly: 14 · 53 · 20 · 2 |
| usable text | shared | by definition, untested | partly: 41 · 42 · 0 · 6 |
| co-signatories | shared | by definition, untested | PDF only: 0 · 2 · 72 · 12 |
| dispatch date | shared | by definition, untested | PDF only: 0 · 0 · 47 · 7 |
| related affairs | shared | by definition, untested | PDF only: 0 · 0 · 76 · 13 |

So 4 fields are in OPD's metadata almost everywhere and 13 partly or only in the PDF; no field lacks a source in a fifth of the parliaments (5 would at a 10% threshold). Three further *concepts* are body-specific and are not fields: oral answers in question time (23.6% of question-time answers are oral; v0.1 types them as a null reason), executive business that answers no member's affair, and councils that publish only meeting documents (16 bodies; v0.1 marks affairs rebuilt from minutes `virtual`, P4). Where OPD metadata carries a field it mostly agrees with print (P3: type 17/18, submitter 23/28, submission date 15/21).

<img alt="fig2" src="docs/figures/fig2_matrix.png" style="width:100%;max-height:none">
*Figure 2. Where each field comes from, per parliament. Orange = not in OPD's data for that parliament (the parliament may still publish it).*

**Cross-parliamentary question.** Of the 91,268 interventions with a written government answer, 82.3% have their text in OPD by the registered census rule (85.0% after the agenda join and the Bern relink; 92.3% after every counted repair). Answer times are not one quantity: the median is 112 days where OPD's "answer" date is the verified decision date (Bern, Ticino), 79 on a government's weekly sitting, 39 for diffuse, publication-like dates; in 7 parliaments the "answer" is the submission date.

**Repair.** *Bern*: of 3,532 answers the canton publishes OPD attaches 229 (6.5%), although 96.1% are in OPD and linkable without a model. Against OPD's own copy all 2,459 relink candidates match affair number and heading; the decision date equals OPD's answer event for 2,421 [97.9, 98.9]: 2,421 in `repair_BE_relink.tsv`, 38 to review. The document `hash` is sha256(body_key + parent_type + url) (49,810 of 49,810 rows), so relinking changes each identifier and file URL unless OPD keeps the old one. A second list corrects 727 `begin_date` load timestamps (554 from the affair's own submission event, 173 to review). *Source adapters* (`repair/adapters/`, `docs/adapters.md`): readers for 50 parliaments (27 yield counted rows) verify 6,613 answers by affair number or title, the parliament's answer formula and a date check, in three tiers: the document's own date equals an OPD event (5,161); a printed date equals an OPD answer event and the document's own date, if read, lies within 30 days of one (1,056); the date lies in the parliament's documented window (396). Listed, not counted: 282 Jura answers matched by identity and wording only (OPD's Jura answer events carry no date) and 917 rows for a person. 2,177 of the "missing" answers are already in OPD with text: the repair is a category on the document (`tag_answer`). **Blind audit v3** (`results/repair/adapters/audit3/`): 200 counted rows, stratified by tier and route, and 60 decoys from the review and failed lists, shuffled into packets without the pipeline's verdict; the key's hash was committed before judging. Claude Opus judged 197/200 counted rows to be the executive's answer (Wilson 95.7% to 99.5%), and the date wrong or unsupported on 15. It rejected 60% of the failed decoys but only 1.5% of the counted rows, and called 77% of the review decoys answers: the pipeline errs on the side of review. A second auditor, Qwen-SEA-LION, accepted 200/200 but was lenient on decoys; the two agree on 252/260. Both are LLMs; no person audited.

## 6. Evaluation: seven pre-registrations

**Design.** Each test froze code, prompts, θ and the scorer by sha256 before any label was committed. Unit (P1, P2, P6): one document's answer date, strict. Arms on identical inputs: **rules**; **pointer** (Apertus on every document); **cascade** (rules, then the pointer on the residue = every suggestion accepted); **naive** free generation, plain and null-allowed, same weights. **Lock before label is shown by time, not only by commit order:** the annotator agents' transcripts date every labelling session; across 10 label sets, all 74 annotator sessions started after GitHub received the LOCK and draw pushes and ended before it received the labels, and all 996 label files were written inside their session (P6: first session 26 s after the draw push; P1: 95 s after the LOCK; `results/eval/annotation_sessions.json`). P1's rules were committed with its sample (D12), so P2 is the clean out-of-sample test of the rules. Pointer v2 (P6) was chosen by a rule written before the DEV2 labels, but its code was committed after them (DEVIATIONS7 D1); LOCK7 froze it before the P6 draw.

**Table 2. The seven tests, in registration order.**

| test | n | what it tests | registered result | note |
|---|---|---|---|---|
| P1 | 154 documents, parliaments with rules | answer date: rules vs Apertus | **partial**: H3 held; H1 null safety failed (7/90); H2 Branch B | rules alone 135/154, so no model by default |
| P2 | 62 documents, 15 parliaments without rules | rules transfer; pointer vs rules | **3 of 4 held**; H3 null safety failed (4/33) | pointer 24/29 dates, rules 2/29 |
| P3 | 29 whole affairs, 10 parliaments | 7 fields: metadata, rules, Apertus | **partial**: no field unattended; Apertus recall held, precision below | feasibility study (D3-5) |
| P3b | 36 fresh affairs, 9 parliaments | replication of P3 | **held**: replicated (S1, S2) | S2 lenient; type 35/36 unattended |
| P4 | 120 agenda items, 6 sittings | affairs rebuilt from minutes | **partial**: H2, H4 held; H1, H3 failed | recall 99/120, precision 99/99 |
| P5 | 40 fresh affairs, 10 parliaments | Q/A pairs, people, recommendation | **partial** tier (H1); H2, H4, H5 held; H3 no gain | *not yet* when parliaments are resampled |
| P6 | 68 fresh documents, 8 parliaments | answer-date reader v2 vs free prompting | **failed**: no hypothesis held | free prompt 62/68, v2 59/68 |

**Gold and checks.** No human labelled a gold value, by design: two blind Claude annotators (Opus, Sonnet), a third breaks ties, quotes verified by code; the raw A1/A2/A3 files are committed for every set, P6 and DEV2 included, and re-merging them reproduces the labels. `Qwen-SEA-LION-v4-32B-IT` (AI Singapore; another vendor and model family) relabelled P1 and P2 blind (post hoc, D14): exact answer date κ 0.80 (P1), 0.87 (P2), no registered decision changes; on P6 κ 0.86 (date), none changes; on P5 its labels are too noisy to judge. Non-LLM checks: OPD's event matches 37 of 44 checkable P1 dates (5 of the other 7 are 1–5 days apart); Ticino titles 20/20; P6: OPD's written-answer event matches the gold on 10/10, every gold quote sits on its page (34/34), and 20/34 dated gold documents have a non-LLM date source (`results/eval/posthoc_r6_p6_oracle.json`). **Statistics:** over the 9 registered confirmatory tests of P1–P4 and P3b all 4 held conclusions survive Holm. Documents from one parliament are not independent, so we also resample whole parliaments (10,000 bootstrap resamples, post hoc, `results/eval/posthoc_r6_cluster.json`).

| P1 arm (154 documents) | exact [95% CI] | dates found /64 | wrong printed date | invented | answerless dated /90 |
|---|---|---|---|---|---|
| **rules only (default)** | **135/154 [81.5, 92]** | 47 | 4 | 0 | 2 |
| pointer | 130/154 [77.9, 89.3] | 46 | 16 | 0 | 6 |
| cascade | 139/154 [84.6, 94] | 56 | 11 | 0 | 7 |
| 8B cascade (CPU, exploratory) | 119/154 [70, 83.2] | 54 | 31 | 0 | 25 |
| naive, null-allowed | 134/154 [80.8, 91.4] | 47 | 11 | 0 | 3 |
| naive, plain | 98/154 [55.8, 70.8] | 47 | 23 | 24 | 39 |

**P1:** H1 null safety failed (the cascade dates 7 of 90 answerless documents, upper bound 15.2% vs 10%); H2 gave Branch B (cascade alone right on 5, rules alone on 1, p = 0.22), so Apertus left the unattended path for an opt-in review suggestion (D6); H3 held (AUROC 0.969).

| P2 arm (62 documents) | exact [CI] | dates found /29 [CI] | wrong date | invented | answerless dated /33 |
|---|---|---|---|---|---|
| rules only | 35/62 [44.1, 68.1] | **2/29** [1.9, 22] | 2 | 0 | 0 |
| **pointer** | **53/62** [74.7, 92.2] | **24/29** [65.5, 92.4] | 8 | 0 | 4 |
| cascade | 51/62 [71, 89.8] | 22/29 [57.9, 87.8] | 10 | 0 | 4 |
| naive, null-allowed, re-parsed (D2-4) | 54/62 | 24/29 | 7 | 1 | 3 |
| *latest printed date (post hoc)* | *24/62* | *22/29* | *38* | *0* | *31* |

**P2:** the rules collapse off their home layouts (47/64 → 2/29). H2 held: on all 62 documents the pointer beats the rules on 22 and loses on 4 (p = 5.3 × 10⁻⁴); resampling the 15 parliaments, the gain is [-0.02, 0.54], so it sits in a few parliaments (ahead in 6, behind in 2 on all documents). The latest printed date finds 22/29 too but dates 31 of the 33 answerless documents. Against the free prompt with null allowed the pointer is ahead on 2 documents and behind on 1: no difference.

**P3/P3b — whole affairs.** Default (metadata + rules) on 29 affairs: type 27/29, number 21/29, submitter 23/29, submission date 15/21, answer date 22/27, 27/27 with Apertus suggestions; no field reaches the unattended bar; the addressed body is withdrawn as evidence (every gold value is "executive", D3-3). P3b replicated on 36 fresh affairs by its registered criteria; its answer date (C 20/35) is the field below P3's interval, 3 of its wrong dates from a Luzern rule that overrode OPD's correct date (D5-2; the product path now keeps OPD's date and flags the record); with Apertus 31/35. **P4:** rules derive 99 of 120 agenda items as virtual affairs, precision 99/99, no decision invented (0/36); recall missed its bar, and Apertus added 2 decisions (p = 0.5).

**P5 — Q/A pairs, people, recommendation.** `qa/` fills `QAItem` with spans; rules decide first, Apertus only points over printed candidates. H1 (rules-only pairing): precision 118/143 = 0.83, recall 118/176 = 0.67. With document-level Wilson intervals the registered rule gives *partial* (precision lower bound 0.75 ≥ 0.70); when parliaments are resampled precision is [0.66, 0.97], below the bar, so the same rule gives *not yet*. French is the weak language (recall 10/30), Valais got 0/11. H2: rules beat paragraph order 116:5. H4: rules-only pairing beats free generation 79:11; the dev-fitted pairing pointer never fired (H3: 0 of 36 residue answers). H5: zero provenance failures (517 rule values). Recommendation 34/40 by rules. The submitter is a review field: rules 12/40 (36/38 on dev), the pointer over printed names 24/40, free generation 34/40.

| P6 arm (68 documents, 34 answered) | exact | dates found | answerless dated | printed nowhere |
|---|---|---|---|---|
| free prompt, null allowed | **62/68** | 32/34 | 4/34 | 0 |
| cascade v2 (rules, then v2) | 60/68 | 31/34 | 5/34 | 0 |
| v2 | 59/68 | 30/34 | 5/34 | 0 |
| v1 pointer | 56/68 | 29/34 | 7/34 | 0 |
| *model-free cascade (post hoc)* | *55/68* | | | *0* |
| rules only | 54/68 | 20/34 | 0/34 | 0 |
| free prompt, plain | 54/68 | 33/34 | 13/34 | 5 |

**P6 — reader v2** (an answer-present gate, then the gold guide's decision-before-letter-date rule). No registered hypothesis held: v2 vs free prompting 1:4 (p = 0.38); v2 dates 5/34 answerless documents (upper bound 30.1% vs 15%); v2 vs v1 5:2 (p = 0.45). The frozen v2 decided 34 of 68 documents by guided generation (kept because the date is printed), 31 by its presence gate (null) and 1 by its role pick. On all 68 documents cascade v2 beats the rules on 11 and loses on 5 (p = 0.21); the 11:0 holds on the 34 answered documents only. A model-free cascade (rules, then the latest printed date on documents OPD types as answers) scores 55/68; cascade v2 is ahead of it on 5 documents, behind on 0 (p = 0.06).

**What the tests say.** Apertus earns its place where layout varies and no rule exists: it finds answer dates the rules miss (P2), fills whole-affair answer dates (P3: 22/27 → 27/27) and doubles submitter detection over the rules (P5: 12/40 → 24/40). **It does not abstain reliably:** every registered null-safety test failed (P1-H1, P2-H3, P6-H2). **Accuracy is not the pointer's argument:** the same Apertus asked freely with null allowed is as accurate (P2 54 vs 53 of 62; P6 62 vs 59 of 68). **Provenance:** no arm that picks from printed dates returned a date printed nowhere, on P1, P2 or P6; the fair comparator, the free prompt that may return null, did so 0, 1 and 0 times; the plain free prompt 24, 4 and 5 times. So free prompting with a null option almost never invents a date: the closed set's advantage is that every value it returns is a printed date with a location, which a reviewer can check in one click.

## 7. Limitations, reproducibility, declarations

Answer dates are tested in depth, Q/A pairs on 40 affairs; tables, annexes and images are not extracted; P3/P3b are small, P4 is one commune, P6 has no Italian document, no gold set contains federal documents; spans index our own pdftotext/tesseract text (`--opd-text` maps them onto OPD's). `make run` (Docker, CPU, clean checkout) recomputes the census and the Bern join, re-derives the P1 rules arm from the source PDFs and the P1/P2 Apertus decisions from the model cache, and replays 26/26 tests locally: P1–P4 and P3b re-scored from committed labels, the 7 hypothesis scripts including P5 and P6, the 8B analysis and the 7 LOCK files (the CI evidence run 38076870082 predates the P5/P6 replay: 22/22). It then recomputes every number in `claims.tsv` from its results file and fails if a document prints anything else. Claude Code agents (Anthropic) wrote most code, documentation and the gold labels; numbers are checked by code. Public AI (may route outside Switzerland) served evaluation only. Next: the Bern and adapter lists and the nightly job at OPD; adapters for the 5,007 answers still found only at the source; schema v0.2 (date roles, `QAItem`, five gaps) with the eCH group. Report CC-BY-4.0; standards in `docs/mapping.md`.
