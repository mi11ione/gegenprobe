# Gegenprobe: one schema and a converter for Swiss parliamentary answers

Track 2A · OpenParlData · Team 444 · **Evidence site: https://gegenprobe.mi11ion.io** · report: `technical_report.md`

1. **Verdict.** The frame of a common schema is feasible: 17 fields, each a value with its source or a typed null that
   says why it is empty, with dates kept apart by role. The *meaning* is verified across parliaments for 1 of the 17
   fields (the government recommendation); 5 more are measured to need a role split; 11 are shared by definition,
   untested (table below).
2. **What OPD can apply tomorrow.** Bern: 2,421 relinks, 48 fetches and 554 `begin_date` corrections, keyed on OPD
   ids, with a dry-run SQL plan. Beyond Bern: one list per parliament from 50 model-free source adapters.
3. **Census.** The registered census counts **16,749** of 91,268 interventions with a written government answer
   without answer text attached in OPD. 2,177 of them are in OPD with text under a heading the census does not
   recognise, so **at most 14,572** lack answer text (13,150 written answers). Verified repairs are proposed for 9,720;
   after every counted repair **92.3%** of the 91,268 have answer text.
4. **What Apertus adds.** On parliaments nobody wrote rules for it finds answer dates the rules miss (P2: 24/29 vs
   2/29); as a closed-set pointer every value is a printed date with page and span. It is not more accurate than the
   same model asked freely with null allowed (P2, P6), and it still dates 4 of 33 (P2) and 5 of 34 (P6) answerless
   documents, so its values are review suggestions a person confirms.
5. **Not done.** Nothing runs at OPD yet (the relinks wait on OPD's hash choice); 5,007 written answers still need
   adapters; tables, annexes and images are not extracted; unattended (the *unattended bar*: a 95% lower bound of at
   least 0.80) only the type on whole affairs and the rules' answer date on parliaments with rules (P1: 135/154
   [81.5, 92]) qualify, not the answer date elsewhere; every gold label comes from LLM agents (no human labelled, by design).

Outside services: by default none beyond OPD's exports and the parliaments' own sites (fetched politely); review mode
adds one model endpoint the operator sets. **Which model:** evaluation used Apertus v1.5 70B weights served by Public AI
(inferred from the served fingerprint; the endpoint name says `8b`); the real 8B was run in-process on CPU on P1, P2
(52 documents), and its P6 run is still running.

**For OPD: three lists, one command.** Direct downloads on the evidence site (box "For OPD's data team"; source
`results/repair/`):
- `repair_BE_relink.tsv`: 2,421 Bern answers that are in OPD but unlinked, each checked against OPD's own copy (affair
  number, answer heading, decision date = OPD's answer event). `repair_BE_fetch.tsv`: 48 to fetch from the canton.
  `repair_BE_review.tsv`: 39 rows for a person.
- `repair_BE_begin_date.tsv`: 727 Bern `begin_date` values that are load timestamps (554 set from the affair's own
  submission event, 173 to review).
- `python -m gegenprobe.repair.apply_be --fetch --out DIR` turns them into a dry-run apply plan
  (`apply_BE_plan.sql.txt`): before and after state per row, guarded `UPDATE` statements as text; it changes nothing in
  OPD. Relinking changes a document's `hash` and file URL unless OPD keeps the old one (`--hash keep`).

