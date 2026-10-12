# Devpost submission: Gegenprobe (Track 2A, OpenParlData, team 444)

Paste each block as is. Character counts are Python `len()` of the block's content.

## 1. Project name (60 / 60 characters)

```text
Gegenprobe: one schema for Swiss parliamentary interventions
```

## 2. Elevator pitch (199 / 200 characters, plain ASCII)

```text
Swiss parliamentary interventions fit one schema if fields name roles. 9,580 model-free repairs would give 92.1% of answered ones their text (now 81.6%). New layouts: Apertus 24/29 dates, rules 2/29.
```

## 3. About the project (8945 characters, about 1,471 words; Markdown with one LaTeX display formula)

````markdown
## Inspiration

OpenParlData (OPD) gathers the business of Switzerland's communal, cantonal and federal parliaments in German, French and Italian. Its challenge asked: **can one schema hold all of it, and where does it break?** The gap it leaves is measurable: of the 91,268 interventions in OPD with a recorded government answer, 16,749 (18.4%) have no answer text attached. We answered the question on the documents themselves and turned each gap into a repair keyed on OPD ids. OPD confirmed the Bern linking bug we found and that our relink list is its workaround until its fix ships (correspondence, 10 Oct 2026).

## What it does

**The answer: yes, if each field says which role its value plays.** OPD's one label "answer date" records the government's decision, its letter or, in 7 parliaments, mostly the submission date: one label, several acts. Tested on the 17-field skeleton of OPD's five intervention types (198,594 of its 325,691 affairs):

