# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

For management and a chancellery: [one page](track_2a/docs/decision.md) with what runs, what leaves the machine, the
cost, OPD's one decision and who reviews.

**For OPD, in three lines:**
1. **Apply now:** repair lists keyed on your ids, as dry-run plans; 3,621 repairs need neither a decision nor a fetch.
2. **Needs one decision:** your hash rule for relinked documents, which the 2,421 ready Bern relinks follow. OPD
   confirmed the Bern linking bug (correspondence, 10 Oct 2026).
3. **Research:** schema v0.2 and the converter's roles (drafts for the eCH group); Apertus as a reviewer's aid.

**Can one schema hold Swiss parliamentary business? Yes, if each field says which role its value plays** (e.g. "answer
date" = the government's decision, its letter or the submission date). Tested on OPD's five intervention types
(interpellation, motion, postulate, question, question time): 198,594 of its 325,691 affairs; the "Yes" covers the
affair's skeleton of 17 fields. Outside interventions the skeleton does not carry over as is (P11, exploratory, 15
affairs): 7 of the 17 fields fit unchanged, 4 answer fields do not apply, and 6 need roles interventions lack, chiefly
the executive acting as proposer (adopting, endorsing and signing its own proposal).

- **Shared:** one schema of 17 fields for communal, cantonal and federal business; every value carries its role and
  source, every gap a typed reason.
- **Needs roles: 10 fields,** e.g. "answer date" is the government's decision, its letter or, in 7 parliaments,
  mostly the submission date.
- **Body-specific: 1 field and 2 constructs:** the submission date (in Vernier and Lausanne OPD's submission date is
  printed in neither document; they print the member's signing or lodging date 2 to 28 days earlier); oral answers,
  councils that publish only minutes. Parliamentary initiatives (5,817) and government business (37,864) are outside
  the tested scope.
- **Untested: 6 fields,** defined once in v0.1; whether each means the same everywhere is the next test.

**Delivered:** repairs for 9,580 answers keyed on OPD ids, every one from model-free rules; schema v0.2 with the roles;
a converter that gives every value its page and span; a nightly job. Apertus only picks values printed in the document,
and code locates them (70B weights via the Public AI gateway; local 8B on CPU). **Runtime external services:** none by
default (public sources only); Apertus review mode sends document text to the Public AI gateway, or nothing with the
local 8B. **Cost:** the rules take about 0.5 CPU-hours for all 902,754 documents in OPD's export, about 5 at ten times
OPD's volume; review mode costs USD 0.59 per 1,000 residue documents on the 70B.

| | |
|---|---|
| **92.1%** | of interventions with a recorded government answer would have answer text once the proposed repairs are applied, up from 81.6% today: 91.5% from row-checked repairs + 0.6 points from the 592 agenda joins and 39 review rows |
| **9,580** | answers with a model-free repair proposed to OPD, keyed on OPD ids; the Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation |
| **10 of 17** | fields are shared once their roles are explicit (8 robust + 2 fragile; 6 from the role test, P8, registered, and 4 from OPD's label vocabularies, post hoc); 1 is body-specific; 6 are not yet tested for meaning |
| **186** | v0.2 records from 26 parliaments validate: the converter's 120 (105 cantonal and communal + 15 federal, 23 parliaments) and P8's 66 gold records (11 parliaments) |

| Apertus, where nobody wrote rules | what Apertus adds | what the model-free baseline reaches |
|---|---|---|
| **24/29** answer dates on new layouts (the date test, P2; 15 parliaments) | exact on 53/62 documents against the baseline's 44/62: right on 10 where the baseline is wrong, the reverse on 1 (exact McNemar p = 0.0117; parliament-resampled interval of the difference [0.056, 0.243]; post hoc); 4 of its 7 wins on answered documents are documents OPD types as interventions, where that baseline returns nothing by construction | the latest date on answer-typed documents: 18/29 answer dates, 44/62 exact; registered: the rules 2/29 |
| **50/141** author roles in 14 parliaments (the author test, P10) | Apertus adds precision deciding who is an author (+7.3 points, post hoc) | Rules 17/141; most of the gain comes from the model-free candidate finder (document order 52/141) |
| **139/154** answer dates where rules exist (P1; rules, then Apertus) | about one document | a model-free cascade (post hoc): 138/154 |
| **120/120** sampled review-queue promotions are answers (P7, registered) | the date: the gold answer date on 113/120 of its promotions, the rule's on 127/146 (post hoc, not paired) | a no-model exact-date match: answers on 146/146, 206 of the 478 frame rows promoted against Apertus's 135 (post hoc) |

<sub>Sources: 92.1% and 9,580 from the census and the repair lists (no model); 186 from
`track_2a/results/schema/v0_2/validation_all.json` (the 15 federal records from an exploratory cell); 24/29 from P2,
registered against the rules (the baselines post hoc, proposed in review); 50/141 from P10, registered (recall +23.4
points over the rules, Holm p = 0.032), level with OPD's contributor list
(37/141; H3a, Holm p = 0.17). Every committed gateway response (17,720) comes from one build, Apertus 70B by inference
(the gateway labelled it 8B; fingerprint check in `track_2a/docs/evaluation.md`); on 12 Oct 2026 Public AI switched
the route to another build and back the same night, and the build guard caught it live; review mode runs again on the
registered build. P1–P8 and P10 are the ten pre-registered tests (P3b replicates P3).</sub>

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections, per-parliament lists from 50 model-free
  source adapters, a vocabulary error list and a Fedlex resolver for 29,946 federal documents. The only open decision
  is OPD's hash rule for relinks.
- **Sovereign and cheap to run:** the default runs no model and only reads public sources. A first network night took
  86 min, the next 6.6 min.
- **Italian and outside interventions (P11, exploratory):** the Apertus pointer is exact on 12/12 Italian answers
  (the latest printed date on the answer 9/12, the rules 8/12); government business needs roles interventions lack.
- **Checked:** ten tests, each frozen by hash before its labels; `make claims` recomputes every number in the README,
  the report and the form from its results file and fails on any mismatch.

The eCH expert group's page, with a per-field recommendation from P8: [`track_2a/docs/ech-onepager.md`](track_2a/docs/ech-onepager.md).

- **Evidence site:** https://gegenprobe.mi11ion.io (also written to `track_2a/out/site/index.html` by `make run`)
- **Project:** [`track_2a/`](track_2a/) — start with [`track_2a/README.md`](track_2a/README.md); technical report
  [`track_2a/technical_report.md`](track_2a/technical_report.md) (PDF: `track_2a/444_Report.pdf`)

```bash
cd track_2a && make run      # Docker, CPU, clean checkout
```

Code: Apache-2.0 ([LICENSE](LICENSE)). Report: CC-BY-4.0 ([track_2a/docs/LICENSE-report.txt](track_2a/docs/LICENSE-report.txt)).
Data in `track_2a/data/` and results in `track_2a/results/`: CDLA-Permissive-2.0
([data/LICENSE](track_2a/data/LICENSE), [results/LICENSE](track_2a/results/LICENSE)). Source: OpenParlData.ch (CC BY 4.0).
