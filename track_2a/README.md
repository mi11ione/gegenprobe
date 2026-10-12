# Gegenprobe: one schema and a converter for Swiss parliamentary answers

Track 2A · OpenParlData (OPD) · Team 444 · **Evidence site: https://gegenprobe.mi11ion.io** · technical report:
[`technical_report.md`](technical_report.md) (PDF `444_Report.pdf`)

**For OPD, in three lines** (detail: [Ready for OPD](#ready-for-opd)):
1. **Apply now:** repair lists keyed on your ids, as dry-run plans; 3,621 repairs need neither a decision nor a fetch.
2. **Needs one decision:** your hash rule for relinked documents, which the 2,421 ready Bern relinks follow. OPD
   confirmed the Bern linking bug (correspondence, 10 Oct 2026).
3. **Research:** schema v0.2 and the converter's roles (drafts for the eCH group); Apertus as a reviewer's aid.

**Can one schema hold Swiss parliamentary business? Yes, if each field says which role its value plays** (e.g. "answer
date" = the government's decision, its letter or the submission date). Tested on OPD's five intervention types
(interpellation, motion, postulate, question, question time): 198,594 of its 325,691 affairs. The "Yes" covers the
affair's skeleton of 17 fields; the statements inside an answer are a layer of their own (45.9% had no schema account
in an inventory over 12 bodies, [`docs/census.md`](docs/census.md)). Parliamentary initiatives (5,817) and government
business (37,864) share the vocabulary and are outside the tested scope. **Outside interventions the skeleton does not
carry over as is** (P11, exploratory, 15 affairs): 7 of the 17 fields fit unchanged, 4 answer fields do not apply, and 6
need roles interventions lack, chiefly the executive acting as proposer (adopting, endorsing and signing its own
proposal).

- **Shared:** one schema of 17 fields for communal, cantonal and federal business; every value carries its role and
  source (page and span, or the OPD record), every gap a typed reason.
- **Needs roles: 10 fields,** e.g. "answer date" is the government's decision, its letter or, in 7 parliaments,
  mostly the submission date.
- **Body-specific: 1 field and 2 constructs:** the submission date (in Vernier, 5/5 affairs, and Lausanne, 3/5, OPD's
  submission date is printed in neither document; they print the member's signing or lodging date 2 to 28 days
  earlier); oral answers, councils that publish only minutes.
- **Untested: 6 fields,** defined once in v0.1; whether each means the same everywhere is the next test.

**Delivered:** repairs for 9,580 answers keyed on OPD ids, every one from model-free rules; schema v0.2 with the roles;
a converter that gives every value its page and span; a nightly job. Apertus only picks values printed in the document,
and code locates them (70B weights via the Public AI gateway; local 8B on CPU). **Runtime external services:** none by
default (public sources only); Apertus review mode sends document text to the Public AI gateway, or nothing with the
local 8B. **Cost:** the rules take about 0.5 CPU-hours for all 902,754 documents in OPD's export, about 5 at ten times
OPD's volume; review mode costs USD 0.59 per 1,000 residue documents on the 70B ([Operations](#operations)).

| | |
|---|---|
| **92.1%** | of interventions with a recorded government answer would have answer text once the proposed repairs are applied, up from 81.6% today: 91.5% from row-checked repairs + 0.6 points from the 592 agenda joins and 39 review rows ([staged](#ready-for-opd)) |
| **9,580** | answers with a model-free repair proposed to OPD, keyed on OPD ids; the Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation |
| **10 of 17** | fields are shared once their roles are explicit (8 robust + 2 fragile; 6 from the role test, P8, registered, and 4 from OPD's label vocabularies, post hoc); 1 is body-specific; 6 are not yet tested for meaning |
| **186** | v0.2 records from 26 parliaments validate: the converter's 120 (105 cantonal and communal + 15 federal, 23 parliaments) and P8's 66 gold records (11 parliaments) |

**What Apertus adds, next to a model-free baseline** (parliaments nobody wrote rules for; the baseline is the one in
P2's results table):

| result | what Apertus adds | what the model-free baseline reaches |
|---|---|---|
| **24/29** answer dates on new layouts (the date test, P2; 15 parliaments) | exact on 53/62 documents against the baseline's 44/62: right on 10 where the baseline is wrong, the reverse on 1 (exact McNemar p = 0.0117; parliament-resampled interval of the difference [0.056, 0.243]; post hoc); 4 of its 7 wins on answered documents are documents OPD types as interventions, where that baseline returns nothing by construction | the latest date on answer-typed documents: 18/29 answer dates, 44/62 exact; registered: the rules 2/29 |
| **50/141** author roles in 14 parliaments without rules (the author test, P10) | Apertus adds precision deciding who is an author (+7.3 points, post hoc) | Rules 17/141; most of the gain comes from the model-free candidate finder (document order 52/141) |

<sub>Sources: 92.1% and 9,580 from the census and the repair lists (no model); 10 of 17 from OPD's labels and P8; 186
from `results/schema/v0_2/validation_all.json` (the 15 federal records from an exploratory cell); 24/29 from P2,
registered against the rules (the baselines post hoc, proposed in review; a generic keyword rule finds 16/29, exact
McNemar p = 0.057); 50/141 from P10, registered (recall +23.4 points over the rules, Holm p = 0.032), level with OPD's
contributor list (37/141; H3a, Holm p = 0.17); the author filter's +7.3 points: one-sided p = 0.012, uncorrected.
**Which model:** every committed gateway response (17,568) comes from one build, Apertus 70B by inference (the gateway
labelled it 8B; fingerprint check in [`docs/evaluation.md`](docs/evaluation.md#use-of-apertus)); on 12 Oct 2026 Public AI
switched the route to another build, and the build guard caught it live ([Which model](#operations)); local 8B
results: same section.
Codes: P1–P8 and P10 are the ten tests (P3b replicates P3), each frozen by hash before its labels; D-numbers are logged
deviations from them (`eval/prereg*/DEVIATIONS*.md`, [which folder is which test](docs/evaluation.md#which-folder-is-which-test));
θ is the frozen margin above which Apertus answers null; post hoc means analysed after the labels.</sub>

```bash
make run    # Docker, CPU, clean checkout: census, Bern join, converter samples, test replays, claims check, evidence site
```

## Evidence at a glance

> **Where a common schema breaks**
> - **Submission date:** in Vernier (0/5) and Lausanne (2/5) OPD's date is mostly printed nowhere in the documents, 2
>   to 28 days after the signing or lodging date they print.
> - **Authorship:** a sole author or first signatory (Bern city, Vaud, Lausanne), joint authors with none first (Zürich
>   city, Thurgau, Fribourg, Vernier) or a parliamentary group (Valais); Bern city's co-signatory list holds authors of
>   record.
> - **Oral answers** in question time have no written text: a typed null, not a missing answer.
> - **Minutes-only councils:** 16 councils publish only meeting documents: affairs rebuilt from minutes are marked
>   `virtual`.
> - **Federal answers** print no answer date and no author: the date exists only in OPD's events (federal cell,
>   exploratory).
> - **Government business** puts the executive in the proposer's seat: it adopts and endorses its own proposal and
>   its officials sign it, roles interventions lack (7 of 8 affairs; P11, exploratory).

**For OPD: the files.** Every list is a dry-run plan keyed on your ids; the one open decision is your hash rule for
relinked documents (keep the old identifier or issue a new one).

| file | what it is | how to run |
|---|---|---|
| [`results/repair/`](results/repair/) | repair lists keyed on OPD ids: Bern relinks, fetches and `begin_date`, adapter lists, the Apertus review tier | download ([Ready for OPD](#ready-for-opd)) |
| [`apply_BE_plan.sql.txt`](results/repair/apply_be/apply_BE_plan.sql.txt) | the Bern plan: rolls back unless every statement changes exactly one row; run on PostgreSQL in CI ([column mapping](results/repair/apply_be/COLUMN_MAPPING.md)) | `python -m gegenprobe.repair.apply_be --fetch --out DIR` |
| `gegenprobe affair` | one validated schema v0.2 record for an OPD affair, from OPD's metadata and the affair's documents | `python -m gegenprobe affair --opd-affair <id> --schema v0.2` |
| [`gegenprobe_schema_v0_2.py`](schema/gegenprobe_schema_v0_2.py) | schema v0.2 with P8's roles, one file, pydantic only (v0.1: [`gegenprobe_schema.py`](schema/gegenprobe_schema.py)) | `make schema-v02` |
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
hash shortened). Every value has its document, page, span and rule; an empty field says why. The Bern answer is French
although OPD tags it German.

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
  "answer_date": {"kind": "value", "value": "2022-05-18", "basis": "normalised", "route": "rule",
                  "rule": "opd_event_date_in_document", "doc": "opd:656633", "page": 1,
                  "char_start": 466, "char_end": 477, "quote": "18 mai 2022"},
  "answering_body": {"kind": "null", "null_reason": "not_extracted", "route": "rule",
                     "evidence": "the answering body is not extracted by converter gegenprobe-0.1.0+affair"}
 }],
 "documents": [
  {"doc_id": "opd:656633", "role": "answer", "language_tag": "de", "language_of_text": ["fr"]}
 ]
}
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
| `adapters/adapters_<BODY>.tsv` | 6,473 counted answers from 50 model-free source adapters, 27 with counted repairs; 2,177 of them a category on a document OPD already holds | affair number or title, answer formula, date check | per list |
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
- **The plan runs on PostgreSQL.** A CI job (`apply-be-postgres`) and a local run on PostgreSQL 16.2 rebuild the
  before-state from the committed join and apply the unchanged plan: 2,975 rows change (2,421 relinks, 554
  `begin_date` corrections), each to its planned value, and none of the 173 review rows; a second run, or one perturbed
  row, rolls the whole transaction back (`results/repair/apply_be/apply_BE_pg_check.json`).
- **Tag rows, guarded plan.** `python -m gegenprobe.repair.apply_tags --exports-dir DIR --out PLAN` turns the counted
  `tag_answer` and `extract_tag` rows into a before-state CSV and guarded `UPDATE` statements (id, affair,
  `category_harmonized IS NULL`, and the text hash or "still no text, same URL"); a dry run like `apply_be`.
- **Workbench schema.** `schema/gegenprobe_schema.py` is schema v0.1 as one file: pydantic only, no imports from
  `gegenprobe`, no I/O, its JSON Schemas tested equal to `results/schema/*.schema.json`.
- **Downloads.** Every list above is a direct download on the evidence site, the Fedlex list, `vocab_bugs.tsv`, the
  P7 tier and `gegenprobe_schema.py` included; a missing path returns HTTP 404.
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
- **The nightly job** re-runs the census and the Bern route against OPD's exports. Three real network nights ran on
  standard GitHub runners: one with the venv unit (10 Oct) and two consecutive with the recommended Docker unit
  (11 Oct): 86 min for the first Docker night, 6.6 min for the incremental second (12 bodies re-scanned). Night 2
  exposed a ledger bug (it reset night 1's per-row verdicts to `unchecked`); it is fixed, a row that is not re-checked
  now keeps its stored verdict, and two-night tests guard it (`results/monitor/two_nights_docker_38098822336/README.md`).

**Two findings for OPD's data** (post hoc, no model):

- **Question and answer in different languages.** Where OPD links both language versions, the lowest-id question and
  the lowest-id answer differ in language in 214 of 1,999 affairs with tagged documents (Graubünden 148, Valais 63,
  Bern 3); in 6 affairs no same-language pair exists at all, among them one Valais affair split in two
  (`results/findings/cross_language_links.json`, [`docs/qa.md`](docs/qa.md)). In OPD's federal texts the Italian
  answer slot holds French text in 7,165 of 37,828 answers (the converter's language detector, `results/fed/pool_probe.json`).
- **Answer times: where OPD's "answer" event is the submission date, OPD's plain median says 0 days.** In Kriens the
  verified answer documents give 26.5 days on 68 affairs, where OPD's date on the same affairs gives 0; in Valais the
  23 verified answers that still count give 2 days, mostly interpellations and questions (post hoc; 6,362 durations,
  17 parliaments with at least 20). On the same affairs, OPD's answer dates and the documents' dates rank the 17
  parliaments almost identically (Spearman 0.997); OPD's plain medians and the documents' dates agree at 0.884, and
  OPD's plain medians and OPD's own dates on these affairs at 0.86: the verified answers are the census gap, with their
  own type mix (`results/findings/answer_times.json`, [`docs/census.md`](docs/census.md)).

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
v0.1 samples upgrade losslessly (`results/schema/v0_2/validation_all.json`, `make schema-v02`). The roles are
exhaustive on P8's gold: every value of the six role-split fields falls into a named v0.2 role: 302/302 across 58
field × parliament cells (post hoc; an exhaustiveness check, since v0.2's roles were written from P8's categories),
next to P10's gold from 15 parliaments, where none of the 197 people needed the guide's open `other` role (0/197, post
hoc; `results/p8/p8_v02_role_coverage.json`). Three converter-made v0.2 records, chosen by a written
rule (Bern in German, Vernier in French, Lugano in Italian), are the samples: `results/schema/v0_2/samples/`.
Author roles are checked for consistency (`src/gegenprobe/schema/role_consistency.py`): a sole author never sits next to
joint authors, and a joint author never next to a designated first signatory. The 2 records where the rules printed a
group's name over signatures as the sole author now list the group as one joint author among the signers, as P8's
guide defines it; all 186 v0.2 records pass the check: the converter's 120 and P8's 66 gold records.

**The converter fills the roles** (`src/gegenprobe/convert/roles.py`, fixed rules, no model; exploratory, written after
P8's lock). Of its 105 records, 75 carry printed authors with their role, 78 the instrument's function and all 105 the
language of every text; every value has its page, span and quote hash. Scored on 5 P8 parliaments the rules never saw
(split fixed before their labels were opened; frozen copy in `results/schema/v0_2/converter_roles_frozen/`): the
language of the text 60/60 documents, the instrument named 27/30 affairs, author (name, role) pairs precision 39/49
and recall 39/137: on unseen layouts the author rules mostly abstain. With one layout rule per parliament added
afterwards, all 66 P8 affairs reach pair precision 286/291 and recall 286/345 (in-sample)
(`results/schema/v0_2/converter_roles.json`).

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
  against categories fixed in advance (`eval/prereg9/`), none of the seven fields tested passes the registered test
  of meaning the same thing everywhere. The submitter is a sole author or designated first signatory
  in Bern city, Vaud and Lausanne, one of several joint authors with none designated first in Zürich city, Thurgau,
  Fribourg and Vernier, and a parliamentary group in Valais: 35/65 affairs carry the one meaning v0.1 gives it. Bern
  city prints several first signatories, so OPD's co-signatory list includes authors of record (co-signatories in
  their v0.1 meaning: 10/41). Two Bellinzona "Motions" propose a decision the council takes itself; two Valais
  "Postulate" mandate the executive to act. In Fribourg, OPD's language tag names the other official language in 2
  of 6 affairs.
- **Language needs roles: the text, the tag and the affair.** A document's text has a language (the converter detects
  it: 60/60 documents on held-out parliaments); OPD's tag is a second value that can differ (3 of the 130 tagged
  documents in the converter's records; in OPD's federal texts the Italian slot holds French text in 7,165 of 37,828
  answers); and an affair can be answered in another language than it was asked (9 of the 105 converter affairs; 214
  of 1,999 tagged affairs when the lowest-id documents are paired). v0.2 keeps `language_of_text` apart from
  `language_tag`, per document.
- **Federal level (exploratory, `eval/fed/`, locked before the draw and the labels).** On 15 Federal Council answers
  (5 each in German, French and Italian; seeded, stratified; the two blind annotators agree on all 15), the answer
  prints no answer date and no author: the date exists only in OPD's events (7 of the 15 records carry one; 20,008 of
  38,307 eligible affairs in the frame). The rules, the Apertus pointer and the converter date none of them (15/15
  right nulls), where the latest printed date dates an answerless document on 6/15 [19.8, 64.3]; the instrument's
  function keeps one meaning (15/15), the converter detects the language of all 15 question and 15 answer documents, and the 15
  records validate as v0.2: with them the converter's records number 120 from 23 parliaments, and with P8's 66 gold
  records 186 affairs from 26 parliaments validate (`results/fed/fed_tables.json`).
- **Outside interventions (P11, exploratory, `eval/p11/`, locked before the draw and the labels).** On 15
  government-business and parliamentary-initiative affairs (8 and 7, in German, French and Italian; the gold affair
  kind matches OPD's type in 15/15), the annotators judged field by field whether the intervention skeleton fits. It
  does not carry over as is: 7 fields carry over (submission date, related affairs, usable text, procedural state,
  decision outcome, submitter, language), 4 answer fields do not apply (Q/A pairing, answer date, answer-link status,
  dispatch date: 13 to 15 of the 15 affairs), and 6 need new roles: the date the executive adopted its own proposal
  (decision date, 5 affairs), its recommendation to adopt its own proposal (5), its steps before parliament
  (procedural history, 4), officials signing for it (co-signatories, 4), a general-terms initiative or a spending
  authorisation (type, 2) and the Confederation addressed through a cantonal initiative (1). Government business needs
  a new role in 7 of its 8 affairs, initiatives in 2 of 7. The converter returns a valid v0.2 record for 3 of the 15;
  the other 12 stop with the typed failure `no_documents`, since its pairing rule looks for a member's text and an
  answer (`results/p11/p11_ni_tables.json`).
- **Submission date (P8).** In 9 of 11 parliaments OPD's date is the printed lodging date (one exception allowed). In Vernier (0/5) and
  Lausanne (2/5) it is mostly printed nowhere in the documents, 2 to 28 days after the signing or lodging date they
  print: a data-source split between OPD's date and the documents (registered class: body-specific), which a standard
  resolves by recording which event the date is. These five verdicts hold on agreed labels only and on another vendor's
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
which makes them cheap to run nightly at OPD. Where Apertus runs, it answers a closed question or picks one of the
dates or phrases printed in the document, and code locates the page and span. Apertus earns its place choosing the
right value among printed candidates: the answer date (P2, P7) and who is an author (P10). Which role an author plays,
document order reads as well (below).

- **The answer date on new layouts (P2).** In 15 parliaments nobody wrote rules for, the pointer finds 24/29 answer
  dates in the registered arms, every value a printed date, where the rules, written for other layouts, find 2/29;
  resampled by whole parliament, the registered gain over the rules (P2-H2) is [-0.02, 0.54], so it sits in some
  parliaments, not all. Post hoc (proposed in review), a generic DE/FR/IT keyword rule (government and answer cue; the
  first date after a "Sitzung vom / séance du / seduta del" cue, else the latest date; answer-typed documents only),
  written without the gold and run unchanged, finds 16/29 answer dates: Apertus's lead is in the answer dates it finds
  (exact McNemar p = 0.057). On all 62 documents the pointer is exact on 53/62, the keyword rule on 45/62 (p = 0.077)
  and the latest date on documents OPD types as answers on 44/62 (post hoc; McNemar p = 0.012, parliament-cluster
  permutation p = 0.031, parliament-resampled interval of the difference [0.056, 0.243],
  `results/eval2/p2_posthoc_best_baseline.json`). It puts a date on 4 of the 33 answerless documents, where the latest printed date (22/29
  found) dates 31. A free prompt finds 22/29 as registered, 24/29 (null allowed) and 25/29 (plain) once its answers
  are re-parsed (D2-4).
- **The answer date in Italian (P11, exploratory, locked before the draw and the labels).** On 12 interventions from
  Ticino, Mendrisio, Lugano, Locarno and Bellinzona, read through the converter's own fetch path (12 of the 24
  documents from OPD's copy, where the parliament's robots.txt disallows the source), the pointer is exact on 12/12
  [75.7, 100]: 10 printed answer dates and 2 right nulls, no invented date. The latest date on the answer document is
  exact on 9/12 and dates both answerless affairs; the rules on 8/12 (in-sample in Ticino, Mendrisio and Lugano), with
  4 answers left null and no wrong date. Author roles (70 gold pairs): the rules are precise and sparse (precision
  0.875, recall 0.10), the converter's record reaches F1 0.30, document order and OPD's list 0.22 each (the role rules
  in-sample in 4 of the 5 parliaments); the Apertus role reader read 5 affairs before the build guard stopped it at the
  gateway's build switch (F1 0.12 on their 31 gold pairs). The two blind annotators agree on the answer date and the
  author lists in 12/12 packets (`results/p11/p11_it_tables.json`).
- **The answer date on the review queue (P7, pre-registered).** On the adapters' review queue Apertus answers two
  closed questions: is this the executive's answer to this intervention, and which printed date is the answer date.
  Blind AI annotators judged 120/120 of its sampled promotions the government's answer (H1, registered, Wilson 95%
  [96.9, 100]; 48/48 without its largest parliament, Frauenfeld), where 86.7% of queue rows are answers. A no-model
  exact-date match (a printed date equal to an OPD answer event) promotes answers only as well (146/146), and more
  rows: 206 of the 478-row test frame against Apertus's 135 (126 both, 9 Apertus only; post hoc, proposed in review).
  Apertus's gain is the date. Registered (H4, weighted): 95.8% of its promotions are answers whose printed answer date
  passes the date check, against 73.2% for the exact-date match, +22.7 points [10.2, 34.3] (unweighted +7.5
  [3.4, 12.2]). Post hoc, the date it picks is the gold answer date on 113/120 of its promotions, against 127/146 for the
  exact-date match, each on its own promotions (not paired); weighted, the difference is +22.0 points [9.5, 33.6].
  The tier it fills holds 214 of the 917 review rows it was applied to; the rule that takes the first printed date passing the date check
  recovers 369.
- **Author roles where nobody wrote rules (P10, pre-registered).** Code lists every person or body the two documents
  print, each with its span; Apertus answers closed true/false questions about each (did it lodge or co-sign this
  intervention, is it the designated first signatory); code composes the role. On 34 fresh affairs (of 38 planned;
  the French stratum 4 short under the registered fill rule) from 14 German- and French-speaking parliaments outside
  every rule set, it reads 50 of 141 gold (name, role) pairs right, about three times the rules (17/141), at precision
  0.52 against 0.31; it is ahead of the rules in 9 of the 14 parliaments and behind in 1. Registered, Holm-corrected:
  recall over the rules +23.4 points (H1, p = 0.032), precision non-inferior (H2, observed +0.21). OPD's own
  contributor list, read as first author and co-signers, gets 37/141: Apertus is not significantly better
  (H3a, Holm p = 0.17), and without Neuchâtel the two are level (33 vs 34 of 79 pairs, post hoc). Post hoc (proposed in review):
  the same candidates in document order, read with OPD's registered mapping (the first is first signatory, the rest
  co-signatories, a lone name sole author), match 52/141 gold pairs (111 printed; precision 0.47, recall 0.37) against
  Apertus's 50/141 (96 printed; 0.52, 0.35); per affair 8 better, 7 worse, 19 tied; parliament-cluster bootstrap:
  recall difference -1.4 points [-12, 10.6], F1 +0.9 [-9, 15.5]. The gain over the rules comes from the model-free
  candidate finder and document order, and Apertus's role choice is level with document order. What Apertus adds is
  the author filter: on the same order rule, keeping only the candidates it calls authors keeps recall and prints 96
  pairs instead of 111, +7.3 points precision [0.8, 18.2] (one-sided p = 0.012, uncorrected). The reader ships as a
  review route: `python -m gegenprobe affair --opd-affair <id> --roles apertus` puts its roles next to the record,
  never into it, each marked for review. A fallback to OPD's list where the reader suggests no author is opt-in
  (`--roles-fallback opd`): on P10's arms it added 32 pairs, none right (post hoc).
- **Dates where rules exist (P1).** Apertus adds about one document: the cascade (rules, then the pointer) is exact on
  139/154, a model-free cascade (rules, then the latest date on answer-typed documents; post hoc) on 138/154.
- **People (P5).** Both model routes beat the rules on submitters: pointing at printed names doubles extraction over
  the rules (12/40 → 24/40), and free generation finds 34/40.
- **Provenance by construction.** No closed-set arm returned a date printed nowhere (P1, P2, P6). On the 53 P2/P6
  documents with no answer at all, the P2 pointer and P6's reader v2 dated none (post hoc; the shipped reader v1
  dated 1 of P6's 28). The closed set reaches near free-prompt accuracy (P2 53/62 vs 54/62; P6 59/68 vs 62/68); a
  printed-date filter on a free prompt gives the same no-invention guarantee, the closed set gives it by construction,
  with a page and span for every value and a margin that orders the review queue.
- **Suggestions go to a reviewer; rules run unattended.** By design, Apertus values arrive with `needs_review: true`
  for OPD's existing manual-review step.
- **Sovereign option.** The Apertus 8B runs locally on CPU (a community 4-bit build, sha256-pinned; 9.3 GB peak
  memory, 180 s per document on 4 vCPUs). On the unseen parliaments of P2 it reproduces the registered result over the
  rules (right on 13 documents where the rules are wrong, the reverse on 0; 52 reachable documents), and its two-step
  reader cuts dates on answerless documents from 18/34 to 5/34 (P6); both runs are exploratory. On P1 its cascade dates
  25 of the 90 answerless documents, the 70B's 7: on the local route, as on the gateway, every model value goes to a
  reviewer. Local 8B: date suggestions only; the review-queue verifier needs the 70B. As P7's verifier
  (exploratory; 88 of the 190 annotated rows scored before the deadline) no θ meets the dev rule, so the 8B promotes
  nothing (`results/p7/gguf8b/hypotheses.json`, `data/p7/gguf8b/theta.json`).

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

Ten tests, each with code, prompts and θ frozen by sha256 before any label was committed (`eval/prereg*/`; [which
folder is which test](docs/evaluation.md#which-folder-is-which-test)). Gold
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
  in P5 question detection, the reasoning span and co-signatory precision. On P1 the latest printed date on
  answer-typed documents scores 131/154, level with the rules (paired p = 0.48, post hoc; P1's rules entered with its
  sample, D12); P2 is the clean test of transfer, where the rules find 2/29 answer dates.
- **P10 in full:** pair precision, recall and F1: Apertus 0.52, 0.35, 0.42; rules 0.31, 0.12, 0.17; OPD's contributor
  list read as first author and co-signers 0.36, 0.26, 0.30. H3a, F1 over the stronger OPD reading, is not confirmed
  (+0.12, Holm p = 0.17): where OPD lists the authors, its order is a strong baseline. On P8's 6 development
  parliaments, where the prompts and thresholds were chosen, F1 is 0.80 (in-sample); on the 14 unseen ones 0.42. In
  Lugano (Italian, outside the family; the rules in-sample) Apertus reaches F1 0.65, OPD's list 0.62, the rules 0/56
  pairs.
- **Exploratory cells, locked before the draw and the labels:** the federal cell (15 answers) and P11 (12 Italian
  interventions, 15 affairs outside interventions), both in Findings
  ([`docs/evaluation.md`](docs/evaluation.md#p11-exploratory-an-italian-cell-and-a-cell-outside-interventions)).
- **Gold labels, no human labelling by design.** Two blind agent annotators (Claude Opus and Sonnet) label each
  document, a third breaks ties, quotes are verified by code, and all 96 annotator sessions (P1–P8, P10, the
  document-parts check and the federal cell) ended before GitHub received their labels and started after GitHub
  received the set's lock or draw, where it has one (`results/eval/annotation_sessions.json`). Another vendor's model (`Qwen-SEA-LION-v4-32B`, AI Singapore) relabelled
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
  replays the Bern join, runs sample documents through the converter and validator, re-scores P1–P8 and P10 from
  committed predictions and labels and re-runs their hypothesis scripts (the ten pre-registration locks and LOCKFED
  verified; P7, P8 and P10 byte-identical from the committed `data/p7/`, `data/p8/` and `data/p10/` copies, the P7
  post-hoc files, P10's gold merge and the federal cell's tables included; step `replay_p10`), re-derives the
  P1 rules arm from the source PDFs, regenerates the summary-number files the claims read and asserts them
  byte-identical, and recomputes every number in `claims.tsv` from its results file. It fails if a document a claim
  lists does not print the claimed value; if a numeric token in this README, the technical report or the form notes
  (`claims_strict.json`) is not bound to its claim by an anchor, a phrase recorded for that claim that contains the
  number at that position (`claims_anchor.json`), or listed as a non-claim with its reason; if a scope word (post hoc,
  registered, exploratory, in-sample, held out, weighted) sits outside an anchor or listed phrase; or if
  `444_Report.pdf` lacks a phrase the report's anchors bind. Integers below 10 are checked in the result tables of the
  report. On a clean clone a source that is gone or a document over its time budget is a typed skip (`source_gone`,
  `over_budget`), never a failure, and the operator command reads OPD's own copy of a document whose source is gone.
  Detail: [`docs/operations.md`](docs/operations.md), [`docs/runbook.md`](docs/runbook.md).
- **OCR fails loudly.** Without the deu/fra/ita models, or when tesseract exits non-zero or returns empty pages, a scan
  is a typed `ocr_failed`, never an empty text turned into a null, and failed OCR is never cached. The image installs
  the measured models (tessdata_fast, sha256-verified at build time); with them all 154/154 P1 documents re-derive from
  the source PDFs, the 22 Ticino scans included (`results/eval/rederive_local_pinned_ocr.json`). On a host without
  Docker, `make ocr-models` installs and verifies the same pinned models.
- **Cache retention.** Cached PDFs and texts expire after `GP_CACHE_MAX_AGE_DAYS` days (default 30), enforced at the
  start of every network night; `make cache-clean` applies it by hand.
- **One affair, one record.** `python -m gegenprobe affair --opd-affair <id> --schema v0.2` builds one validated v0.2
  record from OPD's metadata and the affair's question and answer documents, with question/answer pairs: the P5 pairing
  rules' items (question n → answer n, each with page and span; an unmarked answer is a typed null) in `qa[].items`.
  With them 91 of the 105 converter records carry pairs (P3 26/29, P3b 32/36, P5 33/40; before: 33/105); the rules'
  held-out P5 precision is 0.83, recall 0.67, and on the P3/P3b documents the pairs are unscored. `make run` runs the
  command on the three sample affairs (Bern, Vernier, Lugano) and compares each with its committed sample.
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
  request. Every request Gegenprobe sends carries `GP_USER_AGENT`: document and export fetches, robots.txt, the
  model endpoint, the GGUF download and the alert webhook; the one exception is the development budget gateway
  (`gw.py`, outside this repository), which is not a runtime route. A network night refuses to start until
  `GP_USER_AGENT` names your product and a contact URL (the shipped template's placeholder fails closed;
  `install.sh --user-agent '…'` writes it); a value carrying an e-mail address is refused before any request.
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

**Which model.** Every committed gateway response (17,568, the cache `make run` replays) comes from one build: route
and label `swiss-ai/apertus-v1.5-8b`, fingerprint `vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840`, the 70B
weights by inference ([fingerprint check](docs/evaluation.md#use-of-apertus)); the response's `model` field is checked
on every call. On 12 Oct 2026 Public AI switched that route to another build: it now answers as
`swiss-ai/Apertus-v1.5-70B` (the gateway's own label for the new build), fingerprint
`vllm-0.1.dev1+g54b4292c2-tp2-bfd70257`, with other log-probabilities on the same requests (up to 4.64 apart on 3
replays). The build guard caught the switch live and stopped P11's role reader at its first response from the new
build, so no result mixes builds; cached replays stay valid, and review mode refuses the new build (exit 3) until its
θ is fitted ([routes](docs/runbook.md#review-mode-routes)). The 8B is a community 4-bit GGUF of `swiss-ai/Apertus-v1.5-8B`, sha256-pinned, run in-process on CPU. Review mode
stops on a served build its θ was not fitted on.

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
  officials signing) as v0.3 roles, and a converter route for affairs without a member's text (12 of P11's 15 stop
  with `no_documents`).
- **The nightly job's next real nights.** The fixed ledger code runs its first real two-night pair with OPD's next
  exports; two-night tests guard the fix meanwhile.

**Limits of the answer, and the next test for each:**

- Three splits rest on one parliament each: the addressed body on Bellinzona (2/4 in v0.1's meaning), the
  recommendation on Vernier (0/3) and the language on Fribourg (4/6, where OPD's tag names the other official
  language). On the affairs where the gold and the Qwen check derive the same category, the addressed body and the
  recommendation become shared (5/7 verdicts hold; post hoc, proposed in review). More parliaments per field come next.
- Italian rests on P11's exploratory cell of 12 affairs; its role reader read 5 before the build switch, and Italian
  author roles stay low for every arm (F1 0.30 or lower): a registered Italian test with Italian role layouts comes
  next, with θ and the role reader refitted for the gateway's new build.
- 6 fields are shared by definition only (defined once in v0.1); their meaning test comes next.

## What is in the repository

| Deliverable (challenge) | Where |
|---|---|
| Representation model: versioned schema + controlled vocabularies | `src/gegenprobe/schema/schema_v0_1.py`, `schema/gegenprobe_schema_v0_2.py`, `data/schema/*.json`, `results/schema/*.schema.json`, `docs/schema.md`, `docs/mapping.md`, `docs/ech-onepager.md` |
| Converter: prompts + code, provenance per value | `src/gegenprobe/convert/`, prompts `src/prompts/{de,fr,it}/`, `docs/converter.md`, `docs/convert-your-own.md`, coverage per parliament `docs/converter-coverage.md` |
| One OPD affair to one v0.2 record (operator command) | `src/gegenprobe/affair_cli.py` (`python -m gegenprobe affair`), `docs/affair.md` |
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
