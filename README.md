# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

**The answer.** A common schema for the business of Swiss parliaments works if it carries roles: of its 17 fields, 10
need roles, 6 keep one definition and 1, the submission date, is body-specific in 2 parliaments. Roles matter beyond
dates: "answer date" is the government's decision in some parliaments, the letter or registration date in others and
the submission date in a few, and a pre-registered meaning test (P8: 66 affairs, 11 parliaments) finds the same for
authorship (sole author, joint authors, first signatory, parliamentary group), signatories, the instrument behind a
harmonised type and the date a submission really carries. Gegenprobe's schema v0.1 gives every date its role, every
value its source (page and span, or the OpenParlData record) and every empty field a typed reason; schema v0.2 ships P8's
roles, and all 66 P8 affairs validate in it.

| | |
|---|---|
| **92.3%** | of interventions with a recorded government answer would have answer text once the proposed repairs are applied, up from 81.6% attached today (85.6% from what OPD already holds, 88.3% after its hash decision for the Bern relinks) |
| **9,720** | answers with a repair proposed to OpenParlData (OPD), keyed on OPD ids, with a dry-run apply plan for Bern |
| **120/120** | sampled Apertus promotions judged the government's answer by blind AI annotators in a pre-registered test (P7-H1, Wilson 95% [96.9, 100]); 95.8% are answers whose printed answer date passes the date check, +22.7 points over a trivial date match, weighted, as registered (H4, [10.2, 34.3]; unweighted +7.5); a tier of 214 review-queue answers |
| **24/29** | answer dates Apertus finds in 15 parliaments nobody wrote rules for (P2), every value a printed date; on the 33 answerless documents it puts a date on 4, the latest printed date on 31 (a free prompt: 22/29 as registered, 24/29 null-allowed and 25/29 plain once re-parsed) |
| **5 of 7** | fields v0.1 defines once depart from one meaning under both checks (P8): submitter, co-signatories, type and language split by role; the submission date is body-specific (in Vernier and Lausanne mostly a date the documents do not print); schema v0.2 carries these roles |

- **Ready for OPD:** Bern relinks, fetches and `begin_date` corrections (OPD confirmed the bug; correspondence, 10 Oct
  2026), per-parliament lists from 50 model-free source adapters, 27 with counted repairs, a vocabulary error list and a Fedlex resolver for
  29,946 federal documents. The only open decision is OPD's hash rule for relinks.
- **Auditable by construction:** every value Apertus extracts is a date or phrase printed in the document, with page
  and span; its yes/no answers and category labels are judgements a person reviews. The default runs no model.
- **Pre-registered:** nine tests, each frozen by hash before its labels (P1's hypothesis script followed its labels and
  its rules entered with its sample, both logged: D4, D12). `make claims` recomputes every claimed number from its
  results file and checks it where it appears; in the project README's headline block, the report's summary and the
  form notes it checks every number token by token.

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
