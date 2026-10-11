# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. `make claims` recomputes
the numbers here from their results files and binds every one from 10 up, and every decimal, ratio, percentage and
interval, to its claim by an anchor phrase.

- **Answer.** A common schema for Swiss parliamentary business works if its fields carry roles, and the proposed
  repairs, keyed on OpenParlData (OPD) ids, would raise the share of interventions with a recorded government answer
  that have answer text from 81.6% to 92.3%. Apertus is a closed-set reader: every value it extracts is printed in the
  document (70B weights via the Public AI gateway; local 8B GGUF on CPU).
- **Schema.** The 17 fields: 10 need roles (8 robust, 2 fragile), 1 body-specific, 6 defined once in v0.1 (meaning is
  the next test). "Answer date" is the government's decision in some parliaments, the letter date in others, in 7
  parliaments mostly the submission date. A pre-registered test of 7 fields on 66 affairs from 11 parliaments (P8)
  finds roles in authorship, signatories, the instrument behind a harmonised type and the language: a text's language,
  OPD's tag and the affair's can differ. v0.2 adds P8's roles and the converter fills them: 75 of its 105 records carry
  printed authors with their role; on 5 unseen parliaments the language is right on 60/60 documents. All 171 records
  validate, every empty field with a typed reason.
- **Census.** Of 91,268 interventions with a recorded government answer, 81.6% have answer text attached today, 85.6%
  with the repairs from what OPD already holds, 88.3% after its hash decision for the Bern relinks, 92.3% with the
  checked fetches. 2,177 "missing" answers were in OPD all along, under an unrecognised heading.
- **Ready for OPD.** Repairs proposed for 9,720 answers, keyed on OPD ids, every one from model-free rules. In Bern,
  OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet 96.1% are already in OPD: 2,421 ready relinks
  (of 2,459 candidates, 38 for review) and 48 ready fetches. The Bern plan ran on PostgreSQL: 2,975 rows in one
  transaction that rolls back on any deviation. OPD confirmed the Bern bug (correspondence, 10 Oct 2026); the only
  open decision is its hash rule for relinks. Also: lists from 50 model-free source adapters, 27 with counted repairs
  (blind AI annotators judged 197/200 to be the answer), 9 OPD vocabulary labels wrong as published, and two data
  findings: question and answer in different languages (214 of 1,999 tagged affairs), and on the government's own
  answer dates Valais moves from tied fastest to 14th of 17.
- **What Apertus adds.** Blind AI annotators judged 120/120 sampled promotions the government's answer (P7-H1,
  registered); post hoc, the date it picks is the gold answer date in 113/120 (94%), against 127/146 (87%) for the
  best no-model rule. It fills a tier of 214 answers for review. In 15 parliaments nobody wrote rules for it is exact
  on 53/62 documents, against 44/62 for the best no-model baseline (P2, post hoc; McNemar p = 0.012); registered: 24/29
  answer dates, rules 2/29.
- **Federal level (exploratory).** 15 Federal Council answers print no answer date: rules, pointer and converter date
  none (15/15 right nulls), the latest printed date invents one on 6/15; all 15 v0.2 records validate.
- **Sovereign and cheap to run.** The default runs no model and only reads public sources. On the local route, as on
  the gateway, every model value goes to a reviewer. A first network night took 86 min, the next 6.6 min; at ten
  times OPD's whole export the rules need about 5 CPU-hours.
- **Nine tests, frozen before any label** (P1's hypothesis script followed its labels, its rules came with its sample:
  D4, D12). P1: rules alone right on 135/154, so by default no model runs. P5: Q/A pairing at precision 0.83, recall
  0.67 (partial tier). P6: no registered hypothesis held; the shipped reader stays. P8: of its 7 fields, 4 split by
  role and the submission date is body-specific, under both checks. The 9 held results of P1–P7 survive Holm over
  their 20 tests. Null safety failed on the 70B (P1, P2, P6), so Apertus only suggests.
- **Labels without human labelling, by design.** Two blind AI annotators label, a third settles ties, and all 84
  labelling sessions of P1–P7 ended before the labels reached GitHub. Qwen-SEA-LION (AI Singapore) relabelled P1, P2,
  P6 and P7 blind: dates agree with κ 0.80, 0.87 and 0.86, P7 185/190.
- **Operations.** `make run` (Docker, CPU) recomputes the census, re-derives the rules arm from the PDFs (OCR fails
  loudly; pinned models), replays P1–P8 and checks every number. We found, audited and fixed our own robots.txt bug;
  every fetch now fails closed. Claude Code agents wrote the code and labels.
