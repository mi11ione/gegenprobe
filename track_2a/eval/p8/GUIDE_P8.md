# Annotation guide P8: what the documents of one affair print about its authors, dates, addressee, request, languages and recommendation

You label what the documents of one parliamentary affair PRINT. Never use outside knowledge, memory, the internet,
other packets, other annotators' files or anything in the repository other than this guide and your packet. You do not
know, and must not try to find out, which parliament, sample cell or hypothesis a packet belongs to.

## The packet

`.work/p8/packets/<id>.txt` holds:
- `=== DOCUMENT question ===`: the document that the data source links as the member's text (the intervention as lodged);
- `=== DOCUMENT answer ===`: the document it links as the executive's answer;
- `=== PAGE n ===` markers (text extracted from PDFs: expect odd line breaks, hyphenation, headers repeated on every page);
- `=== DATES ===`: every distinct date a date parser found in the two documents, each with a letter (D01, D02, ...),
  its ISO form and up to three printed lines where it occurs.

The links can be wrong: the "question" document may be something else and the "answer" document may not be the
executive's answer. Say so (`question_doc`, `answer_doc`) and label from whatever the two documents print.

## The file you write

One JSON file per packet: `.work/p8/ann/<A>/<id>.json` (`<A>` is your annotator code). Exactly these keys:

```json
{"id": "P8-001",
 "question_doc": "member_text|other|unclear",
 "answer_doc": "executive_answer|other|unclear",
 "people": [{"name": "Firstname Lastname", "kind": "person|group|committee|other_body",
             "role": "sole_author|first_signatory|joint_author|co_signatory|supporter|spokesperson|other",
             "doc": "question|answer", "page": 1, "quote": "verbatim, <= 200 characters"}],
 "dates": {"D01": ["signed"], "D03": ["answer_or_decision"]},
 "extra_dates": [{"date": "YYYY-MM-DD", "roles": ["lodged"], "doc": "question", "page": 1, "quote": "..."}],
 "addressed_body": {"value": "executive|executive_member_or_department|parliament|committee|administration|other|none_printed",
                    "doc": "question", "page": 1, "quote": "..."},
 "function": {"value": "mandate|examine_report|questions|direct_decision|other|unclear", "doc": "question", "page": 1, "quote": "..."},
 "instrument_named": {"value": "motion|postulate|interpellation|question|resolution|initiative|other|none", "doc": "question", "page": 1, "quote": "..."},
 "languages": {"question": ["de"], "answer": ["de"]},
 "recommendation": {"act": "on_referral|on_fulfilment|other|none_printed|not_applicable",
                    "value": "accept|reject|convert|partial|accept_and_write_off|none|not_applicable",
                    "fits": "one|several|none|not_applicable", "doc": "answer", "page": 2, "quote": "..."},
 "notes": "short reasons; anything ambiguous"}
```

Every `quote` is copied verbatim from the page you name (whitespace may differ; nothing else), at most 200 characters.
`doc`, `page` and `quote` may be omitted only where this guide says so (`none_printed`, `unclear`, `none`,
`not_applicable`). After writing each file run

    cd track_2a && PYTHONPATH=src:. .venv/bin/python -m eval.p8.annotate selfcheck <A> <id>

and fix everything it reports until it prints `OK`.

## 1. `question_doc`, `answer_doc`

- `member_text`: the question document is the intervention as its author(s) lodged it (the motion, postulate,
  interpellation or question text; it may carry a cover sheet or stamp). `other`: something else (an answer, minutes, a
  report, an annex). `unclear`: you cannot tell.
- `executive_answer`: the answer document is the executive's written answer to THIS intervention or its report on it
  (government, Regierungsrat, Staatsrat, Stadtrat or Gemeinderat as executive, Conseil d'État, Municipalité, Conseil
  communal where it is the executive, Consiglio di Stato, Municipio). `other`: something else (the intervention's own
  text, minutes, a committee report, the answer to another intervention). `unclear`: you cannot tell.

## 2. `people`: who lodged the intervention, and in what role

List every person or body that the documents print as author, signatory, supporter or spokesperson of THIS intervention,
in the order printed (the member's text first; add people the answer names in that role only if the member's text does
not print them). Do not list members of the executive who answer, officials, people mentioned in the content, or the
president who announces the intervention.

`name`: as printed, "Firstname Lastname" (or just "Lastname" when only that is printed); a body by its printed name
("SP-Fraktion", "Groupe socialiste", "Commissione della gestione"). `kind`: `person`, `group` (a parliamentary group,
party or "Fraktion / groupe / gruppo"), `committee` (a committee of the parliament), `other_body` (any other body).

