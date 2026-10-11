# Converter: rules first, Apertus only as a closed-set pointer

**What it does.** For each parliamentary document it extracts the executive's answer/decision date (plus decision number,
government recommendation and related-affair links). Every value carries `{page, char_start, char_end, quote, route}`, or the
value is a typed null. Apertus never writes a value. It can only **point** at a value that is already in the document (or in
OPD), or answer null.

```
document (PDF → pdftotext pages; image-only → tesseract deu+fra+ita)
  │
  ├─ (i)  OPD metadata   OPD answer-event date, used only if the same date is printed at an answer anchor in the document
  ├─ (ii) frozen rules   DE/FR/IT anchor lexicons (src/gegenprobe/convert/rules.py) → value | typed null | abstain
  └─ (iii) pointer       residue only: forced choice over {dates in the document} ∪ {null}; null iff margin > θ(build, prompt)
```

## Modes (`convert/modes.py`) — decided by the pre-registered held-out test

| mode | what writes the field | model | held-out (answer date, 154 documents) |
|---|---|---|---|
| `rules_only` (**default**) | OPD metadata + frozen rules; the residue stays a typed null (`present_unanchored` / `not_in_document`) | none | 135/154 exact, values on 2/90 answerless documents, 0 fabricated |
| `review` | as `rules_only`; the pointer's value on the residue is attached as `suggestion` {value, page, span, quote, margin, θ, build} with `needs_review: true`, never written into the field | Apertus pointer | accepting every suggestion = the cascade arm: 139/154, false nulls 15 → 4, values on answerless 2 → 7 |

Branch B of the pre-registration (H2, `eval/prereg/PREREG.md`): Apertus did not measurably add null-safety over the
rules, so it does not write values unattended. `cascade.py` (pre-registration-locked) is unchanged; `modes.py` wraps it.

## Candidate lattice (`convert/lattice.py`)
- **Dates.** Numeric (`28.08.2024`, `28/08/2024`, `2024-08-28`) and day + month name in DE/FR/IT, full or abbreviated
  (`1er mars`, `1° ottobre`, `3 déc.`, `15 sett.`, `15juillet`). Invalid calendar dates are dropped, as are years outside
  1848–2100. Each candidate keeps its page, character span, ±12-token context and line.
- **Affair numbers.** Generic shapes, kept only if the number exists in OPD for that body (`data/convert/affair_numbers.json.gz`,
  built from the affairs export).
- **Enums.** Government recommendation: `accept | reject | convert` (to postulate) per language.

## Frozen rules (`convert/rules.py`)
Rule ids are recorded on every value.

| role | anchors (examples) |
|---|---|
| decision | `RRB-Nr.: 1057/2025 vom 15. Oktober 2025` (BE inline and split header layouts), `Datum RR-Sitzung`, `Regierungsratsbeschluss vom` (BS), `Auszug aus dem Protokoll des Regierungsrates … Sitzung vom` (ZH), `N° ACE … du` (BE-fr), `Extrait du procès-verbal du Conseil-exécutif … le`, `Ainsi adopté en séance de Municipalité … le` (Lausanne), `RG n. 3382 del 3 luglio 2024` (TI), `ris. mun.: 01/02/2012` (Lugano), `Antrag Regierungsrat: 15.03.2021 / Erheblicherklärung` (LU), `Risposta del … all'interpellanza` (TI) |
| dispatch | Place-date line (`Winterthur, 30. November 2016`), `Date de dépôt` (GE), `zugestellt am`, TI letterhead date, a date line right above the answer heading, a signature date at the end, or a place-date directly above an executive signature block. All of these only count in a document that carries an executive answer heading. |
| null | BE empty answer template (`RRB-Nr.: … vom` with no date) → `not_in_document`; VS oral stub → `oral`; empty text → `text_failed` / `image_only` |
| never | Footer, edit and print dates (`Letzte Bearbeitung`, `Dernière modification`, `Document généré le` …) and submission dates (`Eingereicht am`, `déposée le` …) |

Some names are ambiguous across bodies. "Conseil communal" and "Conseil municipal" are the legislature in Lausanne and the Ville de
Genève but the executive in Valais communes, so they are not decision anchors.

**Development.** The rules were developed on the dev pool only (`data/gold/dev_ids.json`):
- the 30 spike items (round 7/8);
- 97 dev documents drawn by the gold sampler (seed 20261009), labelled by a Claude Code agent.

