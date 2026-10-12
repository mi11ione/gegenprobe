# Mapping schema v0.1 to existing standards

This page maps our schema to existing standards. It says what maps cleanly, what maps lossily and what has no counterpart.
Where we do not know a standard's details, we say so instead of guessing. We claim **no compliance** with any of these
standards: v0.1 is a working schema, and these are crosswalks.

Legend: ✓ clean, ≈ lossy or needs a convention, ✗ no counterpart, ? unknown to us.

## 1. Popolo (people, organisations, motions, votes)

Popolo models people, organisations, memberships, motions and vote events. It is the natural home for the actor side, and
for the vote side we deliberately left out.

| Schema v0.1 | Popolo | Fit | Note |
|---|---|---|---|
| `Affair` | `Motion` | ≈ | A Popolo Motion is "a formal step to introduce a matter for consideration". It fits motions/postulates; interpellations and questions are not motions in the procedural sense. Use `classification` = our `type.harmonised`. |
| `Affair.ref.number` | `Motion.identifier` | ✓ | |
| `Affair.title` | `Motion.text` | ≈ | Popolo's `text` is the motion's text, not a title. |
| `Body` | `Organization` (classification legislature) | ✓ | The executive (`addressed_body`, `answering_body`) is a second `Organization`. |
| `Actor` role `submitter` / `first_signatory` | `Motion.creator` | ≈ | Popolo has one creator. Co-signatories need a custom relation or a `Membership`-like extension. |
| `Actor` roles `co_signatory`, `on_behalf_of_group`, `rapporteur`, `presiding_officer`, `secretary`, `committee_member` | `Membership` / `Post` | ≈ | These are posts held at the time, not properties of the motion. |
| `Actor` role `roll_call_voter` | `Vote` (in a `VoteEvent`) | ✓ | Out of scope in v0.1. |
| `decision` | `Motion.result` / `VoteEvent.result` | ≈ | Our 13 outcomes are richer (written off, converted to postulate). |
| `dates[role=submitted]` | `Motion.date` | ✓ | |
| `government_recommendation`, `qa[]`, typed nulls, provenance spans | — | ✗ | Popolo has `sources` (URLs), not span provenance. |

## 2. Akoma Ntoso (OASIS LegalDocML)

AKN is the richest fit for documents and their lifecycle. Fedlex publishes federal acts in AKN. AKN is built around
legislative drafting and debate records, so an affair becomes a `doc` (generic document) with metadata.

| Schema v0.1 | Akoma Ntoso | Fit | Note |
|---|---|---|---|
| `Affair` | `<doc name="interpellation">` (or motion, postulate, …) | ≈ | AKN has no "affair" type; `doc@name` carries it. |
| `Document` | FRBR `Work` / `Expression` (language) / `Manifestation` (the PDF) | ✓ | `sha256` belongs on the Manifestation, `language` on the Expression. |
| `Affair.ref` | `FRBRWork/FRBRthis`, `FRBRuri`, `FRBRnumber` | ✓ | |
| `dates[]` | `<lifecycle>/<eventRef date=… source=… type=…>` | ✓ | Our date roles become `eventRef@type` or `TLCEvent` references. |
| procedural steps, `decision` | `<workflow>/<step date actor role outcome>` | ✓ | `outcome` refers to a `TLCConcept`. |
| `Actor` | `TLCPerson`, `TLCOrganization` + `TLCRole` | ✓ | Our actor roles become `TLCRole` entries. |
| `qa[]` | `<debate>` with `<questions>` / `<question>` / `<answer>` | ≈ | That models oral question time in a debate record. Written answers decided by the executive are separate documents; we link them as two `doc`s. |
| provenance spans (page, char offsets) | — | ✗ | AKN marks up the text itself instead of pointing into an extraction; a span becomes a `<ref>` or `<span eId>` only if the text is converted to AKN. |
| typed nulls | — | ✗ | No equivalent. Absence cannot be typed. |

## 3. Parla-CLARIN / TEI (ParlaMint)

These are for **speeches and transcripts**: `<u>` utterances with speakers, notes and session structure. They are not for
affairs as objects.

| Schema v0.1 | Parla-CLARIN | Fit |
|---|---|---|
| debate transcripts, speeches | `<u who=…>` in a session `<TEI>` | out of scope in v0.1 |
| `Actor` (person) | `<person>` in `listPerson` | ✓ if transcripts are added |
| `Affair` | `<note type="…">` or an agenda item reference | ≈ |

