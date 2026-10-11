# Annotation guide FED: what the texts of one federal affair print about its author, its request, its languages and the answer's date

You label what the texts of one parliamentary affair PRINT. Never use outside knowledge, memory, the internet, other
packets, other annotators' files or anything in the repository other than this guide, the two guide sections it tells
you to read, and your packet. You do not know, and must not try to find out, which affair, sample cell or hypothesis a
packet belongs to.

This guide does not define anything anew. It applies two existing guides to a new kind of packet:
- **P8** (`eval/p8/GUIDE_P8.md`): read its sections **1** (`question_doc`, `answer_doc`), **2** (`people`), **5**
  (`function`, `instrument_named`) and **6** (`languages`), and use them exactly as written. Ignore its sections 3, 4
  and 7 (dates, addressee, recommendation): this packet does not ask for them.
- **P1/P2** (`eval/gold2/GUIDE.md`, section *Definitions*): read the bullets **answer_present**, **answer_date** and
  **answer_date_lenient**, and use them exactly as written, for the answer document of this packet.

In both, "the executive" includes the federal executive: the Federal Council (Bundesrat, Conseil fédéral, Consiglio
federale), which answers members of the Federal Assembly (National Council, Council of States).

## The packet

`.work/fed/packets/<id>.txt` has the same layout as a P8 packet:
- `=== DOCUMENT question ===`: the texts the data source stores as the member's intervention: `PAGE 1` the title,
  `PAGE 2` the text as submitted, `PAGE 3` the reasoning (only if the source stores one);
- `=== DOCUMENT answer ===`: `PAGE 1` the text the source stores as the answer to it;
- `=== DATES ===`: every distinct date a date parser found in the two documents (letters D01, D02, ...). You do not
  label date roles in this packet; the list only helps you find printed dates.

These are web texts, not PDFs: there are no letterheads, signatures or page footers unless the text itself prints them.
Label only what is printed. A field the texts do not print gets the "not printed" value the guides define (for example
`people: []`, `answer_date: null`).

## The file you write

One JSON file per packet: `.work/fed/ann/<A>/<id>.json` (`<A>` is your annotator code). Exactly these keys:

```json
{"id": "FED-001",
 "question_doc": "member_text|other|unclear",
 "answer_doc": "executive_answer|other|unclear",
 "people": [{"name": "Firstname Lastname", "kind": "person|group|committee|other_body",
             "role": "sole_author|first_signatory|joint_author|co_signatory|supporter|spokesperson|other",
             "doc": "question|answer", "page": 1, "quote": "verbatim, <= 200 characters"}],
 "function": {"value": "mandate|examine_report|questions|direct_decision|other|unclear", "doc": "question", "page": 2, "quote": "..."},
 "instrument_named": {"value": "motion|postulate|interpellation|question|resolution|initiative|other|none", "doc": "question", "page": 2, "quote": "..."},
 "languages": {"question": ["de"], "answer": ["de"]},
 "answer_present": "yes|no|oral|unclear",
 "answer_date": "YYYY-MM-DD" ,
 "role": "decision|dispatch",
 "answer_date_page": 1,
 "answer_date_quote": "verbatim text from that page of the ANSWER document containing the date",
 "answer_date_lenient": [],
 "notes": "short reasons; anything ambiguous"}
```

- `answer_date`, `role`, `answer_date_page` and `answer_date_quote` are `null` when no answer date is printed (and
  always when `answer_present` is not `yes`). `answer_date_page` is a page of the **answer** document.
- Every `quote` is copied verbatim from the page you name (whitespace may differ; nothing else), at most 200 characters.
  `doc`, `page` and `quote` may be omitted only where the P8 guide says so (`unclear`, `none`).

After writing each file run

    cd track_2a && PYTHONPATH=src:. .venv/bin/python -m eval.fed.annotate selfcheck <A> <id>

and fix everything it reports until it prints `OK`.

## Tie-break (A3 only)

You receive `.work/fed/a3/<id>.json` with the fields two annotators labelled differently (`fields`, `parts`) and their
two labels as X and Y (order random). Read the packet and this guide (with the sections it names), then write
`.work/fed/ann/A3/<id>.json` with `id` and exactly the keys listed in `parts`, labelled by this guide (you may agree
with X, with Y, or with neither). Run the selfcheck with `A3`.
