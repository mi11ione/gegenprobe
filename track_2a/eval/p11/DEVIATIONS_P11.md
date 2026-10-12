# P11 deviations (after LOCKP11; PROTOCOL §10)

Each entry: what changed, when, why, and its effect on the P11 results. No file hashed by LOCKP11 was changed.

## D1: served-model change on the gateway route during the IT model arms; typed stop through a wrapper

**When.** 12 Oct 2026. The IT model arms (`eval.p11.arms it-pointer --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p11:1.0`)
ran from 00:54 UTC. The date pointer finished all 12 affairs and the role reader 5 of 12, every response from the frozen
build (response `model` = `swiss-ai/apertus-v1.5-8b`, `system_fingerprint` =
`vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840`, the build of P1, P2, P6, P7, P10 and the federal cell). At
~01:06 UTC Public AI began answering requests for `swiss-ai/apertus-v1.5-8b` with the label `swiss-ai/Apertus-v1.5-70B`.
The frozen check (`llm._Remote._check`) raised ServedModelMismatch at the role reader's 6th affair (119632), and
`eval/p11/arms.py`, which catches only budget refusals, crashed instead of recording the stop that PROTOCOL §8.4 requires.

**Was the build the same?** Probe (`eval/p11/served_probe.py` -> `results/p11/served_model_probe.json`, tag 2a-probe,
USD 0.0006, 01:34-01:38 UTC; route returned HTTP 504 for ~15 minutes before): three byte-for-byte replays of requests cached
during registered runs (two P10 role-reader requests of 11 Oct, one P1 held-out date-pointer request of 9 Oct), sent
to `swiss-ai/apertus-v1.5-8b` exactly as the arms send them. All three came back labelled `swiss-ai/Apertus-v1.5-70B`
with a **different fingerprint**, `vllm-0.1.dev1+g54b4292c2-tp2-bfd70257` (another vLLM build; tensor-parallel 2, no
pipeline stage). The two role-reader requests: greedy token changed on one of two; top-20 sets differ (14 and 17 shared
tokens); log-probability deltas up to 4.64 (mean 2.12) and 2.00 (mean 0.58). The date-pointer request: same
log-probability (-39.375) and tokens. **The build changed, not only the label.**

**Decision.** The relabel acceptance prepared for this case (accept exactly the label pair on the frozen fingerprint;
`eval/p11/arms_d1.py --accept-relabel`) is **not used**: its precondition (the probe shows the frozen fingerprint) fails
and the wrapper refuses it. Per PROTOCOL §8.4 the role reader is **stopped** (served-model mismatch) and reported as
partial; the date pointer, complete on the frozen build, stands; the no-model arms stand. The arms were re-run through
`eval/p11/arms_d1.py` (without `--accept-relabel`): the same logic as `eval.p11.arms.it_pointer`, plus the two
`except llm.ServedModelMismatch` branches that record the stop as `served_model_mismatch at affair <id>: ...` (with the
served fingerprint) instead of crashing. Cached responses replay; the first uncached request goes live and is checked by
the frozen check unchanged.

**Effect.** IT author roles: the Apertus role reader is scored on the 5 affairs it read on the frozen build (TI 3,
Mendrisio 2), not 12; the other arms on all 12. IT answer date: the pointer on all 12. NI: no model arm, unaffected.
No θ, configuration, prompt, gold or scorer changed. Not run again on the new build: θ (10.395) and the role reader's
configuration were fitted on the frozen build and do not transfer (`convert/build_guard.py`).
