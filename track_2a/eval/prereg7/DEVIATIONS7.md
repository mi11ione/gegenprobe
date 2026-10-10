# P6 deviations and run notes (after LOCK7, dfd1e72)

## N1 (10 Oct 2026, 23:4x): the draw, by the registered rule (no deviation)
`python -m eval.p6.sample draw` after the LOCK7 commit gave **68 of 77 documents from 8 of 9 parliaments** (≥ 60: not
flagged underpowered). Replacements and shortfalls followed PREREG7 and are logged in `data/p6/p6_fetch_log.jsonl`:
- **Val de Bagnes (6037): 0 of 8.** Its host did not answer from this machine at draw time (robots.txt unreachable,
  fail-closed in `gegenprobe.net`, 54 candidates tried). It had answered a probe hours earlier.
- **Conthey (6023): answers 4 of 5.** 23 answer PDFs extracted to 0 characters (pdftotext and OCR) and were replaced by the
  next candidate, as registered, until the pool was exhausted.
- Zug city: 4 HTTP 404 replaced; Lyss: 1 non-PDF replaced.
Result: 55 German, 13 French documents; 44 answer-typed, 24 intervention-typed (strata by metadata; labels decide).
Packets: `.work/p6/packets/` (68). No label existed at draw time.

## N2 (10 Oct 2026, 23:50): one response refused by the served-model check (no effect on results)
During the first run of `eval.p6.run_p6`, one response to a request for `swiss-ai/apertus-v1.5-8b` carried the model
field `swiss-ai/Apertus-v1.5-70B`. `llm._Remote._check` raised `ServedModelMismatch` and the response was not cached; the
run stopped. Two probes a minute later (one generation, one prefill) returned `swiss-ai/apertus-v1.5-8b` with the usual
fingerprint `vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840`. The runner was started again unchanged: cached
responses replay, and only responses that pass the check are stored. Every P6 cache entry carries the model field and
fingerprint above (`results/p6/p6__publicai_swiss-ai_apertus-v1.5-8b.json` → `served_fingerprints`, re-derived from the
cache in `results/p6/p6_served.json`).
