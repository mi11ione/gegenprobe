# Evaluation in detail: eight pre-registered tests

The full record behind the evaluation summary in [`../README.md`](../README.md) and the technical report. Paths are
relative to `track_2a/`. Every number here is listed in `claims.tsv` and recomputed by `make claims`. Each test froze
code, prompts and θ by sha256 before any label was committed (`eval/prereg*/`); failed hypotheses are reported as
registered, next to the ones that held.

## The eight tests, in registration order

Each froze code, prompts and θ by sha256 before any label was committed (`eval/prereg*/`).

| test | n | what it tests | registered result | note |
|---|---|---|---|---|
| P1 | 154 documents, parliaments with rules | answer date: rules vs Apertus | **partial**: H3 held; H1 null safety failed (7/90); H2 Branch B | rules alone 135/154, so no model by default |
| P2 | 62 documents, 15 parliaments without rules | rules transfer; pointer vs rules | **3 of 4 held**; H3 null safety failed (4/33) | pointer 24/29 answer dates, rules 2/29 |
| P3 | 29 whole affairs, 10 parliaments | 7 fields: metadata, rules, Apertus | **partial**: no field unattended; Apertus recall held, precision below | feasibility study (D3-5) |
| P3b | 36 fresh affairs, 9 parliaments | replication of P3 | **held**: replicated (S1, S2) | S2 lenient; type 35/36 unattended; addressed body 2/33 |
| P4 | 120 agenda items, 6 sittings | affairs rebuilt from minutes | **partial**: H2, H4 held; H1, H3 failed | recall 99/120, precision 99/99 |
| P5 | 40 fresh affairs, 10 parliaments | Q/A pairs, people, recommendation | **partial** tier (H1); H2, H5 held; H4 held as rules vs free generation; H3 no gain | *not yet* when parliaments are resampled; submitter by rules 12/40 |
| P6 | 68 fresh documents, 8 parliaments | answer-date reader v2 vs free prompting | **failed**: no hypothesis held | free prompt 62/68, v2 59/68 |
| P7 | 478 review rows, 190 blind packets | Apertus as verifier of the adapters' review queue | **H1 holds** (120/120); H4 supported; H3 not supported | 214 of 917 review rows promoted, in a separate tier |

- **Unattended** (95% lower bound ≥ 0.80, document-level intervals): the rules' answer date on parliaments with rules
  (P1, 135/154 [81.5, 92], helped by right nulls: dates found 47/64), the type on whole affairs (P3b, 35/36), and in P5
  the question detection (recall 167/187, precision 167/175), the reasoning span (37/40) and co-signatory precision
  (101/103). Not the answer date elsewhere, the submitter or Q/A pairing.
- **Default: rules, no model.** On P1 the frozen DE/FR/IT rules are right on 135/154 and pick a wrong printed date on
  4/154; the trivial baseline (latest printed date on documents OPD types as answers) is right on 131/154. On whole
  affairs (P3b) the unattended default wrote a wrong answer date for 4/35 affairs, 3 of them a Luzern rule that
  overrode OPD's correct date; the product path now keeps OPD's date in that case and flags the record.
- **Gold labels checked by another vendor, and by time.** The labels come from blind Claude annotators;
  `Qwen-SEA-LION-v4-32B` (AI Singapore) relabelled P1, P2, P6 and P7 blind: answer dates agree with κ 0.80 (P1), 0.87
  (P2) and 0.86 (P6), P7's is-answer labels on 185/190, and no registered decision changes; on P5 its labels pass the
  verbatim quote check in only 7/40 files, so they neither confirm nor overturn the verdict. All 84 annotator sessions
  ended before GitHub received their labels; in the nine locked sets they started after it received the LOCK and draw
  pushes (P5 dev and P7 dev have no lock by design; DEV2's anchor is the commit of its written selection rule and draw;
  `results/eval/annotation_sessions.json`, from transcripts kept on the author's machine).

## The 17 fields in detail

*Class* (`results/census/comparability.json`, `data/schema/field_verdict_classes.json`): does the field mean the same
thing in every parliament? *Where it lives* (`results/census/matrix.json`, thresholds in `docs/census.md` §3):
parliaments where OPD metadata carries it · carries it for part of the affairs · only the PDF · not in OPD's data.

| field | class | meaning | where it lives (metadata · mixed · PDF only · none) |
|---|---|---|---|
| answer date | role split | measured: decided, dispatched or registered; in 7 of 54 bodies mostly the submission date | **metadata**: 53 · 1 · 0 · 0 |
| procedural history | role split | measured: 35 event labels carry different date roles | **metadata**: 78 · 9 · 1 · 1 |
| type | role split | measured: 42 of 1,038 raw labels map to different types | partly: 61 · 24 · 2 · 2 |
| procedural state | role split | measured: 32 labels ambiguous | partly: 41 · 27 · 18 · 3 |
| decision outcome | role split | measured: 3 labels ambiguous | partly: 7 · 31 · 33 · 6 |
| government recommendation | shared | OPD's labels map unambiguously (string check) | partly: 3 · 8 · 56 · 10 |
| submission date | shared | defined once in v0.1; field test next | **metadata**: 89 · 0 · 0 · 0 |
| answer-link status | shared | defined once in v0.1; field test next | **metadata**: 54 · 0 · 0 · 0 |
| submitter | shared | defined once in v0.1; field test next | partly: 23 · 61 · 5 · 0 |
| addressed body | shared | defined once in v0.1; field test next | partly: 12 · 10 · 54 · 10 |
| decision date | shared | defined once in v0.1; field test next | partly: 7 · 30 · 34 · 6 |
| Q/A pairing | shared | defined once in v0.1; field test next | partly: 22 · 25 · 4 · 3 |
| language | shared | defined once in v0.1; field test next | partly: 14 · 53 · 20 · 2 |
| usable text | shared | defined once in v0.1; field test next | partly: 41 · 42 · 0 · 6 |
| co-signatories | shared | defined once in v0.1; field test next | PDF only: 0 · 2 · 72 · 12 |
| dispatch date | shared | defined once in v0.1; field test next | PDF only: 0 · 0 · 47 · 7 |
| related affairs | shared | defined once in v0.1; field test next | PDF only: 0 · 0 · 76 · 13 |

So 4 fields are in OPD's metadata almost everywhere and 13 partly or only in the PDF; no field lacks a source in a
fifth of the parliaments (5 would at a 10% threshold, `results/census/tier_sensitivity.json`). *Role split*: the
concept is shared, but one source label covers several roles that must be kept apart before parliaments can be
compared. The recommendation's string check (0 of 183 raw labels map to two concepts) covers only the labels OPD has
harmonised (29.1% of all events carry no harmonised id); a test of meaning would map each parliament's printed forms to
the concept (`docs/ech-onepager.md` §6).
Three further *concepts* are body-specific and are not fields: oral answers in question time (23.6% of question-time
answers are oral; v0.1 types them as a null reason), executive business that answers no member's affair, and councils
that publish only meeting documents (16 bodies, 8 with no affair at all; schema v0.1 marks affairs derived from them
`virtual` with `derived_from`, P4). For the eCH group: `docs/ech-onepager.md`.

Schema v0.1 adds date roles, typed nulls and `QAItem` (question *n* paired with the answer to question *n*; filled with
spans by `src/gegenprobe/qa/`, tested in P5); the 17-field verdict is the table at the top. The Pydantic models are
normative; the exported JSON Schema for OPD's workbench cannot express the cross-field rules (a rule value must carry
page and span), so validate with the models. Where OPD metadata carries a field, it mostly agrees with print (P3: type
17/18, submitter 23/28, submission date 15/21; affair numbers 21/29, format differences). In figure 2 an orange cell
means the value is *not in OPD's data* for that parliament (neither metadata nor a document; the parliament may still
publish it), not a different concept.

