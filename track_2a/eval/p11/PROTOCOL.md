# P11 (EXPLORATORY): an Italian cell and a cell outside interventions (frozen by eval/p11/LOCKP11)

**Why.** Two gaps the submission names, both raised in review (round 17, J1 items 2-3; J2 on scope):
- **Italian.** README §Limits: "Italian is covered thinly: Ticino's robots.txt kept it out of P8, P10's primary cell is
  German and French, and its Italian cell is Lugano (6 affairs)." Yet the converter itself never needs the parliament's
  host: where robots.txt disallows a document (or the source has gone), it reads OPD's own copy on
  files.openparldata.ch (`gegenprobe.affair_cli.fetch_doc`). Cell **IT** runs the converter, its Apertus arms and two
  no-model baselines on 12 Italian-language interventions, read through exactly that path, with gold labels made by the
  project's own protocol (P1/P2 answer-date and P8/P10 author-role definitions).
- **Outside interventions.** README line 14: "parliamentary initiatives (5,817) and government business (37,864) share
  the vocabulary and are outside the tested scope." Cell **NI** asks of 15 such affairs, field by field, whether schema
  v0.2's 17-field skeleton holds (a value fits an existing role / needs a new role / is not printed / does not apply),
  and whether the converter emits a valid v0.2 record for them.

Both cells are **exploratory**: counts and Wilson 95% intervals, no hypothesis test, no threshold, no verdict, no
pooling with any earlier set. In the README and the report they are cited as "exploratory, n affairs", with intervals.

**Written before any P11 affair is drawn.** The frames, type rule, strata, quotas, seeds, fetch path, fields,
definitions, arms, guides, scoring and stop rules are fixed here and in the hashed code (`eval/p11/`). The draw
(`eval/p11/draw.py`) refuses to run until LOCKP11 is committed and unchanged; `eval/p11/lock_p11.py write` refuses if a
P11 draw, affair, key, label or gold file exists, if the pool probe is missing, or if the self-test
(`eval/p11/selftest.py`, synthetic inputs only) fails. The only looks at the pool before registration are counts:
`python -m eval.p11.common count` (no network) and the pool probe `results/p11/pool_probe.json` (one robots.txt
request per document host through the project's fetch path, and one streamed pass over OPD's docs export of each
Italian-language frame body on files.openparldata.ch, keeping only whether OPD holds its own copy of each eligible
document). No affair was selected, no document was requested or opened, no model was called.

## 1. Hosts and robots.txt

Every request goes through `gegenprobe.net` with the RFC 9309 matcher installed by `compliance/fetchguard.py`
(longest match; a fetch is refused while the matcher is inactive), User-Agent `GP_USER_AGENT` (default
`hackapertus-research/0.1`), >= 1.2 s between requests to one host, fail-closed on an unreadable robots.txt (5xx, 429,
DNS, timeout: the host is disallowed for the run). Probe of 12 Oct 2026 (OPD export index of 6 Oct 2026, the census snapshot):

| host | used for | robots.txt at the probe | decision |
|---|---|---|---|
| files.openparldata.ch | `exports/docs/docs_<body>.ndjson.gz` (copy URLs), `doc/<body>/<hash>` (OPD's own copies) | 404: no restrictions (RFC 9309 2.3.1.3) | allowed |
| api.openparldata.ch | nothing | disallows `/v1/`; refused before any request (`net.FORBIDDEN`) | never touched |
| www4.ti.ch (Ticino) | IT documents | read; disallows 4,584 of the 5,109 IT and NI document paths checked (all 2,986 IT paths) | OPD's copy for every disallowed path |
| www.locarno.ch | IT documents | read; disallows all 384 IT document paths | OPD's copy |
| www.lugano.ch, www.bellinzona.ch, legislativo.mendrisio.ch | IT documents | read; every IT document path allowed | source |
| www1.mendrisio.ch | IT documents | 404: no restrictions | source |
| 69 other NI document hosts | NI documents | 38 read (www.ag.ch, www.gl.ch, www.sz.ch, www.arbon.ch, www.einwohnerrat-kriens.ch disallow the paths), 8 without robots.txt (api.fr.ch answers 403: no restrictions), **23 unreachable** (connection timeouts: Winterthur, Uster, Wettingen, Thun, Emmen, Stadt Luzern, Nidwalden, Obwalden, Uri, ...): disallowed for the run, fail-closed | source where allowed; else OPD's copy |
| api.publicai.co | the two Apertus arms, through the budget gateway client (`~/Desktop/hackapertus/gateway/gw.py`) | an API endpoint, not crawled | allowed (as P1/P2, P10) |

Unreachable hosts change between runs (P10 saw the same); the fetch path decides again at the fetch, fail-closed, and
falls back to OPD's copy.

## 2. Frames (`eval/p11/common.py`)

**Type rule (both cells).** OPD's harmonised type. Where OPD leaves an affair of an Italian-language body unharmonised,
the body's own Italian type name (`type_name_it`, case-folded, singular or plural) by the fixed table `IT_NAMES`: the
schema vocabulary's Italian labels of the four intervention types (`data/schema/affair_types.json` `labels.it`:
Mozione, Postulato, Interpellanza, Interrogazione) and "Messaggio", the executive's message to the legislature
(government business). Reason, from the counts: OPD harmonises none of Mendrisio's 1,068 interventions, none of
Locarno's 121 motions and none of the 8,395 "Messaggio/Messaggi" affairs of Italian-language bodies, so without the name
rule Mendrisio and Italian government business could not enter. Every affair records which source gave its type (`type_source`), and the tables report it.

