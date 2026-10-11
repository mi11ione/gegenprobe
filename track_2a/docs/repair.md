# Repair: putting OpenParlData's missing government answers back

Model-free. Every number below is produced by `make repair` (cached inputs) or `make repair-network` (fetches) and is listed
in `claims.d/repair.tsv`. Output files follow one layout for every route: `results/repair/repair_<BODY>.tsv` and `.json`
(gzipped for CHE), and for bodies with more than one action one file per action (`repair_BE_relink.tsv`,
`repair_BE_review.tsv`, `repair_BE_fetch.tsv`, `repair_BE_agenda_join.tsv`, …). Every cell is plain text (no JSON inside
cells), so a `COPY` or a spreadsheet reads it:

| column | meaning |
|---|---|
| `body`, `affair_id`, `affair_number` | the OPD affair the row repairs (`affair_id` = OPD id) |
| `action` | `relink` · `agenda_join` · `fetch` · `retype_oral` · `ocr` · `placeholder_replace` · `review` |
| `proposed_action` | the route; equals `action` unless the row failed its per-row check and became `review` |
| `opd_doc_id` | the OPD document to re-attach / re-extract / replace |
| `source_doc_uid`, `source_doc_title`, `source_url` | the source document (canton uid, Fedlex ELI) and where to get it |
| `snapshot` | the export dates the row was computed from (`opd_exports 2026-10-06; be_ogd 2026-10-08`) |
| `check_identity`, `check_heading`, `check_decision_nr`, `check_decision_date`, `check_answer_event_dates`, `check_date_eq_event` | per-row document checks (BE relink/fetch: every row) |
| `check_detail` | other routes' row facts as `key=value; key=value` |
| `verified` | `true` / `false` per row where checked; empty where only a sample was checked (precision in `summary.json`) |

`results/repair/summary.json` gives the counts per body and route (`by_action` counts the route, i.e. `proposed_action`), the
39 rows sent to `review` by the per-row check, and the measured precision of each route.

## What the routes produce

| route | affairs | evidence |
|---|---|---|
| `relink` (BE): canton answer already in OPD as a parentless document | 2,459 | uid join; **every row** fetched and checked (2,421 pass, 38 → `review`) |
| `fetch` (BE): canton lists an answer OPD lacks | 49 | canton OGD; every row checked (48 pass, 1 → `review`) |
| `agenda_join` (all bodies): answer filed under an agenda item of the affair | 592 | OPD's own `agendas.item_affair_id`; not sample-verified |
| `retype_oral` (VS): the "answer" document is an oral-answer pointer | 1,008 | rule on OPD's own text |
| `ocr` (all bodies): answer document attached, no usable text in OPD | 1,350 | 30-document probe |
| **gap affairs with a typed repair action** | **5,458** | |
| `placeholder_replace` (CHE, documents not affairs) | 29,946 | Fedlex SPARQL |

One affair, 2024.RRGR.195, used to carry two rows (a canton `fetch` and an `ocr` row: OPD holds a scanned French RRB without
text, the canton OGD has the German text PDF). It now has one row, the canton route; the `ocr` count went from 1,351 to 1,350.

