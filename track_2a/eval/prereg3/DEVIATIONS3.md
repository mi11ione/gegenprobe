# Deviations from PREREG3 (whole affairs)

PREREG3.md and LOCK3 are frozen (commit 922218d, before the P3 labels in d90bae7). Later findings:

## D3-1 Defect: arm C drops the decision number (found by the round-2 jury)
Registered result: decision number C 0/17, R 5/17. Cause: arm C takes the answer date from the frozen P1 cascade with OPD's
answer-event dates; when the event date is printed at an answer anchor the cascade returns through its metadata branch
(`convert/cascade.py`, rule `opd_event_date_in_document`), which does not carry the decision number the rules had already
found (`affair/extract.py` reads `r.get("number")` from that return value). Both files are frozen (LOCK/LOCK3) and are not
changed. POST-HOC: taking the rule's number in that case gives C = 5/17, the same as R (`results/eval3/p3_extra.json`).
Either way the field is "not yet" (registered tier).

## D3-2 Registered set metrics were not reported
PREREG3 registers micro precision/recall for co-signatories and related affairs. They were computed by the frozen scorer
(`results/eval3/p3__….json` → `scores.sets`) but left out of the README and report. Default arm C: co-signatories precision
13/16, recall 13/29 (all from OPD metadata; the rules do not extract them); related affairs precision 6/9, recall 6/14
(from the rules). With CIs: `results/eval3/p3_extra.json`.

## D3-3 Near-constant field (found by the round-2 jury)
Every gold `addressed_body` value is `executive` (28/28). A constant answer scores 28/28; arm C (rules) 4/28; arm CA
(with Apertus suggestions) 23/28. The field does not show that Apertus adds anything; the README/report claim that it does
is withdrawn. P3-H3 recomputed without this field (POST-HOC): recall 6/8, precision 6/9 (`results/eval3/baselines_p3.json`).

## D3-4 Header text and hypothesis script
The locked PREREG3.md title still says "(DRAFT)"; its status line says "FROZEN (LOCK3)". `eval/gold3/hypotheses3.py` was
written after the run (commit 1369d60) and applies the registered H1–H4 definitions to the frozen results file.
`eval/gold3/run_p3.py` printed a KeyError after writing its results file (set-valued fields have no `correct` count);
the results file is complete and unaffected.

## D3-5 No separate P3 development set: P3 is exploratory (10 Oct 2026, POST-HOC, found by the round-3 jury)
The whole-affair extractor (`src/gegenprobe/affair/extract.py`, 533 lines; `build.py`, `meta.py`), its 12 new prompts
(`src/prompts/*/affair_*.txt`), the scorer, the annotation tooling and the 29-affair sample (`data/gold3/p3_affairs.jsonl`,
`eval/gold3/sample.py`, OPD metadata) were all added in **one commit**, a0e4636 (orig. 922218d, LOCK3). No P3 development
set exists, and no commit shows the extractor before the sample was drawn. The repository therefore cannot show that the
extractor and prompts were not shaped on the 29 sampled affairs. The labels are clean (LOCK3 precedes them by 3 min 37 s).
The only component with a separate dev fit is the answer date, which uses the frozen P1 cascade and θ. **Consequence:** P3 is a
feasibility study, not a held-out evaluation in the strict sense, and its numbers should be described that way. A
held-out P3 needs fresh affairs drawn after a new lock with the extractor unchanged. Non-LLM check of the P3 gold
(`results/eval/posthoc_r3_gold_oracle.json`): answer dates vs OPD written-answer events 18/21 agree (3 differ by one day,
decision vs publication); vs publisher titles 6/6; submission dates vs OPD submission events 15/21 (4 within a week, 2 by
9 and 14 days: Vernier letter dates vs OPD deposit dates); vs Bern OGD 3/3. Arm C reads OPD metadata, so this checks the
gold, not the extractor.

## D3-6 (11 Oct 2026, round-10 jury): the PREREG3 header predates the lock
`PREREG3.md` line 1 still reads "(DRAFT)" (noted in D3-4). The header was written before the lock and was not updated
when P3 was locked; the file is hashed in `LOCK3`, so it is left unchanged to keep the lock verifiable. Its status line
reads "FROZEN (LOCK3)", and `LOCK3` is the record: P3 was locked before any P3 label, and its registered content is the
hashed text.