`role`, exactly one per entry:
- `sole_author`: the only author printed ("Postulat von Anna Beispiel", "Interpellation de M. Jean Exemple",
  "Interrogazione di Andrea Esempio").
- `first_signatory`: the author designated first among several signatories: "Erstunterzeichner/in",
  "Hauptvorstösser/in", "premier signataire", "primo firmatario", or a form that sets one name apart: "X und
  Mitunterzeichnende", "X et consorts", "X e cofirmatari", "X, Y und Z (Erstunterzeichnende: X)".
- `joint_author`: one of several authors printed with equal standing, none designated first ("Interpellation A, B und C"
  with no cue that one of them leads; a list of signatures under the text with no designated first).
- `co_signatory`: printed as co-signing the text: "Mitunterzeichner/in", "Mitunterzeichnende:", "cosignataire(s)",
  "cofirmatari", names under "et consorts" when they are listed, further signatures after a designated first signatory.
- `supporter`: printed as supporting or backing it rather than co-signing it: "Unterstützer/in", "unterstützt von",
  "Unterstützung durch", "appuyé(e) par", "soutenu(e) par", "sostenuto/a da", signatures collected to reach a quorum
  or to request urgency.
- `spokesperson`: a person who signs or speaks for a group or committee that is the author ("im Namen der SP-Fraktion",
  "für die Kommission", "au nom du groupe", "per il gruppo", "Sprecher/in"). Then also list the group or committee
  itself, with `sole_author` (or `first_signatory` when several bodies are listed).
- `other`: a role of this intervention's authorship that fits none of the above (say which in `notes`).

`quote`: the printed words that show the name and its role (the name must appear in the quote).

## 3. `dates` and `extra_dates`: the dates of this intervention's procedure

Look at the `=== DATES ===` list. For every letter whose date marks a step of THIS intervention's own procedure, give
its role(s); leave out dates that belong to the content (dates of events the text talks about, laws, other affairs,
footers and print dates). A date may have several roles.

- `signed`: the date of the member's text: a place-and-date line ("Bern, 12. März 2024", "Lausanne, le 3 mai 2024"), a
  date next to the signature(s).
- `lodged`: printed as the date it was lodged, submitted, received or registered: "eingereicht am", "Eingang",
  "eingegangen", "déposé(e) le", "reçu(e) le", "enregistré(e)", "presentata il", "inoltrata il", "pervenuta il", a
  receipt stamp.
- `session_lodged`: printed as the sitting at which it was handed in or lodged ("eingereicht an der Sitzung vom",
  "déposé(e) lors de la séance du", "presentata nella seduta del").
- `cited`: the date by which a heading or the answer names the intervention without saying what happened on that day
  ("Interpellation vom 12. März 2024", "Motion du 3 mai 2024", "interrogazione del 4 aprile 2024",
  "Anfrage XY vom ...").
- `later_step`: a later step of parliament on it: announced, read out, taken note of, justified or developed
  ("begründet", "développé(e)"), debated, referred or transmitted ("überwiesen", "renvoyé(e)", "pris(e) en
  considération", "trasmessa"), urgency granted, deadline extended.
- `answer_or_decision`: the date of the executive's answer, decision or letter (RRB/ACE/risoluzione date, "Sitzung
  vom", "séance du", the answer's date line), or of parliament's decision on it.
- `other_procedural`: any other date of this intervention's procedure (publication, a deadline set for the answer, ...).

`extra_dates`: only if the documents print a date of this intervention's procedure that is NOT in the list (the parser
misses forms such as "12.3.24" or "2024-03-12"): give it as YYYY-MM-DD with its roles, `doc`, `page` and `quote`.

## 4. `addressed_body`: whom the intervention asks

