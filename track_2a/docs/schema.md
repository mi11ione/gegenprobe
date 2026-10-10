# Affair schema v0.1.0

The schema is a middle layer for Swiss parliamentary affairs (motions, postulates, interpellations, written questions,
initiatives, government business). It sits between a generic page representation (Docling, plain text) and heavyweight
legislative XML (Akoma Ntoso). It plays the role JATS plays for journal articles: it records affair semantics and keeps
every value tied to the place in the source it came from.

- Code: `src/gegenprobe/schema/schema_v0_1.py` (Pydantic v2; this is the single source of truth)
- JSON Schema for OPD's Pydantic-based extraction workbench: `results/schema/affair.schema.json`
- Vocabularies with DE/FR/IT/EN labels, OPD harmonised ids and corpus counts: `data/schema/*.json`
  (`python -m gegenprobe.schema.vocab`)
- Samples: `results/schema/samples/*.json` (`python -m gegenprobe.schema.samples`)
- Validator: `src/gegenprobe/validate/` (see the end of this page)

## 1. Three design rules

1. **No bare nulls.** Every field that could be read from a source holds one of two things. It is either a `Valued`
   (`kind: "value"`) that carries its provenance, or a `TypedNull` (`kind: "null"`) that says why there is no value. A
   converter that "doesn't know" has to say which kind of not-knowing it is.
2. **Extracted vs inferred is explicit** (challenge ethics clause). Every value has a `basis`:

   | basis | meaning | span required |
   |---|---|---|
   | `extracted` | the value string occurs verbatim at the span | yes |
   | `normalised` | the span is verbatim, the value is its normal form ("28. August 2024" → `2024-08-28`) | yes |
   | `metadata` | taken from a structured OPD or canton record, named in `source` (e.g. `opd:events/84384`) | no |
   | `inferred` | a classification derived from a cited span (e.g. a government recommendation enum) | yes |

3. **The deciding stage is recorded.** `route ∈ {metadata, rule, apertus, ocr+rule, ocr+apertus}`. Values and abstentions
   decided by Apertus must carry `model_build`, `theta` and `margin`, i.e. the null margin of the closed-set forced choice
   in nats. A reviewer can therefore see how close the call was and for which build the threshold θ was fitted. The
   threshold does not transfer across builds (spikes/inversions F2).

### Provenance (on every `Valued`)

`{value, role, basis, route, doc, page, char_start, char_end, quote, source, model_build, theta, margin, candidates}`

- `doc` names an entry in `documents`.
- `page` is 1-based.
- `char_start` and `char_end` index into `pages[page-1]` of that document's cached text, whose `extractor` is recorded on
  the document (e.g. `pdftotext-26.02.0`, `tesseract-5.5.3-deu+fra+ita`).
- `quote` is the verbatim text at the span, at most 400 characters.
- Full document texts are never stored in an instance. Only ids, URLs, hashes and short quotes are.

### Typed nulls

| null_reason | meaning | routes allowed |
|---|---|---|
| `not_in_corpus` | no document or record holding the value exists in OPD or at the source we checked | any |
| `unlinked` | the document exists in OPD but is not attached to the affair (`related_doc` required) | metadata |
| `text_failed` | the document is attached but its text is null, failed or a placeholder | metadata, rule |
| `image_only` | the PDF is a scan without a text layer | metadata, rule |
| `oral` | the question was answered orally, so no written value exists | metadata, rule, ocr+rule |
| `present_unanchored` | candidate values are present, but none is anchored to the field's role | rule, apertus, ocr+* |
| `not_applicable` | the field does not apply to this affair type | metadata, rule |
| `not_in_document` | this document was read and does not contain the value (document-level; other documents of the affair may) | rule, apertus, ocr+* |

A model abstention (`route: apertus`) must have `margin > theta`.

## 2. Objects

