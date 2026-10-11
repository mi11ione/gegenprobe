# Whole-affair extraction (P3)

`src/gegenprobe/affair/` turns an affair's documents (the member's text and the executive's answer) plus OPD metadata into a
validated schema v0.1 `Affair`, field by field, with the same rule as the answer-date converter: metadata first, then
deterministic rules on the documents, then Apertus only as a closed-set pointer with null, and only as a review suggestion.

| field | metadata (route metadata, `source`) | rules on the documents (route rule, page + span) | Apertus pointer (closed set + null) |
|---|---|---|---|
| number | OPD affair number | the own number printed in either document | — |
| affair type | OPD harmonised type + the body's label | first type word in the question head (DE/FR/IT lexicon) | interpellation / motion / postulate / question / resolution |
| submitter | first OPD contributor with role author | a known office holder of the body printed after an author cue | office holders of the body (OPD contributors) whose surname is printed in the question |
| co-signatories | further OPD authors | — | — |
| addressed body | — | addressee phrase ("an den Regierungsrat", "au Conseil d'État", …) | executive / parliament / committee / administration |
| submission date | OPD "Eingereicht" event (BE begin_date 2024-10-28 is a load timestamp and is skipped) | a date within 80 characters after a submission cue | dates printed in the question |
| answer date + decision no. | OPD answer event (used only where the answer prints it) | the frozen P1 cascade on the answer | the frozen P1 pointer (θ +10.40) |
| recommendation | OPD "Antrag:" events | the frozen P1 rules | the frozen P1 pointer |
| procedural state, decision | latest harmonised OPD event | — | — |
| related affairs | — | other OPD-known affair numbers printed | — |
| answer-link status | census (`gegenprobe.census.funnel`) | — | — |

Commands: `python -m eval.gold3.run_p3 --backend none|gateway:…|gguf|fake` writes `results/eval3/p3__<build>.json` with each
arm's values, the pointer suggestions (with model build, θ, margin, candidate count, prompt id) and the validated `Affair`
instances. The evaluation design is `eval/prereg3/PREREG3_draft.md`; the annotation guide `eval/gold3/GUIDE.md`.
θ for the new pointer fields is 0 (declared; no dev labels exist for them).

## One affair from OPD: `python -m gegenprobe affair`

```bash
python -m gegenprobe affair --opd-affair 39369 --schema v0.2 [--mode rules_only|review] [--out FILE]
```

This command turns one OPD affair id into one validated schema v0.2 record (`src/gegenprobe/affair_cli.py`). It reads
OPD's rows for the affair: the affair, its events, its contributors and the rows of its documents. The member's text
(question) and the answer are picked by the P3 pairing rule (`eval.gold3.sample.pair_type`). Both are fetched through
`pdftext.fetch_pdf`, which checks robots.txt (RFC 9309, fail-closed), caps the size and falls back to OPD's own copy
where the original's path is disallowed. The record then goes through the same functions as the committed P3 and P3b
records: `affair.build.run_affair`, `affair_post.finalize`, `schema.v0_2_all.carry_v0_1` and `with_roles`. The v0.2
Pydantic model validates it.

- **Output.** One JSON object: `record` (the v0.2 record, typed nulls included), `needs_review`, `review` (the
  `affair_post` reasons), `suggestions` (review mode only, never inside a field), `changes` and `sources` (export
  snapshot, documents with sha256, answer-link status). `--record-only` prints the record alone. Repeating
  `--opd-affair` gives one JSON line per affair, from one pass over the exports.
- **Where OPD's rows come from.** `api.openparldata.ch/v1/` is disallowed by OPD's robots.txt. The rows therefore come
  from the nightly exports: `affairs`, `events`, `contributors` and `docs/docs_<body>`, streamed through `gegenprobe.net`.
  With `GP_EXPORTS_DIR` they are read from disk. `--source local` reads the copies in `GP_OPD_RAW` and `GP_DOCS_META`
  instead. `--rows FILE` reads a slice saved earlier with `--save-rows FILE`. Streaming the three single exports and
  `docs_BE` (0.47 GB) took 66 s for three affairs on 11 Oct 2026.
- **Failures are typed, exit 2.** `affair_not_found`, `no_documents`, `document_not_in_affair`, `exports_*` (the exports
  could not be read), the document kinds of `convert` (`robots_disallowed`, `robots_unreachable`, `http_error`,
  `timeout`, `not_a_pdf`, `too_large`, `ocr_failed`, ...) and `invalid_record`. `--question-doc` / `--answer-doc` name
  the documents when the pairing rule picks none or another one. Review mode exits 3 on a build mismatch, as `convert`
  does.
