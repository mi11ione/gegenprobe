# Deviations from PREREG5 (P3b)

## D5-1 (10 Oct 2026, at sampling; reported, no change to the procedure) — 36 of 40 affairs
The registered draw (seed 20261017, `eval/gold5/sample5.py`, run once after the LOCK5 commit 43a9012) filled 9 of 10 body
quotas. Locarno (5113) and its registered reserve Bellinzona (5002) yielded no accepted affair: Locarno 0 of 20 tried
(its whole qualifying pool after exclusions was 18 affairs), Bellinzona 0 of 42 (every question document extracted to
0 characters). Fribourg city (2196) yielded 0 of 34 (its OPD document links are web pages, not PDFs); the quota was filled
from its registered reserve Vernier (6643), 4 of 4. Graubünden accepted 4 of 18 (14 links return an HTML page).
Per-attempt reasons: `data/gold5/p3b_fetch_log.jsonl`. The sample is 36 affairs from 9 bodies (rules 20 / no rules 16;
communes 16 / cantons 20). Nothing else changes: hypotheses, thresholds and arms are as registered; S1's
"inconclusive (underpowered)" rule applies as registered if fewer than 10 open pairs carry a gold value.

## D5-2 (10 Oct 2026, POST-HOC, found by the round-4 jury) — a Luzern rule replaced correct OPD answer dates
`results/eval/posthoc_r4_eval.json` → `p3b_luzern_rule`. Frozen code is not changed.
- **Where.** In 3 of the 4 Luzern affairs (240980, 240904, 241105), arm C's answer date is the submission date. OPD's
  answer event (arm M) equals the gold in all three.
- **Why.** The frozen rule `lu_antrag` (`convert/rules.py`) takes the first date within 300 characters after "Antrag
  Regierungsrat:". pdftotext prints the Luzern header labels (Nummer / Eröffnet / Antrag Regierungsrat / Protokoll-Nr.) as
  one column and the values as the next, so that first date is the "Eröffnet" (submission) value. Arm C takes
  answer_date from a document rule whenever one fires and falls back to OPD metadata otherwise. The rule was written on
  one dev document (517948), where it is correct.
- **Effect.** C answer_date is 20/35 as registered. With OPD's answer event kept in these 3 affairs it would be 23/35
  (0.66), within P3's CI [0.63, 0.92]; CA would be 34/35 (31/35 registered). S2 would then have 0 fields below P3 instead
  of 1. The registered verdict ("replicated") is the same either way.
