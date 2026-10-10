# Pre-registration P3b: fresh held-out replication of P3 (whole-affair extraction)

Status: FROZEN by `eval/prereg5/LOCK5` (sha256 of this file and of every file listed under "Frozen"). The commit that adds
LOCK5 is the registration time. At that commit no P3b affair has been drawn, no P3b document fetched, no P3b label exists.

## Why
P3 (`eval/prereg3/PREREG3.md`, 29 affairs, 10 parliaments) is exploratory: the extractor, its prompts and the P3 sample
arrived in one commit, with no P3 development set (DEVIATIONS3 D3-5). P3b evaluates the **same extractor, unchanged**, on
affairs drawn and labelled only after this lock, with P3's hypotheses and thresholds unchanged. P3b is the held-out figure
for whole-affair extraction; P3 remains the feasibility study.

## Sample (drawn after the LOCK5 commit; seed 20261017; `eval/gold5/sample5.py`)
Qualification exactly as P3 (`eval/gold3/sample.py`, reused unchanged): an affair of type Interpellation, Motion, Postulate
or Question with at least one OPD member text and one executive answer (P3 pairing rule), both with OPD text status `ok`
and 1,500-30,000 characters; the lowest-id document of each role; the question's language equal to the body's or unknown;
fetched politely with OCR fallback, accepted only with >= 1,000 characters of text (same `fetch_one`); a failure is replaced
by the next affair of the same body in seeded order and logged. **Excluded:** every affair and document in P1 dev, P1
held-out (incl. spikes and dev-id sources), P2, P3, P4 (dev and held-out meetings) and the P4 transfer cell.

Target **40 affairs**, 4 per body, all 10 bodies **not in P3**. "Rules" = the body is listed in
`data/convert/rules_coverage.json` (the rules were written on its P1 dev documents), as in P3. Pool = qualifying affairs
after exclusions, counted from metadata before this lock (no draw, no text read).

| body | language | level | rules | pool | n | reserve (fills a shortfall, seeded order) |
|---|---|---|---|---|---|---|
| LU Luzern | de | canton | yes | 1536 | 4 | BS |
| VS Valais/Wallis (German documents) | de | canton | yes (written on its French documents) | 74 | 4 | BS |
| GE Genève | fr | canton | yes | 73 | 4 | VS (French documents) |
| 5586 Lausanne | fr | commune | yes | 273 | 4 | VS (French documents) |
| 5192 Lugano | it | commune | yes | 432 | 4 | TI |
| BL Basel-Landschaft | de | canton | no | 688 | 4 | SH |
| GR Graubünden (Italian documents) | it | canton | no | 144 | 4 | 5002 Bellinzona |
| 293 Wädenswil | de | commune | no | 217 | 4 | 2703 Riehen |
| 2196 Fribourg (city) | fr | commune | no | 33 | 4 | 6643 Vernier |
| 5113 Locarno | it | commune | no | 18 | 4 | 5002 Bellinzona |
| **total** | de 16 · fr 12 · it 12 | canton 20 · commune 20 | seen 20 · unseen 20 | | **40** | |

Reserve affairs (from P3 or P2 bodies) are new affairs too; any reserve use is logged and reported per body.

## Frozen (hashed in LOCK5; `python -m eval.prereg5.lock5 check`)
LOCK5 also carries the P1 frozen hashes (eval/prereg/LOCK) and is written only if LOCK3 is intact, i.e. the extractor,
prompts, P3 runner, scorer and annotation tooling are byte-identical to P3's.
- Registration: this file, `eval/prereg5/{__init__,lock5}.py`, `eval/gold3/GUIDE.md` (annotation guide, unchanged).
- P3b tooling: `eval/gold5/{__init__,sample5,packets5,run_p3b,score5,hypotheses5}.py` (wrappers: they rebind P3's paths
  to `data/gold5`, `results/eval5`, `.work/gold5` and call the P3 functions; no P3 logic is copied or changed).
- P3 code: `eval/gold3/{__init__,sample,annotate3,run_p3,score3,hypotheses3}.py`, `eval/baselines.py` (P3 views).
- Sampling: `eval/__init__.py`, `eval/gold/{__init__,sample,doctype}.py`, `eval/gold2/{__init__,sample}.py`.
- Arms/backend: `eval/arms.py`, `eval/score.py`, `eval/naive_baseline.py`.
- Extractor and converter: `src/gegenprobe/affair/{__init__,build,extract,meta}.py`;
  `src/gegenprobe/convert/{__init__,calibrate,cascade,lattice,pointer,rules,overlay}.py`;
  `src/gegenprobe/{__init__,paths,pdftext,net,hardening,llm,stats}.py`; `src/gegenprobe/schema/{__init__,schema_v0_1}.py`;
  `src/gegenprobe/census/{__init__,defs,tables,funnel}.py` (answer-link status). The overlay is not on the P3b scoring path;
  it is frozen so the converter that ships cannot drift during P3b.
