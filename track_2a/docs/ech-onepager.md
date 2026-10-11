# Gegenprobe schema v0.1: one page for the eCH expert group

What a common schema for the business of Swiss parliaments needs, measured on OpenParlData (OPD, snapshot 6 Oct 2026,
89 parliaments with affairs in scope). Normative models: `src/gegenprobe/schema/schema_v0_1.py` (Pydantic); JSON Schema
with `$id` and version 0.1.0: `results/schema/*.schema.json`; field guide: `docs/schema.md`; mappings to Popolo, Akoma
Ntoso, Parla-CLARIN and OParl: `docs/mapping.md`.

**In one line:** the frame is feasible (17 fields, each a value with provenance or a typed null, dates kept apart by
role); the meaning is measured as a role split for 5 fields (answer date, procedural history, type, procedural state,
decision outcome) and assumed for the other 12, which need the test plan in §6. Meaning is tested for 0 of the 17: for
the government recommendation, OPD's label mapping is unambiguous (a string check), which is not a test of meaning.

## 1. Three classes (by meaning, from OPD's own vocabularies)

| class | fields and concepts | what it means for a standard |
|---|---|---|
| **shared** (12 of 17) | submission date, submitter, co-signatories, addressed body, government recommendation, decision date, dispatch date, Q/A pairing, related affairs, language, usable text, answer-link status | one definition by design, meaning untested across parliaments; for the government recommendation OPD's label mapping is unambiguous (0 of 183 raw labels map to different concepts; a string check over OPD's harmonised labels only); *where* the value lives (metadata, PDF, or not in OPD) is measured |
| **shared with a role split** (5 of 17) | answer date, procedural history, type, procedural state, decision outcome | one source label covers several roles that must be kept apart before parliaments can be compared; all 5 are measured |
| **body-specific** (3 concepts, not among the 17 fields) | oral answers in question time; executive business that answers no member's affair; councils that publish only meeting documents | needs its own construct, not a field: v0.1 types oral answers as a null reason and marks affairs rebuilt from minutes `virtual` with `derived_from` |

Of the 17 fields, 12 are shared by definition, their meaning untested (the recommendation's unambiguous OPD mapping
is a string check, not a semantic test). 5 are shared but need their roles kept apart, and all 5 are measured. The 3 body-specific concepts are not
fields; they need constructs of their own. Evidence:
`results/census/comparability.json`, classes and the `meaning_tested` flag in `data/schema/field_verdict_classes.json`. Separately, *where*
the value lives (`results/census/matrix.json`): 4 fields are in OPD's metadata almost everywhere, 13 partly; no field
lacks a written source in a fifth of the parliaments (5 would at a 10% threshold). That threshold measures coverage, not
meaning; the classes above are the finding. Not covered: tables, annexes and images inside answer documents are not
extracted, so the schema says nothing yet about their structure.

## 2. The answer date is three dates

"Answer date" in OPD can be the date the government **decided** (Regierungsratsbeschluss), the date the answer was
**dispatched**, or the date parliament **registered** it. In 7 of 54 bodies OPD's "answer" event is mostly the
submission date; on our held-out gold OPD's event equals the printed date for 37 of 44 checkable documents, and 5 of the
other 7 are 1–5 days apart (decision vs dispatch). OPD's answer date is verified as the decision date only in Bern and
Ticino. v0.1 therefore carries a `DateRole` on every date (`answer_decided`, `answer_dispatched`, `answered`,
`submitted`, `scheduled`, `debated`, … in `data/schema/date_roles.json`), and a date-trust tier per parliament in the
research dataset (`results/census/interventions.tsv.gz`, `results/census/date_trust.json`).

## 3. No bare nulls

Every extractable field is either a value with provenance (`basis`: extracted, normalised, metadata or inferred; the
deciding `route`; for document values page and character span) or a **typed null** that says why it is empty:
`not_in_corpus`, `unlinked` (the document exists in OPD but is not attached), `image_only`, `text_failed`, `oral`,
`present_unanchored`, `not_in_document`, `no_rules_for_body`, `not_applicable` (`data/schema/null_reasons.json`). A
model's document-level classification (e.g. a recommendation chosen from a closed set) names its document and the set
it chose from instead of a span, and is a review suggestion, never an unattended value.

The product record does not carry a null whose reason is not true. Our whole-affair assembly (frozen for the P3/P3b
evaluation) wrote `answering_body` as `present_unanchored` although that field was never extracted; schema v0.1 has no
reason for "not attempted", so the product post-processing (`gegenprobe.affair_post`) leaves the field out and says so
(`omitted`), and an interpellation's `decision` is `not_applicable`, not `not_in_corpus`. A v0.2 candidate: a
`not_extracted` reason, so that a record can be complete and honest at once.

## 4. Question by question: `QAItem`

Interpellations and written questions ask numbered questions, and the answer replies to each. `QAItem` pairs question
*n* with the answer to question *n*, both sides with a span or a typed null (an answer that replies to all at once is
`present_unanchored`). It is in v0.1 as an optional, additive structure, and our converter now fills it
(`src/gegenprobe/qa/`, `docs/qa.md`). The pre-registered test P5 (40 fresh affairs from 10 parliaments, DE/FR/IT) puts
rule-based pairing at precision 0.83 and recall 0.67: usable with a reviewer, not yet unattended (the *partial*
tier holds with document-level intervals, not when whole parliaments are resampled). It transfers where the
answer numbers or repeats the questions ("Zu Frage 2", "Réponse à la question 2") and fails where it does not (Valais
0/11). For a standard this argues for asking executives to number their answers; a v0.2 candidate is a `QAItem` field for
an answer that replies to several questions at once (the converter tracks it internally as `joint_with`).

## 5. Five gaps for v0.2 (cited evidence)

An inventory of what the answers state, over 12 bodies, left 45.9% of statements without a schema account; five gaps
recur across bodies and languages: **person roles; comparison amounts; dates and laws of other polities; dates of
other affairs; entry-into-force and deadline dates** (`docs/census.md`, `data/census/cited_evidence.json`; cited, not
recomputed by `make run`).

## 6. Proposal

Adopt date roles, typed nulls and the three classes as the frame; standardise the role split for the answer date first
(it decides every answer-time comparison); treat oral answers, executive-own business and minutes-only councils as
named constructs; take `QAItem` (measured, P5), the five gaps and a `not_extracted` null reason into v0.2. Test plan for
the 12 fields shared by definition: map each parliament's raw labels or printed forms to the shared concept (for the
government recommendation OPD's harmonised labels pass a string check, `results/census/comparability.json`, but the
printed forms are not yet mapped), and report the share that maps elsewhere. OPD vocabulary errors found on the way
(e.g. the harmonised type "Votaziun", Romansh for a vote, on 9,887 affairs) are listed in `results/census/vocab_bugs.tsv`. Gegenprobe (Hack Apertus,
Track 2A, team 444): https://gegenprobe.mi11ion.io.
