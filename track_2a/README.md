# Gegenprobe — where Swiss parliamentary answers go missing, how to put them back, and a converter that cannot invent

Track 2A · OpenParlData · Team 444 · **Evidence site: https://gegenprobe.mi11ion.io** · report: `technical_report.md`

- **Census.** Of 91,268 interventions whose events record a written government answer, **16,749 (18.4%) have no answer
  text in OpenParlData (OPD)**. Every one has a typed cause: filed under an agenda item, stored without a parent,
  scanned without text, answered orally, or not in OPD at all.
- **Repair lists OPD can apply.** In Bern the answers are in OPD but unlinked. OPD confirmed the bug and its root cause
  (correspondence, 10 Oct 2026); until its fix ships, our relink list (2,459 relinks + 49 fetches) is the best interim
  workaround. A second list fixes 727 Bern `begin_date` values that are load timestamps.
- **A schema verdict with evidence.** The concepts are shared; what differs is where the value lives, the vocabulary and
  the date roles. 4 of 17 fields are feasible from OPD metadata alone, 13 partial, 0 fundamentally different; 42 raw
  affair-type labels mean different things in different parliaments; "answer date" is at least three dates.
- **A converter in which Apertus can only point at a value printed in the document, or say null** — page and character
  span on every value. Four pre-registered tests show where Apertus earns its place. On the parliaments our rules were
  written for it adds nothing significant, so rules run unattended; on **15 parliaments the rules never saw, the rules
  find 2/29 answer dates and Apertus finds 24/29** (exact McNemar p = 4.8 × 10⁻⁷). On whole affairs (29 affairs, 10
  parliaments) metadata and rules fill most fields and Apertus finds the addressed body (rules 4/28, with Apertus 23/28);
  on meeting minutes, regular structure needs no model. Apertus's values arrive as review suggestions, because it still
  puts a date on 4/33 documents that carry no answer. 74 of the 89 parliaments have no rules; we tested 15 of them.
- **Virtual affairs for communes that publish only minutes.** From 6 held-out sittings of Bulle's council (OPD holds its
  members' instruments but none of the council's own business), the agenda and minutes yield 99 affairs with item precision 99/99, every title right, the
  decision found for 49/63 items and invented for none of 36 that carry none.

![Answer funnel](docs/figures/fig1_funnel.png)

## Quickstart

```bash
make run              # Docker, CPU, clean checkout: replays every headline and re-derives the rules arm from source PDFs
make census-replay    # recompute census, link status and feasibility matrix from data/census only (host Python 3.11)
make test             # unit tests (pip install -e .[dev])
```

`make run` needs nothing but Docker; network is optional (live steps report SKIP offline). It exits non-zero on any
failure and writes `out/site/index.html`, the same evidence viewer as https://gegenprobe.mi11ion.io. Steps
(`src/gegenprobe/run.py`): census recomputed and asserted equal to `results/census/`; the Bern canton-uid join and its
triple check; sample documents through the converter with the validator's span, typed-null, footer-distractor and
self-deletion checks; every evaluation file re-scored from its per-document rows; the rules arm re-derived from the
source PDFs fetched by sha256 (locally 154/154 identical to the committed predictions); every number in this README and
the report recomputed from a results file (`claims.tsv`; figures cited from earlier spikes are marked as cited).
Optional: `LLM_NAME` / `LLM_BASE_URL` / `LLM_API_KEY` for a live Apertus slice over a vLLM-style endpoint, or
`make run GGUF=1` for Apertus v1.5 8B (GGUF Q4_K_M, sha256-pinned) in-process on CPU.

**Convert your own PDFs** (guide, field glossary and null reasons in plain words: `docs/convert-your-own.md`):
```bash
python -m gegenprobe convert <pdf-or-url>                        # one document, no model: JSON with page, span, rule
python -m gegenprobe convert --batch inputs.tsv --out out.jsonl  # many, resumable; fetch failures are typed rows
```

## What is in the repository

