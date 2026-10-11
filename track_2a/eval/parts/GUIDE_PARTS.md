# Annotation guide PARTS: what each page of one document shows (tables, annexes, pictures, scans, signatures)

You label what you SEE on each page image of one document. Never use outside knowledge, the internet, other packets,
other annotators' files or anything in the repository other than this guide and your packet. You do not know, and must
not try to find out, which document, parliament or sample group a packet belongs to, or what any program found in it.

## The packet

`.work/parts/packets/<id>/` (ids `PRT-001` ... `PRT-030`) holds:
- `packet.json`: `{"id": "PRT-007", "n_pages": 4}`;
- `page-01.png`, `page-02.png`, ...: every page of the document as an image (100 dpi), page 1 first.

Look at every page image in full. The documents are Swiss parliamentary papers (a member's motion, question or
interpellation, or the government's answer) in German, French or Italian.

## What you label, per page

Seven yes/no labels per page. Each is about this page only; a page can have several labels or none.

- **table** — the page shows a table: information arranged in a grid of **at least 3 rows and at least 3 columns**
  (a header row counts as a row; the first column of row labels counts as a column), with or without ruling lines.
  Count a table even if it is only part of the page, continues from the previous page, or is set as a picture.
  Not a table: a two-column block of "label: value" pairs (e.g. "Vorstoss-Nr.: 268-2021 / Eingereicht am: ..."), a
  numbered or bulleted list, text in two newspaper-style columns, the letterhead or address block.
- **budget_table** — the table (see above) shows money or accounts: amounts in francs, accounts, budget or accounts
  years (Budget, Voranschlag, Rechnung, compte, preventivo, consuntivo, RE/BU/VA 2025, ...). `budget_table` yes needs
  `table` yes.
- **annex** — the page belongs to an annex/appendix/attachment of the document: material appended after the main text
  and labelled as such (Anhang, Beilage, Anlage 1, Annexe, Allegato, Appendice, Appendix), from its label to the end of
  that annex. A sentence that only *mentions* an annex ("voir annexe 2", "im Anhang") does not make the page an annex.
- **annex_start** — this page begins an annex (its label "Anhang 1", "Allegato 2", ... is printed on this page).
  `annex_start` yes needs `annex` yes.
- **image** — the page contains a picture element of noticeable size (roughly a business card or larger, about 2% of the
  page): a photo, map, aerial view, chart or diagram, drawing, or a table shown as a picture. Not: the letterhead or
  logo at the top, a coat of arms or logo that repeats on every page, page header/footer marks, decorative lines,
  handwritten signatures or official seals/stamps (those are `signature`), and not the page itself being a scan (that is
  `scanned`).
- **scanned** — the page itself is a scan or photocopy of paper: the whole page looks photographed or scanned (grey or
  speckled background, slight skew, scanner noise, stamps or handwriting on paper, fuzzy letter edges), rather than a
  clean digitally produced page. Judge the page as a whole.
- **signature** — the page shows handwritten signature(s), an official seal or stamp next to a signature, or a list of
  signatories (names of several members printed or handwritten in columns, usually with signatures). A typed name
  without a handwritten signature, seal or stamp is not enough.

When unsure, choose the answer you find more likely and say why in `notes`.

## The file you write

One JSON file per packet: `.work/parts/ann/<A>/<id>.json` (`<A>` is your annotator code, e.g. `A1`). Exactly these keys:

```json
{"id": "PRT-007",
 "annotator": "A1",
 "pages": [
  {"page": 1, "table": false, "budget_table": false, "annex": false, "annex_start": false, "image": false,
   "scanned": false, "signature": false},
  {"page": 2, "table": true, "budget_table": false, "annex": false, "annex_start": false, "image": false,
   "scanned": false, "signature": true}
 ],
 "notes": "p2: table of course numbers by year; signature of the chancellor at the bottom"}
```

- `pages` has one entry per page, pages 1 to `n_pages` in order; every label is `true` or `false`.
- `notes` is a string (may be empty). Do not copy document text into it beyond a few words.

After writing each file run

    PYTHONPATH=src:. .venv/bin/python -m eval.parts.score selfcheck .work/parts/ann/<A>/<id>.json

and fix the file until it prints `OK`. When all packets are done, run the same command on your directory
(`.work/parts/ann/<A>`).

## What happens next (not your task)

`python -m eval.parts.score merge` takes the majority of the annotators per page and label (an even split is
`disputed` and left out), and `python -m eval.parts.score score` compares it with the program's reading, page by page,
into `results/parts/blind_check.json`. The program's output is never shown in a packet.
