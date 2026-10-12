# Gegenprobe: one schema and a converter for Swiss parliamentary answers

Track 2A · OpenParlData (OPD) · Team 444 · **Start here:**
- **Evidence site:** https://gegenprobe.mi11ion.io · **technical report:** [`technical_report.md`](technical_report.md) (PDF `444_Report.pdf`)
- **One page for OPD's management and a chancellery:** [English](docs/decision.md) · [Deutsch](docs/decision_de.md); for a data protection officer, [a register checklist](docs/dpo_checklist.md) (EN/DE)
- **Replay:** `make run` (Docker, CPU, clean checkout; [what it runs](#operations)); `make claims` recomputes every number from its results file and fails on any mismatch

**For OPD, in three lines** (detail: [Ready for OPD](#ready-for-opd)):
1. **Apply now:** repair lists keyed on your ids, as dry-run plans; 3,621 repairs need neither a decision nor a fetch.
2. **Needs one decision:** your hash rule for relinked documents, which the 2,421 ready Bern relinks follow. OPD confirmed the Bern linking bug (correspondence, 10 Oct 2026).
3. **Apertus 70B (opt-in) reads layouts no rules cover:** 24 of 29 answer dates vs 2 of 29 for the rules (pre-registered test); in use, a reviewer confirms each value.

| | |
|---|---|
| **What runs** | a nightly job on one CPU core: rules write the values; no model runs by default; Apertus (review mode, opt-in) proposes values and a reviewer confirms each |
| **Runtime external services** | none by default (public sources only); Apertus review mode sends document text to the Public AI gateway, a US nonprofit without a processing agreement (nDSG Art. 16), or nothing with the local 8B on CPU |
| **Cost** | the rules take about 0.5 CPU-hours for all 902,754 documents in OPD's export, about 5 at ten times OPD's volume; review mode costs USD 0.59 per 1,000 documents the rules leave open, on the 70B ([Operations](#operations)) |
| **Maturity** | census and Bern repair lists ready to apply (relinks: after the hash decision); nightly job ready to deploy; source-adapter lists audited; rules-only converter a tested prototype; review mode a feasibility study; schema v0.1 and v0.2 drafts for the eCH group |

**Can one schema hold Swiss parliamentary business? Yes, if each field says which role its value plays** (e.g. "answer
date" = the government's decision, its letter or the submission date), for the 17-field skeleton of OPD's five intervention types: 198,594 of its 325,691 affairs.

| verdict | fields | example |
|---|---|---|
| needs roles | **10** (8 robust + 2 fragile; 6 from the pre-registered role test, 4 from OPD's labels, post hoc) | "answer date" is the decision, the letter or, in 7 parliaments, mostly the submission date |
| body-specific | **1 field and 2 constructs** | the submission date; oral answers; councils that publish only minutes |
| untested | **6**, defined once in v0.1 | whether each means the same everywhere is the next test |
| beyond interventions | exploratory, 15 affairs ([scope](#evidence-at-a-glance)) | the executive as proposer |

> **Where a common schema breaks**
> - **Submission date:** OPD's date is printed in neither document in Vernier (5/5 affairs) and Lausanne (3/5), 2 to 28 days after the signing or lodging date they print.
> - **Authorship:** a sole author or first signatory (Bern city, Vaud, Lausanne), joint authors with none first (Zürich city, Thurgau, Fribourg, Vernier) or a parliamentary group (Valais).
> - **Oral answers** have no written text (a typed null), and 16 councils publish only minutes (affairs rebuilt from them are marked `virtual`).
> - **Federal answers** print no answer date and no author; **government business** puts the executive in the proposer's seat.

| | |
|---|---|
| **81.6% → 92.1%** | of interventions with a recorded government answer have answer text today, and would once the 9,580 model-free repairs proposed to OPD are applied (3,621 apply now · 2,459 Bern relinks after the hash decision · 3,500 fetched from the parliaments), keyed on OPD ids; the Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation |
| **186** | v0.2 records from 26 parliaments validate; against blind labels on 36 held-out affairs the converter is right on the type 35/36, the submission date 30/34, the submitter 30/36 and the answer date 20/35, 31/35 with Apertus ([per field](#converter-accuracy)) |

## Evidence at a glance

**Scope.** The "Yes" covers the affair's skeleton of 17 fields; the statements inside an answer are a layer of their own
(45.9% had no schema account in an inventory over 12 bodies, [`docs/census.md`](docs/census.md)). Parliamentary
initiatives (5,817) and government business (37,864) share the vocabulary and are outside the tested scope. **Outside
interventions the skeleton does not carry over as is** (P11, exploratory, 15 affairs): 7 of the 17 fields fit unchanged,
4 answer fields do not apply, and 6 need roles interventions lack, chiefly the executive acting as proposer (adopting,
endorsing and signing its own proposal; 7 of 8 government-business affairs). Bern city's co-signatory list holds
authors of record; federal answer dates exist only in OPD's events (federal cell, exploratory).

### What Apertus adds

| result | test | scope |
|---|---|---|
| **24/29** answer dates in 15 parliaments nobody wrote rules for; the rules, written for other layouts, find 2/29 | the date test, P2 | registered |
| **+23.4 points** author-role recall over the rules in 14 parliaments without rules (50/141 pairs vs 17/141); precision not worse | the author test, P10 (H1, H2) | registered |
| **120/120** sampled review-queue promotions are the government's answer | the verifier test, P7 (H1) | registered |
| **12/12** Italian interventions exact on the answer date (10 printed dates, 2 right nulls), five parliaments | P11 | exploratory |

**What only the closed design gives** (post hoc): every value Apertus returns is a printed value located by code (62/62,
32/32 and 35/35 on P1, P2 and P6), where free prompting's quotes check out on 30/60 and 17/32; and its confidence margin
turns the documents the rules leave open into a ranked review queue: on layouts no rules cover it puts wrong values
first with AUROC 0.90 (P2), above the no-model ranking signals we tested (at most 0.58; the interval of the
difference excludes zero).

<sub>Sources: 92.1% and 9,580 from the census and the repair lists (no model); 10 of 17 from OPD's labels and P8; 186
from `results/schema/v0_2/validation_all.json` (the 15 federal records from an exploratory cell); 24/29 from P2 and
+23.4 points from P10 (Holm p = 0.032), registered; 120/120 from P7 (Wilson 95% [96.9, 100]); the margin from
`results/eval/margin_vs_nomodel.json`; the baselines proposed in review are in
[`docs/evaluation.md`](docs/evaluation.md#baselines-proposed-in-review). **Which model:** every committed gateway response (17,720) comes from one
build, Apertus 70B by inference (the gateway labelled it 8B; fingerprint check in
[`docs/evaluation.md`](docs/evaluation.md#use-of-apertus)); on 12 Oct 2026 Public AI switched the route to another build
and back, and the build guard caught it live ([Which model](#operations)); local 8B results: same section.
Codes: P1–P8 and P10 are the ten tests (P3b replicates P3), each frozen by hash before its labels except P1's hypothesis script and rules (D4, D12); D-numbers are logged
deviations from them (`eval/prereg*/DEVIATIONS*.md`, [which folder is which test](docs/evaluation.md#which-folder-is-which-test));
θ is the frozen margin above which Apertus answers null; post hoc means analysed after the labels.</sub>

**For OPD: the files.** Every list is a dry-run plan keyed on your ids; the one open decision is your hash rule for
relinked documents (keep the old identifier or issue a new one).

| file | what it is | how to run |
|---|---|---|
| [`results/repair/`](results/repair/) | repair lists keyed on OPD ids: Bern relinks, fetches and `begin_date`, adapter lists, the Apertus review tier | download ([Ready for OPD](#ready-for-opd)) |
| [`apply_BE_plan.sql.txt`](results/repair/apply_be/apply_BE_plan.sql.txt) | the Bern plan: rolls back unless every statement changes exactly one row; run on PostgreSQL in CI ([column mapping](results/repair/apply_be/COLUMN_MAPPING.md)) | `python -m gegenprobe.repair.apply_be --fetch --out DIR` |
| `gegenprobe affair` | one validated schema v0.2 record for a cantonal, communal or federal OPD affair, from OPD's metadata and the affair's documents: the published record itself (on the three samples 268/268, 380/380 and 325/325 comparable fields equal, roles and answering body included) | `python -m gegenprobe affair --opd-affair <id> --schema v0.2` |
| [`gegenprobe_schema_v0_2.py`](schema/gegenprobe_schema_v0_2.py) | schema v0.2 with P8's roles, one file, pydantic only (v0.1: [`gegenprobe_schema.py`](schema/gegenprobe_schema.py); the draft [v0.2.1](schema/gegenprobe_schema_v0_2_1.py) adds the `cited` date role, v0.2 itself stays frozen) | `make schema-v02` |
| [`results/opd_spotcheck/`](results/opd_spotcheck/) | 30 gold labels with link, page and quote, verifiable in about an hour | `python -m eval.spotcheck score` |
| [`docs/ech-onepager.md`](docs/ech-onepager.md) | the per-field recommendation for the eCH group | read |
| [`docs/converter-coverage.md`](docs/converter-coverage.md) | the converter's status in every parliament and the tests that read it | `python -m report.converter_coverage` |

- **Auditable by construction:** every value Apertus extracts is a date or phrase printed in the document, located by
  code; its yes/no answers and category labels are judgements a person reviews. The default runs no model.
- **Sovereign and cheap to run:** the default only reads public sources (OPD's exports, Bern's open data, Fedlex, the
  parliaments' sites). A first network night took 86 min on a GitHub runner, the next 6.6 min; at ten times OPD's
  volume the rules need about 5 CPU-hours ([Operations](#operations)).
- **Pre-registered:** ten tests, each frozen by hash before its labels (P1's hypothesis script followed its labels and
  its rules entered with its sample, both logged: D4, D12). `make claims` recomputes every number in this README, the
  report and the form from its results file and fails on any mismatch, or on a number or scope word (post hoc,
  registered, exploratory, in-sample, held out, weighted) not bound to its claim, or on a verdict, multiplier or safety
  phrase outside its pinned wording.

One record, trimmed ([`results/schema/v0_2/samples/p3_BE_39369.json`](results/schema/v0_2/samples/p3_BE_39369.json);
hash shortened). Every value has its document, page, span and rule, or its OPD record; an empty field says why. The
answer date is the government's decision (OPD's date is printed at the decision "N° d'ACE 508/2022 du 18 mai 2022"),
and its box on the page is in `span_bboxes.jsonl`. The Bern answer is French although OPD tags it German.

```json
{
 "schema_version": "0.2.0",
 "ref": {"body_key": "BE", "number": "2021.RRGR.388", "opd_id": 39369, "virtual": false},
 "actors": [
  {"role": "joint_author", "kind": "person",
   "name": {"kind": "value", "value": "Ruchti", "basis": "extracted", "route": "rule",
            "rule": "roles-2:authors:table:eingereicht_von", "doc": "opd:23227", "page": 1,
            "char_start": 231, "char_end": 237, "quote_sha256": "94cbc0329ffdf881…"}}
 ],
 "qa": [{
  "answer_date": {"kind": "value", "value": "2022-05-18", "role": "answer_decided", "basis": "normalised", "route": "rule",
                  "rule": "opd_event_date_in_document", "doc": "opd:656633", "page": 1,
                  "char_start": 466, "char_end": 477, "quote": "18 mai 2022"},
  "answering_body": {"kind": "value", "value": "Regierungsrat des Kantons Bern", "basis": "metadata",
                     "route": "metadata", "source": "opd:bodies/253#executive_name"},
  "answer_identifier": {"kind": "null", "null_reason": "present_unanchored", "route": "rule",
                        "evidence": "decision number carried on answer_date.decision_number"}
 }],
 "documents": [
  {"doc_id": "opd:656633", "role": "answer", "language_tag": "de", "language_of_text": ["fr"]}
 ]
}
```

![Where the registered gap is](docs/figures/fig1_funnel.png)

## Ready for OPD

Every list is keyed on OPD ids, is in `results/repair/` (vocabulary list: `results/census/`) and is a direct download in
the app (About, Downloads; the Repair queue exports any selection). The apply plan is a dry run: we change nothing in OPD.

| list | rows | how each row is checked | applies |
|---|---|---|---|
| `repair_BE_relink.tsv` | 2,421 Bern answers already in OPD, unlinked | against OPD's own copy: affair number, answer heading, decision date = OPD's answer event | once OPD picks its hash rule for relinks |
| `repair_BE_fetch.tsv` | 48 answers to fetch from the canton | identity and heading, every row | now |
| `repair_BE_begin_date.tsv` | 554 load timestamps set to the affair's own submission event (173 to review) | the affair's "Eingereicht" event | now |
| `adapters/adapters_<BODY>.tsv` | 6,473 counted answers from 50 model-free source adapters, 27 with counted repairs; 2,177 of them a category on a document OPD already holds | affair number or title, answer formula, date check | per list |
| `adapters/p7/promoted_by_apertus.tsv` | 214 review rows verified by Apertus, in the adapter-list columns, tier `promoted_by_apertus`, `counted=false` | P7, pre-registered; a pre-sorted batch for OPD's review step | after review |
| `results/census/vocab_bugs.tsv` | 9 OPD harmonised labels wrong as published | e.g. type "Votaziun" (Romansh for a vote) on 9,887 affairs | OPD's vocabulary |
| `results/findings/stale_states.tsv.gz` | 7,876 answered interventions whose last OPD state is still "submitted" (5.9% of 133,215 answered, 73 parliaments) | the state event against the attached answer or the answer event, every row | OPD's state field |
| `repair_CHE.tsv.gz` | 29,946 federal documents whose OPD text is Fedlex's "JavaScript required" page | resolver fetches each text through Fedlex; pre-set rule 40/50 on a sample | one-off run, about 17.5 h at the polite rate |

- **Bern.** OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet 96.1% are already in OPD and
  linkable without a model: 2,459 relink candidates = 2,421 ready (every check passes) + 38 for review, and 49 fetch
  rows = 48 ready + 1 for review. OPD confirmed the linking bug and its root cause, and that the relink list is the
  workaround until its fix ships (correspondence, 10 Oct 2026).
- **The one open decision.** OPD's document `hash` is sha256(body_key + parent_type + url), so relinking changes each
  identifier unless OPD keeps the old one. `python -m gegenprobe.repair.apply_be --fetch --out DIR` writes the plan with
  before and after state and both hash values (`--hash keep`); `python -m gegenprobe.repair.acceptance` counts what OPD
  has attached and can gate a deployment.
- **The plan runs on PostgreSQL.** A CI job (`apply-be-postgres`) and a local run on PostgreSQL 16.2 rebuild the
  before-state from the committed join and apply the unchanged plan: 2,975 rows change (2,421 relinks, 554
  `begin_date` corrections), each to its planned value, and none of the 173 review rows; a second run, or one perturbed
  row, rolls the whole transaction back (`results/repair/apply_be/apply_BE_pg_check.json`).
- **What the 9,580 are:** 8,949 checked row by row, 592 agenda joins (OPD's own agenda link, not sample-checked) and
  39 Bern rows in review. In the blind audit of the counted adapter rows, AI annotators judged 185/186 to be the
  executive's answer (Claude; 3 dates judged wrong, all Solothurn, where the auditor saw OPD's "Beantwortet" date, the
  committee's) and the second auditor, from another vendor (Qwen-SEA-LION), 186/186 (post hoc re-read of audit v3 over
  the strata that still count; `results/repair/adapters/audit3/`). Valais's 140 date-window rows moved to review:
  OPD's Valais answer event is the session that debated the motion, after the government's letter; logged in
  `results/repair/adapters/retier/retier_r18.json` (the audit as run, on 200 rows: 197/200, and 12 of its 15 date
  verdicts fell on the 14 sampled rows of that stratum). The 554 `begin_date` corrections fix a different field and are
  not among the 9,580.
- **What each repair still needs.** 3,621 need neither a decision nor a fetch (agenda joins, category tags, verified
  text of OPD's own copies): with them 85.6% of the 91,268 have answer text. 2,459 Bern answers OPD holds without a
  parent (2,421 relinks, 38 in review) follow its hash decision: 88.3%. 3,500 answers checked at the parliaments are
  fetched into OPD: 92.1%.
- **The nightly job** re-runs the census and the Bern route against OPD's exports; three real network nights and a
  real two-night Docker pair ran on standard GitHub runners ([detail](docs/operations.md#the-nightly-job-real-nights)).

**Findings for OPD's data** (post hoc, no model):

- **Stale procedural states.** OPD's state field lags its own data: 7,876 of 133,215 answered interventions (5.9%,
  73 parliaments) still carry "submitted" as their last state although OPD holds the answer (Bern 1,057, Lugano 1,005,
  St. Gallen city 837); in the converter's 120 records this is 19, and the operator command flags each for review
  (`results/findings/stale_states.json`, the same check on the census and on the records).

- **Answer times** (post hoc): where OPD's "answer" event is the submission date, OPD's plain median says 0 days; in
  Kriens the verified answer documents give 26.5 days on 68 affairs. Question and answer in different languages,
  and the answer-times figure: [`docs/census.md`](docs/census.md#7-findings-for-opds-data-moved-from-the-project-readme).

Detail, per list and per check: [`docs/operations.md`](docs/operations.md), [`docs/repair.md`](docs/repair.md),
[`docs/adapters.md`](docs/adapters.md), [`docs/runbook.md`](docs/runbook.md).

## Findings

### 1. The schema: shared concepts, explicit roles

A common schema works if it carries roles, not only for dates. Meaning is now measured for 11 of the 17 fields: 4
on OPD's own labels, 6 on the documents in P8 and 1 (type) on both. v0.1 encodes the five label splits; v0.2
(`schema/gegenprobe_schema_v0_2.py`) adds P8's roles: author roles (sole author, joint author, first signatory,
co-signatory, supporter, group, committee, spokesperson), the instrument's function next to the harmonised type, the
text's language apart from the source's tag, submission-date roles (signed, lodged, received, announced, later step)
and the recommendation's stage (on adoption, on fulfilment). 186 v0.2 records from 26 parliaments validate: the
converter's 120 (105 cantonal and communal + 15 federal, 23 parliaments) and P8's 66 gold records (11 parliaments); the
v0.1 samples upgrade losslessly (`results/schema/v0_2/validation_all.json`, `make schema-v02`). Validating says the
records have the schema's form; what they hold differs by field (`results/schema/v0_2/field_completeness.json`): of
the 2,040 field-record pairs of the converter's 120 records, 1,171 hold a value, 783 a typed gap, 86 an answer date
whose role is not split and 0 nothing; a record with an untyped cell fails `make schema-v02`. P8's 66 gold records leave
116 cells empty (addressed body and co-signatories, which its annotators did not label). Every value of the converter's
records has its page and span (1,580) or its source record (578: 569 OPD records, and 9 federal answering-body values
from a one-row committed table, since OPD's bodies export names no federal executive); 1,573 of the 1,580 spans also
have their box on the PDF page (`span_bboxes.jsonl`; the 7 others are federal values in OPD's text records), so a
side-by-side PDF view can highlight each. **The answer date's role is in the records:** of the 142 answer dates in the
converter's 120 records, 25 are the government's decision and 17 its letter or dispatch (in 28 records), each from a
role printed in the document (the blind gold role agrees 32/32); the other 100 stay `answered` with a typed reason (no
role printed at the date: 87; OPD's answer date equals the submission date, Valais and Schaffhausen: 13). Every record carries its submission
date, history, usable text and answer-link status; 118/120 the answering body and 118/120 the procedural state from
OPD's metadata (each value typed with its source record), 71/120 an answer date, 19/120 a decision outcome (86 more
typed `not_applicable`) and 12/120 related affairs. Reading OPD's harmonised type id also fixed the converter's type
table, which had typed 33 written questions `unknown` (now 0).

#### Converter accuracy

Validation checks each record's form; accuracy per field is measured against blind labels. On 36 held-out whole
affairs from 9 parliaments (P3b, the registered replication of P3), the five fields it scores:

| field | default converter (OPD metadata + rules, no model) | with Apertus suggestions |
|---|---|---|
| type | 35/36 | 35/36 |
| submitter | 30/36 | 30/36 |
| submission date | 30/34 | 30/34 |
| affair number | 18/29 | 18/29 |
| answer date | 20/35 | 31/35 |

**What would have meant No** (proposed in review): a field body-specific in 2 or more parliaments for reasons of
practice rather than OPD's data, or values outside every named role. v0.2's roles fit the intervention gold labelled after
they were frozen ([role fit and the converter's roles](docs/schema.md#role-fit-the-no-criterion-and-the-converters-roles)).

**Tables, annexes, images, scans and signatures** (`src/gegenprobe/convert/parts.py`, rules parts-1, no model). The
converter marks each by page range in v0.2's `parts`, so a table or annex is referenced where it is, not re-extracted:
66 of 105 converter records carry at least one. Two blind AI annotators labelled 30 of its documents page by page
from the page images (108 pages; exploratory, in-sample for the detector, whose rules were written on these
documents; `results/parts/blind_check.json`):

| part (page level) | precision | recall |
|---|---|---|
| table | 12/12 | 12/15 |
| annex | 6/6 | 6/6 |
| scanned page | 23/24 | 23/23 |
| image | 4/8 | 4/6 |
| signature | 5/5 | 5/23 |

The detector marks a signature when it is an image; the annotators also counted printed signatory lists.

**Where the converter reads documents** (every parliament with its tests: [`docs/converter-coverage.md`](docs/converter-coverage.md),
`results/convert/coverage_by_parliament.json`). Of 91 bodies (the 89 of the feasibility matrix and 2 more a test
sampled), 54 appear in at least one test and 26 have affairs among the validated v0.2 records:

| converter status | bodies | in a test | the converter's document values there |
|---|---|---|---|
| frozen rules | 15 | 15 | from the frozen DE/FR/IT rules, unattended |
| source adapter | 38 | 21 | flagged for review (`no_rules_for_body`); a model-free source adapter verifies their answers for the repair lists |
| metadata only | 38 | 18 | flagged for review (`no_rules_for_body`) |

**Adding a parliament.** A parliament moves from `no_rules_for_body` to rules of its own through its settings file:
answer-date and recommendation anchors (`--anchors`), checked on a sample of its documents, then `confirm_rules`, with
no fork of the frozen rules ([guide](docs/convert-your-own.md#your-own-anchors---anchors-file)). Next come the
source-adapter parliaments already in a test and in the v0.2 records, largest first by interventions with a written
answer in the census: Bern city, Fribourg, Basel-Landschaft, Vaud and Thurgau ([`docs/converter-coverage.md`](docs/converter-coverage.md)).

Field by field, with the federal cell and the cell outside interventions: [`docs/schema.md`](docs/schema.md#field-by-field-what-the-evidence-shows).

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
| answer-link status | untested (one v0.1 definition) | next | **metadata**: 54 · 0 · 0 · 0 |
| decision date · Q/A pairing · usable text | untested (one v0.1 definition) | next | partly |
| dispatch date · related affairs | untested (one v0.1 definition) | next | PDF only |

Of the 10 role splits, 6 come from the role test (P8, registered) and 4 from OPD's label vocabularies (post hoc); 8 are
robust and 2 are fragile (the split holds under one of P8's two checks). By the source of the split, 4 come from
parliamentary practice, 4 partly from OPD's tagging (which OPD can correct) and 2 are open: the labels cannot tell
practice from harmonisation (technical report, Table 1). Two further concepts are body-specific and get constructs of
their own: oral answers in question time (a null reason) and councils that publish only meeting documents (16 bodies;
v0.1 marks affairs rebuilt from minutes `virtual`, tested in P4). The tested scope is interventions; parliamentary
initiatives, government business and other executive business that answers no member's affair are outside it.
The full table and evidence: [`docs/evaluation.md`](docs/evaluation.md#the-17-fields-in-detail).

### 2. The census: where the answers are

The census streams OPD's exports (snapshot 6 Oct 2026) once and gives each of the 91,268 interventions with a recorded
government answer an answer-link status, typed by cause: attached, filed under an agenda item, stored without a
parent, scanned without text, or not in OPD at all.

- **92.1%** would have answer text once the proposed repairs are applied. Today 81.6% have it attached to the intervention (the
  registered count), 82.3% counting the 592 answers OPD files under an agenda item of the same affair; those 592 are
  also among the 9,580, so the repairs add 8,988 beyond the 82.3%.
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

The default (`rules_only`) runs no model, and no repair behind the 92.1% and the 9,580 needs one: those are rules,
which makes them cheap to run nightly at OPD. Apertus reads where the rules cannot: layouts nobody wrote rules for,
author roles and the adapters' review queue. It answers a closed question or picks one of the dates or phrases printed
in the document, and code locates the page and span, so every value it returns can be checked on the page.

Its results: [What Apertus adds](#what-apertus-adds); test by test, with the local 8B's results:
[`docs/evaluation.md`](docs/evaluation.md#what-apertus-adds-test-by-test).
**Which size:** the local 8B gives date suggestions on CPU where no text may leave the machine; the review-queue
verifier and the role reader need the 70B (the 8B and the 70B on the same documents: [`docs/evaluation.md`](docs/evaluation.md#what-apertus-adds-test-by-test)).

## How it works

```
OPD exports ──► census (answer-link status per affair) ──► repair routes + 50 source adapters ──► lists keyed on OPD ids
answer PDFs ──► OPD metadata ──► frozen DE/FR/IT rules ──► Apertus closed-set pointer (review mode, residue only)
                                         └──► schema v0.1 record: value + role + page/span, or a typed null
```

- **Converter** (`src/gegenprobe/convert/`, `qa/`, `affair/`): `python -m gegenprobe convert <pdf-or-url> --body SG`
  returns JSON in which every value has its page, character span and rule (or OPD record), and every gap a typed null.
  `gegenprobe convert <pdf> --schema v0.2 --body KEY` turns a bare PDF into a validated v0.2 record without an OPD
  affair id: the rules' values with page and span, every field only OPD's metadata supplies a typed null
  `not_in_corpus`; `gegenprobe affair --opd-affair <id>` adds OPD's metadata.
  A parliament with no rules gets `no_rules_for_body` and `needs_review: true`; a settings file adds its own anchors
  without forking the rules. Given OPD's document id, a value found in OPD's own stored text also carries its span there
  (`opd_text_span`), so OPD's workbench can highlight it without re-mapping; the first lookup can stream a body's docs
  export (0.47 GB for Bern), then the text is cached ([`docs/converter.md`](docs/converter.md)). Guide:
  [`docs/convert-your-own.md`](docs/convert-your-own.md).
- **Schema** (`src/gegenprobe/schema/schema_v0_1.py`, normative Pydantic; JSON Schema in `results/schema/`): date roles,
  typed nulls, `QAItem` (question *n* paired with the answer to question *n*). v0.2 (`schema/gegenprobe_schema_v0_2.py`,
  JSON Schema in `results/schema/v0_2/`) extends it with P8's roles; the v0.1 samples upgrade to it losslessly. Mappings to Popolo, Akoma Ntoso,
  Parla-CLARIN and OParl: [`docs/mapping.md`](docs/mapping.md).
- **Apertus pointer**: the model scores `null` and every printed date (or label, or name) by log-probability; it is null
  if the null margin exceeds θ, fitted per build on development documents and frozen.

## Evaluation summary

Ten tests, each with code, prompts and θ frozen by sha256 before any label was committed, except P1's hypothesis
script and rules (D4, D12) (`eval/prereg*/`; [which folder is which test](docs/evaluation.md#which-folder-is-which-test)). Gold
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
| P8 | 66 fresh affairs, 11 parliaments | meaning of 7 fields in the documents | none uniform: 6 role split, 1 body-specific; 5 robust under both checks | meaning measured for 11 of 17 fields |
| P10 | 34 fresh affairs, 14 parliaments without rules | author roles: Apertus reader vs rules and OPD's contributor list | 3 of 4 held: H1 recall, H2 precision, H3b; H3a (over OPD's list) not | (name, role) pairs right 50/141, rules 17/141, OPD's list 37/141 |

- **Above the registered 0.80 bar** (95% lower bound): on P1 the rules are exact on 135/154 documents [81.5, 92],
  finding 47 of 64 answer dates and dating 2 of the 90 answerless documents; the type of whole affairs (P3b, 35/36);
  in P5 question detection, the reasoning span and co-signatory precision. P1's rules entered with its sample (D12);
  P2 is the clean test of transfer, where the rules find 2/29 answer dates.
- **P10 in full:** pair precision, recall and F1: Apertus 0.52, 0.35, 0.42; rules 0.31, 0.12, 0.17; OPD's contributor
  list read as first author and co-signers 0.36, 0.26, 0.30. H3a, F1 over the stronger OPD reading, is not confirmed
  (+0.12, Holm p = 0.17): where OPD lists the authors, its order is a strong baseline. On P8's 6 development
  parliaments, where the prompts and thresholds were chosen, F1 is 0.80 (in-sample); on the 14 unseen ones 0.42. In
  Lugano (Italian, outside the family; the rules in-sample) Apertus reaches F1 0.65, OPD's list 0.62, the rules 0/56
  pairs.
- **Baselines proposed in review:** [`docs/evaluation.md`](docs/evaluation.md#baselines-proposed-in-review).
- **Exploratory cells, locked before the draw and the labels:** the federal cell (15 answers) and P11 (12 Italian
  interventions, 15 affairs outside interventions), both in Findings
  ([`docs/evaluation.md`](docs/evaluation.md#p11-exploratory-an-italian-cell-and-a-cell-outside-interventions)).
- **Gold labels, no human labelling by design.** Two blind agent annotators (Claude Opus and Sonnet) label each
  document, a third breaks ties, quotes are verified by code, and all 96 annotator sessions (P1–P8, P10, the
  document-parts check and the federal cell) ended before GitHub received their labels and started after GitHub
  received the set's lock or draw, where it has one (`results/eval/annotation_sessions.json`). An isolation audit of
  the annotators' own transcripts lists every file the 96 sessions read and every command they ran (3,086 file reads,
  1,295 commands): none touched a key, gold label, result, document text outside its packets, another annotator's
  folder or the internet (0 violations; post hoc, `results/eval/annotator_isolation.json`). A manifest lists all 99
  sessions (P11's 3 included) with start and end, model and the sha256 of each transcript and of each of the 1,393 label
  files they wrote, 1,933 labels, every file written inside its session (`results/eval/annotation_manifest.json`); the
  transcripts are not committed because their packets contain document text, only their hashes. Another vendor's model
  (`Qwen-SEA-LION-v4-32B`, AI Singapore) relabelled
  P1, P2, P6 and P7 blind: κ 0.80–0.93 on P1 and P2, and no registered decision changes. On P8 its labels give the
  same verdict for the five robust fields; its low κ on the submitter (0.24) is mostly an interpretive difference: it
  calls the first of several equal authors the "first signatory". Non-LLM sources agree: OPD's written-answer events
  match 37/44 checkable P1 dates, and publishers' titles that name the decision date 20/20.
- **Statistics.** Holm over all 20 registered confirmatory tests of P1–P7: the 9 that held as registered all survive
  (`results/eval/posthoc_r8_multiplicity.json`); documents are also resampled by whole parliament.

![Scoreboards](docs/figures/fig5_scoreboard.png)

## Operations

Operator sheet (data protection under the nDSG, hardware, external hosts, exit codes and alerts, licences, on one screen):
[`docs/runbook.md`](docs/runbook.md#operator-sheet).

- **`make run`** (Docker, CPU, clean checkout) recomputes the census and asserts it equal to `results/census/`,
  replays the Bern join, runs sample documents through the converter and validator, re-scores the ten tests from
  committed predictions and labels, re-derives the P1 rules arm from the source PDFs, and recomputes every number in
  `claims.tsv` from its results file ([every step](docs/operations.md#what-make-run-checks)).
- **OCR fails loudly.** Without the deu/fra/ita models, or when tesseract exits non-zero or returns empty pages, a scan
  is a typed `ocr_failed`, never an empty text turned into a null, and failed OCR is never cached. The image installs
  the measured models (tessdata_fast, sha256-verified at build time); with them all 154/154 P1 documents re-derive from
  the source PDFs, the 22 Ticino scans included (`results/eval/rederive_local_pinned_ocr.json`). On a host without
  Docker, `make ocr-models` installs and verifies the same pinned models, and `install.sh --venv` does so for the venv
  unit, which sets `TESSDATA_PREFIX` and `GP_OCR_REQUIRE_PINNED=1` like the image.
- **Cache retention.** Cached PDFs and texts expire after `GP_CACHE_MAX_AGE_DAYS` days (default 30), enforced at the
  start of every network night; `make cache-clean` applies it by hand.
- **One affair, one record.** `python -m gegenprobe affair --opd-affair <id> --schema v0.2` writes the published v0.2
  record from OPD's metadata and the affair's documents; `make run` compares it with the three committed samples
  field for field ([detail](docs/operations.md#one-affair-one-record)).
- **Sovereignty.** The default nightly job uses no third-party processor. At runtime Gegenprobe makes read-only
  requests to public sources, at least 1.2 s apart per host, and an optional review model runs where the operator
  chooses: with the local 8B no document text leaves the machine. A body that may not disclose text abroad goes
  without only the review-queue verifier and the role reader. Every runtime host, what is sent and Public AI's terms:
  [detail](docs/operations.md#sovereignty-runtime-hosts), [operator sheet](docs/runbook.md#operator-sheet).
- **Hardened.** The container runs as a non-root uid, read-only, with all capabilities dropped; PDFs are capped in
  size and time; CI gates the systemd units' security exposure and pins every Action by SHA.
- **Supply chain and licences** ([`docs/licences.md`](docs/licences.md)): 8 Python packages under permissive licences,
  every lock hash-pinned, CycloneDX SBOMs in `docs/sbom/`; CI scans every lock and the built image and fails on any
  HIGH or CRITICAL finding with a published fix ([detail](docs/operations.md#supply-chain-and-licences)).
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

**Which model.** Every committed gateway response (17,720, the cache `make run` replays) comes from one build: route
and label `swiss-ai/apertus-v1.5-8b`, the 70B weights by inference ([fingerprint check](docs/evaluation.md#use-of-apertus)).
On 12 Oct 2026 Public AI switched that route to another build and back. The build guard caught the switch live, and
review mode refused the other build, so no result mixes builds ([detail](docs/operations.md#which-model)). The 8B is a
community 4-bit GGUF of `swiss-ai/Apertus-v1.5-8B`, sha256-pinned, run in-process on CPU.

## Next steps

- **Schema with the eCH group.** Meaning is measured for 11 of 17 fields and v0.2 ships P8's roles; next come the
  other six (decision and dispatch dates, Q/A pairing, related affairs, usable text, answer-link status)
  ([`docs/ech-onepager.md`](docs/ech-onepager.md)), then the contents of the document parts the converter marks by
  page (table cells, annex text) and image detection (page precision 4/8).
- **Author roles per layout, the candidate finder where none exists.** The converter's author rules are layout rules:
  on unseen parliaments they miss more than they err (pair precision 39/49, recall 39/137). Where no rule exists the
  model-free candidate finder and document order read the roles and Apertus decides who is an author (P10); the finder
  offers 87 of the 141 gold names on unseen layouts, so finding names is the next lever, with OPD's contributor list as
  a further input.
- **At OPD.** The lists are ready as dry-run plans keyed on OPD ids; the relinks take one decision, OPD's hash rule. Of the
  next 5,213 answers to find, 1,079 are already queued for a person.
- **Apertus with a reviewer.** Apertus reads dates and a person confirms them, the design the registered null-safety
  tests (P1, P2, P6) support; P6 kept the shipped reader v1.
- **Gold anyone can check.** Labels come from blind multi-annotator agents, cross-checked by another vendor's model and
  by non-LLM sources; a 30-row kit lets anyone, OPD included, verify the gold in about an hour
  ([`results/opd_spotcheck/`](results/opd_spotcheck/README.md)).
- **Roles for government business** (P11): the executive as proposer (the adoption date, its own recommendation,
  officials signing) as v0.3 roles; the post hoc record writer for affairs without a member's text (15/15 valid) moves
  into `gegenprobe affair`, which stops with `no_documents` on 12 of P11's 15.

**Limits of the answer, and the next test for each:**

- Three splits rest on one parliament each: the addressed body on Bellinzona (2/4 in v0.1's meaning), the
  recommendation on Vernier (0/3) and the language on Fribourg (4/6, where OPD's tag names the other official
  language). On the affairs where the gold and the Qwen check derive the same category, the addressed body and the
  recommendation become shared (5/7 verdicts hold; post hoc, proposed in review). More parliaments per field come next.
- Italian rests on P11's exploratory cell of 12 affairs, and Italian author roles stay low for every arm (F1 0.32 or
  lower): a registered Italian test with Italian role layouts comes next. If Public AI serves the other build again,
  its θ refit resumes from the 40 dev documents done (`python -m eval.refit_bfd70257.run fit`).
- 6 fields are untested, defined once in v0.1; their meaning test comes next.

## What is in the repository

| Deliverable (challenge) | Where |
|---|---|
| Representation model: versioned schema + controlled vocabularies | `src/gegenprobe/schema/schema_v0_1.py`, `schema/gegenprobe_schema_v0_2.py`, `data/schema/*.json`, `results/schema/*.schema.json`, `docs/schema.md`, `docs/mapping.md`, `docs/ech-onepager.md` |
| Converter: prompts + code, provenance per value | `src/gegenprobe/convert/`, prompts `src/prompts/{de,fr,it}/`, `docs/converter.md`, `docs/convert-your-own.md`, coverage per parliament `docs/converter-coverage.md` |
| One OPD affair to one v0.2 record (operator command) | `src/gegenprobe/affair_product.py` on `src/gegenprobe/affair_cli.py` (`python -m gegenprobe affair`), `docs/affair.md` |
| Whole affairs, Q/A pairs, people, recommendation, virtual affairs | `src/gegenprobe/affair/`, `src/gegenprobe/qa/`, `src/gegenprobe/virtual/`, `docs/affair.md`, `docs/qa.md`, `docs/virtual-affairs.md` |
| Validator | `src/gegenprobe/validate/` (schema, span re-check, typed-null consistency) |
| Evidence: ten pre-registrations | `eval/prereg*/` (each with `DEVIATIONS*.md`), gold sets `data/gold*/`, `docs/gold_protocol.md`, `docs/evaluation.md` |
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
