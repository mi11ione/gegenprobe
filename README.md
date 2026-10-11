# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

**The answer.** A common schema for the business of Swiss parliaments works if it carries roles: "answer date" is the
government's decision in some parliaments, the letter or registration date in others and the submission date in a few.
Gegenprobe's schema v0.1 gives every date its role, every value its source (page and span, or the OpenParlData record)
and every empty field a typed reason.

| | |
|---|---|
| **92.3%** | of interventions with a written government answer have answer text once the counted repairs are applied |
| **9,720** | answers with a repair proposed to OpenParlData (OPD), keyed on OPD ids, with a dry-run apply plan for Bern |
| **214** | review-queue answers Apertus recovers as a closed-set verifier; all 120/120 sampled are the government's answer |
| **24/29** | answer dates Apertus finds in parliaments nobody wrote rules for; the rules find 2/29 |

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections (OPD confirmed the bug; correspondence, 10 Oct
  2026), per-parliament lists from 50 model-free source adapters, a vocabulary error list and a Fedlex resolver for
  29,946 federal documents. The only open decision is OPD's hash rule for relinks.
- **Auditable by construction:** every Apertus value is a date or phrase printed in the document, with page and span;
  the default runs no model, and Apertus suggestions go to a reviewer.
- **Pre-registered:** eight tests, each frozen by hash before its labels; every number in the documents is recomputed
  from its results file by `make claims`.

The eCH expert group's page: [`track_2a/docs/ech-onepager.md`](track_2a/docs/ech-onepager.md).

- **Evidence site:** https://gegenprobe.mi11ion.io (also written to `track_2a/out/site/index.html` by `make run`)
- **Project:** [`track_2a/`](track_2a/) — start with [`track_2a/README.md`](track_2a/README.md); technical report
  [`track_2a/technical_report.md`](track_2a/technical_report.md) (PDF: `track_2a/444_Report.pdf`)

```bash
cd track_2a && make run      # Docker, CPU, clean checkout
```

Code: Apache-2.0 ([LICENSE](LICENSE)). Report: CC-BY-4.0 ([track_2a/docs/LICENSE-report.txt](track_2a/docs/LICENSE-report.txt)).
Data in `track_2a/data/` and results in `track_2a/results/`: CDLA-Permissive-2.0
([data/LICENSE](track_2a/data/LICENSE), [results/LICENSE](track_2a/results/LICENSE)). Source: OpenParlData.ch (CC BY 4.0).
