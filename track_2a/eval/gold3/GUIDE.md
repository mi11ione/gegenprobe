# Annotation guide: whole parliamentary affairs (P3 gold set)

You label what the documents of one affair PRINT. Never use outside knowledge, metadata or memory. Each packet holds the
affair's documents, each marked `=== DOCUMENT question ===` (the member's text as lodged) or `=== DOCUMENT answer ===` (the
executive's answer or decision), with `=== PAGE n ===` markers; text is extracted from PDFs (expect line breaks in odd places).

Write one JSON file per affair with exactly these keys (use null / [] when the documents do not print it):

```json
{"affair_id": 123,
 "number": "2021.RRGR.388" | null, "number_doc": "question"|"answer"|null, "number_page": 1|null, "number_quote": "…"|null,
 "affair_type": "interpellation"|"motion"|"postulate"|"question"|"resolution"|"other"|null, "affair_type_quote": "…"|null,
 "submitter": "Firstname Lastname" | null, "submitter_doc": …, "submitter_page": …, "submitter_quote": "…",
 "co_signatories": ["Firstname Lastname", …],
 "addressed_body": "executive"|"parliament"|"committee"|"administration"|null, "addressed_body_quote": "…"|null,
 "submitted": "YYYY-MM-DD"|null, "submitted_doc": …, "submitted_page": …, "submitted_quote": "…", "submitted_lenient": [],
 "answer_present": "yes"|"no"|"oral"|"unclear",
 "answer_date": "YYYY-MM-DD"|null, "role": "decision"|"dispatch"|null, "answer_date_doc": …, "answer_date_page": …,
 "answer_date_quote": "…", "answer_date_lenient": [],
 "decision_number": "879/2024"|null,
 "recommendation": "accept"|"reject"|"convert"|"partial"|"none"|"not_applicable",
 "related_affairs": ["2020.RRGR.12", …],
 "notes": "short reasons, anything ambiguous"}
```

## Field definitions
- **number**: the affair's own number as printed (e.g. "2021.RRGR.388", "M 123/2024", "Interpellation 24.512"). Copy the
  number part only. If several documents print it, give one occurrence.
- **affair_type**: the kind of intervention as the documents name it: interpellation (Interpellation, interpellanza),
  motion (Motion, mozione), postulate (Postulat, postulato), question (Anfrage, Kleine/Schriftliche Anfrage, Frage,
  question écrite, interrogazione), resolution (Resolution, résolution, risoluzione), other. Quote the word.
- **submitter**: the person who lodged it (first signatory / "Erstunterzeichner" / "Hauptvorstösser" / "déposé par" /
  "presentata da"). Write "Firstname Lastname" as printed (if only the surname is printed, write only the surname).
  A party group or committee as sole author: write its name. Quote where it is printed.
- **co_signatories**: further signatories printed (names only, any order). [] if none printed.
- **addressed_body**: whom the intervention addresses or asks: executive (Regierungsrat, Stadtrat, Gemeinderat as
  executive, Conseil d'État, Municipalité, Consiglio di Stato, Municipio, Bundesrat), parliament, committee,
  administration. Quote the phrase that shows it (e.g. "Der Regierungsrat wird beauftragt", "au Conseil d'Etat",
  "Il Municipio è invitato"). null if not recognisable.
- **submitted**: the date the intervention was lodged, as printed ("Eingereicht am", "déposée le", "presentata il", a dated
  submission line, or the date of the member's text). Not a session date, not the answer date.
- **answer_present / answer_date / role / decision_number**: exactly as in the P1/P2 guide: the executive's decision date
  printed in the answer (RRB … vom, Sitzung vom, séance du, risoluzione … del) → role decision; else the dispatch/letter
  date of the answer → role dispatch. Never a footer, print or version date. If the answer is not in the documents,
  answer_present "no" and answer_date null.
- **recommendation**: the executive's recommendation to parliament, only if printed: accept, reject, convert (e.g. motion
  into postulate), partial; none = the document could carry one but prints none (including "write off as fulfilled");
  not_applicable = interpellations, questions, or no executive answer in the documents.
- **related_affairs**: numbers of OTHER affairs the documents cite (not the affair's own number).

Quotes must be copied verbatim from the page you name (≤ 200 characters); code checks them. Run the self-check command you
were given after writing each file and fix what it reports.