- **Two additions to the committed records' pipeline.** (1) The frozen assembly matches OPD's harmonised English type
  name against the vocabulary's English labels, so OPD's "Question" comes out `unknown`. The command takes the type from
  OPD's name by the mapping the P5 records use (`v0_2_all.OPD_TYPE_NAMES`), before `affair_post`. A question's
  `decision` then becomes `not_applicable`, and the change is listed in `changes`. (2) Each document carries the
  fetched file's `sha256` and OPD's text status, as in the P5 records. The record also carries `body.name` and
  `type.opd_harmonised_id` from OPD.
- **Answer-link status** comes from this affair's own rows, by the census definitions applied to one affair:
  `attached` (OPD links an answer document with usable text), `image_only`, then `absent` / `oral` / `not_applicable`
  from the events.
- **Document parts.** `detect_parts` in `affair_cli.py` is the one adapter to the rule-based detector
  `gegenprobe.convert.parts` (`detect_pdf` + `schema_parts`). A document where the detector found nothing gets the
  typed reason `none_printed`. Without the detector, `parts` stays empty with `not_extracted`.
- **Scope.** The command serves affairs whose member's text and answer are PDF documents in OPD's docs export: the
  cantonal and communal parliaments. Federal affairs keep their texts in OPD's `texts` export, which the command does
  not read (`no_documents`).
- **Checked.** Seven P3b affairs (LU, VS, GE, BL, GR, Lausanne, Lugano), run from the exports and compared with
  `results/schema/v0_2/p3b_records.jsonl`, have the same documents, language of each text and answer date. Every
  comparable field is equal except the type correction above. `make run` step: `gegenprobe.affair_cli.step` runs
  the command on the affairs of the three committed samples (Bern, Vernier, Lugano;
  `results/schema/v0_2/samples/`). It reads OPD's rows from the committed slice `data/affair_cli/opd_rows_samples.json`
  (exports of 11 Oct 2026; `GP_AFFAIR_LIVE_EXPORTS=1` reads the live exports) and fetches the documents. It then
  compares each record with its sample. It is skipped offline.

**Product records (`gegenprobe.affair_post`, round 5).** The scored results above are the frozen assembly's output and
stay unchanged. What OPD would load runs through an unlocked post-processing step (`src/gegenprobe/affair_post.py`;
`affair/` itself is hash-locked by LOCK3/LOCK5):

- `qa[].answering_body`: the frozen assembly writes a typed null `present_unanchored` with evidence "not extracted in
  P3", which claims that candidates were present but none anchored, when in fact nobody looked. Schema v0.1 has no null
  reason for "not attempted" (`data/schema/null_reasons.json`) and the field is required, so the product record leaves
  the field out and lists it under `omitted` with that note; `affair_post.validate` checks everything else against
  v0.1. Schema v0.2 adds the reason, `not_extracted`: carried to v0.2 with it, all 65 P3 and P3b product records
  validate as a whole (`python -m gegenprobe.schema.v0_2_all` → `results/schema/v0_2/p3_records.jsonl`,
  `p3b_records.jsonl`, `validation_all.json`).
- `decision`: for an interpellation, a written question or question time, on which parliament takes no decision, a
  metadata null `not_in_corpus` becomes `not_applicable` (route metadata, the type as evidence). A decision OPD records
  is kept.
- `qa[].answer_date`: when a rule read a date that equals the affair's submission date while OPD's answer event has
  another date, OPD's date is kept (basis/route metadata, with its OPD record), the rule's value goes to `review` with
  the reason, and the record needs review. This is the P3b Luzern case: the rule read the motion date printed on the
  answer ("Antrag … vom <submission date>").

`python -m gegenprobe.affair_post <results file> --out records.jsonl` writes one product row per affair (`affair`,
`needs_review`, `review`, `omitted`, `changes`). Post hoc on the committed records (`python -m gegenprobe.affair_post
--measure` → `results/eval5/affair_post_check.json`): the answer-date guard fires on 3 of the 36 P3b affairs, all three
in Luzern, and OPD's kept date equals the gold label in all three; it fires on none of the 29 P3 affairs.
`answering_body` is left out in all 65 records, and `decision` becomes `not_applicable` in 12 P3 and 9 P3b records. The
evidence site's sample record is the post-processed one, carried to schema v0.2.

**Metadata vs document values.** In every `Affair` instance, a value taken from OPD metadata has `route: metadata`,
`basis: metadata`, a `source` naming the OPD record (e.g. `opd:events/…`) and no span. A value read from a document
has `doc`, `page`, `char_start`, `char_end` and `quote`. The schema validators enforce this (`basis=metadata` ⇔
`route=metadata`, `source` required; span routes require a span). `tests/test_overlay.py` checks it on the committed P3
output: 134 metadata values, all without a span, and 35 document values, all with one. The affair type
(`AffairTypeV`: harmonised type + source label) is a plain metadata object without `Valued` provenance.
