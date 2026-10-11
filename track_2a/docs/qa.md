# Questions, answers, people, recommendation and reasoning (P5)

`src/gegenprobe/qa/` reads an affair's two documents (the member's text and the executive's answer). It fills, with a page
and character span for every value:

- **Q/A pairs (`QAPair.items`, schema `QAItem`).** The member's numbered questions, and the passage of the answer that
  replies to each one.
- **People (`Actor`).** The submitter and the co-signatories.
- **The executive's recommendation (`GovRecommendation`).** The printed sentence that states it is the evidence.
- **The reasoning.** The span of the executive's substantive reply.

The rules decide first. Apertus is used only as a closed-set pointer on what the rules leave open. It picks which numbered
question an answer paragraph replies to (or none), which printed candidate sentence states the recommendation (or none),
or which printed name is the submitter (or none). It never generates a value. No earlier locked module is changed. The
module is evaluated by the pre-registered test P5 (`eval/prereg6/PREREG6.md`, LOCK6 at db339eb).

## How it works

| step | rule | where the model may point |
|---|---|---|
| questions | Line-initial marker chains (`1.`, `1)`, `Frage 1`, `a)`, bullets) after a question cue ("folgende Fragen", "questions suivantes", "seguenti domande", "wird beauftragt" …). The chain whose items carry question marks wins. Detached markers (a block of `2.` `3.` `4.` and then the texts, as pdftotext often prints them) are re-attached in order. A list without markers counts as items when each item ends with "?" after a cue. A motion or postulate gets its demand paragraph as one item. | — |
| reply (reasoning) | Starts after the reprint of the member's text or after a reply cue ("wie folgt beantwortet", "Réponse du Conseil d'Etat", "risponde come segue"). Ends before the closing formula ("Im Namen des Regierungsrates", "AU NOM DU CONSEIL D'ETAT", "Per il Consiglio di Stato" …) or before a closing recommendation sentence. | — |
| pairing | Answer headings, in order of preference: "Zu Frage 2", "Zu den Fragen 1 und 3", "Frage 2", "Réponse à la question 2", "Domanda 2", inline "Concernant la question 6, …", "In merito alla domanda 2", or `2.` when it is followed by the reprint of question 2. If there are no headings, the reprinted questions are used. The repeated question text is cut off the answer by token alignment. A heading whose reply is empty is joint with the next one (`joint_with`). | For each unanchored paragraph of the reply: question 1..k or null |
| people | In order: a member list with a "(Sprecher/in)" / "(porte-parole)" marker; the title line "<Type> [von] <Name> und <Name> betreffend"; "von <Name> (Partei, Ort)"; an author cue ("Signataire :", "eingereicht von", "presentata da" …); the signature block after the last question (comma lists, one name per line, initials, names wrapped over a line or page break); the answer's title ("à l'interpellation <Name> et consorts"). | When no rule finds a submitter: the printed person-name strings of the question document, or null |
| recommendation | For an interpellation or a question, not_applicable, with the type word as evidence. Otherwise, sentences with a proposal verb (beantragt, propose, invita …) and an outcome word map to accept / reject / partial / convert / none ("abzuschreiben", "classer"). A header "Antrag Regierungsrat: … Ablehnung" and "<Regierungsrat> lehnt … ab" also count. All candidates agree → rule value. They conflict → residue. | Over the candidate sentences, or null (= none) |

A span can cross pages. The schema value carries the head of the span on its start page (at most 400 characters, as
`quote`) and the whole extent in `context` ("extent p2:120 - p3:540"). Every value is re-checked against its span
(`gegenprobe.validate.spans.recheck`). P5 had 0 failures over 517 rule values (H5).

## P5: fresh affairs from parliaments the converter was not developed on

The **dev set** was 38 affairs from BS, ZH, LU, Zürich city, BE, VD, GE, Vernier and TI. The rules were written on it
and θ was fitted on it.

The **P5 set** was 40 affairs drawn after the lock from 10 other parliaments:
- German: Basel-Landschaft, Schaffhausen, Luzern city, Riehen, Wädenswil.
- French: Lausanne, Valais (French documents), Collombey-Muraz (the reserve for Fribourg city, whose postulates are
  HTML pages).
- Italian: Lugano, Graubünden (Italian documents).

