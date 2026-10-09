# Deviations from the pre-registration

Every change to a file listed in `LOCK` after the lock commit (812030f, 2026-10-09T21:38:02+02:00), and every defect found
in frozen code after the lock, is listed here with its effect on the frozen result.

## D1 (found 2026-10-09, after the lock, before any held-out label): OCR cell prompted in German
`eval/arms.py:load_split` sets the prompt language from the OPD `language` field, falling back on the cell prefix
(`it`/`fr`, else `de`). The OCR cell is named `ocr_ti`, and its documents carry no OPD language tag, so the Italian scans of
the Ticino government are scored with the **German** pointer and naive prompts. The same mapping applied to the 5 OCR
documents of the dev θ fit, so θ and the held-out run are consistent with each other.
- **Headline:** the frozen code is run unchanged (German prompt on the OCR cell).
- **Post-hoc, labelled as such:** the OCR cell is re-scored with the Italian prompt and θ unchanged, and both rows are
  reported.
