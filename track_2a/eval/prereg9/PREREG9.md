# Pre-registration P8: does a "shared" field mean the same thing in every parliament? (frozen by eval/prereg9/LOCK9)

**Question.** Schema v0.1 classes 12 of its 17 fields as *shared* by definition. Meaning is tested for none of them:
the 5 role-split fields were found from OPD's own label vocabularies, and for the government recommendation OPD's
label mapping is unambiguous, which is a string check, not a test of meaning (README, `docs/ech-onepager.md`,
`data/schema/field_verdict_classes.json`). P8 tests, on fresh affairs from twelve parliaments, what the value of seven
fields **denotes** in each parliament, judged from the affair's own documents, against a closed set of meaning
categories fixed here, and decides per field whether it is shared, needs a role split, or is body-specific.

**Written before any P8 affair is drawn.** Fields, categories, the shared-meaning sets, parliaments, quotas, seeds,
exclusions, the derivation code, the guide, the decision rules and every threshold are fixed here and in the hashed
code. The sampler (`eval/p8/sample.py`) refuses to run until LOCK9 is committed and unchanged. No P8 affair, packet or
label exists at registration; `eval/prereg9/lock9.py write` refuses if one does. The only look at the pool before
registration is `results/p8/pool_probe.json`: the number of eligible affairs per parliament and group after the
exclusions, from which the quotas were written; no affair was selected or opened.

