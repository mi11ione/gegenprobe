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
