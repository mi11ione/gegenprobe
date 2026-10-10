# Technical report — Gegenprobe: where Swiss parliamentary answers go missing, how to put them back, and a converter whose every value is printed in the source

**Track 2A — OpenParlData** · Online · Team 444 — Roman (+ Claude Code agents, §9) · Evidence site https://gegenprobe.mi11ion.io · `make run` re-scores P1–P4 from committed labels, re-runs all hypotheses, re-derives the rules arm from source PDFs and recomputes Apertus's decisions from the model cache (§8) · **Maturity:** census, repair lists, nightly job = *deployable prototype*; rules-only converter = *tested prototype*; review mode, whole and virtual affairs = *feasibility study*; schema v0.1 = *draft*.

## 1. Summary

**Promise and reality.** OpenParlData (OPD) publishes the affairs of 89 Swiss parliaments with affairs in scope (it scrapes 90) "to create transparency, promote participation and enable data-based political education". Of 91,268 interventions whose events record a written government answer, **16,749 (18.4%) have no answer text in OPD** (2024–25: 1,855, 14.3%), 1,008 of them Valais oral answers filed as stubs; we type every one by cause. In Bern the canton publishes 3,532 answers and OPD attaches 229 (6.5%), although 96.1% are already in OPD and linkable; OPD confirmed the bug (correspondence, 10 Oct 2026) and that our relink list is the workaround until its fix ships. Deterministic routes repair 3,107 of the 16,749; 11,206 need per-parliament source adapters.
**Schema.** The concepts are shared; what differs is where the value lives, the vocabulary and the date roles. Of 17 fields, **4 are feasible** from OPD metadata alone, **13 partial**, **0 fundamentally different**; "answer date" is shared only with a role split (decided, dispatched, registered).
**Converter.** Every value it returns is printed in the source document, with page and character span, or is a typed null; it can still pick the wrong printed date (rules: 4/154 held-out documents; Apertus: 8/62 on unseen parliaments), so rules run unattended and Apertus's values are review suggestions. Apertus earns its place on **15 parliaments the rules never saw**: 24/29 answer dates where the rules find 2/29, exact 53/62 against 44/62 for the best one-line baseline; it wins in 6 parliaments, loses in none (sign test p = 0.031). On whole affairs it completes the answer date (22/27 → 27/27). For a commune that publishes only minutes, rules derive 99 virtual affairs with item precision 99/99 and no invented decision, but recall (99/120, H1) and Apertus's added decisions (H3) missed their registered bars, and decisions do not transfer to a second commune (0/9).

## 2. Architecture

