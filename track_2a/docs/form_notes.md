# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Each number below is listed
in `claims.tsv` with the results file it comes from, and `make run` re-checks them; spike figures are marked as cited.

- **The two questions.** Can one schema hold the business of all Swiss parliaments? Yes, if it keeps dates apart by
  role and says why a value is missing: of 17 fields, 4 are in OpenParlData's (OPD) metadata almost everywhere, 13 only
  for some parliaments (elsewhere only in the PDF), and none needs a different concept. "Answer date" alone is
  three dates (decided, sent, registered). Can a tool fill it from the documents? Yes: every value it reads from a
  document comes with the page and position where it is printed, or it says why there is none.
- **What that makes possible: where answers go missing.** 16,749 of 91,268 interventions with a written government
  answer (18.4%) have no answer text in OPD. Each has a cause: filed under an agenda item, stored without a parent,
  scanned without text, answered orally in the sitting (1,008 Valais stubs, 406 question-time answers), or not in OPD.
  Answer times per parliament and type, with a CSV and an open dataset of 91,268 rows: site → Parliaments.
- **Repair lists OPD can apply.** In Bern, OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet
  3,394 (96.1%) are already in OPD. OPD confirmed the bug and its cause, and that our list is the workaround until its
  fix ships (correspondence, 10 Oct 2026). Every candidate was checked against OPD's own copy: 2,421 relinks and 48
  fetches pass, 39 go to a person. A second list fixes 727 Bern start dates that are load timestamps. Ready-made routes
  propose repairs for 3,107 of the 16,749; 10,800 need a reader for each parliament's own website, the next step.
- **The tool says when it does not know.** For a parliament it has no rules for, it warns and marks the row for review.
  "Partially accept" stays partial. You can add your own patterns for your parliament, and ask it to explain each try.
- **Four tests, frozen before any label was committed, show where Apertus earns its place.** (1) On 154 documents from
  parliaments our rules were written for, rules alone are right on 135/154 and Apertus adds nothing significant, so
  by default no AI model runs. (2) On 62 documents from 15 parliaments the rules never saw (answer dates in 7 of them),
  the rules find 2/29 answer dates and Apertus 24/29; it also beats the best simple shortcut, 10 documents to 1. Asked
  freely, the same Apertus is about as accurate, but only the pointing form gives every date with its page and
  position (32/32), and the free form invents dates. Apertus still dates 4/33 documents without an answer, so a person
  confirms what it suggests.
- **Labels without human labelling, by design.** Two AI annotators label blind, a third settles ties, and all raw
  labels are committed, so anyone can rerun it. Where an outside source exists it agrees: OPD's own answer dates match
  37/44 checkable test dates, most others within a few days; Ticino's titles 20/20. The unseen-parliament set is thin
  here: 6 of 29 dates can be checked (6/6 agree).
- **Whole affairs.** (3) On 29 affairs from 10 parliaments, OPD's metadata plus rules get type 27/29, submitter 23/29
  and answer date 22/27; Apertus suggestions complete the answer dates (27/27). An early study: no field runs
  unattended yet.
- **Affairs rebuilt from minutes.** (4) For Bulle, whose council business exists in OPD only as meeting documents,
  rules turn 6 held-out sittings into 99 affairs (every one real, every title right, no decision invented), though
  only 99/120 items were found; in La Chaux-de-Fonds items carry over (9/9) but decisions do not (0/9).
- **Which model, what it costs.** All Apertus results are the large 70B model, which the host serves under the small
  model's name; the small 8B model on an ordinary processor is being measured. Our advice: run without a model, and
  use Apertus for suggestions where no rules exist. Suggestions cost USD 0.59 per 1,000 documents the rules leave open; at ten times OPD's
  volume the rules need about 5 processor-hours.
- **Sovereign by default.** One command (`make run`) re-checks the results on an ordinary computer, no graphics card.
  Inside OPD it would read the exports in place: a night with no changed files took 96.8 s, one with three days of
  changes about 21.8 min. Never runs as root; limits on every document; a failed alert is re-sent the next night. Ready to deploy,
  not yet running at OPD. Claude Code agents wrote the code and the labels (declared in the README).
