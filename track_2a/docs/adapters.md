# Source adapters: finding the written answers OPD does not show

Model-free. `src/gegenprobe/repair/adapters/` (upgrade U1). The census counts **16,749** interventions with a written-answer
event and no answer text in OpenParlData (OPD). Before the adapters, deterministic routes proposed repairs for **3,107**
of them (Bern relink 2,459 and fetch 49, agenda joins 592, Curia Vista 7) and **10,800** written answers "needed
per-parliament source adapters": no answer document anywhere in OPD (census link status `absent`, outside BE and CHE,
question time excluded). The adapters work on those 10,800 and, separately, on the 1,350 affairs whose answer document
OPD holds without text (`image_only`, the `ocr` candidates).

    python -m gegenprobe.repair.adapters.targets            # the target affairs with OPD's dates (WORK/adapters)
    python -m gegenprobe.repair.adapters.opd_docs           # OPD's own documents (with text) for those affairs
    python -m gegenprobe.repair.adapters.run BODY ...       # resumable; --redo re-checks non-verified rows from cache
    python -m gegenprobe.repair.adapters.run --write        # rebuild results/repair/adapters/ from the checkpoints
    python -m gegenprobe.repair.adapters.run --table        # the results table below
    python -m gegenprobe.repair.adapters.canary run         # re-check one known affair per external source (network)
    python -m gegenprobe.repair.manifest                    # results/repair/MANIFEST.json: every list, which one wins

## The common interface

Every adapter answers one question per OPD affair (`base.py`): **candidates** (where the answer may be) -> **text** (OPD's
stored text, or the file fetched politely through `gegenprobe.net` and extracted with pdftotext, tesseract deu+fra+ita
for image-only scans) -> **checks**:

