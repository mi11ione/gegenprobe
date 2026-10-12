# Two Docker nights, run 38187596786: the fixed ledger on a real pair of nights

These files are kept as the workflow uploaded them (`.github/workflows/nightly-real-docker.yml`, run 38187596786,
dispatched 12 Oct 2026 00:20 UTC on the commit that fixed the ledger bug documented in
`../two_nights_docker_38098822336/README.md`).

| | night 1 (first night) | night 2 (on night 1's state) |
|---|---|---|
| wall time | 5,254 s | 173 s |
| bodies re-scanned | 97 | 0 |
| BE rows (`be_repair`) | 2,459 relink + 49 fetch | 2,459 relink + 49 fetch |
| new rows, checked tonight | 2,508 | 0 |
| ledger (`run.json` `ledger`) | pending 2,468, review 40 | **pending 2,468, review 40** |
| rows carried back to review (`be_repair_carried_review`) | 0 | 40 |
| alerts (webhook) | 2 | 2 |

`two_nights.json` records `night2_kept_night1_verdicts: true`: every row not checked on night 2 kept its stored verdict,
and the 40 rows that failed their check on night 1 stayed in review. OPD's index did not change between the two nights
(`index_changed_between_nights: false`, both read the export generated 2026-10-11T04:33:46Z), so night 2 re-read the
same exports; the ledger's carry-over is what this pair tests.

Both nights exit with status 3, the job's "alerts raised" status: the adapter canary still verified 7 of 7 sample
affairs, and flagged two texts that differ from the committed hashes (Locarno IR 2008.0022 via OPD's copy, Valais
2020.06.206). The sources did not change: both canaries are read through OCR, and the image's older tesseract reads the
unchanged files differently. A host re-check on 12 Oct verified all 7 with their committed texts
(`results/repair/adapters/canary_runs/2026-10-12.json`); since then a canary alerts only when its file's bytes change
or its text changes under the same extractor. Both alerts reached the webhook (`alert_posts.jsonl`). The User-Agent carried a contact URL
(`has_contact: true`). Install and image build took 32 s; peak memory about 2.1 GB.
