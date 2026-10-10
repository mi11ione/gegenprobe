# Gegenprobe: one schema and a converter for Swiss parliamentary answers

Track 2A · OpenParlData · Team 444 · **Evidence site: https://gegenprobe.mi11ion.io** · report: `technical_report.md`

**The two questions of the challenge.** *Is a common schema feasible?* Yes, with date roles and typed nulls: of 17
fields, 4 are feasible from metadata, 13 partial, 0 need a different concept. The concepts are shared; what differs is
where the value lives, the vocabulary, and which date "answer date" means (decided, dispatched, registered). *Can a
converter fill it from the documents?* Yes, for what the documents print. `python -m gegenprobe convert` returns each
value with the page and character span it was read from, or a typed null that says why there is none. By default it
runs frozen DE/FR/IT rules and no model; where no rule exists, Apertus points at one of the printed dates as a
suggestion that a person confirms. With one schema across 89 parliaments, a cross-parliamentary question becomes
answerable: **how many government answers are missing from the open record, and why?**

- **Census.** Of 91,268 interventions whose events record a written government answer, **16,749 (18.4%) have no answer
  text in OpenParlData (OPD)**. Each is typed by cause: filed under an agenda item, stored without a parent, scanned
  without text, answered orally in the sitting (1,008 Valais stubs, 406 question-time answers), or not in OPD at all.
- **Repair lists keyed on OPD ids.** In Bern the answers are in OPD but unlinked. OPD confirmed the bug and its root
  cause, and that our relink list is the workaround until its fix ships (correspondence, 10 Oct 2026). A second list
  fixes 727 Bern `begin_date` values that are load timestamps. Deterministic routes propose repairs for 3,107 of the
  16,749; 10,800 written answers need per-parliament source adapters, the next step.
- **A converter with provenance.** Every value it takes from a document is printed there, with page and character span;
  values from OPD metadata are marked `route: metadata` with their source. It can still pick the wrong printed date
  (rules: 4/154 held-out documents), so the default runs rules unattended and Apertus only suggests.
- **Where Apertus earns its place.** On 62 documents from 15 parliaments no rule was written for (their 29 answer dates
  come from 7 of them), Apertus finds 24/29 answer dates where the rules find 2/29. Over all 62 documents it is right on
  22 the rules get wrong and the rules on 4 (McNemar p = 5.3 × 10⁻⁴); against the strongest one-line baseline (latest
  printed date, type-gated) it wins 10 documents to 1 (p = 0.012) and 6 parliaments to 0 (p = 0.031). On whole affairs
  it completes the answer date (22/27 → 27/27).
- **Virtual affairs for communes that publish only minutes** (a point OPD named in the challenge). From 6 held-out
  sittings of Bulle's council, rules derive 99 affairs with item precision 99/99, every title right, the decision found
  for 49/63 items and invented for none of 36. Two registered hypotheses failed: recall 99/120 stayed below the bar (H1),
  and Apertus added no significant decisions (H3). On a second commune items transfer (9/9), decisions do not (0/9).

![Answer funnel](docs/figures/fig1_funnel.png)

**Glossary.** *Pointer*: Apertus chooses one of the dates printed in the document, or null; it cannot write a value of
its own. *Typed null*: an empty field that says why (not in the document, unlinked, scan, oral, ...). *Residue*: the
documents where the rules find nothing and stay silent. *Review mode*: Apertus runs on the residue and its choice
arrives as a suggestion with page and span for a person to accept. *Null margin (θ)*: how much more likely Apertus
finds "no answer date" than all printed dates together; above θ it says null. *Virtual affair*: an affair rebuilt from
an agenda item and its minutes, for councils whose business exists only as meeting documents.

## Quickstart

```bash
make run              # Docker, CPU, clean checkout: replays P1-P4, re-derives the rules arm, checks claims.tsv
make census-replay    # recompute census, link status and feasibility matrix from data/census only (host Python 3.11)
make test             # unit tests (pip install -e .[dev])
```