OPD confirmed the Bern bug and its root cause, and that the relink list is the workaround until its fix ships
(correspondence, 10 Oct 2026; a published excerpt awaits OPD's consent).

**Beyond Bern: source adapters for 50 parliaments** (`results/repair/adapters/adapters_<BODY>.tsv`, `docs/adapters.md`;
27 of them yield counted rows). Verified repairs are proposed for **9,720 of the 16,749** (3,107 by the Bern lists, the
agenda join and Curia Vista; 6,613 adapter rows); **5,007** written answers still need adapters. 2,177 of the "missing"
answers are already in OPD with text, filed under the question's file (Zürich city alone: 1,417): the repair is a
category on the document (`tag_answer`), not a new document. A blind audit of 200 counted rows and 60 decoys (verdict-free
packets): Claude Opus judged 197/200 counted rows to be the executive's answer (Wilson 95.7% to 99.5%); an
LLM audit, not a human one.

**Census at a glance** (OPD exports of 6 Oct 2026; `results/census/corrected.json`; open dataset of all 91,268):
- All years: 91,268 interventions with a written government answer; the registered census counts **16,749 (18.4%)
  without answer text attached in OPD**. 2,177 are in OPD with text under a heading the census lexicon does not
  recognise, so **at most 14,572** lack it; 1,422 were answered orally, so **at most 13,150 of 89,846 written answers
  (14.6%)** lack it.
- 2024–25: the registered count is 1,855 (367 oral); 150 are in OPD under an unrecognised heading, so at most 1,338
  written answers lack text.
- Bern: 567 of 593 written answers from 2024–25 (96%) lack text, but 520 of them are in OPD unlinked (418 under an
  agenda item, 102 without a parent); OPD-confirmed linking bug, relink list of 2,459 (2,421 dates verified, 38 to
  review).
- Coverage gaps: 31 parliaments where OPD holds interventions but records almost no written answers (cantons SZ 1,316
  interventions / 0 answers, UR, GL, NW, GE, AI): OPD coverage, not unanswered questions.

## The 17 fields: does each mean the same thing, and where does it live?

*Class* (`results/census/comparability.json`, `data/schema/field_verdict_classes.json`): does the field mean the same
thing in every parliament? *Where it lives* (`results/census/matrix.json`, thresholds in `docs/census.md` §3):
parliaments where OPD metadata carries it · carries it for part of the affairs · only the PDF · not in OPD's data.

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

So 4 fields are in OPD's metadata almost everywhere and 13 partly or only in the PDF; no field lacks a source in a
fifth of the parliaments (5 would at a 10% threshold, `results/census/tier_sensitivity.json`). *Role split*: the
concept is shared, but one source label covers several roles that must be kept apart before parliaments can be
compared. Three further *concepts* are body-specific and are not fields: oral answers in question time (23.6% of
question-time answers are oral; v0.1 types them as a null reason), executive business that answers no member's
affair, and councils that publish only meeting documents (16 bodies, 8 with no affair at all; schema v0.1 marks
affairs derived from them `virtual` with `derived_from`, P4). For the eCH group: `docs/ech-onepager.md`.

## The seven tests, in registration order

Each froze code, prompts and θ by sha256 before any label was committed (`eval/prereg*/`).

| test | n | what it tests | registered result | note |
|---|---|---|---|---|
| P1 | 154 documents, parliaments with rules | answer date: rules vs Apertus | **partial**: H3 held; H1 null safety failed (7/90); H2 Branch B | rules alone 135/154, so no model by default |
| P2 | 62 documents, 15 parliaments without rules | rules transfer; pointer vs rules | **3 of 4 held**; H3 null safety failed (4/33) | pointer 24/29 answer dates, rules 2/29 |
| P3 | 29 whole affairs, 10 parliaments | 7 fields: metadata, rules, Apertus | **partial**: no field unattended; Apertus recall held, precision below | feasibility study (D3-5) |
| P3b | 36 fresh affairs, 9 parliaments | replication of P3 | **held**: replicated (S1, S2) | S2 lenient; type 35/36 unattended |
| P4 | 120 agenda items, 6 sittings | affairs rebuilt from minutes | **partial**: H2, H4 held; H1, H3 failed | recall 99/120, precision 99/99 |
| P5 | 40 fresh affairs, 10 parliaments | Q/A pairs, people, recommendation | **partial** tier (H1); H2, H4, H5 held; H3 no gain | *not yet* when parliaments are resampled; submitter by rules 12/40 |
| P6 | 68 fresh documents, 8 parliaments | answer-date reader v2 vs free prompting | **failed**: no hypothesis held | free prompt 62/68, v2 59/68 |

- **Default: rules, no model.** On P1 the frozen DE/FR/IT rules are right on 135/154 and pick a wrong printed date on
  4/154. On whole affairs (P3b) the unattended default wrote a wrong answer date for 4/35 affairs, 3 of them a Luzern
  rule that overrode OPD's correct date; the product path now keeps OPD's date in that case and flags the record.
- **Where Apertus earns its place (P2).** On the 15 unseen parliaments (29 answer dates, from 7 of them) Apertus finds
  24/29 answer dates, the rules 2/29. The latest printed date in each document also finds 22/29, but it dates 31 of the
  33 documents without an answer; Apertus dates 4. Its value is finding the printed date; on answerless documents it
  still dates some, so nulls need review. On 8 more unseen parliaments (P6), rules first and Apertus on what they leave
  open (cascade v2) find 31 of 34 answer dates, the rules alone 20; on all 68 documents that is 11 documents won, 5
  lost (p = 0.21), and a model-free cascade (rules, then the latest printed date on documents OPD types as answers)
  scores 55/68 against cascade v2's 60/68.
- **The pointer form does not beat free prompting on accuracy, and we say so** (P6, registered): reader v2 59/68, the
  same Apertus asked freely with null allowed 62/68 (1:4 discordant, p = 0.38); v1 56/68. What the closed set gives is
  a printed value with its page and span; the free prompt with null allowed also almost never invents a date (0, 1 and
  0 times on P1, P2 and P6).
- **Questions and answers, people, recommendation (P5).** Rules-only Q/A pairing reaches the *partial* tier with
  document-level intervals (precision 0.83, recall 0.67) and *not yet* when whole parliaments are resampled; rules
  beat paragraph order 116:5 and free generation 79:11 (the dev-fitted pairing pointer never fired). The submitter is a
  review field: rules 12/40, the pointer over printed names 24/40, free generation 34/40.
- **Gold labels checked by another vendor, and by time.** The labels come from blind Claude annotators;
  `Qwen-SEA-LION-v4-32B` (AI Singapore) relabelled P1, P2 and P6 blind: answer dates agree with κ 0.80 (P1), 0.87 (P2)
  and 0.86 (P6), and no registered decision changes; on P5 its labels are too noisy to confirm or overturn the verdict.
  Lock before label is shown by time, not only by commit order: all 74 annotator sessions started after GitHub received
  the LOCK and draw pushes and ended before it received the labels (`results/eval/annotation_sessions.json`).
- **Sovereign path, exploratory.** Apertus v1.5 8B (community 4-bit build) runs on one CPU machine, 180 s per document
  on 4 vCPUs. It finds 15 of 21 answer dates on the 52 P2 documents reachable from CI (the latest printed date: 14),
  but dates 25 of 90 answerless P1 documents (70B: 7), so a reviewer rejects more of its suggestions.
- **One real night** under systemd on a GitHub runner against OPD's live exports: 83 min, the Bern list reproduced on
  live data (2,459 relink + 49 fetch). It is not yet running at OPD; a two-night run of the Docker setup (Actions run
  38098822336) is running.

![Where the registered gap is](docs/figures/fig1_funnel.png)

**What the converter returns.** `python -m gegenprobe convert` gives each date and rule value with the page and
character span the rule matched, each metadata value with its OPD record, and a typed null that says why a value is
missing. An Apertus value is one of the dates printed in the document, by construction; code then locates its page and
span (`pointer.locate`: the occurrence nearest an answer anchor, else the first). Apertus's categorical suggestions
(type, addressed body, recommendation) are document-level review suggestions without a span.

**Glossary.** *Pointer*: Apertus chooses one of the dates printed in the document, or null; it cannot write a value of
its own. *Typed null*: an empty field that says why (not in the document, unlinked, scan, oral, ...). *Residue*: the
documents where the rules find nothing and stay silent. *Review mode*: Apertus runs on the residue and its choice
arrives as a suggestion with page and span for a person to accept. *Null margin (θ)*: how much more likely Apertus
finds "no answer date" than all printed dates together; above θ it says null. *Virtual affair*: an affair rebuilt from
an agenda item and its minutes, for councils whose business exists only as meeting documents.

## Quickstart

```bash
make run              # Docker, CPU, clean checkout: replays P1-P6, re-derives the rules arm, checks claims.tsv
make census-replay    # recompute census, link status and feasibility matrix from data/census only (host Python 3.11)
make test             # unit tests (pip install -e .[dev])
```

`make run` needs Docker; building the image fetches pinned packages, after which the network is optional (live steps,
such as re-deriving the rules arm from the source PDFs, report SKIP offline). The container runs as the
caller's uid, or uid 10001 when the caller is root, with a read-only root filesystem, a private `/tmp`, all capabilities
dropped and `no-new-privileges` (`Makefile`, target `run`). It exits non-zero on any failure and writes
`out/site/index.html`, the same evidence viewer as https://gegenprobe.mi11ion.io. It recomputes the census and asserts
it equal to `results/census/`; replays the Bern join and its triple check; runs sample documents through the converter
with the validator's checks; re-scores P1–P4 and P3b from the committed predictions and labels, re-runs the seven
registered hypothesis scripts (P1–P6, P5 and P6 included) and the 8B analysis and verifies the seven LOCK files
(locally 26/26 replay tests pass); re-derives the P1 rules arm from the
source PDFs (fetched by sha256) and recomputes P1 and P2 Apertus decisions from the committed model cache (cache only,
no model call) within a time budget; and runs the claims check: each number listed in `claims.tsv` is recomputed from
its results file, and the step fails if a document prints anything else. Locally the rules arm re-derives 154/154 and
the Apertus decisions 154/154 (P1) and 62/62 (P2) identically. The latest CI run on main whose jobs all passed (run
38076870082, commit 15dd077, `results/ci/docker_make_run_38076870082.json`) ran `make run` in this hardened container
before P5 and P6 joined the replay: 22/22 replay tests (P1–P4, P3b, the 8B analysis, 5 locks), 141 of 154 rules re-derivations within the budget, all identical;
recomputed Apertus decisions matched 129/129 (P1; 25 prompts missed the cache because the image's poppler 22.12
extracts slightly different text) and 49/49 (P2; 8 hosts unreachable from CI; reported as WARN, never as PASS); 984
claims, 0 failing. Later commits add documentation and claims rows; each push re-runs the same job. Optional: `LLM_NAME` / `LLM_BASE_URL` / `LLM_API_KEY` for a live Apertus slice. `make run GGUF=1` loads Apertus v1.5 8B
(GGUF Q4_K_M, sha256-pinned) in-process on CPU and scores a few demo documents with the frozen scorer; the 8B numbers
below come from CI runs with the fast scorer and are replayed, not recomputed, by `make run`.

## Convert your own PDFs

Guide, field glossary and null reasons in plain words: `docs/convert-your-own.md`.

```bash
python -m gegenprobe convert <pdf-or-url> --body SG                # one document, no model: JSON with page, span, rule
python -m gegenprobe convert --batch inputs.tsv --out out.jsonl --queue review.jsonl   # many, resumable
python -m gegenprobe convert answer.pdf --body SG --anchors docs/examples/anchors_SG.json --explain
```

The converter tells you when it is outside its knowledge. For a parliament the frozen rules were never written on, it
warns, sets `needs_review: true` and gives the null its own reason, `no_rules_for_body`, instead of a silent null. When
a document says more than the rule matched ("accepter partiellement la motion"), the value becomes `partial` and the
quote includes the qualifier. A date printed right after the answer heading, in a layout no rule vouches for, moves to
the top of `candidates` for a person to confirm; it is never written into the field. `--queue-nulls` also sends a
rules-only null answer date on an answer document to review, with the printed dates as candidates. `--affair-type`
accepts the vocabulary keys, their DE/FR/IT/EN labels and OPD's type names; an unknown value is an error, not silently
ignored. `--anchors` adds your own per-parliament anchors without forking the rules: they run only after the frozen
rules, and each value they produce is marked `route: user_anchor`, with page and span (`docs/examples/anchors_SG.json`
fills the answer date on both St. Gallen layouts a trial user brought; `tests/test_overlay.py`). `--explain` lists every
rule and anchor tried and why each did not decide. robots.txt is read per RFC 9309: a disallowed path is never fetched,
a 4xx robots.txt means no restrictions, an unreadable one blocks the host for the run. Fetch failures are typed rows.
A batch re-run converts an input again when the anchors file or an option changed (an options hash per row), and
`--anchors-review` keeps values from your own, unmeasured anchors flagged. When a document has no answer heading but a
letter address to the parliament ("An den Kantonsrat", "Au Grand Conseil", …) with a place-date line under it, that
date is offered first among the candidates (`suggested_by_letter_line`), never written into the field. Spans index our
own pdftotext/tesseract text; `--opd-text` maps them onto OPD's stored text. Tables, annexes and images are not
extracted.

## What is in the repository

| Deliverable (challenge) | Where |
|---|---|
| Representation model: versioned schema + controlled vocabularies | `src/gegenprobe/schema/schema_v0_1.py` (Pydantic, normative; every model exported from `gegenprobe.schema.public`), `data/schema/*.json`, JSON Schema with `$id` and version 0.1.0 `results/schema/*.schema.json`, `docs/schema.md`; mapping to Popolo / Akoma Ntoso / Parla-CLARIN / OParl in `docs/mapping.md`; one page for the eCH group: `docs/ech-onepager.md` |
| Converter: prompts + code, provenance per value | `src/gegenprobe/convert/` (lattice → rules → pointer → cascade, modes, overlay), prompts `src/prompts/{de,fr,it}/`, CLI + batch mode, `docs/converter.md` |
| Whole affairs (multi-field) | `src/gegenprobe/affair/` (metadata → rules → closed-set pointer per field), `docs/affair.md` |
| Questions and answers, people, recommendation, reasoning (`QAItem` filled) | `src/gegenprobe/qa/` (rules, then a closed-set pointer over printed candidates), `docs/qa.md` |
| Virtual affairs from agendas and minutes | `src/gegenprobe/virtual/` (`python -m gegenprobe.virtual derive …`), `docs/virtual-affairs.md` |
| Validator | `src/gegenprobe/validate/` (schema, span re-check, typed-null consistency, self-deletion and distractor harnesses) |
| Evidence: seven pre-registered evaluations | `eval/prereg/` (P1, held-out, seen parliaments), `eval/prereg2/` (P2, unseen parliaments), `eval/prereg3/` (P3, whole affairs), `eval/prereg4/` (P4, virtual affairs), `eval/prereg5/` (P3b, held-out replication of whole affairs), `eval/prereg6/` (P5, Q/A pairs), `eval/prereg7/` (P6, answer-date reader v2), each with its `DEVIATIONS*.md`; gold sets `data/gold*/` with raw annotations, `docs/gold_protocol.md` |
| Cross-parliament question | answer rates and answer times per parliament: `results/census/question.json`, site → Parliaments (per intervention type, CSV) |
| Research dataset | `results/census/interventions.tsv.gz`: 91,268 interventions × 23 columns with date-trust tiers and source links (CDLA-Permissive-2.0) |
| Census, feasibility matrix, comparability, data-quality findings with OPD's response | `src/gegenprobe/census/`, `results/census/`, `docs/census.md` |
| Repair lists keyed on OPD ids, apply plan | `results/repair/repair_BE*.tsv`, `results/repair/apply_be/`, `docs/repair.md`, `docs/runbook.md` |
| Source adapters for 50 parliaments, audits (blind audit v3: `audit3/`), robots.txt incident | `src/gegenprobe/repair/adapters/`, `results/repair/adapters/` (`adapters_<BODY>.tsv`, `adapters_summary.json`, `tiers.json`, `canary.json`, `audit/`, `audit3/`), `results/repair/MANIFEST.json`, `docs/adapters.md`, `docs/incidents.md` |
| Nightly job (systemd timer + container, alerts), one real night | `src/gegenprobe/monitor/`, `deploy/nightly/`, `docs/nightly.md`, `results/monitor/night_real_38062530586/` |

## Schema v0.1 and where values live

Schema v0.1 adds date roles, typed nulls and `QAItem` (question *n* paired with the answer to question *n*; filled with
spans by `src/gegenprobe/qa/`, tested in P5); the 17-field verdict is the table at the top. The Pydantic models are
normative; the exported JSON Schema for OPD's workbench cannot express the cross-field rules (a rule value must carry
page and span), so validate with the models. Where OPD metadata carries a field, it mostly agrees with print (P3: type
17/18, submitter 23/28, submission date 15/21; affair numbers 21/29, format differences). In figure 2 an orange cell
means the value is *not in OPD's data* for that parliament (neither metadata nor a document; the parliament may still
publish it), not a different concept.

