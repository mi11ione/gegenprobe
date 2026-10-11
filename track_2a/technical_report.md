# Technical report — Gegenprobe: one schema and a converter for Swiss parliamentary answers

**Track 2A — OpenParlData** · Online · Team 444 — Roman (+ Claude Code agents, §7) · Evidence site https://gegenprobe.mi11ion.io · **Maturity:** census and Bern repair lists = *ready for OPD* (relinks await its hash decision); source-adapter lists = *audited prototype*; nightly job = *deployable prototype*; rules-only converter = *tested prototype*; review mode, whole and virtual affairs = *feasibility study*; schema v0.1 = *draft*.

## 1. Summary

**The answer in one sentence.** A common schema is feasible as a frame, but its meaning is shared only in part: the answer date, procedural history, type, procedural state and decision outcome differ by role between parliaments and must be split; the other 12 fields are shared by definition, their meaning untested.

1. **Verdict.** 17 fields, each a value with its source (page and character span, or the OPD record) or a typed null that says why it is empty, with dates kept apart by role. 5 fields are measured to need a role split; meaning is tested for 0 of the 17 (for the government recommendation OPD's label mapping is unambiguous, a string check, not a test of meaning; Table 1).
2. **Ready for OPD (awaits its hash decision for relinks).** Bern: 2,421 relinks, 48 fetches and 554 `begin_date` corrections, keyed on OPD ids, with a dry-run SQL plan; OPD confirmed the Bern bug (correspondence, 10 Oct 2026; a published excerpt awaits OPD's consent). Federal: 29,946 documents whose OPD text is Fedlex's "JavaScript required" page, resolved through Fedlex (pre-set rule 40/50 on a sample; about 17.5 h one-off). Beyond: one list per parliament from 50 model-free source adapters, and 9 OPD vocabulary labels that are wrong as published.
3. **Census.** The registered census counts **16,749** of 91,268 interventions with a recorded written-answer event without answer text attached in OPD (1,422 of them were answered orally). Repairs are proposed for 9,720: 9,089 checked row by row, 592 agenda joins (never sample-checked) and 39 Bern rows in review. After every counted repair **92.3%** of the 91,268 have answer text (today 81.6%).
4. **What Apertus adds.** As a closed-set verifier of the adapters' review queue (P7) it promotes 214 of 917 rows into a separate tier; on a fresh blind test 120/120 sampled promotions are the government's answer, and its date check adds 22.7 points of dated precision over a trivial date match. On unseen layouts it finds answer dates the rules miss (P2: 24/29 vs 2/29) and doubles submitter detection (P5: 12/40 → 24/40). It is not more accurate than a well-instructed free prompt (P2, P6, P7-H3) and every null-safety test on the 70B failed, so its values are suggestions a person or a check confirms.
5. **Not done.** Nothing runs at OPD yet; 5,077 answers are not found yet (943 of them wait for a person); tables, annexes and images are not extracted; every gold label comes from LLM agents (no human labelled, by design).

## 2. Architecture

**Census** (`census/`) streams the OPD exports once into a per-affair *answer-link status* (`attached | agenda | parentless | absent | image_only | oral`), the feasibility matrix and a comparability measure; a derived layer (`census/corrected.py`) places every registered gap row once the repair routes have looked (Fig. 1). **Repair** (`repair/`): deterministic routes per cause, each row checked (affair number or title, answer heading, date against OPD's answer event), as lists keyed on OPD ids; a nightly job (`deploy/nightly/`) re-runs the Bern route. **Converter** (`convert/`, `qa/`): OPD metadata and events, then frozen DE/FR/IT anchor rules, then the Apertus closed-set pointer on the residue; modes `rules_only` (default, no model) and `review` (suggestions with page, span and margin, flagged `needs_review`). **Schema and validator** (`schema/`, `validate/`): Pydantic schema v0.1, normative; a value carries `{value, role, page, char_start, char_end, quote, route, rule, model_build, θ, margin}`, a null its reason (`not_in_document | unlinked | image_only | oral | text_failed | present_unanchored | no_rules_for_body | not_applicable`); `QAItem` pairs question *n* with its answer passage.

<img alt="fig1" src="docs/figures/fig1_funnel.png" style="width:100%;max-height:none">
*Figure 1. The registered 16,749 placed once each (`results/census/corrected.json`). "Not found yet" (5,077) = 5,007 the adapters looked at without a counted row (943 of them wait for a person) + 70 no adapter covers.*

## 3. Use of Apertus

**Closed form only.** Apertus never writes a value. (i) *Verifier* (P7, `repair/adapters/adjudicate.py`): for an adapter review row it answers "does this document print the executive's answer to this intervention (number, title)?" (yes vs no scored after a JSON prefix, θ_A = 8) and picks the answer date among the printed dates or none (θ_B = 10); a row is promoted only if both pass and the date passes the adapters' own date rule. (ii) *Pointer* (`convert/pointer.py`, prompts `src/prompts/{de,fr,it}`): the document (first 12,000 characters) and the question in the user message, the assistant turn prefilled with a JSON prefix, `null` and every distinct printed date scored by summed log-probability; null if `lp(null) − logsumexp(lp(dates)) > θ`. Code locates every span (`pointer.locate`: the occurrence nearest an answer anchor, else the first). θ does not transfer across builds, so it is fitted per build on dev documents and frozen (θ = 10.40, AUROC 0.99). The same form picks labels and, in `qa/`, the question a paragraph answers, the recommendation sentence or the submitter's printed name. **Why closed:** asked freely, Apertus dates 15/15 (8B) and 14/15 (70B) Bern interventions that have no answer.

**Which model.** Evaluation used **Apertus v1.5 70B weights served by Public AI** under the name `swiss-ai/apertus-v1.5-8b` (inferred from the served fingerprint `tp8-pp2-…` and 760/792 greedy outputs byte-identical to the `-70b` name); the response `model` is checked on every call. The real **8B** (`swiss-ai/Apertus-v1.5-8B`, a community 4-bit GGUF, sha256-pinned; not an official release) ran in-process on CPU with its own θ = 16.73 on P1, P2 (52 reachable documents) and P6 (67 documents, exploratory): it finds answer dates nearly as well (P2: 15 of 21 vs 70B 16) but dates more answerless documents with the v1 pointer (P1 25 of 90, 70B 7; P6 18/34), and the reader v2 restrains it (P6: 5/34; v2 51/67 vs v1 48/67; rules then v2 55/67 vs rules 54/67). **Recommendation:** `rules_only` unattended; for suggestions the 8B as the sovereign option, the 70B for accuracy on infrastructure the operator chooses. Review mode stops (exit 3) on a served build θ was not fitted on.

**Cost** (`results/report/cost_end_to_end.json`, one core, no GPU). Fetch, extraction and checks about 2.1 s per document plus 6.9 s per OCR page; the rules process 480 documents per second (0.5 CPU-hours for all 902,754 documents in OPD's export). Review mode: 3.5 calls and 5,905 billed prompt tokens per residue document on the 70B, USD 0.59 per 1,000 residue documents; P7's verifier on the whole queue cost USD 0.50. The 8B takes 180 s per document on 4 vCPUs.

## 4. Data and operations

**Data.** OPD bulk exports (snapshot 6 Oct 2026; CC BY 4.0, "Source: OpenParlData.ch"; OPD's API robots.txt disallows `/v1/`), Bern open data, Fedlex, parliament sites, fetched politely (≥ 1.2 s per host and process). `data/` and `results/` are CDLA-Permissive-2.0 and carry OPD's attribution. **Operations.** `make run` and the nightly unit run the image read-only, as a non-root uid, with `--cap-drop ALL`; PDFs are capped at 50 MB and 600 s. One real night under systemd on a GitHub runner (83 min, Bern list reproduced on live data), then **two consecutive real nights in the recommended Docker setup** (Actions run 38098822336): night 1 took 86 min and streamed 6.4 GB; night 2, on night 1's state and OPD's next export, took 6.6 min (12 bodies re-scanned), 0 alerts, Bern list unchanged. The job does not run at OPD yet. **Incident** (`docs/incidents.md`): our network layer judged robots.txt with Python's first-match parser, where RFC 9309 requires the longest match. Between 9 and 11 Oct the project requested 147 distinct URLs on paths www4.ti.ch (Canton Ticino) disallows, 133 of them downloads; CI runs repeated at most 4,942 downloads before the fix (each process at least 1.2 s apart, at most 8 at once). No other host was affected. Since 11 Oct an RFC 9309 matcher judges every fetch (fail-closed once the guard is loaded), and every fetch path requests OPD's own copy on files.openparldata.ch instead.

## 5. Results without a model: schema verdict, census, repair

**Table 1. The 17 fields.** *Class*: does the field mean the same thing in every parliament (`results/census/comparability.json`)? *Where it lives*: parliaments where OPD metadata carries it · carries it for part of the affairs · only the PDF · not in OPD's data (`results/census/matrix.json`).

| field | class | meaning tested? | where it lives (metadata · mixed · PDF only · none) |
|---|---|---|---|
| answer date | role split | measured: decided, dispatched or registered; in 7 of 54 bodies mostly the submission date | **metadata**: 53 · 1 · 0 · 0 |
| procedural history | role split | measured: 35 event labels carry different date roles | **metadata**: 78 · 9 · 1 · 1 |
| type | role split | measured: 42 of 1,038 raw labels map to different types | partly: 61 · 24 · 2 · 2 |
| procedural state | role split | measured: 32 labels ambiguous | partly: 41 · 27 · 18 · 3 |
| decision outcome | role split | measured: 3 labels ambiguous | partly: 7 · 31 · 33 · 6 |
| government recommendation | shared | untested; OPD's mapping unambiguous (string check) | partly: 3 · 8 · 56 · 10 |
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

4 fields are in OPD's metadata almost everywhere, 13 partly or only in the PDF. The recommendation's string check (0 of 183 raw labels map to two concepts) covers only labels OPD has harmonised (29.1% of all events carry no harmonised id). Three further *concepts* are body-specific: oral answers in question time (23.6% of question-time answers), executive business that answers no member's affair, and councils that publish only meeting documents (16 bodies; v0.1 marks affairs rebuilt from minutes `virtual`, P4).

<img alt="fig2" src="docs/figures/fig2_matrix.png" style="width:100%;max-height:none">
*Figure 2. Where each field comes from, per parliament. Orange = not in OPD's data for that parliament (the parliament may still publish it).*

**Cross-parliamentary question.** Of the 91,268 interventions with a written government answer, 81.6% have answer text attached in OPD (the registered count), 82.3% counting answers filed under an agenda item of the affair, 85.0% after the Bern relink and 92.3% after every counted repair. Answer times are not one quantity: the median is 112 days where OPD's "answer" date is the verified decision date (Bern, Ticino), 79 on a government's weekly sitting, 39 for diffuse, publication-like dates; in 7 parliaments the "answer" is the submission date.

**Repair.** *Bern*: of 3,532 answers the canton publishes OPD attaches 229 (6.5%), although 96.1% are in OPD and linkable without a model. 2,459 relink candidates = 2,421 that pass every check against OPD's own copy (affair number, heading, decision date = OPD's answer event [97.9, 98.9]) + 38 to review. The document `hash` is sha256(body_key + parent_type + url) (49,810 of 49,810 rows), so relinking changes each identifier and file URL unless OPD keeps the old one. *Source adapters* (`docs/adapters.md`): readers for 50 parliaments (27 yield counted rows) verify 6,613 answers by affair number or title, the parliament's answer formula and a date check, in three tiers (own date equals an OPD event 5,161; a printed date equals an OPD answer event 1,056; documented window 396). 2,177 of them are already in OPD with text under a heading the census lexicon does not list: the repair is a category on the document (`tag_answer`). Listed, not counted: 282 Jura answers matched by identity and wording only, and 917 review rows (214 of them promoted by Apertus into a separate tier, §6). **Blind audit v3** (`results/repair/adapters/audit3/`): 200 counted rows and 60 decoys, shuffled into packets without the pipeline's verdict; blind for Qwen, blind by instruction for the Claude auditor (packets carry a text hash that joins to the lists); the key's hash reached GitHub before the Claude verdicts were finished. Claude Opus judged 197/200 counted rows to be the executive's answer (Wilson 95.7% to 99.5%), and the date wrong or unsupported on 15. It rejected 60% of the failed decoys but only 1.5% of the counted rows. Both auditors are LLMs; no person audited.

## 6. Evaluation: eight pre-registrations

**Design.** Each test froze code, prompts, θ and the scorer by sha256 before any label was committed. Unit (P1, P2, P6): one document's answer date, strict. Arms on identical inputs: **rules**; **pointer**; **cascade** (rules, then the pointer on the residue); **naive** free generation, plain and null-allowed; trivial baselines. **Timing:** all 74 annotator sessions ended before GitHub received their labels; in the eight locked sets they started after it received the LOCK and draw pushes (P5 dev has no lock by design; DEV2's anchor is the commit of its written selection rule and draw; transcripts stay on the author's machine). P1's rules were committed with its sample (D12), so P2 is the clean out-of-sample test of the rules.

**Table 2. The eight tests, in registration order.**

| test | n | what it tests | registered result | note |
|---|---|---|---|---|
| P1 | 154 documents, parliaments with rules | answer date: rules vs Apertus | **partial**: H3 held; H1 null safety failed (7/90); H2 Branch B | rules alone 135/154, so no model by default |
| P2 | 62 documents, 15 parliaments without rules | rules transfer; pointer vs rules | **3 of 4 held**; H3 null safety failed (4/33) | pointer 24/29 dates, rules 2/29 |
| P3 | 29 whole affairs, 10 parliaments | 7 fields: metadata, rules, Apertus | **partial**: no field unattended; Apertus recall held, precision below | feasibility study (D3-5) |
| P3b | 36 fresh affairs, 9 parliaments | replication of P3 | **held**: replicated (S1, S2) | S2 lenient; type 35/36; addressed body 2/33 |
| P4 | 120 agenda items, 6 sittings | affairs rebuilt from minutes | **partial**: H2, H4 held; H1, H3 failed | recall 99/120, precision 99/99 |
| P5 | 40 fresh affairs, 10 parliaments | Q/A pairs, people, recommendation | **partial** tier (H1); H2, H5 held; H4 as rules vs free generation; H3 no gain | *not yet* when parliaments are resampled |
| P6 | 68 fresh documents, 8 parliaments | answer-date reader v2 vs free prompting | **failed**: no hypothesis held | free prompt 62/68, v2 59/68 |
| P7 | 478 review rows, 190 blind packets | Apertus as verifier of the review queue | **H1 holds** (120/120); H4 supported; H3 not supported | 214 of 917 rows promoted |

**Unattended** (95% lower bound ≥ 0.80, document-level intervals): the rules' answer date where rules exist (P1, helped by right nulls: dates found 47/64), the type on whole affairs (P3b, 35/36), and in P5 question detection (recall 167/187, precision 167/175), the reasoning span (37/40) and co-signatory precision (101/103). **Gold and checks.** No human labelled a gold value, by design: two blind Claude annotators (Opus, Sonnet), a third breaks ties, quotes verified by code, raw files committed. `Qwen-SEA-LION-v4-32B-IT` (AI Singapore) relabelled P1, P2, P6 and P7 blind: date κ 0.80, 0.87 and 0.86, P7's is-answer labels 185/190; no registered decision changes. On P5 its labels pass the quote check in 7/40 files; the disagreement was not adjudicated, so the recommendation count rests on the Claude gold. Non-LLM checks: OPD's event matches 37 of 44 checkable P1 dates; P6: 10/10, every gold quote on its page (34/34). Holm: all 4 held conclusions of P1–P4 and P3b survive; whole parliaments are resampled as well (`results/eval/posthoc_r6_cluster.json`).

| P1 arm (154 documents) | exact [95% CI] | answered: found /64 | wrong printed date | invented | answerless dated /90 |
|---|---|---|---|---|---|
| **rules only (default)** | **135/154 [81.5, 92]** | 47 | 4 | 0 | 2 |
| pointer | 130/154 [77.9, 89.3] | 46 | 16 | 0 | 6 |
| cascade | 139/154 [84.6, 94] | 56 | 11 | 0 | 7 |
| naive, null-allowed | 134/154 [80.8, 91.4] | 47 | 11 | 0 | 3 |
| *trivial: latest date on answer-typed documents* | *131/154 [78.6, 89.8]* | *44* | *16* | *0* | *3* |

**P1:** H1 null safety failed (the cascade dates 7 of 90 answerless documents, 6 of them council reports; upper bound 15.2% vs 10%); H2 gave Branch B (cascade alone right on 5, rules alone on 1, p = 0.22), so Apertus left the unattended path for an opt-in review suggestion (D6); H3 held (AUROC 0.969). The 8B cascade: 119/154, 25 of 90 answerless dated.

| P2 arm (62 documents) | exact [CI] | answered: found /29 [CI] | wrong date | invented | answerless dated /33 |
|---|---|---|---|---|---|
| rules only | 35/62 [44.1, 68.1] | **2/29** [1.9, 22] | 2 | 0 | 0 |
| **pointer** | **53/62** [74.7, 92.2] | **24/29** [65.5, 92.4] | 8 | 0 | 4 |
| naive, null-allowed, re-parsed (D2-4) | 54/62 | 24/29 | 7 | 1 | 3 |
| *trivial: latest printed date* | *24/62* | *22/29* | *38* | *0* | *31* |

**P2:** the rules collapse off their home layouts (47/64 → 2/29). H2 held: on all 62 documents the pointer beats the rules on 22 and loses on 4 (p = 5.3 × 10⁻⁴); resampling the 15 parliaments, the gain is [-0.02, 0.54], so it sits in a few parliaments. "Answerless" means no qualifying answer date: the pointer's 4 such dates all fall on documents that contain an answer but print no qualifying date; of the 25 with no answer at all it dates none. Against the free prompt with null allowed: ahead on 2, behind on 1.

**P3/P3b/P4.** Default (metadata + rules) on 29 affairs: type 27/29, answer date 22/27, 27/27 with Apertus suggestions; the addressed body is withdrawn as evidence (every gold value is "executive", D3-3; P3b: C 2/33). P3b replicated by its registered criteria; its answer date (C 20/35) fell below P3's interval, 3 wrong dates from a Luzern rule that overrode OPD's correct date (the product path now keeps OPD's date and flags the record); with Apertus 31/35. P4: 99 of 120 agenda items as virtual affairs, precision 99/99, no decision invented (0/36). **P5.** Rules-only pairing: precision 118/143 = 0.83, recall 118/176 = 0.67, *partial* with document-level intervals, *not yet* when parliaments are resampled (precision [0.66, 0.97]); Valais 0/11. H2: rules beat paragraph order 116:5. H4, read as rules vs free generation: 79:11 (the pointer never fired, H3). Recommendation 34/40 by rules; submitter rules 12/40, pointer 24/40, free generation 34/40.

| P6 arm (68 documents, 34 answered) | exact | answered: found | answerless dated | printed nowhere |
|---|---|---|---|---|
| free prompt, null allowed | **62/68** | 32/34 | 4/34 | 0 |
| cascade v2 (rules, then v2) | 60/68 | 31/34 | 5/34 | 0 |
| v2 | 59/68 | 30/34 | 5/34 | 0 |
| rules only | 54/68 | 20/34 | 0/34 | 0 |
| *trivial: latest date on answer-typed documents* | *51/68* | *25/34* | *8/34* | *0* |
| *model-free cascade (post hoc)* | *55/68* | | | *0* |

**P6 — reader v2** (an answer-present gate, then the gold guide's decision-before-letter-date rule). No registered hypothesis held: v2 vs free prompting 1:4 (p = 0.38); v2 dates 5/34 answerless documents (upper bound 30.1% vs 15%), all 5 on documents that contain an answer without a qualifying date; v2 vs v1 5:2 (p = 0.45). On all 68 documents cascade v2 beats the rules on 11 and loses on 5 (p = 0.21); the model-free cascade scores 55/68 (cascade v2 ahead on 5, behind on 0, p = 0.06).

**P7 — Apertus as verifier of the review queue** (`eval/prereg8/`, LOCK8 before the draw). Test frame: 478 eligible review rows outside every audit; 190 blind packets, gold A1 Opus / A2 Sonnet. H1 (primary): promotion precision 120/120, Wilson lower bound 96.9% ≥ 0.90: **holds**. H4: dated precision 95.8% vs 73.2% for a trivial exact-date match, +22.7 points [10.2, 34.3]: **supported**. H3: the rows free generation with a printed-date filter adds are 28/30 right: **not supported**. Base rate: 86.7% of eligible queue rows are answers, but only 40.9% are answers whose own date passes the rule, so the gain is the date check; all 10 gold-no rows were stopped by the yes/no question. Applied to the whole queue, 214 of 917 rows go to the tier `promoted_by_apertus`, next to the 6,613 counted rows, never inside them.

**What the tests say.** Apertus earns its place where layout varies and no rule exists (P2, P3) and as a closed-set verifier with a date check (P7). **It does not abstain reliably** as a date reader: every null-safety test on the 70B failed (P1-H1, P2-H3, P6-H2). **Accuracy is not its argument:** the same Apertus asked freely with null allowed is as accurate (P2 54 vs 53 of 62; P6 62 vs 59 of 68; P7-H3). **Provenance:** no arm that picks from printed dates returned a date printed nowhere, on P1, P2 or P6; the free prompt that may return null did so 0, 1 and 0 times, so a printed-date filter on it would give the same guarantee; the closed set adds a location for every value and a margin that orders the review queue.

## 7. Limitations, reproducibility, declarations

Answer dates are tested in depth, Q/A pairs on 40 affairs; tables, annexes and images are not extracted; P3/P3b are small, P4 is one commune, P6 has no Italian document, no gold set contains federal documents; spans index our own pdftotext/tesseract text (`--opd-text` maps them onto OPD's). `make run` (Docker, CPU, clean checkout) recomputes the census and the Bern join, re-derives the P1 rules arm from the source PDFs and the P1/P2 Apertus decisions from the model cache, replays 26/26 tests locally (P1–P6, the 8B analysis, the 7 LOCK files of P1–P6; P7 recomputes with `python -m eval.p7.hypotheses8`), and recomputes every number in `claims.tsv` from its results file, failing if a document prints anything else. Claude Code agents (Anthropic) wrote most code, documentation and the gold labels; numbers are checked by code. Public AI (may route outside Switzerland) served evaluation only. Next: the Bern, Fedlex and adapter lists and the nightly job at OPD; a person or OPD to confirm the review rows; schema v0.2 (date roles, `QAItem`, five gaps) with the eCH group. Report CC-BY-4.0; standards in `docs/mapping.md`.
