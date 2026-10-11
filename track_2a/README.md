# Gegenprobe: one schema and a converter for Swiss parliamentary answers

Track 2A · OpenParlData (OPD) · Team 444 · **Evidence site: https://gegenprobe.mi11ion.io** · technical report:
[`technical_report.md`](technical_report.md) (PDF `444_Report.pdf`)

**The answer.** A common schema for the business of Swiss parliaments works if it carries roles. "Answer date" is the
government's decision in some parliaments, the letter or registration date in others and the submission date in a few;
schema v0.1 gives every date its role, every value its source (page and character span, or the OPD record) and every
empty field a typed reason. Built on that schema, Gegenprobe measures where OPD's answers are, hands OPD checked repair
lists keyed on its own ids, and uses Apertus as a closed-set reader whose every value is printed in the document.

| | |
|---|---|
| **92.3%** | of interventions with a written government answer have answer text once the counted repairs are applied (82.3% today) |
| **9,720** | answers with a repair proposed to OPD, keyed on OPD ids, with a dry-run apply plan for Bern |
| **214** | review-queue answers recovered by Apertus as a closed-set verifier; on a blind pre-registered test, all 120/120 sampled are the government's answer |
| **24/29** | answer dates Apertus finds in parliaments nobody wrote rules for; the rules find 2/29 |

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections with dry-run SQL; per-parliament adapter lists;
  a vocabulary error list; a Fedlex resolver for the federal placeholder documents ([below](#ready-for-opd)).
- **Auditable by construction:** an Apertus value is a date or phrase printed in the document, located by code; the
  default runs no model at all.
- **Pre-registered:** eight tests, each frozen by hash before its labels; every number here is recomputed from its
  results file by `make claims`.

```bash
make run    # Docker, CPU, clean checkout: census, Bern join, converter samples, test replays, claims check, evidence site
```

![Where the registered gap is](docs/figures/fig1_funnel.png)

## Ready for OPD

Every list is keyed on OPD ids, is in `results/repair/` (vocabulary list: `results/census/`) and is a direct download on
the evidence site (box "For OPD's data team"). The apply plan is a dry run: we change nothing in OPD.

| list | rows | how each row is checked | applies |
|---|---|---|---|
| `repair_BE_relink.tsv` | 2,421 Bern answers already in OPD, unlinked | against OPD's own copy: affair number, answer heading, decision date = OPD's answer event | once OPD picks its hash rule for relinks |
| `repair_BE_fetch.tsv` | 48 answers to fetch from the canton | identity and heading, every row | now |
| `repair_BE_begin_date.tsv` | 554 load timestamps set to the affair's own submission event (173 to review) | the affair's "Eingereicht" event | now |
| `adapters/adapters_<BODY>.tsv` | 6,613 counted answers from 50 model-free source adapters, 2,177 of them a category on a document OPD already holds | affair number or title, answer formula, date check | per list |
| `adapters/p7/promoted_by_apertus.tsv` | 214 review rows verified by Apertus, in the adapter-list columns, tier `promoted_by_apertus`, `counted=false` | P7, pre-registered; a pre-sorted batch for OPD's review step | after review |
| `results/census/vocab_bugs.tsv` | 9 OPD harmonised labels wrong as published | e.g. type "Votaziun" (Romansh for a vote) on 9,887 affairs | OPD's vocabulary |
| `repair_CHE.tsv.gz` | 29,946 federal documents whose OPD text is Fedlex's "JavaScript required" page | resolver fetches each text through Fedlex; pre-set rule 40/50 on a sample | one-off run, about 17.5 h at the polite rate |

- **Bern.** OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet 96.1% are already in OPD and
  linkable without a model. OPD confirmed the linking bug and its root cause, and that the relink list is the
  workaround until its fix ships (correspondence, 10 Oct 2026).
- **The one open decision.** OPD's document `hash` is sha256(body_key + parent_type + url), so relinking changes each
  identifier unless OPD keeps the old one. `python -m gegenprobe.repair.apply_be --fetch --out DIR` writes the plan with
  before and after state and both hash values (`--hash keep`); `python -m gegenprobe.repair.acceptance` counts what OPD
  has attached and can gate a deployment.
- **Tag rows, guarded plan.** `python -m gegenprobe.repair.apply_tags --exports-dir DIR --out PLAN` turns the counted
  `tag_answer` and `extract_tag` rows into a before-state CSV and guarded `UPDATE` statements (id, affair,
  `category_harmonized IS NULL`, and the text hash or "still no text, same URL"); a dry run like `apply_be`.
- **Workbench schema.** `schema/gegenprobe_schema.py` is schema v0.1 as one file: pydantic only, no imports from
  `gegenprobe`, no I/O, its JSON Schemas tested equal to `results/schema/*.schema.json`.
- **Downloads.** Every list above is a direct download on the evidence site, the Fedlex list, `vocab_bugs.tsv` and the
  P7 tier included; a missing path returns HTTP 404.
- **What the 9,720 are:** 9,089 checked row by row, 592 agenda joins (OPD's own agenda link) and 39 Bern rows in
  review. A blind audit of 200 counted adapter rows judged 197/200 to be the executive's answer
  (`results/repair/adapters/audit3/`).
- **The nightly job** re-runs the census and the Bern route against OPD's exports. Two consecutive real nights ran in
  the recommended Docker setup: 86 min for the first, 6.6 min for the incremental second (12 bodies re-scanned). The
  first run exposed a ledger bug (night 2 reset night 1's per-row verdicts to `unchecked`); it is fixed, a row that is
  not re-checked now keeps its stored verdict, and two-night tests guard it
  (`results/monitor/two_nights_docker_38098822336/README.md`).

Detail, per list and per check: [`docs/operations.md`](docs/operations.md), [`docs/repair.md`](docs/repair.md),
[`docs/adapters.md`](docs/adapters.md), [`docs/runbook.md`](docs/runbook.md).

## Findings

### 1. The schema: shared concepts, explicit roles

Five fields are measured to need a role split, and schema v0.1 encodes each split explicitly:

- **Answer date.** OPD's "answer" event is the government's decision in some parliaments, the dispatch or registration
  date in others, and in 7 parliaments mostly the submission date. Median answer times differ by what the date is:
  112 days where it is the verified decision date (Bern, Ticino), 79 where it falls on a government's weekly sitting,
  39 where it is a diffuse, publication-like date (`results/census/answer_days_by_trust.json`). v0.1 carries a
  `DateRole` on every date and a date-trust tier per parliament.
- **Procedural history, type, procedural state, decision outcome.** One source label covers several roles: 35 event
  labels carry different date roles, 42 of 1,038 raw type labels map to different types, 32 state labels and 3 outcome
  labels are ambiguous (`results/census/comparability.json`).

The other 12 fields (submitter, submission date, addressed body, …) are defined once in v0.1; for the government
recommendation OPD's harmonised labels map unambiguously (0 of 183 raw labels map to two concepts). Mapping each
parliament's printed forms to these concepts is the next step for the eCH group (test plan:
[`docs/ech-onepager.md`](docs/ech-onepager.md) §6); P8 (`eval/prereg9/`) sets out that test for seven of the shared
fields, on fresh affairs from twelve parliaments, with its categories and decision rules fixed in advance.

| field | class | where it lives (metadata · mixed · PDF only · none) |
|---|---|---|
| answer date | role split, measured | **metadata**: 53 · 1 · 0 · 0 |
| procedural history | role split, measured | **metadata**: 78 · 9 · 1 · 1 |
| type | role split, measured | partly: 61 · 24 · 2 · 2 |
| procedural state | role split, measured | partly: 41 · 27 · 18 · 3 |
| decision outcome | role split, measured | partly: 7 · 31 · 33 · 6 |
| government recommendation | shared; OPD labels unambiguous | partly: 3 · 8 · 56 · 10 |
| submission date · answer-link status | shared | **metadata**: 89 · 0 · 0 · 0 and 54 · 0 · 0 · 0 |
| submitter · addressed body · decision date | shared | partly |
| Q/A pairing · language · usable text | shared | partly |
| co-signatories · dispatch date · related affairs | shared | PDF only, mostly |

Three further concepts are body-specific and get constructs of their own: oral answers in question time (a null
reason), executive business that answers no member's affair, and councils that publish only meeting documents
(16 bodies; v0.1 marks affairs rebuilt from minutes `virtual`, tested in P4). The full table and evidence:
[`docs/evaluation.md`](docs/evaluation.md#the-17-fields-in-detail).

### 2. The census: where the answers are

The census streams OPD's exports (snapshot 6 Oct 2026) once and gives each of the 91,268 interventions with a recorded
written government answer an answer-link status, typed by cause: attached, filed under an agenda item, stored without a
parent, scanned without text, or not in OPD at all.

- **92.3%** have answer text once the counted repairs are applied, up from 82.3% today.
- **At most 13,150** written answers lack answer text on their intervention (14.6% of the 89,846 answered in writing);
  the registered census counts 16,749 under its frozen lexicon, 1,422 of them answered orally in the sitting.
- **2,177** of the "missing" answers were in OPD all along, with text, under a heading the census lexicon does not list
  (Zürich city alone: 1,417, "Der Stadtrat beantwortet die Anfrage wie folgt"); the repair is a category on the
  document (`tag_answer`).
- **Bern's linking bug** accounts for most of the canton's gap: 520 of its 567 missing written answers from 2024–25
  are in OPD, unlinked.
- **Coverage gaps are named as such:** 31 parliaments where OPD holds interventions but almost no written answers are
  shown as an OPD coverage status, not as unanswered questions.

A research dataset ships with it: `results/census/interventions.tsv.gz`, one row per intervention, with dates, where
the answer text is, the OPD and parliament pages and the date-trust tier (CDLA-Permissive-2.0).

### 3. What Apertus adds

The default (`rules_only`) runs no model. Where Apertus runs, it answers a closed question or picks one of the dates
or phrases printed in the document, and code locates the page and span.

- **It picks the right printed date where the rules can't (P7).** On the adapters' review queue Apertus answers two
  closed questions: is this the executive's answer to this intervention, and which printed date is the answer date.
  With its yes/no gate but the adapters' date rule picking among the printed dates, 74.9% of promotions carry a
  rule-passing answer date; with Apertus choosing the date, 95.8% (+20.9 points [5.2, 33.1], post-hoc ablation; the
  yes/no gate itself adds 1.1 points). It recovers 214 of 917 review rows, and on a fresh blind test 120/120 sampled
  promotions are the government's answer (pre-registered H1; 48/48 without its largest parliament, Frauenfeld).
- **New layouts (P2).** In 15 parliaments nobody wrote rules for, it finds 24/29 answer dates; the rules find 2/29.
- **People (P5).** Pointing at printed names doubles submitter extraction over the rules, 12/40 → 24/40.
- **Provenance guaranteed.** No closed-set arm returned a date printed nowhere (0 invented dates on P1, P2 and P6),
  and on the 53 P2/P6 documents with no answer at all the 70B closed-set arms dated 0/53 (post-hoc split).
  The closed set matches the accuracy of a well-instructed free prompt and adds what a free prompt cannot guarantee:
  a page and span for every value, and a margin that orders the review queue.
- **Suggestions go to a reviewer; rules run unattended.** By design, Apertus values arrive with `needs_review: true`
  for OPD's existing manual-review step.
- **Sovereign option.** The Apertus 8B runs locally on CPU (a community 4-bit build). On the unseen parliaments of P2
  it reproduces the registered result over the rules (13 vs 0 documents, 52 reachable documents), and its two-step
  reader cuts dates on answerless documents from 18/34 to 5/34 (P6). Both runs are exploratory.

## How it works

```
OPD exports ──► census (answer-link status per affair) ──► repair routes + 50 source adapters ──► lists keyed on OPD ids
answer PDFs ──► OPD metadata ──► frozen DE/FR/IT rules ──► Apertus closed-set pointer (review mode, residue only)
                                         └──► schema v0.1 record: value + role + page/span, or a typed null
```

- **Converter** (`src/gegenprobe/convert/`, `qa/`, `affair/`): `python -m gegenprobe convert <pdf-or-url> --body SG`
  returns JSON in which every value has its page, character span and rule (or OPD record), and every gap a typed null.
  A parliament with no rules gets `no_rules_for_body` and `needs_review: true`; a settings file adds its own anchors
  without forking the rules. Guide: [`docs/convert-your-own.md`](docs/convert-your-own.md).
- **Schema** (`src/gegenprobe/schema/schema_v0_1.py`, normative Pydantic; JSON Schema in `results/schema/`): date roles,
  typed nulls, `QAItem` (question *n* paired with the answer to question *n*). Mappings to Popolo, Akoma Ntoso,
  Parla-CLARIN and OParl: [`docs/mapping.md`](docs/mapping.md).
- **Apertus pointer**: the model scores `null` and every printed date (or label, or name) by log-probability; it is null
  if the null margin exceeds θ, fitted per build on development documents and frozen.

## Evaluation summary

Eight tests, each with code, prompts and θ frozen by sha256 before any label was committed (`eval/prereg*/`). Gold
labels come from blind agent annotators by design (below). Full tables, deviations and statistics:
[`docs/evaluation.md`](docs/evaluation.md).

| test | n | what it tests | registered result | key number |
|---|---|---|---|---|
| P1 | 154 documents, parliaments with rules | answer date: rules vs Apertus | partial: H3 held; H1 null safety failed (7/90); H2 Branch B | rules alone 135/154, so the default runs no model |
| P2 | 62 documents, 15 parliaments without rules | rules transfer; pointer vs rules | 3 of 4 held; H3 null safety failed (4/33) | pointer 24/29 answer dates, rules 2/29 |
| P3 | 29 whole affairs, 10 parliaments | 7 fields: metadata, rules, Apertus | partial: no field unattended; Apertus recall held, precision below | answer date 22/27 → 27/27 with Apertus |
| P3b | 36 fresh affairs, 9 parliaments | replication of P3 | held: replicated (S1, S2) | type 35/36 unattended |
| P4 | 120 agenda items, 6 sittings | affairs rebuilt from minutes | partial: H2, H4 held; H1, H3 failed | precision 99/99, recall 99/120 |
| P5 | 40 fresh affairs, 10 parliaments | Q/A pairs, people, recommendation | partial tier (H1); H2, H5 held; H3 no gain | submitter 12/40 → 24/40 |
| P6 | 68 fresh documents, 8 parliaments | answer-date reader v2 vs free prompting | no hypothesis held | free prompt 62/68, v2 59/68 |
| P7 | 478 review rows, 190 blind packets | Apertus as verifier of the review queue | H1 holds (120/120); H4 supported; H3 not supported | 214 of 917 review rows recovered |

- **Unattended** (95% lower bound ≥ 0.80): the rules' answer date where rules exist (P1), the type of whole affairs
  (P3b), and in P5 question detection, the reasoning span and co-signatory precision.
- **Gold labels, no human labelling by design.** Two blind agent annotators (Claude Opus and Sonnet) label each
  document, a third breaks ties, quotes are verified by code, and every labelling session is timed against the lock
  and label commits. Another vendor's model (`Qwen-SEA-LION-v4-32B`, AI Singapore) relabelled
  P1, P2, P6 and P7 blind: κ 0.80–0.93 on P1 and P2, and no registered decision changes. Non-LLM sources agree: OPD's
  written-answer events match 37/44 checkable P1 dates, and publishers' titles that name the decision date 20/20.
- **Statistics.** Holm over all 20 registered confirmatory tests of P1–P7: the 9 that held as registered all survive
  (`results/eval/posthoc_r8_multiplicity.json`); documents are also resampled by whole parliament.

![Scoreboards](docs/figures/fig5_scoreboard.png)

## Operations

- **`make run`** (Docker, CPU, clean checkout) recomputes the census and asserts it equal to `results/census/`,
  replays the Bern join, runs sample documents through the converter and validator, re-scores the pre-registered tests
  from committed predictions and labels and re-runs their hypothesis scripts, P7 included (all eight LOCK files
  verified; P7 byte-identical from the committed `data/p7/` copies), re-derives the P1 rules arm from the source PDFs,
  and recomputes every number in `claims.tsv`, failing if a document prints anything else. Detail:
  [`docs/operations.md`](docs/operations.md).
- **Sovereignty.** Runtime external services: none by default (OPD's exports and the parliaments' own sites, fetched
  politely, at least 1.2 s between requests to one host). An optional review-model endpoint is chosen by the operator:
  Public AI, or the local 8B on CPU, in which case no document text leaves the machine. The evidence site is static
  and makes no third-party request. Every request's User-Agent must name a contact URL; one carrying an e-mail address
  is refused before any request.
- **Hardened.** Container and nightly unit run as a non-root uid, read-only, with all capabilities dropped; PDFs are
  capped in size and time; CI gates the systemd units' security exposure and pins every Action by SHA.
- **Cost** (one core, no GPU). Fetching and checking takes about 2.1 s per document; the rules process 480 documents
  per second, about 0.5 CPU-hours for all 902,754 documents in OPD's export. Review mode costs USD 0.59 per 1,000
  residue documents on the 70B; the 8B takes 180 s per document on 4 vCPUs.
- **robots.txt.** We found, audited and fixed our own robots.txt bug; every fetch path now fails closed and requests
  OPD's own copy where one exists. Full disclosure: [`docs/incidents.md`](docs/incidents.md).

**Which model.** Apertus numbers not marked 8B come from the 70B weights that Public AI serves under the name
`swiss-ai/apertus-v1.5-8b` (inferred from the served fingerprint; the response's `model` field is checked on every
call). The 8B is a community 4-bit GGUF of `swiss-ai/Apertus-v1.5-8B`, sha256-pinned, run in-process on CPU. Review mode
stops on a served build its θ was not fitted on.

## Limitations and next steps

- **Schema.** The five role splits are measured; the field-by-field meaning test for the other twelve is the next step
  (P8, `eval/prereg9/`), with the eCH group ([`docs/ech-onepager.md`](docs/ech-onepager.md) §6). Tables, annexes and
  images inside answers are the next extraction target.
- **At OPD.** The lists are ready to apply as dry-run plans keyed on OPD ids; the relinks wait on one decision, OPD's
  hash rule. 5,077 answers remain to be found, 943 of them already waiting for a person.
- **Apertus as a date reader** is used with a reviewer, as the registered null-safety tests (P1, P2, P6) indicate; P6
  confirmed that the shipped reader v1 stays.
- **Gold.** No human labelling, by design; labels are cross-checked by another vendor's model and by non-LLM sources.
  A spot check by OPD or the parliaments is the natural next layer.

## What is in the repository

| Deliverable (challenge) | Where |
|---|---|
| Representation model: versioned schema + controlled vocabularies | `src/gegenprobe/schema/schema_v0_1.py`, `data/schema/*.json`, `results/schema/*.schema.json`, `docs/schema.md`, `docs/mapping.md`, `docs/ech-onepager.md` |
| Converter: prompts + code, provenance per value | `src/gegenprobe/convert/`, prompts `src/prompts/{de,fr,it}/`, `docs/converter.md`, `docs/convert-your-own.md` |
| Whole affairs, Q/A pairs, people, recommendation, virtual affairs | `src/gegenprobe/affair/`, `src/gegenprobe/qa/`, `src/gegenprobe/virtual/`, `docs/affair.md`, `docs/qa.md`, `docs/virtual-affairs.md` |
| Validator | `src/gegenprobe/validate/` (schema, span re-check, typed-null consistency) |
| Evidence: eight pre-registrations | `eval/prereg*/` (each with `DEVIATIONS*.md`), gold sets `data/gold*/`, `docs/gold_protocol.md`, `docs/evaluation.md` |
| Census, feasibility matrix, comparability, research dataset | `src/gegenprobe/census/`, `results/census/`, `docs/census.md` |
| Repair lists, apply plan, source adapters, vocabulary errors | `results/repair/`, `results/census/vocab_bugs.tsv`, `docs/repair.md`, `docs/adapters.md` |
| Nightly job and operations | `src/gegenprobe/monitor/`, `deploy/nightly/`, `docs/nightly.md`, `docs/runbook.md`, `docs/operations.md` |

**Coding assistants.** Claude Code agents (Anthropic) wrote most code, documentation and the gold labels. Correctness
rests on code-level checks: `claims.tsv`, the pre-registration locks, regression fixtures, verbatim-quote checks and
re-derivation from source PDFs.

## Licences

Code: Apache-2.0 (`../LICENSE`). Report: CC-BY-4.0 (`docs/LICENSE-report.txt`). Data in `data/` and generated
results in `results/`: CDLA-Permissive-2.0 (`data/LICENSE`, `results/LICENSE`): identifiers, URLs, hashes, counts,
labels and short quotations only, with no full document texts and no personal contact data. Derived from
OpenParlData.ch, which publishes its data under CC BY 4.0; attribution: "Source: OpenParlData.ch".
