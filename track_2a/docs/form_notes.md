# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. `make claims` recomputes
every number here from its results file and fails on any mismatch, or on a number or scope word not bound to its claim.

- **Answer.** Can one schema hold Swiss parliamentary business? Yes, if its fields carry roles (asked of interventions,
  OPD's five intervention types: 198,594 of its 325,691 affairs). Shared: one schema of
  17 fields for communal, cantonal and federal business, every value with its role and source, every gap with a typed
  reason. Needs roles: 10 fields; "answer date" is the government's decision, its letter or, in 7 parliaments, mostly
  the submission date. Body-specific: 1 field and 2 constructs (the submission date in Vernier and Lausanne; oral
  answers, minutes-only councils). Untested: 6 fields, defined once in v0.1.
- **Delivered.** Repairs for 9,720 answers keyed on OpenParlData (OPD) ids, every one from model-free rules; schema
  v0.2 with the roles; a converter that gives every value its page and span; a nightly job. Apertus only picks values
  printed in the document, and code locates them.
- **Headline.** 92.3% of interventions with a recorded government answer would have answer text once the repairs are
  applied, up from 81.6%: 91.6% from row-checked repairs + 0.7 points from the 592 agenda joins and 39 review rows. The
  Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation. In 15 parliaments
  nobody wrote rules for, Apertus is exact on 53/62 documents, the best no-model baseline on 44/62 (P2, post hoc;
  McNemar p = 0.012); in 14 such parliaments it reads 50/141 author roles right, the rules 17/141, at precision 0.52
  vs 0.31 (P10, registered: recall +23.4 points, Holm p = 0.032); OPD's own contributor list gets 37/141, not
  significantly different (Holm p = 0.17). 186 affairs from 26 parliaments, communal, cantonal and federal, validate in schema v0.2 (the
  15 federal ones exploratory).
- **Schema.** A pre-registered test of 7 fields on 66 affairs from 11 parliaments (P8) finds roles in authorship,
  signatories, the instrument behind a harmonised type and the language. The converter fills v0.2's roles: on 5
  parliaments its rules never saw, author (name, role) pairs reach precision 39/49 at recall 39/137, the language is
  right on 60/60 documents. Tables, annexes, images, scans and signatures are marked by page: blind check of 30
  documents (exploratory, in-sample): tables precision 12/12, recall 12/15; annexes 6/6 and 6/6.
- **Census and OPD.** 2,177 "missing" answers were in OPD all along, under an unrecognised heading. OPD confirmed
  the Bern linking bug (correspondence, 10 Oct 2026); the only open decision is its hash rule for relinks. Lists from
  50 model-free source adapters (blind AI annotators judged 197/200 to be the answer), 9 OPD vocabulary labels wrong
  as published. Answer times: OPD's plain medians mislead where the "answer" event is the submission date (Kriens,
  Valais: 0 days; the answer documents give 26.5 and 100); on the same affairs OPD's and the documents' dates rank the
  parliaments almost identically (Spearman 0.99).
- **What Apertus adds.** Registered: 24/29 answer dates on new layouts, the rules 2/29; resampled by parliament the
  gain is [-0.02, 0.54]. On the review queue it is a precision verifier: its promotions are answers on 120/120
  (registered; 86.7% of queue rows are answers, and a no-model date match's promotions are answers on 146/146), and
  its date is right on 113/120 of its promotions against 127/146 for the best no-model rule, each on its own
  promotions (not paired), at lower recall (214 vs 369 rows). Where rules exist it adds one document net (P1: 139/154
  vs a model-free cascade's 138/154, post hoc).
- **Sovereign and cheap to run.** The default runs no model and only reads public sources; every model value goes
  to a reviewer. A first network night took 86 min, the next 6.6 min.
- **Ten tests, frozen before any label** (P1's hypothesis script followed its labels, its rules came with its
  sample: D4, D12). P1: rules alone right on 135/154, so by default no model runs. P6: no registered hypothesis held.
  The 9 held results of P1–P7 survive Holm over their 20 tests. Null safety failed on the 70B (P1, P2, P6), so
  Apertus only suggests.
- **Labels without human labelling, by design.** Two blind AI annotators label, a third settles ties; Qwen-SEA-LION
  (AI Singapore) relabelled P1, P2, P6 and P7 blind: dates agree with κ 0.80, 0.87 and 0.86.
- **Operations.** `make run` (Docker, CPU) recomputes the census, re-derives the rules arm from the PDFs, replays
  P1–P8 and P10 and checks every number. We found, audited and fixed our own robots.txt bug; every fetch now fails closed.
  Claude Code agents wrote the code and labels.
