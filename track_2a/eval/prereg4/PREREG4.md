# Pre-registration P4 (DRAFT, not locked): virtual affairs from meeting documents

**Question.** For parliaments that publish meeting documents but no affairs (OPD's virtual-affairs frontier: 16 bodies,
5,887 meeting-only documents, `results/census/virtual_affairs.json`), can each agenda item be turned into a schema v0.1
affair (`virtual=true`, `derived_from` = the agenda document, number `V <meeting date> - <item no>` as OPD numbers its
virtual affairs), with title, type, meeting date and the parliament's decision, every value with page and span?

**Body.** Bulle (OPD body 2125, Conseil général, FR). All 641 of its OPD documents hang on meetings, none on an affair. OPD
does hold 276 Bulle affairs, but they are members' instruments only (postulates, questions raised under "Divers"); the
council's own business on each agenda (credits, regulations, accounts, elections) exists in OPD only as meeting documents.

**Dev (used to write the rules; reported as dev, never as a result).** 6 meetings drawn with seed 20261012 from the 34
meetings with both an agenda and the minutes of the same sitting (`data/gold4/p4_meetings.jsonl`): 74 agenda items.
Dev rules output: `results/eval4/p4_dev_rules.json` (all 132 spans re-check).

**Held-out (drawn only after LOCK4).** 6 further Bulle meetings, seed 20261013, from the remaining candidates
(`python -m eval.gold4.packets draw-heldout --fetch`). Exploratory transfer cell (no decision attached): 2 meetings of a
second French-speaking frontier body with agenda + minutes, chosen by a seeded draw among frontier bodies with both document
kinds; reported separately.

**Frozen at LOCK4:** `src/gegenprobe/virtual/*.py`, `src/prompts/fr/virtual_*.txt`, `eval/gold4/run_p4.py` (incl. the item
matching rule), this file, `eval/gold4/GUIDE.md`, `data/gold4/p4_meetings.jsonl`. θ = 0 for both pointers (declared: no
labelled dev set exists for fitting; P1/P2 showed θ = 0 is a reasonable default on the served 70B weights).

**Arms.** `rules_only` (no model) · `review` = rules + Apertus closed-set pointer on the residue (item type when no type
rule fires; decision when the item's minutes section was found but no decision sentence matched). Backend: the served build
used in P1/P2 (`swiss-ai/apertus-v1.5-8b` name = 70B weights) via the gateway; the 8B GGUF if its θ-free run completes.

**Labels.** Same no-human protocol as P1/P2: two blind Claude annotators (A1 Opus, A2 Sonnet), A3 Opus on disagreements
with randomised X/Y order; quotes verified verbatim by code (`eval.gold4.packets check`); raw files committed.

**Metrics (per arm, Wilson 95% CIs).** item segmentation precision and recall (a predicted item matches a gold item by
agenda number, else by normalised title prefix); title correct; type accuracy; decision accuracy and decision recall on items
whose gold decision is adopted/rejected/acknowledged/referred/withdrawn; **invented decisions** = a decision on an item whose
gold is none/not_applicable; precision of model-decided values.

**Hypotheses (decisions attached).**
- **P4-H1** agenda segmentation: rules item recall ≥ 0.90 (Wilson lower bound reported).
- **P4-H2** types: rules type accuracy ≥ 0.85 on matched items.
- **P4-H3 (primary)** decisions: `review` decision recall > `rules_only` (exact McNemar on items with a gold decision,
  α 0.05) while invented decisions stay ≤ 15% (Wilson upper bound) of items without a decision.
- **P4-H4** meeting date: the meeting date matches gold on every held-out meeting.
**Consequences.** If H1–H2 hold, virtual affairs from agendas are reported as deployable for agenda-structured bodies; if
H3 holds, review-mode decisions are recommended with page+span for OPD's review step; if not, decisions stay rules-only and
the residue stays a typed null. Failures are reported as such.


## Label merge (frozen with LOCK4)
`eval/gold4/merge4.py`: items aligned by agenda number; an item is disputed when A1 and A2 differ on type or decision or only one lists it; A3 decides disputed items only, seeing both labels in seeded random X/Y order (seed 20261014); κ for type and decision reported. No human labels.
