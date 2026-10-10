# Gegenprobe — Hack Apertus, Track 2A (OpenParlData), team 444

Where Swiss parliamentary answers go missing, how to put them back, and a converter whose every value is printed in the
source document, with page and span (Apertus points at one of the printed values, or says null).

- **Evidence site:** https://gegenprobe.mi11ion.io (also written to `track_2a/out/site/index.html` by `make run`)
- **Project:** [`track_2a/`](track_2a/) — start with [`track_2a/README.md`](track_2a/README.md); technical report
  [`track_2a/technical_report.md`](track_2a/technical_report.md) (PDF: `track_2a/444_Report.pdf`)

```bash
cd track_2a && make run      # Docker, CPU, clean checkout
```

Code: Apache-2.0 ([LICENSE](LICENSE)). Report: CC-BY-4.0 ([track_2a/docs/LICENSE-report.txt](track_2a/docs/LICENSE-report.txt)).
Data in `track_2a/data/`: CDLA-Permissive-2.0 ([track_2a/data/LICENSE](track_2a/data/LICENSE)).
