# Audit v3: auditor instructions (identical for both auditors)

Input: `results/repair/adapters/audit3/packets.jsonl`, one JSON object per line with `id`, `affair_number`, `title`,
`type`, `answer_event_dates` and `excerpt_path` (a text file under `.work/adapters/audit3/texts/`, path relative to
`track_2a/`). Read nothing else in the repository for this task: not the adapter lists, not results/, not the code, not
earlier audits. For every packet, read its excerpt file and answer the item prompt below with these values filled in
(`{number}` = affair_number, `{title}`, `{type}`, `{dates}` = answer_event_dates joined by ", " or "none",
`{text}` = the excerpt file's content). Judge each packet on its own.

Output: `.work/adapters/audit3/verdicts_<auditor>.jsonl`, one line per packet:
`{"id": "A3-001", "is_answer": "yes|no|unclear", "date_ok": "yes|no|unclear", "quote": "...", "note": "..."}`
(`quote`: at most 200 characters, verbatim from the excerpt).

The Qwen auditor (`python -m gegenprobe.repair.adapters.audit3 qwen`) receives exactly the filled item prompt as the
only user message (temperature 0).

## Item prompt

```
You are auditing whether a document is the government's written answer to a parliamentary intervention in a Swiss parliament (a canton or a municipality). You see the intervention's metadata from OpenParlData (OPD) and the text extracted from one document. Judge only from what is shown.

Intervention
- number: {number}
- title: {title}
- type: {type}
- OPD answer event date(s): {dates}

Document text (extracted; when longer than 15,000 characters, the first 12,000 and the last 3,000 are shown):
<<<
{text}
>>>

Questions
1. is_answer: Is this document the executive's written answer or written response to THIS intervention (the government, Regierungsrat, Conseil d'État, Consiglio di Stato, Stadtrat, Gemeinderat, Municipalité, Municipio, ...)? yes = it is, or it contains it; no = it is something else (the member's own question or motion text, minutes of the parliament that only refer to an answer, a commission report, a request for more time, the answer to a different intervention, ...); unclear = the text does not let you decide.
2. date_ok: Does the document's own date, or the answer date it states, agree with one of the OPD answer event dates (the same day, or within about 30 days)? yes / no / unclear (no date found in the text, or no OPD date given).
3. quote: copy verbatim, at most 200 characters, the passage of the document text that most supports your is_answer judgment.

Reply with one JSON object only, no other text:
{"is_answer": "yes|no|unclear", "date_ok": "yes|no|unclear", "quote": "...", "note": "one short sentence"}
```
