# Pre-registration: precision of the BE `relink` route (written 2026-10-09, before the sample was drawn)

**Question.** When the bulk join proposes "re-attach OPD doc X to affair Y" (`action = relink` in `results/repair/repair_BE.tsv`,
2,459 rows), is X really the government's answer to Y?

**Population.** All 2,459 `relink` rows produced by `python -m gegenprobe.repair.be list` from the 2026-10-06 OPD exports and the
2026-10-08 canton OGD tables (byte-identical to `fixtures/openparldata_be_relink_list.tsv`).

**Sample.** `random.Random(20261009).sample(rows sorted by affair_id, 40)`. Seed and n are fixed here and in `be.py`
(`SAMPLE_SEED`, `SAMPLE_N`) before drawing; the draw is not repeated.

**Document.** The PDF at the URL OPD itself stores for parentless doc X (host www.rrgr-service.apps.be.ch), fetched politely
(UA hackapertus-research/0.1, ≥ 1.2 s per host, robots.txt honoured), text by `pdftotext` (poppler, default reading order).

**Checks (all deterministic, `be.verify_text`).**
1. identity: the affair number of Y (e.g. `2013.RRGR.10100`) or the canton vorstoss number of Y (`geschaeft_vorstoss_nummer`,
   e.g. `314-2013`) is printed in the document.
2. heading: an answer heading matches `repair.common.ANSWER_HEADING` (DE/FR/IT lexicon).
3. date: the first header field `RRB-Nr.: NNN/YYYY vom <date>` parses and equals one of OPD's answer-event dates for Y
   (events with harmonised id 6/76 or a title matching beantw/réponse). Rows where OPD has no answer event are reported as n/a.

**Primary metric.** identity ∧ heading, k/40 with a Wilson 95% CI. A fetch failure counts as not verified.
**Secondary.** date agreement among rows with an OPD answer event; the full triple check.
**Reporting.** All three numbers are reported whatever they are, together with every failing row.
