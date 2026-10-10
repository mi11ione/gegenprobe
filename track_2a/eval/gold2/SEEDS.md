# P2 seeds and draw log

- Seed **20261011**, written into `eval/prereg2/PREREG2.md` before the first draw.
- Unseen bodies are asserted by code (`eval/gold2/sample.py: seen()`): no document of these bodies is in P1 dev, P1 held-out or any `data/gold/dev_ids.json` source.

## Draw v1 (aborted before LOCK2, no labels)
- 47 of 64 documents. Shortfalls: NW/OW answers 0 (language filter "de" excluded untagged documents), canton FR answers 0 (robots.txt), SZ member texts 2 of 4, Fribourg city member texts 0 (HTML pages).
- Rejections by body / reason / host:
  - 2196 · not a PDF · www.ville-fribourg.ch: 58
  - 62 · HTTPError · : 1
  - FR · robots.txt disallow · api.fr.ch: 199
  - GL · robots.txt disallow · www.gl.ch: 17
  - SZ · robots.txt disallow · www.sz.ch: 53

## Draw v2 (the P2 set, quotas as in PREREG2)
- 62 documents, 15 bodies, no shortfall.
- Rejections by body / reason / host:
  - 2196 · not a PDF · www.ville-fribourg.ch: 3
  - 62 · HTTPError · : 1
  - GL · robots.txt disallow · www.gl.ch: 17
  - SZ · robots.txt disallow · www.sz.ch: 52

| cell | answer | intervention |
|---|---|---|
| de_canton | 8 | 15 |
| de_commune | 0 | 10 |
| fr_canton | 8 | 0 |
| fr_commune | 9 | 6 |
| it_commune | 6 | 0 |

Tokens (chars/4) after pdftotext: median 1200, range 282–1932; OCR used on 0 documents.