| Deliverable (challenge) | Where |
|---|---|
| Representation model: versioned schema + controlled vocabularies | `src/gegenprobe/schema/schema_v0_1.py`, `data/schema/*.json`, JSON Schema `results/schema/*.schema.json`, `docs/schema.md`; mapping to Popolo / Akoma Ntoso / Parla-CLARIN / OParl in `docs/mapping.md` |
| Converter: prompts + code, provenance per value | `src/gegenprobe/convert/` (lattice → rules → pointer → cascade, modes), prompts `src/prompts/{de,fr,it}/`, CLI + batch mode, `docs/converter.md` |
| Whole affairs (multi-field) | `src/gegenprobe/affair/` (metadata → rules → closed-set pointer per field), `docs/affair.md` |
| Virtual affairs from agendas and minutes | `src/gegenprobe/virtual/` (`python -m gegenprobe.virtual derive …`), `docs/virtual-affairs.md` |
| Validator | `src/gegenprobe/validate/` (schema, span re-check, typed-null consistency, self-deletion and distractor harnesses) |
| Evidence: four pre-registered evaluations | `eval/prereg/` (held-out, seen parliaments), `eval/prereg2/` (unseen parliaments), `eval/prereg3/` (whole affairs), `eval/prereg4/` (virtual affairs), gold sets `data/gold*/` with raw annotations, `docs/gold_protocol.md` |
| Cross-parliament question | answer rates and answer times per parliament: `results/census/question.json`, site → Parliaments (CSV) |
| Census, feasibility matrix, comparability, data-quality findings with OPD's response | `src/gegenprobe/census/`, `results/census/`, `docs/census.md` |
| Repair lists in OPD's export layout | `results/repair/repair_BE*.tsv`, `docs/repair.md`, `docs/runbook.md` |
| Nightly job (systemd timer + container, alerts) | `src/gegenprobe/monitor/`, `deploy/nightly/`, `docs/nightly.md` |

## Is a common schema feasible?

Partly, and the evidence says exactly where it breaks. Over 17 fields and 89 parliaments with affairs in scope (OPD
scrapes 90), by criteria written down before computing (`docs/census.md` §3; not separately committed — recomputing at
other thresholds is in `results/census/tier_sensitivity.json`):

- **4 feasible** from OPD metadata alone: submission date, answer-event date, procedural history, answer-link status.
  The answer-event date is in OPD for nearly every parliament but is not one concept: in 7 of 54 bodies it is mostly the submission date,
  and on our held-out gold it equals the date printed in the answer for 37/44 documents, the rest being later
  registration or publication dates. A schema needs date roles (decided, dispatched, registered), not one "answer date".
- **13 partial**: in the metadata for some parliaments, only in the PDF for others (type, submitter, co-signatories,
  addressed body, Q/A pairing, dispatch and decision dates, decision outcome, government recommendation, procedural
  state, related affairs, language, usable text).
- **0 fundamentally different** at the frozen thresholds; at a 10% no-source threshold 5 fields would be.
- **Availability is not comparability.** In OPD's own vocabularies 42 of 1,038 raw affair-type labels map to different
  harmonised types in different parliaments, 35 event labels carry different date roles, and 29.1% of events have no
  harmonised id at all (`results/census/comparability.json`).
- **Where OPD metadata carries a field, it mostly agrees with print** (P3, 29 whole affairs): type 17/18, submitter
  23/28, submission date 15/21; affair numbers 21/29 (format differences). What metadata lacks — addressed body,
  decision number — lives only in the PDFs.
- Where the concept itself splits: oral answers, question time, executive business that answers no member's affair,
  and communes that publish only meeting documents. Schema v0.1 marks affairs derived from them as `virtual` with
  `derived_from`, exercised on 99 real agenda items (P4).

![Feasibility matrix](docs/figures/fig2_matrix.png)

## Repair lists for OPD (`docs/repair.md`, `docs/runbook.md`)

- **Bern.** Of the 3,532 answers the canton publishes, OPD attaches 229 (6.5%) to their affair; 3,394 (96.1%) are
  linkable within OPD without any model (229 attached, 527 under an agenda item, 2,638 parentless documents carrying
  the canton's document id). The relink list covers the parentless ones whose affair still lacks its answer (2,459, plus 49 to fetch
  from the canton); the other 179 parentless answers are not missing (155 affairs already have the text, 24 have no
  written-answer event; `results/repair/be_reconcile.json`). Every relink was then checked against OPD's own copy of the
  document: affair number and answer heading 2,459/2,459, decision date equal to OPD's answer event 2,421 [97.9, 98.9];
  the rest go to review (`results/repair/be_verify_all.json`). On the earlier pre-registered sample of 40 the date check
  was 36/40: three misses were our parser on 2020–21 headers, one a typo in the canton's own PDF. The list is reproduced from code in every `make run`.
- **Bern `begin_date`.** 727 affairs carry a load timestamp: 557 on 2024-10-28 and 170 from later loads, the two groups
  OPD described; 554 get the date of their own "Eingereicht" event, 173 go to review (`repair_BE_begin_date.tsv`).
- **Elsewhere.** 1,008 Valais "missing" answers are oral answers filed as a stub; German+French+Italian OCR recovered
  15/15 image-only answers in a probe; 3,107 missing answers are recoverable by deterministic routes in all; 11,206 need
  per-parliament source adapters that are not built — the honest remainder.