| Object | Fields | Notes |
|---|---|---|
| `Affair` | `schema_version`, `ref`, `body`, `type`, `title{lang}`, `languages`, `actors[]`, `dates[]`, `procedural_state`, `decision`, `government_recommendation`, `qa[]`, `answer_link_status`, `related_affairs[]`, `documents[]`, `extraction` | `extra="forbid"` everywhere; doc references are checked |
| `AffairRef` | `body_key`, `number`, `opd_id`, `virtual`, `derived_from` | the body's own number is kept verbatim; date-like numbers ("V 2021-06-28") are OPD's virtual-affair numbers ('V' + start date); see *Virtual affairs* below |
| `Body` | `key` (OPD body_key), `name`, `level` (federal/cantonal/communal), `languages` | multi-valued: bilingual bodies (FR, VS, BE …) list every language. OPD stores one value per body because its crawler fetches German first, then French (OPD response to the census findings) |
| `AffairTypeV` | `harmonised` (20 keys), `opd_harmonised_id`, `source_label`, `urgent` | the body's own label is kept next to the harmonised key |
| `Actor` | `role` (15 keys), `kind`, `name` (a field), `opd_person_id`, `party`, `group` | names are field values with provenance; no contact data |
| `DatedEvent` | `role` (16 date roles), `date` (a field), `label` | one event per role and source; disagreements stay visible |
| `QAPair` | `question_doc`, `answer_doc`, `answer_text_ref`, `link_status`, `answering_body`, `answer_date`, `answer_identifier` | the answer may be a document or a text record (CHE Curia Vista answers live in OPD's `texts` export) |
| `RelatedAffair` | `relation`, `ref`, `evidence` (a field) | evidence is the span that names the other affair |
| `Document` | `doc_id`, `source`, `url`, `sha256`, `role`, `language`, `n_pages`, `extractor`, `image_only`, `opd_text_status`, `parts[]` | the sha256 is our own content hash; OPD's `hash` is an identifier (sha256 of body_key + parent_type + url; `results/census/hash_check.json`). `language` = `unspecified` when the source records none (OPD's empty field), `null` when we do not know |
| `DocumentPart` | `kind` (table, annex, image, signature, stamp, handwriting, header, footer, budget_table, toc), `page_from`, `page_to`, `label` | tables, annexes and images are referenced by page range, not re-extracted |
| `ExtractionRun` | `converter_version`, `schema_version`, `created`, `builds[]`, `notes` | |

### Date roles

`submitted`, `answer_decided` (e.g. the RRB date), `answer_dispatched`, `answered` (decided vs dispatched not
distinguishable), `scheduled`, `debated`, `referred_to_committee`, `decided`, `closed`, `withdrawn`, `published`,
`entry_into_force`, `deadline`, `referendum_deadline`, `popular_vote`, `other`.

OPD's harmonised "Beantwortet" event maps to `answered`, not to `answer_decided`, because OPD does not say which of the two
it is. In BE the event date equals the RRB decision date in 39/39 sampled affairs (`results/repair/be_verify40.json`). The converter may
therefore use it as `answer_decided` for BE only, and records that as a body-specific rule.

### Actor roles

The roles are `submitter`, `first_signatory`, `co_signatory`, `on_behalf_of_group`, `addressed_body`, `answering_body`,
`executive_signatory`, `presiding_officer`, `secretary`, `committee`, `committee_member`, `rapporteur`,
`referenced_member`, `roll_call_voter` and `other`.

The second half of this list exists because a rule-based reading of 94 documents from 12 bodies (`spikes/bilanz`) found
person roles that a submitter/co-signatory model cannot hold. Person mentions had the highest unbooked ("suspense") rate of
any atom type (`data/census/cited_evidence.json`, copied from the pre-registered Bilanz spike).

### Procedural state, decision, government recommendation

- **`procedural_state`** (12 values): `submitted`, `pending_answer`, `answered`, `scheduled`, `in_committee`, `debated`,
  `referred`, `decided`, `closed`, `withdrawn`, `lapsed`, `unknown`.
- **`decision`** (13 values): `adopted`, `rejected`, `referred`, `converted_to_postulate`, `partially_adopted`,
  `written_off`, `not_written_off`, `acknowledged`, `withdrawn`, `lapsed`, `returned`, `no_decision`, `pending`.
- **`government_recommendation`** (7 values): `accept`, `reject`, `convert`, `partial`, `accept_and_write_off`, `none`,
  `not_applicable`. It is `not_applicable` for interpellations, written questions and question time (validator rule N5).

### Answer link status

`attached | agenda | parentless | absent | image_only | oral | not_applicable`

These are the census's categories: where OPD actually keeps the government's answer. Each status has a different repair.

## 3. Grounding in OPD's harmonised vocabularies (snapshot 2026-10-06)

