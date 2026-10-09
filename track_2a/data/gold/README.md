# Gold set (ids, URLs, hashes and labels only — never document texts)

| file | what |
|---|---|
| `dev_docs.jsonl` | dev documents (rule development, θ fitting): doc id, body, affair, URL, sha256, pages, chars, stratum |
| `dev_labels.jsonl` | dev labels: 97 sampler docs labelled by a Claude Code agent (`labeller: claude-agent`) + 30 spike items (labels from the spike files) |
| `dev_ids.json` | every document the rules or prompts were developed or inspected on (sampler dev, spikes, recovery audit, Bilanz) |
| `heldout_docs.jsonl` | held-out documents, drawn after the dev split with a separate seed (`eval/gold/SEEDS.md`); disjoint from `dev_ids.json` and from dev affairs |
| `heldout_labels.jsonl` | held-out labels — written only after `eval/prereg/LOCK` |
| `*_fetch_log.jsonl` | every fetch attempt, including rejected/replaced documents and shortfalls |

Texts are re-fetched from the URL and verified by sha256 (`gegenprobe.pdftext.fetch_pdf(url, expect_sha256=...)`); OCR'd
documents also carry the tesseract version and languages in `extractor`.

## Strata (vision §8)

Cells: `de_canton` (BE-de, ZH, BS, LU) · `de_commune` (Zürich city, Winterthur, St. Gallen city) · `fr_canton` (GE, BE-fr, JU, VS-fr)
· `fr_commune` (Lausanne, Collombey-Muraz, Ville de Genève) · `it_canton` (TI) · `it_commune` (Lugano, Mendrisio, Locarno) ·
`ocr_ti` (TI image-only scans, OCR deu+fra+ita). Per cell (held-out): 10 intervention texts (expected null class), 8 executive
answers/decisions, 4 reports or minutes pages; OCR cell 10 + 12. Non-OCR documents are length-matched by construction: OPD text
length 4,000–8,000 chars (≈ 1,000–2,000 tokens at 4 chars/token) for both classes. Substitutions are listed in `eval/gold/sample.py`
(`SUBSTITUTIONS`): Monthey's OPD documents are HTML pages, not PDFs (replaced by Lausanne and Ville de Genève); Mendrisio documents
are not linked to affairs in OPD; Zürich city and St. Gallen city were added/kept for the German communal cell.

## Labelling sheet (`eval.gold.candidates` writes `.work/gold/<split>_label_sheet.tsv`)

The annotator opens the PDF at `url` (the original is authoritative) with the candidate file `.work/gold/candidates/<split>/<doc_id>.json`
(every date in the document with its page and line; affair numbers known to OPD; lines that look like answer headings). The rules'
predictions are **not** shown, so labels are not anchored on the baseline.

| column | values |
|---|---|
| `answer_present` | `yes` (the executive's answer/decision is in this document) · `no` · `oral` (the document says the answer was oral) · `unclear` |
| `answer_date` | ISO date of the executive's answer/decision **as printed in this document**, else empty. A date that is not printed is never filled in from memory or metadata. |
| `answer_date_page`, `answer_date_quote` | page (1-based) and the line that carries the date |
| `role` | `decision` — the date the executive decided/adopted it (RRB-Nr. … vom, Sitzung vom, Datum RR-Sitzung, N° ACE … du, Ainsi adopté en séance … le, RG n. … del, ris. mun.); `dispatch` — the date on the answer letter (place-date line, Date de dépôt, signature date). Gold = the decision date if printed, else the dispatch date. |
| `answer_date_lenient` | other printed dates that are defensible answer dates for this document (e.g. the letter date next to the RRB date), `;`-separated |
| `decision_number` | the executive's decision number if printed (RRB-Nr., ACE, RG n., ris. mun.) |
| `recommendation` | `accept` · `reject` · `convert` (to postulate) · `none` (no recommendation printed) · `not_applicable` (interpellation, question) |
| `submitters_as_printed` | submitter(s) exactly as printed, `;`-separated |
| `labeller`, `notes` | who labelled; anything ambiguous |

Second annotation (vision correction 4): a Claude agent labels independently; Roman adjudicates every disagreement; Cohen's κ is
reported per field. Apertus never labels.
