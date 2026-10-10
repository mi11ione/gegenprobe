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

**Product records (`gegenprobe.affair_post`, round 5).** The scored results above are the frozen assembly's output and
stay unchanged. What OPD would load runs through an unlocked post-processing step (`src/gegenprobe/affair_post.py`;
`affair/` itself is hash-locked by LOCK3/LOCK5):

- `qa[].answering_body`: the frozen assembly writes a typed null `present_unanchored` with evidence "not extracted in
  P3", which claims that candidates were present but none anchored, when in fact nobody looked. Schema v0.1 has no null
  reason for "not attempted" (`data/schema/null_reasons.json`) and the field is required, so the product record leaves
  the field out and lists it under `omitted` with that note. Such a record is not schema-valid as a whole until the
  field is extracted or v0.2 adds a reason; `affair_post.validate` checks everything else.
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
evidence site's sample record is the post-processed one.

**Metadata vs document values.** In every `Affair` instance, a value taken from OPD metadata has `route: metadata`,
`basis: metadata`, a `source` naming the OPD record (e.g. `opd:events/…`) and no span. A value read from a document
has `doc`, `page`, `char_start`, `char_end` and `quote`. The schema validators enforce this (`basis=metadata` ⇔
`route=metadata`, `source` required; span routes require a span). `tests/test_overlay.py` checks it on the committed P3
output: 134 metadata values, all without a span, and 35 document values, all with one. The affair type
(`AffairTypeV`: harmonised type + source label) is a plain metadata object without `Valued` provenance.
