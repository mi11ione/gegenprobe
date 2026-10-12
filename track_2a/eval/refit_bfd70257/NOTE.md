# Refit of θ for the Public AI build `bfd70257` (deviation / registration note)

**Status: EXPLORATORY deployment refit. Written 12 Oct 2026 03:20 UTC, before any call to the new build in this
workstream.** Nothing here replaces a registered result. No file hashed by LOCK, LOCK2–LOCK10, LOCKFED or LOCKP11 is
changed; everything below lives in new files (`eval/refit_bfd70257/`, `src/gegenprobe/convert/deploy_theta.py`,
`data/deploy/`, `results/refit_bfd70257/`, `data/model_cache/publicai_swiss-ai_apertus-v1.5-8b_bfd70257/`).

## Why

From about 01:05 UTC on 12 Oct 2026 Public AI answers requests for `swiss-ai/apertus-v1.5-8b` with the label
`swiss-ai/Apertus-v1.5-70B` and the fingerprint `vllm-0.1.dev1+g54b4292c2-tp2-bfd70257` (`results/p11/served_model_probe.json`,
`eval/p11/DEVIATIONS_P11.md` D1). Every registered θ was fitted on the previous build
(`vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840`), so review mode on that route now exits 3 (by design: θ does not
transfer across builds). This note fixes, before any new-build call, how θ is refitted for the new build so that review
mode can run again, and how the new build is then measured.

## Route and response checks (binding for every call below)

- Requests are unchanged: model name `swiss-ai/apertus-v1.5-8b` exactly, one plain user message, the assistant prefill
  only to that name (`llm.PREFILL_OK`). No request ever names a `-70b`/`-70B` model, and no system message is ever sent.
- Every call goes through the project budget gateway (`llm.Gateway`, tag `2a-refit`, one cap of USD 3.00 for the whole
  workstream: fit, held-out runs, P7 dev and the end-to-end check).
- Every live response is checked: it is accepted only if its `model` is exactly `swiss-ai/Apertus-v1.5-70B` **and** its
  `system_fingerprint` is exactly `vllm-0.1.dev1+g54b4292c2-tp2-bfd70257`. Anything else (the old label, the old
  fingerprint, a missing fingerprint, any other label) raises ServedModelMismatch and stops the run; nothing from such a
  response is used. Each acceptance is counted and logged in the output files.
- New-build responses are cached under their own build key `publicai:swiss-ai/apertus-v1.5-8b@bfd70257`
  (`data/model_cache/publicai_swiss-ai_apertus-v1.5-8b_bfd70257/`), never under the registered key, so no cached
  response of the old build can be replayed as a new-build answer and vice versa.

## What is refitted, on which data, by which rule

1. **Pointer θ (answer date, review mode).** The frozen `eval.arms.fit` is called unchanged (pointer prompt
   `answer_date`, θ = 0 during scoring, `calibrate.calibrate`: abstain iff margin > θ; θ = midpoint of the widest
   contiguous accuracy-optimal interval; documents with no date candidate are left out; LOO accuracy and AUROC
   reported). Dev data: the **97 committed P1 dev documents** (`data/gold/dev_docs.jsonl`, labels
   `data/gold/dev_labels.jsonl`); the 30 spike items are left out, as the documented refit procedure
   (`docs/runbook.md`, `GP_SPIKES_DIR=none`) and P1 deviation D3 (8B arm) do, because a deployment has no spike texts.
   The registered θ = 10.40 used all 127 dev labels.
   For a like-for-like comparison, the old build's fit on the same 97 documents was replayed from the committed cache
   before this note (no model call): θ = 11.557, LOO 94/97, AUROC 0.994.
   Output: `data/deploy/theta_bfd70257.json`, a deployment file outside the hash-locked `data/convert/theta/`.
   The fit is written whatever it shows; no gate decides whether it is "good enough" (the comparison is reported).
2. **P7 verifier θ_A / θ_B (review-queue verifier), only if budget allows after 1, 3 and 4.** The rule of
   `eval/p7/tune.py`, unchanged, as P7's 8B arm used it (`eval/p7/run_8b.py fit`): per θ_B in `tune.THETA_B`, θ_A = the
   smallest `tune.GRID` value with no promoted dev row gold no/unclear/disputed; chosen: most correct promotions at its
   θ_A, ties the smaller θ_B; prompts fixed at the frozen `a2` / `b1`. Dev data: the 80 P7 dev rows with the committed
   blind labels (`data/p7/dev_annotations/gold.jsonl`), texts from the local P7 work copies (checked against the
   committed `text_sha256`). Output: `data/deploy/p7_theta_bfd70257.json`. No P7 test row is scored.

## Order (test sets touched only after θ is written)