The body the intervention asks to act or to answer. Judge by function, not by name: in some parliaments "Stadtrat" or
"Grand Conseil"/"Conseil communal" is the parliament, in others "Stadtrat"/"Conseil communal" is the executive; the
answer document shows which body is the executive.
- `executive`: the government or municipal executive as a body (Regierungsrat, Staatsrat, Stadtrat/Gemeinderat as
  executive, Kleiner Rat, Conseil d'État, Municipalité, Conseil communal as executive, Consiglio di Stato, Municipio).
  A text that "asks the parliament to invite the executive" ("Le Grand Conseil demande au Conseil d'État ...", "Der
  Grosse Rat lädt den Regierungsrat ein ...") asks the executive.
- `executive_member_or_department`: a named member of the executive, a department or directorate ("Frage an die
  Vorsteherin des Bildungsdepartements", "question au chef du DFJC", "al Capo Dicastero").
- `parliament`: the parliament itself, its bureau or presidency, asked to take a decision itself (e.g. a text that
  proposes that the council amend its own regulation or decide something directly).
- `committee`: a committee of the parliament.
- `administration`: the administration or a body outside the executive (an office, a public enterprise).
- `other`: someone else (say who in `notes`).
- `none_printed`: the documents print no addressee (no quote).

## 5. `function` and `instrument_named`: what the member's text asks for, and what it calls itself

`function` is the operative request of the member's text (read the request, not the title):
- `mandate`: charges or invites the executive to act: to draft or present a law, decree, regulation, credit or measure,
  or to take a measure ("Der Regierungsrat wird beauftragt, ... vorzulegen", "La Municipalité est chargée de présenter
  un projet ...", "Il Municipio è incaricato di elaborare un messaggio ...").
- `examine_report`: asks the executive to examine, study or check and to report or propose, without charging it to act
  ("wird gebeten zu prüfen und Bericht zu erstatten", "est invitée à étudier l'opportunité de ...", "è invitato a
  valutare e riferire").
- `questions`: asks questions for the executive to answer and requests no action.
- `direct_decision`: proposes a decision that the parliament itself takes on this text (a drafted article, an
  amendment of a regulation or law, a budget change put directly to the vote), not a request to the executive.
- `other`: a resolution, declaration, petition-like request or anything else.
- `unclear`: the documents do not let you tell (no quote).
If the text asks for several things, take the first that applies in this order: `direct_decision`, `mandate`,
`examine_report`, `questions`, `other`.

`instrument_named`: the name the documents give the instrument (Motion / motion / mozione → `motion`; Postulat /
postulat / postulato → `postulate`; Interpellation / interpellation / interpellanza → `interpellation`; Anfrage,
Kleine/Schriftliche Anfrage, Frage, question (écrite), interrogazione → `question`; Resolution / résolution / risoluzione
→ `resolution`; Initiative / initiative / iniziativa → `initiative`; any other name → `other`; no name printed → `none`,
without quote). Quote the word as printed.

## 6. `languages`

For each document, the language(s) its text is written in: `de`, `fr`, `it`, `rm`, `en`. List several only when
substantial parts (a paragraph or more) are in several languages (e.g. a bilingual document); a short phrase, a name or
a quoted law title in another language does not count. Use `[]` only when a document has no readable text.

## 7. `recommendation`: what the executive recommends to parliament

Read the answer document.
- `act`:
  - `on_referral`: the executive recommends how parliament should decide on taking up this motion or postulate:
    accept / adopt / refer / declare it relevant ("erheblich erklären", "überweisen", "entgegennehmen", "prendre en
    considération", "accogliere"), reject, convert (e.g. a motion into a postulate), partially, or accept and at once
    write off as fulfilled.
  - `on_fulfilment`: the document is the executive's report on a motion or postulate that parliament has already
    adopted or referred, and it asks parliament to approve that report, to adopt the act it proposes, or to write the
    affair off / close it ("Bericht und Antrag zur Abschreibung", "rapport-préavis en réponse au postulat", "classer",
    "abschreiben", "messaggio ... in risposta alla mozione").
  - `other`: a recommendation by another actor (a committee, the bureau) or on another object.
  - `none_printed`: the answer to a motion or postulate prints no recommendation (no quote).
  - `not_applicable`: an interpellation or question, or the answer document is not the executive's answer (no quote).
- `value`: the printed recommendation in these words: `accept`, `reject`, `convert`, `partial`, `accept_and_write_off`,
  `none` (could carry one, prints none), `not_applicable`.
- `fits`: how many `value` words fit the printed wording: `one`, `several` (it could be read as two of them; say which in
  `notes`), `none` (no word fits; say why in `notes`), `not_applicable`.
- `quote`: the printed recommendation (required for `on_referral`, `on_fulfilment`, `other`).

## 8. `notes`

One or two sentences on anything ambiguous: why you chose a role, a missing link, a document that is not what it is
linked as.

## Tie-break (A3 only)

You receive `.work/p8/a3/<id>.json` with the fields two annotators labelled differently (`fields`, `parts`) and their
two labels as X and Y (order random). Read the packet and this guide, then write `.work/p8/ann/A3/<id>.json` with `id`
and exactly the keys listed in `parts`, labelled by this guide (you may agree with X, with Y, or with neither). Run the
selfcheck with `A3`.