- Prompts: `src/prompts/{de,fr,it}/affair_*.txt` and the P1 prompts (answer date, recommendation, ...).
- Data read at run time: `data/schema/{affair_types,opd_event_titles}.json`, `data/convert/affair_numbers.json.gz`,
  `data/convert/rules_coverage.json`, `data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json` (θ = +10.40),
  `data/census/{affairs,events,agendas,docs,docs_other,texts,be_ogd_answers}.tsv.gz`.
- Exclusion sources: `data/gold/{dev_ids.json,dev_docs.jsonl,heldout_docs.jsonl}`, `data/gold2/p2_docs.jsonl`,
  `data/gold3/p3_affairs.jsonl`, `data/gold4/{p4_meetings,p4_heldout_meetings,p4_transfer_meetings}.jsonl`.
- P3 reference: `results/eval3/hypotheses3__publicai_swiss-ai_apertus-v1.5-8b.json`.

Written after the lock by frozen code (not hashed, committed): `data/gold5/p3b_affairs.jsonl` (ids, urls, sha256, pages,
chars; never text), `p3b_fetch_log.jsonl`, `opd_meta_p3b.jsonl`, `body_names_p3b.json`, `link_status_p3b.json`.

## Gold
As P3, no human labels: A1 (Claude Opus) and A2 (Claude Sonnet) label every affair blind from the packet only
(`.work/gold5/packets/<affair_id>.txt`, `=== DOCUMENT question|answer ===` / `=== PAGE n ===`), with `eval/gold3/GUIDE.md`
unchanged; quotes verified verbatim by code; A3 (Claude Opus) decides only the disputed fields, seeing both labels as X/Y
in seeded random order (seed 20261018). Disagreement keys, set rule (intersection of A1 and A2) and agreement statistics
as P3. Annotators see no extractor output, no metadata, no P3 result. Raw annotator files are committed.

## Arms (`eval/gold5/run_p3b.py` -> `eval/gold3/run_p3.run`)
M (OPD metadata only), R (rules on the two documents), C (default, unattended), CA (C + Apertus closed-set pointer on the
fields C leaves open, every suggestion accepted), exactly as PREREG3. Model: the served build used in P1-P3
(`gateway:swiss-ai/apertus-v1.5-8b:2a-p3b:3.0`; the name serves the 70B weights; response model checked), θ for the answer
date from the committed theta file, θ = 0 for the other fields (`THETA3`, frozen). No 8B GGUF θ exists: CA-8B is not run.
Failed or partial runs are reported.

## Hypotheses (P3's definitions and thresholds, unchanged; `eval/gold5/hypotheses5.py` -> `eval/gold3/hypotheses3.main`)
- **H1** per-field C accuracy (Wilson 95%); "extractable unattended" if lower bound >= 0.80 and <= 1 document-route value
  where the documents print none; "partial" if lower bound >= 0.50; else "not yet".
- **H2** metadata (M) equals the printed value: number, type, submitter, submitted (descriptive, CI).
- **H3** Apertus on the residue, pooled over (affair, field) pairs C leaves open: (a) recall lower bound >= 0.50,
  (b) precision lower bound >= 0.70; decision categories as P3.
  **Registered note:** `addressed_body` is excluded from the primary H3 (P3 claim withdrawn, D3-3: gold was the constant
  `executive`). Primary H3 fields: submitter, submitted, affair_type, answer_date, recommendation. The six-field H3
  exactly as PREREG3 is reported as secondary; `addressed_body` stays in H1 as a descriptive row with its constant baseline.
- **H4** R and C accuracy on bodies with vs without rules, per field (descriptive).
Also reported as in P3: set metrics (co-signatories, related affairs: micro precision/recall with CIs), decision number
as registered (arm C, with the frozen D3-1 defect) next to arm R (the D3-1 view), and a constant baseline per field (most
frequent gold value), now pre-registered.

## Success criteria for the replication (fixed now)
P3 reference (C, Wilson 95%): number 21/29 [0.54, 0.85]; affair_type 27/29 [0.78, 0.98]; submitter 23/29 [0.62, 0.90];
submitted 15/21 [0.50, 0.86]; answer_date 22/27 [0.63, 0.92]; decision_number 0/17 [0.00, 0.18]. P3 H3 without
addressed_body: recall 6/8 [0.41, 0.93], precision 6/9 [0.35, 0.88].
- **S1 (primary) H3 recall holds again:** primary H3 recall Wilson lower bound >= 0.50. If fewer than 10 open pairs have a
  gold value, S1 is "inconclusive (underpowered)", not failed.
- **S2 per-field accuracy consistent with P3:** among fields with >= 10 gold values in both P3 and P3b (P3: the six above),
  each P3b C point estimate is classed below / within / above P3's Wilson 95% CI. S2 holds if at most one field is below.
- **Verdict:** "replicated" if S1 and S2 hold; "partially replicated" if exactly one holds (or S1 inconclusive and S2
  holds, stated as such); "not replicated" otherwise. H1 tiers and H3(b) are reported against P3 without a verdict.

## Not allowed after the lock
Changing any frozen file, the seed, the bodies, quotas or reserves, the guide, the hypotheses or the success criteria.
Any change is a reported deviation in `eval/prereg5/DEVIATIONS5.md`; failed fetches, shortfalls and failed runs are reported.
