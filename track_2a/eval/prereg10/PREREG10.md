# Pre-registration P10: can Apertus read author roles where no rule has been written? (frozen by eval/prereg10/LOCK10)

**Question.** The converter reads each affair's authors with fixed rules (`src/gegenprobe/convert/roles.py`, roles-2).
On P8's five held-out parliaments, the frozen roles-1 rules printed 49 (name, role) pairs, and 39 of them were right
(precision 0.80). But they found only 39 of the 137 gold pairs (recall 0.28; `results/schema/v0_2/converter_roles.json`,
exploratory). The rules work where they were written and abstain elsewhere. P10 tests a division of labour that keeps
every value printed and located:

- **code** finds the candidate names the documents print, each with its span (`src/gegenprobe/convert/role_candidates.py`);
- **Apertus** answers closed true/false questions about each candidate (`src/gegenprobe/convert/roles_pointer.py`);
- **code** composes the role from those answers by the P8 guide's definitions.

The test runs on fresh affairs from parliaments whose documents no role rule and no prompt has seen. The hypotheses
compare this arm with the frozen rules and with two no-model baselines.

**Written before any P10 affair is drawn.** The frame, the quotas, the seeds, the arms, the frozen pointer
configuration, the guide, the scoring, the hypotheses, the thresholds and the stop rules are fixed here and in the hashed
code. The draw (`eval/p10/draw.py`) refuses to run until LOCK10 is committed and unchanged. `eval/prereg10/lock10.py
write` refuses if a P10 draw, key, label or gold file exists, if the self-test fails, or if `roles.py` is not roles-2.

**What was looked at before registration.** The pool probe (`results/p10/pool_probe.json`; the first run's per-body
lines are in `results/p10/pool_probe_run1.txt`) holds counts per parliament and one robots.txt request per document host.
No P10 affair was selected, no document of a frame parliament or of the secondary cell was opened, and no model saw any.
Development (§7) used only the gold and the cached texts of P8's 6 development parliaments. The agent that wrote this
registration has not opened a document of P8's 5 held-out parliaments. It knows their aggregate converter-role scores
(above) and their names.

## 1. Design in one paragraph

The sample has 44 fresh affairs, each with the member's text and the executive's answer: 38 in the primary cell (24
German from 12 parliaments, 14 French from 2) and 6 in a secondary Italian cell. None of them is in any existing gold,
dev, test or audit set. Two blind Claude-agent annotators (A1 Opus, A2 Sonnet) list who lodged each intervention and in
what role, with the P8 guide's definitions word for word (`eval/p10/GUIDE_P10.md`). A3 (Opus) decides the packets where
their lists differ. Four arms print (name, role) pairs for every affair:

- (a) the Apertus role pointer on the model-free candidates;
- (b) the frozen role rules;
- (c1) OPD's contributor list mapped to roles, no model and no document;
- (c2) the same candidates with a trivial role.

The arms run only after the gold is committed, and no annotator sees an arm. Four one-sided hypotheses are tested on the
primary cell with a parliament-cluster bootstrap and Holm correction.

## 2. Frame (`eval/p10/common.py`)

**Parliament.** A parliament is in the frame when all of the following hold:

- It is not role-seen. 30 bodies are excluded:
  - the 15 parliaments the converter's rules were written on (`data/convert/rules_coverage.json`);
  - P8's 12 registered parliaments;
  - the parliaments of P3, P3b, P5 and P5 dev, whose documents the role rules were also written on;
  - the federal parliament.
- Its OPD body language is DE, FR or IT. The stratum is that language.
- It has at least 4 eligible affairs whose two document URLs robots.txt allows for our user agent at the probe. The check
  is fail-closed: an unreachable robots.txt disallows the host.

**Affair.** An affair qualifies by P8's frozen rule (`eval/p8/common.py` `pool`):

- an Interpellation, Motion, Postulate or Question;
- one document typed as the member's text and one typed as the executive's answer;
- OPD text status ok and 1,000 to 40,000 characters, and at least 1,000 extracted characters after fetching;
- not in P8's frozen exclusions (every earlier gold, dev, test and audit set; 2,436 affairs), not one of the 66 P8
  affairs, not one of the 15 federal affairs (2,517 excluded affairs in all).

**Frame at the probe (run 2, committed).**

