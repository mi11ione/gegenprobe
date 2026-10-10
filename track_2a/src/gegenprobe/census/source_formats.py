"""Which file formats a parliament publishes an answer in, next to what OPD holds (network; polite; a spot check, not a count).

    python -m gegenprobe.census.source_formats [ATTO_ID ...]    -> results/census/source_formats_ti.json

Ticino's Gran Consiglio lists each atto on one page (OPD's url_external, the `source ↗` link on the site) with its answer
attachments ("Risposta del CdS del …"). Where OPD's copy of the answer has no text (census link status `image_only`), the
parliament may still publish a text version: a second attachment of the same answer as a Word file or a text PDF. This
module reads the atto page, lists the answer attachments and their file names (from the Content-Disposition header; the
body is not downloaded), and puts OPD's documents for the same affair next to them (data/census/docs.tsv.gz).
Default: atto 101174 (interrogazione 100.19, OPD affair 173406). One page + one request per attachment, >= 1.2 s apart.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys

from .. import net
from ..paths import RESULTS
from .tables import rows

PAGE = "https://www4.ti.ch/poteri/gc/ricerca-messaggi-e-atti/ricerca/risultati/dettaglio?user_gcparlamento_pi8%5Battid%5D={atto}"
LINK = re.compile(r'href="(https://www4\.ti\.ch/user_librerie/php/GC/allegato\.php\?allid=\d+)"[^>]*>([^<]+)</a>')
FNAME = re.compile(r'filename="?([^";]+)"?')
OUT = RESULTS / "census" / "source_formats_ti.json"
DEFAULT = {101174: 173406}  # atto id -> OPD affair id (from the affair's url_external, site/missing.json)


def check(atto: int, affair: int | None) -> dict:
    page = net.get(PAGE.format(atto=atto)).decode("utf-8", "replace")
    links = [(u, html.unescape(t).strip()) for u, t in LINK.findall(page)]
    answers = []
    for u, t in links:
        if not t.startswith("Risposta"):
            continue
        with net.open_url(u) as r:  # headers only; the body is not read
            cd, ct = r.headers.get("Content-Disposition", ""), r.headers.get("Content-Type", "")
        m = FNAME.search(cd)
        answers.append(dict(url=u, title=t, filename=m.group(1) if m else None, content_type=ct.split(";")[0]))
    opd = [dict(doc_id=int(d["id"]), name=d["name"], opd_text_status=d["status"], chars=int(d["n"] or 0))
           for d in rows("docs") if affair is not None and d["affair"] == str(affair)]
    return dict(atto=atto, page=PAGE.format(atto=atto), affair=affair, source_answer_files=answers, opd_documents=opd,
                opd_answer_copies=sum(1 for d in opd if d["name"].startswith("Risposta")),
                opd_answer_copies_with_text=sum(1 for d in opd if d["name"].startswith("Risposta")
                                                and d["opd_text_status"] == "ok"))


def main(argv: list[str]) -> int:
    attos = {int(a): None for a in argv} or DEFAULT
    out = dict(label="Spot check (not a count): answer files the parliament publishes vs OPD's copies, Ticino",
               checked=dt.date.today().isoformat(), user_agent=net.UA,
               attos=[check(a, aff if aff is not None else DEFAULT.get(a)) for a, aff in attos.items()])
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
