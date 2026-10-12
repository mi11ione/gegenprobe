# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

**Start here:**
- **Evidence site:** https://gegenprobe.mi11ion.io (also written to `track_2a/out/site/index.html` by `make run`)
- **Technical report:** [`track_2a/technical_report.md`](track_2a/technical_report.md) (PDF: `track_2a/444_Report.pdf`)
- **One page for OPD's management and a chancellery:** [English](track_2a/docs/decision.md) ·
  [Deutsch](track_2a/docs/decision_de.md); for a data protection officer,
  [a register checklist](track_2a/docs/dpo_checklist.md) (EN/DE)
- **Replay:** `cd track_2a && make run` (Docker, CPU, clean checkout); the project README:
  [`track_2a/README.md`](track_2a/README.md)

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

- **Shared:** one schema of 17 fields for communal, cantonal and federal business; in the converter's 120 records every
  value carries its role and source, every gap a typed reason.
- **Needs roles: 10 fields,** e.g. "answer date" is the government's decision, its letter or, in 7 parliaments,
  mostly the submission date.
- **Body-specific: 1 field and 2 constructs:** the submission date (in Vernier and Lausanne OPD's submission date is
  printed in neither document; they print the member's signing or lodging date 2 to 28 days earlier); oral answers,
  councils that publish only minutes. Parliamentary initiatives (5,817) and government business (37,864) are outside
  the tested scope.
- **Untested: 6 fields,** defined once in v0.1; whether each means the same everywhere is the next test.

**Delivered:** repairs for 9,580 answers keyed on OPD ids, every one from model-free rules; schema v0.2 with the roles;
a converter whose records give every value its page and span or its source record; a nightly job. Apertus only picks values printed in the document,
and code locates them (70B weights via the Public AI gateway; local 8B on CPU). **Runtime external services:** none by
default (public sources only); Apertus review mode sends document text to the Public AI gateway, or nothing with the
local 8B. **Cost:** the rules take about 0.5 CPU-hours for all 902,754 documents in OPD's export, about 5 at ten times
OPD's volume; review mode costs USD 0.59 per 1,000 residue documents on the 70B.

| | |
|---|---|
| **92.1%** | of interventions with a recorded government answer would have answer text once the proposed repairs are applied, up from 81.6% today: +10.5 points, all from the 9,580 repairs (the 8,949 row-checked ones reach 91.5%; the 592 agenda joins and 39 Bern rows in review add the rest) |
| **9,580** | answers with a model-free repair proposed to OPD, keyed on OPD ids; the Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation |
| **10 of 17** | fields are shared once their roles are explicit (8 robust + 2 fragile; 6 from the role test, P8, registered, and 4 from OPD's label vocabularies, post hoc); 1 is body-specific; 6 are not yet tested for meaning |
| **186** | v0.2 records from 26 parliaments validate: the converter's 120 (105 cantonal and communal + 15 federal, 23 parliaments) and P8's 66 gold records (11 parliaments) |

| What Apertus adds where nobody wrote rules | test | scope |
|---|---|---|
| **24/29** answer dates in 15 parliaments nobody wrote rules for; the rules, written for other layouts, find 2/29 | the date test, P2 | registered |
| **+23.4 points** author-role recall over the rules in 14 parliaments without rules (50/141 pairs vs 17/141); precision not worse | the author test, P10 (H1, H2) | registered |
| **120/120** sampled review-queue promotions are the government's answer | the verifier test, P7 (H1) | registered |
| **12/12** Italian interventions exact on the answer date (10 printed dates, 2 right nulls), five parliaments | P11 | exploratory |

Every value Apertus returns is a printed value located by code (62/62, 32/32 and 35/35 on P1, P2 and P6, where free
prompting's quotes check out on 30/60 and 17/32), and its confidence margin ranks the documents the rules leave open
for review: on layouts no rules cover it puts wrong values first with AUROC 0.90, above every no-model ranking signal
we computed (at most 0.58; post hoc).

<sub>Sources: 92.1% and 9,580 from the census and the repair lists (no model); 186 from
`track_2a/results/schema/v0_2/validation_all.json` (the 15 federal records from an exploratory cell); 24/29 from P2
and +23.4 points from P10 (Holm p = 0.032), registered; the margin from `track_2a/results/eval/margin_vs_nomodel.json`;
the baselines proposed in review are in `track_2a/docs/evaluation.md`. Every committed gateway response (17,720) comes
from one build, Apertus 70B by inference (the gateway labelled it 8B; fingerprint check in `track_2a/docs/evaluation.md`);
on 12 Oct 2026 Public AI switched the route to another build and back the same night, and the build guard caught it
live; review mode runs again on the registered build. P1–P8 and P10 are the ten pre-registered tests (P3b replicates P3).</sub>

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections, per-parliament lists from 50 model-free
  source adapters, a vocabulary error list, a list of 7,876 answered interventions whose OPD state still reads
  "submitted", and a Fedlex resolver for 29,946 federal documents. The only open decision is OPD's hash rule for
  relinks.
- **Sovereign and cheap to run:** the default runs no model and only reads public sources. A first network night took
  86 min, the next 6.6 min; on a real two-night Docker pair with the fixed ledger, night 2 kept night 1's verdicts.
- **Italian and outside interventions (P11, exploratory):** the Apertus pointer is exact on 12/12 Italian answers
  (the latest printed date on the answer 9/12, the rules 8/12); government business needs roles interventions lack.
- **Checked:** ten tests, each frozen by hash before its labels except P1's hypothesis script and rules (D4, D12); `make claims` recomputes every number in the README,
  the report and the form from its results file and fails on any mismatch.

The eCH expert group's page, with a per-field recommendation from P8: [`track_2a/docs/ech-onepager.md`](track_2a/docs/ech-onepager.md);
mappings to Popolo, Akoma Ntoso, Parla-CLARIN and OParl: [`track_2a/docs/mapping.md`](track_2a/docs/mapping.md).

Code: Apache-2.0 ([LICENSE](LICENSE)). Report: CC-BY-4.0 ([track_2a/docs/LICENSE-report.txt](track_2a/docs/LICENSE-report.txt)).
Data in `track_2a/data/` and results in `track_2a/results/`: CDLA-Permissive-2.0
([data/LICENSE](track_2a/data/LICENSE), [results/LICENSE](track_2a/results/LICENSE)). Source: OpenParlData.ch (CC BY 4.0).