| | measured | file |
|---|---|---|
| affairs | 325,691 | `results/schema/vocab_summary.json` |
| share with a harmonised type | 82.9% | |
| affairs with a harmonised state | 278 | so the state has to come from events or documents |
| events | 915,238; harmonised 72.1% | |
| distinct harmonised event titles | 84; 81 mapped to schema concepts | `data/schema/opd_event_titles.json` |
| harmonised events covered by the mapping | 99.8% | the three unmapped titles are '-', '1' and 'Folgeschritt' |
| OPD harmonised labels we do not reuse (mistranslations) | 8 | `data/schema/opd_label_issues.json` |

Examples of the label issues: *Abgeschrieben* is rendered "Depreciated" in OPD's English labels, *Erheblich erklärt* is
rendered "Significantly declared", *Zurückgewiesen* is rendered "Rifiutato" in Italian, and the Romansh/English labels of
*Wahl* are "Iniziativa parlamentara" / "Votaziun". The schema keeps OPD's ids for joining and uses its own labels.

Each harmonised event title maps to some of `date_role`, `state`, `decision` and `recommendation`. For example,
`Überwiesen Postulat` maps to `decided` / `referred` / `converted_to_postulate`, and `Antrag: Ablehnen` maps to the
recommendation `reject`. *Antrag* events are proposals. The executive is usually, but not always, the actor, so
`events.actor_*` must be checked before a recommendation is attributed.

## 4. Deliberately out of scope in v0.1

- **Content of tables, budgets and annexes.** They are referenced by `DocumentPart` page ranges. The comparison amounts
  that Bilanz found (prior year, budget vs actual) are not modelled.
- **Speeches and debate transcripts.** These belong to Parla-CLARIN/TEI (see `mapping.md`).
- **Votes and roll calls.** `roll_call_voter` exists only as a role, so that a name in a vote list is not mistaken for a
  co-signatory. Vote counts belong to Popolo `VoteEvent`.
- **Dates and laws of other polities, and dates of other affairs.** Bilanz found both in the same documents. They may be
  cited (`RelatedAffair`, date role `other`), but the schema does not try to model foreign procedures.
- **Persons' contact data.** It is never stored. OPD's persons export contains it, and we do not read it.

## 5. Validator (`src/gegenprobe/validate`)

| Check | Function | What fails |
|---|---|---|
| schema | `validate(obj)` | unknown fields, bare `None` for a field, a span route without span/quote, a model route without build/θ/margin, an abstention with margin ≤ θ, `unlinked` without `related_doc`, a null reason from a route that cannot produce it, a dangling `doc` reference |
| span re-check | `recheck`, `recheck_affair` | page out of range, span out of range, quote ≠ text at the span, a date value with no date in the span normalising to it (DE/FR/IT: "28. August 2024", "28.08.2024", "28 août 2024", "28 agosto 2024", "1er", "1°"; two-digit years refused) |
| consistency | `check_affair` | N1 image-only null on a text document; N2 OCR route on a non-OCR document; N3 text route on an image-only document; N4 link status vs QA pairs; N5 a recommendation for an interpellation or question; N6 several (build, θ) pairs in one field family |
| self-deletion | `harness.self_deletion(converter, pages, field)` | after the anchor line (and every line holding the same value) is blanked, the converter still returns a value |
| footer distractor | `harness.distractor(converter, pages, field, lang)` | after a "Letzte Bearbeitung / Dernière modification / Ultima modifica" footer with an unseen date is added, the converter picks that date or changes its decision |
| report | `report.summarise`, `report.to_markdown` | per-field pass/fail/skipped counts |

The harnesses take any callable `converter(pages, field) -> Valued | TypedNull`, so the converter's cascade, the naive
free-generation baseline and the rules baseline can all be tested the same way.

**Known limitation.** `find_dates` does not split a date from a footnote marker glued to its year. Fedlex PDF text has
"10. März 20142" for "10. März 2014" with footnote 2, so such a date is not found when a whole page is scanned, although a
span that excludes the marker re-checks fine. Candidate builders that scan whole pages need a footnote-aware variant.


## Virtual affairs (v0.1 addition, 10 Oct 2026)

Many communes publish only per-meeting documents (minutes) and no affairs; OPD derives "virtual affairs" for some of them
and numbers them `V` + start date (e.g. Solothurn consultations, "V 2021-06-28"). Schema v0.1 represents this explicitly:
`AffairRef.virtual = true` and `AffairRef.derived_from` = the `doc_id` of the meeting document the affair was derived from
(validated: `derived_from` requires `virtual`, and must be one of the affair's documents). The census measures the frontier:
`results/census/virtual_affairs.json` lists the bodies whose documents hang on meetings rather than affairs.
