# Virtual affairs: agenda items as affairs

**Why.** OPD numbers affairs it derives itself with a `V` (e.g. SO consultations `V 2021-06-28`). Many communes publish
only per-meeting documents: OPD's frontier list (`results/census/virtual_affairs.json`) has 16 bodies with 5,887
meeting-only documents, 8 of them with no affairs at all. For such bodies the agenda is the one structured document every
meeting has, and each numbered item is an affair in all but name.

**What we derive** (`python -m gegenprobe.virtual derive --agenda <pdf|url> --minutes <pdf|url> --body <key>`), per item:
- `ref`: `virtual: true`, `derived_from` = the agenda document, `number` = `V <meeting date> - <item no>`;
- `title` (span in the agenda); `type` (title rules → schema AffairType, the body's own word in `source_label`;
  a Fribourg "proposition" is a member's binding request, mapped to `motion`);
- the meeting date as a `debated` date, taken from the minutes heading where it is printed whole (the agenda's
  "les lundi 29 et 30 mai 2017" names a reserve day, so it is only used when the sitting is a single date);
- `decision` from the minutes: the item's section is located by its title (skipping the agenda the minutes repeat at the
  top), and the LAST decision sentence of the section is read ("Au vote, le Conseil général accepte … par 46 voix",
  "… prend acte de la réponse …", "… refuse … la transmission"). Elections and "Divers" carry the typed null
  `not_applicable`; an item whose section or decision was not found carries `present_unanchored`, never a guess.
- In `review` mode the Apertus closed-set pointer may fill the residue (type when no rule fires; decision when the section
  was found but no sentence matched), choosing among the vocabulary or null, with margin and θ recorded.

**Bulle, a worked case.** OPD holds 276 Bulle affairs, but only members' instruments; the council's own business
(credits, regulations, accounts, elections) appears in OPD only as meeting documents. On 6 dev meetings: 74 items, every
item typed by rule, the meeting date from the minutes heading on 6/6, 29 decisions read from the minutes (14 items left as
`present_unanchored`, 31 `not_applicable`), every one of the 132 spans re-checked against the PDF text (`results/eval4/p4_dev_rules.json`). Dev numbers are not an evaluation; the
held-out test is pre-registered in `eval/prereg4/`.

**Limits.** Scanned agendas (OCR, untested here); items continued over several meetings (not linked yet; title-similarity
linking as `same_subject` is the planned route); sub-items whose decision is recorded under the parent item; minutes that
do not repeat item titles (the section then stays unlocated and the decision a typed null); agenda layouts without numbered
items. Linking items to OPD's existing affairs of the same body (e.g. a postulate item to its OPD affair) is not done yet.
