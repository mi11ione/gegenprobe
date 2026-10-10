# Annotation guide: Swiss parliamentary documents (held-out gold set)

You label what a document itself PRINTS. Never use outside knowledge, metadata or memory. Each document is a page-delimited
text file (`=== PAGE n ===` markers) extracted from a PDF of a Swiss parliament (federal, cantonal or municipal) in German,
French or Italian; some are OCR of scans (expect OCR noise).

For each document write one JSON file with exactly these keys:

```json
{"doc_id": 123,
 "answer_present": "yes" | "no" | "oral" | "unclear",
 "answer_date": "YYYY-MM-DD" | null,
 "role": "decision" | "dispatch" | null,
 "answer_date_page": 1 | null,
 "answer_date_quote": "verbatim text from that page containing the date" | null,
 "answer_date_lenient": ["YYYY-MM-DD", ...],
 "decision_number": "e.g. 879/2024" | null,
 "recommendation": "accept" | "reject" | "convert" | "partial" | "none" | "not_applicable",
 "recommendation_quote": "verbatim" | null,
 "notes": "short reason, anything ambiguous"}
```

## Definitions
- **answer_present**: `yes` if this document contains the executive's (government's: Bundesrat, Regierungsrat,
  Conseil d'État, Conseil-exécutif, Consiglio di Stato, Stadtrat, Gemeinderat, Municipalité, Municipio, Conseil communal…)
  answer to, or decision on, the parliamentary affair. A text that only asks (motion, postulate, interpellation, question
  as lodged by members) is `no`, even if it has an empty "RRB-Nr.: … vom" template field. A parliamentary
  committee report or minutes page that does not contain the executive's answer is `no`. `oral` if the document says the
  answer was given orally. `unclear` only if you truly cannot tell.
- **answer_date**: the date of the executive's answer AS PRINTED in this document.
  - Prefer the **decision** date: the date the executive decided/adopted it, e.g. "RRB-Nr.: 879/2024 vom 28. August 2024",
    "Auszug aus dem Protokoll des Regierungsrates … Sitzung vom 3. Juli 2024", "Regierungsratsbeschluss vom …",
    "N° ACE … du …", "Ainsi adopté en séance du …", "Arrêté du Conseil-exécutif … du …", "RG n. … del …", "ris. mun. … del …".
    Then `role` = "decision".
  - If no decision date is printed, use the **dispatch** date of the answer: the place-date line or signature date of the
    answer letter (e.g. "Basel, 3. März 2025", "Lausanne, le 12 mai 2023", "Bellinzona, 4 aprile 2022"). Then `role` = "dispatch".
  - NEVER a footer/print/version/filing date ("Letzte Bearbeitung", "Version", "Dok.-Nr.", "Druck", page footers), never
    the date the members lodged the affair ("Eingereicht am", "déposé le", "presentata il"), never dates of laws, other
    affairs, sessions or events mentioned in the text.
  - If answer_present is not `yes`, answer_date is null.
  - `answer_date_quote` must be copied VERBATIM from the page given in `answer_date_page` (a short line or phrase,
    max 200 characters, containing the date). It is checked by code; whitespace differences are tolerated, nothing else.
- **answer_date_lenient**: other printed dates that are also defensible as this answer's date (e.g. the letter date next to
  the RRB date). Usually empty.
- **decision_number**: the executive's decision number if printed (RRB-Nr., ACE n°, RG n., ris. mun.), else null.
- **recommendation**: what the executive recommends to parliament about the affair, only if printed in this document:
  `accept` (annehmen / erheblich erklären / accepter / accogliere), `reject` (ablehnen / rejeter / respingere), `convert`
  (e.g. motion into postulate), `partial` (partly accept), `none` (no recommendation printed). `not_applicable` for
  interpellations, questions and documents that cannot carry one (e.g. a member's question text). Quote it if not none/n.a.

## Procedure
1. Read the whole document text before answering.
2. Decide answer_present first, then the date, then the rest.
3. Write the JSON file, then run the self-check command you were given; fix any reported error (usually a quote that is not
   verbatim or the wrong page) and re-run until it prints OK.