![Feasibility matrix](figures/fig2_matrix.png)

## What the converter returns, and a glossary

**What the converter returns.** `python -m gegenprobe convert` gives each date and rule value with the page and
character span the rule matched, each metadata value with its OPD record, and a typed null that says why a value is
missing. An Apertus value is one of the dates printed in the document, by construction; code then locates its page and
span (`pointer.locate`: the occurrence nearest an answer anchor, else the first). Apertus's categorical suggestions
(type, addressed body, recommendation) are document-level review suggestions without a span.

**Glossary.** *Pointer*: Apertus chooses one of the dates printed in the document, or null; it cannot write a value of
its own. *Typed null*: an empty field that says why (not in the document, unlinked, scan, oral, ...). *Residue*: the
documents where the rules find nothing and stay silent. *Review mode*: Apertus runs on the residue and its choice
arrives as a suggestion with page and span for a person to accept. *Null margin (θ)*: how much more likely Apertus
finds "no answer date" than all printed dates together; above θ it says null. *Virtual affair*: an affair rebuilt from
an agenda item and its minutes, for councils whose business exists only as meeting documents.

## Protocol, gold labels and every test

**Locks.** Every test froze code, prompts and θ by sha256 before any label was committed: the LOCK commit precedes the
commit adding its labels by 6 min 0 s (P1), 2 min 28 s (P2), 3 min 37 s (P3) and 4 min 3 s (P4) by commit date
(`results/eval/posthoc_r3_gold_oracle.json`), an order GitHub's clock confirms
(`results/eval/lock_server_times_all.json`; rewritten SHAs in `docs/commit-map.md`); P3b's LOCK5 (commit 43a9012), P5's
LOCK6 (db339eb), P6's LOCK7 (dfd1e72) and P7's LOCK8 (73954c3) precede their draws and labels. **Session times, not
only commit order:** the annotator agents' own transcripts date every labelling session. Across 12 label sets (P1 to P7,
the P4 transfer cell, P5 dev, P7 dev and DEV2), 84 annotator sessions wrote 1,546 label files, and all 1,546 carry a
write time inside their own session. In every set the last session ended before GitHub received the label commit. In
the nine locked sets the first session started after GitHub received the push of the LOCK (and of the draw, where it is
a separate commit); P5 dev and P7 dev have no lock by design, and DEV2's anchor is the commit of its written selection rule and draw,
not a LOCK. The transcripts are not committed and their times come from the author's clock. The P6 annotators started 26 s
after the draw was pushed and finished 10 s before the labels were pushed; for P5 the gap after the draw was 7 s; for
P1 the gap after the LOCK was 95 s. The short gaps are real: each set was split over 2 to 18 parallel sessions lasting
20 s to 7 minutes (`results/eval/annotation_sessions.json`; the transcripts stay on the author's machine because they
contain the full document text). Pointer v2 (P6) was chosen by a rule written before the DEV2 labels, but its code was
committed after them (DEVIATIONS7 D1); C won DEV2 with 29 of 31 documents against 28 and 27, within noise, and LOCK7
froze it before the P6 draw. Post-hoc findings are logged per test
(`eval/prereg*/DEVIATIONS*.md`); the round-4 ones in one clause each: D9, the 8B scorer's gate record, cache key and θ
interval; D10, multiplicity, the lenient metric and the served build; D11, three P1 gold dates before OPD's submission
date, all genuine; D2-6, P2 per parliament on all documents and the 8B on P2; D5-2, a Luzern rule that replaced
correct OPD answer dates in P3b. Round 5: D12, P1 is held out by protocol, not by commit order (below); D13, the
times in `eval/gold/SEEDS.md` were wrong (corrected there); D14 and D2-7, the annotator from another vendor; a D7
addendum gives the annotation timing from local file times (about two minutes per set, 16 parallel agents).

**Gold labels, checked by another vendor.** No human labelled or adjudicated a gold value, by design. Two blind agent
annotators (Claude Opus and Sonnet) label each document, a third breaks ties (in P2 with the order randomised), quotes
are verified by code, and the raw A1, A2 and A3 files are committed for every set, P6 and DEV2 included
(`data/p6/annotations/`), so every label and every κ recomputes; the committed
labels are the record (rerunning the agents need not reproduce them). Because all three are Claude models, an annotator
from another vendor and model family, `Qwen-SEA-LION-v4-32B-IT` (AI Singapore, Qwen family; neither Anthropic nor
Apertus), labelled all 216 P1 and P2 documents blind from the same guide and the same text (post hoc, D14/D2-7; 216
calls, USD 0.14; `results/eval/posthoc_r5_independent_gold.json`). Answer present: P1 146/154 (κ 0.89), P2 60/62
(κ 0.93). Exact answer date: P1 134/154 (κ 0.80), P2 56/62 (κ 0.87); where both name a date, Qwen's is the gold date or
one of its listed alternatives in 54/54 P1 documents, and the gold date in 25/29 P2 documents. No registered decision
changes under either reading, only the documents where both vendors agree or Qwen's labels wherever they differ: P2-H2
is 22 vs 0 under the gold, 21 vs 0 and 23 vs 1; the P1 cascade is exact on 139/154, 127/134 and 133/154. Limits: Qwen
reads the same extracted text, so OCR errors stay invisible to both, and this is a check across model families, not a
human audit; the 21 P1 and 8 P2 disagreements are listed with both values in the JSON and were not adjudicated. P1-H1
(null safety) fails as registered (7/90) and rests on contested documents: 6 of the 7 values fall on documents OPD
types as reports (council reports that quote the executive's decision). Without the 24 reports it is 1/72 (upper bound
7.5%), on the documents where both vendors agree 2/84, under Sonnet's labels 5/88, under Qwen's 11/94.

