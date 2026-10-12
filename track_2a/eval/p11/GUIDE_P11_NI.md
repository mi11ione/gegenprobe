# Annotation guide P11-NI: does each field of the affair schema hold for this affair?

You label what the documents of one parliamentary affair PRINT, and judge, field by field, whether a schema built for
members' interventions can hold this affair. Never use outside knowledge, memory, the internet, other packets, other
annotators' files or anything in the repository other than this guide, the guide sections it tells you to read, and
your packet. You do not know, and must not try to find out, which parliament, sample cell or hypothesis a packet
belongs to.

The schema has 17 fields. Each was defined for interventions (motions, postulates, interpellations, written questions),
and each value it holds carries a **role**: which of several possible meanings the value has (for example, an "answer
date" is the executive's decision date or the date of its letter). The existing roles below come from the P8 guide
(`eval/p8/GUIDE_P8.md`) and the P1/P2 guide (`eval/gold2/GUIDE.md`, *Definitions*); you may read those two files for
their wording, nothing else. This packet's affair may be something other than an intervention. Your job is to say, for
each field, whether its existing roles can hold what these documents print.

## The packet

`.work/p11/packets/NI-<nnn>.txt` holds:
- `=== DOCUMENT d1 ===`, `=== DOCUMENT d2 ===`, `=== DOCUMENT d3 ===`: up to three documents the data source links to
  the affair (in the source's order, not by importance; text extracted from PDFs: expect odd line breaks, hyphenation,
  repeated headers);
- `=== PAGE n ===` markers;
- `=== DATES ===`: every distinct date a date parser found in the documents (letters D01, ...), to help you find
  printed dates.

The source may link documents that are not about the affair, or only part of its documents. Label from what is there.

## The file you write

One JSON file per packet: `.work/p11/ann/<A>/NI-<nnn>.json` (`<A>` is your annotator code). Exactly these keys:

```json
{"id": "NI-001",
 "affair_kind": {"value": "government_business|parliamentary_initiative|intervention|other|unclear",
                 "doc": "d1", "page": 1, "quote": "verbatim, <= 200 characters"},
 "documents": {"d1": "message", "d2": "report"},
 "fields": {
   "date_submission": {"verdict": "fits|new_role|not_printed|not_applicable|cannot_tell",
                       "role": "one of the field's existing roles, only with fits; else null",
                       "new_role": "a short label of the role (<= 80 characters), only with new_role; else null",
                       "doc": "d1", "page": 1, "quote": "verbatim, <= 200 characters"},
   "...": "one entry for each of the 17 fields of section 3"},
 "notes": "short reasons; anything ambiguous"}
```

- `documents`: one entry per document of the packet, its kind: `question` (an intervention's text as lodged),
  `answer` (an executive's answer to an intervention), `decision` (a decision of parliament or of the executive, e.g.
  a decree, an extract of minutes stating a decision), `message` (the executive's message, report and proposal to
  parliament: Botschaft, Vorlage, Bericht und Antrag, Ratschlag, message, préavis, messaggio), `report` (a report of a
  committee or another body), `minutes`, `agenda`, `annex`, `publication` (an official gazette or law collection
  entry), `placeholder` (no real content: a cover page, an error page), `other`.
- `fields`: exactly the 17 keys of section 3. With `fits` and `new_role`, `doc`, `page` and `quote` show the printed
  value; for the three fields marked *(evidence optional)* they may be `null`. With `not_printed`, `not_applicable` and
  `cannot_tell`, `role`, `new_role`, `doc`, `page` and `quote` are all `null` (say why in `notes`).
- Every `quote` is copied verbatim from the page you name (whitespace may differ; nothing else), at most 200 characters.

After writing the file run

    cd track_2a && PYTHONPATH=src:. .venv/bin/python -m eval.p11.annotate selfcheck <A> NI-<nnn>

and fix everything it reports until it prints `OK`. Run no other command.

## 1. `affair_kind`

What the documents show the affair to be, judged from what they print (not from a title alone):
- `government_business`: the executive brings a matter before parliament: a bill, decree, credit, budget, plan,
  report or other proposal of the executive for parliament to decide or take note of.
- `parliamentary_initiative`: a member, group or committee of parliament proposes that parliament itself adopt or
  amend a law, decree or regulation (drafted, or in general terms for parliament or one of its committees to draft).
- `intervention`: a motion, postulate, interpellation or written question of members, with or without the answer.
- `other`: something else (a petition, an election, a popular initiative, a report of parliament's own, ...); say what
  in `notes`.
- `unclear`: the documents do not let you tell (no quote).
Quote the words that show it.

## 2. The verdict of a field

Read the field's definition and its existing roles (section 3) **literally, with "the affair" in place of "the
intervention" and "whoever brought the affair before parliament" in place of "the member(s)"**. Then:
- `fits`: the documents print a value of this field, and an existing role describes it as written. Give that `role`
  (for a field with several printed values: the role of the first one in document order, if every printed value fits
  some existing role) and quote the value.
- `new_role`: the documents print a value of this field's kind, but no existing role describes what it is (as written,
  without stretching the words). Give a short label of the role it plays (e.g. "date the executive adopted its own
  proposal") and quote it. If any printed value of the field needs a new role, the verdict is `new_role`.
- `not_printed`: the field's concept exists for this affair (an affair of this kind can have such a value), but these
  documents print none.
- `not_applicable`: the field's concept does not exist for this affair (there is nothing such a value could be). Say why
  in `notes`.
- `cannot_tell`: you cannot decide (say why in `notes`).

`not_printed` and `not_applicable` differ: a government bill that names no related affair has `related_affairs:
not_printed` (it could have named one); a field that presupposes something this affair does not have (e.g. an answer
by the executive to a member, if no member asked anything) is `not_applicable`.

## 3. The 17 fields and their existing roles

1. **`date_submission`**: the date the affair was brought before parliament. Roles (P8 §3):
   `signed` (the date of the text that brings the affair: a place-and-date line, a date next to the signature(s));
   `lodged` (printed as the date it was lodged, submitted, received or registered; a receipt stamp);
   `session_lodged` (printed as the sitting at which it was handed in);
   `cited` (the date by which a heading or another text names the affair without saying what happened that day,
   e.g. "Interpellation vom 12. März 2024").
2. **`date_decision`**: the date on which the executive decided its answer to, or decision on, the affair, as printed.
   Role (P1/P2 *answer_date*, role decision): `decision` (e.g. "RRB-Nr. 879/2024 vom 28. August 2024", "Sitzung vom",
   "Ainsi adopté en séance du", "risoluzione n. … del"). Never a lodging date, a footer or a date in the content.
3. **`date_dispatch`**: the date of the executive's answer letter or document. Role (P1/P2, role dispatch): `dispatch`
   (its place-date line or signature date, e.g. "Bellinzona, 4 aprile 2022").
4. **`qa_pairing`**: the text that brings the affair asks separate questions of the executive, and the executive's
   text answers them one by one. Role: `question_answer` (question n answered by a passage of the executive's text).
5. **`related_affairs`**: another affair the documents name, with its relation to this one. Roles: `answers`,
   `answered_by`, `follows_up`, `replaces`, `replaced_by`, `joined_with` (handled together), `same_subject`, `cites`,
   `implements` (this affair carries out what the other asked for), `counter_proposal_to`.
6. **`documents_usable_text`** *(evidence optional)*: each document's text can be read (not a scan without text, not a
   placeholder). Role: `usable`. `not_printed` when no document of the packet has readable text.
7. **`answer_link_status`** *(evidence optional)*: where the executive's written answer to the affair is. Roles:
   `attached` (one of the documents is the executive's written answer to this affair: give it as `doc`), `oral` (the
   documents say it was answered orally). `not_printed`: the affair calls for an answer by the executive but none of
   the documents is it.
8. **`date_answer`**: the date of the executive's answer to the affair (P1/P2 *answer_date*). Roles: `decision`
   (the decision date, preferred when printed), `dispatch` (else the answer's place-date line).
9. **`procedural_history`**: the dated steps of the affair's own procedure. Roles: `submitted`, `signed`, `lodged`,
   `received`, `announced` (read out or announced in parliament), `answer_decided`, `answer_dispatched`, `answered`,
   `scheduled` (put on an agenda), `debated`, `referred_to_committee`, `decided` (parliament decided on it), `closed`
   (written off, settled), `withdrawn`, `published`, `entry_into_force`, `deadline`, `referendum_deadline`,
   `popular_vote`, `later_step` (another later step of parliament: taken note of, urgency granted, deadline extended).
10. **`type`**: what the text that brings the affair before parliament asks for (P8 §5 `function`). Roles: `mandate`
    (charges or invites the executive to act: to draft or present a law, decree, credit or measure, or to take a
    measure), `examine_report` (asks the executive to examine and report or propose, without charging it to act),
    `questions` (asks questions for the executive to answer and requests no action), `direct_decision` (proposes a
    decision that the parliament itself takes on this text: a drafted article, an amendment of a regulation or law, a
    budget change put directly to the vote; not a request to the executive).
11. **`procedural_state`**: the state the documents show the affair in. Roles: `submitted`, `pending_answer`,
    `answered`, `scheduled`, `in_committee`, `debated`, `referred` (referred to the executive), `decided`, `closed`,
    `withdrawn`, `lapsed`.
12. **`decision_outcome`**: parliament's decision on the affair. Roles: `adopted`, `rejected`, `referred`,
    `converted_to_postulate`, `partially_adopted`, `written_off`, `not_written_off`, `acknowledged` (taken note of),
    `withdrawn`, `lapsed`, `returned` (sent back), `no_decision`, `pending`.
13. **`submitter`**: who brought the affair before parliament, and in what role (P8 §2, its wording for `people`).
    Roles: `sole_author`, `first_signatory`, `joint_author`, `spokesperson` (a person who signs or speaks for a group
    or committee that is the author).
14. **`co_signatories`**: who else signed or backed it (P8 §2). Roles: `co_signatory`, `supporter`, `joint_author` (the
    further authors of a joint text), `spokesperson`.
15. **`addressed_body`**: whom the affair asks to act or to answer (P8 §4). Roles: `executive`,
    `executive_member_or_department`, `parliament` (the parliament itself, its bureau or presidency, asked to take a
    decision itself), `committee`, `administration`.
16. **`government_recommendation`**: what the executive recommends parliament do with the affair (P8 §7 `act`).
    Roles: `on_referral` (how parliament should decide on taking the affair up: accept, adopt, refer, reject, convert,
    partially, or accept and write off at once), `on_fulfilment` (the executive's report on an affair parliament has
    already adopted or referred, asking parliament to approve the report, adopt the act it proposes, or write the affair
    off).
17. **`language`** *(evidence optional)*: the language(s) the documents' texts are written in (P8 §6). Role:
    `text_language`.

## Tie-break (A3 only)

You receive `.work/p11/a3/NI-<nnn>.json` with the fields two annotators judged differently (`fields`; `affair_kind`
among them if they differ there) and their two labels as X and Y (order random). Read the packet and this guide, then
write `.work/p11/ann/A3/NI-<nnn>.json` with exactly the keys `id`, `notes`, `fields` (holding exactly the disputed
fields of section 3, each in the format above) and, if `affair_kind` is disputed, `affair_kind`. You may agree with X,
with Y, or with neither. Run the selfcheck with `A3`.