**Applying the BE relinks.** OPD confirmed (correspondence, 10 Oct 2026) that its staging keeps the first parent a document
is seen under; until that fix ships, the next scrape can re-attach a relinked answer to the agenda item or leave it
parentless again. Apply the list as a protected override, or after the fix. Either way the list doubles as the **acceptance
test of the fix**: `python -m gegenprobe.repair.acceptance` (local snapshot) or `--fetch` (today's `docs_BE` export) counts
how many of the 2,459 relink documents are attached to the affair the list names. In the 6 Oct 2026 snapshot all 2,459 are
still parentless; after the fix all 2,459 should be attached. The command exits 0 only then (1 otherwise, so a deployment
pipeline can gate on it) and keeps one dated result per check (`acceptance_<live|file>_<YYYY-MM-DD>.json`, in
`results/repair/` or in `--out DIR`, e.g. `--out /var/lib/gegenprobe/results` on a host whose checkout is read-only; the
directory is checked for writability before the export is streamed, exit 2 if it is not writable); the nightly
job's ledger (`repair_BE_ledger.tsv`, see `docs/nightly.md`) marks each row `resolved` once OPD has the answer.

## Which list wins: `results/repair/MANIFEST.json`

`python -m gegenprobe.repair.manifest` (last step of `make repair`, and of `make adapters-write`) lists every repair list
under `results/repair` (route lists, the Bern begin_date list and apply plan, the source-adapter lists
`adapters/adapters_<BODY>.tsv`) with the command that writes it, its rows by action (adapter lists also by tier) and its
sha256, checks that no two files share a name, and records where two lists name the same affair. Rules, then the
overlaps per parliament (route action / adapter tier; "no adapter row" = the adapter looked and listed nothing, so the
route row stands):

| lists | wins | why |
|---|---|---|
| adapter list vs route list, action=ocr (same affair) | adapter list | the route's ocr rows are candidates (OPD holds the answer file without usable text; no text read, verified empty). The adapters ran on every one of those affairs, read or OCR'd the text and checked it: their row (tier says whether it counts) replaces the candidate. A candidate whose affair has no adapter row (the adapter failed: no usable text, identity or heading not found) stays the only row for it. |
| adapter list vs route list, action=agenda_join or retype_oral (same affair) | no overlap | agenda joins are census link status agenda, retype_oral is Valais' oral-answer pointer; the adapters only take absent and image_only affairs. Checked on every run (overlaps below). |
| route list repair_<BODY>.tsv vs repair_<BODY>_<action>.tsv | either (same rows) | the per-action files are the combined file split by action; apply one or the other, not both. |
| repair_BE_relink.tsv / repair_BE_begin_date.tsv vs apply_be/apply_BE_plan.* | apply_be plan for execution | the plan is built from the two lists and guards every UPDATE with the before-state (repair.apply_be). |
| results/ vs site/downloads/ | identical | site/downloads holds byte-identical copies of the lists it offers (sha256 below). |

| parliament | route list (rows) | adapter list (rows) | same affair | route action / adapter tier |
|---|---|---|---|---|
| 131 | repair_131.tsv (60) | adapters_131.tsv (22) | 22 | agenda_join / no adapter row 8, ocr / exact_doc_date 2, ocr / no adapter row 30, ocr / review 20 |
| 191 | repair_191.tsv (37) | adapters_191.tsv (34) | 34 | ocr / exact_any_printed_date 1, ocr / exact_doc_date 1, ocr / no adapter row 3, ocr / review 32 |
| 198 | repair_198.tsv (2) | adapters_198.tsv (0) | 0 | ocr / no adapter row 2 |
| 230 | repair_230.tsv (64) | adapters_230.tsv (0) | 0 | agenda_join / no adapter row 64 |
| 2831 | repair_2831.tsv (16) | adapters_2831.tsv (15) | 15 | ocr / no adapter row 1, ocr / review 15 |
| 296 | repair_296.tsv (47) | adapters_296.tsv (39) | 39 | agenda_join / no adapter row 3, ocr / exact_any_printed_date 1, ocr / exact_doc_date 29, ocr / no adapter row 5, ocr / review 9 |
| 4289 | repair_4289.tsv (18) | adapters_4289.tsv (27) | 18 | ocr / exact_any_printed_date 1, ocr / review 17 |
| 4671 | repair_4671.tsv (31) | adapters_4671.tsv (4) | 2 | ocr / no adapter row 29, ocr / review 2 |
| 5002 | repair_5002.tsv (49) | adapters_5002.tsv (49) | 49 | ocr / review 49 |
| 5113 | repair_5113.tsv (3) | adapters_5113.tsv (225) | 3 | ocr / exact_doc_date 3 |
| 5586 | repair_5586.tsv (15) | adapters_5586.tsv (65) | 14 | ocr / no adapter row 1, ocr / review 14 |
| 581 | repair_581.tsv (24) | adapters_581.tsv (14) | 14 | ocr / no adapter row 10, ocr / review 14 |
| AR | repair_AR.tsv (2) | adapters_AR.tsv (0) | 0 | ocr / no adapter row 2 |
| BL | repair_BL.tsv (56) | adapters_BL.tsv (2) | 0 | ocr / no adapter row 56 |
| BS | repair_BS.tsv (24) | adapters_BS.tsv (1) | 0 | ocr / no adapter row 24 |
| FR | repair_FR.tsv (9) | adapters_FR.tsv (7) | 7 | ocr / exact_any_printed_date 6, ocr / no adapter row 2, ocr / review 1 |
| GR | repair_GR.tsv (2) | adapters_GR.tsv (0) | 0 | ocr / no adapter row 2 |
| JU | repair_JU.tsv (1) | adapters_JU.tsv (382) | 0 | ocr / no adapter row 1 |
| OW | repair_OW.tsv (12) | adapters_OW.tsv (0) | 0 | ocr / no adapter row 12 |
| SG | repair_SG.tsv (1) | adapters_SG.tsv (1,014) | 1 | ocr / exact_doc_date 1 |
| SH | repair_SH.tsv (1) | adapters_SH.tsv (0) | 0 | ocr / no adapter row 1 |
| SO | repair_SO.tsv (1) | adapters_SO.tsv (211) | 1 | ocr / exact_doc_date 1 |
| TG | repair_TG.tsv (50) | adapters_TG.tsv (49) | 49 | ocr / exact_any_printed_date 32, ocr / no adapter row 1, ocr / review 17 |
| TI | repair_TI.tsv (775) | adapters_TI.tsv (765) | 765 | ocr / exact_any_printed_date 719, ocr / no adapter row 10, ocr / review 46 |
| VS | repair_VS.tsv (1,111) | adapters_VS.tsv (282) | 36 | ocr / date_window 4, ocr / exact_any_printed_date 15, ocr / exact_doc_date 3, ocr / no adapter row 67, ocr / review 14, retype_oral / no adapter row 1,008 |
| ZH | repair_ZH.tsv (22) | adapters_ZH.tsv (2,255) | 7 | ocr / exact_doc_date 1, ocr / no adapter row 15, ocr / review 6 |

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

| rows checked | identity + heading | RRB date = OPD event date |
|---|---|---|
| 40 random 2024–25 interpellations without an attached answer, canton source PDF (seed 20261008; re-run from code) | 40/40 [91.2, 100] | 39/39 [91, 100] (one affair has no OPD answer event) |
| **pre-registered**: 40 random `relink` rows, the copy OPD itself stores (seed 20261009, `data/repair/prereg_be_relink_sample.md`, hashed before drawing) | 40/40 [91.2, 100] | 36/40 [76.9, 96] |
| **all 2,459 `relink` rows**, the copy OPD stores, fetched and checked (`repair.verify_all`, 0 fetch errors) | 2,459 / 2,459 | parser v2: 2,421 [97.9, 98.9]; registered parser v1: 2,332 |
| all 49 `fetch` rows, the canton's OGD PDF | 49 / 49 | 48 |

Every row of the list is now checked, not only the samples: the document OPD would re-attach prints the affair (or the
canton's Vorstoss) number and an answer heading in all 2,459 cases, and its RRB date equals OPD's own answer-event date in
2,421 (parser v2). The 39 rows that fail (38 relink, 1 fetch) are moved to `action=review` with their checks filled in: in 22
no decision date was parsed from the header, in 16 the parsed date differs from OPD's event (several 2015 RRBs whose header
carries a second "vom" date), and one is the canton's own typo (2015.RRGR.870, below). They are not wrong relinks; they are
the rows a person looks at before applying (about 2 minutes each).

The four registered date failures of the 40-row sample: three are parser misses (2020–21 header layouts where pdftotext emits the RRB number, other
header values, then `vom <date>`), and one is a typo in the canton's own PDF: 2015.RRGR.870 prints "RRB-Nr.: 119/2016 vom
3. Februar 2015" while OPD's answer event is 2016-02-03. A second parser version (v2, written after the registered run and
reported separately as post-hoc) reads the split header; on the same 40 cached documents the triple check then passes
39/40 [87.1, 99.6], and the only failure left is the source typo, which the check is meant to catch. The demo in `make run`
shows exactly this case as `REVIEW (date mismatch)`. The three parser misses are ours, not the canton's.

