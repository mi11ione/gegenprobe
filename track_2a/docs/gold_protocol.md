# Gold-set protocol (no human labels)

No member of the team labels or adjudicates. Every held-out label comes from one of two independent sources, and the
report gives the agreement between them.

## Sources
1. **Structured oracle (where one exists).** Data that does not come from reading the document text:
   - OPD events: the date of the affair's written-answer event (`Beantwortet` / answer-titled event);
   - BE canton OGD `dokument.csv`: the RRB date in the answer document's title (`RRB-dd.mm.yyyy`);
   - the OPD doc `date` field of the answer document.
   The oracle is used to **check** labels, never to produce them: OPD's own metadata is known to be off by a day in places
   (2025.GRPARL.384), and it says nothing about what is printed in a given document.
2. **Blind double annotation by two Claude agents** (A1, A2), declared as coding-assistant use in the report.
   - Each annotator sees only the extracted page texts of one document (with page numbers) and the annotation guide below.
   - They never see the rules output, the candidate lattice, any model score, the other annotator, or the oracle.
   - Each label carries a **verbatim quote** and its page; a label whose quote is not found verbatim on that page is void
     (checked by code) and the annotator is asked once more.
3. **Tie-break by a third Claude agent** (A3) on disagreements only. A3 sees both labels with quotes and the document, not
   the oracle, and must pick one of them or null with a one-line reason.

## Reported
- Cohen's κ between A1 and A2 per field (answer present, answer date, recommendation); raw agreement.
- Agreement of the final label with the structured oracle where one exists (expected high but not 100%; every mismatch is
  listed with the document id, both values and the quote).
- The number of labels decided by A3.

## Annotation guide (given verbatim to A1–A3)
For the document below, answer:
1. `answer_present`: does this document contain the government's (executive's) answer or decision on the parliamentary
   affair? (yes / no). A question text that only asks, or a parliamentary decision without the executive's answer, is "no".
2. `answer_date`: if yes, the date on which the executive decided its answer (the date of the government decision /
   resolution / sitting: e.g. "RRB-Nr. 879/2024 vom 28. August 2024", "Sitzung vom …", "séance du …", "seduta del …",
   "Regierungsratsbeschluss vom …"). If only a letter/dispatch date is printed, give it under `answer_dispatched` instead.
   Never a footer, "Letzte Bearbeitung", print or version date. Give the verbatim quote that contains the date and its page.
   If no such date is printed, null.
3. `answer_dispatched`: the letter/dispatch date of the answer if printed separately (e.g. "Basel, 3. März 2025"), else null.
4. `recommendation`: what the executive recommends to parliament, only if stated: accept / reject / convert (e.g. motion
   into postulate) / partial / none-stated. Quote it.
Answer in JSON with a quote and page for every non-null value.