**Non-LLM checks.** Of 64 P1 answer dates, 44 can be checked against OPD's written-answer events or publisher titles;
37 of 44 agree, and 5 of the other 7 are 1–5 days apart (decision vs dispatch or publication); Ticino titles that name
the decision date match 20/20. P3 answer dates match OPD 18/21. The three P1 gold dates that precede OPD's submission
date were audited: 3 checked, 0 gold errors (one is a year typo in the source, labelled as printed as the protocol
requires; D11). P2 is thinner: 6 of its 29 dates have an exact external source (6/6 agree), and 19/29 face at least one
non-LLM bound, none contradicted (`results/eval/posthoc_r4_gold_oracle_p2.json`, D2-6).

**Statistics.** Across the 9 registered confirmatory tests of P1–P4 and P3b (post hoc, D10), all 4 conclusions that
held survive a Holm correction (P2-H1 7.2 × 10⁻⁹, P2-H2 3.8 × 10⁻⁶, P3-H3a 0.01, P3b-S1 0.016), and Benjamini–Hochberg
gives the same split; the 8B tests are exploratory and outside the family. The registered lenient metric (a second
printed date the annotators listed as defensible also counts) raises each arm by 0–5 documents and changes no registered
decision (P1 rules 136/154, cascade 140/154; P2 pointer 56/62). Documents from the same parliament are not
independent, so we also resample whole parliaments (percentile bootstrap, 10,000 resamples, post hoc;
`results/eval/posthoc_r6_cluster.json`); the intervals are given with P2, P5 and P6 below.

**Which Apertus.** Evaluation used Apertus v1.5 70B weights served by Public AI (inferred from the served fingerprint;
the endpoint name says `8b`); the real 8B was run in-process on CPU on P1, P2 (52 documents) and P6 (67 documents).
Apertus numbers not marked 8B come from the 70B weights, which Public AI serves under the name
`swiss-ai/apertus-v1.5-8b`. That is inferred, not documented by Public AI: the served fingerprint (`tp8-pp2-…`, a
tensor-parallel 8 × pipeline-parallel 2 deployment) and the behaviour (report §3: 760/792 greedy outputs
byte-identical to the `-70b` name; MMLU 84.4% vs 70.8% for the v1 8B route) point to the 70B. We use that name because
the `-70b` name answers prefilled requests with a different model; the response's `model` field is checked on every
call. Re-derived from the response cache, every P1 (1,542) and P2 (351) answer comes from one served build
(`results/eval/served_models.json`). The 8B is `swiss-ai/Apertus-v1.5-8B` (Apache-2.0) as a community text-only export
(`andreasmartin/apertus-v1.5-8b-text`) quantised to 4 bits by a community member
(`Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF`, file `apertus-v1.5-8b-text-q4_k_m.gguf`, sha256 `a037df8d…f299`, pinned in
`src/gegenprobe/llm.py` `GGUF_PINS`); it is not an official Swiss AI release, and an operator can re-quantise from the
official weights (`docs/runbook.md` "Supply chain"). It ran with llama.cpp on a 4-vCPU CI runner with its own θ = 16.73
from 97 dev documents (pre-registered exploratory arms, DEVIATIONS D2/D3), on the P1 arms and, after the round-4
review, on P2 (D2-6).

**Which size to deploy.** `rules_only` (no model) unattended, the default. For review suggestions, two options:
- **The 8B is the measured sovereign option** (exploratory; a community 4-bit build of the official weights, not an
  official Swiss AI release): one CPU machine, no document text leaves it. On P1 its rules + suggestions dated 25 of
  90 answerless documents (70B: 7), so its suggestions rely on the reviewer even more. On the 52
  reachable P2 documents it finds nearly as many answer dates as the 70B (15 vs 16 of 21) but proposes a date for 11
  of 31 answerless documents (70B: 4), and on P1's residue its suggestions are right 7/34 times (70B: 9/16, p = 0.021), so a reviewer rejects
  far more of them. On P6 the reader v2 restrains it: 5 of 34 answerless documents dated, against 18/34 for v1 (below).
  Cost: 180 s per document on 4 vCPUs.
- **The 70B is the accuracy option**, on infrastructure the operator chooses: all positive Apertus evidence on unseen
  parliaments is the 70B. Its bf16 weights alone are about 140 GB (e.g. two 80 GB GPUs; arithmetic, not measured by
  us); the Public AI service we evaluated on may route outside Switzerland.

**P1 — 154 held-out documents from parliaments the rules were written for** (DE/FR/IT × canton/commune + Ticino scans;
64 with an answer date, 90 without; always-null scores 90/154). Unit: one document's answer date, strict. Held out by
protocol (seeded draw; labels after the lock). The rules and the sample entered in one commit (`da26116`), so commit
order does not prove the rules predate the draw (D12); P2 is the clean out-of-sample test of the rules.

| arm | exact [95% CI] | answered: dates found /64 | wrong printed date | fabricated | answerless: values on the 90 |
|---|---|---|---|---|---|
| **rules only (default mode)** | **135/154 [81.5, 92]** | 47/64 | 4 | 0 | 2 |
| Apertus pointer on every document | 130/154 [77.9, 89.3] | 46/64 | 16 | 0 | 6 |
| rules + Apertus suggestions, all accepted | 139/154 [84.6, 94] | 56/64 | 11 | 0 | 7 |
| 8B pointer on every document (CPU, exploratory) | 112/154 [65.2, 79.1] | 50/64 | 37 | 0 | 28 |
| 8B rules + suggestions, all accepted (CPU, exploratory) | 119/154 [70, 83.2] | 54/64 | 31 | 0 | 25 |
| naive free generation, null-allowed | 134/154 [80.8, 91.4] | 47/64 | 11 | 0 | 3 |
| ↳ null-allowed, re-parsed (post hoc, D5) | 133/154 [80.1, 90.9] | 47/64 | 13 | 0 | 4 |
| naive free generation, plain prompt | 98/154 [55.8, 70.8] | 47/64 | 23 | 24 | 39 |
| ↳ plain, re-parsed (post hoc, D5) | 103/154 [59.1, 73.8] | 54/64 | 26 | 24 | 41 |
| *trivial: latest printed date on documents OPD types as answers (post hoc)* | *131/154 [78.6, 89.8]* | *44/64* | *16* | *0* | *3* |
| *trivial: latest printed date, ungated (post hoc)* | *50/154 [25.6, 40.2]* | *46/64* | *104* | *0* | *86* |

