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
