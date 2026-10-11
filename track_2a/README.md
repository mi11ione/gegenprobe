# Gegenprobe: one schema and a converter for Swiss parliamentary answers

Track 2A · OpenParlData (OPD) · Team 444 · **Evidence site: https://gegenprobe.mi11ion.io** · technical report:
[`technical_report.md`](technical_report.md) (PDF `444_Report.pdf`)

**A common schema for Swiss parliamentary business works if its fields carry roles, and the proposed repairs, keyed on
OpenParlData (OPD) ids, would raise the share of interventions with a recorded government answer that have answer text
from 81.6% to 92.3%.** Of the 17 fields, 10 need roles (8 robust, 2 fragile), 1 is body-specific,
and 6 are defined once in v0.1 (their meaning is the next test) ([the 17 fields](#1-the-schema-shared-concepts-explicit-roles)).
"Answer date" is the government's decision in some parliaments, the letter or registration date in others and the
submission date in a few; a pre-registered meaning test (P8) finds roles in authorship, signatories, the instrument
behind a harmonised type and the date a submission carries. Schema v0.1 gives every value its role and source (page and
character span, or the OPD record) and every empty field a typed reason; schema v0.2 adds P8's roles and validates
171 affairs, 105 of them the converter's own records. Apertus is a closed-set reader: every value it extracts is
printed in the document.

> **For OPD.** The repair lists are dry-run plans keyed on your ids; the one open decision is your hash rule for
> relinked documents (keep the old identifier or issue a new one). Files: [`docs/ech-onepager.md`](docs/ech-onepager.md)
> (per-field recommendation for the eCH group), [`schema/gegenprobe_schema.py`](schema/gegenprobe_schema.py) (v0.1, one
> file, pydantic only) with [`schema/gegenprobe_schema_v0_2.py`](schema/gegenprobe_schema_v0_2.py) (v0.2: P8's roles),
> [`results/repair/apply_be/apply_BE_plan.sql.txt`](results/repair/apply_be/apply_BE_plan.sql.txt) (Bern plan, dry run:
> rolls back unless every statement changes exactly one row). Spot-check kit:
> [`results/opd_spotcheck/`](results/opd_spotcheck/), 30 gold labels with link, page and quote that anyone, OPD
> included, can verify in about an hour (`python -m eval.spotcheck score`).

| | |
|---|---|
| **92.3%** | of interventions with a recorded government answer would have answer text once the proposed repairs are applied, up from 81.6% attached today ([staged](#ready-for-opd)) |
| **9,720** | answers with a repair proposed to OPD, keyed on OPD ids, with a self-checking dry-run SQL plan for Bern |
| **5 of 7** | fields v0.1 defines once depart from one meaning under both checks (P8: 66 affairs, 11 parliaments); schema v0.2 carries their roles |
| **+22.7** | points for Apertus as review-queue verifier: the right answer with a checkable date, over a no-model date match (P7-H4, weighted as registered; unweighted +7.5); 120/120 promotions are answers (H1) |
| **24/29** | answer dates Apertus finds in 15 parliaments nobody wrote rules for (P2), where the rules find 2/29; exact on 53/62 documents, against 44/62 for the best no-model baseline (post hoc) |

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections with dry-run SQL; per-parliament adapter lists;
  a vocabulary error list; a Fedlex resolver for the federal placeholder documents ([below](#ready-for-opd)).
- **Auditable by construction:** every value Apertus extracts is a date or phrase printed in the document, located by
  code; its yes/no answers (P7) and category labels are judgements a person reviews. The default runs no model.
- **Sovereign and cheap to run:** the default runs no model and only reads public sources (OPD's exports, Bern's open
  data, Fedlex, the parliaments' sites); Apertus runs through the Public AI gateway or locally (8B GGUF, CPU). A first
  network night took 86 min on a GitHub runner, the next 6.6 min; at ten times OPD's volume the rules need about 5
  CPU-hours ([Operations](#operations)).
- **Pre-registered:** nine tests, each frozen by hash before its labels (P1's hypothesis script followed its labels and
  its rules entered with its sample, both logged: D4, D12). `make claims` recomputes every claimed number from its
  results file and checks that it is printed where listed; in the headline blocks (this one, the report's summary,
  the form notes) and the README's results tables, every number must be bound to its claim by an anchor phrase at its
  position.

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
| `adapters/adapters_<BODY>.tsv` | 6,613 counted answers from 50 model-free source adapters, 27 with counted repairs; 2,177 of them a category on a document OPD already holds | affair number or title, answer formula, date check | per list |
| `adapters/p7/promoted_by_apertus.tsv` | 214 review rows verified by Apertus, in the adapter-list columns, tier `promoted_by_apertus`, `counted=false` | P7, pre-registered; a pre-sorted batch for OPD's review step | after review |
| `results/census/vocab_bugs.tsv` | 9 OPD harmonised labels wrong as published | e.g. type "Votaziun" (Romansh for a vote) on 9,887 affairs | OPD's vocabulary |
| `repair_CHE.tsv.gz` | 29,946 federal documents whose OPD text is Fedlex's "JavaScript required" page | resolver fetches each text through Fedlex; pre-set rule 40/50 on a sample | one-off run, about 17.5 h at the polite rate |

- **Bern.** OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet 96.1% are already in OPD and
  linkable without a model: 2,459 relink candidates = 2,421 ready (every check passes) + 38 for review, and 49 fetch
  rows = 48 ready + 1 for review. OPD confirmed the linking bug and its root cause, and that the relink list is the
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
- **Downloads.** Every list above is a direct download on the evidence site, the Fedlex list, `vocab_bugs.tsv`, the
  P7 tier and `gegenprobe_schema.py` included; a missing path returns HTTP 404.
- **What the 9,720 are:** 9,089 checked row by row, 592 agenda joins (OPD's own agenda link, not sample-checked) and
  39 Bern rows in review. In a blind audit of 200 counted adapter rows, AI annotators judged 197/200 to be the executive's answer, with
  the date wrong or unsupported in 15; a second auditor from another vendor (Qwen-SEA-LION) accepted 200/200, and the
  two agree on 252 of 260 packets, decoys included (`results/repair/adapters/audit3/`). The 554 `begin_date`
  corrections fix a different field and are not among the 9,720.
- **What each repair still needs.** 3,621 need neither a decision nor a fetch (agenda joins, category tags, verified
  text of OPD's own copies): with them 85.6% of the 91,268 have answer text. 2,459 Bern answers OPD holds without a
  parent (2,421 relinks, 38 in review) follow its hash decision: 88.3%. 3,640 answers checked at the parliaments are
  fetched into OPD: 92.3%.
- **The nightly job** re-runs the census and the Bern route against OPD's exports. Two consecutive real nights ran in
  the recommended Docker setup on a GitHub runner: 86 min for the first, 6.6 min for the incremental second (12
  bodies re-scanned). Night 2 exposed a ledger bug (it reset night 1's per-row verdicts to `unchecked`); it is fixed,
  a row that is not re-checked now keeps its stored verdict, two-night tests guard it, and the real two-night re-run of
  the fixed code starts with OPD's next nightly export, 12 Oct 00:30 UTC (first run: `results/monitor/two_nights_docker_38098822336/README.md`).

Detail, per list and per check: [`docs/operations.md`](docs/operations.md), [`docs/repair.md`](docs/repair.md),
[`docs/adapters.md`](docs/adapters.md), [`docs/runbook.md`](docs/runbook.md).

## Findings

### 1. The schema: shared concepts, explicit roles

A common schema works if it carries roles, not only for dates. Meaning is now measured for 11 of the 17 fields: 5
from OPD's own labels and 7 from the documents in P8 (type both ways). v0.1 encodes the five label splits; v0.2
(`schema/gegenprobe_schema_v0_2.py`) adds P8's roles: author roles (sole author, joint author, first signatory,
co-signatory, supporter, group, committee, spokesperson), the instrument's function next to the harmonised type, the
text's language apart from the source's tag, submission-date roles (signed, lodged, received, announced, later step)
and the recommendation's stage (on adoption, on fulfilment). 171 affairs validate as v0.2 records: the converter's own
records for P3 (29), P3b (36) and P5 (40), and the 66 P8 affairs; the v0.1 samples upgrade losslessly
(`results/schema/v0_2/validation_all.json`, `make schema-v02`). Three converter-made v0.2 records (Bern in German,
Valais in French, Graubünden in Italian, with per-question Q/A items) are the samples: `results/schema/v0_2/samples/`.

- **Answer date.** OPD's "answer" event is the government's decision in some parliaments, the dispatch or registration
  date in others, and in 7 parliaments mostly the submission date. Median answer times, described per group of
  parliaments (different parliaments in each group, so not an effect of the date's role alone): 112 days where the date
  is the verified decision date (Bern, Ticino), 79 where it falls on a government's weekly sitting, 39 where it is a
  diffuse, publication-like date (`results/census/answer_days_by_trust.json`). v0.1 carries a `DateRole` on every date
  and a date-trust tier per parliament.
- **Procedural history, type, procedural state, decision outcome.** One source label covers several roles: 35 event
  labels carry different date roles, 42 of 1,038 raw type labels map to different types, 32 state labels and 3 outcome
  labels are ambiguous (`results/census/comparability.json`).
- **Authorship, signatories, instrument, language (P8).** On 66 fresh affairs from 11 parliaments, labelled blind
  against categories fixed in advance (`eval/prereg9/`), none of the seven fields v0.1 defines once passes the
  registered test of meaning the same thing everywhere. The submitter is a sole author or designated first signatory
  in Bern city, Vaud and Lausanne, one of several joint authors with none designated first in Zürich city, Thurgau,
  Fribourg and Vernier, and a parliamentary group in Valais: 35/65 affairs carry the one meaning v0.1 gives it. Bern
  city prints several first signatories, so OPD's co-signatory list includes authors of record (co-signatories in
  their v0.1 meaning: 10/41). Two Bellinzona "Motions" propose a decision the council takes itself; two Valais
  "Postulate" mandate the executive to act. In Fribourg, OPD's language tag names the other official language in 2
  of 6 affairs.
- **Submission date (P8).** In 9 of 11 parliaments OPD's date is the printed lodging date (one exception allowed). In Vernier (0/5) and
  Lausanne (2/5) it is mostly printed nowhere in the documents, 2 to 28 days after the lodging date they print: a
  standard records which event the date is. These five verdicts hold on agreed labels only and on another vendor's
  labels (details and the two fragile splits: [`docs/evaluation.md`](docs/evaluation.md#p8-what-the-shared-fields-mean)).

| field | class | meaning tested | where it lives (metadata · mixed · PDF only · none) |
|---|---|---|---|
| answer date | role split | OPD labels | **metadata**: 53 · 1 · 0 · 0 |
| procedural history | role split | OPD labels | **metadata**: 78 · 9 · 1 · 1 |
| type | role split | OPD labels; P8: the instrument behind it | partly: 61 · 24 · 2 · 2 |
| procedural state | role split | OPD labels | partly: 41 · 27 · 18 · 3 |
| decision outcome | role split | OPD labels | partly: 7 · 31 · 33 · 6 |
| submitter | role split | P8: sole, joint or group author | partly: 23 · 61 · 5 · 0 |
| co-signatories | role split | P8: co-signers or authors of record | PDF only: 0 · 2 · 72 · 12 |
| language | role split | P8: tag names the other language | partly: 14 · 53 · 20 · 2 |
| addressed body | role split, fragile | P8: Bellinzona, the council itself | partly: 12 · 10 · 54 · 10 |
| government recommendation | role split, fragile | P8: Vernier, write-off reports | partly: 3 · 8 · 56 · 10 |
| submission date | body-specific in 2 | P8: Vernier, Lausanne | **metadata**: 89 · 0 · 0 · 0 |
| answer-link status | shared by definition | next | **metadata**: 54 · 0 · 0 · 0 |
| decision date · Q/A pairing · usable text | shared by definition | next | partly |
| dispatch date · related affairs | shared by definition | next | PDF only |

Three further concepts are body-specific and get constructs of their own: oral answers in question time (a null
reason), executive business that answers no member's affair, and councils that publish only meeting documents
(16 bodies; v0.1 marks affairs rebuilt from minutes `virtual`, tested in P4). The full table and evidence:
[`docs/evaluation.md`](docs/evaluation.md#the-17-fields-in-detail).

### 2. The census: where the answers are

The census streams OPD's exports (snapshot 6 Oct 2026) once and gives each of the 91,268 interventions with a recorded
government answer an answer-link status, typed by cause: attached, filed under an agenda item, stored without a
parent, scanned without text, or not in OPD at all.

- **92.3%** would have answer text once the proposed repairs are applied. Today 81.6% have it attached to the intervention (the
  registered count), 82.3% counting the 592 answers OPD files under an agenda item of the same affair; those 592 are
  also among the 9,720, so the repairs add 9,128 beyond the 82.3%.
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

- **A verifier of the review queue (P7, pre-registered).** On the adapters' review queue Apertus answers two closed
  questions: is this the executive's answer to this intervention, and which printed date is the answer date. The
  registered result only Apertus produces is the right answer with the right kind of date: 95.8% of its promotions are
  answers whose printed answer date passes the date check, +22.7 points over a no-model date match (H4, [10.2, 34.3],
  weighted, as registered; unweighted +7.5 [3.4, 12.2]). Blind AI annotators judged 120/120 sampled promotions the
  government's answer (H1, Wilson 95% [96.9, 100]; 48/48 without its largest parliament, Frauenfeld). Post hoc, the
  date Apertus picks is the gold answer date in 113/120 promotions, against 127/157 for a no-model rule that takes the
  first printed date passing the date check. The tier it fills holds 214 of 917 review rows. Further post-hoc
  ablations are in [`docs/evaluation.md`](docs/evaluation.md#protocol-gold-labels-and-every-test).
- **New layouts (P2).** In 15 parliaments nobody wrote rules for, it finds 24/29 answer dates, every value a printed
  date, where the rules, written for other layouts, find 2/29. On all 62 documents it is exact on 53/62, against 44/62
  for the best no-model baseline, the latest date on documents OPD types as answers (post hoc). It puts a date on 4 of
  the 33 answerless documents, where the latest printed date (22/29 found) dates 31. A free prompt finds 22/29 as
  registered, 24/29 (null allowed) and 25/29 (plain) once its answers are re-parsed (D2-4).
- **People (P5).** Both model routes beat the rules on submitters: pointing at printed names doubles extraction over
  the rules (12/40 → 24/40), and free generation finds 34/40.
- **Provenance by construction.** No closed-set arm returned a date printed nowhere (P1, P2, P6). On the 53 P2/P6
  documents with no answer at all, the P2 pointer and P6's reader v2 dated none (post hoc; the shipped reader v1
  dated 1 of P6's 28). The closed set reaches near free-prompt accuracy (P2 53 vs 54/62; P6 59 vs 62/68); a
  printed-date filter on a free prompt gives the same no-invention guarantee, the closed set gives it by construction,
  with a page and span for every value and a margin that orders the review queue.
- **Suggestions go to a reviewer; rules run unattended.** By design, Apertus values arrive with `needs_review: true`
  for OPD's existing manual-review step.
- **Sovereign option.** The Apertus 8B runs locally on CPU (a community 4-bit build, sha256-pinned; 9.3 GB peak
  memory, 180 s per document on 4 vCPUs). On the unseen parliaments of P2 it reproduces the registered result over the
  rules (right on 13 documents where the rules are wrong, the reverse on 0; 52 reachable documents), and its two-step
  reader cuts dates on answerless documents from 18/34 to 5/34 (P6); both runs are exploratory. On P1 its cascade dates
  25 of the 90 answerless documents, the 70B's 7: on the local route, as on the gateway, every model value goes to a
  reviewer.

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
  typed nulls, `QAItem` (question *n* paired with the answer to question *n*). v0.2 (`schema/gegenprobe_schema_v0_2.py`,
  JSON Schema in `results/schema/v0_2/`) extends it with P8's roles; the v0.1 samples upgrade to it losslessly. Mappings to Popolo, Akoma Ntoso,
  Parla-CLARIN and OParl: [`docs/mapping.md`](docs/mapping.md).
- **Apertus pointer**: the model scores `null` and every printed date (or label, or name) by log-probability; it is null
  if the null margin exceeds θ, fitted per build on development documents and frozen.

## Evaluation summary

Nine tests, each with code, prompts and θ frozen by sha256 before any label was committed (`eval/prereg*/`). Gold
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
| P7 | 478 review rows, 190 blind packets | Apertus as verifier of the review queue | H1 holds (120/120); H4 supported; H3 not supported | 214 of 917 review rows promoted |
| P8 | 66 fresh affairs, 11 parliaments | meaning of 7 fields v0.1 defines once | none uniform: 6 role split, 1 body-specific; 5 robust under both checks | meaning measured for 11 of 17 fields |

- **Above the registered 0.80 bar** (95% lower bound): on P1 the rules are exact on 135/154 documents [81.5, 92],
  finding 47 of 64 answer dates and dating 2 of the 90 answerless documents (latest printed date on answer-typed
  documents: 131/154); the type of whole affairs (P3b, 35/36); in P5 question detection, the reasoning span and
  co-signatory precision.
- **Gold labels, no human labelling by design.** Two blind agent annotators (Claude Opus and Sonnet) label each
  document, a third breaks ties, quotes are verified by code, and every labelling session of P1–P7 is timed against
  the lock and label commits. Another vendor's model (`Qwen-SEA-LION-v4-32B`, AI Singapore) relabelled
  P1, P2, P6 and P7 blind: κ 0.80–0.93 on P1 and P2, and no registered decision changes. On P8 its labels give the
  same verdict for the five robust fields; its low κ on the submitter (0.24) is mostly an interpretive difference: it
  calls the first of several equal authors the "first signatory". Non-LLM sources agree: OPD's written-answer events
  match 37/44 checkable P1 dates, and publishers' titles that name the decision date 20/20.
- **Statistics.** Holm over all 20 registered confirmatory tests of P1–P7: the 9 that held as registered all survive
  (`results/eval/posthoc_r8_multiplicity.json`); documents are also resampled by whole parliament.

![Scoreboards](docs/figures/fig5_scoreboard.png)

## Operations

Operator sheet (hardware, external hosts, exit codes and alerts, licences, on one screen):
[`docs/runbook.md`](docs/runbook.md#operator-sheet).

- **`make run`** (Docker, CPU, clean checkout) recomputes the census and asserts it equal to `results/census/`,
  replays the Bern join, runs sample documents through the converter and validator, re-scores P1–P8 from
  committed predictions and labels and re-runs their hypothesis scripts (nine LOCK files verified; P7 and P8
  byte-identical from the committed `data/p7/` and `data/p8/` copies, the P7 post-hoc files included), re-derives the P1 rules arm from the source PDFs,
  and recomputes every number in `claims.tsv` from its results file. It fails if a document a claim lists does not
  print the claimed value, or if a number in the strict zones (this README's top and its results tables, the report's
  summary, the form notes; `claims_strict.json`) is not bound to a claim by an anchor: a phrase recorded for that
  claim that contains the number at that position (`claims_anchor.json`). Detail:
  [`docs/operations.md`](docs/operations.md).
- **Sovereignty.** The default nightly job uses no third-party processor. At runtime Gegenprobe makes read-only
  requests to public sources, at least 1.2 s apart per host; an optional review model runs where the operator chooses
  (our evaluation used Public AI, which may route outside Switzerland; with the local 8B no text leaves the machine):

  | runtime host | what is sent | needed for |
  |---|---|---|
  | files.openparldata.ch (or none, with `GP_EXPORTS_DIR`) | GET only | census, nightly job |
  | ogd.parl.apps.be.ch, rrgr-service.apps.be.ch (canton Bern) | GET; an affair number | Bern repair |
  | fedlex.data.admin.ch (SPARQL), www.fedlex.admin.ch | a citation such as "BBl 2014 9657" | federal placeholder repair |
  | document hosts listed in OPD; the parliaments' sites the source adapters read (one canary per source each network night, on by default) | GET of a public page or PDF and its robots.txt | conversion, adapter lists, canaries |
  | huggingface.co, only with `GP_GGUF=1` | GET of the pinned GGUF, once | local 8B |
  | the LLM endpoint the operator sets (`LLM_BASE_URL`), or none | text of public parliamentary documents | review mode |
  | the webhook or SMTP relay the operator sets (`GP_ALERT_*`), or none | the night's alerts | nightly alerts |

  With the local 8B no document text leaves the machine. The evidence site is static and makes no third-party
  request. Every request carries `GP_USER_AGENT`: the default names no contact and a network night warns until the
  operator sets one with a contact URL; a value carrying an e-mail address is refused before any request.
- **Hardened.** The container runs as a non-root uid, read-only, with all capabilities dropped; PDFs are capped in
  size and time; CI gates the systemd units' security exposure and pins every Action by SHA.
- **Cost** (one core, no GPU). Outside OPD, fetching and checking takes about 2.1 s per document, about 527 hours for
  all 902,754 documents in OPD's export; inside OPD the exports are read in place (`GP_EXPORTS_DIR`, no transfer). The
  rules process 480 documents per second, about 0.5 CPU-hours for all 902,754 documents. Review mode costs USD 0.59 per 1,000
  residue documents on the 70B; the 8B takes 180 s per document on 4 vCPUs. For the whole export (about 569k residue
  documents, an upper bound) review mode would cost about USD 336 on the 70B or 28,400 machine-hours on the 8B. **At
  ten times OPD's volume** the rules need about 5 CPU-hours and review mode on the 70B about USD 3,357; fetching the
  documents dominates, not the rules. **Review load per night** (estimate): OPD recorded about 18.2 answers a day in
  2025 (28.6 in its busiest month); at the held-out residue share (0.63) that is 11.5 documents a night, about 34
  minutes on the 8B (54 in the busiest month).
- **robots.txt.** We found, audited and fixed our own robots.txt bug; every fetch path now fails closed and requests
  OPD's own copy where one exists. Full disclosure: [`docs/incidents.md`](docs/incidents.md).

**Which model.** Apertus numbers not marked 8B come from the 70B weights that Public AI serves under the name
`swiss-ai/apertus-v1.5-8b` (inferred from the served fingerprint; the response's `model` field is checked on every
call). The 8B is a community 4-bit GGUF of `swiss-ai/Apertus-v1.5-8B`, sha256-pinned, run in-process on CPU. Review mode
stops on a served build its θ was not fitted on.

## Next steps

- **Schema with the eCH group.** Meaning is measured for 11 of 17 fields and v0.2 ships P8's roles; next come the
  other six (decision and dispatch dates, Q/A pairing, related affairs, usable text, answer-link status)
  ([`docs/ech-onepager.md`](docs/ech-onepager.md)), then tables, annexes and images inside answers.
- **At OPD.** The lists are ready as dry-run plans keyed on OPD ids; the relinks take one decision, OPD's hash rule. Of the
  next 5,077 answers to find, 943 are already queued for a person.
- **Apertus with a reviewer.** Apertus reads dates and a person confirms them, the design the registered null-safety
  tests (P1, P2, P6) support; P6 kept the shipped reader v1.
- **Gold anyone can check.** Labels come from blind multi-annotator agents, cross-checked by another vendor's model and
  by non-LLM sources; a 30-row kit lets anyone, OPD included, verify the gold in about an hour
  ([`results/opd_spotcheck/`](results/opd_spotcheck/README.md)).

## What is in the repository

| Deliverable (challenge) | Where |
|---|---|
| Representation model: versioned schema + controlled vocabularies | `src/gegenprobe/schema/schema_v0_1.py`, `schema/gegenprobe_schema_v0_2.py`, `data/schema/*.json`, `results/schema/*.schema.json`, `docs/schema.md`, `docs/mapping.md`, `docs/ech-onepager.md` |
| Converter: prompts + code, provenance per value | `src/gegenprobe/convert/`, prompts `src/prompts/{de,fr,it}/`, `docs/converter.md`, `docs/convert-your-own.md` |
| Whole affairs, Q/A pairs, people, recommendation, virtual affairs | `src/gegenprobe/affair/`, `src/gegenprobe/qa/`, `src/gegenprobe/virtual/`, `docs/affair.md`, `docs/qa.md`, `docs/virtual-affairs.md` |
| Validator | `src/gegenprobe/validate/` (schema, span re-check, typed-null consistency) |
| Evidence: nine pre-registrations | `eval/prereg*/` (each with `DEVIATIONS*.md`), gold sets `data/gold*/`, `docs/gold_protocol.md`, `docs/evaluation.md` |
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
