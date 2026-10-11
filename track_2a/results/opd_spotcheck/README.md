# Spot check: 30 gold labels, about an hour

Every gold label in Gegenprobe comes reproducibly from blind multi-annotator agents with a cross-vendor check. This kit
lets anyone, OpenParlData included, verify 30 of them against the documents.

1. Open `spotcheck.csv` in a spreadsheet. Each row is one label: `set` is `dates` (P1/P2 answer dates), `p7` (Apertus
   promotions, P7) or `p8` (submitter and type, P8).
2. Open `document_url` (OPD's own copy where OPD holds the document, else the parliament's URL; `source_url` is the
   parliament's), go to `page` and find `quoted_text` (`char_span` is its position in our text of that page).
3. Read `what_to_check`, compare with `our_label`, and write `yes` or `no` in `reviewer_agrees`; add anything in `note`.
4. Leave a row empty if you cannot decide; it is not counted. About 2 minutes per row.
5. Score it: `PYTHONPATH=src:. python -m eval.spotcheck score results/opd_spotcheck/spotcheck.csv` (agreement overall and
   per set, with a Wilson 95% interval).

Selection: seeded (20261050) and stratified, 10 rows per set, every quote one the committed gold already carries; rebuilt
by `python -m eval.spotcheck build` (the selection rule is in `eval/spotcheck.py`). P8 type rows carry no quote: their
quotes are committed as sha256 only, so page and span locate the text.