| stratum | parliaments in the frame (robots-allowed eligible affairs) | affairs |
|---|---|---|
| DE | Emmen 499, Horw 18, Wetzikon 154, Adliswil 10, Neuhausen am Rheinfall 94, Lyss 27, Wil 18, Aarau 14, Zofingen 24, Appenzell Ausserrhoden 34, St. Gallen 803, Zug (canton) 433 | 2,128 |
| FR | Neuchâtel 35, Fribourg (city) 4 | 39 |
| IT | none | 0 |

**Out of the frame.** Locarno (the only Italian-speaking parliament outside the role-seen set; 183 eligible), Aargau
(1,936), Kriens and Arbon disallow the document paths in robots.txt. 18 hosts did not answer for their robots.txt at
probe run 2 and are therefore disallowed: Uri, Uster, Langenthal, Wettingen, Val de Bagnes and other communes. Host
reachability changed between probe run 1 and run 2: Emmen, Horw and Adliswil were unreachable in run 1 and in the frame
in run 2, while Langenthal and Wettingen went the other way. The committed run 2 defines the frame. At the draw the fetch
path checks robots.txt again (fail-closed), and §3's fill rule handles a host that has become unreachable.

**Secondary Italian cell (outside the family).** Lugano (5192; 494 robots-allowed eligible affairs) is a P8 held-out
parliament. Its layouts were used to write the post-hoc rules of roles-2, so the rules arm is in-sample there. The
pointer's development never saw it. This cell can only favour the rules, and it is reported apart.

## 3. Sample (`eval/p10/common.py` `quotas`, `eval/p10/draw.py`)

**Quotas.** The quotas are computed from the committed probe by a fixed rule: every primary frame parliament gets 2
affairs, and if a stratum is then below its target (DE 22, FR 14), the rest goes to its largest robots-allowed pool.

- DE: 12 × 2 = 24.
- FR: Neuchâtel 12, Fribourg city 2.
- Secondary IT: Lugano 6.

That gives 44 affairs, 38 of them primary. There is no language filter and no type filter beyond P8's qualification.

**Draw.** For each parliament, the eligible affairs are sorted by affair id, shuffled with
`random.Random(f"20261100:{body}")` and fetched in that order through the project's fetch path
(`eval.gold2.sample.fetch_one`). That path uses `gegenprobe.net` with the RFC 9309 matcher (fail-closed), User-Agent
`hackapertus-research/0.1`, ≥ 1.2 s between requests to a host, and OCR fallback. Rules for failures:

- A failed fetch is replaced by the next affair of the same parliament.
- A primary stratum left short is filled one affair at a time from its other parliaments, in the seeded order
  `random.Random(f"20261100:fill:{stratum}")`, cycling.
- The secondary cell is never filled.
- Every attempt, fill and shortfall is logged.
- An affair whose documents turn out to be something else stays in the sample.

**Committed after the draw, before any label:**

