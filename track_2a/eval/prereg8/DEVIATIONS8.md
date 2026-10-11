# Deviations from PREREG8 (P7)

## D1: Qwen check started through a shim for the gateway path (no effect on any registered result)
`eval/p7/qwen8.py` (hashed in LOCK8) reads the gateway directory from `audit3.GATEWAY`. Commit f540e91 (Ops: development
paths from `GP_GATEWAY_DIR`, `gegenprobe/devpaths.py`) removed that attribute from `audit3.py` before LOCK8 was written,
so LOCK8 hashed the new `audit3.py` and a `qwen8.py` that no longer runs. The locked file was not edited. The check was
run with the attribute set back from `devpaths.gateway_dir()` (the same directory, `~/Desktop/hackapertus/gateway`) before
`qwen8.main()` was called:

    PYTHONPATH=src:. python -c "from gegenprobe import devpaths; from gegenprobe.repair.adapters import audit3; \
        audit3.GATEWAY = devpaths.gateway_dir(); from eval.p7 import qwen8; qwen8.main()"

Model, prompt, tag (`2a-p7-qwen`), cap, served-model check and output path are as locked. The Qwen check changes no gold
label and no decision; H1–H4 do not read it.

## D2 (11 Oct 2026, post hoc, round 8): context for H1 and H4 (no registered result changes)
Written after the test gold was read; `python -m eval.p7.posthoc_r8` -> `results/p7/p7_posthoc_r8.json`, no model call.
- Frauenfeld (4566) supplies 109 of the 214 queue promotions and 72 of the 120 judged p7 rows. Without it, H1's rule is still
  met: 48/48, Wilson [92.6, 100]. Every one of the 9 parliaments with a judged promotion is at 100%; counted as one
  observation per parliament, Wilson [70.1, 100]. H4 with parliaments resampled: +22.7 points [5.5, 49.6].
- The trivial date match is also right on is_answer for 146/146 annotated promotions and also stops all 10 gold-no rows.
  Unweighted, H4 is 115/120 (95.8%) vs 129/146 (88.4%), +7.5 points; the registered weighted +22.7 comes from 8 rest-stratum
  rows (weight 7.625) of which 2 are date-checked.
- No-model ablation: the adapters' date rule on every printed date of the model's view promotes 217 of the 478 frame rows
  (369 of the 863-row queue) at 98.9% is_answer precision and 76.2% date-checked precision; p7 is +19.6 points [8.4, 30.9]
  above it on date-checked precision and +1.1 [0, 2.9] on is_answer. What Apertus adds over the rule is the choice of date.
