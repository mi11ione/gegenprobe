# Pre-registration P3 (DRAFT) — whole-affair extraction across fields, parliaments and languages

Status: FROZEN (LOCK3). Written as a draft; became PREREG3.md when the integrator writes LOCK3 (sha256 of this file, the affair sample, the
extraction package, the new prompts, the scorer and the annotation tooling), before any P3 label exists.

## Why
P1 and P2 evaluate one field (the government's answer date). The challenge asks whether an LLM can turn heterogeneous
parliamentary PDFs into the schema across fields, parliaments and languages. P3 measures every field of schema v0.1 that
a question document and its answer can carry, on whole affairs, with OPD metadata as a first-class route.

## Sample (drawn before this draft was frozen; seed 20261012; `eval/gold3/sample.py`)
29 affairs (58 PDFs, 179 pages) with one member text and one executive answer each, from 10 parliaments; none of the
affairs or documents occur in P1 dev, P1 held-out or P2.

| body | language | level | rules written for it | affairs |
|---|---|---|---|---|
| BE | de | canton | yes | 3 |
| ZH | de | canton | yes | 3 |
| BS | de | canton | yes | 3 |
| TI | it | canton | yes | 3 |
| 261 Zürich city | de | commune | yes | 3 |
| NW | de | canton | no | 3 |
| OW | de | canton | no | 3 |
| VD | fr | canton | no | 3 |
| 6643 Vernier | fr | commune | no | 3 |
| 5002 Bellinzona | it | commune | no (one letterhead rule names it; reported with and without) | 2 |
| **total** | de 18 · fr 6 · it 5 | canton 21 · commune 8 | seen 15 · unseen 14 | **29** |

Types: Interpellation 15, Question 11, Motion 2, Postulate 1. Sion (no linked question+answer pairs in OPD) was replaced by
Vernier before the draw was accepted; Bellinzona has one affair fewer (pool exhausted after fetch failures); affairs whose
PDFs are image-only were not accepted by the fetcher (no text after extraction), so P3 says nothing about scans.

## Gold
Two blind Claude-agent annotators (A1 Opus, A2 Sonnet) label every field from the documents only (`eval/gold3/GUIDE.md`);
a third (A3 Opus) decides only the fields where they disagree, seeing both labels as X/Y in seeded random order. Quotes are
verified verbatim by code. Disagreement keys: the single-valued fields, recommendation none ≡ not_applicable, names by
surname + first initial. Sets (co-signatories, related affairs): the final set is what both annotators list; Jaccard
reported. No human labels (by design). Raw annotator files are committed.

## Arms (`eval/gold3/run_p3.py`; extraction in `src/gegenprobe/affair/`)
| arm | what |
|---|---|
| M | OPD metadata only (affair row, events, contributors) |
| R | deterministic rules on the two documents only (no metadata) |
| C | default, unattended: metadata first, rules fill what metadata lacks; answer date = the frozen P1 cascade |
| CA | C plus the Apertus closed-set pointer on the fields C leaves open (submitter, submission date, addressed body, type, answer date, recommendation), every suggestion accepted |
Model: the same served build as P1/P2 (`swiss-ai/apertus-v1.5-8b` name = 70B weights, gateway, user message only, response
model checked), θ = +10.40 for the answer date (frozen, P1), **θ = 0 for the new fields (declared now: no dev labels exist
for them)**. The 8B GGUF build is run if its θ exists by then.

## Metrics (`eval/gold3/score3.py`)
Per single-valued field and arm: correct / missed / wrong on affairs whose documents print the field (value accuracy with
Wilson 95% CI), null_ok, and "unprinted" (a value where the documents print none — for metadata values not an error by
itself, reported apart). Sets: micro precision / recall. Every field also split by rules coverage (seen vs unseen bodies).

## Hypotheses and decisions (thresholds fixed now)
1. **P3-H1 breadth (descriptive, per field).** C value accuracy with CI for each field. A field is called "extractable
   unattended" if the lower Wilson bound is ≥ 0.80 and C has no value on more than 1 affair whose documents print none for a
   document-route value; otherwise "partial" (lower bound ≥ 0.50) or "not yet".
2. **P3-H2 metadata vs print.** For number, type, submitter and submission date: share of affairs where OPD metadata (M)
   equals what the documents print, among affairs where both exist. Reported with CI; it feeds the schema verdict (where
   metadata and documents agree, the field is consistent across parliaments).
3. **P3-H3 Apertus on the residue.** Pooled over (affair, field) pairs that C leaves open:
   (a) recall: CA correct / open pairs whose gold has a value — holds if the Wilson lower bound ≥ 0.50;
   (b) precision: CA correct / suggestions made — holds if the Wilson lower bound ≥ 0.70.
   Both hold → review-mode suggestions are recommended for those fields; (a) only → recommended with a reviewer gate;
   neither → the pointer is not recommended beyond the answer date, and the report says so.
4. **P3-H4 rules coverage (descriptive).** R and C value accuracy on unseen vs seen bodies, per field.

## Not allowed after the lock
Changing the extraction package, prompts, θ, the sample, the scorer or the annotation tooling. Any later change is a
reported deviation; failed runs are reported.