- `data/p10/p10_affairs.jsonl` (ids, URLs, sha256, pages, characters; never text);
- `data/p10/p10_fetch_log.jsonl`;
- `data/p10/opd_meta_p10.jsonl` and `data/p10/body_names_p10.json` (frozen `affair.meta.vendor`: the affairs' OPD rows,
  events and contributors, and each parliament's contributor names, i.e. first and last name only);
- `results/p10/sample.json`.

## 4. Arms (`eval/p10/arms.py`)

All arms read the same sha256-verified extracted text that the packets show.

**Candidates (shared, model-free, `role_candidates.py`, version `rolecand-1`).** A candidate comes from at least one of
these sources:

- every actor the frozen rules print, whatever its role;
- every located name block of the frozen rules, not only the first that fires: labelled author, first-signatory,
  co-signatory and supporter blocks, heading forms, closing signatures and a group above them, the Bern and Vaud forms,
  the Valais "durch" line, Thurgau address blocks and the answer's heading;
- a person from the parliament's OPD contributor roster, printed with a cue. The cue is a first name or initial next to
  the surname, a title before it, "et consorts / und Mitunterzeichnende / e cofirmatari" after it, or a line that holds
  only the name. The roster is searched in the member's text and in the first 3,000 characters of the answer;
- a parliamentary-group phrase in the head or closing of the member's text or in the answer's head;
- a committee name as a line of its own.

Persons are merged by `roles.same_person`. At most 60 candidates are kept per affair, in reading order. Candidate recall
is measured separately (§6).

**(a) pointer** (`roles_pointer.py`, version `rolepointer-2`, configuration frozen in `data/p10/p10_config.json`). For
every candidate, one user message shows:

- excerpts: the first 2,500 and last 1,500 characters of the member's text, and the first 1,000 of the answer;
- the numbered list of candidates;
- up to 2 printed lines where this candidate occurs.

The assistant message is prefilled with a JSON prefix, and P(true) of the next token is read. Two questions are asked:

- **author** (`role_author_v2`): did the candidate lodge or sign THIS intervention? The prompt names the places where
  authors are printed, and the things that are not authors: vote, attendance and member lists, the executive,
  officials, the president, reporting committees, people mentioned, and authors of other interventions.
- **first** (every person): asked in two wordings (`role_first`, `role_first_v2`), combined by their geometric mean. Do
  the documents set the candidate apart as THE first signatory?

The role is composed in code. Authors are the candidates with p_author ≥ **0.98**. Then:

- One group or committee author is sole_author. With several, the first printed is first_signatory and the others are
  co_signatory.
- If a person has p_first ≥ **0.30**, the person with the highest p_first is first_signatory and the other persons are
  co_signatory.
  - A person alone becomes first_signatory only when the documents print a co-signing cue (`COSIGN_CUE`: Erstunter-,
    Mitunterzeichn-, Konsorten, consorts, cosignataire, premier signataire, cofirmatari, primo firmatario).
- Otherwise, with a group author, the persons are spokespersons. Without one, a single person is sole_author and
  several persons are joint_author.

Every output names a located candidate. Nothing is generated.

**Route and budget for the pointer.**

- Route: the Public AI name `swiss-ai/apertus-v1.5-8b` (it serves the 70B weights), through the budget gateway with tag
  `2a-p10` and cap **USD 2.00**. This is the same route as the P1/P2 pointer.
- One user message plus an assistant prefill, sent only to a name on `llm.PREFILL_OK`. Never a system message, and never
  a prefill to `-70b`.
- One request per question with `max_tokens=1`, `logprobs` and `top_logprobs=20`. For these single-token options this
  equals the exact forced choice.
- The response's `model` is checked on every live call (ServedModelMismatch stops the run). Every response is kept in
  the hash-keyed model cache (`data/model_cache/`), so the arm replays offline.

**(b) rules**: `roles.extract(q, a, body)["actors"]`, frozen roles-2 (sha256 `5f6c978e…`), unchanged.

**(c1) opd_first / opd_joint (no model, no document).** OPD's contributors of the affair, persons and groups with an
author-like harmonised role (author, primary) or a co-signing one (cosign, co-signer), in OPD's order:

- one author and no co-signer: sole_author;
- one author and co-signers: the author is first_signatory and the co-signers co_signatory;
- several OPD authors: two readings. `first_and_co` makes the first author first_signatory and the rest co_signatory;
  `joint` makes all of them joint_author.

H3a compares the pointer with the stronger of the two readings in every bootstrap resample. This is conservative.
These names are OPD's and are not located in the documents.

**(c2) cand_joint (no model)**: the shared candidates. One candidate is sole_author; with several, every candidate is
joint_author.

**(d) exploratory, outside the family**: the same pointer and configuration on the local Apertus 8B GGUF (exact forced
choice, CPU runner). The thresholds were fitted on the gateway build and are not refitted. It is reported as
exploratory.

## 5. Gold (`eval/p10/packets.py`, `eval/p10/annotate.py`, `eval/p10/GUIDE_P10.md`)

- **Packets** (WORK only, never committed) hold an opaque id (ids assigned in seeded random order, seed 20261100) and the
  two documents as extracted, page-delimited. They carry no OPD metadata, no parliament, no stratum, no candidate list
  and no arm output.
- **Annotators.** A1 (Claude Opus) and A2 (Claude Sonnet) label every packet blind, each in its own session, with
  `GUIDE_P10.md`: P8 guide §1-§2 word for word, plus the packet and file sections. They label `question_doc`,
  `answer_doc` and `people` (name, kind, role, doc, page, quote). Every file must pass
  `python -m eval.p10.annotate selfcheck`: closed vocabularies; every quote verbatim (whitespace-insensitive) on the page
  it names; the name's last word inside the quote. The lead launches the agents, and no human labels. Session times are
  recorded as for earlier sets.
- **Tie-break.** Two lists agree when they have the same length and match one-to-one on (same person, equal role). A3
  (Claude Opus) gets each disagreeing packet with both lists as X/Y, in seeded random order (seed 20261101), and labels
  `people` anew. The gold per packet is A1's list where A1 and A2 agree, else A3's.
- **Committed after the merge:**
  - `data/p10/p10_gold.jsonl` (every quote replaced by its sha256 and resolved span);
  - `data/p10/annotations/{A1,A2,A3}.jsonl` (same treatment; notes stay in WORK);
  - `data/p10/p10_key.jsonl`;
  - `results/p10/p10_agreement.json` (packets agreeing, A1 vs A2 pair F1, packets sent to A3).

No document text is committed.

## 6. Metrics, hypotheses and decision rules (`eval/p10/score.py`)

**Unit.** A (name, role) pair of one affair. A predicted pair matches a gold pair when the names are one person and the
roles are equal. One person means `roles.same_person`: equal token sets, or one a subset of the other, accents and
titles folded. Matching is greedy and one-to-one in printed order, the converter evaluation's rule. All gold roles count,
including `supporter` and `other`.

**Per arm, pooled over affairs:**

- pair precision = matched / predicted;
- pair recall = matched / gold;
- F1;
- Wilson 95% intervals.

An arm that prints nothing for an affair loses recall there and no precision.

**Hypotheses.** All are tested on the PRIMARY cell, one-sided, α = 0.05, Holm over the family of four:

| | hypothesis | statistic | null |
|---|---|---|---|
| H1 | the pointer finds more gold pairs than the rules | recall(pointer) − recall(rules) | ≤ 0 |
| H2 | the pointer's precision is non-inferior to the rules' | precision(pointer) − precision(rules) | ≤ −0.10 |
| H3a | the pointer beats OPD's contributor list | F1(pointer) − max(F1(opd_first), F1(opd_joint)) | ≤ 0 |
| H3b | the pointer beats code-only roles on the same candidates | F1(pointer) − F1(cand_joint) | ≤ 0 |

**Test.** A paired parliament-cluster bootstrap: 10,000 resamples of the primary parliaments with replacement (seed
20261102), each resample pooling the affairs of the drawn parliaments. p = (1 + #{resampled statistic ≤ null}) /
(10,001). A hypothesis is **confirmed** when it is rejected by Holm's step-down at 0.05, else **not confirmed**.

- H2: if the rules print nothing in a resample, their precision is taken as 0 there.
- H1 secondary (not decisive): the exact McNemar test on gold pairs found by exactly one of pointer and rules.

**Stop rules.**

1. *Underpowered:* fewer than 30 primary affairs scored, or fewer than 60 primary gold pairs. Then every hypothesis is
   reported as *inconclusive (underpowered)* with its numbers.
2. *Budget:* if the gateway refuses a call for the cap, the pointer stops. Affairs it did not reach count as pointer
   abstentions (no pairs), never as exclusions.
3. *Served model:* a ServedModelMismatch on any live call stops the pointer, and nothing from another model is scored.
   Served fingerprints not seen in development are reported (`fingerprints_not_seen_in_development`).
4. *Compliance:* robots.txt is fail-closed. `api.openparldata.ch` is refused by the fetch path. OPD data comes only from
   the committed-snapshot exports (files.openparldata.ch).

**Also reported (never decisive):**

- per stratum and per parliament;
- names-only precision and recall;
- affairs whose pair set is exactly right;
- candidate recall: gold names found among the candidates;
- the pointer's recall given the candidates;
- the secondary Italian cell, apart;
- the 8B exploratory arm.

Every outcome is reported, including failures.

## 7. Development (`eval/p10/dev.py` → `results/p10/dev10.json`; frozen configuration `data/p10/p10_config.json`)

**Data.** The development data is the gold and cached texts of P8's **6 development parliaments**: 261 Zürich city, 5002
Bellinzona, 5586 Lausanne, 6643 Vernier, FR, GR. That is 36 affairs and 208 gold pairs. P8's 5 held-out parliaments (351,
5192, TG, VD, VS) were not used. Their layouts were used to write roles-2 after their held-out score, so they could not
show how the pointer generalises, and they are kept away from it.

**Calls and cost.** Development calls went through the gateway with tag `2a-p10-dev` (cap USD 1.00). The spend was USD
0.32, all with the served fingerprint `vllm-0.23.1rc1.dev1029+ga601a9d99-tp8-pp2-dd237840`, and no option fell outside
the top 20.

**Selection rule (fixed before the first sweep).** The highest macro pair F1 (mean over the 6 parliaments) wins. Ties
are broken by pooled F1, then precision, then larger thresholds. Macro is used because Graubünden's signature lists hold
146 of the 208 pairs.

**Variants run:**

- `letters_v1`: one seven-way lettered choice. Strong letter bias towards C (first_signatory); best macro F1 0.38.
- `staged_v1`: true/false questions. Macro 0.56; it says yes to almost every candidate.
- `staged_v2`: a reworded author question plus a negated one, and a stricter first question. Macro 0.72. The negated
  question is yes-biased too, and the strict first question misses Graubünden's heading form.
- `staged_v3`: the v2 author question, plus both first wordings combined. Macro **0.74**; selected with tau 0.98,
  tau_first 0.30 and the cue rule.

**Development results (in-sample for the pointer's prompts and thresholds, and for the rules, which were written on
these parliaments):**

| arm | pairs right / predicted / gold | precision | recall | F1 | macro F1 |
|---|---|---|---|---|---|
| pointer (staged_v3) | 169 / 214 / 208 | 0.790 | 0.813 | 0.801 | 0.737 |
| rules (roles-2) | 198 / 199 / 208 | 0.995 | 0.952 | 0.973 | 0.839 |
| opd_first | 145 / 236 / 208 | 0.614 | 0.697 | 0.653 | 0.263 |
| opd_joint | 39 / 236 / 208 | 0.165 | 0.188 | 0.176 | 0.508 |
| cand_joint | 42 / 291 / 208 | 0.144 | 0.202 | 0.168 | 0.446 |

**Candidate recall on development:** 206 of 208 gold names (99.0%), with 291 candidates. One miss is an OCR-damaged name
and the other a group name the phrase pattern cuts short.

**Pointer by parliament (right / predicted / gold):**

| parliament | pointer | rules |
|---|---|---|
| Zürich city | 12/12/12 | 12/12/12 |
| Vernier | 20/20/20 | 20/20/20 |
| Graubünden | 119/144/146 | 146/146/146 |
| Lausanne | 8/11/13 | 9/10/13 |
| FR | 6/10/10 | 10/10/10 |
| Bellinzona | 4/17/7 | 1/1/7 |

In Bellinzona the linked "member's text" is a vote report or a committee report.

These numbers say nothing about unseen layouts. That is what the test measures. The rules' frozen held-out recall on
unseen layouts was 0.28.

## 8. Order of operations and stop points (phase 2)

1. Commit phase 1: this file, `eval/prereg10/`, `eval/p10/`, the two new converter modules, the role prompts,
   `data/p10/p10_config.json`, `results/p10/{pool_probe.json,pool_probe_run1.txt,dev10.json}`, and the development
   model-cache entries. Then run `python -m eval.prereg10.lock10 write` and commit `eval/prereg10/LOCK10` alone. Its
   commit time is the registration time.
2. Run `python -m eval.p10.draw` (network; once). Commit the draw files of §3 before any label exists.
3. **Annotation point.**
   1. A1 and A2 label blind.
   2. `annotate verify A1`, then `annotate verify A2`.
   3. `annotate a3packets`.
   4. A3 labels the disputed packets.
   5. `annotate verify A3`.
   6. `annotate merge`.

   Commit the gold before any arm runs. The arms refuse without the merged gold.
4. Run `arms offline`, `arms pointer`, `arms join` and `score`. Commit the arms, the model-cache entries and the scores.
   Then, optionally, the exploratory 8B arm.

## 9. Not allowed after LOCK10

No change to any hashed file: frame, quotas, seeds, exclusions, candidate generator, pointer, prompts, configuration,
rules, guide, scoring, hypotheses, thresholds or stop rules. Every later change goes into
`eval/prereg10/DEVIATIONS10.md` with its effect. Files frozen by earlier locks stay unchanged.
