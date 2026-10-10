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
  20/24 in Wädenswil and 17/20 in Lugano. It was 0/11 in Valais, whose answers discuss the questions without marking
  them. Basel-Landschaft was 14/31, with precision 14/30.
- **Rules-only submitter detection does not transfer:** 12/40 on P5, against 36/38 on dev. There were 14 affairs
  without a value and 14 with the wrong person. The pointer over printed names raises it to 24/40. Free generation names
  the right printed person in 34/40, but without a span or a closed set. Submitter detection stays a review field.
- Questions (167/187), reasoning (37/40) and recommendation (34/40 by rules, 36/40 with the pointer) hold up across the
  new parliaments.

## Commands

```
python -m eval.gold6.run6 p5 --backend none                                        # rules + trivial baselines (no model)
python -m eval.gold6.run6 p5 --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p5-test:1.5   # + pointer arms, free generation
python -m eval.gold6.hypotheses6 p5 publicai_swiss-ai_apertus-v1.5-8b              # registered hypotheses
python -m eval.gold6.posthoc6                                                      # post-hoc breakdowns
python -m eval.gold6.qwen6_run && python -m eval.gold6.qwen6 analyse               # independent Qwen check
```

To use it in code: `from gegenprobe.qa.extract import extract; extract(question_pages, answer_pages, "de")` returns
`view` (flat spans), `records` (validated `QAItem` / `Actor` / recommendation / reasoning values) and `pointer`. The
`pointer` entry is a log of every model call, with its closed-set size, margin, θ and prompt id.
