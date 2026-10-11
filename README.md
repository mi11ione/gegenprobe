# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

1. **Verdict.** The frame of a common schema for the business of Swiss parliaments is feasible: 17 fields, each a value
   with its source (page and span, or the OpenParlData record) or a typed null, with dates kept apart by role. Meaning
   is verified across parliaments for 1 of the 17 fields; 5 are measured to need a role split; 11 are shared by
   definition, untested.
2. **What OpenParlData (OPD) can apply tomorrow.** Bern: 2,421 relinks, 48 fetches and 554 `begin_date` corrections,
   keyed on OPD ids, with a dry-run SQL plan; OPD confirmed the bug. Beyond Bern: one list per parliament from 50
   model-free source adapters.
3. **Census.** The registered census counts 16,749 of 91,268 interventions with a written government answer without
   answer text attached in OPD; 2,177 are in OPD under a heading the census does not recognise, so at most 14,572 lack
   text. Verified repairs are proposed for 9,720; after them 92.3% have answer text.
4. **What Apertus adds.** On parliaments nobody wrote rules for it finds answer dates the rules miss (24/29 vs 2/29),
   each a printed date with page and span. It is not more accurate than the same model asked freely with null allowed,
   and it still dates some answerless documents, so a person confirms its suggestions.
5. **Not done.** Nothing runs at OPD yet; 5,007 written answers still need adapters; tables, annexes and images are not
   extracted; every gold label comes from LLM agents, cross-checked by another vendor's model, not by a person.

The eCH expert group's page: [`track_2a/docs/ech-onepager.md`](track_2a/docs/ech-onepager.md).

- **Evidence site:** https://gegenprobe.mi11ion.io (also written to `track_2a/out/site/index.html` by `make run`)
- **Project:** [`track_2a/`](track_2a/) — start with [`track_2a/README.md`](track_2a/README.md); technical report
  [`track_2a/technical_report.md`](track_2a/technical_report.md) (PDF: `track_2a/444_Report.pdf`)

```bash
cd track_2a && make run      # Docker, CPU, clean checkout
```

Code: Apache-2.0 ([LICENSE](LICENSE)). Report: CC-BY-4.0 ([track_2a/docs/LICENSE-report.txt](track_2a/docs/LICENSE-report.txt)).
Data in `track_2a/data/`: CDLA-Permissive-2.0 ([track_2a/data/LICENSE](track_2a/data/LICENSE)).
