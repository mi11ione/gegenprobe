# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

**A common schema for Swiss parliamentary business works if its fields carry roles, and the proposed repairs, keyed on
OpenParlData (OPD) ids, would raise the share of interventions with a recorded government answer that have answer text
from 81.6% to 92.3%.** Of the 17 fields, 10 need roles (8 robust, 2 fragile), 1 is body-specific,
and 6 are defined once in v0.1 (their meaning is the next test). "Answer date" is the government's decision in some
parliaments, the letter or registration date in others and the submission date in a few, and a pre-registered meaning
test (P8: 66 affairs, 11 parliaments) finds roles in authorship (sole author, joint authors, first signatory,
parliamentary group), signatories, the instrument behind a harmonised type and the date a submission carries.
Gegenprobe's schema v0.1 gives every date its role, every value its source (page and span, or the OPD record) and
every empty field a typed reason; schema v0.2 adds P8's roles and validates 171 affairs, 105 of them the
converter's own records.

| | |
|---|---|
| **92.3%** | of interventions with a recorded government answer would have answer text once the proposed repairs are applied, up from 81.6% attached today |
| **9,720** | answers with a repair proposed to OPD, keyed on OPD ids, with a self-checking dry-run SQL plan for Bern |
| **5 of 7** | fields v0.1 defines once depart from one meaning under both checks (P8); schema v0.2 carries their roles |
| **+22.7** | points for Apertus as review-queue verifier: the right answer with a checkable date, over a no-model date match (P7-H4, weighted as registered; unweighted +7.5); 120/120 promotions are answers (H1) |
| **24/29** | answer dates Apertus finds in 15 parliaments nobody wrote rules for (P2), where the rules find 2/29 |

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections (OPD confirmed the bug; correspondence, 10 Oct
  2026), per-parliament lists from 50 model-free source adapters, 27 with counted repairs, a vocabulary error list and a Fedlex resolver for
  29,946 federal documents. The only open decision is OPD's hash rule for relinks.
- **Auditable by construction:** every value Apertus extracts is a date or phrase printed in the document, with page
  and span; its yes/no answers and category labels are judgements a person reviews. The default runs no model.
- **Sovereign and cheap to run:** the default only reads public sources; Apertus runs through the Public AI gateway or
  locally (8B GGUF, CPU). A first network night took 86 min, the next 6.6 min.
- **Pre-registered:** nine tests, each frozen by hash before its labels (P1's hypothesis script followed its labels and
  its rules entered with its sample, both logged: D4, D12). `make claims` recomputes every claimed number from its
  results file and checks it where it appears.

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