Per-affair fallback (no OPD ids needed): the canton's Geschäftsdetail fragment
`https://www.rrgr-service.apps.be.ch/api/gr/instances/585199c5-e188-44cb-b514-f143ada83635/render?gnumber=<nr>&lang=de`
(`be.route_b`).

## BE begin_date corrections

`python -m gegenprobe.repair.be_begin_date` → `repair_BE_begin_date.tsv`: 727 BE affairs whose `begin_date` is a load timestamp
(557 on 2024-10-28 and 170 from later loads, the two groups OPD described). The proposal is the affair's own "Eingereicht"
event, given as columns OPD can join on (`evidence_event_id`, `evidence_event_date`, `evidence_event_title`; 655 rows carry an
event id, the other 72 affairs have no events at all). 554 rows are `set_begin_date`; 173 are `review`: no Eingereicht event,
or a proposed date two or more years after the year in the affair number (9 rows, e.g. 2007.RRGR.2254 → 2011-03-28,
plausible for a re-submitted affair but checked before applying).

Three columns say three different things. `opd_group` is OPD's grouping, the one the README counts: `load_2024_10_28`
(557) or `later_load` (170). `group` is how the row was found: `load_2024_10_28`, `begin_matches_no_event` (98: the
begin_date equals none of the affair's own event dates) or `no_events` (72: the affair has no events, so nothing can be
proposed). `action` is what to do: `set_begin_date` (554) or `review` (173).

