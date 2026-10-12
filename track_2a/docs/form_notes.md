# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. `make claims` recomputes
every number here from its results file and fails on any mismatch, or on a number or scope word not bound to its claim.

- **Answer.** Can one schema hold Swiss parliamentary business? Yes, if each field says which role its value plays
  (e.g. "answer date" = the government's decision, its letter or the submission date). Tested on OPD's five
  intervention types: 198,594 of its 325,691 affairs; the "Yes" covers the affair's 17-field skeleton.
  Needs roles: 10 fields (8 robust + 2 fragile; 6 from the role test, P8, registered, 4 from OPD's labels, post hoc).
  Body-specific: 1 field and 2 constructs (the submission date: in Vernier (5/5) and Lausanne (3/5) OPD's submission
  date is printed in neither document; they print the member's signing or lodging date 2 to 28 days earlier; oral
  answers, minutes-only councils). Untested: 6 fields, defined once in v0.1. Outside interventions the skeleton does
  not carry over as is (P11, exploratory, 15 affairs: 6 fields need roles interventions lack, 4 answer fields do not
  apply).
- **Delivered.** Repairs for 9,580 answers keyed on OpenParlData (OPD) ids, every one from model-free rules; schema
  v0.2 with the roles; a converter that gives every value its page and span; a nightly job. Apertus only picks values
  printed in the document, and code locates them.
- **Headline.** 92.1% of interventions with a recorded government answer would have answer text once the repairs are
  applied, up from 81.6%: 91.5% from row-checked repairs + 0.6 points from the 592 agenda joins and 39 review rows. The
  Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation. 186 v0.2 records from 26
  parliaments validate: the converter's 120 (105 cantonal and communal + 15 federal, 23 parliaments) and P8's 66 gold
  records (11 parliaments).
- **What Apertus adds: the right value among printed candidates.** On new layouts (P2, 15 parliaments) it finds 24/29
  answer dates and is exact on 53/62 documents; the model-free baseline of P2's table (latest date on answer-typed
  documents) reaches 18/29 and 44/62: 10 documents vs 1, exact McNemar p = 0.0117, parliament-resampled interval
  [0.056, 0.243] (post hoc; 4 of its 7 wins on answered documents are documents OPD types as interventions, where that
  baseline returns nothing). Registered: the rules 2/29. On the review queue (P7, registered) its promotions are
  answers on 120/120. Author roles, in 14 parliaments without rules (P10): Apertus
  50/141, level with OPD's contributor list (37/141; Holm p = 0.17); Rules 17/141; most of the gain comes from the
  model-free candidate finder (document order 52/141); Apertus adds precision deciding who is an author (+7.3 points,
  post hoc). Where rules exist it adds one document net (P1: 139/154 vs a model-free cascade's 138/154, post hoc). In
  Italian (P11, exploratory) the pointer is exact on 12/12 answers, the rules on 8/12.
- **Census and OPD.** 2,177 "missing" answers were in OPD all along, under an unrecognised heading. OPD confirmed
  the Bern linking bug (correspondence, 10 Oct 2026); the only open decision is its hash rule for relinks. Lists from
  50 model-free source adapters: blind AI annotators judged 185/186 counted rows to be the answer (Claude; 3 dates
  judged wrong) and 186/186 (Qwen), post hoc after Valais's 140 date-window rows moved to review.
- **Sovereign and cheap to run.** The default runs no model and only reads public sources; every model value goes
  to a reviewer. Runtime external services: none by default (public sources only); Apertus review mode sends document
  text to the Public AI gateway, or nothing with the local 8B (date suggestions; the queue verifier needs the 70B).
  Rules: about 0.5 CPU-hours for OPD's 902,754 documents; review USD 0.59 per 1,000 residue documents. The build guard
  caught Public AI's gateway build switch (12 Oct 2026) live: no result mixes builds.
- **Ten tests, frozen before any label** (P1's hypothesis script followed its labels, its rules came with its
  sample: D4, D12). P1: rules alone right on 135/154, so by default no model runs. P6: no registered hypothesis held.
  The 9 held results of P1–P7 survive Holm over their 20 tests. Null safety failed on the 70B (P1, P2, P6), so
  Apertus only suggests.
- **Labels without human labelling, by design.** Two blind AI annotators label, a third settles ties; Qwen-SEA-LION
  (AI Singapore) relabelled P1, P2, P6 and P7 blind: dates agree with κ 0.80, 0.87 and 0.86.
- **Operations.** `make run` (Docker, CPU) recomputes the census, re-derives the rules arm from the PDFs, replays
  P1–P8 and P10 and checks every number. We found, audited and fixed our own robots.txt
  bug; every fetch now fails closed. Claude Code agents wrote the code and labels.