**The 8B rows** (`python -m eval.gguf_8b_analysis` → `results/eval/gguf_8b_analysis.json`): its rules arm is the same
(154/154 identical decisions), and every value it returns is a printed date (0 fabricated of 85 cascade values). Against
the 70B, document by document: pointer 10 right only on the 8B vs 28 only on the 70B (McNemar p = 0.0051), rules +
suggestions 2 vs 22 (p = 3.6 × 10⁻⁵); against its own rules arm the 8B cascade loses 7 vs 23 (p = 0.0052). Its margin
still separates answered from answerless documents (AUROC 0.854 vs 0.969), but θ = 16.73 lets through many wrong
printed dates on answerless documents, mostly German communes and Ticino scans. The registered P1 hypotheses
(`eval/hypotheses.py`, unchanged) on the 8B: H1 fails (25/90), Branch B (FR+IT+scans: rules alone right on 10, the
cascade alone on 2, p = 0.039; 10 vs 5 under the lenient metric), H3 passes, H4 triggers (7 of 9). The duplicated
documents of the sharded run (5) gave identical decisions, and a second CI run on the same inputs reproduced θ exactly
(a determinism check, not an independent replication; θ sits in a 0.105-nat gap between two dev margins, and moving it
0.5 nats flips 1 of 97 dev decisions). **Scorer record** (D9): the fast 8B scorer failed its parity gate against the
frozen scorer twice (57.8 nats, a bug; then 4.47 nats on a 3-token date continuation); a replacement gate, written
after those failures and before any 8B arm ran, compared both with bf16 on 30 multi-token verdict cells, not dates,
and passed (29/30 each); the pre-registered implementation check passed (58/60 decisions vs bf16) and the preset
self-check failed (10/12 decisions, 3.16 nats). The 8B numbers are fast-scorer numbers, with θ
fitted by the same scorer. The frozen naive scorer could not read answers written as DD-MM-YYYY and counted them as
"no date" (D5 / D2-4; registered numbers unchanged); the re-parsed rows re-score the stored generations with the frozen
scorer.

Outcomes as registered: null safety failed (7/90 answerless documents get a value; 95% upper bound 15.2% against 10%).
H2 gave Branch B: the registered consequence keeps Apertus only where it measurably adds null safety, and it adds none
(the cascade dates 7/90 answerless documents, the rules 2/90). We removed Apertus from the unattended path (default
`rules_only`) and kept it, as a departure logged in D6, as an opt-in review suggestion that a person confirms; P2 then
tested that use on unseen parliaments. The null margin separates answered from answerless documents (AUROC 0.969 on all
documents, 0.966 on the registered length-matched set); 3 of 8 Apertus-decided French/Italian values are wrong. A
one-line baseline (latest printed date, only on documents OPD types as answers) is exact on 131/154.

**P2 — 62 documents from 15 parliaments absent from every dev and held-out set** (29 with an answer date, from 7 of the
15: VD 8, NW 6, Bellinzona 5, OW 4, Vernier 3, SZ 2, Schlieren 1; 33 without; always-null scores 33/62; two Claude
annotators agreed on all 62 P2 dates (κ 1.0); an annotator from another vendor agrees on 56/62 (κ 0.87)). Wilson 95%
intervals in brackets (`results/eval2/posthoc_r5_p2_table.json`):

| arm | exact [95% CI] | dates found [95% CI] | wrong printed date | fabricated | values on the 33 answerless [95% CI] |
|---|---|---|---|---|---|
| rules only | 35/62 [44.1, 68.1] | **2/29** [1.9, 22] | 2 | 0 | 0 [0, 10.4] |
| **Apertus pointer** | **53/62 [74.7, 92.2]** | **24/29** [65.5, 92.4] | 8 | 0 | 4 [4.8, 27.3] |
| rules + Apertus suggestions | 51/62 [71, 89.8] | 22/29 [57.9, 87.8] | 10 | 0 | 4 [4.8, 27.3] |
| naive free generation, null-allowed | 52/62 [72.8, 91] | 22/29 [57.9, 87.8] | 7 | 1 | 3 [3.1, 23.6] |
| ↳ null-allowed, re-parsed (post hoc, D2-4) | 54/62 [76.6, 93.3] | 24/29 | 7 | 1 | 3 |
| naive free generation, plain prompt | 45/62 [60.4, 82.1] | 21/29 [54.3, 85.3] | 8 | 4 | 9 [15.1, 44.2] |
| ↳ plain, re-parsed (post hoc, D2-4) | 49/62 [67.4, 87.3] | 25/29 | 9 | 4 | 9 |
| *latest printed date, ungated (post hoc)* | *24/62 [27.6, 51.2]* | *22/29 [57.9, 87.8]* | *38* | *0* | *31 [80.4, 98.3]* |
| *latest printed date on documents OPD types as answers (post hoc)* | *44/62 [58.7, 80.8]* | *18/29 [44, 77.3]* | *13* | *0* | *7 [10.7, 37.8]* |

