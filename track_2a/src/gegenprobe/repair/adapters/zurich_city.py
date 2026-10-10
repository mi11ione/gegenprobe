"""Zürich (city), OPD body 261: the answer is already in OPD, on the affair, under a file name.

The Stadtrat's answer to a Schriftliche Anfrage / Interpellation is an extract of its minutes ("Auszug aus dem Protokoll
des Stadtrats von Zürich ... GR Nr. 2019/375 vom 27. November 2019" or "Beschluss des Stadtrats vom ..."; before 2012 the
extract starts with the decision number, "1393. Interpellation von ..."), and it says "Der Stadtrat beantwortet die
Anfrage wie folgt". The header of the Stadtrat's own minutes extract counts as the answer heading: the legislature's
documents never carry it. OPD stores it attached to the affair as "2019_0375" / "2009_0174.pdf", the same file name as the
question, so neither the name nor the census lexicon marks it as the answer. Route: OPD's own text, no request to the
city; documents OPD holds without text are fetched from the city's URL OPD stores (gemeinderat-zuerich.ch/dokumente,
robots.txt allows) and extracted.
"""
from __future__ import annotations

import re

from .base import Adapter, Candidate, flatten

HEADING = re.compile(
    r"beantwortet der Stadtrat (die|den) [^.:]{0,160}?wie folgt|Der Stadtrat beantwortet (die|den) [^.:]{0,160}?wie folgt|"
    r"Auszug\s+aus dem Protokoll des Stadtrate?s von Zürich|Beschluss des Stadtrate?s\s+vom|"
    r"Antwort des Stadtrate?s|Stellungnahme des Stadtrate?s|Der Stadtrat (ist bereit|lehnt)[\w ,]{0,60}(Motion|Postulat)",
    re.I,
)
HEADER_DATE = re.compile(r"(?:Protokoll des Stadtrate?s von Zürich|Beschluss des Stadtrate?s)[\s\S]{0,120}?vom\s+"
                         r"(\d{1,2}\.\s*\w+\s+\d{4})", re.I)
PROTO = re.compile(r"^Protokolleintrag", re.I)


class ZurichCity(Adapter):
    body = "261"
    label = "Zürich (city)"
    route = ("OPD's own text on the affair: Stadtrat minutes extract 'beantwortet die Anfrage wie folgt'; text-less "
             "copies fetched from the URL OPD stores")
    action = "extract_tag"
    hosts = ("www.gemeinderat-zuerich.ch",)
    heading = HEADING
    header_date = HEADER_DATE
    # OPD's "Stadtrat, Antwort" event is the Stadtrat's decision date since about 2012; before, it is often the dispatch
    # one or two weeks later (pilot of 200 affairs: deltas 0 x150, +1, +7 x13, +8 x3, +14, +15)
    date_window = (0, 15)

    def number_patterns(self, number: str) -> list[str]:
        m = re.match(r"(\d{4})/0*(\d+)$", number or "")
        if not m:
            return [re.escape(number)]
        y, n = m.groups()
        return [rf"{y}\s*/\s*0*{n}"]

    def candidates(self, x: dict, opd: list[dict]) -> list[Candidate]:
        docs = [d for d in opd if not PROTO.match(d["name"] or "")]
        with_text = [d for d in docs if len((d["text"] or "").strip()) >= 200]
        with_text.sort(key=lambda d: (not HEADING.search(flatten(d["text"])), d["id"]))
        out = [Candidate(url=d["url"], title=d["name"], origin="opd_text", opd_doc_id=d["id"], text=d["text"])
               for d in with_text]
        out += [Candidate(url=d["url"], title=d["name"], origin="opd_file", opd_doc_id=d["id"])
                for d in docs if len((d["text"] or "").strip()) < 200 and d["url"]]
        return out


ADAPTER = ZurichCity()
