# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Each number below is listed
in `claims.tsv` with the file it comes from, and `make run` re-checks them.

- **The two questions.** Can one schema hold the business of all Swiss parliaments? Yes, if it keeps dates apart by
  role and says why a value is missing. Of 17 fields, 12 mean the same everywhere and 5 need their roles kept apart
  ("answer date" alone is three dates: decided, sent, registered); 4 are in OpenParlData's (OPD) metadata almost
  everywhere, 13 only for some parliaments. Can a tool fill it from the documents? Yes, for what the documents print,
  tested in depth for the answer date: each date comes with the page and position where it is printed, or the tool says
  why there is none. Apertus's category suggestions (type, recommendation) are for a person to check.
- **Where answers go missing.** 16,749 of 91,268 interventions with a written government answer (18.4%) have no
  answer text in OPD, each with a cause: filed under an agenda item, stored without a parent, scanned without text,
  answered orally (1,008 Valais stubs, 406 question-time answers), or not in OPD. Open dataset of all 91,268.
- **Repair lists OPD can apply.** In Bern, OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet
  3,394 (96.1%) are already in OPD. OPD confirmed the bug and its cause, and that our list is the workaround until its
  fix ships (correspondence, 10 Oct 2026). Every candidate was checked against OPD's own copy: 2,421 relinks and 48
  fetches pass, 39 go to a person. An apply plan shows each row before and after; relinking changes OPD's document
  identifier, which the plan flags. Ready-made routes cover 3,107 of the 16,749; 10,800 need a reader for each
  parliament's website, the next step.
- **Five tests, frozen before any label was committed.** (1) On 154 documents from parliaments our rules were written
  for, rules alone are right on 135 and Apertus adds nothing significant, so by default no AI model runs. (2) On 62
  documents from 15 parliaments the rules never saw (answer dates in 7 of them), the rules find 2/29 answer dates and
  Apertus 24/29; it also beats the best simple shortcut we tried, 10 documents to 1. Asked freely, Apertus is about as
  accurate, but only the pointing form gives every date with its page and position (32/32). It still dates 4/33
  documents without an answer, so a person confirms what it suggests.
- **Labels without human labelling, by design.** Two AI annotators label blind, a third settles ties, all raw labels
  are committed; rerunning the AI annotators need not give the same labels, so the committed ones are the record. OPD's
  own answer dates match 37 of 44 checkable test dates, and 5 of the other 7 are 1–5 days apart; Ticino's titles 20/20.
  For the unseen parliaments only 6 of 29 dates can be checked exactly (6/6 agree).
- **Whole affairs.** (3) On 29 affairs from 10 parliaments, OPD's metadata plus rules get type 27/29, submitter 23/29
  and answer date 22/27; Apertus suggestions fill the answer dates (27/27). (3b) A fresh pre-registered replication on
  36 affairs passed its own criteria; its weakest field was the answer date, 20 of the 35 that have one (a Luzern rule
  took the wrong date in 3 affairs), 31/35 with Apertus.
- **Affairs rebuilt from minutes.** (4) For Bulle, whose council business exists in OPD only as meeting documents,
  rules turn 6 held-out sittings into 99 affairs (every one real, every title right, no decision invented), though
  only 99/120 items were found; in La Chaux-de-Fonds items carry over (9/9) but decisions do not (0/9).
- **Which model, what it costs.** The results above use the large 70B Apertus, which the hosting service Public AI
  serves under the small model's name (we checked). The small 8B, on one ordinary 4-core machine, takes 180 s per
  document and never returns a date that is not printed. On unseen parliaments it finds nearly as many answer dates
  (15 of 21; 70B: 16), but suggests dates for more documents without an answer (11 of 31; 70B: 4), so a person rejects
  more. Our advice: run without a model; for suggestions, the 8B fully local, or the 70B for accuracy on servers the
  operator chooses (USD 0.59 per 1,000 documents the rules leave open at Public AI's price).
- **Runs on ordinary machines.** `make run` re-checks the results on an ordinary computer, no graphics card, in a
  locked-down container that never runs as root. The nightly job ran one real night on a GitHub test machine against
  OPD's live data: 83 min, no alerts, the Bern list reproduced. It is not yet running at OPD; inside OPD a night with no
  changed files took 96.8 s. It only fetches public documents and sends document text only to a model service the
  operator sets. Claude Code agents wrote the code and the labels (declared in the README).