## Applying the Bern lists: `repair.apply_be`

`python -m gegenprobe.repair.apply_be --docs-export docs_BE.ndjson.gz --out DIR` (or `--fetch` for today's export) turns
`repair_BE_relink.tsv` and `repair_BE_begin_date.tsv` into an apply plan: `apply_BE_relink_plan.csv` (per document the
before-state read from the export, i.e. `parent_type`, `affair_id`, `agenda_id`, `meeting_id`, `hash`, `url_oparl`, and
the after-state), `apply_BE_begin_date_plan.csv` (before = the list's value, or the current one with
`--affairs-export affairs.ndjson.gz`), `apply_BE_plan.sql.txt` (guarded `UPDATE` statements as text: each one changes a
row only if it is still in its before-state) and `apply_BE_plan.json`. Without `--out` it prints the summary and writes
nothing. It never connects to OPD.

**Re-parenting changes OPD's document identifier.** OPD's `hash` is sha256(body_key + parent_type + url). In the
10 Oct 2026 `docs_BE` export every one of the 49,810 rows follows that rule, and all 2,421 verified relink documents are
stored with `parent_type = agenda` (and no agenda, affair or meeting id). Moving one to its affair therefore changes the
rule's input: the new identifier is sha256("BE" + "affair" + url), and the public file URL
`files.openparldata.ch/doc/BE/<hash>` changes with it. None of the 2,421 new identifiers collides with an existing one.
`--hash recompute` (default) writes the new value, consistent with what OPD's loader computes for an affair document;
`--hash keep` keeps the old identifier (stable URL, but it no longer follows the rule). Which one to use is OPD's decision.
The plan for the 10 Oct export is in `results/repair/apply_be/` (made from a projection of `docs_BE` that keeps the
metadata fields and drops the text): 2,421 `apply`, 554 begin_date `apply`, 173 begin_date `review`.

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
per-body source adapters: `repair/adapters/`, results and limits in `docs/adapters.md`. The 1,350 `ocr` rows are candidates; only the 30-document probe was OCR'd.
