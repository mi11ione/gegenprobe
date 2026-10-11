# Annotation guide P10: who lodged the intervention, and in what role

You label what the documents of one parliamentary affair PRINT about who lodged it. Never use outside knowledge,
memory, the internet, other packets, other annotators' files or anything in the repository other than this guide and
your packet. You do not know, and must not try to find out, which parliament, sample cell or hypothesis a packet
belongs to.

This guide reuses, word for word, the definitions of the P8 guide (eval/p8/GUIDE_P8.md §1 and §2); only the packet,
the file and the tie-break are P10's.

## The packet

`.work/p10/packets/<id>.txt` holds:
- `=== DOCUMENT question ===`: the document that the data source links as the member's text (the intervention as lodged);
- `=== DOCUMENT answer ===`: the document it links as the executive's answer;
- `=== PAGE n ===` markers (text extracted from PDFs: expect odd line breaks, hyphenation, headers repeated on every page).

The links can be wrong: the "question" document may be something else and the "answer" document may not be the
executive's answer. Say so (`question_doc`, `answer_doc`) and label from whatever the two documents print.

## The file you write

One JSON file per packet: `.work/p10/ann/<A>/<id>.json` (`<A>` is your annotator code). Exactly these keys:

```json
{"id": "P10-001",
 "question_doc": "member_text|other|unclear",
 "answer_doc": "executive_answer|other|unclear",
 "people": [{"name": "Firstname Lastname", "kind": "person|group|committee|other_body",
             "role": "sole_author|first_signatory|joint_author|co_signatory|supporter|spokesperson|other",
             "doc": "question|answer", "page": 1, "quote": "verbatim, <= 200 characters"}],
 "notes": "short reasons; anything ambiguous"}
```

Every `quote` is copied verbatim from the page you name (whitespace may differ; nothing else), at most 200 characters,
and contains the name's last word. An affair whose documents print no author gets `"people": []`. After writing each
file run

    cd track_2a && PYTHONPATH=src:. .venv/bin/python -m eval.p10.annotate selfcheck <A> <id>

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

## 3. `notes`

One or two sentences on anything ambiguous: why you chose a role, a missing link, a document that is not what it is
linked as.

## Tie-break (A3 only)

You receive `.work/p10/a3/<id>.json` with two `people` lists that two annotators wrote for the same packet, as
`people_X` and `people_Y` (order random). Read the packet and this guide, then write `.work/p10/ann/A3/<id>.json` with
exactly the keys `id`, `people` and `notes`, labelled by this guide (you may agree with X, with Y, or with neither).
Run the selfcheck with `A3`.