![Bern before and after](docs/figures/fig3_be_before_after.png)

## Evaluation: four pre-registrations

Every test froze code, prompts and θ by sha256 before any label existed (`eval/prereg/LOCK`, commit `812030f`, received by
GitHub at 2026-10-09T19:38:07Z, labels at 2026-10-09T19:44:06Z; `eval/prereg2/LOCK2`, `eval/prereg3/LOCK3`,
`eval/prereg4/LOCK4`). Gold labels come from two blind
annotators (Claude Opus and Sonnet) and a tie-breaker, quotes verified by code, no human labels by design; the raw
annotations are committed so agreement recomputes. Apertus = the 70B weights served by Public AI under
`swiss-ai/apertus-v1.5-8b`, answer date, strict.

**P1 — 154 held-out documents from parliaments the rules were written for** (DE/FR/IT × canton/commune + Ticino scans;
64 with an answer date, 90 without; always-null scores 90/154):

| arm | exact [95% CI] | dates found | wrong printed date | fabricated | values on the 90 answerless |
|---|---|---|---|---|---|
| **rules only (default mode)** | **135/154 [81.5, 92]** | 47/64 | 4 | 0 | 2 |
| Apertus pointer on every document | 130/154 [77.9, 89.3] | 46/64 | 16 | 0 | 6 |
| rules + Apertus suggestions, all accepted | 139/154 [84.6, 94] | 56/64 | 11 | 0 | 7 |
| naive free generation, null-allowed | 134/154 [80.8, 91.4] | 47/64 | 11 | 0 | 3 |
| naive free generation, plain prompt | 98/154 [55.8, 70.8] | 47/64 | 23 | 24 | 39 |
<!-- SLOT: 8B rows -->

Outcomes as registered: null safety failed (7/90 answerless documents get a value; 95% upper bound 15.2% against 10%);
Apertus over rules is not significant (+3.6 points on FR/IT/scans, 95% CI −1.4 to 9.3, p = 0.22), so rules run
unattended and Apertus's answers are review suggestions; the null margin separates answered from answerless documents
(AUROC 0.969); 3 of 8 Apertus-decided French/Italian values are wrong (θ sweep in the report, post hoc).

**P2 — 62 documents from 15 parliaments absent from every dev and held-out set** (29 with an answer date, 33 without;
always-null scores 33/62; annotators agreed on all 62 dates, κ 1.0):

| arm | exact [95% CI] | dates found | wrong printed date | fabricated | values on the 33 answerless |
|---|---|---|---|---|---|
| rules only | 35/62 [44.1, 68.1] | **2/29** | 2 | 0 | 0 |
| **Apertus pointer** | **53/62 [74.7, 92.2]** | **24/29** | 8 | 0 | 4 |
| rules + Apertus suggestions | 51/62 [71, 89.8] | 22/29 | 10 | 0 | 4 |
| naive free generation, null-allowed | 52/62 [72.8, 91] | 22/29 | 7 | 1 | 3 |
| naive free generation, plain prompt | 45/62 [60.4, 82.1] | 21/29 | 8 | 4 | 9 |

Outcomes as registered: the rules collapse off their home layouts (dates found 47/64 → 2/29); the pointer beats them on
answered documents (22 documents only the pointer gets right, 0 only the rules; p = 4.8 × 10⁻⁷; without Bellinzona, whose
letterhead one rule happens to match, 17 vs 0, p = 1.5 × 10⁻⁵); the margin separates the classes (AUROC 0.983); the null
safety target failed again (4/33, upper bound 27.3%), so Apertus's values remain review suggestions.

**P3 — whole affairs: 29 affairs (58 PDFs) from 10 parliaments, 5 with rules and 5 without, DE/FR/IT.** Arms: OPD metadata
only (M), rules only (R), the default metadata + rules (C), and C plus Apertus suggestions on the fields C leaves open
(CA). Annotators agreed on at least 27/29 affairs on every field; 4 fields were tie-broken.

| field | M | R | **C (default)** | C + Apertus |
|---|---|---|---|---|
| type | 17/29 | 26/29 | **27/29** | 27/29 |
| affair number | 21/29 | 14/29 | **21/29** | 21/29 |
| submitter | 23/29 | 5/29 | **23/29** | 23/29 |
| submission date | 15/21 | 4/21 | **15/21** | 15/21 |
| answer date | 21/27 | 16/27 | **22/27** | 27/27 |
| addressed body | 0/28 | 4/28 | **4/28** | 23/28 |
| decision number | 0/17 | 5/17 | **0/17** | 0/17 |