**What shaped the categories (all from committed material, none from a P8 affair).** OPD's contributor-role
vocabulary (`data/census/contributor_roles.tsv.gz`) harmonises printed co-signers as `author` in many bodies
(e.g. "Mitunterzeichnende/r" in Bern city, 27,289 rows; "Cofirmatari" in Ticino, 22,860; "Mitunterzeichnerin /
Mitunterzeichner" in Zürich canton, 14,728, and Graubünden, 11,386), while the federal parliament has a separate
`cosign` role; the census counts OPD's lead department ("Federführung", role `leading_department`) as the addressed
body (`census/matrix.py`, ADDRESSED_ROLES); OPD tags 1,954 documents with the language "GR" and 1,056 with "de;fr"
(docs scan); in P3b affair 15393 OPD's first `author` is a person the gold labels as a co-signatory. The definitions
of submitter, co-signatories, submission date and addressed body follow the P3 guide (`eval/gold3/GUIDE.md`); the
recommendation values follow schema v0.1 (`GovRecommendation`).

## 1. Design in one paragraph

72 fresh whole affairs (member's text + executive answer), 6 from each of 12 parliaments (cantons and communes; German,
French, Italian and multilingual), none in any existing gold, dev, test or audit set. Two blind Claude-agent
annotators (A1 Opus, A2 Sonnet) label what the two documents print: who lodged the intervention and in what role, the
procedural role of every printed date, whom it addresses, what it asks for and what it calls itself, the languages of
each document, and the executive's recommendation. They never see OPD's metadata. Code then derives, per affair and
field, the **meaning category of the value schema v0.1 carries** (OPD's metadata value where OPD has one, located in
the annotators' inventory; else the printed value). A3 (Opus) decides fields whose derived category differs.
Qwen-SEA-LION-v4-32B-IT relabels every packet as an independent check that changes nothing. Per field and
parliament: the share of affairs in the field's shared-meaning set E with a Wilson interval; the field's verdict by
the rules in §7. No model is part of the system under test; no Apertus call is made.

## 2. Fields, categories and the shared-meaning sets (`eval/p8/common.py`, `eval/p8/derive.py`)

The *carried value* is the value schema v0.1 carries for the field. Its *layer* is `opd` when OPD's metadata supplies
it (located by name or date in the annotators' inventory; never shown to them) and `doc` when it comes from the
documents. *Undeterminable* affairs (reason recorded) are in no denominator. Categories in **bold** form E.

| field | carried value | applicable | categories (E in bold) | unnamed |
|---|---|---|---|---|
| submitter | OPD's first `author` person (frozen `affair.extract.from_metadata`), else the printed author of record | all | **author_person**, joint_person, cosigner_person, group, committee_or_body, other | other |
| co-signatories | OPD's further `author` persons, else the printed co-signatories, supporters and further joint authors | the carried list is not empty | **cosigners**, supporters, cosigners_and_supporters, joint_authors, includes_author_of_record, signing_for_group, other | other |
| submission date | OPD's submission date (earliest submission event, else `begin_date`; `from_metadata`) | all | **lodged**, **cited**, later_step, answer_or_decision, other_printed, unprinted_differs | other_printed, unprinted_differs |
| addressed body | the printed addressee (the product takes it from the documents) | all | **executive**, executive_member_or_department, parliament, committee, administration, other | other |
| language | OPD's language tag of the member's text | all | **text_language**, subset_of_text, superset_of_text, other_language, invalid_tag | – |
| government recommendation | the printed recommendation's procedural act | OPD type Motion or Postulate | **on_referral**, on_fulfilment, other | other |
| type | OPD's harmonised type (Motion, Postulate, Interpellation, Question) | all | **conforms**, mandate, examine_report, questions, direct_decision, other | other |

Definitions (the annotators' side is `eval/p8/GUIDE_P8.md`; the derivation is `eval/p8/derive.py`):

- **submitter.** The carried person is matched by name (all surname tokens printed, first initial compatible) to the
  people the annotators list with a role: sole author or designated first signatory → `author_person`; one of several
  equal authors with none designated → `joint_person`; a co-signatory or supporter → `cosigner_person`; a spokesperson
  for a group (committee) that is the author of record → `group` (`committee_or_body`); any other role → `other`; not
  printed → undeterminable. Several matches: the highest role in the order sole/first, joint, spokesperson,
  co-signatory, supporter, other. Without an OPD author: the kind of the printed author of record (person → E;
  group; committee or other body), else `joint_person` if joint authors are printed.
- **co-signatories.** The roles of the matched carried names: all co-signatories → `cosigners`; all supporters →
  `supporters`; both → `cosigners_and_supporters`; all joint authors → `joint_authors`; any carried name is the author
  of record → `includes_author_of_record` (checked first); any spokesperson → `signing_for_group`; else `other`.
  No carried name printed → undeterminable; no list in OPD and none printed → not applicable.
- **submission date.** The roles the annotators give the dates in the packet's date list (every distinct date the
  frozen parser `repair.common.parse_dates` finds, plus dates the annotators add when the parser misses them). The
  carried date d is `lodged` if d is printed as signed, lodged/received or handed in at a sitting; else `cited` (the
  date by which a heading or the answer names the intervention); else `later_step` (announced, read, justified,
  debated, referred, urgency, deadline); else `answer_or_decision`; else `other_printed` (printed in another role or in
  the content). d not printed: `unprinted_differs` if some lodging date is printed, else undeterminable.
- **addressed body.** The body the intervention asks to act or answer, judged by function: the executive as a body
  (E); a named member or department of the executive; the parliament (asked to decide itself); a committee; the
  administration; other. `none_printed` → undeterminable.
- **language.** T = OPD's tag of the member's text (split on ";"), P = the languages the annotators find in its text.
  T = P → E; T ⊂ P → `subset_of_text`; T ⊃ P → `superset_of_text`; disjoint or partly overlapping → `other_language`;
  T contains a value that is not a language code → `invalid_tag`; untagged or P empty → undeterminable. (The answer
  document's category is reported as secondary.)
- **government recommendation.** The procedural act of the printed recommendation: a recommendation on how parliament
  should decide on adopting or referring the motion or postulate, including accept-and-write-off (E); a request to
  approve the executive's report on, or to write off, a motion or postulate already adopted or referred
  (`on_fulfilment`); by another actor or on another object (`other`). No executive answer, `none_printed` or
  `not_applicable` → undeterminable.
- **type.** The operative request of the member's text: `mandate` (charges the executive to act or to draft),
  `examine_report` (asks it to examine and report), `questions`, `direct_decision` (a decision parliament takes itself
  on the text), `other`. E is the function the harmonised type names: Motion → mandate, Postulate → examine_report,
  Interpellation and Question → questions; an affair whose function equals it `conforms`, else its function is its
  category. `unclear` → undeterminable.

## 3. Sample (`eval/p8/common.py`, `eval/p8/sample.py`)

**Parliaments and quotas** (MP = Motion/Postulate, IQ = Interpellation/Question; eligible affairs after the
exclusions from `results/p8/pool_probe.json`; "tagged" = eligible affairs whose member text OPD tags with a language):

| parliament | level | stratum | quota MP + IQ | eligible MP | eligible IQ | tagged |
|---|---|---|---|---|---|---|
| Thurgau (TG) | canton | de | 4 + 2 | 143 | 673 | 0 |
| Valais (VS) | canton | multi (de/fr) | 4 + 2 | 924 | 413 | 1,337 |
| Bern city (351) | commune | de | 4 + 2 | 85 | 1,017 | 1,102 |
| Zürich city (261) | commune | de | 4 + 2 | 146 | 490 | 0 |
| Vaud (VD) | canton | fr | 2 + 4 | 2 | 301 | 0 |
| Fribourg (FR) | canton | fr (bilingual) | 4 + 2 | 99 | 141 | 240 |
| Lausanne (5586) | commune | fr | 4 + 2 | 73 | 241 | 314 |
| Vernier (6643) | commune | fr | 4 + 2 | 72 | 36 | 108 |
| Ticino (TI) | canton | it | 0 + 6 | 0 | 1,493 | 20 |
| Lugano (5192) | commune | it | 4 + 2 | 91 | 409 | 0 |
| Bellinzona (5002) | commune | it | 4 + 2 | 57 | 2 | 0 |
| Graubünden (GR) | canton | multi (de/rm/it) | 4 + 2 | 276 | 320 | 596 |

72 affairs: 42 Motion/Postulate, 30 Interpellation/Question. Valais replaced Luzern before registration because OPD
tags none of Luzern's documents; with Valais six parliaments carry language tags, the minimum for the language field
to be testable (§7). No language filter is applied anywhere (the language field is under test).

**Qualification.** OPD harmonised type Interpellation, Motion, Postulate or Question; one document typed as the
member's text and one as the executive's answer (P3's frozen `pair_type` first, else P6's frozen `doctype6`; per role
the lowest id of the P3-typed documents, else of the P6-typed ones), both with OPD text status ok and 1,000-40,000
characters; after fetching, at least 1,000 extracted characters (`eval.gold2.sample.fetch_one`).

**Exclusions** (2,436 affairs, 1,022 documents at registration): every affair and document of P1 dev + held-out (+ the
spikes and every dev-id source), P2, P3, P3b, P4 (dev, held-out, transfer), P5 dev + test, DEV2, P6, P7 dev + test and
the adapter audits (design + backup copy, v2, v3). The WORK lists (P7 keys, audits) are hashed in LOCK9.

**Draw.** Per parliament and group, the eligible affairs sorted by id and shuffled with
`random.Random(f"20261042:{body}:{group}")`; taken in that order. A failed fetch is replaced by the next affair of the
same cell; a cell whose pool runs out is filled from the other group of the same parliament. No other replacement:
an affair whose documents turn out to be something else stays in the sample (its fields become undeterminable as the
labels say). Fetching uses the project's fetch path only (gegenprobe.net with the RFC 9309 matcher, OPD's copy for
mirrored URLs, polite rate). Committed after the draw: `data/p8/p8_affairs.jsonl` (ids, URLs, sha256, pages,
characters, OPD tags; never text), the fetch log, OPD's metadata of the drawn affairs (`data/p8/opd_meta_p8.jsonl`,
frozen `affair.meta.vendor`), the date lists without context (`data/p8/p8_datelists.jsonl`), `results/p8/sample.json`.

## 4. Derivation and the disagreement key

`eval/p8/derive.py` computes every field's carried value, layer and category from one label and OPD's metadata, by the
rules of §2; `eval/p8/selftest.py` checks the rules and every verdict path on synthetic labels (passes at registration).
The disagreement key of a field is its derived category (or n/a).

## 5. Gold protocol (`eval/p8/packets.py`, `eval/p8/annotate.py`, `eval/p8/GUIDE_P8.md`)

- **Packets** (WORK only, never committed): an opaque id (ids assigned in seeded random order), the two documents as
  extracted (the sha256-verified cached text every earlier set used), page-delimited, and the parser's date list with
  up to three printed lines per date. No OPD metadata, parliament key, cell or hypothesis.
- **Annotators.** A1 (Claude Opus) and A2 (Claude Sonnet) label every packet blind, each in its own session, with
  `GUIDE_P8.md`; every file must pass `python -m eval.p8.annotate selfcheck` (closed vocabularies; every quote verbatim,
  whitespace-insensitive, on the page it names; each person's last name inside the quote; date letters from the
  packet's list). The lead launches them; no human labels.
- **Tie-break.** For each packet, the fields whose derived category differs between A1 and A2 go to A3 (Claude Opus),
  who sees the packet and the two labels of those fields as X and Y in seeded random order (seed 20261043) and labels
  them anew. Gold per field: the A1 label where A1 and A2 agree on the category, else A3's.
- **Committed after the merge:** `data/p8/p8_gold.jsonl` (per affair and field: source, layer, category, reason,
  document-layer and OPD-layer categories, secondary values, the label parts with every quote replaced by its sha256
  and resolved span), `data/p8/annotations/{A1,A2,A3}.jsonl` (same treatment; notes stay in WORK),
  `data/p8/p8_key.jsonl`, `results/p8/p8_agreement.json` (per field raw agreement and Cohen's kappa of A1 vs A2, fields
  decided by A3). No document text is committed.
- **Independent check (registered; it changes nothing).** `Qwen-SEA-LION-v4-32B-IT` through the budget gateway (tag
  `2a-p8-qwen`, cap USD 0.8; the served model is checked on every call) labels every packet blind with the same
  vocabularies (shortened view: member text first 14,000 characters, answer first 8,000 + last 3,000, full date list;
  no quotes asked). Its labels go through the same derivation; `results/p8/p8_qwen.json` reports per field agreement
  and kappa with the gold (an unparseable reply counts as a disagreement). No Apertus model is used anywhere in P8.
- Annotation session times are recorded as for every earlier set.

## 6. What is reported (`eval/p8/score.py` → `results/p8/p8_tables.json`; `eval/p8/hypotheses9.py` → `results/p8/p8_hypotheses.json`)

Per field and parliament: affairs, applicable, determinable, undeterminable by reason, not applicable by reason,
counts per category, carried-value layer (opd/doc), n in E, share in E with Wilson 95% interval, affairs outside E,
the exceptions allowed, evaluable / conforms / deviates, and outside-E affairs in named vs unnamed categories. Per
field: the pooled share in E over the evaluable parliaments with a parliament-cluster bootstrap 95% interval (10,000
resamples of parliaments, seed 20261044) and a Wilson interval; the same over all parliaments with a determinable
affair; the verdict, the evaluable and deviating parliaments, each deviating parliament's kind and repeated roles, the
other-meaning test; the verdict recomputed on affairs whose field A1 and A2 labelled alike (sensitivity, never
decisive). **Secondary, OPD vs documents (agreement, never decisive):** submitter: OPD's first author is the printed
author of record (n of affairs with both), OPD's submitter not printed; co-signatories: surname-set Jaccard and
identical sets; submission date: OPD's date equals the earliest printed lodging date, within 1 day, offsets (median,
IQR), per parliament; addressed body: the printed addressee where OPD names a lead department; language: the answer
document's category and the tags seen; recommendation: OPD's value equals the printed value, and how many value words
fit the printed wording; type: the printed instrument name equals OPD's type, and the function per OPD type. Also the
gold agreement and the Qwen check. Every outcome is reported, including inconclusive fields.

## 7. Hypotheses and decision rules (fixed now)

For each field f: **H(f): f is shared**, i.e. its carried value falls in E_f in every parliament. Thresholds:
X = 0.90, K = 3, MIN_PARLIAMENTS = 6.

- A parliament is **evaluable** for f with at least K determinable affairs; it **conforms** when at most
  max(1, floor(0.10 × n)) of its n determinable affairs fall outside E_f (at n ≤ 19 one exception: a single affair is
  never enough to call a parliament different, it may be a labelling error); otherwise it **deviates**.
- A deviating parliament is *unnamed* when more than half of its affairs outside E_f fall in an unnamed category, else
  *systematic* when one named category outside E_f holds at least 2 of its affairs, else *scattered*.
- **shared**: at least 6 evaluable parliaments, none deviates, and the pooled share in E_f over the evaluable
  parliaments is ≥ 0.90.
- **body_specific**: some deviating parliament is unnamed.
- **role_split**: no deviating parliament is unnamed and at least one is systematic; the roles to keep apart are its
  repeated named categories.
- **shared_other_meaning**: replaces body_specific, role_split or the scattered case when the most frequent category c
  outside E_f passes the `shared` test on its own (every evaluable parliament conforms to {c}, at least 6, pooled ≥
  0.90): the field is shared, but not in the meaning v0.1 gives it.
- **inconclusive**: no parliament deviates but fewer than 6 are evaluable or the pooled share is < 0.90; or every
  deviating parliament is scattered.

H1 submitter, H2 co-signatories, H3 submission date, H4 addressed body, H5 language, H6 government recommendation,
H7 type (the harmonised type names one instrument function). Seven hypotheses, each decided by the same rule; no
correction is applied (each verdict is a per-field classification, reported with its per-parliament counts).

**Operating characteristics (computed now).** If a fraction q of gold labels were wrong at random, a parliament with
6 determinable affairs would deviate by chance with probability 0.6% (q = 2%), 1.3% (3%), 3.3% (5%); the systematic
condition (two affairs in the same named category) lowers the chance of a false role split further. If a parliament
truly used the field in another meaning for a third, half or two thirds of its affairs, it deviates with probability
0.64, 0.89, 0.98 at n = 6 and 0.40, 0.69, 0.89 at n = 4 (the recommendation's typical n). The language field can be
decided as shared only if all six tagging parliaments are evaluable.

## 8. Consequences (written now)

- **shared**: `field_verdict_classes.json` sets `meaning_tested` = "measured (P8): shared" with the evidence path; the
  field stays in class shared.
- **role_split**: the field moves to class `shared_with_role_split`; the roles to keep apart are the named categories
  found; the schema documentation names them.
- **body_specific**: the field is marked body-specific for the deviating parliaments' meaning; a standard needs the
  body's own vocabulary there.
- **shared_other_meaning**: the field stays shared; its definition is rewritten to the category every parliament shares.
- **inconclusive**: the field stays "by definition, untested", with the P8 reason.
- The README and `docs/ech-onepager.md` state "meaning tested for N of 17" with N = 5 (role split, from OPD's labels)
  + the P8 fields with a verdict other than inconclusive, and report the secondary agreement as agreement, not meaning.
  Every outcome goes into `results/p8/`, the docs and the claims file, including failures.

## 9. Order of operations and stop points

1. LOCK9 committed (the lock commit holds this file, `eval/prereg9/`, `eval/p8/`, `results/p8/pool_probe.json`).
2. `PYTHONPATH=src:. .venv/bin/python -m eval.p8.sample` (network; once) → the draw files of §3 and the packets;
   the draw files are committed before any label exists.
3. **Annotation point.** A1 and A2 label blind; `annotate verify A1|A2`; `annotate a3packets`; A3 on disputed fields;
   `annotate verify A3`; `annotate merge`.
4. `qwen9 run`, `score`, `hypotheses9`, `qwen9 score`; results committed with the gold.

## 10. Not allowed after LOCK9

Any change to the hashed files (fields, categories, E, derivation, parliaments, quotas, seeds, exclusions, guide,
analysis, thresholds) or to the reused frozen code. Later changes are listed in `eval/prereg9/DEVIATIONS9.md` with
their effect.