**Exclusions (both cells).** P10's (`eval.p10.common.exclusions`: P8's frozen exclusions, i.e. every earlier gold, dev,
test and audit set, plus the P8 and federal samples) plus the 44 P10 affairs and their documents: 2,557 affairs and
1,234 documents.

**IT frame.** Bodies whose OPD language is Italian. An affair qualifies by P8's frozen rule (`eval.p8.common.pool`, run
unchanged with the type rule's types): an Interpellation, Motion, Postulate or Question with one document typed as the
member's text and one as the executive's answer (P3's pair_type, else P6's doctype6), both OPD text status ok and
1,000-40,000 characters; minus the exclusions. A body enters the frame when at least 4 of its eligible affairs are
**readable**: each of the two documents either allowed by the parliament's robots.txt or kept by OPD as its own copy.
**Stratum = body.** Frame at the probe:

| body | level | eligible | types | type source | both documents allowed at the source | both kept by OPD as its own copy | readable | quota | in-sample arms |
|---|---|---|---|---|---|---|---|---|---|
| TI Ticino | canton | 1,493 | Question 1,013, Interpellation 480 | OPD harmonised | 0 | 1,493 | 1,493 | 3 | date rules, role rules |
| 5254 Mendrisio | city | 693 | Question 693 | Italian name (OPD unharmonised) | 693 | 693 | 693 | 3 | date rules, role rules |
| 5192 Lugano | city | 488 | Question 403, Motion 85 | OPD harmonised | 488 | 488 | 488 | 2 | date rules, role rules (roles-2 post hoc) |
| 5113 Locarno | city | 192 | Question 172, Interpellation 11, Motion 9 | harmonised 183, Italian name 9 | 0 | 192 | 192 | 2 | none |
| 5002 Bellinzona | city | 53 | Motion 53 | OPD harmonised | 53 | 53 | 53 | 2 | role rules, role reader (P10 development) |
| **total** | | **2,919** | | | 1,234 | 2,919 | 2,919 | **12** | |

"In-sample arms" (`in_sample_for` in the probe): the body is in `data/convert/rules_coverage.json` (date rules), in
P10's role-seen set (role rules) or among the role reader's development parliaments (PREREG10 §7).

Chiasso and the other Italian-language communes have no eligible affair (no intervention with both documents in OPD).