Outcomes: the rules collapse off their home layouts (dates found 47/64 → 2/29). **Per parliament** (post hoc, D2-1,
D2-6): on answered documents the pointer is ahead in 6, the rules in 0, 1 tie (sign test p = 0.031); on all 62
documents, counting a right null as a success, the pointer is ahead in 6, the rules in 2 (Fribourg city and 6266, whose
sampled documents carry no answer and the pointer dates some) and 7 tie (p = 0.29). The registered document-level test
(P2-H2): on the 29 answered documents 22 are right only with the pointer and 0 only with the rules
(McNemar p = 4.8 × 10⁻⁷; without Bellinzona, whose letterhead one rule happens to match, 17 vs 0, p = 1.5 × 10⁻⁵); on
all 62 it is 22 vs 4 (p = 5.3 × 10⁻⁴), the rules' nulls winning on 4 answerless documents the pointer dates.
Resampling the 15 parliaments, the accuracy gain over the rules is [-0.02, 0.54], so the gain sits in a few
parliaments; against the free prompt that may return null, the pointer is ahead on 2 documents and behind on 1, gain
[-0.04, 0.09]: no difference. **Against simple baselines** (post hoc): the latest
printed date in the document finds 22/29 answer dates, nearly as many as the pointer (on the answered documents 3 vs 1,
p = 0.63), but it dates 31 of the 33 answerless documents, where the pointer dates 4. Apertus's value is finding the
printed date. Its 4 dates on answerless documents all fall on documents that contain an answer but print no qualifying
answer date; of the 25 P2 documents with no answer at all it dates none (`results/report/r7docs_numbers.json`). Against the latest date gated by OPD's document type (null on documents OPD types as member
texts), the pointer is right on 10 documents the baseline gets wrong and the baseline on 1 (p = 0.012), 6 parliaments
to 0 (p = 0.031; this comparison was chosen after the results, D2-5). Asked freely with a null-allowed prompt, Apertus
scores about the same as the pointer (52 vs 53 of 62; re-parsed 54); the pointer adds provenance by construction, not
accuracy. The margin separates the classes (AUROC 0.983); null safety failed again (4/33, upper bound 27.3%), so
Apertus's values remain review suggestions. θ = 0, registered in PREREG2 as a secondary with no decision attached,
scores 54/62 (53 at θ = 10.40). **Error profile** (`results/report/p2_numbers.json`): the rules are right on 35, pick a
wrong printed date on 2, date none of the answerless documents and miss 25 answer dates; the pointer is right on 53,
picks a wrong printed date on 4, dates 4 answerless documents and misses 1; rules + Apertus are right on 51, wrong
date 6, answerless 4, missed 1. The combination scores below the pointer alone because Apertus is asked only where the
rules abstain: on 2 documents a rule (`rrb_vom`) fired with a wrong printed date.

**The 8B on P2** (post hoc run of the registered exploratory arms, D2-6; `python -m report.p2_8b` →
`results/eval2/p2_8b_analysis.json`). The hosts of 10 documents were unreachable from the CI runners, all 8 Vaud answers
among them, so 52 documents with 21 answer dates were scored; the 70B and the baselines are shown on the same 52.

| on the 52 reachable documents | exact | dates found | values on the 31 answerless | fabricated |
|---|---|---|---|---|
| rules only | 33/52 | 2/21 | 0 | 0 |
| 8B pointer | 35/52 | 15/21 | 11 | 0 |
| 8B rules + suggestions | 33/52 | 13/21 | 11 | 0 |
| 70B pointer | 43/52 | 16/21 | 4 | 0 |
| 70B rules + suggestions | 41/52 | 14/21 | 4 | 0 |
| *latest printed date, ungated* | *16/52* | *14/21* | *29* | *0* |
| *latest printed date on answer-typed documents* | *35/52* | *10/21* | *6* | *0* |

This is an exploratory arm, outside the registered family. On these 52 documents (Vaud's 8 answers missing) the 8B
finds 15 of 21 answer dates [50, 86.2], the rules 2 and the ungated latest printed date 14 (on the answered documents
4 vs 3). It ran on the fast scorer, which failed both registered parity gates and was admitted through a replacement
gate (DEVIATIONS D2, D9). The registered P2-H2 script on these rows gives 13 vs 0 (p = 2.4 × 10⁻⁴). The 8B finds the
dates; what it lacks is restraint: on all 52 documents it is 13 vs 11
against the rules, 10 vs 10 against the latest-date baseline (the 70B: 9 vs 1, p = 0.021), and 2 vs 10 against the 70B
(p = 0.039, pointer and cascade alike).

**P3 — whole affairs: 29 affairs (58 PDFs) from 10 parliaments, 5 with rules and 5 without, DE/FR/IT.** A feasibility
study: the extractor, its prompts and the sample entered in one commit and P3 had no development set (D3-5); its labels
were committed after the lock. Arms: OPD metadata only (M), rules only (R), the default metadata + rules (C), and C plus
Apertus suggestions on the fields C leaves open (CA). Annotators agreed on at least 27/29 affairs on every field.

| field | M | R | **C (default)** | C + Apertus |
|---|---|---|---|---|
| type | 17/29 | 26/29 | **27/29** | 27/29 |
| affair number | 21/29 | 14/29 | **21/29** | 21/29 |
| submitter | 23/29 | 5/29 | **23/29** | 23/29 |
| submission date | 15/21 | 4/21 | **15/21** | 15/21 |
| answer date | 21/27 | 16/27 | **22/27** | **27/27** |
| addressed body (gold constant: a constant answer scores 28/28) | 0/28 | 4/28 | **4/28** | 23/28 |
| decision number (defect D3-1; post hoc C 5/17) | 0/17 | 5/17 | **0/17** | 0/17 |

Outcomes as registered: no field reaches the "unattended" bar (95% lower bound ≥ 0.80; type comes closest). Apertus
suggestions on the open fields are right for 25/32 of those that have a value and 25/34 of its suggestions are right,
but the addressed body, where every gold value is "executive", dominates that count: we withdraw it as evidence (D3-3).
Without it the evidence is thin, 6/8 found and 6/9 right; the case rests on the answer date (22/27 → 27/27). Set fields:
co-signatories (OPD metadata) precision 13/16, recall 13/29; related affairs (rules) precision 6/9, recall 6/14.
Details: `docs/affair.md`.

**P3b — pre-registered held-out replication of P3** (`eval/prereg5/`, LOCK5 at commit 43a9012 before the draw; 36 fresh
affairs from 9 parliaments, 36 of 40 because Locarno and its registered reserve Bellinzona yielded no usable affair,
DEVIATIONS5 D5-1; blind annotators agreed with κ ≥ 0.97 on every field, 1 field went to the tie-breaker; blindness
audit `results/eval5/annotation_audit.json`). The registered criteria: S1, Apertus's recall on the fields C leaves
open has a Wilson lower bound of at least 0.50; S2, each eligible field's accuracy under C is within or above P3's 95%
interval, with at most one field below. Both held, so the registered verdict is **replicated**. S2 is lenient: the one
field it allows below is here the answer date, the field the case for Apertus rests on. S1: Apertus on the open fields
finds 14/16 [64, 96.5]; S2: 4 of 5 eligible fields are within or above P3's CIs (number 18/29, type 35/36, submitter
30/36, submission date 30/34 above). The answer date is the field below (C 20/35; one of the 36 affairs has no answer):
the unattended default wrote a wrong answer date for 4/35 affairs (P1: 4/154 documents), and in 3 of them, all in
Luzern, the frozen rule `lu_antrag` read the submission date and replaced OPD's correct answer event (D5-2); with OPD's
date kept it would be 23/35, within P3's interval (post hoc). With Apertus it reaches 31/35, its 11 suggestions all
right (11/11). In the product path (not the scored evaluation), a post-processing guard keeps OPD's answer date when a
rule-read date equals the affair's submission date while OPD's answer event says otherwise, and flags the record. Post
hoc on the committed records it fires on 3 of 36 P3b affairs, all three in Luzern, and OPD's kept date matches the gold
label in all three; it fires on none of the 29 P3 affairs (`results/eval5/affair_post_check.json`). Precision on the open fields is 14/20,
below the bar, so the reviewer gate stays as in P3; the type now reaches the "extractable unattended" tier (35/36).
`python -m eval.gold5.hypotheses5 publicai_swiss-ai_apertus-v1.5-8b` →
`results/eval5/hypotheses_p3b__publicai_swiss-ai_apertus-v1.5-8b.json`.

