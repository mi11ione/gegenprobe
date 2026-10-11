# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. `make claims` recomputes
every number here from its results file and binds each one to its claim by an anchor phrase.

- **Answer.** A common schema for Swiss parliamentary business works if its fields carry roles, and the proposed
  repairs, keyed on OpenParlData (OPD) ids, would raise the share of interventions with a recorded government answer
  that have answer text from 81.6% to 92.3%. Of the 17 fields, 10 need roles (8 robust, 2
  fragile), 1 is body-specific, and 6 are defined once in v0.1 (their meaning is the next test). "Answer date" means
  the government's decision in some parliaments, the letter or registration date in others, and in 7 parliaments
  mostly the submission date. A pre-registered test on 66 affairs from 11 parliaments (P8) finds roles in fields v0.1
  defined once: sole, joint or group authors; co-signatory lists that include authors; one harmonised type for
  different instruments; language tags naming the other official language. Schema v0.1 gives every value its role and
  source (page and position, or the OPD record) and every empty field a reason; v0.2 adds P8's roles and validates 171
  affairs, 105 of them the converter's own records.
- **Census.** Of 91,268 interventions with a recorded government answer, 81.6% have answer text attached today, 85.6%
  with the repairs from what OPD already holds, 88.3% after its hash decision for the Bern relinks, 92.3% with the
  checked fetches. 2,177 "missing" answers were in OPD all along, under an unrecognised heading.
- **Ready for OPD.** Repairs proposed for 9,720 answers, keyed on OPD ids. In Bern, OPD attaches 229 of the 3,532
  answers the canton publishes (6.5%), yet 96.1% are already in OPD: 2,421 ready relinks (of 2,459 candidates, 38 for
  review) and 48 ready fetches, with a self-checking dry-run SQL plan. OPD confirmed the Bern bug (correspondence,
  10 Oct 2026); the only open decision is its hash rule for relinks. Also: lists from 50 model-free source adapters, 27
  with counted repairs (blind AI annotators judged 197/200 to be the answer), 9 OPD vocabulary labels wrong as
  published, and a Fedlex resolver for 29,946 federal placeholder documents.
- **What Apertus adds.** Every date it extracts is printed in the document, with page and position. As a closed-set
  verifier of the review queue (P7, pre-registered), 95.8% of its promotions are the government's answer with a
  checkable answer date, +22.7 points over a no-model date match (H4, [10.2, 34.3], weighted, as registered;
  unweighted +7.5), and 120/120 sampled promotions are answers (H1, Wilson [96.9, 100]). Post hoc, the date it picks
  is the gold date in 113/120 promotions, against 127/157 for a no-model rule. It fills a tier of 214 answers for
  review. In 15 parliaments nobody wrote rules for it finds 24/29 answer dates (rules 2/29) and is exact on 53/62
  documents, against 44/62 for the best no-model baseline (post hoc).
- **Sovereign and cheap to run.** The default runs no model and only reads public sources (OPD's exports, Bern's open
  data, Fedlex, the parliaments' sites). Apertus runs through the Public AI gateway or locally (8B GGUF, CPU); on the
  local route, as on the gateway, every model value goes to a reviewer. A first network night took 86 min, the next
  6.6 min; at ten times OPD's whole export the rules need about 5 CPU-hours.
- **Nine tests, frozen before any label** (P1's hypothesis script followed its labels, its rules came with its sample:
  D4, D12). P1: rules alone right on 135/154, so by default no model runs. P2: 24/29 answer dates on 15 unseen
  parliaments. P3/P3b: whole affairs, replicated. P5: Q/A pairing at precision 0.83, recall 0.67 (partial tier). P6:
  no registered hypothesis held; the shipped reader stays. P7: H1 holds (120/120). P8: of 7 fields v0.1 defines once,
  4 split by role and the submission date is body-specific, under both checks. The 9 held results of P1–P7 survive
  Holm over their 20 tests. Null safety failed on the 70B (P1, P2, P6), so Apertus only suggests.
- **Labels without human labelling, by design.** Two blind AI annotators label, a third settles ties, and all 84
  labelling sessions of P1–P7 ended before the labels reached GitHub. Qwen-SEA-LION (AI Singapore) relabelled P1, P2,
  P6 and P7 blind: dates agree with κ 0.80, 0.87 and 0.86, P7 185/190.
- **Operations.** `make run` (Docker, CPU) recomputes the census, re-derives the rules arm from the PDFs, replays
  P1–P8 and checks every number. Two consecutive real nights in Docker on a GitHub runner, 0 alerts; night 2 exposed a
  ledger bug, now fixed and tested (real re-run starts with OPD's next nightly export, 12 Oct 00:30 UTC). We found, audited and fixed
  our own robots.txt bug; every fetch now fails closed. Claude Code agents wrote the code and labels.