On that pool the rules reach 126/127 strict and 0/72 inventions on null documents (`results/convert/rules_dev.json`). These are
in-sample numbers: the same agent wrote the rules and the dev labels. Only the held-out set measures the rules.

## Pointer (`convert/pointer.py`)
- **Protocol.** This is S-SHAPE arm (a) from round 8:
  - User message: the template from `src/prompts/<lang>/answer_date.txt` with the document.
  - Assistant prefix: `{"antwort_datum":` (`date_reponse` in FR, `data_risposta` in IT).
  - Continuations: ` null` plus one ` "DD.MM.YYYY"` per distinct date in the document.
  - Margin = lp(null) − logsumexp(lp(dates)). The answer is null iff margin > θ, otherwise the argmax date.
- **Provenance.** The chosen date is mapped back to its span. If the date occurs more than once, the occurrence nearest an
  answer anchor is used, else the first one. The rule used is recorded.
- **Truncation.** Documents are cut at 12,000 characters. This stands in for the spikes' 3,000 Apertus tokens (≈ 4 chars/token)
  and is recorded on every result.
- **Prompt identity.** `answer_date_spike8a.txt` is byte-identical to the round-8 arm (a) prompt, kept for replication. The
  default prompts generalise it to any body and level in DE/FR/IT. θ is keyed by `prompt_id`
  (`<lang>/<file>@sha256[:12]`) and by build.
- **One user message only.** Public AI answers the 70B name with Qwen-SEA-LION when given a system message or prefill.
  Forced choice is therefore sent only to names that accept prefill, and `llm.py` checks the served `model` field on every
  call.

## θ per build (`convert/calibrate.py`)
θ is the midpoint of the widest accuracy-optimal interval, with leave-one-out validation. It is fitted on dev labels only.

`eval/replay_spikes.py` reruns the spike margins through this code and reproduces `spikes/inversions` F2:
- final g64 chat_plain: AUROC 1.00, LOO 20/20, θ −32.3;
- final DWQ chat_null: θ −14.8;
- RLVR→final transfer: accuracy 0.25.

It also reproduces round-8 SHAPE (a): θ +4.9, BE LOO 20/20, ZH+BS 10/10 kept with the correct date, BE answered dates
correct 2/5.

## Naive contrast (`eval/naive_baseline.py`)
This is the free-generation JSON strawman, with plain and null-allowed prompts. Two kinds of prompt are kept:
- `naive_*_spike7.txt`: the S-NULL prompts verbatim;
- `naive_*.txt`: generic DE/FR/IT versions.

It adds the naive receipt check (verbatim quote containing the date). Replaying the cached generations reproduces round 7:
- plain prompt: invents 15/15 (7 fabricated, 8 misattributed);
- null-allowed prompt: invents 14/15, and the receipt check passes 10/15 of those wrong dates.

On the Public AI endpoint, which serves the 70B weights, the plain prompt invents 14/15 and the null-allowed prompt 0/15.

## Gold set (`eval/gold/`, `data/gold/README.md`)
- **Cells.** DE/FR/IT × canton/commune, plus TI OCR scans. Per cell: 10 intervention texts, 8 answers and 4 reports/minutes.
- **Length matching.** Both classes are 4,000–8,000 OPD characters.
- **Disjointness.** The held-out split shares no document and no affair with dev or the spikes.
- **Label sheets.** They show the date lattice, never the rules' predictions.