**P4 — virtual affairs from minutes: 6 held-out sittings of Bulle's council, 120 agenda items.** Deterministic parsing
derives 99 items as virtual affairs: item precision 99/99, titles 99/99, type 91/99 (H2 holds), meeting date 6/6 (H4
holds), decision found for 49/63 items (46/63 correct), invented for 0/36. **H1 failed**: recall 99/120 (82.5%, sub-items
and unnumbered lines) below the registered bar. **H3 failed**: Apertus added 2 decisions (p = 0.5). Registered transfer
cell (exploratory, DEVIATIONS4 D4-4): 2 sittings of La Chaux-de-Fonds; items 9/9 and titles 9/9, but the rules find 0/9
decisions, and with Apertus 2/9 are found, 1 correct (the annotators agreed on 7/9 of these decisions, κ 0.4, so read
the decision cell as indicative). Details: `docs/virtual-affairs.md`.

**P5 — questions and answers, people, recommendation, reasoning: 40 fresh affairs from 10 parliaments**
(`eval/prereg6/`, LOCK6 at db339eb before the draw; `docs/qa.md`). `src/gegenprobe/qa/` fills schema v0.1's
`QAPair.items` (`QAItem`) with spans: for each numbered question the member's question and the passage of the answer
that replies to it, plus the submitter and co-signatories, the executive's recommendation (with the printed sentence as
evidence) and the span of the reasoning. Rules decide first; Apertus is used only as a closed-set pointer over
enumerated, printed candidates (which numbered question a paragraph answers, which sentence states the recommendation,
which printed name is the submitter) and never generates a value. The 40 affairs come from Basel-Landschaft,
Schaffhausen, Luzern city, Riehen, Wädenswil, Lausanne, Valais (French), Collombey-Muraz, Lugano and Graubünden
(Italian), none of them in the 38-affair development set; labels from blind Claude annotators (question count, answer
style and recommendation agreed in 40/40 affairs).
- **H1 (primary):** rules-only Q/A pairing: precision 118/143 = 0.83, recall 118/176 = 0.67. With document-level Wilson
  intervals the registered rule gives *partial* (precision lower bound 0.75 ≥ 0.70). When parliaments are resampled,
  precision is [0.66, 0.97] and recall [0.51, 0.81]: the precision lower bound falls below the 0.70 bar, so the same
  rule gives *not yet*. The result depends on which parliaments were drawn; French is the weak language (recall
  10/30), and Valais got 0/11. The "unattended" bar is missed either way.
- **H2:** the rules beat a paragraph-order baseline, 116:5 discordant answers (one-sided p = 7.8 × 10⁻²⁹).
- **H4, read as rules vs free generation:** 79:11 (p = 3.9 × 10⁻¹⁴). The registered arm is rules + pointer, but the
  pointer never fired (H3), so H4 credits the rules, not the pointer. Free-generation Apertus with null
  allowed pairs 50/176 answers at precision 50/113, and 87 of its quoted values are in no document.
- **H5:** zero provenance failures: every span re-checks (517 rule values). **H3:** the dev-fitted pairing pointer
  abstained on all 36 residue answers (no measurable gain).
- **Verdict as registered: supported, at the partial tier** (document-level intervals; *not yet* under parliament
  resampling). By the same tiers, question detection (recall 167/187, precision 167/175), the reasoning span (37/40)
  and co-signatory precision (101/103) reach the unattended bar with document-level intervals; the recommendation is
  right 34/40 by rules and 36/40 with the pointer.
- **What did not transfer.** Rules-only submitter detection reached 36/38 on dev (in-sample) but 12/40 on
  P5. The pointer over printed names doubles it to 24/40, and free generation finds the submitter best (34/40); the
  submitter stays a review field. Post hoc, pairing transfers where answers number or repeat the questions (Riehen
  21/22, Wädenswil 20/24, Lugano 17/20) and fails where they do not (Valais 0/11).
- **Independent labels.** Qwen-SEA-LION's own labels pass the verbatim quote check in only 7/40 files and match the gold's
  answer spans in 96/176; with them as gold H1 would fall to *not yet* (65/116 recall, 65/105 precision). The
  disagreements were not adjudicated, so this check neither confirms nor overturns the verdict, and the recommendation
  count (34/40) rests on the Claude gold alone; both readings are reported.

**P6 — answer-date reader v2: 68 fresh documents from 8 parliaments in no earlier set** (`eval/prereg7/`, LOCK7 at
dfd1e72 before the draw; 55 German, 13 French, no Italian document because no unseen Italian-language parliament was
reachable; 34 with an answer date, 34 without; blind annotators disagreed on 1). We tried to make the closed-set reader
clearly better than free prompting: v2 asks first whether an answer is present, then applies the gold guide's
decision-before-letter-date rule (guided generation kept only if the date is printed, else a choice by date role). On
P6 the frozen v2 decided 34 of 68 documents by guided generation, 31 by its presence gate (null) and 1 by its role
pick. It was chosen on a development set by a rule written before its labels; its code was committed after them
(DEVIATIONS7 D1).

