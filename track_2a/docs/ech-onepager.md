# Gegenprobe schema v0.1 and v0.2: one page for the eCH expert group

What a common schema for the business of Swiss parliaments needs, measured on OpenParlData (OPD, snapshot 6 Oct 2026,
89 parliaments with affairs in scope). Normative models: `src/gegenprobe/schema/schema_v0_1.py` (Pydantic); JSON Schema
with `$id` and version 0.1.0: `results/schema/*.schema.json`; v0.2 with P8's roles: `schema/gegenprobe_schema_v0_2.py`,
JSON Schema `results/schema/v0_2/affair.schema.json`; field guide: `docs/schema.md`; mappings to Popolo, Akoma
Ntoso, Parla-CLARIN and OParl: `docs/mapping.md`.

**In one line:** a common schema works if its fields carry roles, and not only for dates. Of the 17 fields, 10 need
roles (8 robust, 2 fragile), 1 is body-specific, and 6 are defined once in v0.1 (their meaning is
the next test). "Answer date" is the government's decision in some parliaments, the letter or registration date in
others and in 7 bodies mostly the submission date; v0.1 makes the role explicit on every date. A pre-registered test on
66 fresh affairs from 11 parliaments (P8) finds roles in fields v0.1 defined once: authorship (sole author, first
signatory, joint authors, parliamentary group), signatories, the instrument behind a harmonised type, and the date a
submission really carries; §2 turns each finding into a recommendation. Meaning is now measured for 11 of the 17
fields. **v0.2 ships P8's roles and validates 171 affairs**: the converter's own records for P3 (29), P3b (36) and P5
(40) and the 66 P8 affairs; the v0.1 samples upgrade losslessly (`results/schema/v0_2/validation_all.json`).

## 1. Classes (by meaning, measured on OPD's labels and on the documents)

| class | fields and concepts | what it means for a standard |
|---|---|---|
| **shared with a role split** (10 of 17: 8 robust, 2 fragile) | answer date, procedural history, type, procedural state, decision outcome (from OPD's labels; all 5 are measured); submitter, co-signatories, language (P8; type splits there too); addressed body and government recommendation (P8, *fragile, to confirm*: split on the gold, not under both checks) | one label covers several roles that must be kept apart before parliaments can be compared; the roles are named in §2 and in `data/schema/field_verdict_classes.json` |
| **body-specific** (1 of 17) | submission date: in Vernier and Lausanne OPD's date is mostly printed nowhere in the documents (P8, under both checks) | a standard records which event the date is |
| **defined once in v0.1** (6 of 17) | decision date, dispatch date, Q/A pairing, related affairs, usable text, answer-link status | one definition in v0.1; their meaning is the next test (the same test as P8); *where* the value lives (metadata, PDF, or not in OPD) is measured |
| **body-specific** (3 concepts, not among the 17 fields) | oral answers in question time; executive business that answers no member's affair; councils that publish only meeting documents | needs its own construct, not a field: v0.1 types oral answers as a null reason and marks affairs rebuilt from minutes `virtual` with `derived_from` |

For the government recommendation OPD's harmonised labels map unambiguously (0 of 183 raw labels map to different
concepts, a string check); the documents show the split P8 found, by procedural stage. Evidence:
`results/census/comparability.json`, `results/p8/p8_hypotheses.json`, classes and the `meaning_tested` flag in
`data/schema/field_verdict_classes.json`. Separately, *where* the value lives (`results/census/matrix.json`):
4 fields are in OPD's metadata almost everywhere, 13 partly; no field lacks a written source in a fifth of the
parliaments (5 would at a 10% threshold). That threshold measures coverage, not meaning; the classes above are the finding. Tables,
annexes and images inside answer documents are the next extraction target, and with them their structure in the schema.

## 2. Roles a standard needs: per-field recommendations (P8)

