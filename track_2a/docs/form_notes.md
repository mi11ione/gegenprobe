# Form notes (for the submission form, ≤ 5000 characters; jurors read these)

Gegenprobe, Track 2A OpenParlData, team 444. Evidence site: https://gegenprobe.mi11ion.io. Every number below is
recomputed from a results file in the repository by `make run`; spike figures are marked as cited.

- **Where Swiss parliamentary answers go missing.** 16,749 of 91,268 interventions with a written government answer
  (18.4%) have no answer text in OpenParlData (OPD), 1,008 of them Valais oral answers filed as stubs. Each one has a
  cause: filed under an agenda item, stored without a parent, scanned without text, oral, or not in OPD. Answer rates
  and answer times per parliament, with a CSV: site → Parliaments. Open dataset: 91,268 interventions × 23 columns with
  source links and a trust level for each parliament's answer dates.
- **Repair lists OPD can apply.** In Bern, OPD attaches 229 of the 3,532 answers the canton publishes (6.5%), yet
  3,394 (96.1%) are already in OPD. OPD confirmed the bug and its cause (correspondence, 10 Oct 2026) and called our
  list of 2,459 relinks + 49 fetches "the best workaround" until its fix ships. Each relink was checked against OPD's
  own copy: affair number and heading 2,459/2,459, decision date 2,421 (the rest go to review). A second list fixes 727
  Bern start dates that are load timestamps. Ready-made routes repair 3,107 of the 16,749; 11,206 need a reader for
  each parliament's own website, the next step.
- **Is a common schema feasible? Partly, and we show where it breaks.** Over 17 fields and 89 parliaments: 4 are in
  OPD's metadata almost everywhere, 13 only for some parliaments (elsewhere only in the PDF), 0 without a written source in a fifth or more of
  parliaments.
  The words differ more than the concepts: 42 affair-type labels mean different things in different parliaments, and
  "answer date" is three dates (decided, sent, registered) that a schema must keep apart. `docs/census.md`.
- **A converter whose every value is printed in the document.** It returns a date from the document, with page and
  position, or says why there is none. Asked freely instead, Apertus writes an answer date for 15/15 (local 8B) and
  14/15 (70B) documents that have no answer (cited spike). It can still pick the wrong printed date, so a person
  confirms what Apertus suggests.
- **Four tests, written down and frozen before any label existed, show where Apertus earns its place.** Labels by two
  blind AI annotators plus a tie-breaker; no human labels by design; raw annotations committed. (1) On 154 documents
  from parliaments our rules were written for, rules alone are exact on 135/154 and Apertus adds nothing significant,
  so rules run on their own. (2) On 62 documents from 15 parliaments the rules never saw, the rules find 2/29 answer
  dates and Apertus 24/29: exact on 53/62 against 44/62 for the best simple shortcut; better in 6 parliaments, worse in
  none. It still dates 4/33 documents without an answer, so its values are suggestions for OPD's existing review
  step. All Apertus results so far are the 70B served under the 8B name; real 8B runs are pending.
- **Whole affairs.** (3) On 29 affairs from 10 parliaments in German, French and Italian, OPD's metadata plus rules
  get type 27/29, submitter 23/29 and answer date 22/27; Apertus suggestions complete the answer dates (27/27). No
  field is reliable enough to run unattended yet; that is stated field by field.
- **Affairs rebuilt from minutes.** OPD named these virtual affairs one of the points of the challenge. (4) For Bulle,
  whose council business exists in OPD only as meeting documents, rules turn 6 held-out sittings into 99 affairs
  (every one real, every title right, decision found for 49/63 items, invented for none), though only 99/120 items
  were found.
  In a second town, La Chaux-de-Fonds, items and titles carry over (9/9) but decisions do not (0/9): each town words
  its decisions differently.
- **Runs anywhere, sovereign by default.** One command (`make run`) replays every result on an ordinary computer, no
  graphics card needed. Inside OPD it reads the exports in place: a full night takes 96.8 s with no download. Never runs as root; time and size limits on every
  document; a site that cannot say whether it allows us is not fetched; alerts are never lost. The default needs no
  AI model; review can run Apertus on the same machine. Maturity: census, repair lists, nightly job ready to deploy;
  extraction a tested study. Claude Code agents wrote the code and the gold labels (declared in the README).
