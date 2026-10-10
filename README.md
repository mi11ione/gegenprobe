# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

One schema for the business of Swiss parliaments (of 17 fields, 12 mean the same everywhere and 5 need their date or
label roles kept apart; 4 are in OpenParlData's metadata almost everywhere, 13 partly), a converter that returns each
date and rule value it reads from a document with the page and span where it is printed, or a typed null (Apertus points
at one of the printed dates, or says null, as a suggestion a person confirms), and the cross-parliamentary result this
enables: where government answers go missing from OpenParlData, and how to put them back. The eCH expert group's page:
[`track_2a/docs/ech-onepager.md`](track_2a/docs/ech-onepager.md).

- **Evidence site:** https://gegenprobe.mi11ion.io (also written to `track_2a/out/site/index.html` by `make run`)
- **Project:** [`track_2a/`](track_2a/) — start with [`track_2a/README.md`](track_2a/README.md); technical report
  [`track_2a/technical_report.md`](track_2a/technical_report.md) (PDF: `track_2a/444_Report.pdf`)

```bash
cd track_2a && make run      # Docker, CPU, clean checkout
```

Code: Apache-2.0 ([LICENSE](LICENSE)). Report: CC-BY-4.0 ([track_2a/docs/LICENSE-report.txt](track_2a/docs/LICENSE-report.txt)).
Data in `track_2a/data/`: CDLA-Permissive-2.0 ([track_2a/data/LICENSE](track_2a/data/LICENSE)).