![Feasibility matrix](docs/figures/fig2_matrix.png)

## The cross-parliamentary result: where answers go missing

The census streams OPD's exports once and gives every in-scope affair an answer-link status (`attached | agenda |
parentless | absent | image_only | oral`). Of 91,268 interventions whose events record a written government answer,
16,749 (18.4%) have no answer text attached in OPD (the registered count; 2,177 of them are in OPD with text under a
heading the census lexicon does not recognise, so at most 14,572 lack it). 1,422 of them were answered orally in the sitting (1,016 Valais oral-answer
stubs, 406 question-time answers; Graubünden's *Fragestunde* accounts for 367 of those), so no written text is expected.
Subtracting them leaves at most 13,150 written answers without answer text on their intervention (14.6% of the
89,846 answered in writing). Each is typed by cause: filed under an agenda item, stored without a parent, scanned without text, or
not in OPD at all. Answer times are not one quantity across parliaments, because OPD's "answer" date has different
roles: the median is 112 days where it is the verified decision date (Bern, Ticino), 79 where it falls on a
government's weekly sitting, 62 for mixed and 39 for diffuse, publication-like dates, and in 7 parliaments the
"answer" is the submission date (`results/census/answer_days_by_trust.json`). The evidence site compares answer times within one
intervention type (median and IQR per type; not a league table, since procedures differ), shows 31 parliaments whose
answers OPD barely covers (among the cantons SZ, UR, GL, AI, NW and GE) as a coverage-gap status rather than as
unanswered questions, and filters to cantons. Cantons are named by their official name in the language of their
majority (Ticino, Vaud, Genève, Valais, Fribourg; Graubünden, Bern, Luzern), cities and communes by OPD's name.

## Repair lists for OPD (`docs/repair.md`, `docs/runbook.md`)

- **Bern.** Of the 3,532 answers the canton publishes, OPD attaches 229 (6.5%) to their affair; 3,394 (96.1%) are
  linkable within OPD without any model (229 attached, 527 under an agenda item, 2,638 parentless documents carrying
  the canton's document id). Every candidate was checked against OPD's own copy of the document: affair number and
  answer heading 2,459/2,459; decision date equal to OPD's answer event 2,332 with the registered parser and 2,421
  [97.9, 98.9] with a second parser written after the registered run. On the pre-registered sample of 40 the date
  check was 36/40: three misses were our parser on 2020–21 headers, one a typo in the canton's own PDF. The other 179
  parentless answers are not missing (155 affairs already have the text, 24 have no written-answer event). All Bern
  numbers are reconciled in one table (site `#bern-numbers`, `results/repair/be_reconcile.json`).
