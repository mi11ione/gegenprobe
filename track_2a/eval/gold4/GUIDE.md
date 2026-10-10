# Annotation guide: virtual affairs from a meeting's agenda and minutes (P4)

You get ONE meeting of a Swiss communal parliament: its agenda ("Ordre du jour") and its minutes ("Procès-verbal"), as
page-delimited text (`=== AGENDA PAGE n ===`, `=== MINUTES PAGE n ===`). Label what the documents PRINT; no outside
knowledge.

Write one JSON file per meeting: `{"meeting": "YYYY-MM-DD", "meeting_date_quote": "...", "items": [ ... ]}` with one entry
per agenda item, in agenda order:

```json
{"no": "5", "title_quote": "first ≤ 80 characters of the item title, verbatim from the AGENDA",
 "type": "motion|postulate|interpellation|question|election|budget|report|government_affair|approval_decision|miscellaneous|unknown",
 "decision": "adopted|rejected|acknowledged|referred|withdrawn|none|not_applicable",
 "decision_page": 12, "decision_quote": "verbatim sentence from the MINUTES that records the decision (≤ 250 chars)" | null,
 "notes": "short reason if ambiguous"}
```

## Definitions
- **Item**: every numbered entry of the agenda, including sub-items ("1.1"). Use the agenda's own number in `no`.
- **meeting**: the date the body sat, as printed in the minutes heading ("PROCES-VERBAL DE LA SEANCE … DU 9 OCTOBRE 2017");
  `meeting_date_quote` is that printed date.
- **type** (by the item's subject):
  - `motion`: a member's motion, or in Fribourg communes a member's "proposition"; `postulate`; `interpellation`;
    `question` (including the executive's answers to written questions);
  - `election`: any election or constitution of a bureau/commission;
  - `budget`: accounts, budget, financial plan; `report`: a report taken note of;
  - `government_affair`: a decision on the executive's message (credit, sale, purchase, regulation, statutes, ratification);
  - `approval_decision`: approval of a previous meeting's minutes; `miscellaneous`: "Divers", speeches, communications;
  - `unknown` only if the title gives no clue.
- **decision** (what the parliament decided on THIS item, per the minutes):
  - `adopted` (accepte, approuve, adopte, ratifie, transmet / décide de transmettre), `rejected` (refuse, rejette, ne transmet
    pas), `acknowledged` (prend acte), `referred` (renvoie), `withdrawn` (retiré);
  - `none`: the item could carry a decision but the minutes record none for it;
  - `not_applicable`: elections (who was elected is out of scope), "Divers", speeches.
  - Use the FINAL vote of the item when there are several (e.g. entry into the matter, then the final vote).
  - `decision_quote` must be copied VERBATIM from the minutes page given in `decision_page` (checked by code).