`make run` needs nothing but Docker; network is optional (live steps report SKIP offline). It exits non-zero on any
failure and writes `out/site/index.html`, the same evidence viewer as https://gegenprobe.mi11ion.io. It recomputes the
census and asserts it equal to `results/census/`; replays the Bern join and its triple check; runs sample documents
through the converter with the validator's checks; re-scores P1–P4 from the committed predictions and labels, re-runs
the four registered hypothesis scripts and verifies the four LOCK files; re-derives the P1 rules arm from the source
PDFs (fetched by sha256) and recomputes P1 and P2 Apertus decisions from the committed model cache (cache only, no
model call) within a time budget; and runs the claims check: each of the 653 numbers listed in `claims.tsv` is
recomputed from its results file, and the step fails if a document prints anything else. Locally the rules arm
re-derives 154/154 and the Apertus decisions 154/154 (P1) and 62/62 (P2) identically. In the latest Docker run on GitHub's CI
(run 38049690293, `results/ci/docker_make_run_38049690293.json`) the budget allowed 140 of 154 rules
re-derivations, all identical; 129/129 recomputed P1 Apertus decisions matched, 25 prompts missed the cache because the
image's poppler 22.12 extracts slightly different text; P2 recomputed 7 of 62 documents, 7/7 matching (8 hosts
unreachable from CI, 46 over budget; reported as WARN, never as PASS); 641 claims were checked with 0 failing. Optional: `LLM_NAME` /
`LLM_BASE_URL` / `LLM_API_KEY` for a live Apertus slice. `make run GGUF=1` runs Apertus v1.5 8B (GGUF Q4_K_M,
sha256-pinned) in-process on CPU. Its accuracy on our gold sets is not yet measured. Our CPU scorer matches a bf16
stand-in reference on 58/60 decisions, but a stricter self-check fixed in advance failed (10/12 decisions, 3.16 nats
vs ≤ 1.0; `results/eval/gguf_impl60.json`).

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
the top of `candidates` for a person to confirm; it is never written into the field. `--anchors` adds your own
per-parliament anchors without forking the rules: they run only after the frozen rules, and each value they produce is
marked `route: user_anchor`, with page and span (`docs/examples/anchors_SG.json` fills the answer date on both
St. Gallen layouts a trial user brought; `tests/test_overlay.py`). `--explain` lists every rule and anchor tried and why each did not decide.
robots.txt is read per RFC 9309: a disallowed path is never fetched, a 4xx robots.txt means no restrictions, an
unreadable one blocks the host for the run. Fetch failures are typed rows.

## What is in the repository

| Deliverable (challenge) | Where |
|---|---|
| Representation model: versioned schema + controlled vocabularies | `src/gegenprobe/schema/schema_v0_1.py` (Pydantic, normative), `data/schema/*.json`, JSON Schema `results/schema/*.schema.json`, `docs/schema.md`; mapping to Popolo / Akoma Ntoso / Parla-CLARIN / OParl in `docs/mapping.md` |
| Converter: prompts + code, provenance per value | `src/gegenprobe/convert/` (lattice → rules → pointer → cascade, modes, overlay), prompts `src/prompts/{de,fr,it}/`, CLI + batch mode, `docs/converter.md` |
| Whole affairs (multi-field) | `src/gegenprobe/affair/` (metadata → rules → closed-set pointer per field), `docs/affair.md` |
| Virtual affairs from agendas and minutes | `src/gegenprobe/virtual/` (`python -m gegenprobe.virtual derive …`), `docs/virtual-affairs.md` |
| Validator | `src/gegenprobe/validate/` (schema, span re-check, typed-null consistency, self-deletion and distractor harnesses) |
| Evidence: four pre-registered evaluations | `eval/prereg/` (held-out, seen parliaments), `eval/prereg2/` (unseen parliaments), `eval/prereg3/` (whole affairs), `eval/prereg4/` (virtual affairs), each with its `DEVIATIONS*.md`; gold sets `data/gold*/` with raw annotations, `docs/gold_protocol.md` |
| Cross-parliament question | answer rates and answer times per parliament: `results/census/question.json`, site → Parliaments (per intervention type, CSV) |
| Research dataset | `results/census/interventions.tsv.gz`: 91,268 interventions × 23 columns with date-trust tiers and source links (CDLA-Permissive-2.0) |
| Census, feasibility matrix, comparability, data-quality findings with OPD's response | `src/gegenprobe/census/`, `results/census/`, `docs/census.md` |
| Repair lists keyed on OPD ids | `results/repair/repair_BE*.tsv`, `docs/repair.md`, `docs/runbook.md` |
| Nightly job (systemd timer + container, alerts) | `src/gegenprobe/monitor/`, `deploy/nightly/`, `docs/nightly.md` |

