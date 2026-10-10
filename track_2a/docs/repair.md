# Repair: putting OpenParlData's missing government answers back

Model-free. Every number below is produced by `make repair` (cached inputs) or `make repair-network` (one-off fetches) and is
listed in `claims.d/repair.tsv`. Output files follow one layout for every route (`results/repair/repair_<BODY>.tsv` and `.json`,
gzipped for CHE):

| column | meaning |
|---|---|
| `body`, `affair_id`, `affair_number` | the OPD affair the row repairs (`affair_id` = OPD id) |
| `action` | `relink` · `agenda_join` · `fetch` · `retype_oral` · `ocr` · `placeholder_replace` |
| `opd_doc_id` | the OPD document to re-attach / re-extract / replace |
| `source_doc_uid`, `source_doc_title`, `source_url` | the source document (canton uid, Fedlex ELI) and where to get it |
| `checks`, `verified` | the named checks run on that row (JSON) and their verdict; empty where only a sample was checked |

`results/repair/summary.json` gives the counts per body and action, and the measured precision of each route.

## What the routes produce

| route | affairs | evidence |
|---|---|---|
| `relink` (BE): canton answer already in OPD as a parentless document | 2,459 | uid join, byte-identical to the list prepared for OPD |
| `fetch` (BE): canton lists an answer OPD lacks | 49 | canton OGD |
| `agenda_join` (all bodies): answer filed under an agenda item of the affair | 592 | OPD's own `agendas.item_affair_id` |
| `retype_oral` (VS): the "answer" document is an oral-answer pointer | 1,008 | rule on OPD's own text |
| `ocr` (all bodies): answer document attached, no usable text in OPD | 1,351 | 30-document probe |
| **gap affairs with a typed repair action** | **5,459** | |
| `placeholder_replace` (CHE, documents not affairs) | 29,946 | Fedlex SPARQL |

## BE: the answers are in OPD, just not attached

The canton's own OGD tables (`ogd.parl.apps.be.ch/data/dokument.csv`, `geschaeft.csv`) list a government answer for 3,532 BE
interventions. In the 2026-10-06 OPD exports, 229 of them are attached to their affair, 527 sit under an agenda item, 2,638 are
parentless documents (no affair, agenda or meeting) that carry the canton's document uid in their URL, and 138 are absent.

`python -m gegenprobe.repair.be list` joins the canton answer documents to the OPD gap affairs on
`dokument_geschaeft_uid == affair.external_id` and to OPD's parentless documents on the uid. It reproduces the list prepared
for OpenParlData (`data/repair/fixtures/openparldata_be_relink_list.tsv`) byte for byte: 2,459 relink and 49 fetch rows, plus 2
gap affairs for which the canton lists no answer. The same join on the nightly census tables (`monitor.nightly`) gives the same
2,459 / 49, which cross-checks the census extraction against the raw exports.

**Triple check** (`be.verify_text`): (1) the affair number or the canton vorstoss number is printed in the document; (2) an
answer heading is present (DE/FR/IT lexicon); (3) the header field `RRB-Nr.: NNN/YYYY vom <date>` equals OPD's own answer-event
date.

| sample | identity + heading | RRB date = OPD event date |
|---|---|---|
| 40 random 2024–25 interpellations without an attached answer, canton source PDF (seed 20261008; re-run from code) | 40/40 [91.2, 100] | 39/39 [91, 100] (one affair has no OPD answer event) |
| **pre-registered**: 40 random `relink` rows, the copy OPD itself stores (seed 20261009, `data/repair/prereg_be_relink_sample.md`, hashed before drawing) | 40/40 [91.2, 100] | 36/40 [76.9, 96] |

The four registered date failures: three are parser misses (2020–21 header layouts where pdftotext emits the RRB number, other
header values, then `vom <date>`), and one is a typo in the canton's own PDF: 2015.RRGR.870 prints "RRB-Nr.: 119/2016 vom
3. Februar 2015" while OPD's answer event is 2016-02-03. A second parser version (v2, written after the registered run and
reported separately as post-hoc) reads the split header; on the same 40 cached documents the triple check then passes
39/40 [87.1, 99.6], and the only failure left is the source typo, which the check is meant to catch. The demo in `make run`
shows exactly this case as `REVIEW (date mismatch)`.

