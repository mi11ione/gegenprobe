# Raw blind annotations of the held-out gold set

`A1.jsonl` (Claude Opus), `A2.jsonl` (Claude Sonnet): one label per held-out document, made blind (each annotator saw only
the annotation guide and the document's page texts). `A3.jsonl` (Claude Opus): the tie-break label for the 41 documents
where A1 and A2 differed on answer date or recommendation; A3 saw both labels (A1 always as "X", A2 as "Y") and the document.
Final labels: `../heldout_labels.jsonl` (A1 where A1 = A2, else A3), built by `eval/gold/annotate.py merge`.

Fields as in the guide (`docs/gold_protocol.md`). `answer_date_quote` and `recommendation_quote` are verbatim excerpts of at
most 200 characters, verified against the page text by code; `notes` is the annotator's own comment. No document full
texts. Reproduce the agreement figures: `PYTHONPATH=src:. python -m eval.robustness agreement`
(→ `results/eval/robustness_agreement.json`, which also checks equality with `results/eval/gold_agreement.json`).