## Is a common schema feasible?

Yes, with date roles and typed nulls, and the evidence says where each value lives. Over 17 fields and 89 parliaments
with affairs in scope (OPD scrapes 90), by criteria written down before computing (`docs/census.md` §3): **4 of 17
fields feasible from metadata** (submission date, answer-event date, procedural history, answer-link status), **13
partial** (in the metadata for some parliaments, only in the PDF for others), **0 need a different concept**. In
figure 2 an orange cell means *no source in OPD* for that parliament (neither metadata nor a document), not a different
concept; no field is orange in a fifth or more of the parliaments (5 fields would be at a 10% threshold,
`results/census/tier_sensitivity.json`). Whether a value *means* the same thing everywhere is answered from OPD's own
vocabularies (`results/census/comparability.json`, classes in `data/schema/field_verdict_classes.json`):

| class | fields and concepts | evidence |
|---|---|---|
| **shared** | submission date, submitter, co-signatories, addressed body, government recommendation, decision and dispatch dates, Q/A pairing, related affairs, language, usable text, answer-link status | one meaning everywhere; only where the value lives differs (government recommendation: 0 ambiguous labels) |
| **shared with a role split** | **answer date**, procedural history, type, procedural state, decision outcome | "answer date" is at least three dates (decided, dispatched, registered): in 7 of 54 bodies the "answer" event is mostly the submission date, and on our held-out gold OPD's event equals the printed date for 37/44 documents; 35 event labels carry different date roles, 42 of 1,038 raw type labels map to different harmonised types, 32 state and 3 outcome labels are ambiguous; 29.1% of events have no harmonised id |
| **body-specific** | oral answers in question time, executive business that answers no member's affair, councils that publish only meeting documents | 23.6% of question-time answers are oral; 16 bodies publish only meeting documents (8 have no affair at all); schema v0.1 marks affairs derived from them `virtual` with `derived_from` (P4) |

Schema v0.1 adds date roles, typed nulls and `QAItem` (question *n* paired with the answer to question *n*; the
converter does not fill it yet). The Pydantic models are normative; the exported JSON Schema for OPD's workbench cannot
express the cross-field rules (a rule value must carry page and span), so validate with the models. Where OPD metadata
carries a field, it mostly agrees with print (P3: type 17/18, submitter 23/28, submission date 15/21; affair numbers
21/29, format differences).

![Feasibility matrix](docs/figures/fig2_matrix.png)

## The cross-parliamentary result: where answers go missing

The census streams OPD's exports once and gives every in-scope affair an answer-link status (`attached | agenda |
parentless | absent | image_only | oral`). Question-time answers given in the sitting are typed `oral`, not missing
(406 retyped; Graubünden's *Fragestunde* accounts for 367). The evidence site compares answer times within one
intervention type (median and IQR per type), shows 31 parliaments whose answers OPD barely covers (among the cantons
SZ, UR, GL, AI, NW and GE) as a coverage-gap status rather than as unanswered questions, and filters to cantons.

## Repair lists for OPD (`docs/repair.md`, `docs/runbook.md`)

- **Bern.** Of the 3,532 answers the canton publishes, OPD attaches 229 (6.5%) to their affair; 3,394 (96.1%) are
  linkable within OPD without any model (229 attached, 527 under an agenda item, 2,638 parentless documents carrying
  the canton's document id). Every candidate was checked against OPD's own copy of the document: affair number and
  answer heading 2,459/2,459; decision date equal to OPD's answer event 2,332 with the registered parser and 2,421
  [97.9, 98.9] with a second parser written after the registered run. On the pre-registered sample of 40 the date
  check was 36/40: three misses were our parser on 2020–21 headers, one a typo in the canton's own PDF. The other 179
  parentless answers are not missing (155 affairs already have the text, 24 have no written-answer event). All Bern
  numbers are reconciled in one table (site `#bern-numbers`, `results/repair/be_reconcile.json`).