Per-affair fallback (no OPD ids needed): the canton's Geschäftsdetail fragment
`https://www.rrgr-service.apps.be.ch/api/gr/instances/585199c5-e188-44cb-b514-f143ada83635/render?gnumber=<nr>&lang=de`
(`be.route_b`).

## CHE: placeholders and federal answers

Most federal OPD documents (57.3%, see the census) store Fedlex's "JavaScript required" page as their text. These are BBl/AS publications attached to
government affairs, not answers to interventions. `repair.che` resolves the citation in the document's old URL through the
Fedlex SPARQL endpoint (one query per 100 citations) and fetches the pdf-a from `www.fedlex.admin.ch/filestore/`
(`fedlex.data.admin.ch` disallows `/filestore/` in robots.txt).

| sample | pre-set rule (> 1,000 chars, not the placeholder, year and page/citation in the text) |
|---|---|
| the 20 spike documents, re-verified from cached PDFs | 19/20 [76.4, 99.1]; 20/20 [83.9, 100] correct on inspection |
| 50 further documents (seed 20261009), resumable backlog run | 40/50 [67, 88.8] |

Of the 10 rule failures in the backlog run, 7 are short documents (one-page decrees under 1,000 characters) whose year and page
match, 2 are long reports whose text does not print the citation year, and 1 citation has no Fedlex match. The rule is
conservative; the backlog run needs 2.1 s per document at the polite rate, i.e. about 17.5 h for all 29,946 documents (one-off).

Answers to federal interventions are in OPD's separate `texts` export (Curia Vista "Antwort BR / Büro"), so the federal gap is
only 75 affairs. Curia Vista OData has a substantive Federal Council answer for 7/75 [4.6, 18] of them; 60 carry only the
one-line motion formula, 8 nothing.

## VS: oral answers, not lost answers

Of the 1,409 VS gap affairs, 1,112 have an `_ANT` (answer) document. Rule: a VS `_ANT` document whose OPD text is shorter than
200 characters and reads "réponse orale" / "mündliche Antwort" is the pointer "cf. réponse orale du Conseil d'Etat / s.
mündliche Antwort des Staatsrats". 1,008 gap affairs have only such pointers; they are retyped `oral` (the answer was given in
the session). Other short `_ANT` texts are reported, not retyped: "Pas de réponse pour les Interpellations" (38 documents) and
"pas de réponse car passe directement" (11 documents), i.e. no answer by procedure, and bare page numbers (scans).

## OCR: image-only answer scans

The re-extraction sample (30 random gap affairs outside BE/CHE with an answer document but no OPD text) splits into 15/30
image-only scans (TI 12, plus three communes), 13 VS oral-answer pointers that have a text layer, 1 BL document with a 152-char
text layer, and 1 TG document whose text OPD never extracted. The earlier "29/30 image-only" count treated every document under
200 characters as a scan; the VS stubs are not scans.

Tesseract with `deu+fra+ita` (tessdata_fast @ 8741641, sha256 in `repair/ocr.py`) recovers a written answer from 15/15
[79.6, 100] image-only scans: at least 200 characters, the executive's heading or letterhead, and a full date on page 1.
The English-only model passes the same coarse checks, but drops diacritics: 133 accented characters against 467 with the
language models on the same pages, which matters for quoting spans. Cost: 6.9 s per page (M-series Mac, 200 dpi, first 3
pages per document, under concurrent load).

## Not measured

The 11,206 gap affairs with no answer document anywhere in OPD (ZH before 2016, Zürich city, SG, NE, JU, Winterthur, …) need
per-body source adapters; none is built here. The 1,351 `ocr` rows are candidates; only the 30-document probe was OCR'd.
