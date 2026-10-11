# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Every number is traced in
`claims.tsv` to its results file; `make claims` recomputes them all.

- **Answer.** A common schema is feasible as a frame, but its meaning is shared only in part: answer date, procedural
  history, type, procedural state and decision outcome differ by role between parliaments and must be split; the other
  12 of the 17 fields are shared by definition, their meaning untested (for the government recommendation OpenParlData
  (OPD)'s label mapping is unambiguous, a string check). Every value carries its source (page and position, or the OPD
  record) or a reason why it is empty.
- **Ready for OPD (awaits its hash decision for relinks).** In Bern, OPD attaches 229 of the 3,532 answers the canton
  publishes (6.5%), yet 96.1% are already in OPD. Checked against OPD's own copy: 2,421 relinks and 48 fetches, plus
  554 wrong Bern start dates, as a dry-run plan with before and after state. Federal: 29,946 documents whose text is
  Fedlex's "JavaScript required" page, resolved through Fedlex (40/50 on a sample). Also a list of 9 OPD vocabulary
  labels wrong as published. OPD confirmed the Bern bug (correspondence, 10 Oct 2026; a published excerpt awaits OPD's
  consent).
- **Census.** 16,749 of 91,268 interventions with a government answer have no answer text attached in OPD. Repairs
  are proposed for 9,720: 9,089 checked row by row, 592 agenda joins never sample-checked, 39 Bern rows in review;
  after them 92.3% have answer text. A blind audit (verdict-free packets with decoys; Claude blind by instruction)
  judged 197/200 counted adapter repairs to be the answer, with the date wrong or unsupported on 15/200; an LLM audit,
  not a human one. 5,077 answers are not found yet; 943 of them wait for a person.
- **What Apertus adds.** As a closed-set verifier of the review queue (P7, pre-registered) Apertus moves 214 answers
  into a separate tier; on a fresh blind test all 120 sampled promotions are the government's answer (Wilson lower
  bound 96.9%). Read against the base rate (86.7% of the queue are answers) its gain is the date check: 95.8% of its
  promotions are answers with a passing date, a trivial date match 73.2% (+22.7 points). On new parliaments it finds
  answer dates the rules miss (24/29 vs 2/29) and doubles submitter detection (12/40 to 24/40). The local 8B with the
  two-step reader dates 5 of 34 answerless documents, the plain pointer 18/34 (exploratory). Limits: no accuracy gain
  over a well-instructed free prompt (P2, P6, P7-H3), and every null-safety test on the 70B failed, though of the 53
  P2/P6 documents with no answer at all it dated none (its dates fell on answers that print no qualifying date).
- **Eight tests, frozen before any label.** All 74 labelling sessions ended before the labels reached GitHub; in the
  locked sets they started after the lock did. P1: rules alone right on 135/154, so by default no model runs. P2:
  rules find 2/29 answer dates on 15 unseen parliaments. P3, P3b: whole affairs. P4: 99 affairs rebuilt from minutes,
  none invented. P5: Q/A pairing at precision 0.83, recall 0.67 (partial). P6: no registered hypothesis held. P7: H1
  holds (120/120).
- **Labels.** Two AI annotators label blind, a third settles ties, raw files are committed. Qwen-SEA-LION (AI
  Singapore) relabelled P1, P2, P6 and P7 blind: dates agree with κ 0.80, 0.87 and 0.86, P7 185/190; no registered
  result changes.
- **Which model, what it costs.** Evaluation used Apertus v1.5 70B weights served by Public AI (inferred from the
  served fingerprint). The 8B (a community 4-bit build) runs on one CPU machine, 180 s per document. Advice: run
  without a model; for suggestions the 8B fully local, or the 70B on servers the operator chooses (USD 0.59 per 1,000
  documents the rules leave open).
- **Operations.** `make run` (Docker, CPU) re-derives the rules arm from the PDFs and replays the tests (26/26
  locally). Two consecutive real nights in the Docker setup: 86 min, then 6.6 min on the first night's state, 0
  alerts. We found and disclosed our own robots.txt bug: 147 Ticino URLs fetched on disallowed paths; fixed, and
  every fetch now goes to OPD's own copy. Not done: nothing runs at OPD yet; tables and annexes are not extracted.
  Claude Code agents wrote the code and the labels.
