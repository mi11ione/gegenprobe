# Annotation guide P5: questions, answers, people, recommendation, reasoning

You label what the documents of ONE parliamentary affair PRINT. Never use outside knowledge, metadata or memory. Each
packet holds two documents, marked `=== DOCUMENT question ===` (the member's text as lodged: interpellation, question,
motion, postulate) and `=== DOCUMENT answer ===` (the executive's answer or report), with `=== PAGE n ===` markers. The
text is extracted from PDFs: expect line breaks in odd places, hyphenation, headers and footers inside the text.

Write one JSON file per affair (UTF-8) with exactly the keys below. Every location is given as a **verbatim quote** from
the page you name; code checks each quote against the page text (whitespace differences, including line breaks, are
ignored; everything else must match exactly, including punctuation, hyphens and typos). Quotes must be unique enough to be
found: when a short quote occurs twice on the page, make it longer. Run the self-check command you were given after
writing each file and fix every error it reports.

## A span

A *span* is a piece of text, possibly over several pages, given as

```json
{"doc": "question" | "answer",
 "page": 1, "start": "first 20-60 characters of the span, verbatim",
 "end_page": 2, "end": "last 20-60 characters of the span, verbatim"}
```

`start` must be the very beginning of the span and `end` its very end (the span ends where the `end` quote ends). A span
on one page has `end_page` = `page`. The `end` quote must lie at or after the `start` quote. For a span shorter than 60
characters, `start` and `end` may be the same text.

## The keys

```json
{"affair_id": 123,
 "questions": [{"n": 1, "span": SPAN}, ...],
 "question_style": "enumerated" | "single" | "running_text" | "none",
 "answer_style": "per_question" | "global" | "mixed" | "no_answer",
 "answers": [{"n": 1, "span": SPAN | null, "joint_with": []}, ...],
 "submitter": {"name": "Firstname Lastname", "doc": "question", "page": 1, "quote": "..."} | null,
 "co_signatories": [{"name": "...", "doc": "...", "page": 1, "quote": "..."}, ...],
 "recommendation": "accept" | "reject" | "partial" | "convert" | "none" | "not_applicable",
 "recommendation_quote": {"doc": "answer", "page": 3, "quote": "..."} | null,
 "reasoning": SPAN | null,
 "notes": "short reasons; anything ambiguous"}
```

### questions, question_style
- The questions **the member asks the executive in the question document**, in the order printed.
- `enumerated`: the member's text lists its questions as separate items (numbers "1.", "1)", "Frage 1", letters "a)",
  roman numerals, or bullets/dashes). Give one entry per item, `n` = 1, 2, 3, … in printed order (also for letters or
  bullets). The span of item n starts at its marker (the number, letter or bullet itself) and ends at the end of its
  text, i.e. before the next item's marker, or, for the last item, at the end of its last sentence (not the signature,
  date or closing line that follows).
- An item that is not a question but part of the list (e.g. "3. Der Regierungsrat wird gebeten …") still counts: label
  every item of the enumerated list addressed to the executive.
