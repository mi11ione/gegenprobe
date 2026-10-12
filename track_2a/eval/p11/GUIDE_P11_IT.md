# Annotation guide P11-IT: what the documents of one affair print about its authors, its request, its languages and the answer's date

You label what the documents of one parliamentary affair PRINT. Never use outside knowledge, memory, the internet, other
packets, other annotators' files or anything in the repository other than this guide, the guide sections it tells you to
read, and your packet. You do not know, and must not try to find out, which parliament, sample cell or hypothesis a
packet belongs to.

This guide defines nothing anew. It applies two existing guides to this packet:
- **P8** (`eval/p8/GUIDE_P8.md`): read its sections **1** (`question_doc`, `answer_doc`), **2** (`people`), **5**
  (`function`, `instrument_named`) and **6** (`languages`), and use them exactly as written. Ignore its sections 3, 4
  and 7 (dates, addressee, recommendation): this packet does not ask for them.
- **P1/P2** (`eval/gold2/GUIDE.md`, section *Definitions*): read the bullets **answer_present**, **answer_date** and
  **answer_date_lenient**, and use them exactly as written, for the answer document of this packet.

"The executive" includes the Consiglio di Stato (cantonal government) and the Municipio (communal executive); the
parliament is the Gran Consiglio or the Consiglio comunale.

## The packet

`.work/p11/packets/IT-<nnn>.txt` has the layout of a P8 packet:
- `=== DOCUMENT question ===`: the document the data source links as the member's text;
- `=== DOCUMENT answer ===`: the document it links as the executive's answer;
- `=== PAGE n ===` markers (text extracted from PDFs: expect odd line breaks, hyphenation, headers repeated on every
  page);
- `=== DATES ===`: every distinct date a date parser found in the two documents (letters D01, D02, ...). You do not
  label date roles in this packet; the list only helps you find printed dates.

The links can be wrong: the "question" document may be something else and the "answer" document may not be the
executive's answer. Say so (`question_doc`, `answer_doc`) and label from whatever the two documents print.

## The file you write

One JSON file per packet: `.work/p11/ann/<A>/IT-<nnn>.json` (`<A>` is your annotator code). Exactly these keys:

```json
{"id": "IT-001",
 "question_doc": "member_text|other|unclear",
 "answer_doc": "executive_answer|other|unclear",
 "people": [{"name": "Firstname Lastname", "kind": "person|group|committee|other_body",
             "role": "sole_author|first_signatory|joint_author|co_signatory|supporter|spokesperson|other",
             "doc": "question|answer", "page": 1, "quote": "verbatim, <= 200 characters"}],
 "function": {"value": "mandate|examine_report|questions|direct_decision|other|unclear", "doc": "question", "page": 1, "quote": "..."},
 "instrument_named": {"value": "motion|postulate|interpellation|question|resolution|initiative|other|none", "doc": "question", "page": 1, "quote": "..."},
 "languages": {"question": ["it"], "answer": ["it"]},
 "answer_present": "yes|no|oral|unclear",
 "answer_date": "YYYY-MM-DD",
 "role": "decision|dispatch",
 "answer_date_page": 1,
 "answer_date_quote": "verbatim text from that page of the ANSWER document containing the date",
 "answer_date_lenient": [],
 "notes": "short reasons; anything ambiguous"}
```

- `answer_date`, `role`, `answer_date_page` and `answer_date_quote` are `null` when no answer date is printed (and
  always when `answer_present` is not `yes`). `answer_date_page` is a page of the **answer** document.
- Every `quote` is copied verbatim from the page you name (whitespace may differ; nothing else), at most 200 characters;
  a `people` quote contains the name's last word. `doc`, `page` and `quote` may be omitted only where the P8 guide says
  so (`unclear`, `none`). An affair whose documents print no author gets `"people": []`.

After writing each file run

    cd track_2a && PYTHONPATH=src:. .venv/bin/python -m eval.p11.annotate selfcheck <A> IT-<nnn>

and fix everything it reports until it prints `OK`. Run no other command.

## Tie-break (A3 only)

You receive `.work/p11/a3/IT-<nnn>.json` with the fields two annotators labelled differently (`fields`, `parts`) and
their two labels as X and Y (order random). Read the packet and this guide (with the sections it names), then write
`.work/p11/ann/A3/IT-<nnn>.json` with `id` and exactly the keys listed in `parts`, labelled by this guide (you may agree
with X, with Y, or with neither). Run the selfcheck with `A3`.
