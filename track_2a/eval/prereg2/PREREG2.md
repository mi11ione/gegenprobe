# Pre-registration P2 — unseen parliaments (frozen by eval/prereg2/LOCK2)

**Question.** The P1 held-out set (eval/prereg/PREREG.md, LOCK 812030f) held out *documents*, not *parliaments*: its 154
documents come from the same 16 bodies as the dev set the rules were written on, and one rule anchors on a body-specific
letterhead ("Bellinzona …"). P2 asks how the frozen converter does on parliaments it has never seen, and whether the
closed-set pointer — which carries no body-specific layout knowledge — recovers answer dates the rules miss there.

**Written before any P2 document was drawn.** Seed, body list, quotas and every threshold below are fixed in this file;
`eval/gold2/sample.py` reads them from here. LOCK2 hashes this file, the drawn document list, the P2 code and (copied) the
P1 frozen hashes; the LOCK2 commit must precede the first commit that adds P2 labels (`data/gold2/p2_labels.jsonl`).

## Frozen system (no change from P1)
Rules, lattice, pointer, prompts, cascade, scorer and θ exactly as locked in P1 (LOCK 812030f, 33 files; hashes copied into
LOCK2). Build: Public AI name `swiss-ai/apertus-v1.5-8b`, which serves the **70B** weights, through the budget gateway, the
response `model` field checked on every call.
- **θ primary = 10.40** (P1 dev fit, `data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json`).
- **θ secondary = 0.** This value comes from the P1 *post-hoc* θ curve (θ ≈ 0–2.5 scored best on the P1 held-out) and the
  earlier live spike; it is registered here as a hypothesis to test on fresh data, not as a P1 result.
- The 8B GGUF build is added as an exploratory arm if its CI run (θ fitted on dev for that build) completes; otherwise it is
  reported as not run.

## Documents
- **Seed: 20261011.**
- **Unseen bodies:** bodies with no document in `data/gold/dev_docs.jsonl`, `data/gold/heldout_docs.jsonl` or any source
  listed in `data/gold/dev_ids.json` (spikes, recovery audit, Bilanz). 15 bodies, quotas (OPD metadata document type;
  annotators set the labels):

| cell | executive answers (expected value class) | member texts (expected null class) |
|---|---|---|
| de_canton | NW 6, OW 2 | SZ 2, GL 3, SH 3, AR 3, OW 2, NW 2 |
| de_commune | — | Luzern city (1061) 4, Schlieren (247) 3, Kloten (62) 3 |
| fr_canton | VD 8 (fr) | — |
| fr_commune | Vernier (6643) 3, Sion (6266) 3, Fribourg city (2196) 3 | La Chaux-de-Fonds (6421) 3, Sion (6266) 3 |
| it_commune | Bellinzona (5002) 6 | — |

  (62 documents, 15 bodies.) Cells without a class have no such documents of usable length in the OPD metadata; that imbalance is
  reported, not filled from seen bodies.
- **Length window** as P1: OPD text length 4,000–8,000 characters, text layer present. One document per affair; no affair
  or document shared with P1 dev/held-out or the spikes. A fetch failure (robots.txt disallow, not a PDF, HTTP error) is
  replaced by the next document of the same body and type in seeded order, logged in `eval/gold2/SEEDS.md`.
- **Disclosed proximity:** Bellinzona (5002) is unseen, but the frozen TI cantonal rule `ti_header_date` anchors on the place
  name "Bellinzona". Every P2 result is reported **with and without Bellinzona** (pre-registered sensitivity).

- **Revision before LOCK2 (draw v1 → v2, no label existed):** draw v1 used a language filter "de" for NW/OW answers, which
  excluded every NW/OW answer (OPD leaves their language untagged), and canton FR (api.fr.ch) disallows our user agent in
  robots.txt for every document, as does SZ for most; Fribourg city's member texts are HTML pages. v2 (the table above)
  drops canton FR, takes NW/OW answers without a language filter (both bodies are German-speaking), moves the FR-canton
  answer quota to VD, and replaces Fribourg city member texts by Sion; seed unchanged. Both draws are logged in
  `eval/gold2/SEEDS.md`.

## Labels
Same protocol as P1 (`docs/gold_protocol.md`, guide `eval/gold2/GUIDE.md`, identical in substance to the P1 guide): two blind
Claude-agent annotators (A1 Opus, A2 Sonnet), a third (A3 Opus) on disagreements only, quotes verified verbatim by code,
κ reported. **Change from P1:** the two labels shown to A3 are in a seeded random X/Y order (seed 20261011), so A3 cannot
learn which annotator is which. No human labels or adjudication.

## Arms and metrics
`eval/gold2/run_p2.py` runs the frozen `eval.arms.run` on the P2 documents: `rules`, `pointer`, `cascade` (every review
suggestion accepted), `naive_plain`, `naive_null` (same weights, free generation), at θ = 10.40; the θ = 0 decisions are
recomputed from the same cached scores (`eval/gold2/hypotheses2.py`). Metrics exactly as P1 (`eval/score.py`, strict), plus,
as pre-registered reporting: **value recall** (correct values / gold-value documents), the **always-null baseline** (exact =
gold-null share), and the **precision of Apertus-decided values**.

## Hypotheses (decided now)
1. **P2-H1 rules generalisation.** Rules value recall on P2 gold-value documents vs on P1 held-out gold-value documents
   (47/64). Confirmed (the rules do not generalise) if the 95% Newcombe interval of the difference (P1 − P2) excludes 0.
2. **P2-H2 primary: does the pointer generalise better than the rules?** On P2 documents with a gold answer date, `pointer`
   correct vs `rules` correct, paired exact McNemar, two-sided α = 0.05, at θ = 10.40. Holds if p < 0.05 and the pointer is
   right on more documents than the rules. Secondary (reported, no decision attached): the same at θ = 0, and `cascade` vs
   `rules`.
3. **P2-H3 null safety on new bodies.** `cascade` values on P2 gold-null documents: holds if the Wilson 95% upper bound is
   ≤ 15%, at θ = 10.40 (θ = 0 reported alongside).
4. **P2-H4 abstention signal.** AUROC of the pointer null margin, gold-null vs gold-value documents (documents with ≥ 1 date
   candidate) ≥ 0.80.

## Consequences (written now)
- **P2-H2 holds:** the review mode (rules + Apertus suggestions) is recommended for parliaments without hand-written rules,
  and the report says that Apertus carries the long tail of parliaments where rules do not exist.
- **P2-H2 fails:** the report says the pointer does not generalise better than the rules either, and that extending the
  converter to new parliaments needs per-body rules or adapters.
- **P2-H3 fails:** suggestions on new bodies need a stricter θ; the frozen result is reported unchanged.
- **P2-H4 fails:** the null margin is not reported as a usable abstention signal on new bodies.
- Every outcome, including failures, is reported; the 8B arms are exploratory.

## Not allowed after LOCK2
Any change to the frozen P1 system, θ values, the document list, the guide, the annotation wrapper, the runner or the
hypothesis script. Later changes are listed in `eval/prereg2/DEVIATIONS2.md` with their effect.
