# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. `make claims` recomputes
every number here from its results file and checks these notes token by token.

- **Answer.** A common schema for Swiss parliamentary business works if it carries roles, not only for dates. Of its
  17 fields, 10 need roles, 6 keep one definition and 1, the submission date, is body-specific in 2 parliaments.
  "Answer date" means the government's decision in some parliaments, the letter or registration date in others, and
  in 7 parliaments mostly the submission date. A pre-registered test on 66 affairs from 11 parliaments (P8) finds
  roles in fields v0.1 defined once: sole, joint or group authors; co-signatory lists that include authors; one
  harmonised type for different instruments; language tags naming the other official language. Schema v0.1 gives
  every date its role, every value its source (page and position, or the OpenParlData (OPD) record) and every empty
  field a reason; v0.2 ships P8's roles, and all 66 P8 affairs validate in it.
- **Census.** Of 91,268 interventions with a recorded government answer, 92.3% would have answer text once the
  proposed repairs are applied (81.6% attached today; 85.6% from what OPD already holds, 88.3% after its hash
  decision for the Bern relinks). 2,177 "missing" answers were in OPD all along, under a heading the census did not
  recognise. Median answer time: 112 days where the date is the verified decision, 39 where publication-like.
- **Ready for OPD.** Repairs proposed for 9,720 answers, keyed on OPD ids. In Bern, OPD attaches 229 of the 3,532
  answers the canton publishes (6.5%), yet 96.1% are already in OPD: 2,421 relinks and 48 fetches (plus 554 corrected
  start dates), with a dry-run SQL plan. OPD confirmed the Bern bug (correspondence, 10 Oct 2026); the only open
  decision is its hash rule for relinks. Also: lists from 50 model-free source adapters, 27 with counted repairs
  (blind AI annotators judged 197/200 to be the answer), 9 OPD vocabulary labels wrong as published, and a Fedlex
  resolver for 29,946 federal placeholder documents.
- **What Apertus adds.** Every date it extracts is printed in the document, with page and position. As a closed-set
  verifier of the review queue (P7, pre-registered), 120/120 sampled promotions were judged the government's answer
  by blind AI annotators (Wilson [96.9, 100]); 95.8% are answers whose date passes the date check, +22.7 points over
  a trivial date match, weighted, as registered ([10.2, 34.3]; unweighted +7.5); it fills a tier of 214 answers for
  review. In 15 parliaments nobody wrote rules for it finds 24/29 answer dates and dates 4 of 33 documents without
  one, where the latest printed date dates 31. On submitters, pointing at printed names doubles the rules' extraction
  (12/40 to 24/40); free generation finds 34/40.
- **Sovereign by design.** The default nightly job uses no third-party processor and only reads public
  sources. The optional review model is the operator's choice: Public AI, or the Apertus 8B on one CPU machine
  (180 s per document). On new parliaments the 8B is right on 13 documents where the rules are wrong, the reverse on
  0; its two-step reader cuts dates on answerless documents from 18/34 to 5/34 (exploratory).
- **Nine tests, frozen before any label** (P1's hypothesis script followed its labels, its rules came with its
  sample: D4, D12). P1: rules alone right on 135/154, so by default no model runs. P2: 24/29 answer dates on 15
  unseen parliaments. P3/P3b: whole affairs, replicated. P4: 99 affairs rebuilt from minutes, none invented. P5: Q/A
  pairing at precision 0.83, recall 0.67 (partial tier). P6: no registered hypothesis held; the shipped reader stays.
  P7: H1 holds (120/120). P8: of 7 fields v0.1 defines once, 4 split by role and the submission date is
  body-specific, under both checks. The 9 held results of P1–P7 survive Holm over their 20 tests. Null safety
  failed on the 70B (P1, P2, P6), so Apertus only suggests.
- **Labels without human labelling, by design.** Two blind AI annotators label, a third settles ties, raw files are
  committed, and all 84 labelling sessions of P1–P7 ended before the labels reached GitHub. Qwen-SEA-LION (AI
  Singapore) relabelled P1, P2, P6 and P7 blind: dates agree with κ 0.80, 0.87 and 0.86, P7 185/190; no registered
  result changes.
- **Operations.** `make run` (Docker, CPU) recomputes the census, re-derives the rules arm from the PDFs, replays
  P1–P8 and checks every number. Two consecutive real nights in Docker on a GitHub runner: 86 min, then 6.6 min, 0
  alerts; night 2 exposed a ledger bug, now fixed and tested (real re-run dispatched tonight). We found, audited and
  fixed our own robots.txt bug; every fetch now fails closed. Next: tables and annexes, v0.2 with the eCH group.
  Claude Code agents wrote the code and labels.