- **Counts per file.** 2,459 relink candidates = 2,421 in `repair_BE_relink.tsv` (all checks pass) + 38 in review;
  49 fetch candidates = 48 in `repair_BE_fetch.tsv` + 1 in review; `repair_BE_review.tsv` holds those 39. Apply the
  relinks first, as a protected override or after OPD's staging fix, then the fetches; review rows need a person.
- **Bern `begin_date`.** 727 affairs carry a load timestamp: 557 on 2024-10-28 and 170 from later loads, the two groups
  OPD described; 554 get the date of their own "Eingereicht" event, 173 go to review (`repair_BE_begin_date.tsv`).
- **Coverage.** Deterministic routes (Bern relinks and fetches, agenda joins, federal Curia Vista) propose repairs for
  3,107 of the 16,749 missing answers. 1,008 Valais "missing" answers are oral answers filed as a stub, to retype rather
  than to find; German+French+Italian OCR recovered 15/15 image-only answers in a probe (1,350 affairs on that route);
  10,800 written answers need per-parliament source adapters (406 more are oral question time), the next step.

![Bern before and after](docs/figures/fig3_be_before_after.png)

## Evaluation: four pre-registrations

**Locks.** Every test froze code, prompts and θ by sha256 before any label was committed: the LOCK commit precedes the
commit adding its labels by 6 min 0 s (P1), 2 min 28 s (P2), 3 min 37 s (P3) and 4 min 3 s (P4) by commit date
(`results/eval/posthoc_r3_gold_oracle.json`), an order GitHub's clock confirms (`results/eval/lock_server_times_all.json`;
rewritten SHAs in `docs/commit-map.md`). The clock proves that order; the annotation files carry no timestamps
(DEVIATIONS D7). Post-hoc findings are logged per test (`eval/prereg*/DEVIATIONS*.md`).

**Gold labels without human labelling, by design.** Two blind agent annotators (Claude Opus and Sonnet) label each
document, a third breaks ties (in P2 with the order randomised), quotes are verified by code, and the raw annotations
are committed, so every label and every κ recomputes and the protocol reruns on any new set. Where a non-LLM source
exists, it agrees. Of 64 P1 answer dates, 44 can be checked against OPD's written-answer events or publisher titles:
OPD's event matches 37/44, and 5 of the 7 others are 1–5 days apart (decision vs dispatch or publication); Ticino titles
that name the decision date match 20/20. P3 answer dates match OPD 18/21. The limit is P2: only 6 of its 29 dates have
an external source, and 6/6 agree (`results/eval/posthoc_r3_gold_oracle.json`, D8).