The labels come from blind Claude annotators: A1 (Opus) and A2 (Sonnet), with A3 (Opus) deciding 2 disputed submitter
fields. A registered independent Qwen-SEA-LION check is reported in `results/eval6/p5_qwen_check.json`. There were 176
gold answer spans and 11 gold-null answers.

| arm | Q/A recall | Q/A precision | spans on gold-null | questions (recall) | submitter | recommendation | reasoning |
|---|---|---|---|---|---|---|---|
| rules only (default) | 118/176 | 118/143 | 3 | 167/187 | 12/40 | 34/40 | 37/40 |
| rules + pointer (θ fitted on dev, primary) | 118/176 | 118/143 | 3 | 167/187 | 24/40 | 36/40 | 37/40 |
| rules + pointer, θ_pair = 0 (secondary) | 128/176 | 128/165 | 5 | 167/187 | 24/40 | 36/40 | 37/40 |
| free-generation Apertus, null allowed | 50/176 | 50/113 | 6 | 98/187 | 34/40 | 4/40 | 6/40 |
| answer n = paragraph n (trivial) | 7/176 | 7/171 | 9 | 167/187 | 16/40 | 31/40 | 38/40 |
| answer n = whole reply (trivial) | 3/176 | 3/172 | 10 | 167/187 | 16/40 | 31/40 | 38/40 |

The registered hypotheses (`results/eval6/hypotheses6__p5__publicai_swiss-ai_apertus-v1.5-8b.json`):

- **H1 (primary).** Rules-only pairing is in the **partial** tier: precision 0.83 [0.75, 0.88] and recall 0.67
  [0.60, 0.74]. The bar for "extractable unattended" was a precision lower bound of 0.85 and a recall lower bound of 0.60.
- **H2.** The rules beat the paragraph-order baseline: 116 answers right only for the rules, 5 only for the baseline,
  one-sided exact McNemar p ≈ 8·10⁻²⁹.
- **H3.** The pairing pointer at its dev-fitted θ (-47) made **no suggestion** on the 36 residue answers. Verdict: no
  measurable gain. The recommendation pointer got both of the 2 recommendation residue cases right.
  - **H3b (secondary).** With θ_pair = 0 the pointer finds 10/36 residue answers (0.28 [0.16, 0.44]). Its
    suggestions are right in 10/22 cases (0.45 [0.27, 0.65]); 2 of them sit on gold-null answers.
- **H4.** The closed-set system beats free generation on Q/A pairing: 79 answers right only for the closed-set system,
  11 only for free generation, p ≈ 4·10⁻¹⁴. Free generation's precision is 0.44. Of its quoted values, 87 cannot be
  found in the documents, and 3 replies do not parse.
- **H5.** 0 span re-check failures (rules only: 517 values; the primary pointer arm: 533).
- **Verdict (S1 and S2):** supported, at the partial tier.

**Independent check (registered; `results/eval6/p5_qwen_check.json`).** Qwen-SEA-LION-v4-32B-IT labelled all 40
affairs blind with the same guide and the same packets.
- **Quality of its labels.** Only 7 of its 40 label files pass the verbatim quote check. Its answer spans match the Claude
  gold in 96/176 answers. It agrees with the gold on the question count in 30 affairs, the answer style in 29, the
  recommendation in 28 and the submitter in 33.
- **H1 with Qwen's labels as gold.** The rules' pairing scores 65/116 recall and 65/105 precision, so H1 would fall to
  "not yet".
- **H1 on the consensus subset** (the 96 gold answers whose Qwen span matches). The rules find 65/96. By the registered
  definition, the precision on this subset counts every prediction for a dropped answer as wrong, so it is not
  informative.
- **Reading.** The registered H1 verdict rests on the Claude gold. The non-Anthropic check is too noisy to confirm it or
  to overturn it.

## What P5 shows (post hoc, `results/eval6/p5_posthoc.json`)

- **Pairing transfers best where answers repeat or number the questions.** Rules-only Q/A recall was 21/22 in Riehen,
  20/24 in Wädenswil and 17/20 in Lugano. It was 0/11 in Valais. The cause is the language of the documents, not the
  answers: all 11 scored answers sit in two affairs whose German answers number their replies (1.–6. and 1.–5.), but the
  question documents are the French versions. The frozen rule accepts bare numbers only where the answer reprints
  question n in the member's words, which cannot happen across languages (see "Question and answer in different
  languages" below; pairing by number alone finds 11/11, post hoc). Basel-Landschaft was 14/31, with precision 14/30.