| arm (strict) | exact | answered: dates found | answerless dated | printed nowhere |
|---|---|---|---|---|
| free prompt, null allowed | **62/68** | 32/34 | 4/34 | 0 |
| free prompt with v2's instructions | 61/68 | 32/34 | 5/34 | 0 |
| rules, then v2 on what they leave open (cascade v2) | 60/68 | **31/34** | 5/34 | 0 |
| v2 | 59/68 | 30/34 | 5/34 | 0 |
| v1 pointer (θ = 10.40) | 56/68 | 29/34 | 7/34 | 0 |
| rules only | 54/68 | 20/34 | 0/34 | 0 |
| free prompt, plain | 54/68 | 33/34 | 13/34 | 5 |
| *trivial: latest printed date on documents OPD types as answers* | *51/68* | *25/34* | *8/34* | *0* |
| *model-free cascade: rules, then that baseline (post hoc)* | *55/68* | | | *0* |
| *trivial: latest printed date* | *29/68* | *27/34* | *32/34* | *0* |

**No registered hypothesis holds.** H1 (primary), v2 vs free prompting: 1:4 discordant documents (p = 0.38). H2: v2
dates 5/34 answerless documents (Wilson upper bound 30.1%, bar 15%). H3, v2 vs v1: 5:2 (p = 0.45). Registered
consequence: we drop any claim that the pointer form beats free prompting on accuracy, and v1 stays in the shipped
review mode. Secondary (registered): rules first, v2 on the residue vs rules alone on the answered documents, 11:0
(p = 0.001), 31/34 vs 20/34. On all 68 documents cascade v2 beats the rules on 11 and loses on 5 (p = 0.21; parliament
bootstrap of the gain [-0.11, 0.29]); the 11:0 holds on the 34 answered documents only. A model-free cascade (rules,
then the latest printed date on documents OPD types as answers) scores 55/68, cascade v2 60/68, the free prompt with
null allowed 62/68; cascade v2 is ahead of the model-free cascade on 5 documents and behind on 0 (p = 0.06). Qwen-SEA-LION relabelled P6 blind: presence κ 0.91, date κ 0.86; under its labels no
registered decision changes (v2 60/68, free prompt 61/68). Post hoc (`results/p6/posthoc7.json`): 4 of v2's 9 errors
are Interlaken answers its presence gate stopped (presence AUROC 0.93), 4 are Lyss documents the gold calls answerless.
**The real 8B on P6** (exploratory, CI run 38089554021, 67 of 68 documents,
`results/p6/hypotheses7__gguf_apertus-v1.5-8b-text-q4_k_m.json`): v2 51/67, v1 48/67, the free prompt with null
allowed 54/67, rules 54/67, rules then v2 55/67; answerless documents dated: v2 5/34, v1 18/34, free prompt 11/34. The
two-step reader restrains the small model where v1's margin does not. **Non-LLM checks of the P6 gold**
(`results/eval/posthoc_r6_p6_oracle.json`): OPD's written-answer event matches the gold date on 10/10 documents that
have one; every gold quote occurs on its stated page and yields the gold date (34/34); OPD's document type agrees with
the answer/no-answer label on 58/68; 20/34 dated gold documents have at least one non-LLM date source.

**What the tests say together.** Apertus earns its place where layout varies and no rule exists, by finding what the
rules miss: on parliaments nobody wrote rules for (P2: 24/29 answer dates where the rules find 2/29, 22:4 documents on
all 62), for the answer date of whole affairs (P3: 22/27 → 27/27; P3b on fresh affairs: 20/35 → 31/35), and on
submitters, where both model routes beat the rules (P5: pointer 24/40, free generation 34/40, rules 12/40). **Null safety:** every registered
null-safety test on the 70B failed (P1-H1, P2-H3, P6-H2), so its values and nulls go to a reviewer. As a
verifier of the adapters' review queue (P7) it is precise (120/120 sampled promotions are answers), but 86.7% of that
queue are answers anyway; its gain there is the choice of date (+19.6 points of date-checked precision over the
no-model date rule, parliament-cluster [0.9, 42.8], post hoc; registered H4: +22.7 points over a trivial date match). On P1 the rules alone are as accurate as rules +
Apertus (registered H2: Branch B), so the default runs no model, and in Bulle's minutes (P4) Apertus added no
significant decisions. Neither means the rules are complete: P1 rule recall is 47/64 and P4 recall 99/120. **Accuracy
close to free prompting, provenance by construction:** the same Apertus asked freely with a null-allowed prompt is about as accurate (P2: 54/62
re-parsed vs 53/62; discordant 1 vs 0, p = 1; both right on the same 24 of 29 answer dates; P6: 62 vs 59). **Provenance:** no arm
that picks from printed dates returned a date printed nowhere, on P1, P2 or P6. The fair comparator is the free prompt
that may return null: it did so 0, 1 and 0 times on P1, P2 and P6; the plain free prompt, which must always return a
date, did so 24, 4 and 5 times. So free prompting with a null option already almost never invents a date, and a
printed-date filter on it would give the same guarantee; what the closed set adds is a location for every value (32/32
on P2) and a margin that orders
the review queue (suggestions in the strong band right 26/33, weak band 3/11, post hoc); the free prompt gives a
verbatim quote containing its date for 17/32 values. Writing the gold guide's decision-before-letter-date rule into the
prompt lifted every Apertus arm on P1 dev (in-sample; free prompt with null allowed 116/127 → 125/127).

**P7 — Apertus as verifier of the review queue** (`eval/prereg8/`, LOCK8 before the draw; replayed from `data/p7/` by
`eval/p7/replay8.py`). Test frame: 478 eligible review rows outside every audit; 190 blind packets, gold A1 Opus / A2
Sonnet. H1 (primary): promotion precision 120/120, Wilson lower bound 96.9%: holds. H4: dated precision 95.8% vs
73.2% for a trivial exact-date match, +22.7 points [10.2, 34.3]: supported. H3: the rows free generation with a
printed-date filter adds are 28/30 right: not supported. Applied to the whole queue, 214 of 917 review rows go to the
tier `promoted_by_apertus`.

