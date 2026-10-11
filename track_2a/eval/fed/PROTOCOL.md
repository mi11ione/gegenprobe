# Federal cell (EXPLORATORY): the converter and four schema fields on Federal Council answers (frozen by eval/fed/LOCKFED)

**Why.** Every converter and schema record so far is cantonal or communal: P1/P2 strata are `canton` and `commune`
(`results/eval/breadth_p1_p2.json`), P8's twelve registered parliaments include no federal one (PREREG9.md §3), and all
171 v0.2 records carry a cantonal or communal body. This cell runs the converter, its Apertus pointer and a no-model
baseline on 15 federal affairs (5 per language), with gold labels made by the project's own protocol, and reports the
result as exploratory: counts and Wilson intervals, no hypothesis test.

**Written before any federal affair is drawn.** The frame, strata, quotas, seeds, fields, definitions, arms, guide,
scoring and stop rules are fixed here and in the hashed code (`eval/fed/`). The draw (`eval/fed/draw.py`) refuses to run
until LOCKFED is committed and unchanged; `eval/fed/lock_fed.py write` refuses if a federal draw, key, label or gold file
exists, or if the self-test (`eval/fed/selftest.py`, synthetic inputs only) fails. The only look at the pool before
registration is (i) `WORK/fed/texts_che_meta.jsonl.gz`, one streamed pass over OPD's `texts_CHE` export that kept per
text row and language slot only the length, the sha256 of the stored HTML, the converter's language guess and the
number of dates its date lattice finds (no text), and (ii) `results/fed/pool_probe.json`, counts computed from it and
from OPD's committed-snapshot exports. No affair was selected, no text was read or shown, no model was called.

## 1. Where federal answers live in OPD (what phase 1 found)

- **Not documents.** OPD's `docs_CHE` export (52,451 rows) holds Federal Gazette and Official Compilation publications
  (messages, decrees), 57% of them stored as Fedlex's "JavaScript required" page. The Fedlex resolver
  (`gegenprobe.repair.che`) resolves those through the Fedlex SPARQL endpoint and fetches the pdf-a from
  `www.fedlex.admin.ch/filestore/` (`fedlex.data.admin.ch` disallows `/filestore/*`). It never reaches an answer to an
  intervention, and this cell does not use it.
