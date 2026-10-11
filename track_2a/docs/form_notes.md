# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Every number is traced in
`claims.tsv` to its results file; `make claims` recomputes them all.

- **Verdict.** The frame of a common schema is feasible: 17 fields, each a value with its source (page and position,
  or the OpenParlData (OPD) record) or a reason why it is empty, with dates kept apart by role ("answer date" alone is
  three dates). Meaning is verified across parliaments for 1 of the 17 fields; 5 are measured to need a role split; 11
  are shared by definition, untested. 4 fields are in OPD's records almost everywhere, 13 partly or only in the PDF.
- **What OPD can apply tomorrow.** In Bern, OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet
  3,394 (96.1%) are already in OPD. Checked against OPD's own copy: 2,421 relinks and 48 fetches, plus 554 wrong Bern
  start dates, as a dry-run plan with before and after state. OPD confirmed the bug (correspondence, 10 Oct 2026; a
  published excerpt awaits OPD's consent).
- **Census.** The registered census counts 16,749 of 91,268 interventions with a government answer without answer text
  attached in OPD. 2,177 of them are in OPD under a heading the census does not recognise, so at most 14,572 lack text
  (13,150 written answers). Readers for 50 parliaments and the Bern routes propose verified repairs for 9,720; after
  them 92.3% have answer text; 5,007 still need an adapter. A blind audit (verdict-free packets with decoys) judged
  197/200 counted repairs to be the answer; it is an LLM audit, not a human one.
- **Seven tests, frozen before any label.** All 74 labelling sessions started after the frozen tests reached GitHub and
  ended before the labels did. P1, 154 documents: rules alone right on 135, so by default no model runs. P2, 62
  documents from 15 parliaments without rules: rules find 2/29 answer dates, Apertus 24/29. P3, P3b: whole affairs;
  Apertus fills answer dates the rules miss (22/27 to 27/27). P4: 99 affairs rebuilt from one commune's minutes, none
  invented, 99/120 found. P5, 40 affairs: rules pair each question with its answer at precision 0.83, recall 0.67
  (partial; not yet when parliaments are resampled). P6: no registered hypothesis held.
- **What Apertus adds, plainly.** It finds dates the rules miss on new parliaments, and every value it returns is a
  printed date with its page. It is not more accurate than the same model asked freely with null allowed (P6: 62/68
  free vs 59/68), which also almost never invents a date. It still dates some documents without an answer (5 of 34
  in P6), so a person confirms every suggestion. On all 68 P6 documents rules then Apertus win 11 and lose 5
  against rules alone (p 0.21).
- **Labels.** Two AI annotators label blind, a third settles ties, raw files are committed. Qwen-SEA-LION (AI
  Singapore) relabelled P1, P2 and P6 blind: dates agree with κ 0.80, 0.87 and 0.86, no registered result changes.
  OPD's own dates match 37 of 44 checkable P1 dates and 10/10 in P6.
- **Which model, what it costs.** Evaluation used Apertus v1.5 70B weights served by Public AI (inferred from the
  served fingerprint; the endpoint name says 8b). The 8B (a community 4-bit build) runs on one CPU machine, 180 s per
  document; on new parliaments it finds 15 of 21 answer dates (70B: 16) but dates 11 of 31 documents without an
  answer (70B: 4); its P6 run is still running. Advice: run without a model; for suggestions the 8B fully local, or the
  70B on servers the operator chooses (USD 0.59 per 1,000 documents the rules leave open).
- **Operations.** `make run` (Docker, CPU) re-derives the rules arm from the PDFs and replays all seven tests (26/26
  locally). One real night against OPD's live data took 83 min and reproduced the Bern list; a two-night Docker run is
  running. We found and disclosed our own robots.txt bug: we fetched 147 Ticino URLs on paths its robots.txt disallows;
  fixed, and every fetch now goes to OPD's own copy. Not done: nothing runs at OPD yet; tables and annexes are not
  extracted. Claude Code agents wrote the code and the labels.
