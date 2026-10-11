# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Every number is traced in
`claims.tsv` to its results file; `make claims` recomputes them all.

- **Answer.** A common schema for Swiss parliamentary business works if it carries roles. "Answer date" means the
  government's decision in some parliaments, the letter or registration date in others, and in 7 parliaments mostly
  the submission date. Schema v0.1 gives every date its role, every value its source (page and position, or the
  OpenParlData (OPD) record) and every empty field a reason. Five fields are measured to need such a role split; the
  other twelve are defined once, and a field-by-field meaning test is the next step with the eCH group.
- **What the census shows.** Of 91,268 interventions with a written government answer, 92.3% have answer text once our
  counted repairs are applied (82.3% today). At most 13,150 written answers lack text. 2,177 "missing" answers were in
  OPD all along, under a heading the census did not recognise. Answer times depend on what the date means: median 112
  days where it is the verified decision date, 39 where it is a publication-like date.
- **Ready for OPD.** Repairs proposed for 9,720 answers, keyed on OPD ids. In Bern, OPD attaches 229 of the 3,532
  answers the canton publishes (6.5%), yet 96.1% are already in OPD: 2,421 relinks, 48 fetches and 554 corrected start
  dates, with a dry-run SQL plan. OPD confirmed the Bern bug (correspondence, 10 Oct 2026); the only open decision is
  its hash rule for relinks. Also: per-parliament lists from 50 model-free source adapters (a blind audit judged
  197/200 to be the answer), 9 OPD vocabulary labels wrong as published, and a Fedlex resolver for 29,946 federal
  documents that store a "JavaScript required" page.
- **What Apertus adds.** It picks the right printed date where the rules cannot. It never writes a free value: it
  chooses a date or phrase printed in the document, and code records page and position. As a closed-set verifier of
  the review queue (P7, pre-registered) it recovers 214 answers; on a blind test all 120/120 sampled were judged the
  government's answer (48/48 without its largest parliament). Its choice of date lifts the share with a correct,
  rule-passing date by 20.9 points over the rules alone (post hoc). In parliaments nobody wrote rules for it finds
  24/29 answer dates (rules 2/29), and it doubles submitter detection (12/40 to 24/40). It matches the accuracy of a
  well-instructed free prompt, with provenance guaranteed by construction. By design its suggestions go to a
  reviewer; the rules run unattended.
- **Sovereign by default.** No external service is needed at runtime beyond OPD's exports and the parliaments' own
  sites. The optional review model is the operator's choice: Public AI, or the Apertus 8B on one CPU machine (180 s
  per document). On new parliaments the 8B beats the rules 13 to 0 on documents with an answer date, and its
  two-step reader cuts dates on documents without an answer date from 18/34 to 5/34 (exploratory).
- **Eight tests, frozen before any label.** P1: rules alone right on 135/154, so by default no model runs. P2: on 15
  unseen parliaments Apertus 24/29 answer dates, rules 2/29. P3 and P3b: whole affairs, replicated on fresh ones. P4:
  99 affairs rebuilt from minutes, none invented. P5: Q/A pairing at precision 0.83, recall 0.67 (partial tier). P6:
  no registered hypothesis held, so the shipped reader stays. P7: H1 holds (120/120). All 9 held results survive a
  Holm correction over all 20 tests. Null-safety tests on the
  70B failed (P1, P2, P6), which is why Apertus only suggests.
- **Labels without human labelling, by design.** Two blind AI annotators label, a third settles ties, raw files are
  committed, and all 84 labelling sessions ended before the labels reached GitHub. Qwen-SEA-LION (AI Singapore)
  relabelled P1, P2, P6 and P7 blind: dates agree with κ 0.80, 0.87 and 0.86, P7 185/190; no registered result
  changes. Non-LLM sources agree too: publishers' titles 20/20.
- **Operations.** `make run` (Docker, CPU) recomputes the census, re-derives the rules arm from the PDFs, replays the
  tests and checks every number. Two consecutive real nights in Docker: 86 min, then 6.6 min, 0 alerts; night 2
  exposed a ledger bug, which we fixed and test over two nights. We found, audited and fixed our own robots.txt bug;
  every fetch now fails closed (docs/incidents.md). Next: the lists and the nightly job at OPD, tables and annexes,
  and the meaning test with eCH. Claude Code agents wrote the code and labels.