1. Fit θ on dev (above); write `data/deploy/theta_bfd70257.json`.
2. Only then, with that θ: P2's held-out arms (62 documents; arms rules, pointer, cascade, naive), scored with the P2
   scorer (`eval/gold2/hypotheses2.py` `block`, strict) and compared with the registered build (pointer 53/62 exact,
   24/29 answer dates; `results/eval2/hypotheses2__publicai_swiss-ai_apertus-v1.5-8b.json`) and with the model-free
   baseline (latest date on answer-typed documents, 44/62 and 18/29; `results/eval2/p2_posthoc_best_baseline.json`), by
   the method of `eval/gold2/posthoc_best_baseline.py` (exact McNemar, parliament-cluster bootstrap B = 10,000, seed
   20261011). -> `results/refit_bfd70257/p2_newbuild.json`.
3. If budget allows: P1's held-out arms (154 documents) the same way -> `results/refit_bfd70257/p1_heldout_newbuild.json`,
   compared with `results/eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json`.
4. End to end: `python -m gegenprobe convert … --mode review` and `python -m gegenprobe affair --opd-affair 39369
   --schema v0.2 --roles apertus` on the gateway route: exit 0 with the deployment θ file present (one live call),
   exit 3 without it.

## Review-mode loader (deployment lookup)

`src/gegenprobe/convert/deploy_theta.py` (new, unlocked) wraps the frozen lookup only inside the CLI
(`python -m gegenprobe convert|affair`): when a remote backend resolves to the registered route build
`publicai:swiss-ai/apertus-v1.5-8b`, the run is live, and a deployment θ file for that route exists, the backend is
moved to the new build key, its response check accepts exactly the (label, fingerprint) pair the file records and
nothing else, and the BuildGuard is fitted from the deployment file (θ and fingerprint). Without the file, the frozen
path runs unchanged and review mode still exits 3 on the new build. Offline replays (`GP_OFFLINE=1`) and an explicit
`--theta` keep the frozen path. The role reader (`--roles apertus`) runs its frozen P10 configuration on the new build:
not refitted, marked `same_build_as_p10: false` (exploratory) in its block.

## What these results are

Exploratory, post registration, on a build no registration names. They are reported next to the registered results,
never in place of them; every registered number stays as it is.

## Addendum (12 Oct 2026, 03:50 UTC): the route went back to the registered build; the refit stopped

**What happened.** The fit started at 03:19:01 UTC (`run fit`, 3 workers). Its first 169 responses all came from the new
build (label `swiss-ai/Apertus-v1.5-70B`, fingerprint `…-bfd70257`; every one checked and cached under the new build
key). At about 03:32:45 UTC the route answered with the **registered** label `swiss-ai/apertus-v1.5-8b` and fingerprint
`vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840`. The response check stopped the fit, as fixed above; no response of
that build was used or cached under the new key (`run audit`: 169 responses, one label-fingerprint pair). 40 of the 97 dev
documents were complete on the new build. No θ was fitted and no deployment θ file was written. P2, P1 and P7 were not run
on the new build: the rule above lets test documents be scored only after θ is written.

**Probes** (`eval/refit_bfd70257/probe.py`, byte-for-byte replays of dev requests whose responses both caches hold,
no prompt text kept): 03:43 UTC 6/6 and 03:47 UTC 3/3 responses from the registered label and fingerprint
(`results/refit_bfd70257/probe_0343.json`, `probe_0347.json`).

**Consequences.**
- Hosted review mode runs again on the registered θ: live, `convert … --mode review` and `affair --opd-affair 39369
  --schema v0.2 --mode review --roles apertus` both exit 0 on the registered fingerprint (`results/refit_bfd70257/e2e_live.json`;
  the 10 responses of that check were removed from the registered cache afterwards).
- The loader got one addition before any deployment file exists: with a deployment file, one preflight request (one plain
  user message, max_tokens 1, the same `-8b` name, never cached) reads which build serves the route before θ is chosen;
  the deployment θ applies only if that is the file's build, otherwise the frozen path decides (registered θ for the
  registered build, exit 3 for any other). Reason: the route has switched builds twice within three hours.
- Descriptive only, no θ fitted (`run partial`, no call): on the 40 dev documents both builds answered, AUROC 0.990
  (registered) vs 0.985 (new); the abstain/answer decision at the registered build's 97-document θ (11.56) agrees on
  38/40, the top candidate on 37/40; margins differ by a median 4.3 and up to 33.7 nats
  (`results/refit_bfd70257/dev_partial_compare.json`).
- If `bfd70257` returns: `run fit` resumes from the 169 cached responses (only the rest goes live), then `p2`, `p1`,
  `p7dev`, all under the rules above.

Cost of this workstream (tag 2a-refit, gateway ledger): USD 0.031 of the USD 3.00 cap.