## Command line (`python -m gegenprobe convert`, `convert/batch.py`, `convert/output.py`)
One PDF (path or URL) or a batch file (`--batch inputs.tsv --out results.jsonl`, resumable) gives one row per document:
`status`, `input` (with `opd_doc_id`, `body`, `affair_number` passed through), `doc_role` (answer / question / other, by
rule, with its evidence), `fields` (a flat reviewer view: value or typed null, `route`, `rule_id`, `decision_number`, page +
char span, `quote` = the exact span text, `context` = the anchor phrase through the end of the date's line, ≤ 200
characters), `needs_review`, `review_suggestion` (review mode only), and `record` (the validated schema v0.1
`DocExtraction`; its values also carry `rule` and, for dates, `decision_number`). A document that cannot be fetched or
read gives a typed failure row instead of a traceback: `robots_disallowed`, `robots_unreachable`, `http_error`, `timeout`,
`network_error`, `not_a_pdf`, `sha_mismatch`, `file_not_found`, `text_failed`, `too_large`, `text_timeout`. Review mode refuses to run without a θ fitted for the exact
build and lists the fitted builds; while it runs, `convert/build_guard.py` compares every live response's
`system_fingerprint` with the fingerprints the θ file records (GGUF: the weights' sha256) and stops with exit 3 on another
build (`--allow-build-mismatch` continues and marks each suggestion `build_mismatch`; refit procedure in
`docs/runbook.md`). User guide, field glossary and null reasons in plain words: `docs/convert-your-own.md`.

**Review aids (round 2).** Every answer-date field carries `candidates` (the closed set: every printed date with page,
span and context, the chosen one marked, and Apertus' probability shares in review mode); rule values carry
`rule_precision` (`results/convert/rule_precision.json`, per rule on the P1 + P2 held-out rows, with its Wilson 95%
interval and a small-sample flag below n = 10); review suggestions carry a
`band` (strong: margin ≤ −5; weak: −5 < margin ≤ θ), measured post-hoc on P1 + P2 (`results/convert/band_precision.json`);
recommendations carry `multiple_recommendations`; `--opd-text` adds `opd_text_span`, offsets into OPD's stored text
(`convert/opdtext.py`). Batch: exit code 2 on any failure row (`--allow-failures` to override), `--queue` for a review
queue sorted strongest first. Rule coverage for routing: `data/convert/rules_coverage.json`. All computed by
`python -m gegenprobe.convert.precision` from committed result rows; no new labels, no model call.

**Overlay after the frozen rules (round 3, `convert/overlay.py`).** The overlay is applied in `batch.convert_pages`
after the cascade has decided. The locked modules are not touched, and the evaluation scripts call those modules
directly, so no registered number changes. It does five things:

- **Rule coverage per body.** A `--body` outside `rules_coverage.json` prints a warning on stderr. Open fields become
  `null_reason: no_rules_for_body` (a new schema null reason, routes rule / ocr+rule) instead of `present_unanchored`.
  Values found by a frozen rule are kept but flagged, and the row is `needs_review`.
- **Recommendation qualifiers.** A partial qualifier after a frozen accept or reject match (`partiellement`, `en partie`,
  `teilweise (erheblich)`, `partiell`, `parzialmente`, `in parte`) gives `partial`, with rule
  `rec_<label>+qualifier_partial` and the quote extended to the qualifier. Conditional or modified-wording qualifiers
  (`im Sinne der Erwägungen`, `mit geändertem Wortlaut`, `Nichteintreten`, `sous réserve`, …) keep the value and flag it.
  Per-point recommendations are left to `multiple_recommendations`.
- **Heading proximity.** When the rules return `heading_without_date`, a date printed within 80 characters after an
  executive answer heading is moved to `candidates[0]` (`suggested_by_heading_proximity`) and the row is flagged. The
  date may only be separated from the heading by the rest of the heading line and at most one line break, and the
  heading must not name the instrument. The field is not filled.
- **User anchors** (`--anchors FILE`, JSON, per body). These are tried only after a null from the frozen rules. Values get
  `route: user_anchor` (a new schema route that requires a span) and `rule: user_anchor:<id>`. Example:
  `docs/examples/anchors_SG.json`.
- **`--explain`.** It replays the frozen rule order read-only and says per rule why it did not decide; it also prints the
  cache path. On the 3,398 cached documents the replayed `fired` step equals the frozen result 3,398/3,398.

robots.txt follows RFC 9309 (`net.py`): a 4xx means "no restrictions". A 5xx, a 429 or a network error fails closed,
as the typed failure `robots_unreachable`. A real Disallow is `robots_disallowed`.

## Commands
```
python -m gegenprobe convert <pdf|url> [--mode review --backend gguf]   # one document
python -m gegenprobe convert --batch inputs.tsv --out results.jsonl       # many, resumable
python -m gegenprobe convert answer.pdf --body SG --anchors docs/examples/anchors_SG.json --explain
make convert                     # spike replay, dev rules, tests (no model)
make gold-heldout gold-candidates
make theta BACKEND=gateway:swiss-ai/apertus-v1.5-8b:2a-theta:1.0      # model run: fit θ on dev (the -8b name serves the 70B)
make arms  BACKEND=gateway:swiss-ai/apertus-v1.5-8b:2a-arms:2.0 SPLIT=heldout
make arms  BACKEND=gguf SPLIT=heldout                                  # real 8B, Q4_K_M, CPU (CI runner)
```