**Which Apertus.** All Apertus numbers are the 70B weights, which Public AI serves under the name
`swiss-ai/apertus-v1.5-8b` (measured, report §3; the response's `model` field is checked on every call). We use that
name because the `-70b` name answers prefilled requests with a different model. The real 8B (GGUF Q4_K_M, CPU) arms are running
on CI; no 8B accuracy result is committed yet. **Which size to deploy:** `rules_only` (no model) unattended; review
suggestions with Apertus, the 70B on a Swiss host the operator controls today, the 8B on CPU once its arms confirm.

**P1 — 154 held-out documents from parliaments the rules were written for** (DE/FR/IT × canton/commune + Ticino scans;
64 with an answer date, 90 without; always-null scores 90/154). Unit: one document's answer date, strict.

| arm | exact [95% CI] | dates found | wrong printed date | fabricated | values on the 90 answerless |
|---|---|---|---|---|---|
| **rules only (default mode)** | **135/154 [81.5, 92]** | 47/64 | 4 | 0 | 2 |
| Apertus pointer on every document | 130/154 [77.9, 89.3] | 46/64 | 16 | 0 | 6 |
| rules + Apertus suggestions, all accepted | 139/154 [84.6, 94] | 56/64 | 11 | 0 | 7 |
| naive free generation, null-allowed | 134/154 [80.8, 91.4] | 47/64 | 11 | 0 | 3 |
| ↳ null-allowed, re-parsed (post hoc, D5) | 133/154 [80.1, 90.9] | 47/64 | 13 | 0 | 4 |
| naive free generation, plain prompt | 98/154 [55.8, 70.8] | 47/64 | 23 | 24 | 39 |
| ↳ plain, re-parsed (post hoc, D5) | 103/154 [59.1, 73.8] | 54/64 | 26 | 24 | 41 |

8B rows: pending the CI run (workflow `arms-8b`, GGUF Q4_K_M on CPU, own θ). The frozen naive scorer could not read
answers written as DD-MM-YYYY and counted them as "no date" (D5 / D2-4; registered numbers unchanged); the re-parsed rows
re-score the stored generations with the frozen scorer.

Outcomes as registered: null safety failed (7/90 answerless documents get a value; 95% upper bound 15.2% against 10%).
H2 gave Branch B: the registered consequence keeps Apertus only where it measurably adds null safety, and it adds none
(the cascade dates 7/90 answerless documents, the rules 2/90). We removed Apertus from the unattended path (default
`rules_only`) and kept it, as a departure logged in D6, as an opt-in review suggestion that a person confirms; P2 then
tested that use on unseen parliaments. The null margin separates answered from answerless documents (AUROC 0.969 on all
documents, 0.966 on the registered length-matched set); 3 of 8 Apertus-decided French/Italian values are wrong. A
one-line baseline (latest printed date, only on documents OPD types as answers) is exact on 131/154.

**P2 — 62 documents from 15 parliaments absent from every dev and held-out set** (29 with an answer date, from 7 of the
15: VD 8, NW 6, Bellinzona 5, OW 4, Vernier 3, SZ 2, Schlieren 1; 33 without; always-null scores 33/62; annotators
agreed on all 62 dates, κ 1.0):

| arm | exact [95% CI] | dates found | wrong printed date | fabricated | values on the 33 answerless |
|---|---|---|---|---|---|
| rules only | 35/62 [44.1, 68.1] | **2/29** | 2 | 0 | 0 |
| **Apertus pointer** | **53/62 [74.7, 92.2]** | **24/29** | 8 | 0 | 4 |
| rules + Apertus suggestions | 51/62 [71, 89.8] | 22/29 | 10 | 0 | 4 |
| naive free generation, null-allowed | 52/62 [72.8, 91] | 22/29 | 7 | 1 | 3 |
| ↳ null-allowed, re-parsed (post hoc, D2-4) | 54/62 [76.6, 93.3] | 24/29 | 7 | 1 | 3 |
| naive free generation, plain prompt | 45/62 [60.4, 82.1] | 21/29 | 8 | 4 | 9 |
| ↳ plain, re-parsed (post hoc, D2-4) | 49/62 [67.4, 87.3] | 25/29 | 9 | 4 | 9 |
| *latest printed date on documents OPD types as answers (post hoc)* | *44/62* | *18/29* | *13* | *0* | *7* |

Outcomes: the rules collapse off their home layouts (dates found 47/64 → 2/29). On the 29 answered documents, as
registered, 22 are right only with the pointer and 0 only with the rules (McNemar p = 4.8 × 10⁻⁷; without Bellinzona,
whose letterhead one rule happens to match, 17 vs 0, p = 1.5 × 10⁻⁵); on all 62 it is 22 vs 4 (p = 5.3 × 10⁻⁴), the
rules' nulls winning on 4 answerless documents the pointer dates. By parliament (post hoc, D2-1) the pointer wins in 6,
the rules in 0, 1 tie (sign test p = 0.031). Against the strongest one-line baseline (latest printed date, null on
documents OPD types as member texts) the pointer is right on 10 documents the baseline gets wrong and the baseline on 1
(p = 0.012), 6 parliaments to 0 (p = 0.031; D2-5). The margin separates the classes (AUROC 0.983); null safety failed
again (4/33, upper bound 27.3%), so Apertus's values remain review suggestions. θ = 0, registered in PREREG2 as a
secondary with no decision attached, scores 54/62 (53 at θ = 10.40). **Error profile** (`results/report/p2_numbers.json`):
the rules are right on 35, pick a wrong printed date on 2, date none of the answerless documents and miss 25 answer
dates; the pointer is right on 53, picks a wrong printed date on 4, dates 4 answerless documents and misses 1; rules +
Apertus are right on 51, wrong date 6, answerless 4, missed 1. The combination scores below the pointer alone because
Apertus is asked only where the rules abstain: on 2 documents a rule (`rrb_vom`) fired with a wrong printed date.

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

**P4 — virtual affairs from minutes: 6 held-out sittings of Bulle's council, 120 agenda items.** Deterministic parsing
derives 99 items as virtual affairs: item precision 99/99, titles 99/99, type 91/99 (H2 holds), meeting date 6/6 (H4
holds), decision found for 49/63 items (46/63 correct), invented for 0/36. **H1 failed**: recall 99/120 (82.5%, sub-items
and unnumbered lines) below the registered bar. **H3 failed**: Apertus added 2 decisions (p = 0.5). Registered transfer
cell (exploratory, DEVIATIONS4 D4-4): 2 sittings of La Chaux-de-Fonds; items 9/9 and titles 9/9, but the rules find 0/9
decisions, and with Apertus 2/9 are found, 1 correct (the annotators agreed on 7/9 of these decisions, κ 0.4, so read
the decision cell as indicative). Details: `docs/virtual-affairs.md`.

**What the four tests say together.** Apertus earns its place where the layout varies and no rule exists: on
parliaments nobody wrote rules for (P2: 24/29 answer dates where the rules find 2/29; 10 documents to 1 and 6 parliaments
to 0 against the strongest trivial baseline) and for the answer date of whole affairs (P3: 22/27 → 27/27). Where
structure is regular (P1, Bulle's minutes in P4) rules suffice. **Why a pointer and not free generation:** the same
Apertus asked freely with a null-allowed prompt is as accurate (P2: 54/62 re-parsed vs 53/62; discordant 1 vs 0, p = 1;
both right on the same 24 of 29 answer dates). But every pointer value is a printed date with page and span (32/32 on
P2), and its margin orders the review queue (suggestions in the strong band right 26/33, weak band 3/11, post hoc);
the free prompt gives a verbatim quote containing its date for 17/32 values and invents a date printed nowhere (1 on P2;
the plain prompt 24 on P1).

![Scoreboards](docs/figures/fig5_scoreboard.png)

## Use of Apertus

- **Where:** only in the converter, as a closed-set pointer: forced choice over the dates (or enum labels, or OPD affair
  numbers) printed in the document, plus null; summed log-probabilities; null if the margin exceeds θ, fitted per build
  on dev documents and frozen (θ = 10.40 for the Public AI build). Free generation is run only as the naive baseline.
- **Why a pointer:** asked freely when the government answered, Apertus writes a precise date for 15/15 (local 8B) and
  14/15 (70B) Bern interventions that have no answer, often the "Letzte Bearbeitung" footer (earlier spikes, cited); a
  null-allowed prompt fixes this on the 70B but not on the local 8B (still 14/15).
- **Modes:** `rules_only` (default, unattended, no model) and `review`: Apertus on the rules' residue, its value attached
  as a suggestion with page, span, margin and `needs_review: true` for OPD's existing manual-review step. Recommended
  for the 74 of 89 parliaments without rules (P2) and for the answer date of whole affairs (P3), with a reviewer gate.
- **Builds:** θ does not transfer between builds, so each gets its own; the 70B results above carry θ = 10.40, the
  real 8B gets its own θ from the same dev documents.

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
from a dated snapshot.

- **Designed to run inside OPD.** Pointed at the export directory (`GP_EXPORTS_DIR`), a night with no changed export
  files took 96.8 s wall on a copied snapshot with 0 bytes of export transfer (`results/monitor/run_local_exports.json`);
  a night that re-scans the files OPD changed over three days (80.6% of the docs bytes) is about 21.8 min (derived;
  a full re-scan is 25 min of one core; `results/monitor/night_cost.json`).
- **Hardened.** The container never runs as root (uid 10001, read-only root filesystem, all capabilities dropped,
  no-new-privileges, 4 GB / 2 CPU ceiling). Untrusted PDFs are bounded: 50 MB per file, 300 s per pdftotext/tesseract
  call, 600 s per document; each hit is a typed failure row, never a hung night. A host whose robots.txt cannot be read
  is not fetched that night. A failed alert send keeps the alerts in an outbox, written atomically, and re-sends them the
  next night; a corrupt outbox is quarantined and reported. One configurable User-Agent, at least 1.2 s between
  requests to one host.
- **Research dataset.** `results/census/interventions.tsv.gz`: one row for each of the 91,268 interventions, with
  submission and answer dates, where the answer text is, the OPD page and the parliament's own page, and a per-body
  date-trust tier, because OPD's "answer" date is verified only in Bern (2,421 of 2,459 relinks carry the printed date)
  and elsewhere ranges from a weekly cabinet sitting day to the submission date (`results/census/date_trust.json`).

**Cost** (`results/report/cost_end_to_end.json`; one core, no GPU). Per document, fetching politely, extracting and
checking takes about 2.1 s (50 federal documents), plus 6.9 s per page where OCR is needed; the rules themselves
process 480 documents per second, about 0.5 CPU-hours for all 902,754 documents in OPD's export. Re-deriving the 154
held-out documents from their PDFs (22 of them scans) took 727 s. Review mode adds the pointer on the rules' residue
(97/154 held-out documents): 3.5 calls and 5,905 billed prompt tokens per residue document on the 70B, USD 0.59 per
1,000 residue documents at Public AI's list price; the 8B cost per residue document is pending the CI run. **At ten
times OPD's volume** the rules need about 5 CPU-hours and review mode about USD 3,357 at that list price.

## Maturity, limitations, coding assistants

- **Maturity per component:** census and repair lists: ready to hand over (lists keyed on OPD ids, reproduced in every
  `make run`). Nightly job: ready to deploy (container, systemd units, alerts, runbook, local-exports mode; CI runs
  `systemd-analyze verify` on the units and three offline nights in the read-only container on fixture exports); not
  yet running at OPD. Converter, rules-only mode: tested prototype (154 held-out + 62 unseen documents). Review mode
  with Apertus: feasibility study with a reviewer gate. Whole affairs and virtual affairs: feasibility studies (no field
  unattended yet; one commune for minutes). Schema v0.1: draft for the eCH group.
- **Limitations:** answer dates are the field evaluated in depth; 10,800 missing written answers need per-parliament
  adapters that are not built; no federal documents in any gold set; spans index our own pdftotext/tesseract text,
  though `--opd-text` maps values onto OPD's stored text.
- **Coding assistants:** Claude Code agents (Anthropic) wrote most code, documentation and the gold labels; no human
  labelled or adjudicated a gold value, by design. Correctness rests on code-level checks — spike numbers reproduced
  cell-for-cell, regression fixtures, `claims.tsv`, the pre-registration locks, verbatim-quote checks, re-derivation
  from source PDFs — not on reading.

## Licences

Code: Apache-2.0 (`../LICENSE`). Report: CC-BY-4.0 (`docs/LICENSE-report.txt`). Data in `data/`: CDLA-Permissive-2.0
(`data/LICENSE`): identifiers, URLs, hashes, counts, labels and short quotations only — no full document texts and no
personal contact data.