- Sub-items (1a, 1b under 1) belong to their parent item; do not number them separately.
- `single`: the member asks exactly one question or makes one request without enumeration. Give one entry, n = 1, whose
  span is that question sentence (or the request paragraph, e.g. the motion's demand "Der Regierungsrat wird beauftragt
  …").
- `running_text`: the member asks several questions (or makes several requests) in running text, without separating
  them into items. `questions` = [] (no split is guessed).
- `none`: no question or request text is printed (e.g. the document is only a cover sheet). `questions` = [].
- Numbers inside the running text that do not start a list item (e.g. "zur Frage 4 schrieb der Regierungsrat") are not
  items. A list elsewhere (e.g. a list of facts or figures in the explanation, not addressed as questions/requests) is not
  the question list.

### answers, answer_style
- Where in the **answer document** the executive replies to each question. One entry per question in `questions`, same
  `n`.
- `per_question`: the answer replies question by question (headings like "Zu Frage 1", "Ad 1", "Réponse à la question
  1", "Risposta 1", a repeated question followed by its answer, or numbered answer paragraphs). The span of answer n
  starts at the first word of the executive's reply to question n and ends at the end of that reply (before the next
  answer heading or repeated question). **Exclude** a heading like "Zu Frage 1:" and any repeated question text: the span
  is the reply text only.
- When one passage answers several questions together ("Zu den Fragen 2 und 3"), give that passage as the span of each
  of them and list the other numbers in `joint_with` (e.g. for n=2: `"joint_with": [3]`; for n=3: `[2]`).
- `global`: the executive answers the questions in running text without saying which part replies to which question.
  Give `span: null` for every question. (Do not guess a split.)
- `mixed`: some questions are answered separately and others not: spans where the document makes the link explicit, null
  elsewhere.
- `no_answer`: the answer document does not contain the executive's reply (e.g. it is another kind of document). All
  answer spans null.
- If `question_style` is `single`, answer n=1 is the executive's whole substantive reply to it (the same text as
  `reasoning`, see below) when the answer document replies to it; `answer_style` is then `per_question`.

### submitter, co_signatories
- `submitter`: the person who lodged the affair (first signatory, "Erstunterzeichner(in)", "Interpellant(in)",
  "Motionär(in)", "eingereicht von", "déposé par", "presentata da", the first name of the signature block, or the person
  named in the title "Interpellation <Name> betreffend …"). Prefer where the question document prints it; use the answer
  document only if the question document prints no name. `name` = "Firstname Lastname" exactly as printed (if only the
  surname is printed: only the surname). `quote` = a short verbatim piece (≤ 120 characters) of the page that contains the
  name as printed. A party group or committee as sole author: its name. Nothing printed: null.
- `co_signatories`: every further person printed as co-signatory or co-author (signature list, "Mitunterzeichnende",
  "cosignataires", "cofirmatari", a second name in "Motion A und B"), each with its own quote. Not: names of people merely
  mentioned in the text, members of the executive, the secretary or the chancellor signing the answer, "und Konsorten"
  without names. [] if none.

### recommendation
- The executive's recommendation to parliament on what to do with this affair, only as printed in the **answer
  document**: `accept` (accept/refer/declare the motion or postulate, "erheblich erklären", "überweisen", "entgegennehmen",
  "accepter", "prendre en considération", "accogliere"), `reject` (reject, not refer, "nicht erheblich erklären",
  "abzulehnen", "rejeter", "respingere"), `partial` (accept part, reject part, or "teilweise erheblich"), `convert`
  (accept it in another form, e.g. motion as postulate), `none` (an answer to a motion/postulate that prints no
  recommendation, including a proposal only to write it off), `not_applicable` (interpellations, questions, and any affair
  whose answer document is not the executive's answer).
- `recommendation_quote`: the sentence that states it (≤ 200 characters, verbatim) or null for none/not_applicable.

### reasoning
- The span of the executive's **substantive answer text** in the answer document: from the first sentence in which the
  executive itself speaks about the matter (including preliminary remarks such as "Vorbemerkung", "Considérations
  générales", "Osservazioni introduttive") to the last sentence of its reply, **before** the closing part (the
  recommendation formula, "Im Namen des Regierungsrates", "Mit freundlichen Grüssen", "Ainsi délibéré", "Per il Consiglio
  di Stato", signatures, distribution list, annexes).
- **Exclude** the letterhead, title, address block, the introductory sentence that only says the executive was asked to
  answer, and a full reprint of the member's text at the start. Repeated questions *between* answers stay inside the
  span (it is one contiguous span from the first to the last sentence of the reply).
- null if the answer document contains no executive reply.

## Notes
Use `notes` for doubts (e.g. "answers 3 and 4 not separated", "list items are demands, not questions"). Do not leave keys
out; use null / [] as defined above.
