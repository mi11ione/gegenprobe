# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Every number is traced in
`claims.tsv` to its file; `make run` re-checks them.

- **The answer.** One schema can hold the business of all Swiss parliaments if it keeps dates apart by role and says
  why a value is missing. Of 17 fields, 12 are shared (we tested the meaning of 1; 11 by definition) and 5 need their
  roles kept apart ("answer date" alone is three dates: decided, sent, registered); 4 are in OpenParlData's (OPD)
  records almost everywhere, 13 only for some parliaments. Our tool fills what documents print: the answer date in
  depth, with page and position or a reason why there is none; only the type runs without a person.
- **For OPD: three lists, one command.** In Bern, OPD attaches 229 of the 3,532 answers the canton publishes (6.5%),
  yet 3,394 (96.1%) are already in OPD. Every candidate was checked against OPD's own copy: 2,421 relinks and 48
  fetches pass, 39 go to a person, plus 727 wrong Bern start dates. All are downloads on the site; one command turns
  them into a plan showing each row before and after (it flags that relinking changes OPD's document identifier). OPD
  confirmed the bug and that our list is the workaround until its fix ships (correspondence, 10 Oct 2026; a published
  excerpt awaits OPD's consent).
- **Where answers go missing.** 16,749 of 91,268 interventions with a government answer (18.4%) have no answer text in
  OPD. 1,422 were answered orally, so no text is expected (1,016 Valais notes, 406 question-time answers); the other
  15,327 written answers (17.1%) are missing, each with a cause. Ready-made routes cover 3,107; 10,800 need a reader for
  each parliament's website, the next step.
- **Five tests, frozen before any label was committed.** (1) On 154 documents from parliaments our rules were written
  for, rules alone are right on 135, so by default no AI model runs. (2) On 62 documents from 15 parliaments no rule
  was written for (answer dates in 7 of them), the rules find 2/29 answer dates and Apertus 24/29; it is ahead in 6
  of those parliaments and behind in none. Taking the latest date in each document (compared after the results) finds
  22/29 too, but dates 31 of the 33 documents without an answer; Apertus dates 4/33. Its value is finding the date and
  staying silent when there is none. Asked freely, Apertus is about as accurate; only the pointing form ties every date
  to its page and position (32/32). A person confirms what it suggests.
- **Labels checked by another company's model.** Two AI annotators label blind, a third settles ties, raw labels are
  committed. A model from another company and family (Qwen-SEA-LION, AI Singapore) relabelled all 216 documents
  blind for USD 0.14: dates agree with κ 0.80 and 0.87, and no registered result changes. OPD's own dates match 37 of
  44 checkable test dates; Ticino's titles 20/20. One registered test fails on documents the labellers dispute,
  council reports (1/72 without them).
- **Whole affairs.** (3) On 29 affairs from 10 parliaments, OPD's records plus rules get type 27/29, submitter 23/29
  and answer date 22/27; Apertus suggestions fill the answer dates (27/27). (3b) A fresh replication on 36 affairs
  passed its registered criteria, which allow one weaker field: the answer date, 20 of 35. Without a person the tool
  wrote 4/35 wrong dates, 3 by a Luzern rule that overrode OPD's correct date; the product now keeps OPD's date there.
  With Apertus, 31/35.
- **Affairs rebuilt from minutes.** (4) For Bulle, rules turn 6 sittings into 99 affairs (all real, no decision
  invented), though only 99/120 items were found; in La Chaux-de-Fonds items carry over (9/9), decisions do not (0/9).
- **Which model, what it costs.** The results use the large 70B Apertus; Public AI serves it under the small model's
  name, as its server signature and behaviour indicate. The small 8B (a community 4-bit build) runs on one ordinary 4-core
  machine, 180 s per document, and cannot return a date that is not printed. Tried on unseen parliaments, it finds 15
  of 21 answer dates (70B: 16; the latest printed date: 14) but dates 11 of 31 documents without an answer (70B: 4).
  Advice: run without a model; for suggestions, the 8B fully local, or the 70B on servers the operator chooses (USD
  0.59 per 1,000 documents the rules leave open).
- **Runs on ordinary machines.** `make run` re-checks the results on an ordinary computer, locked down. One real night
  on a GitHub machine against OPD's live data took 83 min (6.2 GB read) and reproduced the Bern list; a first night has
  nothing to compare with, so no drop alert could fire. A two-night run is scheduled; inside OPD a quiet night took
  96.8 s. Outside services: only OPD and the parliaments' sites; suggestions add one model service the operator sets.
  Claude Code agents wrote the code and the labels.