Outcomes as registered: no field reaches the "unattended" bar (95% lower bound ≥ 0.80; type comes closest); number,
type, submitter, submission date and answer date are partial. On the fields the default leaves open, Apertus suggestions
are right for 25/32 of those that have a value (recall holds), and 25/34 of its suggestions are right (precision below
the 0.70 bar), so the registered consequence is: suggestions with a reviewer gate. Details: `docs/affair.md`.

**P4 — virtual affairs from minutes: 6 held-out sittings of Bulle's council, 120 agenda items.** Deterministic parsing of
agenda and minutes derives 99 items as virtual affairs, item precision 99/99, titles 99/99, type 91/99, decision found
for 49/63 items (46 correct), invented for 0/36, meeting date 6/6. Recall stayed below the registered bar (99/120,
82.5%; sub-items and unnumbered lines), Apertus added 2 decisions (not significant). Details: `docs/virtual-affairs.md`.

**What the four tests say together.** Apertus earns its place where the layout varies: on parliaments nobody wrote rules
for (P2) and for fields no rule anchors (P3, addressed body). Where structure is regular — the parliaments the rules were
written for (P1) and council minutes (P4) — rules suffice. The system uses Apertus exactly there, as reviewed
suggestions. A well-prompted 70B is about as accurate on answer dates (P1 134 vs 139, P2 52 vs 53), but it can fabricate
(1 in P2, 24 with the plain prompt in P1) and returns no span; the closed-set pointer cannot fabricate by construction
and every value carries page and span for the reviewer.

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
  for every parliament without rules (P2) and for fields no rule anchors, with a reviewer gate (P3: addressed body,
  answer date).
- **Builds:** Public AI's `swiss-ai/apertus-v1.5-8b` name serves the 70B weights (measured; report §3), so those results
  are labelled 70B. The real 8B runs as GGUF Q4_K_M on CPU; θ does not transfer between builds, so each gets its own.

## Sovereignty, runtime dependencies, cost

| Service (runtime) | What is sent | Needed for |
|---|---|---|
| files.openparldata.ch (exports) | GET only | census, nightly job |
| ogd.parl.apps.be.ch, rrgr-service.apps.be.ch (canton Bern) | GET; an affair number for the per-affair route | Bern repair |
| fedlex.data.admin.ch (SPARQL), www.fedlex.admin.ch (filestore) | a citation such as "BBl 2014 9657" | federal placeholder repair |
| document hosts listed in OPD | GET of a public PDF | conversion, triple check |
| huggingface.co, only with `GP_GGUF=1` | GET of the pinned GGUF (once) | local 8B |
| the LLM endpoint the operator sets (`LLM_BASE_URL`) — or none | text of public parliamentary documents | review mode |

ws.parlament.ch (Curia Vista) was queried once for the federal answers missing from the texts export; it is not part of
the running system. The evidence site on Cloudflare is documentation, not runtime. With `GP_GGUF=1` no document text
leaves the machine; Public AI was used for development and evaluation only (it may route outside Switzerland).
`api.openparldata.ch/robots.txt` disallows `/v1/` for all agents (its comment says it targets search crawlers); we used
the nightly bulk exports, which also makes every number reproducible from a dated snapshot. One fixed User-Agent, at
least 1.2 s between requests to one host, robots.txt honoured.

**Cost.** Rules only: about 0.5 CPU-hours for all 902,754 documents in OPD's export. Review mode adds the pointer on the
rules' residue (97/154 held-out documents): 3.5 calls and 5,905 billed prompt tokens per residue document
(`results/report/cost.json`).

## Maturity, limitations, coding assistants

- **Maturity:** census and repair: deployable prototype (nightly job, systemd units, alerts, outputs in OPD's export
  layout, runbook). Extraction: feasibility study, now tested on parliaments it was not built on.
- **Limitations:** the converter is evaluated on the answer date (the recommendation arm is exploratory); 11,206 missing
  answers need per-parliament adapters that are not built; no federal documents in either gold set; spans index our own
  pdftotext/tesseract text, not OPD's stored text.
- **Coding assistants:** Claude Code agents (Anthropic) wrote most code, documentation and the gold labels. Correctness
  rests on code-level checks — spike numbers reproduced cell-for-cell, regression fixtures, `claims.tsv`, the
  pre-registration locks, verbatim-quote checks, re-derivation from source PDFs — not on reading.

## Licences

Code: Apache-2.0 (`../LICENSE`). Report: CC-BY-4.0 (`docs/LICENSE-report.txt`). Data in `data/`: CDLA-Permissive-2.0
(`data/LICENSE`): identifiers, URLs, hashes, counts, labels and short quotations only — no full document texts and no
personal contact data.
