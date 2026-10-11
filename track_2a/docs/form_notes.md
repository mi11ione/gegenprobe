# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Every number is traced in
`claims.tsv` to its file; `make run` re-checks them.

- **The answer.** One schema can hold the business of all Swiss parliaments if it keeps dates apart by role and says
  why a value is missing. Of 17 fields, 12 are shared (we tested the meaning of 1; 11 by definition) and 5 need their
  roles kept apart ("answer date" alone is three dates); 4 are in OpenParlData's (OPD) records almost everywhere, 13
  only for some parliaments. Our tool fills what documents print, with page and position or a reason why there is
  none: the answer date in depth, each question with its answer; only the type runs without a person.
- **For OPD: lists and one command.** In Bern, OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet
  3,394 (96.1%) are already in OPD. Checked against OPD's own copy: 2,421 relinks and 48 fetches pass, 39 go to a
  person, plus 727 wrong Bern start dates. One command turns them into a before/after plan. OPD confirmed the bug and
  that our list is the workaround until its fix ships (correspondence, 10 Oct 2026; a published excerpt awaits OPD's
  consent).
- **Where answers go missing, and how to put them back.** 16,749 of 91,268 interventions with a government answer
  (18.4%) have no answer text in OPD; 1,422 were answered orally, so 15,327 written answers (17.1%) are missing, each
  with a cause. Readers for 50 parliaments now verify repairs for 9,720 of the 16,749 (was 3,107); 5,007 still need
  one. A blind audit of 300 random repairs: 297 are the answer, 0 wrong, 3 unclear. We found and disclosed our own bug:
  a standard robots.txt parser let 3 disallowed files through once; deleted, unused, fixed everywhere.
- **Seven tests, frozen before any label was committed.** (1) On 154 documents from parliaments our rules know, rules
  alone are right on 135, so by default no AI model runs. (2) On 62 documents from 15 parliaments no rule was written
  for, the rules find 2/29 answer dates and Apertus 24/29, ahead in 6 parliaments, behind in none; the latest date in
  each document finds 22/29 too but dates 31 of the 33 without an answer (Apertus 4/33). (6) On 8 more new parliaments,
  rules then Apertus find 31/34 answer dates, rules alone 20/34. Plainly: the same Apertus asked freely is as accurate
  (62/68 vs 59/68); our pointing form guarantees printed dates only, each with its page (32/32). A person confirms.
- **Questions and answers (5).** On 40 affairs from 10 new parliaments, rules pair each question with its answer at
  precision 0.83 and recall 0.67 (a person checks), far ahead of free generation (79:11); Apertus doubles finding the
  submitter (12/40 → 24/40).
- **Labels checked by another company's model.** Two AI annotators label blind, a third settles ties, raw labels are
  committed. Qwen-SEA-LION (AI Singapore) relabelled blind (P1, P2 for USD 0.14): dates agree with κ 0.80, 0.87 and 0.86 (tests 1, 2, 6), no
  registered result changes; on (5) its labels were too noisy to judge. OPD's own dates match 37 of 44 checkable test
  dates; Ticino's titles 20/20. One registered test fails on documents the labellers dispute, council reports (1/72
  without them).
- **Whole affairs.** (3) On 29 affairs, OPD's records plus rules get type 27/29 and answer date 22/27; Apertus
  suggestions fill the answer dates (27/27). (3b) A fresh replication on 36 affairs passed its registered criteria:
  answer date 20/35 (4/35 wrong, 3 by a Luzern rule, now guarded), with Apertus
  31/35. (4) For Bulle, rules turn 6 sittings into 99 affairs, no decision invented,
  though only 99/120 items were found.
- **Which model, what it costs.** The results use the 70B Apertus, which Public AI serves under the 8B's name, as its
  server signature indicates. The 8B (a community 4-bit build) runs on one 4-core machine, 180 s per document, and
  cannot return a date that is not printed; on new parliaments it finds 15 of 21 answer dates (70B: 16) but dates 11
  of 31 documents without an answer (70B: 4). Advice: run without a model; for suggestions the 8B fully local, or the
  70B on servers the operator chooses (USD 0.59 per 1,000 documents the rules leave open).
- **Runs on ordinary machines.** `make run` re-checks the results, locked down. One real night against OPD's live data
  took 83 min and reproduced the Bern list; a two-night run is scheduled. Outside services: only OPD and the
  parliaments' sites; suggestions add one model service the operator sets. Claude Code agents wrote the code and the
  labels.