- **Downloads.** All four Bern lists, the dry-run apply plan and the JSON Schemas are direct downloads on the evidence
  site (https://gegenprobe.mi11ion.io/downloads/repair_BE_relink.tsv etc.; box "For OPD's data team"), next to the
  repository link.
- **Counts per file.** 2,459 relink candidates = 2,421 in `repair_BE_relink.tsv` (all checks pass) + 38 in review;
  49 fetch candidates = 48 in `repair_BE_fetch.tsv` + 1 in review; `repair_BE_review.tsv` holds those 39. Apply the
  relinks first, as a protected override or after OPD's staging fix, then the fetches; review rows need a person.
- **Applying them.** `python -m gegenprobe.repair.apply_be --fetch --out DIR` reads today's `docs_BE` export and writes
  an apply plan: per row the before-state (current parent, `hash`, file URL), the after-state, and guarded `UPDATE`
  statements as text; it changes nothing in OPD. **A note for OPD:** the document `hash` is sha256(body_key +
  parent_type + url) (all 49,810 rows of the 10 Oct export follow it), and all 2,421 verified relink documents are
  stored as `parent_type = agenda`, so relinking changes each one's identifier and its `files.openparldata.ch/doc` URL
  unless OPD keeps the old one (`--hash keep`); the plan lists both values. `python -m gegenprobe.repair.acceptance
  --fetch --out DIR` counts how many relinks OPD has attached and can gate a deployment.
- **Bern `begin_date`.** 727 affairs carry a load timestamp: 557 on 2024-10-28 and 170 from later loads (column
  `opd_group`), the two groups OPD described; 554 get the date of their own "Eingereicht" event, 173
  go to review (`repair_BE_begin_date.tsv`).
- **Coverage.** Before the source adapters, deterministic routes (Bern relinks and fetches, agenda joins, federal Curia
  Vista) proposed repairs for 3,107 of the 16,749 without answer text; with them, 9,720 (next bullet). The retype list holds 1,008 Valais answers, confirmed by the exact text
  rule, that were given orally and filed as a stub: they are retyped as oral, not searched for (the length proxy finds
  1,016 such stubs; `results/census/vs_reconcile.json`). For 1,350 affairs whose answer OPD holds only as an image, a probe ran German+French+Italian OCR on 15
  image-only answers: all 15/15 gave text passing our usability check (≥ 200 characters, an answer heading, a parseable
  date), a coarse check that an English-only model also passes; re-taking a text version is cheaper where the parliament
  publishes one. 10,800 written answers had no answer document anywhere in OPD (406 more are oral question
  time).
- **Source adapters for 50 parliaments** (`src/gegenprobe/repair/adapters/`, `docs/adapters.md`; model-free). Routes of
  their own for the parliaments with the most missing answers (Zürich canton and city, St. Gallen, Ticino, Neuchâtel,
  Jura, Valais, Solothurn, Luzern, Aarau) and a reader of OPD's own documents for every other parliament verify 6,613
  more answers: 5,793 of the 10,800 without an answer document and 820 of the 1,350 image-only ones. Each is checked by
  affair number or title, the parliament's answer formula and a date check, and typed filters reject documents that
  only look like answers (deadline extensions, commission reports, minutes, the member's own text, another affair).
  Verification tiers: 5,161 whose own date equals an OPD event; 1,056 where a printed date equals an OPD answer
  event and the document's own date, if read, lies within 30 days of one (rows more than 30 days off go to review);
  396 within the parliament's documented window (at most 15 days in Zürich city, 120 in Valais). Listed separately and **not counted**: 282 Jura answers that match by
  identity and wording only (OPD's Jura answer events carry no date), and 917 rows that wait for a person.
  **Verified repairs are proposed for 9,720 of the 16,749; 5,007 written answers still need adapters.**
  2,177 of the answers the census counts as missing are already in OPD with text, filed under the question's file and
  worded in a way our frozen census lexicon does not list (Zürich city alone: 1,417, "Der Stadtrat beantwortet die
  Anfrage wie folgt"): the repair is a category on the document (`tag_answer`), not a new document. The registered
  census number itself is unchanged: it is an upper bound under a frozen lexicon (at most 14,572 lack text).
- **Audits of the adapter rows.** A design audit of 796 rows (Claude annotator) found the document types the checks
  could not tell from an answer: 34 non-answers among 511 verified rows. The filters written from it catch all 34 and
  remove none of the sample's 713 answers (a design-sample check, not a precision estimate). **Blind audit v3**
  (`results/repair/adapters/audit3/`, prompt `PROMPT.md`): 200 counted rows, stratified by tier and route, and 60
  decoys from the review and failed lists, shuffled into packets that carry no outcome, reason or proposed action; the
  hash of the key was committed before judging. Claude Opus judged **197/200** counted rows to be the executive's
  answer (Wilson 95.7% to 99.5%; a plain proportion over a stratified sample), and the date wrong or unsupported on 15.
  It rejected 60% of the failed decoys but only 1.5% of the counted rows, and called 77% of the review decoys answers:
  the pipeline errs on the side of review. A second auditor from another vendor, Qwen-SEA-LION, accepted 200/200 but
  was lenient on decoys; the two agree on 252/260. Both auditors are LLMs; no person audited.
- **A compliance bug we found and disclosed ourselves** (`docs/incidents.md`, `results/compliance/`). Our network
  layer checked robots.txt with Python's `urllib.robotparser`, which applies the first matching rule; RFC 9309
  requires the longest. www4.ti.ch (Canton Ticino) lists `Allow: /` before its `Disallow` lines, so between 9 and 11
  Oct 2026 the project requested 147 distinct URLs on paths it disallows, 133 of them downloads, mostly by the gold-set
  samplers that fetched the parliament's URL OPD records; CI runs repeated at most 6,655 requests before the fix. An
  audit of all 14,152 URLs the project fetched found no other host affected. Since 11 Oct one RFC 9309 matcher
  (`src/gegenprobe/robots9309.py`) judges every fetch, and every fetch path requests a mapped URL from OPD's own copy
  on files.openparldata.ch instead (`data/compliance/mirror_urls.json`); 126 of the 130 evaluation documents are
  byte-identical to OPD's copy, so a re-derivation from OPD gives the same text. Local copies that could not be shown
  identical were deleted.

![Bern before and after](docs/figures/fig3_be_before_after.png)

## Evaluation: seven pre-registrations

**Locks.** Every test froze code, prompts and θ by sha256 before any label was committed: the LOCK commit precedes the
commit adding its labels by 6 min 0 s (P1), 2 min 28 s (P2), 3 min 37 s (P3) and 4 min 3 s (P4) by commit date
(`results/eval/posthoc_r3_gold_oracle.json`), an order GitHub's clock confirms
(`results/eval/lock_server_times_all.json`; rewritten SHAs in `docs/commit-map.md`); P3b's LOCK5 (commit 43a9012), P5's
LOCK6 (db339eb) and P6's LOCK7 (dfd1e72) precede their draws and labels. **Session times, not only commit order:** the
annotator agents' own transcripts date every labelling session. Across 10 label sets (P1 to P6, the P4 transfer cell,
P5 dev and DEV2), 74 annotator sessions wrote 996 label files, and all 996 carry a write time inside their own session.
In every set the first session started after GitHub received the push of the LOCK (and of the draw, where it is a
separate commit), and the last session ended before GitHub received the label commit: the P6 annotators started 26 s
after the draw was pushed and finished 10 s before the labels were pushed; for P5 the gap after the draw was 7 s; for
P1 the gap after the LOCK was 95 s. The short gaps are real: each set was split over 2 to 18 parallel sessions lasting
20 s to 7 minutes (`results/eval/annotation_sessions.json`; the transcripts stay on the author's machine because they
contain the full document text). Pointer v2 (P6) was chosen by a rule written before the DEV2 labels, but its code was
committed after them (DEVIATIONS7 D1); C won DEV2 with 29 of 31 documents against 28 and 27, within noise, and LOCK7
froze it before the P6 draw. Post-hoc findings are logged per test
(`eval/prereg*/DEVIATIONS*.md`); the round-4 ones in one clause each: D9, the 8B scorer's gate record, cache key and θ
interval; D10, multiplicity, the lenient metric and the served build; D11, three P1 gold dates before OPD's submission
date, all genuine; D2-6, P2 per parliament on all documents and the 8B on P2; D5-2, a Luzern rule that replaced
correct OPD answer dates in P3b. Round 5: D12, P1 is held out by protocol, not by commit order (below); D13, the
times in `eval/gold/SEEDS.md` were wrong (corrected there); D14 and D2-7, the annotator from another vendor; a D7
addendum gives the annotation timing from local file times (about two minutes per set, 16 parallel agents).

**Gold labels, checked by another vendor.** No human labelled or adjudicated a gold value, by design. Two blind agent
annotators (Claude Opus and Sonnet) label each document, a third breaks ties (in P2 with the order randomised), quotes
are verified by code, and the raw A1, A2 and A3 files are committed for every set, P6 and DEV2 included
(`data/p6/annotations/`), so every label and every κ recomputes; the committed
labels are the record (rerunning the agents need not reproduce them). Because all three are Claude models, an annotator
from another vendor and model family, `Qwen-SEA-LION-v4-32B-IT` (AI Singapore, Qwen family; neither Anthropic nor
Apertus), labelled all 216 P1 and P2 documents blind from the same guide and the same text (post hoc, D14/D2-7; 216
calls, USD 0.14; `results/eval/posthoc_r5_independent_gold.json`). Answer present: P1 146/154 (κ 0.89), P2 60/62
(κ 0.93). Exact answer date: P1 134/154 (κ 0.80), P2 56/62 (κ 0.87); where both name a date, Qwen's is the gold date or
one of its listed alternatives in 54/54 P1 documents, and the gold date in 25/29 P2 documents. No registered decision
changes under either reading, only the documents where both vendors agree or Qwen's labels wherever they differ: P2-H2
is 22 vs 0 under the gold, 21 vs 0 and 23 vs 1; the P1 cascade is exact on 139/154, 127/134 and 133/154. Limits: Qwen
reads the same extracted text, so OCR errors stay invisible to both, and this is a check across model families, not a
human audit; the 21 P1 and 8 P2 disagreements are listed with both values in the JSON and were not adjudicated. P1-H1
(null safety) fails as registered (7/90) and rests on contested documents: 6 of the 7 values fall on documents OPD
types as reports (council reports that quote the executive's decision). Without the 24 reports it is 1/72 (upper bound
7.5%), on the documents where both vendors agree 2/84, under Sonnet's labels 5/88, under Qwen's 11/94.

**Non-LLM checks.** Of 64 P1 answer dates, 44 can be checked against OPD's written-answer events or publisher titles;
37 of 44 agree, and 5 of the other 7 are 1–5 days apart (decision vs dispatch or publication); Ticino titles that name
the decision date match 20/20. P3 answer dates match OPD 18/21. The three P1 gold dates that precede OPD's submission
date were audited: 3 checked, 0 gold errors (one is a year typo in the source, labelled as printed as the protocol
requires; D11). P2 is thinner: 6 of its 29 dates have an exact external source (6/6 agree), and 19/29 face at least one
non-LLM bound, none contradicted (`results/eval/posthoc_r4_gold_oracle_p2.json`, D2-6).

**Statistics.** Across the 9 registered confirmatory tests of P1–P4 and P3b (post hoc, D10), all 4 conclusions that
held survive a Holm correction (P2-H1 7.2 × 10⁻⁹, P2-H2 3.8 × 10⁻⁶, P3-H3a 0.01, P3b-S1 0.016), and Benjamini–Hochberg
gives the same split; the 8B tests are exploratory and outside the family. The registered lenient metric (a second
printed date the annotators listed as defensible also counts) raises each arm by 0–5 documents and changes no registered
decision (P1 rules 136/154, cascade 140/154; P2 pointer 56/62). Documents from the same parliament are not
independent, so we also resample whole parliaments (percentile bootstrap, 10,000 resamples, post hoc;
`results/eval/posthoc_r6_cluster.json`); the intervals are given with P2, P5 and P6 below.

**Which Apertus.** Evaluation used Apertus v1.5 70B weights served by Public AI (inferred from the served fingerprint;
the endpoint name says `8b`); the real 8B was run in-process on CPU on P1, P2 (52 documents), and its P6 run is still
running. Apertus numbers not marked 8B come from the 70B weights, which Public AI serves under the name
`swiss-ai/apertus-v1.5-8b`. That is inferred, not documented by Public AI: the served fingerprint (`tp8-pp2-…`, a
tensor-parallel 8 × pipeline-parallel 2 deployment) and the behaviour (report §3: 760/792 greedy outputs
byte-identical to the `-70b` name; MMLU 84.4% vs 70.8% for the v1 8B route) point to the 70B. We use that name because
the `-70b` name answers prefilled requests with a different model; the response's `model` field is checked on every
call. Re-derived from the response cache, every P1 (1,542) and P2 (351) answer comes from one served build
(`results/eval/served_models.json`). The 8B is `swiss-ai/Apertus-v1.5-8B` (Apache-2.0) as a community text-only export
(`andreasmartin/apertus-v1.5-8b-text`) quantised to 4 bits by a community member
(`Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF`, file `apertus-v1.5-8b-text-q4_k_m.gguf`, sha256 `a037df8d…f299`, pinned in
`src/gegenprobe/llm.py` `GGUF_PINS`); it is not an official Swiss AI release, and an operator can re-quantise from the
official weights (`docs/runbook.md` "Supply chain"). It ran with llama.cpp on a 4-vCPU CI runner with its own θ = 16.73
from 97 dev documents (pre-registered exploratory arms, DEVIATIONS D2/D3), on the P1 arms and, after the round-4
review, on P2 (D2-6).

**Which size to deploy.** `rules_only` (no model) unattended, the default. For review suggestions, two options:
- **The 8B is the measured sovereign option** (exploratory): one CPU machine, no document text leaves it. On the 52
  reachable P2 documents it finds nearly as many answer dates as the 70B (15 vs 16 of 21) but proposes a date for 11
  of 31 answerless documents (70B: 4), and on P1's residue its suggestions are right 7/34 times (70B: 9/16, p = 0.021), so a reviewer rejects
  far more of them. Cost: 180 s per document on 4 vCPUs.
- **The 70B is the accuracy option**, on infrastructure the operator chooses: all positive Apertus evidence on unseen
  parliaments is the 70B. Its bf16 weights alone are about 140 GB (e.g. two 80 GB GPUs; arithmetic, not measured by
  us); the Public AI service we evaluated on may route outside Switzerland.

**P1 — 154 held-out documents from parliaments the rules were written for** (DE/FR/IT × canton/commune + Ticino scans;
64 with an answer date, 90 without; always-null scores 90/154). Unit: one document's answer date, strict. Held out by
protocol (seeded draw; labels after the lock). The rules and the sample entered in one commit (`da26116`), so commit
order does not prove the rules predate the draw (D12); P2 is the clean out-of-sample test of the rules.

| arm | exact [95% CI] | dates found | wrong printed date | fabricated | values on the 90 answerless |
|---|---|---|---|---|---|
| **rules only (default mode)** | **135/154 [81.5, 92]** | 47/64 | 4 | 0 | 2 |
| Apertus pointer on every document | 130/154 [77.9, 89.3] | 46/64 | 16 | 0 | 6 |
| rules + Apertus suggestions, all accepted | 139/154 [84.6, 94] | 56/64 | 11 | 0 | 7 |
| 8B pointer on every document (CPU, exploratory) | 112/154 [65.2, 79.1] | 50/64 | 37 | 0 | 28 |
| 8B rules + suggestions, all accepted (CPU, exploratory) | 119/154 [70, 83.2] | 54/64 | 31 | 0 | 25 |
| naive free generation, null-allowed | 134/154 [80.8, 91.4] | 47/64 | 11 | 0 | 3 |
| ↳ null-allowed, re-parsed (post hoc, D5) | 133/154 [80.1, 90.9] | 47/64 | 13 | 0 | 4 |
| naive free generation, plain prompt | 98/154 [55.8, 70.8] | 47/64 | 23 | 24 | 39 |
| ↳ plain, re-parsed (post hoc, D5) | 103/154 [59.1, 73.8] | 54/64 | 26 | 24 | 41 |

**The 8B rows** (`python -m eval.gguf_8b_analysis` → `results/eval/gguf_8b_analysis.json`): its rules arm is the same
(154/154 identical decisions), and every value it returns is a printed date (0 fabricated of 85 cascade values). Against
the 70B, document by document: pointer 10 right only on the 8B vs 28 only on the 70B (McNemar p = 0.0051), rules +
suggestions 2 vs 22 (p = 3.6 × 10⁻⁵); against its own rules arm the 8B cascade loses 7 vs 23 (p = 0.0052). Its margin
still separates answered from answerless documents (AUROC 0.854 vs 0.969), but θ = 16.73 lets through many wrong
printed dates on answerless documents, mostly German communes and Ticino scans. The registered P1 hypotheses
(`eval/hypotheses.py`, unchanged) on the 8B: H1 fails (25/90), Branch B (FR+IT+scans: rules alone right on 10, the
cascade alone on 2, p = 0.039; 10 vs 5 under the lenient metric), H3 passes, H4 triggers (7 of 9). The duplicated
documents of the sharded run (5) gave identical decisions, and a second CI run on the same inputs reproduced θ exactly
(a determinism check, not an independent replication; θ sits in a 0.105-nat gap between two dev margins, and moving it
0.5 nats flips 1 of 97 dev decisions). **Scorer record** (D9): the fast 8B scorer failed its parity gate against the
frozen scorer twice (57.8 nats, a bug; then 4.47 nats on a 3-token date continuation); a replacement gate, written
after those failures and before any 8B arm ran, compared both with bf16 on 30 multi-token verdict cells, not dates,
and passed (29/30 each); the pre-registered implementation check passed (58/60 decisions vs bf16) and the preset
self-check failed (10/12 decisions, 3.16 nats). The 8B numbers are fast-scorer numbers, with θ
fitted by the same scorer. The frozen naive scorer could not read answers written as DD-MM-YYYY and counted them as
"no date" (D5 / D2-4; registered numbers unchanged); the re-parsed rows re-score the stored generations with the frozen
scorer.

Outcomes as registered: null safety failed (7/90 answerless documents get a value; 95% upper bound 15.2% against 10%).
H2 gave Branch B: the registered consequence keeps Apertus only where it measurably adds null safety, and it adds none
(the cascade dates 7/90 answerless documents, the rules 2/90). We removed Apertus from the unattended path (default
`rules_only`) and kept it, as a departure logged in D6, as an opt-in review suggestion that a person confirms; P2 then
tested that use on unseen parliaments. The null margin separates answered from answerless documents (AUROC 0.969 on all
documents, 0.966 on the registered length-matched set); 3 of 8 Apertus-decided French/Italian values are wrong. A
one-line baseline (latest printed date, only on documents OPD types as answers) is exact on 131/154.

**P2 — 62 documents from 15 parliaments absent from every dev and held-out set** (29 with an answer date, from 7 of the
15: VD 8, NW 6, Bellinzona 5, OW 4, Vernier 3, SZ 2, Schlieren 1; 33 without; always-null scores 33/62; two Claude
annotators agreed on all 62 P2 dates (κ 1.0); an annotator from another vendor agrees on 56/62 (κ 0.87)). Wilson 95%
intervals in brackets (`results/eval2/posthoc_r5_p2_table.json`):

| arm | exact [95% CI] | dates found [95% CI] | wrong printed date | fabricated | values on the 33 answerless [95% CI] |
|---|---|---|---|---|---|
| rules only | 35/62 [44.1, 68.1] | **2/29** [1.9, 22] | 2 | 0 | 0 [0, 10.4] |
| **Apertus pointer** | **53/62 [74.7, 92.2]** | **24/29** [65.5, 92.4] | 8 | 0 | 4 [4.8, 27.3] |
| rules + Apertus suggestions | 51/62 [71, 89.8] | 22/29 [57.9, 87.8] | 10 | 0 | 4 [4.8, 27.3] |
| naive free generation, null-allowed | 52/62 [72.8, 91] | 22/29 [57.9, 87.8] | 7 | 1 | 3 [3.1, 23.6] |
| ↳ null-allowed, re-parsed (post hoc, D2-4) | 54/62 [76.6, 93.3] | 24/29 | 7 | 1 | 3 |
| naive free generation, plain prompt | 45/62 [60.4, 82.1] | 21/29 [54.3, 85.3] | 8 | 4 | 9 [15.1, 44.2] |
| ↳ plain, re-parsed (post hoc, D2-4) | 49/62 [67.4, 87.3] | 25/29 | 9 | 4 | 9 |
| *latest printed date, ungated (post hoc)* | *24/62 [27.6, 51.2]* | *22/29 [57.9, 87.8]* | *38* | *0* | *31 [80.4, 98.3]* |
| *latest printed date on documents OPD types as answers (post hoc)* | *44/62 [58.7, 80.8]* | *18/29 [44, 77.3]* | *13* | *0* | *7 [10.7, 37.8]* |

Outcomes: the rules collapse off their home layouts (dates found 47/64 → 2/29). **Per parliament** (post hoc, D2-1,
D2-6): on answered documents the pointer is ahead in 6, the rules in 0, 1 tie (sign test p = 0.031); on all 62
documents, counting a right null as a success, the pointer is ahead in 6, the rules in 2 (Fribourg city and 6266, whose
sampled documents carry no answer and the pointer dates some) and 7 tie (p = 0.29). The registered document-level test
(P2-H2): on the 29 answered documents 22 are right only with the pointer and 0 only with the rules
(McNemar p = 4.8 × 10⁻⁷; without Bellinzona, whose letterhead one rule happens to match, 17 vs 0, p = 1.5 × 10⁻⁵); on
all 62 it is 22 vs 4 (p = 5.3 × 10⁻⁴), the rules' nulls winning on 4 answerless documents the pointer dates.
Resampling the 15 parliaments, the accuracy gain over the rules is [-0.02, 0.54], so the gain sits in a few
parliaments; against the free prompt that may return null, the pointer is ahead on 2 documents and behind on 1, gain
[-0.04, 0.09]: no difference. **Against simple baselines** (post hoc): the latest
printed date in the document finds 22/29 answer dates, nearly as many as the pointer (on the answered documents 3 vs 1,
p = 0.63), but it dates 31 of the 33 answerless documents, where the pointer dates 4. Apertus's value is finding the
printed date; it still dates 4 answerless documents, so nulls need review. Against the latest date gated by OPD's document type (null on documents OPD types as member
texts), the pointer is right on 10 documents the baseline gets wrong and the baseline on 1 (p = 0.012), 6 parliaments
to 0 (p = 0.031; this comparison was chosen after the results, D2-5). Asked freely with a null-allowed prompt, Apertus
scores about the same as the pointer (52 vs 53 of 62; re-parsed 54); the pointer adds provenance by construction, not
accuracy. The margin separates the classes (AUROC 0.983); null safety failed again (4/33, upper bound 27.3%), so
Apertus's values remain review suggestions. θ = 0, registered in PREREG2 as a secondary with no decision attached,
scores 54/62 (53 at θ = 10.40). **Error profile** (`results/report/p2_numbers.json`): the rules are right on 35, pick a
wrong printed date on 2, date none of the answerless documents and miss 25 answer dates; the pointer is right on 53,
picks a wrong printed date on 4, dates 4 answerless documents and misses 1; rules + Apertus are right on 51, wrong
date 6, answerless 4, missed 1. The combination scores below the pointer alone because Apertus is asked only where the
rules abstain: on 2 documents a rule (`rrb_vom`) fired with a wrong printed date.

**The 8B on P2** (post hoc run of the registered exploratory arms, D2-6; `python -m report.p2_8b` →
`results/eval2/p2_8b_analysis.json`). The hosts of 10 documents were unreachable from the CI runners, all 8 Vaud answers
among them, so 52 documents with 21 answer dates were scored; the 70B and the baselines are shown on the same 52.

| on the 52 reachable documents | exact | dates found | values on the 31 answerless | fabricated |
|---|---|---|---|---|
| rules only | 33/52 | 2/21 | 0 | 0 |
| 8B pointer | 35/52 | 15/21 | 11 | 0 |
| 8B rules + suggestions | 33/52 | 13/21 | 11 | 0 |
| 70B pointer | 43/52 | 16/21 | 4 | 0 |
| 70B rules + suggestions | 41/52 | 14/21 | 4 | 0 |
| *latest printed date, ungated* | *16/52* | *14/21* | *29* | *0* |
| *latest printed date on answer-typed documents* | *35/52* | *10/21* | *6* | *0* |

This is an exploratory arm, outside the registered family. On these 52 documents (Vaud's 8 answers missing) the 8B
finds 15 of 21 answer dates [50, 86.2], the rules 2 and the ungated latest printed date 14 (on the answered documents
4 vs 3). It ran on the fast scorer, which failed both registered parity gates and was admitted through a replacement
gate (DEVIATIONS D2, D9). The registered P2-H2 script on these rows gives 13 vs 0 (p = 2.4 × 10⁻⁴). The 8B finds the
dates; what it lacks is restraint: on all 52 documents it is 13 vs 11
against the rules, 10 vs 10 against the latest-date baseline (the 70B: 9 vs 1, p = 0.021), and 2 vs 10 against the 70B
(p = 0.039, pointer and cascade alike).

**P3 — whole affairs: 29 affairs (58 PDFs) from 10 parliaments, 5 with rules and 5 without, DE/FR/IT.** A feasibility
study: the extractor, its prompts and the sample entered in one commit and P3 had no development set (D3-5); its labels
were committed after the lock. Arms: OPD metadata only (M), rules only (R), the default metadata + rules (C), and C plus
Apertus suggestions on the fields C leaves open (CA). Annotators agreed on at least 27/29 affairs on every field.

| field | M | R | **C (default)** | C + Apertus |
|---|---|---|---|---|
| type | 17/29 | 26/29 | **27/29** | 27/29 |
| affair number | 21/29 | 14/29 | **21/29** | 21/29 |
| submitter | 23/29 | 5/29 | **23/29** | 23/29 |
| submission date | 15/21 | 4/21 | **15/21** | 15/21 |
| answer date | 21/27 | 16/27 | **22/27** | **27/27** |
| addressed body (gold constant: a constant answer scores 28/28) | 0/28 | 4/28 | **4/28** | 23/28 |
| decision number (defect D3-1; post hoc C 5/17) | 0/17 | 5/17 | **0/17** | 0/17 |

Outcomes as registered: no field reaches the "unattended" bar (95% lower bound ≥ 0.80; type comes closest). Apertus
suggestions on the open fields are right for 25/32 of those that have a value and 25/34 of its suggestions are right,
but the addressed body, where every gold value is "executive", dominates that count: we withdraw it as evidence (D3-3).
Without it the evidence is thin, 6/8 found and 6/9 right; the case rests on the answer date (22/27 → 27/27). Set fields:
co-signatories (OPD metadata) precision 13/16, recall 13/29; related affairs (rules) precision 6/9, recall 6/14.
Details: `docs/affair.md`.

**P3b — pre-registered held-out replication of P3** (`eval/prereg5/`, LOCK5 at commit 43a9012 before the draw; 36 fresh
affairs from 9 parliaments, 36 of 40 because Locarno and its registered reserve Bellinzona yielded no usable affair,
DEVIATIONS5 D5-1; blind annotators agreed with κ ≥ 0.97 on every field, 1 field went to the tie-breaker; blindness
audit `results/eval5/annotation_audit.json`). The registered criteria: S1, Apertus's recall on the fields C leaves
open has a Wilson lower bound of at least 0.50; S2, each eligible field's accuracy under C is within or above P3's 95%
interval, with at most one field below. Both held, so the registered verdict is **replicated**. S2 is lenient: the one
field it allows below is here the answer date, the field the case for Apertus rests on. S1: Apertus on the open fields
finds 14/16 [64, 96.5]; S2: 4 of 5 eligible fields are within or above P3's CIs (number 18/29, type 35/36, submitter
30/36, submission date 30/34 above). The answer date is the field below (C 20/35; one of the 36 affairs has no answer):
the unattended default wrote a wrong answer date for 4/35 affairs (P1: 4/154 documents), and in 3 of them, all in
Luzern, the frozen rule `lu_antrag` read the submission date and replaced OPD's correct answer event (D5-2); with OPD's
date kept it would be 23/35, within P3's interval (post hoc). With Apertus it reaches 31/35, its 11 suggestions all
right (11/11). In the product path (not the scored evaluation), a post-processing guard keeps OPD's answer date when a
rule-read date equals the affair's submission date while OPD's answer event says otherwise, and flags the record. Post
hoc on the committed records it fires on 3 of 36 P3b affairs, all three in Luzern, and OPD's kept date matches the gold
label in all three; it fires on none of the 29 P3 affairs (`results/eval5/affair_post_check.json`). Precision on the open fields is 14/20,
below the bar, so the reviewer gate stays as in P3; the type now reaches the "extractable unattended" tier (35/36).
`python -m eval.gold5.hypotheses5 publicai_swiss-ai_apertus-v1.5-8b` →
`results/eval5/hypotheses_p3b__publicai_swiss-ai_apertus-v1.5-8b.json`.

**P4 — virtual affairs from minutes: 6 held-out sittings of Bulle's council, 120 agenda items.** Deterministic parsing
derives 99 items as virtual affairs: item precision 99/99, titles 99/99, type 91/99 (H2 holds), meeting date 6/6 (H4
holds), decision found for 49/63 items (46/63 correct), invented for 0/36. **H1 failed**: recall 99/120 (82.5%, sub-items
and unnumbered lines) below the registered bar. **H3 failed**: Apertus added 2 decisions (p = 0.5). Registered transfer
cell (exploratory, DEVIATIONS4 D4-4): 2 sittings of La Chaux-de-Fonds; items 9/9 and titles 9/9, but the rules find 0/9
decisions, and with Apertus 2/9 are found, 1 correct (the annotators agreed on 7/9 of these decisions, κ 0.4, so read
the decision cell as indicative). Details: `docs/virtual-affairs.md`.

**P5 — questions and answers, people, recommendation, reasoning: 40 fresh affairs from 10 parliaments**
(`eval/prereg6/`, LOCK6 at db339eb before the draw; `docs/qa.md`). `src/gegenprobe/qa/` fills schema v0.1's
`QAPair.items` (`QAItem`) with spans: for each numbered question the member's question and the passage of the answer
that replies to it, plus the submitter and co-signatories, the executive's recommendation (with the printed sentence as
evidence) and the span of the reasoning. Rules decide first; Apertus is used only as a closed-set pointer over
enumerated, printed candidates (which numbered question a paragraph answers, which sentence states the recommendation,
which printed name is the submitter) and never generates a value. The 40 affairs come from Basel-Landschaft,
Schaffhausen, Luzern city, Riehen, Wädenswil, Lausanne, Valais (French), Collombey-Muraz, Lugano and Graubünden
(Italian), none of them in the 38-affair development set; labels from blind Claude annotators (question count, answer
style and recommendation agreed in 40/40 affairs).
- **H1 (primary):** rules-only Q/A pairing: precision 118/143 = 0.83, recall 118/176 = 0.67. With document-level Wilson
  intervals the registered rule gives *partial* (precision lower bound 0.75 ≥ 0.70). When parliaments are resampled,
  precision is [0.66, 0.97] and recall [0.51, 0.81]: the precision lower bound falls below the 0.70 bar, so the same
  rule gives *not yet*. The result depends on which parliaments were drawn; French is the weak language (recall
  10/30), and Valais got 0/11. The "unattended" bar is missed either way.
- **H2:** the rules beat a paragraph-order baseline, 116:5 discordant answers (one-sided p = 7.8 × 10⁻²⁹).
- **H4:** rules-only pairing beats free generation, 79:11 (p = 3.9 × 10⁻¹⁴); the registered arm is rules + pointer,
  but the pointer never fired (H3), so this compares the rules with free generation. Free-generation Apertus with null
  allowed pairs 50/176 answers at precision 50/113, and 87 of its quoted values are in no document.
- **H5:** zero provenance failures: every span re-checks (517 rule values). **H3:** the dev-fitted pairing pointer
  abstained on all 36 residue answers (no measurable gain).
- **Verdict as registered: supported, at the partial tier** (document-level intervals; *not yet* under parliament
  resampling). Questions are found 167/187, the reasoning span matches
  37/40, the recommendation is right 34/40 by rules and 36/40 with the pointer.
- **What did not transfer, said plainly.** Rules-only submitter detection reached 36/38 on dev (in-sample) but 12/40 on
  P5. The pointer over printed names doubles it to 24/40, and free generation finds the submitter best (34/40); the
  submitter stays a review field. Post hoc, pairing transfers where answers number or repeat the questions (Riehen
  21/22, Wädenswil 20/24, Lugano 17/20) and fails where they do not (Valais 0/11).
- **Independent labels.** Qwen-SEA-LION's own labels pass the verbatim quote check in only 7/40 files and match the gold's
  answer spans in 96/176; with them as gold H1 would fall to *not yet* (65/116 recall, 65/105 precision). The check from
  another vendor is too noisy to confirm or to overturn the verdict; both readings are reported.

**P6 — answer-date reader v2: 68 fresh documents from 8 parliaments in no earlier set** (`eval/prereg7/`, LOCK7 at
dfd1e72 before the draw; 55 German, 13 French, no Italian document because no unseen Italian-language parliament was
reachable; 34 with an answer date, 34 without; blind annotators disagreed on 1). We tried to make the closed-set reader
clearly better than free prompting: v2 asks first whether an answer is present, then applies the gold guide's
decision-before-letter-date rule (guided generation kept only if the date is printed, else a choice by date role). On
P6 the frozen v2 decided 34 of 68 documents by guided generation, 31 by its presence gate (null) and 1 by its role
pick. It was chosen on a development set by a rule written before its labels; its code was committed after them
(DEVIATIONS7 D1).

| arm (strict) | exact | dates found | answerless dated | printed nowhere |
|---|---|---|---|---|
| free prompt, null allowed | **62/68** | 32/34 | 4/34 | 0 |
| free prompt with v2's instructions | 61/68 | 32/34 | 5/34 | 0 |
| rules, then v2 on what they leave open (cascade v2) | 60/68 | **31/34** | 5/34 | 0 |
| v2 | 59/68 | 30/34 | 5/34 | 0 |
| v1 pointer (θ = 10.40) | 56/68 | 29/34 | 7/34 | 0 |
| rules only | 54/68 | 20/34 | 0/34 | 0 |
| free prompt, plain | 54/68 | 33/34 | 13/34 | 5 |
| *latest printed date* | *29/68* | *27/34* | *32/34* | *0* |

**No registered hypothesis holds.** H1 (primary), v2 vs free prompting: 1:4 discordant documents (p = 0.38). H2: v2
dates 5/34 answerless documents (Wilson upper bound 30.1%, bar 15%). H3, v2 vs v1: 5:2 (p = 0.45). Registered
consequence: we drop any claim that the pointer form beats free prompting on accuracy, and v1 stays in the shipped
review mode. Secondary (registered): rules first, v2 on the residue vs rules alone on the answered documents, 11:0
(p = 0.001), 31/34 vs 20/34. On all 68 documents cascade v2 beats the rules on 11 and loses on 5 (p = 0.21; parliament
bootstrap of the gain [-0.11, 0.29]); the 11:0 holds on the 34 answered documents only. A model-free cascade (rules,
then the latest printed date on documents OPD types as answers) scores 55/68, cascade v2 60/68, the free prompt with
null allowed 62/68; cascade v2 is ahead of the model-free cascade on 5 documents and behind on 0 (p = 0.06). Qwen-SEA-LION relabelled P6 blind: presence κ 0.91, date κ 0.86; under its labels no
registered decision changes (v2 60/68, free prompt 61/68). Post hoc (`results/p6/posthoc7.json`): 4 of v2's 9 errors
are Interlaken answers its presence gate stopped (presence AUROC 0.93), 4 are Lyss documents the gold calls answerless.
The real 8B on P6 is still running (exploratory); no number is reported. **Non-LLM checks of the P6 gold**
(`results/eval/posthoc_r6_p6_oracle.json`): OPD's written-answer event matches the gold date on 10/10 documents that
have one; every gold quote occurs on its stated page and yields the gold date (34/34); OPD's document type agrees with
the answer/no-answer label on 58/68; 20/34 dated gold documents have at least one non-LLM date source.

**What the tests say together.** Apertus earns its place where layout varies and no rule exists, by finding what the
rules miss: on parliaments nobody wrote rules for (P2: 24/29 answer dates where the rules find 2/29, 22:4 documents on
all 62), for the answer date of whole affairs (P3: 22/27 → 27/27; P3b on fresh affairs: 20/35 → 31/35), and by
doubling submitter extraction over the rules (P5: 12/40 → 24/40). **It does not abstain reliably:** every registered
null-safety test failed (P1-H1, P2-H3, P6-H2), so a person reviews its nulls and values alike. On P1 the rules alone are as accurate as rules +
Apertus (registered H2: Branch B), so the default runs no model, and in Bulle's minutes (P4) Apertus added no
significant decisions. Neither means the rules are complete: P1 rule recall is 47/64 and P4 recall 99/120. **Accuracy
is not the pointer's argument:** the same Apertus asked freely with a null-allowed prompt is as accurate (P2: 54/62
re-parsed vs 53/62; discordant 1 vs 0, p = 1; both right on the same 24 of 29 answer dates; P6: 62 vs 59). **Provenance:** no arm
that picks from printed dates returned a date printed nowhere, on P1, P2 or P6. The fair comparator is the free prompt
that may return null: it did so 0, 1 and 0 times on P1, P2 and P6; the plain free prompt, which must always return a
date, did so 24, 4 and 5 times. So free prompting with a null option already almost never invents a date; the closed
set's advantage is that every value it returns is a printed date with a location (32/32 on P2), and a margin that orders
the review queue (suggestions in the strong band right 26/33, weak band 3/11, post hoc); the free prompt gives a
verbatim quote containing its date for 17/32 values. Writing the gold guide's decision-before-letter-date rule into the
prompt lifted every Apertus arm on P1 dev (in-sample; free prompt with null allowed 116/127 → 125/127).