P8 (`eval/prereg9/PREREG9.md`, frozen by LOCK9 before the draw) took 66 fresh affairs from 11 parliaments, cantons and
communes in German, French and Italian, read the two documents OPD links to each (the member's text and the
executive's answer) and had blind annotators label what each field's value denotes, against categories fixed in
advance. A field is shared when every parliament with enough affairs keeps it in its one meaning (one exception
tolerated); a parliament that departs systematically names a role. Share in v0.1's meaning, pooled over parliaments
(parliament-cluster 95% interval), and the recommendation:

- **Submitter: a role per author, not a slot** (role split; 35/65 [33.3%, 75.0%]). Bern city, Vaud and Lausanne
  print a sole author or designated first signatory; Zürich city, Thurgau, Fribourg and Vernier print joint authors
  with none designated first, and OPD's "submitter" is whichever is listed first; in Valais the author of record is a
  parliamentary group. *Recommend:* `Actor.role` ∈ {sole_author, first_signatory, joint_author, co_signatory,
  supporter, spokesperson} with `kind` ∈ {person, group, committee}. *In v0.2:* `Actor.role` adds `sole_author`,
  `joint_author`, `supporter`, `spokesperson` and `group` to v0.1's `first_signatory`, `co_signatory` and `committee`;
  groups and committees are actors (`kind`), and a spokesperson names the body it speaks for (`on_behalf_of`).
- **Co-signatories: the printed role of each person, not a derived list** (role split; 10/41 [6.8%, 46.3%]). Bern
  city prints two to four first signatories ("Erstunterzeichnende"), so OPD's co-signatory list includes authors of
  record; elsewhere the list holds joint authors (Zürich city, Thurgau, Fribourg, Vernier) or persons signing for a
  group (Valais). *Recommend:* derive no co-signatory tail from an author list; carry each person with the role above.
- **Type: the instrument behind the harmonised value** (role split; 55/64 [76.2%, 95.3%]). Two Bellinzona "Motions"
  propose a decision the council takes itself; two Valais "Postulate" mandate the executive to act. *Recommend:* carry
  the operative request next to the harmonised type. *In v0.2:* `type.instrument_function` ∈ {mandate,
  direct_decision, examine_report, questions, other}, with `type.instrument_named`.
- **Language: the text's language, apart from the source's tag** (role split; 34/36 [83.3%, 100.0%]). In Fribourg 2 of
  6 tags name the other official language; 5 of 11 parliaments tag no document. *Recommend:* record the language
  determined from the text and, separately, the tag the source carries. *In v0.2:* `Document.language_of_text` and
  `Document.language_tag`.
- **Submission date: the event and its source** (body-specific; 44/57 [57.1%, 91.8%]). In 9 of 11 parliaments OPD's
  date is the printed lodging date (one exception allowed); in Vernier (0/5) and Lausanne (2/5) it is mostly printed nowhere in the documents,
  2 to 28 days after the lodging date they print. *Recommend:* give the submission date a role and a source like every
  other date. *In v0.2:* `DateRole` adds `signed`, `lodged`, `received`, `announced` and `later_step` (v0.1's
  `submitted` stays for a source's own "submitted" event).
- **Addressed body and recommendation: fragile, to confirm.** Both split on the gold but not under both registered
  checks (the addressed body is shared on agreed labels only, the recommendation on Qwen's labels). Addressed body:
  the executive in 10 of 11 parliaments (one exception allowed); Bellinzona's direct-decision instruments address the council itself, which
  `instrument_function` already captures. Recommendation: "accept" at referral and "approve the report and write off"
  on a motion already adopted (Vernier) are different acts; *in v0.2:* `government_recommendation.stage` ∈
  {on_adoption, on_fulfilment} next to the value.

Labels: two blind Claude annotators (Opus, Sonnet), a third on 11 disputed fields; another vendor's model
(Qwen-SEA-LION) gives the same verdict for the five robust fields above. Every outcome, the tables per parliament and
the agreement checks: `results/p8/`, [`docs/evaluation.md`](evaluation.md#p8-what-the-shared-fields-mean). Ticino is not
in the sample: its robots.txt disallows the documents, and our fetch guard refused them.

## 3. The answer date is three dates

"Answer date" in OPD can be the date the government **decided** (Regierungsratsbeschluss), the date the answer was
**dispatched**, or the date parliament **registered** it. In 7 of 54 bodies OPD's "answer" event is mostly the
submission date; on our held-out gold OPD's event equals the printed date for 37 of 44 checkable documents, and 5 of the
other 7 are 1–5 days apart (decision vs dispatch). OPD's answer date is verified as the decision date only in Bern and
Ticino. v0.1 therefore carries a `DateRole` on every date (`answer_decided`, `answer_dispatched`, `answered`,
`submitted`, `scheduled`, `debated`, … in `data/schema/date_roles.json`), and a date-trust tier per parliament in the
research dataset (`results/census/interventions.tsv.gz`, `results/census/date_trust.json`).

## 4. No bare nulls

Every extractable field is either a value with provenance (`basis`: extracted, normalised, metadata or inferred; the
deciding `route`; for document values page and character span) or a **typed null** that says why it is empty:
`not_in_corpus`, `unlinked` (the document exists in OPD but is not attached), `image_only`, `text_failed`, `oral`,
`present_unanchored`, `not_in_document`, `no_rules_for_body`, `not_applicable` (`data/schema/null_reasons.json`). A
model's document-level classification (e.g. a recommendation chosen from a closed set) names its document and the set
it chose from instead of a span, and is a review suggestion, never an unattended value.

The product record does not carry a null whose reason is not true. Our whole-affair assembly (frozen for the P3/P3b
evaluation) wrote `answering_body` as `present_unanchored` although that field was never extracted; schema v0.1 has no
reason for "not attempted", so the product post-processing (`gegenprobe.affair_post`) leaves the field out and says so
(`omitted`), and an interpellation's `decision` is `not_applicable`, not `not_in_corpus`. v0.2 adds the
`not_extracted` reason, so that a record can be complete and honest at once.

## 5. Question by question: `QAItem`

Interpellations and written questions ask numbered questions, and the answer replies to each. `QAItem` pairs question
*n* with the answer to question *n*, both sides with a span or a typed null (an answer that replies to all at once is
`present_unanchored`). It is in v0.1 as an optional, additive structure, and our converter now fills it
(`src/gegenprobe/qa/`, `docs/qa.md`). The pre-registered test P5 (40 fresh affairs from 10 parliaments, DE/FR/IT) puts
rule-based pairing at precision 0.83 and recall 0.67: usable with a reviewer, not yet unattended (the *partial*
tier holds with document-level intervals, not when whole parliaments are resampled). It transfers where the
answer numbers or repeats the questions ("Zu Frage 2", "Réponse à la question 2") and fails where it does not (Valais
0/11). For a standard this argues for asking executives to number their answers; a v0.3 candidate is a `QAItem` field for
an answer that replies to several questions at once (the converter tracks it internally as `joint_with`).

## 6. Five gaps for the next version (cited evidence)

An inventory of what the answers state, over 12 bodies, left 45.9% of statements without a schema account; five gaps
recur across bodies and languages: **person roles; comparison amounts; dates and laws of other polities; dates of
other affairs; entry-into-force and deadline dates** (`docs/census.md`, `data/census/cited_evidence.json`; cited, not
recomputed by `make run`).

## 7. Proposal

Adopt date roles, typed nulls and the classes of §1 as the frame; standardise the role split for the answer date first
(it decides every answer-time comparison); treat oral answers, executive-own business and minutes-only councils as
named constructs. v0.2 ships the P8 roles of §2 (author roles, `instrument_function` next to the type, the language
from the text apart from the tag, submission-date roles, the recommendation's `stage`) and a `not_extracted` null
reason; 171 affairs validate in it, 105 of them the converter's own records (P3, P3b, P5). Next for v0.3: a `QAItem`
field for joint answers (measured, P5) and the five gaps. Test plan for the six fields defined once (decision and dispatch dates, Q/A pairing, related affairs, usable text,
answer-link status): the same P8 protocol, with Ticino's documents once its robots.txt permits them. OPD vocabulary errors found on the way
(e.g. the harmonised type "Votaziun", Romansh for a vote, on 9,887 affairs) are listed in `results/census/vocab_bugs.tsv`. Gegenprobe (Hack Apertus,
Track 2A, team 444): https://gegenprobe.mi11ion.io.