**NI frame.** Affairs whose type (type rule) is government business ("Government affairs", OPD harmonised id 9; or
"Messaggio" in an Italian-language body) or a parliamentary initiative (id 4), of a body whose OPD language is de, fr or
it (the federal parliament and Liechtenstein carry no body language and are outside), linking at least one
**qualifying document** (URL, OPD text status ok, 1,000-40,000 characters, P8's band), minus the exclusions.
**Stratum = (type, body language).** Frame at the probe:

| stratum | eligible | bodies | largest bodies | first packet document allowed at the source | quota |
|---|---|---|---|---|---|
| GA:de | 27,549 | 57 | BL 2,562, ZH 2,483, Zürich city 2,188, St. Gallen 1,324 | 18,676 | 3 |
| GA:fr | 195 | 3 | Vernier 175, Sierre 19, La Chaux-de-Fonds 1 | 195 | 2 |
| GA:it | 3,594 (all by the Italian name "Messaggio") | 5 | TI 1,483, Lugano 917, Mendrisio 499, Locarno 399, Bellinzona 296 | 2,186 | 3 |
| PI:de | 919 | 24 | ZH 746, TG 38, BL 25, VS 18 | 880 | 3 |
| PI:fr | 24 | 1 | JU 24 | 24 | 2 |
| PI:it | 640 | 1 | TI 640 | 51 | 2 |

Out of the frame: 7,296 / 45 / 4,790 / 86 / 18 / 974 affairs (same order) without a qualifying document; 28 excluded
affairs. Where the source is not allowed, the fetch reads OPD's copy (§3); the probe did not count copies for NI.

## 3. Sample, draw and fetch (`eval/p11/common.py`, `eval/p11/draw.py`)

- **IT: 12 affairs** by a fixed rule on the committed probe (`common.it_quotas`): 2 per frame body, the rest one at a
  time to the bodies in descending order of readable pool. At the probe: TI 3, Mendrisio 3, Lugano 2, Locarno 2, Bellinzona 2.
- **NI: 15 affairs** (`common.NI_QUOTAS`, fixed before the probe): government business de 3, fr 2, it 3; parliamentary
  initiatives de 3, fr 2, it 2. Government business is 6.5x as frequent in OPD and gets the extra affair, which goes to
  Italian, the gap the README names.
- **Orders** (`draw.py draw`, no network, once): IT per body, the eligible affairs sorted by affair id and shuffled with
  `random.Random(f"20261110:it:{body}")`; NI per cell, sorted and shuffled with
  `random.Random(f"20261110:ni:{type}:{language}")`, then every body's first affair before any body's second (body
  spread). The first 30 affairs of each order are written with their document rows to `data/p11/p11_draw.jsonl`, the
  whole order as ids.
- **NI packet documents** (`common.packet_docs`): the affair's qualifying documents in OPD id order, at most 3 and at
  most 60,000 OPD characters (the first always; the list stops at the first document that would pass the cap). The
  documents the converter's own pairing rule picks (`affair_cli.pick_docs`) are recorded too.
- **Fetch** (`draw.py fetch`, network, once): the converter's fetch path, `gegenprobe.affair_cli.fetch_doc`, unchanged:
  the source first; on robots_disallowed, robots_unreachable, an HTTP error, a network error, a timeout or a non-PDF
  body, OPD's own copy (`url_oparl`, files.openparldata.ch/doc/<body>/<hash>), recorded as `fetched_from: opd_copy`
  with the source's error. The copy URLs are read from one streamed pass over the body's docs export on
  files.openparldata.ch, made the first time a document of that body needs its copy (`draw.CopyIndex`, installed as
  `affair_cli.opd_copy_url`: the same rule, one pass per body instead of one per document). OCR for scans.
- **Acceptance.** IT: both documents fetched with >= 1,000 extracted characters each; a failure is replaced by the next
  affair of the same body; a body left short is filled one affair at a time from the other frame bodies in the order
  `random.Random("20261110:it:fill")`, cycling (logged as fills). NI: the first packet document fetched with >= 1,000
  characters; a later packet document that fails is dropped (logged); the converter's picked documents are fetched for
  the converter arm and a failure there is recorded, not a reason to reject; a failure is replaced by the next affair of
  the same cell; an NI cell is never filled from another cell. No other replacement: an affair whose documents turn
  out to be something else stays in the sample.
- **Committed after the fetch, before any label:** `data/p11/p11_draw.jsonl`, `data/p11/p11_affairs.jsonl` (ids, URLs,
  sha256, pages, characters, fetch route; never text), `data/p11/p11_fetch_log.jsonl`, `data/p11/opd_meta_p11.jsonl`
  and `data/p11/body_names_p11.json` (frozen `gegenprobe.affair.meta.vendor`), `data/p11/p11_datelists.jsonl` (dates
  without context), `results/p11/sample.json`. Texts and PDFs stay in WORK (never committed).

## 4. Fields

**IT** (definitions unchanged; the federal cell's label format):

| field | gold (what the documents print) | definition | values the arms carry | schema v0.2 |
|---|---|---|---|---|
| **answer date, with role** | `answer_present`, `answer_date`, `role` (decision / dispatch), page, quote, lenient dates, on the answer document | P1/P2 guide (`eval/gold2/GUIDE.md`, *Definitions*) | rules, converter record, pointer, latest date | `QAPair.answer_date`; `DatedEvent` |
| **author roles** | `people`: name, kind, role (sole_author, first_signatory, joint_author, co_signatory, supporter, spokesperson, other), quote | P8 guide §2 (= P10's guide); scored as (name, role) pairs by P10's scorer; P8's derived submitter category | rules, converter record, role reader, document order, OPD list (reference) | `Actor.role` |
| **instrument function** | `function`, `instrument_named` | P8 guide §5; P8 derivation `type_` (`conforms` iff the function equals what OPD's type names) | converter record | `type.instrument_function`, `type.instrument_named` |
| **text language** | `languages` of each document | P8 guide §6; P8 derivation `language` against OPD's language tag of the document | converter record | `Document.language_of_text` vs `language_tag` |

**NI**: the 17 fields of `data/schema/field_verdict_classes.json` (date_submission, date_decision, date_dispatch,
qa_pairing, related_affairs, documents_usable_text, answer_link_status, date_answer, procedural_history, type,
procedural_state, decision_outcome, submitter, co_signatories, addressed_body, government_recommendation, language).
For each, `GUIDE_P11_NI.md` §3 gives its definition and its **existing roles**, taken from the P8 guide (§§2-7), the
P1/P2 answer-date definitions and schema v0.1/v0.2's vocabularies (`other` is never offered: a value no listed role fits
is what the cell counts). The annotator reads each definition literally with "the affair" in place of "the
intervention" and "whoever brought the affair before parliament" in place of "the member(s)" and gives a **verdict**:
`fits` (a printed value fits an existing role; the role is given), `new_role` (a printed value of the field's kind fits
none; a short label is given), `not_printed` (the concept exists for this affair; these documents print no value),
`not_applicable` (the concept does not exist for this affair), `cannot_tell`. With `fits` and `new_role` the printed
value is quoted (optional for documents_usable_text, answer_link_status, language). Also labelled: `affair_kind`
(government_business, parliamentary_initiative, intervention, other, unclear; quoted) and the kind of each document
(schema v0.1's document roles).

## 5. Gold protocol (`eval/p11/packets.py`, `eval/p11/annotate.py`, the two guides)

- **Packets** (WORK only): IT in P8's packet format, rendered by the frozen P8 functions (`DOCUMENT question`,
  `DOCUMENT answer`, `PAGE n`, the parser's date list); NI with `DOCUMENT d1..d3`, `PAGE n` and the same date list
  over all documents. Opaque ids (`IT-001`..., `NI-001`...) in seeded order (`20261110:packets:<cell>`). No OPD
  metadata, number, title, names, dates, language tag, body, stratum or arm output. Text: the sha256-verified cached
  extraction every arm reads.
- **Annotators**: A1 (Claude Opus) and A2 (Claude Sonnet) label every packet of a cell blind, each in its own session,
  with `GUIDE_P11_IT.md` (which applies P8 guide §§1, 2, 5, 6 and the P1/P2 answer-date definitions unchanged) or
  `GUIDE_P11_NI.md` (derived from P8's: its definitions per field, plus the verdicts). They may read only their guide,
  the guide sections it names and their packets; never `data/p11/`, `results/p11/`, a key or an arm output (the arms
  run after the merge). Every file must pass `python -m eval.p11.annotate selfcheck <A> <id>` (closed vocabularies;
  every quote verbatim, whitespace-insensitive, on the page it names; a people quote contains the name's last word;
  P1's answer-date check). The lead launches them; no human labels.
- **Disagreement keys**: IT answer_date (the printed date or null, P1's key), people (P10's key: the two (name, role)
  lists differ under P10's one-to-one matcher, or P8's derived submitter category differs), type and language (P8's
  derived categories, with OPD's metadata, which the annotators never see). NI: per field the verdict; affair_kind its
  value.
- **Tie-break**: the disputed fields go to A3 (Claude Opus), who sees the packet and the two labels of those fields as X
  and Y in seeded random order (`20261111:<cell>`) and labels them anew. Gold per field: A1 where A1 and A2 agree, else
  A3. The IT answer date's lenient set is P1's. For an NI field both annotators judge `fits`, the gold role is A1's and
  role agreement is reported; for agreed `new_role` both labels are kept.
- **Committed after each cell's merge**: `data/p11/p11_<cell>_gold.jsonl`, `data/p11/annotations/<cell>_{A1,A2,A3}.jsonl`
  (quotes replaced by sha256 and span; notes stay in WORK; NI new-role labels are the annotators' own short words and
  are kept), `data/p11/annotations/<cell>_a3_order.json`, `data/p11/p11_<cell>_key.jsonl`,
  `results/p11/p11_<cell>_agreement.json` (raw agreement and Cohen's kappa of A1 vs A2 per field; fields decided by A3;
  IT people pair F1 A1 vs A2; NI role agreement). Session times recorded as for every earlier set.

## 6. Arms (`eval/p11/arms.py`; they read the cached texts the packets show and never a label; they refuse to run before the cell's gold is merged)

**The converter** in both cells is the existing whole-affair command, `gegenprobe.affair_cli.build`, rules_only mode,
unchanged (OPD metadata first, the frozen rules and P1 answer-date cascade, product post-processing, the v0.2 carry, the
role rules with role_consistency, Q/A pairing, document parts, validation by the v0.2 Pydantic model), with two inputs
pinned so that it reads what the annotators read and makes no request: OPD's rows are the vendored snapshot rows, and
`affair_cli.fetch_doc` returns the documents fetched in the draw (a document whose fetch failed raises its recorded
typed failure). IT names the two documents; NI lets the converter pick by its own pairing rule.

| IT field | rules / converter (no model) | Apertus (gateway) | no-model baselines |
|---|---|---|---|
| answer date | P1 rules arm `convert.rules.answer_date`; the converter record's `qa[0].answer_date` | P1 pointer `convert.pointer.answer_date`, θ = 10.395 (`data/convert/theta/publicai_swiss-ai_apertus-v1.5-8b.json`), anchors from the rules, through the review mode's BuildGuard | latest date the converter's lattice finds on the document typed as the answer |
| author roles | `convert.roles.extract` (P10's arm b); the record's actors | P10's role reader `convert.roles_pointer.read`, frozen configuration `data/p10/p10_config.json` (tau 0.98, tau_first 0.30, cue rule), prompt language it, on `convert.role_candidates` | P10's post hoc document-order baseline (`eval.p10.posthoc_baselines.order_pairs` on the candidates); OPD's contributor list by P10's `opd_pairs(first_and_co)` as a reference row (OPD's names, not located) |
| instrument | the record's `instrument_function`, `instrument_named` | — | — |
| language | the record's `language_of_text` | — | — |

**NI arm**: the converter's status per affair (a validated v0.2 record, or its typed failure: no_documents,
invalid_record, source_gone, ...) and, per schema field, what a valid record carries (value; value whose decided /
dispatched role the record does not split; typed null and reason; empty list and reason; nothing), cross-tabulated with
the gold verdict. Valid records are written to `results/p11/ni_records_v0_2.jsonl` (IT: `it_records_v0_2.jsonl`).

**Model route**: `eval.arms.backend("gateway:swiss-ai/apertus-v1.5-8b:2a-p11:1.0")` (the 70B weights Public AI serves
under that name, the route of P1/P2 and P10), tag `2a-p11`, **cap USD 1.00 for both model arms together**; the date
pointer runs first, then the role reader. Every response is cached by hash in `data/model_cache` (replayable with
`GP_OFFLINE=1`).

**In-sample status, reported per IT stratum** (`in_sample_for` in the probe): Lugano's layouts were used to write the
post hoc role rules (roles-2), so the rules arm is in-sample there; Bellinzona is one of the role reader's six
development parliaments (PREREG10 §7), so the role reader is in-sample there; the date rules' coverage is read from
`data/convert/rules_coverage.json`. Nothing is excluded for it; the tables say it.

## 7. Reporting (`eval/p11/score.py` -> `results/p11/p11_it_tables.json`, `results/p11/p11_ni_tables.json`)

Labelled EXPLORATORY everywhere; per stratum and overall; counts with Wilson 95% intervals.
- **IT answer date**: gold distribution (answer present, printed or null, role); per arm the frozen `eval.score.summarise`
  counts, strict and lenient (exact, false null, misattributed, fabricated, values on gold-null).
- **IT author roles**: per arm pooled pair precision, recall and F1 with Wilson intervals, affairs exactly right (P10's
  scorer); P8's derived submitter category (share in E with Wilson).
- **IT instrument function, text language**: P8 categories (determinable / undeterminable by reason, share in E); the
  converter record's function, instrument name and language of text against the gold.
- **IT documents by route**: how many were read from the source and how many from OPD's copy; type source.
- **NI per field**: verdict counts by type, by language and by stratum; shares with Wilson of `needs_new_role`,
  `fits_existing_role`, `not_printed` and `not_applicable` among determinable affairs (excluding `cannot_tell`); the
  existing roles used; every new-role label with its affair; the same restricted to affairs whose gold `affair_kind`
  matches their OPD type.
- **NI affair kind and documents**: gold affair_kind by OPD type, share conforming with Wilson; document kinds.
- **NI converter**: statuses by stratum; valid v0.2 records with Wilson; gold verdict by record status per field.
- Agreement files as in §5.

## 8. Stop rules

1. **Fetch path**: a robots.txt disallow or an unreadable robots.txt (fail-closed) stops a request to the source; the
   document is then read from OPD's own copy on files.openparldata.ch, or the fetch fails (and is replaced, §3).
   api.openparldata.ch is never requested (`net.FORBIDDEN`); OPD data comes only from files.openparldata.ch and the
   committed snapshot. Nothing is fetched another way.
2. **Lock**: `draw` and `fetch` refuse unless LOCKP11 is committed and every hashed file and WORK input is unchanged;
   each runs once.
3. **Shortfall**: an IT body is filled from the other frame bodies (§3); an NI cell is never filled; a remaining
   shortfall is reported, with its n.
4. **Served build**: a date-pointer response from a fingerprint θ was not fitted on stops the date pointer
   (`BuildMismatch`); a ServedModelMismatch stops the role reader; fingerprints the role reader's development did not see
   are reported. An arm that stops is reported as not run or partial; the no-model arms stand.
5. **Budget**: the gateway's cap (USD 1.00, tag `2a-p11`) refuses further calls; an arm cut off is reported as partial
   with its n (affairs not reached are listed, never imputed).
6. **Frame checks**: IT, if both annotators label the answer document as not the executive's answer for more than half
   of the affairs, the frame is reported as invalid and no arm is scored as a result. NI, if the gold affair_kind is
   `intervention` for more than half of a type's affairs, that type's strata are reported as OPD mistyping, not as
   evidence about government business or initiatives (`stop_rules` in the tables).
7. **No re-draw, no re-labelling** after a merge; every outcome is reported, including empty cells.

## 9. Order of operations (phase 2)

    cd track_2a        # PYTHONPATH=src:. and .venv/bin/python throughout
    python -m eval.p11.selftest                          # must print "selftest OK"
    # commit eval/p11/ (without LOCKP11) and results/p11/pool_probe.json
    python -m eval.p11.lock_p11 write                    # -> eval/p11/LOCKP11; commit it alone (= registration time)
    python -m eval.p11.draw draw                         # no network -> data/p11/p11_draw.jsonl
    python -m eval.p11.draw fetch                        # network -> data/p11/*, results/p11/sample.json, packets
    # commit data/p11/ and results/p11/sample.json before any label
    # IT: A1, A2 label .work/p11/packets/IT-*.txt -> .work/p11/ann/{A1,A2}/ (each file: annotate selfcheck <A> <id>)
    python -m eval.p11.annotate verify it A1 && python -m eval.p11.annotate verify it A2
    python -m eval.p11.annotate a3packets it             # A3 on .work/p11/a3/IT-*.json -> .work/p11/ann/A3/
    python -m eval.p11.annotate verify it A3 && python -m eval.p11.annotate merge it      # commit the IT gold
    # NI: the same with `ni`                             # commit the NI gold
    python -m eval.p11.arms it-offline
    python -m eval.p11.arms it-pointer --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p11:1.0
    python -m eval.p11.arms ni-offline
    python -m eval.p11.score it && python -m eval.p11.score ni   # commit results/p11/, data/p11/it_candidates.jsonl,
                                                                 # the new data/model_cache entries

## 10. Not allowed after LOCKP11

Any change to the hashed files (frames, type rule, strata, quotas, seeds, fetch path, fields, guides, arms, scoring,
stop rules) or to the reused frozen code. A later change is listed in `eval/p11/DEVIATIONS_P11.md` with its effect.