- **Rules-only submitter detection does not transfer:** 12/40 on P5, against 36/38 on dev. There were 14 affairs
  without a value and 14 with the wrong person. The pointer over printed names raises it to 24/40. Free generation names
  the right printed person in 34/40, but without a span or a closed set. Submitter detection stays a review field.
- Questions (167/187), reasoning (37/40) and recommendation (34/40 by rules, 36/40 with the pointer) hold up across the
  new parliaments.

## Question and answer in different languages (finding for OPD, post hoc, `results/findings/cross_language_links.json`)

How the Valais pairs came about: P5's Valais quota fixed the language of the question document (French), and the P3
pairing convention takes the lowest-id answer document. In all 4 Valais P5 affairs that is the German file
(`INT_…_ANT_DE.pdf` / `_ANT_D1.pdf`) next to the French question (`INT_…_DEP_Final_FR.pdf`). OPD links a German
question too in all 4. It links a French answer in 2 of them (87651, 247619), with a higher id than the German one, and no
French answer in the other 2 (295461, 252838).

Across OPD's exports (`python -m gegenprobe.findings.cross_language`; committed census tables, no model, no network):

- **Definitions.** An affair counts when it is an Interpellation, Motion, Postulate, Question or Question time, and OPD
  links at least one question document and one answer document to it. Roles follow the frozen P3 pairing
  (`eval/gold3/sample.py` `pair_type`, which reads OPD's document name and category). Language comes from OPD's
  `language` tag on the document. The file-name suffix (`_DE.pdf`, `_FR.pdf`, `_D1.pdf`, `-fr.pdf` …) and stop-word
  counts on the cached PDF text serve as cross-checks.
- **Coverage.** 23,471 affairs have both roles. In 1,999 of them, all in 10 parliaments, both roles carry a language
  tag. Elsewhere OPD leaves documents untagged, which is mostly harmless in a one-language parliament.
- **No same-language pair at all: 6 affairs.** Three are in Bern (German question, French answer; 39369, 130479,
  130732). The other three are in Valais. There the file names confirm the tags: on the 290 Valais affairs where both
  signals are available, they agree in all 290 (287 same language, 3 different):
  - Valais affair 2020.09.253 is split over two OPD affairs, 86774 and 176868. Each holds one language of the question
    and the other language of the answer.
  - OPD affair 86823 (postulate 2020.11.336) carries the French question file of interpellation 2020.11.350.
- **The lowest-id question and answer differ in language in 214 of the 1,999 affairs (10.7%):** Graubünden 148/341,
  Valais 63/313, Bern 3/7. Where OPD links both language versions, the consumer has to match the languages itself.
  Anyone who takes one document per role without doing so gets a cross-language pair, as our P5 sampler did.
- **Text cross-check.** Of the 209 gold-set affairs (P3, P3b, P5 dev, P5, P8) whose PDF text is cached, 208 have a
  detectable language on both documents. Of these, 15 pair a question and an answer in different languages: Graubünden
  7, Valais 5, Bern 2, Fribourg canton 1. On the 141 documents that have both an OPD tag and a detected text language,
  the tag names another language than the text in 3 cases. All 3 are in the canton of Fribourg (P8's tag finding).

**Valais re-scored by question number (post hoc, not registered; the registered result stays 0/11).** Pair answer n with
the numbered paragraph "n." inside the frozen reply span when all k numbers appear in order. Skip a reprinted question up
to its line-final "?". Drop the same-language reprint check. This finds 11/11 gold answers with 11 predictions (IoU ≥ 0.5;
per-answer IoU 0.57–1.0). The two affairs whose answers are running text get no prediction. The rule is language-independent.
It was applied only to Valais, the one P5 parliament whose question and answer differ in language. It is a candidate for
the converter, to be tested on fresh affairs before it counts.

## Commands

```
python -m eval.gold6.run6 p5 --backend none                                        # rules + trivial baselines (no model)
python -m eval.gold6.run6 p5 --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p5-test:1.5   # + pointer arms, free generation
python -m eval.gold6.hypotheses6 p5 publicai_swiss-ai_apertus-v1.5-8b              # registered hypotheses
python -m eval.gold6.posthoc6                                                      # post-hoc breakdowns
python -m eval.gold6.qwen6_run && python -m eval.gold6.qwen6 analyse               # independent Qwen check
```

## Run it on your own affair

```
python -m gegenprobe.qa_cli --question Q.pdf --answer A.pdf [--affair-type TYPE] [--lang de|fr|it] [--json]
                            [--body KEY] [--anchors FILE] [--explain]
python -m gegenprobe.qa_cli --opd-text-question Q.txt --opd-text-answer A.json [--affair-type TYPE] [--json]
```

Each document is a PDF (a local path or a URL) or OPD's stored text (`--opd-text-question` / `--opd-text-answer`). The
stored text can be plain text or a docs-export JSON row with a `text` field; the row's `id` becomes the document id
`opd:<id>`. A URL is fetched the same way as by `convert`: politely, with robots.txt matched under RFC 9309, into the
same cache. Either document may be left out.

- **OPD's stored text has no page breaks.** OPD extracts the whole PDF into one string, so the stored text is read as
  **one page**. Every span then says page 1, and its character offsets are offsets into the stored text as given. If the
  text contains form feeds (`\f`), they are taken as page breaks. The output says which case applies, per document.
- **Rules only.** No model is called (`model_calls` is 0). Whatever the rules leave open is listed under "left open" (in
  `--json`: `left_open`): answers that no heading or reprinted question ties to a question, a submitter no rule found,
  conflicting recommendation sentences, and a recommendation no rule found on a layout the rules do not cover (or whose
  coverage was not checked). The pointer arm is run only by `eval/gold6/run6.py`; its θ is fitted to one
  served build.
- **`--affair-type`** takes the same values as `convert`: a vocabulary key, a DE/FR/IT/EN label, OPD's harmonised
  name, or an OPD type name that OPD maps to one harmonised type (`Auftrag` is a motion; the list is
  `data/convert/affair_type_aliases.json`), plus the settings file's `affair_types` for `--body`. Interpellation, Question
  and Question time make the recommendation `not_applicable` when the question document does not name its type itself.
  An unknown value is an error.
- **`--body KEY`** checks rule coverage as `convert` does (`rules_coverage` in `--json`). For a body outside
  `data/convert/rules_coverage.json` the CLI prints a warning, every value a rule decided is flagged (`needs_review`,
  `review_reasons`, and "needs review" in the report), and a recommendation no rule found is `no_rules_for_body` (listed
  under "left open"), not `not_in_document`. Without `--body`, an open recommendation stays `not_in_document` but is
  listed for review: the tool cannot know whether the layout was understood.
- **`--anchors FILE`** is the per-parliament settings file shared with `convert --anchors` (docs/convert-your-own.md,
  "One settings file per parliament"). `qa_cli` uses its `recommendation` phrases (same format, labels and
  `(?P<phrase>…)` span), its `affair_types` and its `confirm_rules`. It also reads four keys that only it uses:
  `closing` (lines that open the closing block), `reprint_headings` (headings of the reprinted member's text),
  `questions_end` (lines that end the member's question list, on top of the built-in "Begründung" / "Motivation" /
  "Motivazione" / "Exposé des motifs" / co-signature table headings), all lists of regular expressions, and
  `prefer_answer_title` (`true`: the people come from the answer's title line). Example for the Grosser Rat Thurgau:

  ```json
  {"bodies": {"TG": {
    "recommendation": [{"id": "tg_nicht_erheblich", "label": "reject",
                        "pattern": "beantragen wir Ihnen[^.]{0,160}?(?P<phrase>nicht erheblich zu erkl(ä|a)ren)"}],
    "closing":        ["^\\s*(Der|Die) Pr(ä|a|\\.)[^\\n]{0,40}$"],
    "questions_end":  ["^\\s*Mitunterzeichnerinnen"],
    "prefer_answer_title": true,
    "confirm_rules":  ["heading_frage", "answer_title"]}}}
  ```
- **`--explain`** prints, per field, the frozen rule that decided, every post step tried (below) with what it did, and
  each anchor tried (stderr; `--json` adds an `explain` key).
- **A typed null is printed as one.** The report says `recommendation: null (no_rules_for_body: …)` or
  `null (not_in_document: …)`; `none` is only printed for a recommendation value `none` (a write-off phrase) with its
  evidence sentence.
- **Pairing needs the question document.** Without it there are no numbered questions to pair, so the answer comes out
  as one reply (`answer_style` `global`).
- **Output.** The default output is a short report: each question and its answer with page:character spans, the
  submitter and co-signatories, the recommendation with its evidence sentence, and the reasoning span. `--json` adds the
  flat view, the validated schema v0.1 records (`QAItem`, `Actor`, the recommendation, the reasoning), the rules that
  decided and `left_open`.
- **Exit codes.** 0: extracted. 2: bad input. That covers an unknown `--affair-type`, no document, a file that is not a
  PDF (the message points to `--opd-text-*`), and a document that could not be fetched or read. The last case prints the
  same typed kinds as `convert` (`file_not_found`, `robots_disallowed`, `not_a_pdf`, …).

### What `qa_cli` adds on top of the frozen extractor

The extractor in `src/gegenprobe/qa/` is frozen by LOCK6, and the P5 numbers above are its numbers. `qa_cli` runs it and
then an unlocked post-processing layer, `src/gegenprobe/qa_post.py`. It fixes what a Solothurn developer met in a user test
and a Thurgau developer met in a later one. The layer reads the frozen result and the original text; it never calls a model, and every value it writes is a
span of the original text that re-checks. Steps, in order:

| step | what it does | rule id |
|---|---|---|
| questions end | The member's question list ends at the reasoning heading ("Begründung", "Begründung:", "Motivation", "Motivazione", "Exposé des motifs", "Développement"), at a co-signature table heading ("Mitunterzeichnerinnen und Mitunterzeichner", "Name / Vorname", "Unterschriften") or at a line matching the settings file's `questions_end`. The heading must come after the first question. A question that runs into it is cut before it, and a numbered item after it is not a question. A heading that further questions with "?" follow (a reason printed under each question) does not end the list. A trailing item of a question list with no "?", under 60 characters and with characters no printed text has (`^ < > \| ~ { }`, or fewer than 70% letters) is a garbled signature-table row and is dropped ("7. BreniicT M^rho" on a Thurgau scan). | `…+post_questions_end` |
| section-number headings | "3.1 Zu Frage 1:" on one line (OPD's stored text, some PDFs) is split before the frozen rules run, by replacing the one space with a line break. Offsets do not move. | (frozen `heading_zu_frage`) |
| motion demand | A motion's or postulate's demand whose points are dash bullets is **one** item: the request paragraph through its last bullet, answered by the whole reply. Points numbered `1.` `2.` or `a)` `b)` stay separate items. | `…+post_one_demand`, `post_single_demand_whole_reply` |
| reasoning start | The reasoning starts after the reprinted member's text: a reprint heading ("Vorstosstext", "Auftragstext", "Wortlaut des Vorstosses", "Begründung (Vorstosstext)", "Texte de l'interpellation", "Testo dell'interpellanza") followed by the executive's heading ("Stellungnahme des Regierungsrates", "Réponse du Conseil d'Etat", "Risposta del Consiglio di Stato"). Without a heading, only a reprint of the member's **whole** text at the start is skipped. A single question repeated before its answer stays part of the reply, as the P5 labels have it. | `…+post_after_reprint` |
| closing block | The reasoning and the last answer end before the closing block: a signature (a name line over "Staatsschreiber", "Landschreiberin", "Le chancelier", "Il Cancelliere", "Präsident", …), a distribution list ("Verteiler", "Mitteilung an", "Copie à", "Vorberatende Kommission", …), a closing formula ("Im Namen des Regierungsrates", "Namens der Regierung", "Le Conseil d'Etat", "Per il Consiglio di Stato", …) or the recommendation section ("4. Antrag des Regierungsrates", "Proposition du Conseil d'Etat"). The list is generic, not per parliament. | `…+post_closing` |
| repeated question | An answer that still opens with the end of its question (the frozen alignment stopped at a word hyphenated over a line, "Behör- den beeinflussen?") loses that fragment, if the question document contains it word for word. The same holds if the fragment repeats a whole question except for an OCR slip: at least 40 characters and a similarity of at least 0.92 ("lindern" in the answer, "lindem" in the scanned question). | `…+post_question_tail` |
| people | A labelled signature list ("Unterschriften:", "Signataires :", "Firmatari:") is parsed. Labels, counts "(9)" and numbering "1." are not part of a name. A name broken over a line ("Markus⏎Dick") is joined, and its span keeps the line break. In a numbered list ("1. Beat Künzli, 2. …, 3. …, Richard Aschberger, …") the numbered names come first and no. 1 is the submitter; otherwise the first name is. If a title line or an author cue already named the submitter, the list only supplies the co-signatories. | `post_signature_list`, `post_signature_list_numbered` |
| answer title | If the frozen rule read the people from a signature block, and that block is OCR-garbled, the submitter and co-signatories come from the answer's title line instead ("Einfache Anfrage von A, B und C vom …", "Interpellation de …", "Interrogazione di …"; the frozen title patterns). Garbled means a name line, or one of the six lines above it, has characters a printed name does not have (`^ < > / \| ~ { } [ ]`, a digit inside a word: "Didi 1-euerle"). With `prefer_answer_title: true` in the settings file, the answer's title line is used whenever it names people, over a question title line or a signature list too. A title that names only the submitter ("… et consorts") keeps the clean co-signatories read before. The names are spans in the answer document. | `answer_title` |
| recommendation | When the frozen rules found no recommendation sentence (`not_in_document`) or conflicting ones, the layer tries, in order: your `--anchors` recommendation phrases for the body, `convert`'s frozen recommendation rules, and a phrase printed under an "Antrag des Regierungsrates" / "Proposition du Conseil d'Etat" / "Proposta del Consiglio di Stato" heading (lexicon: Nichterheblicherklärung → reject, Erheblicherklärung → accept, … und Abschreibung → accept_and_write_off, als Postulat → convert, teilweise → partial). A qualified phrase ("mit geändertem Wortlaut", "im Sinne der Erwägungen") is flagged, as in `convert`. A value picked over conflicting frozen candidates is flagged too. A frozen `accept` read off "Nichterheblicherklärung" (the frozen lexicon matches "erheblicherkl" inside it) becomes `reject`. On a body outside the rule coverage, a matching `--anchors` phrase replaces a frozen lexicon value, as in `convert`. A value of a different label than the one `convert`'s frozen rules read from the same answer is flagged (docs/convert-your-own.md, "convert and qa_cli"). | `user_anchor:<id>`, `convert_rec_<label>`, `post_antrag_heading`, `…+post_nichterheblich` |

**Post-hoc check, not registered.** The layer was run over the P5 dev and P5 affairs and scored with the P5 scorer
(`eval/gold6/score6.py`). It changes none of the counts in the table above. Reasoning spans got slightly closer to the
labels, because the closing block is cut, and every value re-checks against its span. A first version also skipped a
leading repeated question that had no reprint heading. On three P5 affairs that cut text the labels count as reasoning,
so the layer now skips only a reprint of the member's whole text. A later fix adds the questions end, the answer title and
the fuzzy repeated question, and the counts are still unchanged on both sets. Questions end changes nothing on P5 dev or
P5. The answer title replaced two garbled signature blocks on P5 dev (two VD Grand Conseil affairs), keeping the
submitter's surname. The fuzzy repeated question cut one more answer opening on P5 (Lausanne 120219), which now starts
where the label starts.
Every value re-checks: 555 on P5 dev, 517 on P5.

**convert and qa_cli agree on the recommendation.** On a body outside the rule coverage, `convert` now falls back to
the same Q/A lexicon rule (`lexicon_reject`, …) with the same sentence span, after its own rules and your anchors. In
`qa_cli` your anchors now beat the lexicon, as they do in `convert`. Where the two rule sets still read different
labels, both tools flag the field. The full table is in docs/convert-your-own.md, "convert and qa_cli".

**Confirming rules for a parliament.** On a body outside the rule coverage every rule value is flagged. Once you have
checked a rule on a sample (run with `--explain`: each field names its rule id, e.g. `heading_zu_frage` or
`reply_cue_after_reprint+post_after_reprint+post_closing`), list it under `confirm_rules` in the settings file. A
combined id is confirmed when the whole id is listed or every `+` part is. Its values then stop being flagged. Rules you
did not list stay flagged.

To use it in code: `from gegenprobe.qa.extract import extract; extract(question_pages, answer_pages, "de")` returns
`view` (flat spans), `records` (validated `QAItem` / `Actor` / recommendation / reasoning values) and `pointer`. The
`pointer` entry is a log of every model call, with its closed-set size, margin, θ and prompt id. The post layer is
`gegenprobe.qa_cli.run(question_pages, answer_pages, lang, affair_type, docs, body=..., settings=...)`; `--json` keeps the
frozen view and rules under `frozen` for comparison.