![Scoreboards](docs/figures/fig5_scoreboard.png)

## Use of Apertus

- **Where:** only in the converter, as a closed-set pointer: forced choice over the dates (or enum labels, or OPD affair
  numbers) printed in the document, plus null; summed log-probabilities; null if the margin exceeds θ, fitted per build
  on dev documents and frozen (θ = 10.40 for the Public AI build). In `src/gegenprobe/qa/` the same form picks which
  numbered question an answer paragraph replies to, which printed sentence states the recommendation and which printed
  name is the submitter. Free generation is run only as the naive baseline.
- **What it adds, measured:** finding answer dates the rules miss on unseen parliaments (P2 22:4; P6 11:5 on all 68
  documents, p = 0.21) and doubling submitter detection over the rules (P5: 12/40 → 24/40; free generation 34/40), every
  value a printed one with its location. Not accuracy over the same model asked freely with null allowed (P2 and P6,
  registered), and not reliable abstention (P1-H1, P2-H3, P6-H2 failed).
- **Why a pointer:** asked freely when the government answered, Apertus writes a precise date for 15/15 (local 8B) and
  14/15 (70B) Bern interventions that have no answer, often the "Letzte Bearbeitung" footer (earlier spikes, cited); a
  null-allowed prompt fixes this on the 70B but not on the local 8B (still 14/15).