| verdict | fields | example |
|---|---|---|
| needs roles | **10** (6 from the pre-registered role test, 4 from OPD's labels, post hoc; 2 of the 10 are fragile) | answer date, submitter, co-signatories, language |
| body-specific | **1 field and 2 constructs** | the submission date; oral answers; councils that publish only minutes |
| untested | **6**, defined in v0.1 | their meaning test comes next |

Where it breaks: OPD's submission date is printed in neither the question nor the answer in Vernier (5/5 affairs) and Lausanne (3/5). The submitter needs roles because authorship takes three forms: a sole author, joint authors with none first, or a parliamentary group.

**The repair: 81.6% → 92.1% of answered interventions would have their text.** A census types every answer gap by cause and proposes **9,580 model-free repairs** keyed on OPD ids: 3,621 apply now; 2,459 Bern relinks (2,421 ready, 38 for review) follow one OPD decision, its hash rule for relinked documents; 3,500 answers verified on the parliaments' sites are to be fetched into OPD. 2,177 of the 16,749 without attached text were in OPD all along, under another heading. In the repair queue Bern has 2,976 relinks: those 2,459 plus 517 agenda joins among the 3,621 that apply now. The Bern SQL plan, a different set, ran on PostgreSQL: 2,975 rows (the 2,421 ready relinks plus 554 date corrections) in one transaction that rolls back on any deviation; the 554 fix another field and are not among the 9,580.

**The converter** writes validated schema v0.2 records: every value with its document, page, character span and rule (or its OPD record), every gap a typed reason. 186 v0.2 records from 26 parliaments validate: the converter's 120 and the role test's 66 gold records. On 36 held-out affairs with blind labels it is right on the type 35/36, the submitter 30/36 and the answer date 20/35, **31/35 with Apertus**.

**The app** ([gegenprobe.mi11ion.io](https://gegenprobe.mi11ion.io)) looks up all 91,268 interventions and exports the repair queue as CSV or as the Bern SQL plan.

**Apertus reads layouts no rules cover** (opt-in review mode; all three pre-registered):

- **P2:** 24/29 answer dates in 15 parliaments nobody wrote rules for; the rules find 2/29.
- **P10:** author-role recall +23.4 points over the rules in 14 parliaments without rules (50/141 pairs vs 17/141), pair precision 0.52 vs 0.31.
- **P7:** of 120 sampled rows Apertus moved out of the review queue, all 120 are the government's answer.

**What the closed design adds:** free prompting's quotes check out on 30/60 (P1) and 17/32 (P2) of its values; the closed pointer's values are printed and located on 62/62, 32/32 and 35/35 (P1, P2, P6), each checkable on its page. Its confidence margin puts wrong values first in the review queue: AUROC 0.90 on new layouts (P2, post hoc), above the no-model signals we tested (at most 0.58).

**Where it fell short set the design:** in the three registered null-safety tests (P1, P2, P6) the Apertus arms dated 7 of 90, 4 of 33 and 5 of 34 answerless documents, so the default runs no model and a person confirms every value Apertus proposes.

**Sovereign by default.**

- **Runtime external services:** none by default; the job reads public sources only (OPD's exports, Bern's open data, Fedlex, the parliaments' sites) and runs no model. Review mode sends document text to the Public AI gateway (a US nonprofit, without a processing agreement), or to a self-hosted 70B, or nowhere with the local 8B (GGUF on CPU).
- **Cost:** the rules take about 0.5 CPU-hours for all 902,754 documents in OPD's export, about 5 at ten times OPD's volume; review mode costs USD 0.59 per 1,000 documents the rules leave open, on the 70B.
- **Model size:** on the 52 reachable P2 documents (exploratory), the local 8B finds 15/21 new-layout answer dates (70B 16/21) but dates 11 of 31 answerless documents (70B 4), hence the 70B for review.
- **Maturity:** repair lists ready to apply (the relinks after the hash decision); nightly job ready to deploy; rules-only converter a tested prototype; review mode a feasibility study; schema v0.2 a draft for eCH, the Swiss e-government standards body.

## How we built it

- **Python 3.11 in Docker:** poppler for page-exact text, tesseract for scans, pydantic for the schema, every lock hash-pinned.
- **Apertus pointer:** Apertus v1.5 70B weights, served by Public AI under the name swiss-ai/apertus-v1.5-8b (inferred from the served fingerprint and 760/792 greedy outputs identical byte for byte to those of the -70b name). It scores `null` and every printed date by log-probability; θ is fitted per build and frozen:

$$\text{null} \iff \mathrm{lp}(\text{null}) - \operatorname{logsumexp}\big(\mathrm{lp}(\text{dates})\big) > \theta$$

- **Ten pre-registered tests (P1–P8, P3b, P10):** code, prompts and θ frozen by sha256 before the labels; P1's hypothesis script followed its labels and its rules came with its sample, both logged as deviations.
- **Tools:** Claude Code agents (Anthropic) wrote most of the code and the documentation, and the gold labels in separate blind annotator sessions (Claude Opus and Sonnet, two per document, a third for disagreements). Qwen-SEA-LION (AI Singapore) relabelled P1, P2 and P6 independently and blind (date κ 0.80, 0.87, 0.86), and an isolation audit of all 96 annotator sessions found none that read a key, a result or another annotator's files.
- **Reproducible:** `make run` (Docker, CPU, clean checkout) recomputes the census and re-scores the ten tests; `make claims` recomputes every number in the README, report and form notes and fails on any mismatch.

## Challenges we ran into

- **OPD's Bern linking bug.** OPD attaches 229 of the 3,532 answers the canton publishes, yet 96.1% of them are already in OPD. Joining on OPD's own copy gave 2,421 relinks that pass every check: affair number, answer heading, and a decision date equal to OPD's answer event.
- **The provider switched builds mid-run.** On 12 Oct 2026 Public AI switched the route to another build and back. The build guard caught it live, so all 17,720 committed gateway responses come from one build.
- **robots.txt, longest match.** Python's stdlib parser applies the first matching rule; RFC 9309 applies the longest, and our crawler had used the first. We wrote an RFC 9309 matcher, audited 14,152 URLs on 75 hosts against it and disclosed the finding in `docs/incidents.md`; every fetch path now fails closed.
- **Scans.** A failed OCR is a typed `ocr_failed`, never an empty page; with pinned OCR models all 154/154 P1 documents re-derive from the source PDFs, the 22 Ticino scans included.

## Accomplishments that we're proud of

- A schema verdict drawn from the documents: meaning measured for 11 of 17 fields, v0.2 with the roles, a one-page recommendation for eCH.
- Dry-run repair plans keyed on OPD ids, plus findings in its data: 7,876 interventions in 73 parliaments still carry "submitted" as their last state although OPD holds their answer (5.9% of the 133,215 with any answer document, date or event in OPD, a wider count than the 91,268 with a written-answer event).
- A nightly job that re-checks OPD's exports, lists new Bern repairs and alerts when a parliament's answer-linking rate drops; on real network nights it took 86 min the first night and 6.6 min the next.

## What we learned

- Parliaments share the fields; they differ in which act a value records.
- Test every model claim against a strong no-model baseline. Where rules exist they are right on 135/154 (P1), so the default runs no model; on new layouts they find 2/29 answer dates, and that is where Apertus earns its place.

## What's next for Gegenprobe

- With OPD: its hash decision for the 2,421 ready Bern relinks.
- With eCH: the meaning test for the 6 untested fields.
- v0.3 roles for government business, where the executive is the proposer.
- Rules for the next parliaments, largest first: Bern city, Fribourg, Basel-Landschaft, Vaud, Thurgau.
````

## 4. Built with (25 / 25 tags; 251 characters)

```text
python, pydantic, numpy, jinja2, matplotlib, pytest, docker, github-actions, postgresql, poppler, tesseract, llama.cpp, gguf, apertus, public-ai, qwen-sea-lion, claude-code, json-schema, javascript, html, css, cloudflare, systemd, openparldata, fedlex
```

## 5. "Try it out" links (4 links)

```text
https://gegenprobe.mi11ion.io
https://github.com/mi11ione/gegenprobe
https://raw.githubusercontent.com/mi11ione/gegenprobe/main/track_2a/444_Report.pdf
https://github.com/mi11ione/gegenprobe/blob/main/track_2a/docs/decision.md
```

## 6. Image gallery captions

| file | slot | caption | chars |
|---|---|---|---|
| `media/00-thumbnail.png` | thumbnail | Gegenprobe: one schema for Swiss parliamentary interventions if each field names its role; 92.1% answer text after 9,580 proposed repairs. | 138 |
| `media/01-answer.png` | gallery 1 | The schema answer: of 17 fields, 10 need roles (6 from the pre-registered role test, 4 from OPD's labels, post hoc), 1 field and 2 constructs are body-specific, 6 are untested. | 176 |
| `media/02-lookup.png` | gallery 2 | Lookup: every value of a v0.2 record with its page, span and role; left, an inset added for this image: the answer page, "18 mai 2022" boxed. | 141 |
| `media/03-repair.png` | gallery 3 | The repair: 81.6% to 92.1% of answered interventions would have answer text after 9,580 model-free repairs on OPD ids. | 118 |
| `media/04-queue.png` | gallery 4 | Repair queue, filtered to Bern's 2,976 relinks: 517 agenda joins that apply now, 2,459 after OPD's hash decision; export as CSV or SQL. | 135 |
| `media/05-parliaments.png` | gallery 5 | Parliaments: Bern (canton) has answer text on 11.2% of its 3,409 answered interventions, 99.9% after 3,025 proposed repairs. | 124 |
| `media/06-apertus.png` | gallery 6 | Apertus, pre-registered: 24/29 answer dates vs 2/29 for rules (P2), +23.4 points author-role recall (P10), 120/120 rows it cleared from review are answers (P7). | 160 |
| `media/07-scoreboard.png` | gallery 7 | Report Figure 5: where rules exist they are right on 135/154 with no model; on 15 new parliaments, answer dates: rules 2/29, Apertus 24/29. | 139 |
| `media/08-matrix.png` | gallery 8 | Report Figure 2: where each of the 17 fields comes from in OPD's data, for 41 of the 89 parliaments with interventions in OPD. | 126 |
| `media/09-about.png` | gallery 9 | About: each of the 17 fields with its verdict, whether it is fragile and what tested it (P8 or OPD's labels), and all 55 lists as downloads. | 140 |

## Checklist before submitting

- **Thumbnail:** upload `media/00-thumbnail.png`.
- **Gallery order:** `media/01-answer.png`, `02-lookup.png`, `03-repair.png`, `04-queue.png`, `05-parliaments.png`,
  `06-apertus.png`, `07-scoreboard.png`, `08-matrix.png`, `09-about.png`, each with its caption from section 6.
- **File to upload:** `track_2a/444_Report.pdf` (6 pages).
- **Prizes to tick (all three Track 2A prizes):** Hack Apertus Online - Winner Apertus Adoption: Academia;
  Hack Apertus Online - 1st Runner-up Apertus Adoption: Academia; Hack Apertus Online - 2nd Runner-up Apertus
  Adoption: Academia. Leave Own project, Red-Teaming and Swiss Voices unticked.
- **Video demo link:** optional for this challenge; paste the film's URL only if it is ready.
