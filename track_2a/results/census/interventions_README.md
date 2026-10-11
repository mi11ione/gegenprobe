# interventions.tsv.gz — one row per intervention with a written government answer

Built by `python -m gegenprobe.census.interventions` from the vendored census tables (`data/census/`, OpenParlData exports
of 2026-10-06). Scope: affairs of harmonised type Interpellation, Motion, Postulate, Question or Question time whose events
record a written government answer (the census funnel's denominator: 91,268 rows). Tab-separated, UTF-8, gzip.
Licence: CDLA-Permissive-2.0 (see `data/LICENSE`); derived from OpenParlData.ch, which publishes material the parliaments
themselves publish.

**Read this first.** "Not in OpenParlData" is not "not published by the parliament". Answer dates are OPD event dates;
they are verified as the government's decision date in two parliaments: Bern, against the decision date printed in the
answer (2,421 of 2,459 relink rows, `results/repair/be_verify_all.json`), and Ticino, against the publisher's answer title
"Risposta del CdS del …" (2,379 of 2,379 dated answers that carry such a title; on 20 held-out answers the title date is
the date printed in the answer, `results/eval/posthoc_r3_gold_oracle.json`). Elsewhere use `date_trust` before comparing
bodies.

| column | meaning |
|---|---|
| `body` | OPD body key (canton code, `CHE`, or a commune's BFS number) |
| `affair_id` | OPD affair id |
| `number` | the affair number as OPD stores it |
| `type` / `type_raw` | OPD harmonised type / the parliament's own label (42 raw labels map to different harmonised types in different bodies: `results/census/comparability.json`) |
| `year` | year from the affair number, else from `begin_date` |
| `submitted` | earliest 'Eingereicht'-type event (harmonised ids 1, 56, 67), else OPD `begin_date` |
| `submitted_source` | `event` or `begin_date` |
| `be_load_date` | 1 if Bern `begin_date` is the 2024-10-28 load timestamp and no submission event exists (OPD-confirmed bug); durations are blank for these rows |
| `answer_date` / `answer_hid` | census rule: the earliest written-answer event, and its OPD harmonised event id |
| `answer_date_alt` / `answer_hid_alt` | alternative rule: the earliest event harmonised as 'Beantwortet' (id 6) if there is one, else the census rule. Changes 753 rows; fixes Schaffhausen, where an event harmonised 'Eingereicht' carries the answer title on the submission date (median 0 → 71 days) (`results/census/answer_rule_alt.json`) |
| `n_answer_events` / `answer_spread_days` | number of written-answer events, and days between the first and last |
| `days_to_answer` / `days_to_answer_alt` | submitted → answer date (rule / alternative rule); blank if a date is missing, negative or > 10 years |
| `link_status` | where the answer text is: `attached` · `agenda` (filed under an agenda item) · `parentless` (in OPD without a parent; Bern) · `image_only` (scan without text) · `oral` (answered in the sitting: question time / Fragestunde with no answer document, or a Valais "réponse orale" stub) · `absent` (not in OPD) |
| `oral_event` | 1 if an event also records an oral answer |
| `same_day_body` | 1 if the body's 'answer' events mostly fall on the submission date (census flag, 7 bodies) |
| `date_trust` | per body: `verified` (Bern: printed decision date; Ticino: publisher's answer title; `verified_by` in date_trust.json) · `sitting_day` (≥ 80 % of answer dates on one weekday, a government's weekly sitting) · `mixed` (50–80 %) · `diffuse` (< 50 %) · `same_day` · `too_few` (< 20 dated) — `results/census/date_trust.json` |
| `opd_url` | the affair's page on openparldata.ch |
| `source_url` | the parliament's own page for the affair, from OPD's `url_external_*`, filled for rows whose answer text is not attached (16,745 of 16,749) |

# parliaments.csv — the Parliaments table, one row per body

Built by `make site` (`python -m gegenprobe.viewer collect`, `viewer/data.py:write_csv`) from the census results and this
dataset. Column groups `all_*`, `since2015_*`, `y2425_*` repeat per period (by the year in the affair number, else its
`begin_date`). One denominator: `written` = interventions whose events record a written government answer.

| column (per period) | meaning |
|---|---|
| `written` | interventions with a written-answer event (the census denominator) |
| `attached` · `agenda` · `parentless` · `image_only` · `oral` · `absent` | where the answer is (the `link_status` values above); they sum to `written` |
| `no_answer_text` | `written − attached`: no answer text attached in OPD (the census gap; 16,749 over all years). **Includes `oral`** |
| `oral` | answered orally in the sitting (question time; Valais `_ANT` oral-answer stubs): no written text is expected, so **not missing** |
| `in_writing` | `written − oral`: the answers given in writing |
| `written_missing` | `no_answer_text − oral` = `agenda + parentless + image_only + absent`: written answers without attached text. Use this, over `in_writing`, when you write about *missing* answers |
| `written_missing_share` | `written_missing / in_writing` |
| `in_opd_unrecognised_heading` | derived layer (`results/census/corrected.json`, `python -m gegenprobe.census.corrected`): written answers without attached text that are in OPD **with text on the intervention**, under a heading the census lexicon does not recognise (verified adapter rows, `tag_answer`; 2,316 over all years). The registered `no_answer_text` counts them; `no_answer_text − in_opd_unrecognised_heading` is an upper bound on the interventions without answer text on their intervention in OPD |
| `in_opd_image_only` · `image_only_text_verified` | derived layer: in OPD only as a copy without usable text (`image_only`, plus answer files an adapter found in OPD without text); of them, read from OPD's own copy (text layer or OCR) and verified by affair and date |
| `fetchable_verified` · `still_open` | derived layer: not in OPD, a verified fetch row from the parliament exists (adapters, Bern, Curia Vista) · no verified answer yet. `agenda + parentless + in_opd_unrecognised_heading + in_opd_image_only + fetchable_verified + still_open = written_missing` |
| `written_lack_text_at_most` | `written_missing − in_opd_unrecognised_heading`: upper bound on the written answers without answer text on their intervention in OPD |
| `with_text` · `after_repair` | `attached / written`; the same after every counted repair: agenda join, Bern relink, `in_opd_unrecognised_heading`, the verified text of OPD's own copies without text, verified fetches (adapter rows count only in the tiers with a date check) |

| column | meaning |
|---|---|
| `median_days_all_types` | median days to answer over **all intervention types pooled** (census rule; blank for same-day bodies and < 20 dated answers). **Caution:** it mixes motions, postulates, interpellations, questions and question time, whose "answer" is a different act (Neuchâtel: 25 days pooled, 70 for interpellations since 2015). Quote a per-type median instead |
| `{period}_median_days_{type}` · `{period}_n_{type}` | median days and number of dated answers for one type (`interpellation`, `question`, `motion`, `postulate`, `question_time`), shown where n ≥ 10; blank for same-day bodies |
| `median_flag` | `same_day` (OPD's "answer" date mostly equals the submission date: no answer time) · `few` (< 20 dated answers) |
| `safe_to_say` | one generated sentence with its caveat; it uses `written_missing` over `in_writing` and names oral answers separately |
| `coverage` | `measured` · `coverage_gap` (OPD holds ≥ 20 interventions but records a written answer for < 20 and < 10 % of them: a gap in OPD, not evidence about the parliament) · `few` · `no_affairs` |
| `first_year` · `last_year` | years of the body's written-answer interventions in OPD |
| `all_main_type` · `all_median_days_main_type` | the type with the most dated answers, and its median |
| `date_trust` · `date_verified_by` | the body's date-trust tier (see `date_trust` above) and, for `verified`, how (`printed`, `title`) |

Valais oral counts, one definition each: **1,017** interventions typed `oral` (this table, `link_status`) = 1,016 `_ANT`
stubs found by the census length proxy + 1 question-time answer; **1,016** = the stubs alone (`results/census/summary.json`
`gap_oral_split.vs_stub`); **1,008** = the stubs the repair's exact text rule confirms (the `retype_oral` list for OPD;
`results/census/vs_reconcile.json`).