| check | passes when |
|---|---|
| identity | the affair number is printed, in the parliament's own spellings (`GR Nr. 2009/039` for 2009/39, `P 517` for 2025P 517, `(3320)` for QE 3320, ...), or the OPD title is printed near the top (as one string, or 80% of its content words) |
| heading | the parliament's answer formula is printed ("Der Stadtrat beantwortet die Anfrage wie folgt", "Antwort der Regierung vom", "Réponse écrite du Conseil d'État", "Il Municipio risponde", ...). Question phrases ("prié de répondre", "um Beantwortung", "Souhait d'une réponse écrite") and council minutes ("prend acte de la réponse") are excluded and tested |
| date | the document's own date (header, or the place-date line) **equals** one of OPD's written-answer event dates (`eq`), or an executive event of the affair (`eq_gov`, Solothurn: OPD's "Beantwortet" event is the committee's, the government's "Antrag" event carries the answer date), or some date printed in the document equals an OPD answer event (`anywhere`), unless the document's own date was read and lies more than 30 days from every OPD event (`anywhere_conflict`: review); a documented per-parliament window (below); where OPD's answer events carry no date (Jura), the document is dated within a year after OPD's submission event (`after_submission`) |

**Verified** = identity and heading and date, and no document-type filter fires (below); how strong the date check is
sets the verification tier (Results, "Verification tiers"), and only the three tiers with a date check count as repairs.
**Review** = identity and heading but the date is off (within 14 days: `near`, or further: `differs`), or identity and
the source itself types the document as the answer but no heading matched, or a filter that sends to review fired.
**Failed** = a typed reason: `no_candidate` (the source lists no answer document), `not_found`, `robots_disallowed`,
`robots_unreachable`, `http_404`, `empty_text`, `oral_pointer` (VS: the answer document points to an oral answer),
`translation_stub`, `identity_fail`, `heading_fail`, or the reason of a filter that fails the row.

**Document-type filters** (`filters.py`, shared by every adapter; 11 Oct 2026, after the blind audit below). A document
can print the affair, an answer formula and a matching date and still not be the government's answer. Each filter
recognises one such type from the document's own wording and moves the row down, never up, with a typed reason; the
checks carry `filter` and `filter_quote`, and `results/repair/adapters/filtered.tsv` lists every affair a filter fired
on. Nothing is dropped silently: filtered rows stay in `<BODY>.json` and the summary (`filtered`).

| filter | recognises | moves to |
|---|---|---|
| `extension_request` | the subject line asks for or grants more time (Fristverlängerung, Fristerstreckung, prolongation du délai, proroga del termine), the subject does not also announce the answer or the closing report (Prüfungsbericht, Abschreibung, Antwort, réponse, risposta), and no answer formula is printed | failed |
| `parliament_report` | the document opens as a report of a parliamentary body (Rapporto della commissione, Bericht der ...kommission, Bericht des Ratsbüros, Rapport de la commission) and its header carries no executive formula | failed |
| `minutes_reference` | the legislature's minutes, which only refer to the written answer ("Die Antwort des Stadtrates liegt schriftlich vor", "auf die separaten Akten verwiesen") and print no answer of their own | failed |
| `member_text_only` | the member's own text: it opens or closes as the question ("ANFRAGE von", "presentano la seguente interrogazione", "Initiative : interpellation urgente", "Nell'attesa di una risposta", "Nous remercions le Gouvernement de ses réponses") and no executive answer formula is printed outside a citation ("nella risposta all'interrogazione 1069" is a citation) | failed |
| `wrong_affair` | the header prints an affair number of the parliament's own shape (Solothurn `A 0110/2024`, St. Gallen `51.15.56`, Zürich `KR-Nr. 468/1998`, Zürich city `GR Nr.`, Bern city `2014.SR.000106`) that is not the target's, and the target's number is printed nowhere in the document (joint answers print it and pass); header typos exist, so | review |
| `resolution_reply` | the executive's reply to a resolution the council adopted after the answer to the interpellation (Lausanne): an executive document, not the answer itself | review |

`python -m gegenprobe.repair.adapters.run --refilter` re-judges every saved excerpt with the current checks (no
network) and processes again each affair whose best document a filter moved down (its other candidates, documents from
the WORK caches; Zürich canton and St. Gallen re-read the source's document list), keeping the new result only when it
is better: 7 Zürich canton motions verified on the government's report (`Vorlage 154c/2021`, ...) once the extension
request filed before it (`154a/2021`) no longer verified first. Every affair keeps its outcome in
`results/repair/adapters/<BODY>.json` (with its tier); only verified and review rows go into `adapters_<BODY>.tsv`
("The lists OPD applies" below; `check_detail` carries route, identity and date class, sha256, extractor and a quote of
at most 200 characters). Document texts and PDFs stay in WORK and are never committed.

**Actions.** `fetch`: the parliament publishes the answer and OPD does not hold it. `relink`: OPD holds the same file
elsewhere. `tag_answer`: **OPD already holds the answer, with text, on the affair**, under a generic name (the
intervention's title, a file name, "Vorstoss - V2017.154") and in a wording the census lexicon does not list, so neither
OPD's users nor the census see it as the answer; the fix is to set the document's category. `extract_tag`: OPD holds the
answer file on the affair without usable text; extract (text layer or OCR) and tag it.

Per-parliament date rules (event − document date, days), each from the parliament's practice: Zürich city 0 to +15
(before about 2012 OPD's "Stadtrat, Antwort" event is the dispatch a week or two after the decision; pilot of 200: 150
equal, +1, +7 ×13, +8 ×3, +14, +15); Neuchâtel −1 to +1 ("transmise aux membres du Grand Conseil le …"); Frauenfeld −3
to +3 (signed around OPD's date); Kriens −70 to 0 (OPD's answer event carries the submission date; the Stadtrat's
position follows within about 8 weeks); Valais 0 to +120 (for motions OPD's answer event is the session that treated the
motion, which the Conseil d'État's written answer precedes; first full run: 0 to 217 days, median about 55, 145 of 172
within 120; `vs.py`). Everywhere else: equal dates only.

## Investigation: the parliaments with the most written answers missing

Ranked by written answers with no answer document in OPD (census `absent`; Bern has its own route). Robots status is the
parliament's robots.txt for the paths the route needs, read under RFC 9309.

| parliament | written answers missing (absent) | route | robots |
|---|---|---|---|
| Zürich canton (ZH) | 3,008 | **yes**: Kantonsrat CDWS web service, search by KR-Nr., step "Antwort Regierungsrat" document -> `Files/<id>/<version>/pdf`; when OPD already holds the file on the affair (Vorlage), `tag_answer` | parlzhcdws.cmicloud.ch: robots.txt 404 (no restrictions) |
| Zürich city (261) | 1,457 | **yes, in OPD**: the Stadtrat's minutes extract with the answer is attached to the affair under the question's file name | gemeinderat-zuerich.ch: no rules |
| St. Gallen canton (SG) | 1,017 | **yes**: RIS JSON API `/api/businesses/<external_id>/published_documents`, document type "Antwort" | robots.txt is the app's HTML (no rules) |
| Neuchâtel canton (NE) | 721 | **partial, in OPD**: older question PDFs carry the appended "Réponse écrite du Conseil d'État"; for the rest the sampled answers (14/14) were given orally in the session ("Réponse de M./Mme …"), so a written source does not exist; session minutes (PV, from 2023) not built | ne.ch: allowed |
| Jura canton (JU) | 656 | **partial**: the answer PDF ("…Reponse-du-Gouvernement.pdf") is listed in OPD for about half; taken from OPD's text or fetched from /Htdocs/ and OCR'd; the intervention pages are disallowed | jura.ch: `/InterventionParlementaire.ashx` **disallowed**; /Htdocs/ allowed |
| Winterthur (230) | 629 | **no**: the CMI page lists a document "Antwort Stadtrat" (seen in the Internet Archive), but the host does not answer (TCP timeouts on 80/443) | parlament.winterthur.ch **unreachable** (fail-closed) |
| Locarno (5113) | 296 | **partial, in OPD**: the Municipio's answer letters are attached under the question's title; text-less copies come from OPD's own file copy | locarno.ch: `/files/` **disallowed** (OPD's copy on files.openparldata.ch is used) |
| Valais canton (VS) | 289 (+103 image-only) | **yes**: front-end API `/api/fe/v1/entity?id=<external_id>` -> `_ANT`/`_REP` member -> `/api/fe/v1/document?id=…&locale=fr|de` -> PDF; answers to written questions are departmental letters "En accord avec le Conseil d'État, nous …" | parlement.vs.ch: empty robots.txt |
| Münsingen (616) | 269 | **no adapter**: OPD's url_external is the register PDF of all motions; answers only in session protocols (2019+), about 40% reachable, not built | allowed |
| Solothurn canton (SO) | 211 | **yes**: same RIS API as St. Gallen, "Stellungnahme des Regierungsrates" | no rules |
| Lugano (5192) | 201 | in OPD only (generic adapter); motions are answered by the Municipio's "preavviso"/"osservazioni" | `/dam/...` items disallowed; not needed |
| Frauenfeld (4566) | 194 | **yes, in OPD**: OPD's document is the Stadtrat's answer with the question attached; scans and broken font maps re-extracted | `/public/upload/assets/` allowed |
| Pratteln (2831) | 184 | **no**: host unreachable; OPD holds the question only | www.pratteln.ch **unreachable** |
| Illnau-Effretikon (296) | 178 (+44 image-only) | **partial, in OPD**: answer files "…_SRB_Antwort SR_…" (mostly scans) via OPD's own copy and OCR | www.ilef.ch **unreachable** |
| Aarau (4001) | 177 | **yes for 2018+**: yearly "Anfragen" pages link the question OPD holds next to "Antwort Stadtrat"; 2014-17 only in minutes | `/route/` disallowed (not needed); 429 on bursts |
| Liestal (2829) | 167 | **partial, in OPD**: "DER STADTRAT AN DEN EINWOHNERRAT … Bericht" | www.liestal.ch **unreachable** |
| Lausanne (5586) | 148 | in OPD only (generic) | not needed |
| Vaud canton (VD) | 112 | **yes, in OPD**: "RAPPORT DU CONSEIL D'ETAT AU GRAND CONSEIL sur le postulat …" | sieldocs.vd.ch robots.txt 503 (blocked, not needed) |
| Bern city (351) | 106 | **partial, in OPD**: "Vortrag des Gemeinderats an den Stadtrat"; Kleine Anfragen in session minutes not built | allowed |
| Luzern canton (LU) | 105 | **yes**: affair page (OPD url_external) -> link "Antwort/Stellungnahme des Regierungsrates" -> cdws document | allowed |
| Kriens (1059) | 75 | **yes, in OPD**: "Begründung zum Postulat / zur Motion", "Antrag des Stadtrates" | `/route/` disallowed (not needed: OPD text) |
| Ticino canton (TI) | 1 (+775 image-only) | **Word/PDF route blocked**: the answer files (`allegato.php`) are disallowed by robots.txt; the image-only answers are OCR'd from OPD's own copy on files.openparldata.ch | www4.ti.ch: `/user_librerie/php/GC/allegato.php` **disallowed** |

Every other parliament with target affairs runs the generic in-OPD adapter (`inopd.py`).

## Results

All 12,150 target affairs (10,800 `absent` + 1,350 `image_only`) were run; outputs in `results/repair/adapters/`
(`adapters_summary.json`, `tiers.json`, per body `<BODY>.json` and `adapters_<BODY>.tsv`). OPD docs snapshot of 10 Oct
2026; parliament sites fetched 10-11 Oct 2026.

**Coverage.** Every row below printed the affair's identity and the parliament's answer formula; the tiers differ in the
date check and no document-type filter fired. Counted as verified repairs (tiers with a date check): **6,613** affairs,
**5,793** of the 10,800 written answers that had no answer document in OPD and **820** of the 1,350 image-only answers
(a text copy verified). Deterministic routes now propose repairs for **9,720 of 16,749** interventions without answer
text: **3,107** from the routes before the adapters (Bern relink 2,459 and fetch 49, agenda joins 592, Curia Vista 7)
plus **6,613** adapter rows. **5,007** written answers still need adapters. **27 of the 50** adapters yield counted
repairs; 23 yield none (unreachable hosts, answers only in minutes or given orally, no answer file in OPD). Listed
separately and not counted: **282** Jura answers checked by identity and wording only (OPD's Jura answer events carry no
date). Another **917** rows are review (661 absent, 256 image-only): listed, not counted.

Round 6 (11 Oct 2026, list hygiene after the judges' review) moved **220** rows from counted to review and changed no row
the other way: **211** rows whose only date match was some printed date while the document's own date lay more than 30
days from every OPD event (Frauenfeld 129, where the header date is the attached question's; Valais 32, Dübendorf 15,
Ticino 10, ...), and **9** Zürich canton `tag_answer` rows whose Kantonsrat file sits on the affair in OPD twice or more
(two versions of the same CDWS file; `review_reason` names the ids and the version read). Before (first run, then the
filters): 6,909 and 6,833 counted, 10,016 and 9,940 of 16,749.

### Verification tiers

`results/repair/adapters/tiers.json` (per tier: rows by cause, action, date class and parliament; for the window tier
each parliament's window and the offsets observed); `summary.json` carries the counts.

| tier | date check | rows | absent | image-only | counted |
|---|---|---|---|---|---|
| `exact_doc_date` | the document's own date (header or place-date line) equals an OPD answer event (`eq` 4,947), or the executive's event (`eq_gov` 214, Solothurn) | 5,161 | 5,120 | 41 | yes |
| `exact_any_printed_date` | some date printed in the document equals an OPD answer event (`anywhere`), and the document's own date was not read (OCR'd Ticino letters, Neuchâtel's appended answers, Aarau, ...) or lies within 30 days of an OPD event | 1,056 | 281 | 775 | yes |
| `date_window` | within the parliament's documented window above (`window` 301; `latest_in_window` 95: no header date, the latest printed date before the event lies in the window): Zürich city N = 15 (215 rows, observed +1 to +15 days), Valais N = 120 (140, +1 to +118), Kriens N = 70 (32, −61 to −1), Neuchâtel N = 1 (9, −1 to +1); Frauenfeld's window (N = 3) decided no row | 396 | 392 | 4 | yes |
| `identity_wording_only` | Jura: OPD's Jura answer events carry no date, so the date check is only "dated within a year after OPD's submission event" (`after_submission`) | 282 | 282 | 0 | no, listed separately |
| `review` | identity and heading, but the date is off (`near`, `differs`, `anywhere_conflict` 211, no date), no answer event, a filter that sends to review, or an ambiguous OPD document (`opd_doc_ambiguous` 9) | 917 | 661 | 256 | no |

Rule (conservative, fixed before the audit below): a row counts only in the first three tiers. An `anywhere` match is
weaker evidence than the document's own date, so it never overrides a document date that disagrees: a read document
date more than 30 days from every OPD event sends the row to review. Where no document date was read at all (mostly OCR
of scanned letters), the printed date that equals OPD's answer event is the only date evidence and the row counts; the
blind audit v3 estimates this tier's precision separately.

The 282 Jura rows stay in `adapters_JU.tsv` with `tier=identity_wording_only`, `counted=false`, `verified=false` and
`action=review` (`proposed_action` keeps `tag_answer` / `extract_tag`) for a person or OPD to confirm; they are not in
the headline figures. Jura's counted rows: 72, all with the document's own date.

**By action** (counted tiers): `fetch` 3,584 (Zürich canton, St. Gallen, Solothurn, Luzern, Valais, Aarau), `tag_answer`
2,177 and `extract_tag` 852 (the Jura tier adds `extract_tag` 281 and `tag_answer` 1). **2,177 answers are already in OPD
with text** on the affair (`tag_answer`: Zürich city 1,417, Neuchâtel 237, Zürich canton 143 Vorlagen, Vaud 91, Kriens
69, ...): the census lexicon (`census/defs.py`, frozen) does not recognise their wording, so they are counted as
missing. Identity: the affair number for most bodies; the title for Ticino, Jura, Frauenfeld, Locarno and Aarau; the
source's own document label for Valais.

`python -m gegenprobe.repair.adapters.run --table`:

| parliament | targets (absent + image-only) | exact document date | exact printed date | date window | of which tag/extract (in OPD) | identity + wording only (not counted) | review | failed: top reasons | moved down by document-type filters |
|---|---|---|---|---|---|---|---|---|---|
| Zürich (canton) (ZH) | 3,030 | 2,170 | 2 | 0 | 144 | 0 | 83 | no_candidate 740, member_text_only 23, extension_request 12 | member_text_only 23, extension_request 12, wrong_affair 3 |
| Zürich (city) (261) | 1,457 | 1,162 | 40 | 215 | 1,417 | 0 | 21 | heading_fail 19 | - |
| St. Gallen (canton) (SG) | 1,018 | 1,012 | 0 | 0 | 0 | 0 | 2 | http_404 2, no_candidate 2 | wrong_affair 1 |
| Ticino (canton) (TI) | 776 | 0 | 719 | 0 | 719 | 0 | 46 | identity_fail 7, http_404 2, no_candidate 2 | - |
| Neuchâtel (canton) (NE) | 721 | 117 | 111 | 9 | 237 | 0 | 14 | no_candidate 470 | - |
| Jura (canton) (JU) | 657 | 72 | 0 | 0 | 72 | 282 | 28 | no_candidate 260, identity_fail 15 | - |
| Winterthur (city) (230) | 629 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 629 | - |
| Valais (canton) (VS) | 392 | 8 | 15 | 140 | 0 | 0 | 119 | oral_pointer 49, empty_text 33, http_404 15 | - |
| Locarno (city) (5113) | 299 | 109 | 13 | 0 | 122 | 0 | 103 | no_candidate 43, member_text_only 17, http_404 9 | member_text_only 17 |
| Münsingen (city) (616) | 269 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 268, identity_fail 1 | - |
| Illnau-Effretikon (city) (296) | 222 | 29 | 1 | 0 | 30 | 0 | 9 | no_candidate 177, minutes_reference 4, identity_fail 2 | minutes_reference 4 |
| Solothurn (canton) (SO) | 212 | 210 | 0 | 0 | 0 | 0 | 1 | identity_fail 1 | wrong_affair 1 |
| Lugano (city) (5192) | 201 | 0 | 1 | 0 | 1 | 0 | 6 | no_candidate 187, parliament_report 7 | parliament_report 7 |
| Pratteln (city) (2831) | 200 | 0 | 0 | 0 | 0 | 0 | 15 | no_candidate 184, member_text_only 1 | member_text_only 1 |
| Frauenfeld (city) (4566) | 194 | 12 | 4 | 0 | 16 | 0 | 147 | identity_fail 21, heading_fail 9, no_candidate 1 | - |
| Aarau (city) (4001) | 177 | 2 | 69 | 0 | 4 | 0 | 16 | no_candidate 83, identity_fail 5, member_text_only 2 | member_text_only 2 |
| Liestal (city) (2829) | 167 | 0 | 0 | 0 | 0 | 0 | 63 | no_candidate 101, identity_fail 3 | - |
| Lausanne (city) (5586) | 163 | 1 | 3 | 0 | 4 | 0 | 61 | no_candidate 93, identity_fail 4, member_text_only 1 | resolution_reply 25, member_text_only 1 |
| Collombey-Muraz (municipality) (6152) | 130 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 130 | - |
| Monthey (city) (6153) | 119 | 4 | 25 | 0 | 29 | 0 | 4 | no_candidate 86 | - |
| Vaud (canton) (VD) | 112 | 83 | 8 | 0 | 91 | 0 | 13 | no_candidate 8 | - |
| Bern (city) (351) | 106 | 3 | 0 | 0 | 3 | 0 | 2 | no_candidate 66, extension_request 35 | extension_request 35 |
| Luzern (canton) (LU) | 105 | 104 | 0 | 0 | 0 | 0 | 1 | - | - |
| Basel-Landschaft (canton) (BL) | 104 | 0 | 2 | 0 | 2 | 0 | 0 | no_candidate 102 | - |
| Basel-Stadt (canton) (BS) | 103 | 0 | 1 | 0 | 1 | 0 | 0 | no_candidate 100, parliament_report 2 | parliament_report 2 |
| Kriens (city) (1059) | 75 | 35 | 2 | 32 | 69 | 0 | 4 | no_candidate 2 | - |
| Kreuzlingen (city) (4671) | 56 | 0 | 0 | 0 | 0 | 0 | 4 | http_404 29, no_candidate 23 | - |
| Adliswil (city) (131) | 52 | 2 | 0 | 0 | 2 | 0 | 20 | empty_text 20, http_404 10 | - |
| Wetzikon (ZH) (city) (121) | 51 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 51 | - |
| Bellinzona (city) (5002) | 50 | 0 | 0 | 0 | 0 | 0 | 49 | no_candidate 1 | - |
| Thurgau (canton) (TG) | 50 | 0 | 32 | 0 | 32 | 0 | 17 | identity_fail 1 | - |
| Fribourg (canton) (FR) | 43 | 0 | 6 | 0 | 6 | 0 | 1 | no_candidate 34, http_400 1, identity_fail 1 | - |
| Dübendorf (city) (191) | 37 | 1 | 1 | 0 | 2 | 0 | 32 | identity_fail 3 | - |
| Zofingen (city) (4289) | 34 | 4 | 1 | 0 | 5 | 0 | 22 | no_candidate 6, identity_fail 1 | - |
| Vernier (city) (6643) | 32 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 32 | - |
| Arbon (city) (4401) | 31 | 21 | 0 | 0 | 21 | 0 | 0 | no_candidate 7, identity_fail 3 | - |
| Interlaken (city) (581) | 26 | 0 | 0 | 0 | 0 | 0 | 14 | no_candidate 12 | - |
| Obwalden (canton) (OW) | 12 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 12 | - |
| Uster (city) (198) | 11 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 11 | - |
| Nidau (municipality) (743) | 6 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 6 | - |
| Thun (city) (942) | 5 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 5 | - |
| Schlieren (city) (247) | 4 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 4 | - |
| Appenzell Ausserrhoden (canton) (AR) | 2 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 2 | - |
| Graubünden (canton) (GR) | 2 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 2 | - |
| Liechtenstein (Landtag) (LIE) | 2 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 2 | - |
| Schaffhausen (canton) (SH) | 2 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 2 | - |
| Wädenswil (city) (293) | 1 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 1 | - |
| Neuchâtel (city) (6458) | 1 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 1 | - |
| Opfikon (city) (66) | 1 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 1 | - |
| Genève (canton) (GE) | 1 | 0 | 0 | 0 | 0 | 0 | 0 | no_candidate 1 | - |

Why the large remainders fail: Zürich canton 740 `no_candidate` are mostly postulates (524) and motions (192) whose
Kantonsrat record lists no government document (OPD's "answer" event there is a step of the council's own procedure);
Neuchâtel 470 and Pratteln are answers given orally in the session; Winterthur (629), Pratteln, Liestal and
Illnau-Effretikon sit on unreachable hosts; Münsingen (269) and Collombey-Muraz keep answers only in session minutes; Jura
260 have no answer file in OPD and the intervention pages are disallowed (and 282 of Jura's 354 rows that pass identity
and wording are not counted: no dated answer event to check against).


## The lists OPD applies

`results/repair/adapters/adapters_<BODY>.tsv`, one per parliament (`site/downloads/` holds byte-identical copies). The
columns of `repair/common.py` without the per-row `note` (the route is per parliament, in `adapters_summary.json`), then:

| column | meaning |
|---|---|
| `tier` | `exact_doc_date`, `exact_any_printed_date`, `date_window`, `identity_wording_only` or `review` (failed affairs are not listed; they stay in `<BODY>.json`) |
| `counted` | `true` only for the three tiers with a date check; `verified` equals `counted` in every row, and `action` is the proposed action only when counted (otherwise `review`; `proposed_action` keeps it). Filtering `counted=true` (or `verified=true`, or `action!=review`) gives the same 6,613 rows |
| `review_reason` | why a row does not count: the check's reason and date class (`date_mismatch: anywhere_conflict(335d)`), `identity_wording_only: after_submission(+41d)`, `opd_doc_ambiguous: ... (ids 173738 633165; the version read is 633165)` |
| `opd_doc_id` | the OPD document the row acts on, for every row that points at a document already in OPD. Zürich canton's `tag_answer` rows found the Kantonsrat's file on the affair in OPD; they are joined back by the CDWS file id in OPD's URL (`/Files/<id>-332/<version>/pdf`): 147 match one document; 9 match two or four (versions of the same file) and go to review |
| `text_sha256` | sha256 of the extracted text the checks read (UTF-8); with `check_detail` `sha256=` (the file) OPD can confirm it reads the same document and the same text |
| `target_category` | the category an applied `tag_answer`, `extract_tag` or `fetch` row sets: `response_text`, the value of OPD's harmonised document vocabulary (docs exports, `category_harmonized`) for a government answer (744 documents in OPD carry it; next to `submitted_text`) |
| `target_category_note` | the parliament's own answer label in OPD where it uses one (`category_fr=Réponses aux questions écrites` for Jura, `category_it=Risposte` for Ticino, `category_de=Antwort Stadtrat` for Arbon and Zofingen, ...); where none of OPD's documents on the parliament's target affairs carries a category, or none of its labels names an answer, the note says that the own label cannot be determined and only `category_harmonized` is set (`results/repair/adapters/opd_categories.json`) |
| `census_link_status`, `census_category` | the registered census status of the affair and its place in the derived layer (`census/corrected.py`: `unrecognised:exact_doc_date`, `image_only:text_verified`, `fetchable:adapter`, `open:review`, ...) |

**Which list wins.** `results/repair/MANIFEST.json` (`python -m gegenprobe.repair.manifest`; table in `docs/repair.md`)
lists every repair list with its command, rows, actions and sha256. The older route lists `results/repair/repair_<BODY>.tsv`
hold `ocr` candidate rows for the 1,350 image-only affairs (no text read, `verified` empty); the adapters ran on every
one of them, so for the 1,076 affairs both lists name, the adapter row wins (its tier says whether it counts; 12 point at
a different OPD document than the candidate, the one whose text verified), and a candidate the adapter could not read
stays the only row. Agenda joins and Valais' `retype_oral` rows have no adapter counterpart. No two files under
`results/repair` share a name (the adapter lists were `repair_<BODY>.tsv` and `repair_<BODY>_review.tsv` until 11 Oct
2026; the review subset is now `tier=review`, and the summary is `adapters_summary.json`).
`adapters_X.tsv` is not a parliament's list: it is a header-only file that a test wrote into this folder until round 8.
It stays because LOCK8 hashes every `adapters_*.tsv`, and `MANIFEST.json` marks it as a test artefact.

**Applying the tag rows.** `python -m gegenprobe.repair.apply_tags --exports-dir DIR --out PLAN` (or `--fetch`) reads
OPD's `docs_<BODY>` exports. For every `counted=true` row with action `tag_answer` or `extract_tag`, it writes a
before-state CSV, a JSON summary and guarded `UPDATE docs SET category_harmonized = 'response_text'` statements as text.
It is a dry run like `repair.apply_be` and never connects to OPD. Every statement checks the document id, `body_key`,
`affair_id` and `category_harmonized IS NULL`. The rest of the guard depends on the row:
- A `tag_answer` row checked on OPD's own text adds `sha256(text) = text_sha256`.
- A row checked on our extraction of the same file (Zürich canton: pdftotext of the PDF that OPD links) adds the URL and
  the hash of OPD's text in that export.
- An `extract_tag` row adds "the document still has no text, same URL". Its `text_sha256` is the hash of our tesseract
  output, so it cannot guard OPD's own OCR text.

A document that already has another category is listed as `category_set` and gets no statement.

**Scraper-set categories can overwrite hand-set ones.** Several scrapers write `category_harmonized` themselves; in the
target bodies, for example, NE sets `recording_video` and TI sets `protocol`. A value set by an import can therefore be
overwritten on the next scrape. Apply the tag rows as a **protected override** (a field the scraper does not overwrite),
as for the Bern relinks (`docs/runbook.md`), or fix the scraper's mapping first.

**The P7 tier in the same columns.** `results/repair/adapters/p7/promoted_by_apertus.tsv`
(`python -m gegenprobe.repair.adapters.promoted_list`) holds the 214 rows of the registered P7 output
`results/repair/adapters/p7/promoted.tsv`, laid out in the adapter-list columns. Each row is its parliament's
`tier=review` row, joined on affair, OPD document and text hash, so `source_url`, `target_category` and `text_sha256`
are filled. On every row `tier` is `promoted_by_apertus`, `counted` and `verified` are `false`, `action` is `review`,
`proposed_action` is set, and P7's own columns follow with the prefix `p7_`. The apply filter stays `counted=true`: this
tier is a pre-sorted batch for a reviewer.

## Robots.txt: RFC 9309 in every process (incident of 10 Oct 2026)

`gegenprobe.net.allowed()` used Python's `urllib.robotparser`, which applies the **first** matching rule of a group; RFC
9309 §2.2.2 says the **most specific (longest)** match wins and an allow wins a tie. www4.ti.ch lists `Allow: /` before
`Disallow: /user_librerie/php/GC/allegato.php`, so `net` allowed a path the site disallows. On 10 Oct 2026, during the
adapter run, three Ticino answer files (`allegato.php?allid=115005`, `119023`, `137701`) were fetched this way; they
were deleted from WORK and no row uses them (Ticino's answers come from OPD's own copy on files.openparldata.ch). The
same parser also let the gold-set samplers, `make run` and a census spot check request disallowed www4.ti.ch paths (147
URLs in all, 9-10 Oct); the project-wide audit, the OPD-copy fallback and the timeline are in `docs/incidents.md`.

The fix covers every entry point, not only the adapters. `src/gegenprobe/robots9309.py` is the one matcher (longest
match, allow wins ties, `*` and a final `$`, groups for our product token merged, empty `Disallow` allows, percent
escapes compared in one normal form); `src/sitecustomize.py`, which Python imports at start-up from the first `sys.path`
entry that has one, installs it into `urllib.robotparser.RobotFileParser` for the whole process. Every entry point puts
`src/` on `PYTHONPATH` (Makefile, Dockerfile for `make run` and the Docker nightly unit, the venv nightly unit, CI, the
subprocesses of the nightly job), so `net.allowed()` (locked, LOCK2, unchanged) now decides by RFC 9309.
`repair/adapters/robots.py` keeps its own read of robots.txt with the same matcher before every adapter request, so
an adapter URL is fetched only when both agree. `tests/test_robots9309.py` checks the matcher (the ti.ch case, `*`,
`$`, ties), that `net` refuses the three allegato.php URLs with a stubbed robots.txt, and that sitecustomize loads under
each entry point's `PYTHONPATH`; CI checks the patch on the runner and inside the built image.

**Audit** (`python -m gegenprobe.repair.adapters.robots_audit` -> `results/repair/adapters/robots_audit.json`, robots.txt
read 11 Oct 2026, RFC 9309 matcher): of the 7,463 documents the adapters fetched, 7,393 sit on hosts whose robots.txt
could be read and **none is disallowed**; the 11 API and index requests (CDWS, RIS, Valais, Luzern, Aarau, OPD
exports) are allowed. 70 fetched documents (www.ilef.ch 52, www.pratteln.ch 18) cannot be re-checked: both hosts are
unreachable from our network today, and `net` fetched them only while their robots.txt was readable. The 1,157
disallowed URLs in the audit are parliament URLs OPD records next to its own copy or its text (Ticino 801, Locarno 259,
Kriens 73, Arbon 24); the adapters read OPD's copy or text instead, and apart from the three Ticino files above did
not request them.

## Audit

`.work/adapters/audit/<BODY>.jsonl`: per adapter a stratified sample of 30 (20 verified, 6 review, 4 failed with text;
seed 20261011), each row with OPD's title, type and answer dates, the proposed action, the source URL and the path of
the extracted text, for blind auditors ("Is this document the government's written answer to this affair?").

**First audit** (blind agent annotators, 11 Oct 2026; verdicts in `.work/adapters/audit_verdicts/`): 796 rows. Of the
**511** verified rows, **457** were judged the government's answer, **34** not, **20** unclear. The verified 'no' rows
were deadline-extension requests (Bern city's Gemeinderat asking for more time on a motion or postulate, 26; one
Zürich canton extension request), Lugano commission reports on motions (5) and Illnau-Effretikon council minutes that
only refer to the written answer (2); 18 of the 20 'unclear' are Lausanne's replies to council resolutions adopted
after the interpellation answer. Among the review and failed rows the auditors also found the member's own text filed
as the answer (Zürich canton, Aarau, Locarno, Lugano, Lausanne, Jura, Pratteln), Basel-Stadt Ratsbüro reports and a
Solothurn RRB on another affair. These classes are the document-type filters above.

**Filter effect on the design sample** (`python -m gegenprobe.repair.adapters.audit_effect` ->
`results/repair/adapters/audit_effect.json`; the audited document of each row is frozen in
`.work/adapters/audit/frozen/`). The filters were written from these rows, so this shows that they catch the cases they
were designed on and remove no row the auditors judged an answer; it is **not** an unbiased precision estimate.
Re-judged with the current checks: **34 of the 34** verified 'no' rows now fail (extension_request 27,
parliament_report 5, minutes_reference 2); 17 of the 20 verified 'unclear' rows move to review (resolution_reply) and 3
stay verified (a Kriens template, a Bern city Vortrag on a share transfer, a Lausanne reply whose header does not
name the resolution); none of the 457 verified 'yes' rows moves (none of the 713 'yes' rows in the whole sample does); 13 of
the 17 review 'no' rows now fail.

**Fresh sample** (`python -m gegenprobe.repair.adapters.run --fresh-audit 300`, seed 20261111 ->
`.work/adapters/audit2/<BODY>.jsonl`, same fields as the first audit, each excerpt copied next to the sample;
`results/repair/adapters/audit2_sample.json`): **300** counted verified rows (exact date and date window), drawn after
the filters from the **6,390** that were not in the first audit, per parliament in proportion to its pool with at least
5 where the pool allows (18 parliaments; Zürich canton 78, Zürich city 52, St. Gallen 38, Ticino 29). Its blind verdicts,
not the design sample, estimate the precision of the counted tiers.

**What v2 could not show** (round 6 review): its rows carried the pipeline's `outcome`, `reason` and `proposed_action`
next to the text, so the auditor saw the verdict it was asked to check; its inputs stayed in WORK; the sample was
stratified by parliament but the interval treated it as simple random; there were no negative controls; and 8 of its 300
`date_ok` answers were "no" (5 Valais rows inside the 120-day window, a Jura and a Solothurn row).

**Blind audit v3** (`python -m gegenprobe.repair.adapters.audit3 draw`, seed 20261212; `results/repair/adapters/audit3/`):

- frame: the 6,209 counted rows outside the design audit (404 counted rows of the design audit excluded: the filters
  were written from them); strata = tier × action (8 strata), at least 12 per stratum, the rest in proportion to size:
  `exact_doc_date` fetch 67 / tag_answer 39 / extract_tag 13, `exact_any_printed_date` extract_tag 24 / tag_answer 14 /
  fetch 13, `date_window` tag_answer 16 / fetch 14 (`sample.json`: frame sizes and allocation);
- 60 decoys the pipeline did not count (30 review rows, 30 failed rows with extracted text), shuffled in with the 200;
- `packets.jsonl` (committed): per packet only an opaque id, the affair number, OPD's title, type and answer event dates,
  the path of the text (`.work/adapters/audit3/texts/`, the extracted text without any header, cut to the first 12,000 and
  last 3,000 characters when longer) and the sha256 of the full text (equal to the list's `text_sha256`) and of the text
  shown. No parliament, outcome, reason, action, tier or verified field. **Blind for Qwen, blind by instruction for
  Claude:** `text_sha256` is a join key. It equals the `text_sha256` column of the committed `adapters_<BODY>.tsv`
  lists, so anyone with the repository can look up a packet's tier and counted flag. The Qwen auditor received only the
  filled item prompt (metadata and text; no hash, no repository). The Claude auditor ran as an agent in a checkout, so
  its blindness rests on the instruction in `PROMPT.md` ("Read nothing else in the repository for this task");
- the key (packet id -> parliament, affair, stratum or decoy group) stays in WORK until both auditors are done; its
  sha256 is committed in `sample.json` (`score --final` then commits it). GitHub's server time for that commitment:
  commit `ce416a8` was pushed at 2026-10-11T00:56:16Z (repository activity API; `sample.json`
  `key_committed_github_time`), the verdicts and the key with `483dd2e` at 01:03:57Z. Local file times put the Qwen
  verdicts (which never depend on the key) before the push and the Claude verdicts and the scoring after it;
- `PROMPT.md`: the exact prompt, identical for both auditors (is_answer, date_ok within about 30 days, a verbatim quote);
- two independent auditors: a Claude agent and Qwen-SEA-LION-v4-32B-IT (another vendor, through the budget gateway,
  temperature 0; never an Apertus model). `score` reports per auditor the stratified precision (N_h/N weights, 95%
  interval from per-stratum Jeffreys posteriors), date_ok, whether each quote is found in the text, the decoys' yes
  rate, and the two auditors' agreement.