- **Modes:** `rules_only` (default, unattended, no model) and `review`: Apertus on the rules' residue, its value attached
  as a suggestion with page, span, margin and `needs_review: true` for OPD's existing manual-review step. Recommended
  for the 74 of 89 parliaments without rules (P2) and for the answer date of whole affairs (P3), with a reviewer gate.
  In operation, review mode refuses a served build θ was not fitted on: θ files record the server fingerprints of the
  fit, and the first response from another fingerprint stops the run (exit 3) before any suggestion from it is attached
  (`--allow-build-mismatch` continues and marks each suggestion). `docs/runbook.md` "Review mode in operation" gives the
  refit commands, the owner and the cost per 1,000 residue documents.
- **Builds:** θ does not transfer between builds, so each gets its own; the 70B results above carry θ = 10.40, the
  real 8B θ = 16.73 (dev AUROC 0.90; 97 dev documents, D3). The shipped review mode keeps the v1 reader: P6 found v2
  right on 5 documents v1 missed and wrong on 2 (p = 0.45), not enough to switch.

## Sovereignty, operations, cost

| Service (runtime) | What is sent | Needed for |
|---|---|---|
| files.openparldata.ch (exports) — or none, with `GP_EXPORTS_DIR` | GET only | census, nightly job |
| ogd.parl.apps.be.ch, rrgr-service.apps.be.ch (canton Bern) | GET; an affair number for the per-affair route | Bern repair |
| fedlex.data.admin.ch (SPARQL), www.fedlex.admin.ch (filestore) | a citation such as "BBl 2014 9657" | federal placeholder repair |
| document hosts listed in OPD | GET of a public PDF (and its robots.txt) | conversion, triple check |
| huggingface.co, only with `GP_GGUF=1` | GET of the pinned GGUF (once) | local 8B |
| the LLM endpoint the operator sets (`LLM_BASE_URL`) — or none | text of public parliamentary documents | review mode |
| the webhook or SMTP relay the operator sets (`GP_ALERT_*`) — or none | the night's alerts | nightly alerts |

