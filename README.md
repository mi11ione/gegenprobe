# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

**Can one schema hold Swiss parliamentary business? Yes, if its fields carry roles.**

- **Shared:** one schema of 17 fields for communal, cantonal and federal business; every value carries its role and
  source, every gap a typed reason.
- **Needs roles: 10 fields:** "answer date" is the government's decision, its letter or, in 7 parliaments, mostly the
  submission date.
- **Body-specific: 1 field and 3 constructs:** the submission date in Vernier and Lausanne; oral answers, executive
  business, councils that publish only minutes.
- **Untested: 6 fields,** defined once in v0.1; meaning is measured for the other 11 (OPD's labels and P8: 66 affairs,
  11 parliaments).

**Delivered:** repairs for 9,720 answers keyed on OPD ids, every one from model-free rules; schema v0.2 with the roles;
a converter that gives every value its page and span; a nightly job. Apertus only picks values printed in the document,
and code locates them (70B weights via the Public AI gateway; local 8B on CPU).

| | |
|---|---|
| **92.3%** | of interventions with a recorded government answer would have answer text once the proposed repairs are applied, up from 81.6% today: 91.6% from row-checked repairs + 0.7 points from the 592 agenda joins and 39 review rows |
| **9,720** | answers with a model-free repair proposed to OPD, keyed on OPD ids; the Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation |
| **10 of 17** | fields are shared once their roles are explicit; 1 is body-specific; 6 are not yet tested for meaning |
| **53/62** | documents exact in 15 parliaments nobody wrote rules for when Apertus picks the answer date among the printed dates, against 44/62 for the best no-model baseline |
| **186** | affairs from 26 parliaments, communal, cantonal and federal, validate in schema v0.2 |

<sub>Sources: 92.3% and 9,720 from the census and the repair lists (no model); 10 of 17 from OPD's labels and P8
(pre-registered); 53/62 from P2, post hoc (McNemar p = 0.012, parliament-cluster p = 0.031); 186 from P3, P3b, P5, P8
and the federal cell, whose 15 affairs are exploratory. P1–P8 are the nine pre-registered tests (P3b replicates P3).</sub>

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections (OPD confirmed the bug; correspondence, 10 Oct
  2026), per-parliament lists from 50 model-free source adapters, a vocabulary error list and a Fedlex resolver for
  29,946 federal documents. The only open decision is OPD's hash rule for relinks.
- **Sovereign and cheap to run:** the default runs no model and only reads public sources. A first network night took
  86 min, the next 6.6 min.
- **Checked:** nine tests, each frozen by hash before its labels; `make claims` recomputes every number in the README,
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
