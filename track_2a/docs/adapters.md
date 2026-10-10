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

## The common interface

Every adapter answers one question per OPD affair (`base.py`): **candidates** (where the answer may be) -> **text** (OPD's
stored text, or the file fetched politely through `gegenprobe.net` and extracted with pdftotext, tesseract deu+fra+ita
for image-only scans) -> **checks**:

| check | passes when |
|---|---|
| identity | the affair number is printed, in the parliament's own spellings (`GR Nr. 2009/039` for 2009/39, `P 517` for 2025P 517, `(3320)` for QE 3320, ...), or the OPD title is printed near the top (as one string, or 80% of its content words) |
| heading | the parliament's answer formula is printed ("Der Stadtrat beantwortet die Anfrage wie folgt", "Antwort der Regierung vom", "Réponse écrite du Conseil d'État", "Il Municipio risponde", ...). Question phrases ("prié de répondre", "um Beantwortung", "Souhait d'une réponse écrite") and council minutes ("prend acte de la réponse") are excluded and tested |
| date | the document's own date (header, or the place-date line) **equals** one of OPD's written-answer event dates (`eq`), or an executive event of the affair (`eq_gov`, Solothurn: OPD's "Beantwortet" event is the committee's, the government's "Antrag" event carries the answer date), or some date printed in the document equals an OPD answer event (`anywhere`); a documented per-parliament window (below); where OPD's answer events carry no date (Jura), the document is dated within a year after OPD's submission event (`after_submission`) |

**Verified** = identity and heading and date. **Review** = identity and heading but the date is off (within 14 days:
`near`, or further: `differs`), or identity and the source itself types the document as the answer but no heading
matched. **Failed** = a typed reason: `no_candidate` (the source lists no answer document), `not_found`,
`robots_disallowed`, `robots_unreachable`, `http_404`, `empty_text`, `oral_pointer` (VS: the answer document points to
an oral answer), `translation_stub`, `identity_fail`, `heading_fail`. Every affair keeps its outcome in
`results/repair/adapters/<BODY>.json`; only verified and review rows go into `repair_<BODY>.tsv` (columns of
`repair/common.py`; `check_detail` carries route, identity and date class, sha256, extractor and a quote of at most 200
characters). Document texts and PDFs stay in WORK and are never committed.

**Actions.** `fetch`: the parliament publishes the answer and OPD does not hold it. `relink`: OPD holds the same file
elsewhere. `tag_answer`: **OPD already holds the answer, with text, on the affair**, under a generic name (the
intervention's title, a file name, "Vorstoss - V2017.154") and in a wording the census lexicon does not list, so neither
OPD's users nor the census see it as the answer; the fix is to set the document's category. `extract_tag`: OPD holds the
answer file on the affair without usable text; extract (text layer or OCR) and tag it.

Per-parliament date rules (event − document date, days), each from the parliament's practice: Zürich city 0 to +15
(before about 2012 OPD's "Stadtrat, Antwort" event is the dispatch a week or two after the decision; pilot of 200: 150
equal, +1, +7 ×13, +8 ×3, +14, +15); Neuchâtel −1 to +1 ("transmise aux membres du Grand Conseil le …"); Frauenfeld −3
to +3 (signed around OPD's date); Kriens −70 to 0 (OPD's answer event carries the submission date); Valais −366 to 0
(OPD's answer event carries the deposit date; the answer's own date follows). Everywhere else: equal dates only.

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
| Ticino canton (TI) | 1 (+775 image-only) | **Word/PDF route blocked**: the answer files (`allegato.php`, e.g. `r100.19.doc`) are disallowed by robots.txt; the image-only answers are OCR'd from OPD's own copy on files.openparldata.ch | www4.ti.ch: `/user_librerie/php/GC/allegato.php` **disallowed** |

Every other parliament with target affairs runs the generic in-OPD adapter (`inopd.py`).

## Results

All 12,150 target affairs (10,800 `absent` + 1,350 `image_only`) were run; outputs in `results/repair/adapters/`
(`summary.json`, per body `<BODY>.json`, `repair_<BODY>.tsv`, `repair_<BODY>_review.tsv`). OPD docs snapshot of 10 Oct
2026; parliament sites fetched 10-11 Oct 2026.

**Coverage.** Verified: **7,191** affairs, **6,330** of the 10,800 written answers that had no answer document in OPD and
**861** of the 1,350 image-only answers (a text copy verified). Deterministic routes now propose repairs for **10,298 of
16,749** interventions without answer text (3,107 before); **4,470** written answers still need adapters. Another **725**
rows are review (501 absent, 224 image-only): listed, not counted.

**By action:** `fetch` 3,623 (Zürich canton, St. Gallen, Solothurn, Luzern, Valais, Aarau), `tag_answer` 2,380 and
`extract_tag` 1,188. **2,380 answers are already in OPD with text** on the affair (`tag_answer`: Zürich city 1,417,
Neuchâtel 239, Zürich canton 161 Vorlagen, Frauenfeld 131, Vaud 95, ...): the census lexicon (`census/defs.py`, frozen) does not recognise their
wording, so they are counted as missing. **By date check:** equal 4,992, executive event 214 (Solothurn), any printed
date equal 1,307, documented window 301, latest printed date in window 95 (Zürich city before 2012, no header date),
after submission 282 (Jura: OPD's answer events carry no date). Identity: the affair number for most bodies; the title for
Ticino (729), Jura (288), Frauenfeld (145), Locarno (127), Aarau (61); the source's own document label for Valais (132).

`python -m gegenprobe.repair.adapters.run --table`:

| parliament | targets (absent + image-only) | verified | of which tag/extract (in OPD) | review | failed: top reasons |
|---|---|---|---|---|---|
| Zürich (canton) (ZH) | 3,030 | 2,193 | 162 | 97 | no_candidate 740 |
| Zürich (city) (261) | 1,457 | 1,417 | 1,417 | 21 | heading_fail 19 |
| St. Gallen (canton) (SG) | 1,018 | 1,013 | 0 | 1 | http_404 2, no_candidate 2 |
| Ticino (canton) (TI) | 776 | 729 | 729 | 36 | http_404 2, identity_fail 7, no_candidate 2 |
| Neuchâtel (canton) (NE) | 721 | 239 | 239 | 12 | no_candidate 470 |
| Jura (canton) (JU) | 657 | 357 | 357 | 25 | identity_fail 15, no_candidate 260 |
| Winterthur (city) (230) | 629 | 0 | 0 | 0 | no_candidate 629 |
| Valais (canton) (VS) | 392 | 195 | 0 | 87 | empty_text 33, http_404 15, no_candidate 13 |
| Locarno (city) (5113) | 299 | 127 | 127 | 115 | http_404 9, identity_fail 5, no_candidate 43 |
| Münsingen (city) (616) | 269 | 0 | 0 | 0 | identity_fail 1, no_candidate 268 |
| Illnau-Effretikon (city) (296) | 222 | 33 | 33 | 10 | identity_fail 2, no_candidate 177 |
| Solothurn (canton) (SO) | 212 | 210 | 0 | 1 | identity_fail 1 |
| Lugano (city) (5192) | 201 | 7 | 7 | 7 | no_candidate 187 |
| Pratteln (city) (2831) | 200 | 0 | 0 | 16 | no_candidate 184 |
| Frauenfeld (city) (4566) | 194 | 145 | 145 | 18 | heading_fail 9, identity_fail 21, no_candidate 1 |
| Aarau (city) (4001) | 177 | 74 | 4 | 15 | identity_fail 5, no_candidate 83 |
| Liestal (city) (2829) | 167 | 0 | 0 | 63 | identity_fail 3, no_candidate 101 |
| Lausanne (city) (5586) | 163 | 24 | 24 | 42 | identity_fail 4, no_candidate 93 |
| Collombey-Muraz (municipality) (6152) | 130 | 0 | 0 | 0 | no_candidate 130 |
| Monthey (city) (6153) | 119 | 29 | 29 | 4 | no_candidate 86 |
| Vaud (canton) (VD) | 112 | 95 | 95 | 9 | no_candidate 8 |
| Bern (city) (351) | 106 | 39 | 39 | 1 | no_candidate 66 |
| Luzern (canton) (LU) | 105 | 104 | 0 | 1 | - |
| Basel-Landschaft (canton) (BL) | 104 | 2 | 2 | 0 | no_candidate 102 |
| Basel-Stadt (canton) (BS) | 103 | 1 | 1 | 2 | no_candidate 100 |
| Kriens (city) (1059) | 75 | 71 | 71 | 2 | no_candidate 2 |
| Kreuzlingen (city) (4671) | 56 | 0 | 0 | 4 | http_404 29, no_candidate 23 |
| Adliswil (city) (131) | 52 | 2 | 2 | 20 | empty_text 20, http_404 10 |
| Wetzikon (ZH) (city) (121) | 51 | 0 | 0 | 0 | no_candidate 51 |
| Bellinzona (city) (5002) | 50 | 0 | 0 | 49 | no_candidate 1 |
| Thurgau (canton) (TG) | 50 | 34 | 34 | 15 | identity_fail 1 |
| Fribourg (canton) (FR) | 43 | 7 | 7 | 0 | http_400 1, identity_fail 1, no_candidate 34 |
| Dübendorf (city) (191) | 37 | 17 | 17 | 17 | identity_fail 3 |
| Zofingen (city) (4289) | 34 | 6 | 6 | 21 | identity_fail 1, no_candidate 6 |
| Vernier (city) (6643) | 32 | 0 | 0 | 0 | no_candidate 32 |
| Arbon (city) (4401) | 31 | 21 | 21 | 0 | identity_fail 3, no_candidate 7 |
| Interlaken (city) (581) | 26 | 0 | 0 | 14 | no_candidate 12 |
| Obwalden (canton) (OW) | 12 | 0 | 0 | 0 | no_candidate 12 |
| Uster (city) (198) | 11 | 0 | 0 | 0 | no_candidate 11 |
| Nidau (municipality) (743) | 6 | 0 | 0 | 0 | no_candidate 6 |
| Thun (city) (942) | 5 | 0 | 0 | 0 | no_candidate 5 |
| Schlieren (city) (247) | 4 | 0 | 0 | 0 | no_candidate 4 |
| Appenzell Ausserrhoden (canton) (AR) | 2 | 0 | 0 | 0 | no_candidate 2 |
| Graubünden (canton) (GR) | 2 | 0 | 0 | 0 | no_candidate 2 |
| Liechtenstein (Landtag) (LIE) | 2 | 0 | 0 | 0 | no_candidate 2 |
| Schaffhausen (canton) (SH) | 2 | 0 | 0 | 0 | no_candidate 2 |
| Wädenswil (city) (293) | 1 | 0 | 0 | 0 | no_candidate 1 |
| Neuchâtel (city) (6458) | 1 | 0 | 0 | 0 | no_candidate 1 |
| Opfikon (city) (66) | 1 | 0 | 0 | 0 | no_candidate 1 |
| Genève (canton) (GE) | 1 | 0 | 0 | 0 | no_candidate 1 |

Why the large remainders fail: Zürich canton 740 `no_candidate` are mostly postulates (524) and motions (192) whose
Kantonsrat record lists no government document (OPD's "answer" event there is a step of the council's own procedure);
Neuchâtel 470 and Pratteln are answers given orally in the session; Winterthur (629), Pratteln, Liestal and
Illnau-Effretikon sit on unreachable hosts; Münsingen (269) and Collombey-Muraz keep answers only in session minutes; Jura
260 have no answer file in OPD and the intervention pages are disallowed.


## Robots.txt: one correction to the network layer

`gegenprobe.net.allowed()` uses Python's `urllib.robotparser`, which applies the **first** matching rule of a group; RFC
9309 says the **longest** match wins. www4.ti.ch lists `Allow: /` before `Disallow: /user_librerie/php/GC/allegato.php`,
so `net` allowed a path the site disallows. During development three Ticino answer files (`allegato.php?allid=115005,
119023, 137701`) were fetched this way before the check below existed; they were deleted from WORK and no row uses them.
Every adapter request now passes `adapters/robots.py` first (RFC 9309 longest match, `*` and `$`, allow wins ties) and
then `net.get`, so a URL is fetched only when both agree; an audit of every URL the adapters requested found no other
disallowed path. `net.py` is locked (LOCK2); the same fix belongs there in a future version.

## Audit

`.work/adapters/audit/<BODY>.jsonl`: per adapter a stratified sample of 30 (20 verified, 6 review, 4 failed with text;
seed 20261011), each row with OPD's title, type and answer dates, the proposed action, the source URL and the path of
the extracted text, for blind auditors ("Is this document the government's written answer to this affair?").