1. **Census** (`census/`): streams the OPD exports once, keeps metadata only, and computes the answer funnel, a per-affair *answer-link status* (`attached | agenda | parentless | absent | image_only | oral`), the feasibility matrix and a comparability measure from OPD's own vocabularies. A vendored extract (`data/census/`) lets `make run` recompute every census number.
2. **Repair** (`repair/`): deterministic routes per cause, verified by a triple check (affair number printed, answer heading present, decision date = OPD's answer event), as lists keyed on OPD ids. A nightly job (`deploy/nightly/`, `docs/runbook.md`) re-runs the joins and raises alerts.
3. **Converter** (`convert/`): per document, (i) OPD metadata and events, (ii) frozen DE/FR/IT anchor rules, (iii) the Apertus closed-set pointer on the residue. Modes: `rules_only` (default, unattended, no model) and `review` (pointer values attached as suggestions with page, span and margin, flagged `needs_review`). CLI with batch mode (`docs/convert-your-own.md`).
4. **Schema and validator** (`schema/`, `validate/`): Pydantic schema v0.1, normative; every field is a value with provenance `{value, role, page, char_start, char_end, quote, route, rule, model_build, θ, margin}` or a *typed null* (`not_in_document | unlinked | image_only | oral | text_failed | present_unanchored | not_applicable`); `QAItem` pairs question *n* with answer *n* (not yet filled). The JSON Schema export for OPD's workbench cannot express the cross-field rules (a rule value must carry page and span), so validation uses the Pydantic models.

![fig1](docs/figures/fig1_funnel.png)
*Figure 1. National answer funnel with typed causes and repair routes.*

## 3. Use of Apertus

**Closed-set pointer** (`convert/pointer.py`, prompts `src/prompts/{de,fr,it}`). The user message holds the document (first 12,000 characters) and the question; the assistant turn is prefilled with a JSON prefix (`{"antwort_datum":`); `null` and every distinct date printed in the document are scored as continuations by summed log-probability (exact forced choice via `prompt_logprobs`). Null if `lp(null) − logsumexp(lp(dates)) > θ`, else the best date, mapped back to its span. θ does not transfer across builds (spike F2: a θ fitted on RLVR scores 0.25 on the final build), so it is fitted per build on dev documents and frozen: θ = 10.40 for the Public AI build (AUROC 0.99, leave-one-out 124/127 [93.3, 99.2]).

**Why a pointer** (earlier spikes, cited, `results/report/cited_spikes.json`). Asked freely when the government answered, Apertus writes a precise date for 15/15 (local 8B) and 14/15 (70B) Bern interventions that have no answer, often copying the "Letzte Bearbeitung" footer; a null-allowed prompt fixes this on the 70B (0/15) but not on the 8B (14/15).

**Which Apertus.** All Apertus results so far are the **70B** weights, served by Public AI under the name `swiss-ai/apertus-v1.5-8b` (cited: 760/792 greedy outputs byte-identical to the 70B name; MMLU 84.4% vs 70.8% for the v1 8B route); a system message or prefill to the `-70b` name is answered by Qwen-SEA-LION (3/3), so forced choice goes only to the `-8b` name and the response `model` field is checked on every call. The real 8B arms (GGUF Q4_K_M, CPU) are running on CI; our CPU scorer agrees with bf16 on 58/60 decisions, as close as the spike's Metal build (57/60; a stricter parity rule fixed in advance failed, 10/12; `results/eval/gguf_impl60.json`).

**Cost** (`results/report/cost_end_to_end.json`, one core, no GPU). A document costs about 2.1 s to fetch politely, extract and check, plus 6.9 s per page where OCR is needed; the rules process 480 documents per second (0.5 CPU-hours for all 902,754 documents in OPD's export). Review mode adds the pointer on the residue (97 of 154 held-out documents): 3.5 calls and 5,905 billed prompt tokens per residue document on the 70B; 8B cost per residue document pending the CI run. At ten times OPD's volume: about 5 CPU-hours for the rules, about USD 3,357 at Public AI's list price for review mode.

## 4. Data and operations

OPD bulk exports (affairs, events, agendas, docs, texts, contributors; snapshot 6 Oct 2026, contributors 9 Oct). `api.openparldata.ch/robots.txt` reads "Block all API data endpoints (not for SEO)" above `Disallow: /v1/`; we use the bulk exports, which also makes every number reproducible from a dated snapshot. Bern open data, Fedlex, source PDFs fetched politely (one configurable User-Agent, ≥ 1.2 s per host; robots.txt fails closed: an unreadable robots.txt means no fetch that night). The container never runs as root (uid 10001, capabilities dropped); PDFs are capped at 50 MB, each pdftotext/tesseract call at 300 s, each document at 600 s, every hit a typed failure row. Alerts go to an outbox before the night's state is committed, so none is lost. Inside OPD (`GP_EXPORTS_DIR`) a full night takes 96.8 s with 0 bytes of export transfer. The research dataset `results/census/interventions.tsv.gz` has 91,268 rows with a per-body date-trust tier. `data/` holds ids, URLs, hashes, labels and quotes of ≤ 200 characters; no full texts, no personal contact data.

## 5. Results without a model: schema verdict, census, repair

![fig2](docs/figures/fig2_matrix.png)
*Figure 2. Where each schema field comes from, per parliament (all 89 in `results/census/matrix.csv`).*

**Where the value lives.** A field is *feasible* if OPD metadata carries it in ≥ 80% of eligible parliaments, *fundamentally different* if ≥ 20% have no written source, else *partial* (written down before computing; criteria and matrix were committed together). **4 feasible** (submission date, answer-event date, procedural history, answer-link status), **13 partial**, **0 fundamentally different**; at a 10% no-source threshold 5 fields would be (`results/census/tier_sensitivity.json`). Type is harmonised for 82.9% of affairs, procedural state for only 278; the government recommendation is in metadata for 34.2% of motions and postulates and PDF-only in 56 bodies.

**What the value means** (`results/census/comparability.json`; classes `data/schema/field_verdict_classes.json`):

| class | fields and concepts | evidence |
|---|---|---|
| shared | submission date, submitter, co-signatories, addressed body, recommendation, decision and dispatch dates, Q/A pairing, related affairs, language, usable text, link status | one meaning; only where the value lives differs |
| shared with a role split | **answer date**, procedural history, type, procedural state, decision outcome | in 7 of 54 bodies the "answer" event is mostly the submission date; OPD's event equals the printed date for 37 held-out documents and differs for 7; 35 event labels carry different date roles; 42 of 1,038 type labels map to different harmonised types ("Antrag" alone to 7); 32 state, 3 outcome labels ambiguous |
| body-specific | oral answers, executive-own business, minutes-only councils | 23.6% of question time is oral; 16 bodies publish only meeting documents, 8 without any affair → `virtual` affairs (P4) |

29.1% of events have no harmonised id. Where OPD metadata carries a field it mostly agrees with print (P3: type 17/18, submitter 23/28, submission date 15/21; affair numbers 21/29, format differences). Five schema gaps recur across 12 bodies; Chao2 could not estimate the missing schema's size (≈ 57.4 new accounts per body, no saturation). **Cross-parliamentary question:** across 54 parliaments, 82.3% of written answers have their text in OPD (85.0% after the measured repairs); the median government answers in 68 days (69 without the 7 same-day bodies; Question time 5).

![fig3](docs/figures/fig3_be_before_after.png)
*Figure 3. Bern: answers attached to their affair today vs linkable within OPD.*

**Repair.** Bern: 229 attached, 527 under an agenda item, 2,638 parentless with the canton's document uid; the relink list holds 2,459 relinks and 49 fetches, the other 179 parentless answers are not missing (155 affairs already have the text, 24 have no answer event). The spike sample verifies 40/40 [91.2, 100] and OPD's answer event equals the decision date 39/39. Checked against OPD's own copy, all 2,459 relinks match affair number and heading; the decision date equals OPD's event for 2,332 with the registered parser and 2,421 [97.9, 98.9] with a parser written afterwards, 38 go to review (pre-registered sample: 36/40, three parser misses and one canton typo; one reconciliation table: site `#bern-numbers`, `results/repair/be_reconcile.json`). A second list corrects 727 Bern `begin_date` load timestamps (557 on 2024-10-28 + 170 from later loads, the groups OPD described; 554 from the affair's own submission event). Federal placeholders (57.3% of federal documents store Fedlex's "JavaScript required" page): Fedlex SPARQL plus filestore recovers 19/20, and 40/50 [67, 88.8] fresh; the 29,946-document backlog takes about 17.5 h once. Scans: 15/30 "text-missing" answers are image-only (13 are Valais stubs); DE+FR+IT OCR recovers 15/15 [79.6, 100], keeping 467 accented characters where English OCR keeps 133. From outside OPD the nightly job re-downloads most exports (68/116 files changed within three days).

## 6. Evaluation: four pre-registrations

**Design.** Every test freezes code, prompts, θ and the scorer by sha256 before any label exists. GitHub's clock shows the order (`results/eval/lock_server_times_all.json`; rewritten SHAs, originals in `docs/commit-map.md`): LOCK `912bda2` (orig. `812030f`) 2026-10-09T19:38:07Z → labels `6eb4d3b` (orig. `ded0033`) 2026-10-09T19:44:06Z; LOCK2 `5b044a2` (orig. `3dde418`) → labels `dbf387e` (orig. `2e4a9d6`); LOCK3+4 `a0e4636` (orig. `922218d`) → P3 labels `7750b6c` (orig. `d90bae7`), P4 labels `8cf32f9` (orig. `8a40ca1`). The clock proves order, not effort: agent annotators take minutes. Unit: one document's answer date, strict. Arms on identical inputs: **rules**; **pointer** (Apertus on every document); **cascade** (rules, then the pointer on the residue = every review suggestion accepted); **naive** free generation, plain and null-allowed, same weights. Gold: two blind annotators (Claude Opus, Sonnet), quotes verified by code, a third decides disagreements; no human labels by design; κ recomputes. Deviations: `eval/prereg*/DEVIATIONS*.md`.

**P1 — 154 held-out documents from the parliaments the rules were written for** (DE/FR/IT × canton/commune + Ticino scans; 64 with an answer date, 90 without; always-null 90/154; κ 0.95 presence, 0.94 date, 148/154 identical; 41 tie-breaks; OPD oracle 37 agree / 7 differ).

| arm | exact [95% CI] | dates found | wrong printed date | fabricated | values on answerless |
|---|---|---|---|---|---|
| **rules only (default mode)** | **135/154 [81.5, 92]** | 47 | 4 | 0 | 2 |
| pointer | 130/154 [77.9, 89.3] | 46 | 16 | 0 | 6 |
| cascade (suggestions accepted) | 139/154 [84.6, 94] | 56 | 11 | 0 | 7 |
| naive, null-allowed | 134/154 [80.8, 91.4] | 47 | 11 | 0 | 3 |
| naive, plain | 98/154 [55.8, 70.8] | 47 | 23 | 24 | 39 |

*8B rows: pending the CI run (GGUF Q4_K_M, own θ).* **H1 null safety failed**: the cascade dates 7 of 90 answerless documents (upper bound 15.2% vs 10%). **H2, Branch B**: on FR+IT+scans (n = 110) the cascade alone is right on 5 documents, the rules alone on 1 (p = 0.22; pooled 9 vs 5, p = 0.42), so rules run unattended and Apertus's answers are review suggestions. **H3 passed**: AUROC 0.969 on all documents, 0.966 on the registered length-matched set. **H4 triggered**: 3 of 8 Apertus-decided FR/IT values are wrong. Post hoc: latest printed date on documents OPD types as answers is exact on 131/154.

**P2 — 62 documents from 15 parliaments absent from every dev and held-out set** (29 with an answer date, 33 without; always-null 33/62; κ 1.0).

| arm | exact | dates found | wrong printed date | fabricated | values on answerless |
|---|---|---|---|---|---|
| rules only | 35/62 | **2/29** | 2 | 0 | 0 |
| **pointer** | **53/62** | **24/29** | 8 | 0 | 4 |
| cascade | 51/62 | 22/29 | 10 | 0 | 4 |
| naive, null-allowed | 52/62 | 22/29 | 7 | 1 | 3 |
| naive, plain | 45/62 | 21/29 | 8 | 4 | 9 |
| *latest date on answer-typed documents (post hoc)* | *44/62* | *18/29* | *13* | *0* | *7* |

**P2-H1**: the rules' recall drops from 47/64 to 2/29. **P2-H2 holds**: by parliament (post hoc, D2-1), the pointer wins in 6, the rules in 0, 1 tie (sign test p = 0.031); by document, as registered, 22 vs 0 (McNemar p = 4.8 × 10⁻⁷; without Bellinzona 17 vs 0, p = 1.5 × 10⁻⁵). **P2-H3 failed**: the cascade dates 4/33 answerless documents (upper bound 27.3% vs 15%). **P2-H4 holds**: AUROC 0.983. *Error profile:* rules right 35, wrong printed date 2, answerless dated 0, missed 25; pointer 53, 4, 4, 1; cascade 51, 6, 4, 1. The cascade trails the pointer because on 2 documents a rule (`rrb_vom`) fired with a wrong printed date, so Apertus was never asked; no document goes the other way. Consequence: review mode for parliaments without rules.

**P3 — whole affairs: 29 affairs (58 PDFs), 10 parliaments (5 with rules, 5 without), DE/FR/IT.** Arms: OPD metadata (M), rules (R), the default metadata + rules (C), C + Apertus suggestions on fields C leaves open (CA); annotators agreed on ≥ 27/29 affairs per field.

| arm | type | number | submitter | submitted | answer date | addressed body* | decision no.† |
|---|---|---|---|---|---|---|---|
| M | 17/29 | 21/29 | 23/29 | 15/21 | 21/27 | 0/28 | 0/17 |
| R | 26/29 | 14/29 | 5/29 | 4/21 | 16/27 | 4/28 | 5/17 |
| **C** | **27/29** | **21/29** | **23/29** | **15/21** | **22/27** | **4/28** | **0/17** |
| CA | 27/29 | 21/29 | 23/29 | 15/21 | 27/27 | 23/28 | 0/17 |

\*Every gold value is "executive"; a constant scores 28/28 (D3-3). †Defect D3-1: the frozen cascade's metadata branch drops the rule's number; post hoc C = 5/17. No field reaches the unattended bar (lower bound ≥ 0.80). H3 (Apertus on open fields) 25/32 recall, 25/34 precision is dominated by the near-constant field, so the addressed-body claim is withdrawn; without it 6/8 and 6/9. Set fields (C, registered): co-signatories precision 13/16, recall 13/29 (OPD metadata); related affairs 6/9, 6/14 (rules).

**P4 — virtual affairs: 6 held-out sittings of Bulle's council, 120 agenda items.** Rules derive 99 items (precision 99/99, titles 99/99), type 91/99 (H2 holds), the decision for 49/63 (46/63 correct), invent none of 36, and date all 6 sittings (H4 holds). **H1 failed** (recall 99/120, 82.5%; sub-items, unnumbered lines); **H3 failed** (Apertus +2 decisions, p = 0.5). Transfer cell (2 sittings of La Chaux-de-Fonds, D4-4): items 9/9, titles 9/9, decisions 0/9 by rules, 2/9 found with Apertus (1 correct): decision parsing is commune-specific.

![fig5](docs/figures/fig5_scoreboard.png)
*Figure 5. Scoreboards of P1 and P2 (frozen code).*

**What the four tests say.** Apertus earns its place where layout varies and no rule exists: unseen parliaments (P2: 53/62 vs 44/62 for the best trivial baseline and 35/62 for the rules; 6 parliaments to 0) and the answer date of whole affairs (P3: 22/27 → 27/27). Where structure is regular (P1, P4) rules suffice. A well-prompted 70B is about as accurate on answer dates (P1 134 vs 139; P2 52 vs 53) but can write dates printed nowhere (1 in P2, 24 with the plain prompt in P1) and returns no span. **Post hoc** (`results/eval/robustness.json`): the cascade's gain over the rules on FR+IT+scans is +3.6 points (95% CI −1.4 to 9.3; detectable effect 6.2); asking Apertus only on documents typed as answers would give 143/154 with 2/90 values on answerless documents. Hypotheses for the next registration, not results.

## 7. Limitations

Answer dates were tested in P1/P2, whole affairs on 29 (P3), minutes in one commune plus a 2-sitting transfer (P4). No gold set contains federal documents; the pointer sees at most 12,000 characters. Gold labels come from AI annotators with high agreement and an external oracle check, not from humans. The 70B results come from one provider build; θ must be refitted per build. 11,206 missing answers need source adapters that are not built; OCR was measured on a probe. Spans index our own pdftotext/tesseract text (`--opd-text` maps them onto OPD's stored text).

## 8. Reproducibility

`make run` (Docker, CPU, clean checkout) recomputes the census, replays the Bern join and triple check, converts sample documents with all validator checks, re-scores P1–P4 from the committed predictions and labels, re-runs the four registered hypothesis scripts, verifies the four LOCK files, re-derives the P1 rules arm from the source PDFs fetched by sha256, recomputes every P1 and P2 Apertus decision from the committed model cache, and recomputes all 509 numbers in `claims.tsv` (matched as whole tokens; values of ≤ 3 characters pinned by a context phrase). Locally: rules 154/154, Apertus 154/154 (P1) and 62/62 (P2) identical. In the Docker run on GitHub's CI (run 38043355800, `results/ci/`) the time budget allowed 138 of 154 rules re-derivations, all 138 identical, and 129/129 recomputed P1 Apertus decisions matched; 24 prompts missed the cache because that image's poppler 22.12 extracts slightly different text, and P2 did not fit the budget (reported as WARN, never as a mismatch). With `LLM_BASE_URL` or `GGUF=1` a live slice runs.

## 9. Declarations

Claude Code agents (Anthropic) wrote most code, documentation and the gold labels under the protocols above; numbers were checked by code (`claims.tsv`, lock hashes, verbatim quotes, re-derivation), not by reading. No human labelled or adjudicated any gold value, by design. Public AI (which may route outside Switzerland) was used for development and evaluation only. The default mode needs no model; review mode adds a local GGUF or the endpoint the operator chooses.

## 10. Next steps

Hand both Bern lists and the placeholder list to OPD and run the nightly job beside their importer; build source adapters for the 11,206 answers that exist only at the source; date roles, `QAItem` and the five schema gaps in schema v0.2 with the eCH group; pre-register θ = 0 and type-gating; per-commune decision parsing and sub-item segmentation (the P4 gaps); virtual affairs for the other frontier bodies (`results/census/virtual_affairs.json`).

## License and references

Report CC-BY-4.0 (`docs/LICENSE-report.txt`). OpenParlData exports; Bern Grosser Rat open data; Fedlex; Apertus v1.5 model cards; Chao (1987); Popolo, Akoma Ntoso (`docs/mapping.md`).