**What the model adds in P7 (post hoc, round 8; `results/p7/p7_posthoc_r8.json`, DEVIATIONS8 D2).** The adapters' date
rule, run without a model on every printed date of the text Apertus reads, would promote 217 of the 478 frame rows; 98.9%
are answers, but only 76.2% carry a gold answer date that passes the rule, and the first passing date is the gold date
for 70.2%. P7's promotions reach 95.8% and 94.2%: +19.6 points [8.4, 30.9] date-checked and +23.9 points [12.7, 34.7]
on the date itself. Keeping Apertus's yes/no gate but dropping its date choice, 172 rows reach 74.9%: the date choice
alone is worth +20.9 points [5.2, 33.1], the yes/no question 1.1 points [0, 2.9] on is-answer. With whole parliaments
resampled (post hoc, round 9, `eval/p7/cluster_r9.py` → `results/p7/p7_cluster_r9.json`; 15 parliaments, B = 10,000)
the gain over the no-model rule is [0.9, 42.8] and the date choice [0, 47.4]: the gain is concentrated in a few
parliaments, and without Frauenfeld it is larger (+28.5 and +36.4 points). A date match without a
model is also right on is-answer (146/146) and also stops all 10 gold-no rows, so Apertus's value in P7 is choosing which
printed date is the answer date. H4 as registered is weighted to the frame; unweighted over the judged rows it is
115/120 vs 129/146 (88.4%), +7.5 points [3.4, 12.2], the gap coming from the `rest` stratum (2/8 trivial promotions
there carry a passing gold date); with parliaments resampled the registered gap is [5.5, 49.6]. Frauenfeld supplies 109
of the 214 promotions and 72 of the 120 judged ones; without it 48/48 promotions are answers (Wilson [92.6, 100]) and
H4 is +30.2 points [10.4, 46.8]; counting each of the 9 parliaments with a judged promotion once gives [70.1, 100].
Qwen-SEA-LION agrees with the P7 gold on 185/190 packets (κ 0.655; with 92.4% chance agreement κ is low by
construction, prevalence-adjusted 0.947; the two Claude annotators reach κ 0.826).

**Across the registered family (post hoc, `results/eval/posthoc_r8_multiplicity.json`).** Holm over all 20 registered
confirmatory tests of P1–P7: the 9 that held as registered all survive (smallest margin P3b-S1, Holm p = 0.032; P7-H1
0.0042, P7-H4 0.006); no failed test turns into a pass. With parliaments resampled: P5-H1 precision [66.4, 96.6] and
recall [51.2, 81.2]; P5-H2 [42.3, 79] points; P5-H4 [22.4, 55.7] points; P6-H1 (v2 − free prompt) [-13.3, 1.6] points.

**Documents with no answer at all (post hoc, `results/eval/posthoc_r8_noanswer.json`; DEVIATIONS2 D2-8, DEVIATIONS7
D3).** In P2 and P6 "answerless" means no qualifying answer date. Split after the results by the gold's `answer_present`
field: on the 53 documents with no answer at all (25 in P2, 28 in P6) the P2 pointer and P6's v2 dated 0/53
(Wilson [0, 6.8]); the shipped reader v1 dated 1 of P6's 28, and the free prompt with null allowed 1. All 9 of their dates on answerless documents fall on
the 14 documents that contain an answer printing no qualifying date (9/14). The registered null-safety tests (P2-H3,
P6-H2) failed and still fail. The 8B v2 dated 1/28 P6 no-answer documents. On the 8B in P6 the free prompt with v2's
instructions is right on 55/67 and dates 7/34 answerless documents (v2 vs it: 2 vs 6 discordant documents).

**P7 by GitHub's clock** (UTC, 11 Oct; `results/eval/annotation_sessions.json`): LOCK8 (73954c3) arrived at
2026-10-11T02:04:10Z; the test arms and draw (6e4420c) at 2026-10-11T02:43:18Z; the 5 annotator sessions ran from
2026-10-11T02:43:23Z to 2026-10-11T02:49:31Z; the labels (432cd74) arrived at 2026-10-11T02:49:40Z. The P7 dev labels
(5 sessions ending 2026-10-11T01:51:00Z, pushed 2026-10-11T01:51:12Z) precede LOCK8 by design: they chose θ_A, the
is-answer variant and θ_B.

![Scoreboards](figures/fig5_scoreboard.png)

## Use of Apertus

- **Where:** in the converter and, since P7, on the adapters' review queue, always in closed form. In the converter it
  is a closed-set pointer: forced choice over the dates (or enum labels, or OPD affair
  numbers) printed in the document, plus null; summed log-probabilities; null if the margin exceeds θ, fitted per build
  on dev documents and frozen (θ = 10.40 for the Public AI build). In `src/gegenprobe/qa/` the same form picks which
  numbered question an answer paragraph replies to, which printed sentence states the recommendation and which printed
  name is the submitter. Free generation runs only as a contrast arm in the evaluations (P1, P2, P6,
  P7), never in the product path.
- **What it adds, measured:** the date check as a closed-set verifier of the adapters' review queue (P7: 214 rows
  promoted into a separate tier, 120/120 sampled are answers; +22.7 points of dated precision over a trivial date
  match), finding answer dates the rules miss on unseen parliaments (P2 22:4; P6 11:5 on all 68 documents, p = 0.21)
  and doubling submitter detection over the rules (P5: 12/40 → 24/40; free generation 34/40), every extracted value a
  printed one with its location. Accuracy is close to the same model asked freely with null allowed (P2 and P6,
  registered; P7-H3), and a printed-date filter on the free prompt gives the same no-invention guarantee; null safety is left to the reviewer (P1-H1, P2-H3, P6-H2 failed).
- **Why a pointer:** asked freely when the government answered, Apertus writes a precise date for 15/15 (local 8B) and
  14/15 (70B) Bern interventions that have no answer, often the "Letzte Bearbeitung" footer (earlier spikes, cited); a
  null-allowed prompt fixes this on the 70B but not on the local 8B (still 14/15).
- **Modes:** `rules_only` (default, unattended, no model) and `review`: Apertus on the rules' residue, its value attached
  as a suggestion with page, span, margin and `needs_review: true` for OPD's existing manual-review step. Recommended
  for the 74 of 89 parliaments without rules (P2) and for the answer date of whole affairs (P3), with a reviewer gate.
  In operation, review mode refuses a served build θ was not fitted on: θ files record the server fingerprints of the
  fit, and the first response from another fingerprint stops the run (exit 3) before any suggestion from it is attached
  (`--allow-build-mismatch` continues and marks each suggestion). `docs/runbook.md` "Review mode in operation" gives the
  refit commands, the owner and the cost per 1,000 residue documents.
- **Builds:** θ does not transfer between builds, so each gets its own; the 70B results above carry θ = 10.40, the
  real 8B θ = 16.73 (dev AUROC 0.90; 97 dev documents, D3). The shipped review mode keeps the v1 reader: P6 found v2
  right on 5 documents v1 missed and wrong on 2 (p = 0.45), not enough to switch.
