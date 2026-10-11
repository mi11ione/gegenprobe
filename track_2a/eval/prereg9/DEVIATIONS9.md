# Deviations from PREREG9 (P8)

Changes after LOCK9, with their effect. None touches a hashed file, a label, a verdict or a decision rule.

- **D9-1 (reporting, after the results).** §8 says the README and `docs/ech-onepager.md` state "meaning tested for N of
  17" with N = 5 (role splits from OPD's labels) + the P8 fields with a verdict other than inconclusive, which gives
  5 + 7 = 12. Type is among both the five label-measured fields and the seven P8 fields, so N counts it twice. The
  documents state the number of distinct fields whose meaning is measured: 11 of 17 (`site/data.json`
  `schema.meaning_measured`, computed from `data/schema/field_verdict_classes.json`). Effect: the count is one lower
  than the formula; no verdict changes.
- **D9-2 (sample, at the draw).** Ticino (TI), registered with a quota of 0 + 6, contributed no affair: its robots.txt
  disallows every one of its 1,493 eligible candidate documents for our user agent, and the fail-closed fetch guard
  refused them (`data/p8/p8_fetch_log.jsonl`; shortfall recorded in `results/p8/sample.json`). The registered
  replacement rule (§3) replaces only within a parliament, so P8 has 66 affairs from 11 parliaments instead of 72
  from 12. Recorded at the draw (commit 4d8a228); listed here for completeness.