- **Texts.** The Federal Council's answers are rows of OPD's separate `texts` export (`texts_CHE.ndjson.gz`, 210,423 rows
  in the export of 10 Oct 2026, 248 MB): type "Antwort BR / Büro" (FR "Réponse CF / Bureau", IT "Risposta del CF /
  Ufficio"), each row carrying one HTML version per language slot (`text_de`, `text_fr`, `text_it`, `text_rm`). The
  member's intervention is the submitted-text row ("Eingereichter Text", "Texte déposé", "Testo depositato") plus the
  reasoning row ("Begründung", "Développement", "Motivazione") where the instrument has one. `text_date` is null on all
  51,066 answer, 63,994 submitted-text and 25,896 reasoning rows: OPD's texts carry no date; the Federal Council's dates
  are in OPD's events, and only for part of the affairs (§2).
- **Three language versions.** Most answers exist as three genuine versions (German, French, Italian). OPD's `text_it`
  slot holds a French text in 7,165 (and a German one in 1) of the 37,828 eligible answers whose Italian slot has
  >= 200 characters (the converter's language guess; `answer_slot_vs_language_guess` in the probe): the Italian slot
  then repeats the French version.
- **Curia Vista OData** (`ws.parlament.ch`, used by `repair.che curia` for 75 gap affairs) is not used.

**Hosts and robots.txt** (checked through the project's fetch path, `gegenprobe.net` with the RFC 9309 matcher
installed by `compliance/fetchguard.py`, User-Agent `hackapertus-research/0.1`, >= 1.2 s between requests to a host,
fail-closed on an unreadable robots.txt; 11 Oct 2026):

| host | used in this cell for | robots.txt | decision |
|---|---|---|---|
| files.openparldata.ch | `exports/index.json`, `exports/texts/texts_CHE.ndjson.gz` (scan, once; fetch, once) | 404: no restrictions (RFC 9309 2.3.1.3) | allowed |
| api.openparldata.ch | nothing | disallows `/v1/`; refused before any request (`net.FORBIDDEN`) | never touched |
| api.publicai.co | the pointer arm, through the budget gateway client (`~/Desktop/hackapertus/gateway/gw.py`) | read; no rule for our agent or `*` | allowed (an API endpoint, not a crawl) |
| fedlex.data.admin.ch | nothing (the resolver's SPARQL host) | disallows `/filestore/*` | not touched |
| www.fedlex.admin.ch | nothing (the resolver's PDF host) | allows `/`, disallows print views | not touched |
| ws.parlament.ch, www.parlament.ch | nothing | 404 / no rule for our agent | not touched |

OPD's affairs, events and contributors come from the committed-snapshot exports in `GP_OPD_RAW` (`.work/opd`, the
census snapshot; sha256 in the probe and in LOCKFED), read locally.

## 2. Frame (`eval/fed/common.py`, `frame`)

An affair qualifies when all hold:

1. OPD body `CHE`, harmonised type Interpellation, Motion, Postulate or Question (P8's scope; question time is out);
2. a recorded Federal Council answer: an answer text row in `texts_CHE`, and the affair is not answered by another body
   (an affair whose only written-answer events name the Bureau, a supervisory authority or a federal court is out;
   census `classify_event`). OPD carries a Federal Council answer event for only part of these affairs: most
   interpellations and questions have the answer text and no answer event (13,975 of 18,028 interpellations, 4,007 of
   4,097 questions). Both qualify; the probe counts each;
3. a submitted-text row (the lowest row id of each type is used; no eligible affair has several answer rows);
4. at least one **genuine** language version L in {de, fr, it}: the answer in slot L has 200 to 40,000 characters
   (census MIN_DOC_CHARS; P8's upper bound) and the converter's language guess (`convert.batch.guess_lang`) on it is L,
   and the member's text in slot L (submitted text + reasoning) has >= 200 characters with guess L;
5. not in any existing gold, dev, test or audit set (P8's frozen exclusions, 2,436 affairs, plus the 66 P8 affairs; no
   federal affair is among them).

**Stratum = the language version tested.** An answer with three genuine versions has no single language, so each
eligible affair is assigned one stratum: a seeded uniform choice among its genuine slots
(`random.Random(f"20261050:slot:{affair}")`), fixed before the draw and independent of any outcome. (Choosing Italian
whenever genuine would leave German and French only the older affairs that lack an Italian version.) The packet, the
arms and the gold all use that slot.

**Frame size** (`results/fed/pool_probe.json`):

| | de | fr | it | total |
|---|---|---|---|---|
| eligible affairs with a genuine version in this language (overlapping) | 37,955 | 37,770 | 30,447 | 38,307 affairs |
| assigned stratum | 14,147 | 14,005 | 10,155 | 38,307 |
| of which Motion / Postulate (MP) | 6,138 | 6,215 | 4,620 | 16,973 |
| of which Interpellation / Question (IQ) | 8,009 | 7,790 | 5,535 | 21,334 |
| with an OPD Federal Council answer event (MP / IQ) | 5,924 / 1,189 | 6,052 / 1,167 | 4,572 / 1,104 | 20,008 |
| answer text with >= 1 date the converter's lattice finds | 7,609 | 7,507 | 5,307 | 20,423 |

By type: Interpellation 17,327, Motion 12,356, Postulate 4,617, Question 4,007. Not eligible: 2,513 Motion/Postulate
and 46 Interpellation/Question affairs without a genuine version (mostly a one-line answer under 200 characters), 65
answered by another body, 19 without a submitted text, 3 with an answer event but no answer text, 1,404 with
neither (42,357 affairs in scope).

## 3. Sample and draw (`eval/fed/common.py` QUOTAS, `eval/fed/draw.py`)

- **15 affairs**: 5 per stratum (de, fr, it), each 2 Motion/Postulate + 3 Interpellation/Question.
- **Draw** (`draw.py draw`, no network): per stratum and group, the eligible affairs sorted by id and shuffled with
  `random.Random(f"20261050:{stratum}:{group}")`; the whole order is written to `data/fed/fed_draw.jsonl` (affair ids,
  row ids, sha256s; no text).
- **Fetch** (`draw.py fetch`, one streamed request for `texts_CHE` through the project's fetch path): taken in that order;
  an affair is accepted when the stored HTML of its answer, submitted-text and reasoning rows in the stratum's slot has
  the sha256 the scan recorded. A changed or missing text is a failed fetch, replaced by the next affair of the same
  cell; a cell whose order runs out (the fetch considers the first 30 affairs of each order) is filled from the other
  group of the same stratum. No other replacement: an affair whose texts turn out to be something else stays in the
  sample (its fields become what the labels say).
- **Committed after the fetch, before any label:** `data/fed/fed_draw.jsonl`, `data/fed/fed_affairs.jsonl` (ids,
  number, type, stratum, row ids, sha256s, characters, OPD's Federal Council event dates; never text),
  `data/fed/fed_fetch_log.jsonl`, OPD's metadata of the drawn affairs (`data/fed/opd_meta_fed.jsonl` and
  `body_names_fed.json`, frozen `affair.meta.vendor`), `data/fed/fed_datelists.jsonl` (dates without context),
  `results/fed/sample.json`. The texts stay in `WORK/fed/texts/` (never committed).

## 4. Fields scored (definitions unchanged from P1/P2, P8 and schema v0.2)

| field | gold (what the texts print) | definition | value the converter carries | schema v0.2 |
|---|---|---|---|---|
| **answer date, with role** | `answer_present`, `answer_date`, `role` (decision / dispatch), page, quote, lenient dates, on the answer text | P1/P2 guide (`eval/gold2/GUIDE.md`, *Definitions*): the executive's decision date as printed, else the answer's dispatch date; never the submission date or dates in the content; null when none is printed | `qa[].answer_date`: the frozen P1 cascade (OPD's answer-event date only where the text prints it, else the rules); OPD's event as `dates[]` role `answered` (route metadata) | `DateValue` with `role`; `DatedEvent` |
| **submitter role** | `people` with role (sole_author, first_signatory, joint_author, co_signatory, supporter, spokesperson, other) | P8 guide §2; P8 derivation (`eval/p8/derive.py` `submitter`): the category of the carried value, E = {author_person} | OPD's first `author` (`affair.extract.from_metadata`) | `Actor.role` (v0.2 roles) |
| **instrument function** | `function` (mandate, examine_report, questions, direct_decision, other, unclear) and `instrument_named` | P8 guide §5; P8 derivation `type_`: `conforms` iff the function equals the one OPD's harmonised type names (Motion: mandate, Postulate: examine_report, Interpellation and Question: questions) | OPD's harmonised type | `type.instrument_function`, `type.instrument_named` |
| **text language** | `languages` of the member's text and of the answer | P8 guide §6; P8 derivation `language`, with OPD's language slot as the tag | the slot (`Document.language_tag`) | `Document.language_of_text` vs `language_tag` |

Because the frame keeps only genuine slots (§2), the text-language category of a drawn affair is `text_language` unless
the converter's guess was wrong: on the sample the field checks the guess; the slot finding (Italian slots holding
French) is the frame-level count of §1, labelled as the guess's count.

## 5. Arms (`eval/fed/arms.py`; they read the same converted texts the packets show and never read a label)

| field | rules / converter (no model) | Apertus pointer (gateway) | no-model baseline |
|---|---|---|---|
| answer date | P1 rules arm `convert.rules.answer_date`; converter record C (`affair.build.run_affair`, metadata first, then rules) | P1 pointer `convert.pointer.answer_date`, θ = 10.395 (`data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json`), anchors from the rules; record CA's suggestion | latest date the converter's lattice finds in the answer text |
| submitter | M/C: OPD's first author; R: name after an author cue; role rules (if frozen) | CA: closed set of CHE office holders printed in the member's text, θ = 0 (P3) | — |
| instrument | M/C: OPD's harmonised type; R: first type word in the head; role rules (if frozen) | CA: closed set motion / postulate / interpellation / question / resolution, θ = 0 | — |
| language | the slot; the converter's language guess; role rules (if frozen) | — (no pointer exists) | — |

- **Whole-affair converter**: P3's arms through `affair.build.run_affair`, unchanged, its text source pointed at the
  federal texts (as `eval/gold2/run_p2.py` points the frozen P1 runner at P2); `link_status` = `attached`. The default
  record C is finalised (`affair_post.finalize`), carried to v0.2 (`schema.v0_2_all.carry_v0_1`) and validated
  (`schema.v0_2_all.stats`); valid records are written to `results/fed/fed_records_v0_2.jsonl` as exploratory federal
  records.
- **Converter role rules** (`gegenprobe.convert.roles.extract`, round 13): an arm only if the file exists and is
  committed when LOCKFED is written (`lock_fed.ROLES` is then hashed); otherwise reported as not run.
- **Pointer path**: `eval.arms.backend("gateway:swiss-ai/apertus-v1.5-8b:2a-fed:0.5")` (the 70B weights Public AI
  serves under that name; tag `2a-fed`, cap USD 0.5), wrapped in the review mode's `BuildGuard`; every response is
  cached by hash in `data/model_cache` (replayable with `GP_OFFLINE=1`).

## 6. Gold protocol (P8's tooling and packet format; `eval/fed/packets.py`, `eval/fed/annotate.py`, `eval/fed/GUIDE_FED.md`)

- **Packets** (WORK only): P8's format, rendered by the frozen P8 functions: `DOCUMENT question` (page 1 title, page 2
  submitted text, page 3 reasoning if stored), `DOCUMENT answer` (page 1), and the parser's date list. An opaque id
  (`FED-001`...) in seeded order (seed 20261050). No OPD metadata, number, names, dates, slot, stratum or arm output.
- **Annotators**: A1 (Claude Opus) and A2 (Claude Sonnet) label every packet blind, each in its own session, with
  `GUIDE_FED.md`, which applies P8 guide §§1, 2, 5, 6 and the P1/P2 answer-date definitions unchanged. They may read
  only the guide, the two guide sections it names and their packet; never `data/fed/`, `results/fed/`, the key or an
  arm output (the arms run after the merge, §9). Every file must pass `eval.fed.annotate selfcheck` (P8's closed
  vocabularies and quote check; P1's answer-date check). The lead launches them; no human labels.
- **Tie-break**: fields whose disagreement key differs (answer date: the date or null, P1's key; submitter, type,
  language: P8's derived category) go to A3 (Claude Opus), who sees the packet and the two labels of those fields as X
  and Y in seeded random order (seed 20261051) and labels them anew. Gold per field: A1 where A1 and A2 agree, else A3.
  The answer date's lenient set is P1's: both annotators' lenient dates and the other annotator's date.
- **Committed after the merge**: `data/fed/fed_gold.jsonl`, `data/fed/annotations/{A1,A2,A3}.jsonl` (quotes replaced by
  sha256 and span; notes stay in WORK), `data/fed/fed_key.jsonl`, `results/fed/fed_agreement.json` (raw agreement and
  Cohen's kappa of A1 vs A2 per field; fields decided by A3). Session times recorded as for every earlier set.

## 7. Reporting (`eval/fed/score.py` -> `results/fed/fed_tables.json`)

Labelled EXPLORATORY everywhere. Per stratum and overall, counts with Wilson 95% intervals; no hypothesis test, no
threshold, no verdict, no pooling with P1/P2/P8 numbers.
- **Answer date**: gold distribution (answer present, date printed or null, role); per arm (rules, latest printed date,
  converter record C, pointer, CA) the frozen `eval/score.summarise` counts, strict and lenient: exact, false null,
  misattributed, fabricated, values on gold-null; the metadata layer: records carrying OPD's answer event, and where a
  date is printed, whether it equals an OPD Federal Council event date.
- **Submitter, instrument function, text language**: P8 categories, determinable / undeterminable by reason, share in E
  with Wilson; per converter arm the name, instrument and function outcomes (correct, wrong, null); the language guess vs
  the gold; the role rules if they ran.
- **v0.2 records**: valid / invalid with errors, routes and null reasons used.
- In the README or report the cell is cited as "exploratory, 15 federal affairs", with its intervals.

## 8. Stop rules

1. **Fetch path**: a robots.txt disallow or an unreadable robots.txt (fail-closed) stops the scan or fetch; nothing is
   fetched another way.
2. **Lock**: `draw`/`fetch` refuse unless LOCKFED is committed and every hashed file and WORK input is unchanged; the
   draw and the fetch each run once.
3. **Shortfall**: a cell is filled from the other group of its stratum; a remaining shortfall is reported, never filled
   from another stratum.
4. **Served build**: a pointer response from a fingerprint θ was not fitted on stops the pointer arm (`BuildMismatch`,
   exit 3); the arm is then reported as not run, the no-model arms stand.
5. **Budget**: the gateway's cap (USD 0.5, tag `2a-fed`) refuses further calls; a partial pointer run is reported as
   partial with its n.
6. **Frame check**: if both annotators label the answer document as not the executive's answer for more than half of
   the affairs, the frame is reported as invalid and no arm is scored as a result (`stop_rules` in the tables).
7. **No re-draw, no re-labelling** after the merge; every outcome is reported, including empty cells.

## 9. Order of operations (phase 2)

    cd track_2a                                        # PYTHONPATH=src:. and .venv/bin/python throughout
    python -m eval.fed.selftest                        # must print "selftest OK"
    python -m eval.fed.lock_fed write                  # -> eval/fed/LOCKFED; commit eval/fed/, results/fed/pool_probe.json
    python -m eval.fed.draw draw                       # no network -> data/fed/fed_draw.jsonl
    python -m eval.fed.draw fetch                      # one streamed request -> data/fed/*, packets; commit before labels
    # A1, A2 label .work/fed/packets/FED-*.txt -> .work/fed/ann/{A1,A2}/ (each file: annotate selfcheck <A> <id>)
    python -m eval.fed.annotate verify A1 && python -m eval.fed.annotate verify A2
    python -m eval.fed.annotate a3packets              # A3 on .work/fed/a3/*.json -> .work/fed/ann/A3/
    python -m eval.fed.annotate verify A3 && python -m eval.fed.annotate merge   # commit the gold
    python -m eval.fed.arms offline
    python -m eval.fed.arms pointer --backend gateway:swiss-ai/apertus-v1.5-8b:2a-fed:0.5
    python -m eval.fed.score                           # -> results/fed/fed_tables.json; commit

## 10. Not allowed after LOCKFED

Any change to the hashed files (frame, strata, quotas, seeds, fields, guide, arms, scoring, stop rules) or to the
reused frozen code. A later change is listed in `eval/fed/DEVIATIONS_FED.md` with its effect.
