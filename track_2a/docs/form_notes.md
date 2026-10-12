# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. `make claims` recomputes
every number here from its results file and fails on any mismatch, or on a number or scope word not bound to its claim.

- **Answer.** Can one schema hold Swiss parliamentary business? Yes, if each field says which role its value plays
  (e.g. "answer date" = the government's decision, its letter or the submission date). Tested on OPD's five
  intervention types: 198,594 of its 325,691 affairs; the "Yes" covers the affair's 17-field skeleton.
  Needs roles: 10 fields (8 robust + 2 fragile; 6 from the role test, P8, registered, 4 from OPD's labels, post hoc).
  Body-specific: 1 field and 2 constructs (the submission date: OPD's is printed in neither document in Vernier, 5/5
  affairs, and Lausanne, 3/5; oral answers, minutes-only councils). Untested: 6 fields, defined once in v0.1.
  Outside interventions the skeleton does not carry over as is (P11, exploratory, 15 affairs: 6 fields need roles interventions lack, 4 answer fields do not
  apply).
- **Delivered.** Repairs for 9,580 answers keyed on OpenParlData (OPD) ids, every one from model-free rules; schema
  v0.2 with the roles; a converter whose 120 records give every value its page and span or its source record, every
  gap a typed reason and the answer date its role (blind gold role: 32/32), the cantonal
  and communal ones written by the operator command itself;
  a nightly job (three real nights, then a real two-night Docker pair: night 2 kept night 1's verdicts).
- **Headline.** 92.1% of interventions with a recorded government answer would have answer text once the repairs are
  applied, up from 81.6%: +10.5 points, all from the 9,580 repairs (91.5% from the 8,949 row-checked alone). The
  Bern plan ran on PostgreSQL: 2,975 rows in one transaction that rolls back on any deviation. 186 v0.2 records from 26
  parliaments validate: the converter's 120 (105 cantonal and communal + 15 federal, 23 parliaments) and P8's 66 gold
  records (11 parliaments).
- **Apertus, opt-in: it reads what no rules cover.** Apertus only picks values printed in the document, and code
  locates them. In 15 parliaments nobody wrote rules for (P2) it finds 24/29 answer dates, the rules 2/29
  (registered). In 14 parliaments without rules (P10) it raises author-role recall by 23.4 points over the rules,
  precision not worse (H1, H2, registered). On the review queue (P7) 120/120 of its sampled promotions are the
  government's answer (H1, registered). On 15 Federal Council answers that print no date it dates none, and in
  Italian (P11) it is exact on 12/12 (both exploratory). Every value it returns is a located printed value (62/62,
  32/32, 35/35; free prompting's quotes 30/60, 17/32), and its margin ranks the open documents for review: AUROC 0.90
  on new layouts, above every no-model signal we computed (at most 0.58; post hoc).
- **Census and OPD.** 2,177 "missing" answers were in OPD all along, under another heading; 7,876 answered
  interventions (5.9%, 73 parliaments) still carry "submitted" as their last OPD state. OPD confirmed
  the Bern linking bug (correspondence, 10 Oct 2026); the only open decision is its hash rule for relinks. Lists from
  50 model-free source adapters: blind AI annotators judged 185/186 counted rows to be the answer (Claude) and
  186/186 (Qwen), post hoc.
- **Sovereign and cheap to run.** The default runs no model; every model value goes
  to a reviewer. Runtime external services: none by default (public sources only); Apertus review mode sends document
  text to the Public AI gateway, or nothing with the local 8B (date suggestions).
  Rules: about 0.5 CPU-hours for OPD's 902,754 documents; review USD 0.59 per 1,000 residue documents. A body that
  may not send text abroad loses only the verifier and the role reader. CI scans every lock and the image (base: 0 fixable
  HIGH/CRITICAL findings kept); a DPO checklist (EN/DE) gives purpose, recipients and retention.
- **Ten tests, frozen before any label** (P1's hypothesis script followed its labels, its rules came with its
  sample: D4, D12). P1: rules alone right on 135/154, so by default no model runs. P6: no registered hypothesis held.
  The 9 held results of P1–P7 survive Holm over their 20 tests. Null safety failed on the 70B (P1, P2, P6), so
  Apertus only suggests.
- **Labels without human labelling, by design.** Two blind AI annotators label, a third settles ties; Qwen-SEA-LION
  (AI Singapore) relabelled P1, P2, P6 and P7 blind: dates agree with κ 0.80, 0.87 and 0.86.
- **Operations.** `make run` (Docker, CPU) recomputes the census, re-derives the rules arm from the PDFs, replays
  P1–P8 and P10 and checks every number. We found, audited and fixed our own robots.txt
  bug; every fetch now fails closed. Claude Code agents wrote the code and labels.