ws.parlament.ch (Curia Vista) was queried once for the federal answers missing from the texts export; it is not part of
the running system. The evidence site is static files only and makes no third-party request (fonts self-hosted, SIL
OFL); its links to OPD and to the parliaments' own pages are followed only when clicked. With `GP_GGUF=1` no document
text leaves the machine; Public AI was used for development and evaluation only (it may route outside Switzerland).
OPD's API robots.txt disallows `/v1/`; we use the nightly bulk exports, which also makes every number reproducible
from a dated snapshot. Every request carries `GP_USER_AGENT`; a network night warns when it names no contact.

- **One real night** (`results/monitor/night_real_38062530586/`, `report/r4d_numbers.py`). The nightly job, installed
  with `deploy/nightly/install.sh --venv` on a GitHub-hosted 4-vCPU runner and started by systemd, ran one network
  night against OPD's live exports: 4,997 s wall (83 min), of which 1,892 s reading the exports (198 MB of single
  exports downloaded and stored, 6.2 GB of docs/texts exports streamed once and not stored; the streamed bytes
  reconstructed from the index the night read, `results/monitor/night_real_bytes.json`) and about 50 min (by
  subtraction) the one-time triple check of all 2,508 Bern rows a first night does; 28 min of CPU, peak memory
  2,078 MB. It raised no alert; as a first night it had no previous state, so the drop and trend alerts could not fire.
  From round 5 on, every night counts the bytes it streams (`run.json` `bytes`). On live data it reproduced the Bern list (2,459 relink, 49 fetch); the triple check passed
  2,468 rows and sent 40 to review (the committed lists of the 6 Oct snapshot: 2,421 + 48 pass, 39 to review). This
  tests the install and the job, not Swiss hosting; the job is not yet running at OPD.
