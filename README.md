# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

**The answer in one sentence.** A common schema for the business of Swiss parliaments is feasible as a frame, but its
meaning is shared only in part: the answer date, procedural history, type, procedural state and decision outcome
differ by role between parliaments and must be split; the other 12 fields are shared by definition, their meaning
untested.

1. **Verdict.** 17 fields, each a value with its source (page and span, or the OpenParlData record) or a typed null,
   with dates kept apart by role. Meaning is tested for 0 of the 17; 5 are measured to need a role split. For the
   government recommendation, OpenParlData's label mapping is unambiguous (a string check), not a test of meaning.
2. **Ready for OpenParlData (OPD; awaits its hash decision for relinks).** Bern: 2,421 relinks, 48 fetches and 554
   `begin_date` corrections, keyed on OPD ids, with a dry-run SQL plan; OPD confirmed the bug (correspondence, 10 Oct
   2026; a published excerpt awaits OPD's consent). Federal: a fix for 29,946 documents that store Fedlex's
   "JavaScript required" page. Beyond: one list per parliament from 50 model-free source adapters.
3. **Census.** The registered census counts 16,749 of 91,268 interventions with a recorded written-answer event
   without answer text attached in OPD (1,422 of them were answered orally). Repairs are proposed for 9,720 (9,089 checked row by row, 592 agenda joins never
   sample-checked, 39 Bern rows in review); after them 92.3% have answer text.
4. **What Apertus adds.** As a closed-set verifier of the adapters' review queue it moves 214 answers into a separate
   tier; on a fresh blind test all 120/120 sampled promotions are the government's answer, and its date check is the
   gain over a trivial date match. On parliaments nobody wrote rules for it finds answer dates the rules miss (24/29
   vs 2/29). It is not more accurate than a well-instructed free prompt, and as a date reader it does not abstain
   reliably, so a person or a check confirms its suggestions.
5. **Not done.** Nothing runs at OPD yet; 5,077 answers are not found yet; tables, annexes and images are not
   extracted; every gold label comes from LLM agents, cross-checked by another vendor's model, not by a person.

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
