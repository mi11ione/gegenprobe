# Technical report — Gegenprobe: where Swiss parliamentary answers go missing, how to put them back, and what a common schema can carry

**Track 2A — OpenParlData** · Online · Team `team name` — Roman (+ Claude Code agents, §9) · Code in `track_2a/`, `make run` reproduces every headline (§8) · **Maturity:** census, repair lists, nightly job = *deployable prototype*; PDF-to-schema extraction = *feasibility study*.

## 1. Summary

**Promise.** OpenParlData (OPD) publishes the affairs of 89 Swiss parliaments "to create transparency, promote participation and enable data-based political education".
**Reality.** Of 91,268 interventions whose events record a written government answer, **16,749 (18.4%) have no answer text in OPD** (2024–25: 1,855, 14.3%). In Bern the canton lists 3,532 answers, but OPD attaches only 229 (6.5%) to their affair; 2,638 already sit in OPD as documents without any parent. 57.3% of federal documents store Fedlex's "JavaScript required" page as their text.
**Repair.** A model-free census types every missing answer by cause, and deterministic routes put answers back: 2,459 Bern relinks plus 49 fetches (the list reproduces byte-for-byte), 592 agenda joins, 1,008 Valais answers retyped as oral, OCR for image-only scans. In Bern, 96.1% of the canton's answers are linkable within OPD (attached, under an agenda item, or parentless by canton uid), against 6.5% attached today.
**Schema.** Over 17 fields × 89 bodies, by criteria written down before computing (not separately committed): **4 fields feasible today, 13 partial, 0 fundamentally different** — the concepts are shared; what differs is *where* the value lives (metadata in some parliaments, only in PDFs in others) and the vocabulary.
**Converter.** Free-generation Apertus invents an answer date on 14/15 answerless documents (live, 70B) and 15/15 (local 8B). Our converter lets Apertus only *point* at a value that exists in the document, or say null, and every value carries page and character span. On 154 held-out documents (pre-registered, blind gold) the cascade is exact on 139 (rules alone 135, naive free generation 98 with 24 fabricated dates) and fabricates nothing by construction, but it misattributes more than the rules (11 vs 4) and its gain is not significant. Apertus does not measurably add null-safety, so under our registration (Branch B) the default converter is rules only, and Apertus's answers on the residue become review suggestions (§6).

## 2. Architecture

![fig1](docs/figures/fig1_funnel.png)
*Figure 1. National answer funnel with typed causes and repair routes (`results/census`, `results/repair`).*

Four components (`docs/`):