- **Two consecutive nights in the recommended Docker setup** (`.github/workflows/nightly-real-docker.yml`): the workflow
  builds the image, installs the Docker unit with `install.sh`, runs night 1, waits for OPD's next export and runs
  night 2 on night 1's persisted state, so the index diff, the ledger, retries, outbox redelivery and the drop/trend
  alerts run against a real previous night. The first run (Actions run 38098822336) is running; no result is reported
  yet.
- **Designed to run inside OPD.** Pointed at the export directory (`GP_EXPORTS_DIR`), a night with no changed export
  files took 96.8 s wall on a copied snapshot with 0 bytes of export transfer (`results/monitor/run_local_exports.json`);
  a night that re-scans the files OPD changed over three days (80.6% of the docs bytes) is about 21.8 min (derived;
  a full re-scan is 25 min of one core; `results/monitor/night_cost.json`).
- **Hardened.** The container never runs as root: `make run` and the nightly unit run it as a non-root uid (10001 when
  the caller is root), read-only, with a private `/tmp`, all capabilities dropped and `no-new-privileges` (nightly:
  4 GB / 2 CPU ceiling). Untrusted PDFs are bounded: 50 MB per file, 300 s per pdftotext/tesseract call, 600 s per
  document; each hit is a typed failure row, never a hung night. A host whose robots.txt cannot be read is not fetched
  that night. Each event triggers one alert; a failed send keeps the alerts in an outbox, written atomically, and
  re-sends them the next night. An empty cache gives a message naming the command to run, not a traceback. CI runs
  `systemd-analyze verify` on the units and gates their `systemd-analyze security` exposure (venv unit ≤ 2.0, the
  job's own sandbox; Docker unit ≤ 5.0, which scores only the docker client, the job being confined by the container
  flags); the `systemd-units` job of CI run 38073556535 measured 1.2 and 3.9
  (`results/ci/systemd_security_38073556535.json`). CI pins
  every Action by commit SHA, checks gitleaks against its release sha256 and installs test dependencies with
  `--require-hashes`. At least 1.2 s between requests to one host.
- **Research dataset.** `results/census/interventions.tsv.gz`: one row for each of the 91,268 interventions, with
  submission and answer dates, where the answer text is, the OPD page and the parliament's own page, and a per-body
  date-trust tier, because OPD's "answer" date is verified as the government's decision date in two parliaments only:
  Bern (2,421 of 2,459 relinks carry the printed date) and Ticino (2,379 of 2,379 answers whose title names the decision
  date carry the same date in OPD). Elsewhere it ranges from a weekly cabinet sitting day to the submission date
  (`results/census/date_trust.json`).

**Cost** (`results/report/cost_end_to_end.json`; one core, no GPU). Per document, fetching politely, extracting and
checking takes about 2.1 s (50 federal documents), plus 6.9 s per page where OCR is needed; the rules themselves
process 480 documents per second, about 0.5 CPU-hours for all 902,754 documents in OPD's export. Re-deriving the 154
held-out documents from their PDFs (22 of them scans) took 727 s. Review mode adds the pointer on the rules' residue
(97/154 held-out documents): 3.5 calls and 5,905 billed prompt tokens per residue document on the 70B, USD 0.59 per
1,000 residue documents at Public AI's list price. The local 8B takes 180 s per document end to end on a 4-vCPU
machine (692 CPU-seconds, fetch and extraction included; 9.3 GB memory), about 50 machine-hours per 1,000 residue
documents; fitting its θ took 5.1 hours for 97 dev documents. Applied to OPD's whole export at the held-out residue
share (about 569k residue documents; an upper bound, since review mode runs only on new answer documents), the 8B would
take about 28,400 machine-hours on one such machine, the 70B about USD 336 at that list price. **At ten times OPD's
volume** the rules need about 5 CPU-hours and review mode about USD 3,357 at that list price; fetching and extracting
the documents (about 2.1 s each) dominates, not the rules.

## Maturity, limitations, coding assistants

- **Maturity per component:** census and Bern repair lists: ready for OPD to apply (lists keyed on OPD ids, reproduced in
  every `make run`, dry-run apply plan with before and after state); applying the relinks needs OPD's choice on the
  document `hash` (keep or change) or its staging fix, and the acceptance test counts 2,459 of 2,459 still unlinked on
  the 6 Oct snapshot. Nightly job: deployable prototype; CI runs `systemd-analyze verify` and the security gate on the
  units and three offline nights in the read-only container on fixture exports, and one real network night ran under
  systemd on a CI runner (83 min, Bern list reproduced on live data); a two-night Docker run (38098822336) is
  running; not yet running at OPD. Source-adapter lists: audited prototype (blind audit v3: 197/200 counted rows are
  the executive's answer, by an LLM auditor; the 917 review rows and the identity-only Jura rows need a person).
  Converter, rules-only mode: tested prototype (154 held-out + 62 unseen documents). Review mode with Apertus:
  feasibility study with a reviewer gate. Whole affairs: feasibility study, replicated on held-out affairs (P3b; only
  the type reaches the unattended bar). Q/A pairs, people, recommendation, reasoning: tested prototype at the partial
  tier (P5). Virtual affairs: feasibility study (one commune). Schema v0.1: draft for the eCH
  group (`docs/ech-onepager.md`).
- **Limitations:** answer dates are the field evaluated in depth, Q/A pairs on 40 affairs (P5); tables, annexes and
  images are not extracted; 5,007 missing written answers still need per-parliament adapters (some hosts are
  unreachable from our network, some answers exist only in session minutes); no federal documents in any gold set, and
  no Italian document in P6; the 8B was not run on P3/P3b/P5, on P2 only 52 of 62 documents were reachable from CI, and
  its P6 run is still running; gold labels and adapter audits are made by LLM agents and cross-checked by another
  vendor's model, not by a person; the P5 tier depends on the interval (*partial* per document, *not yet* when
  parliaments are resampled); spans index our own pdftotext/tesseract text, though `--opd-text` maps values
  onto OPD's stored text.
- **Coding assistants:** Claude Code agents (Anthropic) wrote most code, documentation and the gold labels; no human
  labelled or adjudicated a gold value, by design. Correctness rests on code-level checks — spike numbers reproduced
  cell-for-cell, regression fixtures, `claims.tsv`, the pre-registration locks, verbatim-quote checks, re-derivation
  from source PDFs — not on reading.

## Licences

Code: Apache-2.0 (`../LICENSE`). Report: CC-BY-4.0 (`docs/LICENSE-report.txt`). Data in `data/`: CDLA-Permissive-2.0
(`data/LICENSE`): identifiers, URLs, hashes, counts, labels and short quotations only — no full document texts and no
personal contact data.
