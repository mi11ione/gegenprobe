# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

**The answer.** A common schema for the business of Swiss parliaments works if it carries roles: "answer date" is the
government's decision in some parliaments, the letter or registration date in others and the submission date in a few.
Gegenprobe's schema v0.1 gives every date its role, every value its source (page and span, or the OpenParlData record)
and every empty field a typed reason.

| | |
|---|---|
| **92.3%** | of interventions with a written government answer have answer text after every counted repair, up from 81.6% attached today (85.6% from what OPD already holds, 88.3% after its hash decision for the Bern relinks) |
| **9,720** | answers with a repair proposed to OpenParlData (OPD), keyed on OPD ids, with a dry-run apply plan for Bern |
| **+19.6 points** | date-checked precision when Apertus chooses the printed answer date, over the no-model date rule (P7: 95.8% vs 76.2%; parliament-cluster 95% interval [0.9, 42.8]); it fills a tier of 214 review-queue answers |
| **24/29** | answer dates Apertus finds in 15 parliaments nobody wrote rules for, as many as a free prompt, every value a printed date; the latest printed date finds 22 but dates 31 of 33 answerless documents |

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections (OPD confirmed the bug; correspondence, 10 Oct
  2026), per-parliament lists from 50 model-free source adapters, a vocabulary error list and a Fedlex resolver for
  29,946 federal documents. The only open decision is OPD's hash rule for relinks.
- **Auditable by construction:** every value Apertus extracts is a date or phrase printed in the document, with page
  and span; its yes/no answers and category labels are judgements a person reviews. The default runs no model.
- **Pre-registered:** eight tests, each frozen by hash before its labels; every measured number in the README, the
  report and the form notes is recomputed from its results file by `make claims`.

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