OPD has a `speeches` export. Linking speeches to affairs would be a Parla-CLARIN job layered on top of this schema.

## 4. Docling (page representation)

Docling's `DoclingDocument` items (texts, tables, pictures) carry `prov` entries with `page_no`, a bounding box and a
`charspan`.

| Schema v0.1 | Docling | Fit | Note |
|---|---|---|---|
| `Valued.page` | `prov.page_no` | ✓ | Both are 1-based. |
| `Valued.char_start` / `char_end` | `prov.charspan` | ≈ | Our offsets index into the *page text of our extractor* (pdftotext / tesseract), recorded in `Document.extractor`. Docling's charspan is relative to its own text item. Converting needs a text alignment, not just a re-index. |
| — | `prov.bbox` | sidecar | The schema carries no box (v0.2 forbids extra fields); `results/schema/v0_2/span_bboxes.jsonl` gives each located value its box on the PDF page (PDF points, origin top left, from `pdftotext -bbox`), keyed by record, value path, document, page and span: 1,573 of the converter's 1,580 spans (the 7 others are federal values in OPD text records). Join on path + doc + page + char_start + char_end for the workbench's side-by-side view. |
| `DocumentPart(kind=table/image)` | `TableItem` / `PictureItem` | ✓ | Same idea: a referenced part, by page. |
| `Affair` semantics | — | ✗ | Docling is deliberately domain-agnostic. This schema is the layer above it. |

## 5. OParl (German council information systems)

OParl is not in the challenge text, but it is the closest existing standard for municipal parliaments. OPD's `bodies`
export already has an `flag_image_oparl_url` column.

| Schema v0.1 | OParl 1.x | Fit |
|---|---|---|
| `Affair` | `Paper` (Drucksache) | ✓ |
| `Affair.type.source_label` | `Paper.paperType` | ✓ |
| `Document` | `File` (`mainFile`, `auxiliaryFile`) | ✓ |
| `dates[]`, procedural steps | `Consultation` (paper ↔ meeting / agenda item, `role`, `authoritative`) | ≈ |
| `RelatedAffair` | `relatedPaper`, `superordinatedPaper`, `subordinatedPaper` | ✓ |
| `Actor` submitter | `originatorPerson`, `originatorOrganization` | ✓ |
| provenance, typed nulls, `government_recommendation` | — | ✗ |

## 6. eCH (expert group on political affairs)

**What we know.** eCH runs an expert group on political affairs, which Christian Gutknecht (OpenParlData) co-chairs. A
data standard for political affairs is being drafted there.

**What we do not know.** We have not seen the draft. We do not know its element names, its vocabularies or its status. The
mapping column is therefore left open on purpose:

| Schema v0.1 concept | eCH draft element |
|---|---|
| affair type vocabulary (20 keys) | ? |
| date roles (16) | ? |
| actor roles (15) | ? |
| procedural states (12), decision outcomes (13), government recommendation (7) | ? |
| answer link status, typed nulls, span provenance | ? (probably out of the draft's scope) |

We would offer the expert group two things as input: the typed-null vocabulary and the "metadata vs normalised vs
inferred" basis. Both are needed to run extraction unattended at OPD scale, whatever element names the standard picks.

## 7. Wikidata

OPD's harmonised affair types carry Wikidata ids (motion Q1949668, postulate Q2106323, interpellation Q1505023, written
question Q2052854, question time Q1286157, popular initiative Q335918, parliamentary initiative Q2052859, petition
Q697279, consultation Q1591788). `data/schema/affair_types.json` keeps the OPD ids, so these links are one join away.

## Summary

| Area | Best existing home | Gap this schema fills |
|---|---|---|
| people, organisations, votes | Popolo | co-signatories and executive roles per affair |
| documents, lifecycle, workflow | Akoma Ntoso | span provenance into extracted text; typed absence |
| speeches | Parla-CLARIN | (not covered) |
| page layout | Docling | affair semantics on top of pages |
| municipal paper/consultation model | OParl | Swiss executive answers (RRB), recommendations |
| Swiss political-affairs data | eCH draft (unknown to us) | typed nulls, extracted-vs-inferred basis |