1. **Census** (`census/`): streams the OPD exports once, keeps metadata only (no full texts), and recomputes the answer funnel, a new per-affair *answer-link status* (`attached | agenda | parentless | absent | image_only | oral`) and the feasibility matrix. A compact vendored extract (`data/census/`) lets `make run` recompute every census number without the exports.
2. **Repair** (`repair/`): deterministic routes per cause, each verified by a triple check (affair number printed in the document, answer heading present, decision date equal to OPD's answer event), written in OPD's export layout as `repair_<body>.tsv/json`. A nightly job (`deploy/nightly/`) re-runs the joins and raises alerts when a body's linking rate drops.
3. **Converter** (`convert/`): a cascade per document — (i) OPD metadata and events, (ii) frozen DE/FR/IT anchor rules, (iii) the Apertus closed-set pointer on the residue only. **Design rule: Apertus may only choose among values that exist in the document (or in OPD), or null.** It never generates a value. Two modes (`convert/modes.py`): `rules_only` (default, unattended, no model) and `review` (the pointer's residue value attached as a suggestion with page, span and margin, flagged `needs_review`).
4. **Validator and schema** (`schema/`, `validate/`): Pydantic schema v0.1 in which every field is either a value with provenance `{value, role, page, char_start, char_end, quote, route, model_build, θ, margin}` or a *typed null* (`not_in_document | unlinked | image_only | oral | text_failed | present_unanchored | not_applicable`); span re-check, typed-null consistency, footer-distractor and self-deletion tests. A JSON Schema export (`results/schema/`) fits OPD's Pydantic-based extraction workbench.

## 3. Use of Apertus

**Where and why.** Apertus decides only where rules cannot: unanchored dates, French/Italian formats without a lexicon hit, OCR'd text, the government-recommendation enum, and links to other affairs. The census and repair are model-free on purpose: they need to be exact, and they are. On the held-out set the rules carry the extraction; in the cascade Apertus decides 93 of 154 documents (the residue, mostly by abstaining) and supplies 16/67 values. After the held-out test these are review suggestions for OPD's existing manual-review step, not unattended values.

**Closed-set pointer** (`convert/pointer.py`, prompts in `src/prompts/{de,fr,it}`). The user message holds the document (truncated at 12,000 characters) and the question; the assistant turn is prefilled with a JSON prefix (`{"antwort_datum":`); every candidate — `null` and each distinct date printed in the document — is scored as a continuation by its summed log-probability (exact forced choice through `prompt_logprobs`). The decision is null if `lp(null) − logsumexp(lp(dates)) > θ`, else the best date, mapped back to its span (nearest answer anchor if it occurs more than once).

**θ per build.** A threshold does not transfer across builds, quantisations or prompts (spike F2: a θ fitted on RLVR scores 0.25 on the final build). We fit θ per served build on dev documents only and froze it: for the Public AI build θ = 10.40 nats (AUROC 0.99, leave-one-out 124/127 [93.3, 99.2], `data/convert/theta/`).

**Which Apertus.** The evaluation in this repository ran Apertus on Public AI through a budget gateway that caches by request hash and logs every call, and the 8B GGUF on GitHub's CPU runners; earlier exploratory spikes also ran Apertus 8B (MLX 4-bit) on our own machines. Prior measurements (cited prior work, not recomputed here; `results/report/cited_spikes.json`) shaped three rules: (a) the `swiss-ai/apertus-v1.5-8b` name serves the **70B** weights (760/792 greedy outputs byte-identical to the 70B name; 84.4% vs 70.8% on the same MMLU items as the v1 8B route), so we label every result from it as 70B; (b) a system message or prefill sent to the `-70b` name is silently answered by Qwen-SEA-LION-32B (3/3), so forced choice goes only to the `-8b` name and the response `model` field is checked on every call; (c) identical requests come from a response cache, so generation passes a seed. The real 8B runs as GGUF Q4_K_M (sha256-pinned) under llama.cpp on a CPU runner. Against bf16 on 60 cells, our llama-cpp-python scorer agrees on 58/60 decisions (mean |Δ| 2.66 nats), the spike's Metal build on 57/60 (2.87), libllama on CPU on 57/60 and 58/60 (3.25, 3.34) (`results/eval/gguf_impl60.json`). A parity rule we had fixed in advance (within 1.0 nat of the Metal build on 12 near-boundary cells) **failed** (10/12, 3.16 nats): implementations of one file differ from each other by about as much, and all sit equally far from bf16.

**Where Apertus fell short** (spike numbers cited, not recomputed here). Free generation invents: asked when the government answered, it writes a precise date on 15/15 answerless Bern documents (local 8B) and 14/15 (live 70B), often copying the "Letzte Bearbeitung" footer; a naive verbatim-quote check approves 10/15 of the local inventions. A null-allowed prompt fixes it on the 70B (0/15) but not on the 8B (14/15). Asking Apertus for the *role* of each date failed (AUROC 0.57). The pointer is the response to all three. On held-out documents the plain prompt fabricated 24 dates and put a value on 39/90 answerless documents, while the null-allowed prompt on the same 70B weights was competitive with our cascade (134/154, §6).

**Cost.** Rules only: about 0.5 CPU-hours for all 902,754 documents in OPD's export (measured on the held-out texts). Review mode: the pointer runs on the residue only (97 of 154 held-out documents, 63%), 3.5 calls and 5,905 billed prompt tokens per residue document (1,593 unique prefill tokens); projected to the whole export, about 3.4 billion billed prompt tokens, $336 at Public AI's list price ($3,357 at ten times the volume; `results/report/cost.json`).

![fig4](docs/figures/fig4_naive_contrast.png)
*Figure 4. Naive free generation vs the relinked source (2024.RRGR.91).*

## 4. Data

OPD bulk exports from `files.openparldata.ch/exports` (affairs, events, agendas, docs, texts, contributors; snapshot 6 Oct 2026, contributors 9 Oct; `data/census/meta.json`); the API (`/v1/`) is disallowed by robots.txt and was not used. Bern's open data `ogd.parl.apps.be.ch` (`dokument.csv`, `geschaeft.csv`, nightly); Fedlex SPARQL and the `www.fedlex.admin.ch` filestore; source PDFs fetched politely (one fixed user agent without personal data, ≥ 1.2 s per host, robots.txt honoured). The persons export carries 6 contact fields (e-mail, phone, address …); we counted the field names and never stored values. Nothing personal is committed; full document texts are never committed — `data/` holds ids, URLs, sha256 hashes, labels and quotes of ≤ 200 characters. Code Apache-2.0, report CC-BY-4.0, data CDLA-Permissive-2.0.

## 5. Results without a model: schema feasibility, census and repair

![fig2](docs/figures/fig2_matrix.png)
*Figure 2. Where each schema field comes from, per parliament (all 89 bodies in `results/census/matrix.csv`).*

**The verdict.** A field is *feasible* if OPD metadata carries it in ≥ 80% of eligible parliaments, *fundamentally different* if ≥ 20% of parliaments have no written source for it, else *partial*. By that rule, written down before computing (criteria and matrix were committed together): **4 feasible** (submission date, answer-event date — in 7 of 54 bodies mostly the submission date — harmonised procedural history, answer-link status), **13 partial**, **0 fundamentally different**.

| field family | where it lives today | tier |
|---|---|---|
| submission date, procedural history, answer-event date, answer-link status | OPD metadata in nearly every body | feasible |
| type, submitter, procedural state, Q/A pairing | metadata in most bodies, vocabulary mapping needed (type harmonised for 82.9% of affairs; state harmonised for 278) | partial |
| decision date and outcome, addressed body | metadata in some bodies, PDF in others | partial |
| government recommendation | metadata for 34.2% of motions/postulates; PDF-only in 56 bodies | partial (Apertus) |
| dispatch date, related affairs, co-signatories | in no export field; PDF only | partial |

**Where parliaments genuinely differ** (post hoc, descriptive): 20.7% of Question-time answers are oral only; Valais files 1,008 oral answers as a stub document rather than an event; in 7 of 54 bodies the "answer" event date is the submission date for most affairs, so the date exists but is not an answer date. On the held-out gold set (§6) OPD's answer-event date equals the date printed in the answer document for 37 documents and differs for 7 — each time a later registration/publication date or a filing date. A common schema therefore needs *date roles* (decided, dispatched, registered), not one "answer date". A rule-based inventory over 12 bodies found five recurring gaps a schema must add (person roles beyond author, comparison amounts, other polities' dates and laws, other affairs' dates, entry-into-force/deadlines); estimating the *size* of the missing schema with Chao2 failed both pre-registered checks (≈ 57.4 new accounts per body, no saturation) — a well-evidenced negative (`data/census/cited_evidence.json`).

**A cross-parliamentary question nobody could answer reliably:** across 54 parliaments, 82.3% of written answers have their text in OPD today, 85.0% after the measured repairs; the median government takes 68 days to answer (Question time: 5).

![fig3](docs/figures/fig3_be_before_after.png)
*Figure 3. Bern: answers attached to their affair today vs linkable within OPD (attached, agenda, parentless by canton uid).*

**Repair, verified.** Bern: the canton's nightly `dokument.csv` joined on the canton's document uid gives 2,459 relinks and 49 fetches, reproduced byte-for-byte; the other 179 of the 2,638 parentless answers belong to affairs whose answer text is already in OPD (155) or that have no written-answer event (24) (`results/repair/be_reconcile.json`); the spike's sample verifies 40/40 [91.2, 100] and OPD's answer event equals the decision date 39/39. A new pre-registered sample of 40 relinks (seed hashed before the draw) passes identity and heading 40/40 [91.2, 100] but the date check only 36/40 [76.9, 96]: three parser misses on 2020–21 headers and one real typo in the canton's PDF, which is what the check is for. Federal placeholders: Fedlex SPARQL plus the filestore recovers 19/20 by the pre-set rule, 40/50 [67, 88.8] on fresh documents; the 29,946-document backlog is about 17.5 h once. Scans: only 15/30 sampled "text-missing" answers are image-only (13 are Valais oral stubs); German+French+Italian OCR recovers 15/15 [79.6, 100], with 467 accented characters where English-only OCR keeps 133. 11,206 missing answers have no answer document in OPD at all and need per-body source adapters, which we did not build. Measured extraction accuracy exists only for the answer date, per language × level cell rather than per body (`results/census/matrix_accuracy.json`); the gold set has no federal documents. The nightly job computes in 260.5 s on cached inputs; from outside OPD it must re-download most export files each night (68/116 changed within three days; `docs/nightly.md`).

## 6. Evaluation (pre-registered, held-out)

**Design** (`eval/prereg/PREREG.md`, frozen with sha256 in `eval/prereg/LOCK`, commit `812030f` at 21:38 on 9 Oct, before any held-out label existed). 154 held-out documents in 7 cells (German/French/Italian × canton/commune, plus Ticino scans through OCR), 3 document types, length-matched classes, disjoint from every document the rules were developed on: 64 with an answer date, 90 gold-null. Arms on identical inputs: **rules** only; **pointer** (Apertus on every document); **cascade** (rules, then pointer on the residue — the converter as registered); **naive** free generation (plain and null-allowed prompts) on the same endpoint and weights; recommendation arms exploratory; 8B arms on the GGUF build. Metrics per cell with Wilson intervals: correct, correct null, false null, misattributed (a wrong date printed in the document), fabricated (a date printed nowhere), model share. Hypotheses: H1 null safety; H2 does the cascade beat the rules (exact McNemar, FR+IT+OCR; Branch A/B); H3 margin AUROC ≥ 0.80; H4 wrong values on unanchored FR/IT.

**Gold without human judgement** (`docs/gold_protocol.md`). Two blind Claude annotators (Opus, Sonnet) labelled every document, quotes checked verbatim by code; a third (Opus) decided the 41 disagreements. Agreement: Cohen's κ 0.95 on answer presence, 0.94 on the answer date (148/154 identical), 0.42 on the recommendation — almost entirely the `none` vs `not_applicable` boundary, which scoring treats alike. Disclosed weakness: the tie-breaker always saw A1's label as "X", not randomised. OPD event dates served as an external check only (37 agree, 7 differ as described in §5).

**Deviations** (`eval/prereg/DEVIATIONS.md`): D1 the frozen code prompts the Ticino scans in German (run as frozen, Italian re-run reported post hoc); D2 a faster GGUF scorer for the 8B arms, behind a parity gate; D3 the 8B θ is fitted without the 30 spike dev items whose texts are not in the repository, on the runner's own text extraction.

**Results** (frozen code, 70B weights, replayed offline from the hash cache, one served fingerprint; `results/eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json`; answer date, strict).

| arm | exact [95% CI] | correct date | correct null | false null | wrong date printed in the document | fabricated | values on the 90 answerless |
|---|---|---|---|---|---|---|---|
| **rules only (default mode)** | **135/154 [81.5, 92]** | 47 | 88 | 15 | 4 | 0 | 2 |
| pointer (Apertus on every document) | 130/154 [77.9, 89.3] | 46 | 84 | 8 | 16 | 0 | 6 |
| cascade (every review suggestion accepted) | 139/154 [84.6, 94] | 56 | 83 | 4 | 11 | 0 | 7 |
| naive, plain prompt | 98/154 [55.8, 70.8] | 47 | 51 | 9 | 23 | **24** | 39 |
| naive, null-allowed prompt | 134/154 [80.8, 91.4] | 47 | 87 | 9 | 11 | 0 | 3 |
<!-- SLOT: 8B rows -->

![fig5](docs/figures/fig5_scoreboard.png)
*Figure 5. Held-out scoreboard (left, frozen) and a post-hoc sweep of θ (right, labelled).*

**Pre-registered outcomes, as computed** (`results/eval/hypotheses__publicai_swiss-ai_apertus-v1.5-8b.json`).
**H1 null safety — FAIL.** The cascade puts a value on 7 of 90 answerless documents (upper Wilson bound 15.2% against the 10% target), 4 of them in the German communal cell (limit 1 per cell). The naive plain prompt does so on 39/90.
**H2 — Branch B.** On the French, Italian and OCR cells (n = 110) the cascade is right where the rules are wrong on 5 documents and the reverse on 1 (exact McNemar p = 0.22); over all cells 9 against 5 (p = 0.42). Apertus does not measurably add null-safety over the rules (values on answerless documents 7 vs 2; wrong printed dates 11 vs 4), so under the registered rule it is not kept in the unattended path: the default mode is rules only, and the pointer's residue answers (false nulls 15 → 4) are review suggestions.
**H3 margin separation — PASS.** The null margin separates answerless from answered documents with AUROC 0.969 on the length-matched set; the spike's 1.00 was confounded by length.
**H4 — triggered.** 3 of the 8 values Apertus decided on French or Italian documents are wrong, so we publish the θ curve below.

**What the comparison says.** On the same 70B weights, the naive null-allowed prompt reaches 134/154 and puts a value on only 3/90 answerless documents: competitive with the cascade on accuracy, and safer on nulls at the frozen θ. What the closed-set pointer adds is structural: it cannot fabricate (0 by construction, not by prompt), every value carries page and span, θ is tunable per build, and its margin separates answered from answerless documents (AUROC 0.969), though the frozen θ was too permissive (H1 failed). The naive plain prompt fabricates 24 dates.

**Post hoc (not pre-registered; `results/eval/posthoc/`).** *θ sweep:* the dev-fitted θ = 10.40 is too permissive on held-out; at θ between 0 and 2.5 the cascade would be exact on 142–143 with 3 values on answerless documents. θ = 0 is also what the earlier live spike observed, so this is the hypothesis for the next pre-registration, not a result. *Error anatomy:* every Apertus value on an answerless document is a real session or publication date of a parliament document (misattribution, not invention); two of the four rule errors are documents the annotators split on. *D1:* with the Italian prompt the pointer goes from 17/22 to 21/22 on the Ticino scans; the cascade stays at 21/22.

## 7. Limitations

The held-out set is 154 documents; per-cell intervals are wide. Only the answer date was evaluated (recommendation exploratory); the gold set has no federal documents, and the pointer sees at most 12,000 characters per document. Gold labels come from AI annotators with high but not perfect agreement; the protocol and every disagreement are public. The recommendation field has only 10 non-null gold values, so its arm is exploratory; at the declared θ = 0 the recommendation pointer puts a value on 28/144 documents without one (24/144 in the cascade), so it is not usable as is. The 70B results come from one provider build (one vLLM fingerprint), which may change without notice — θ must be refitted per build. 11,206 missing answers need source adapters we did not build; OCR was measured on 30 documents. The nightly cost from outside OPD is an estimate.

## 8. Reproducibility

`make run` (Docker, CPU, clean checkout) recomputes the census, replays the Bern join and triple check, converts sample documents with all validator checks, re-scores every evaluation file and recomputes every number here from `claims.tsv` (cited spike figures excepted, marked as cited); CI fails on any drift. Model outputs are replayed from a hash-keyed cache; with `LLM_BASE_URL` (vLLM-style) or `GGUF=1` a live slice runs. Seeds, snapshot dates and sha256 hashes are in `data/` and `eval/gold/SEEDS.md`.

## 9. Declarations

**Coding assistants.** Claude Code agents (Anthropic) wrote most of the code, the documentation and the gold labels, under the protocols above; numbers were checked by code (reproduction of every spike number, `claims.tsv`, LOCK hashes, verbatim-quote checks), not by reading. No human labelled or adjudicated any gold value — by design. Public AI (which may route outside Switzerland) was used for development and evaluation only. The default mode runs on CPU without any model and contacts only OPD, the canton's open data and Fedlex; review mode adds a local GGUF or whichever Apertus endpoint the operator chooses.

## 10. Next steps

Hand the relink and placeholder lists to OPD and run the nightly job beside their importer; build source adapters for the 11,206 answers that exist only at the source; add date roles and the five schema gaps to schema v0.2 with the eCH expert group; pre-register θ = 0 and extend the converter beyond the answer date.

## License and references

Report CC-BY-4.0 (`docs/LICENSE-report.txt`). OpenParlData exports (openparldata.ch); Kanton Bern Grosser Rat open data (ogd.parl.apps.be.ch); Fedlex (fedlex.admin.ch); Swiss AI Initiative, Apertus v1.5 model cards; Chao (1987); Popolo and Akoma Ntoso (`docs/mapping.md`).
