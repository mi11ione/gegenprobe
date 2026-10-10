"""Canton of Lucerne, OPD body LU: the Kantonsrat's affair page (www.lu.ch; robots.txt allows everything).

  OPD url_external  https://www.lu.ch/kr/parlamentsgeschaefte/detail?ges=<external_id>
lists the affair's documents; the government's answer is the link titled "Antwort des Regierungsrates" (questions,
interpellations) or "Stellungnahme des Regierungsrates" (motions, postulates):
  https://www.lu.ch/-/klu/ris/cdws/document?fileid=<32 hex>
The PDF opens "Luzern, <date>" and "ANTWORT AUF ANFRAGE A 721" / "STELLUNGNAHME ZU POSTULAT P 517", then
"Nummer: P 517" and the title; OPD's number is "2025P 517".
"""
from __future__ import annotations

import html
import re

from . import robots
from .base import Adapter, Candidate, Failure

LINK = re.compile(r'<a[^>]*href="(/-/klu/ris/cdws/document\?fileid=[0-9a-f]{32})"[^>]*>\s*([^<]{0,120})', re.I)
ANSWER_LINK = re.compile(r"Antwort des Regierungsrates|Stellungnahme des Regierungsrates|Antwort|Stellungnahme", re.I)
HEADING = re.compile(r"ANTWORT AUF (?:ANFRAGE|INTERPELLATION|DRINGLICHE)|STELLUNGNAHME ZU(?:R)? (?:POSTULAT|MOTION|"
                     r"ANFRAGE|INTERPELLATION|BEGEHREN)|Antwort des Regierungsrate?s|Stellungnahme des Regierungsrate?s",
                     re.I)


class Lucerne(Adapter):
    body = "LU"
    label = "Luzern (canton)"
    route = "lu.ch affair page (OPD url_external) -> link 'Antwort/Stellungnahme des Regierungsrates' -> cdws document"
    action = "fetch"
    hosts = ("www.lu.ch",)
    heading = HEADING
    header_date = re.compile(r"Luzern, (\d{1,2}\.\s*\w+\s+\d{4})")

    def number_patterns(self, number: str) -> list[str]:
        m = re.match(r"^(\d{4})\s*([A-Z]+)\s*(\d+)$", number or "")
        if not m:
            return [re.escape(number or "")]
        return [rf"\b{m.group(2)}\s*{m.group(3)}\b"]

    def candidates(self, x: dict, opd: list[dict]) -> list[Candidate]:
        u = x.get("url_external")
        if not u:
            raise Failure("no_source_key", "no url_external")
        page = robots.get(u, timeout=60, tries=3).decode("utf-8", "replace")
        out = []
        for href, label in LINK.findall(page):
            label = html.unescape(label).strip()
            if ANSWER_LINK.search(label):
                fid = href.split("=")[-1]
                out.append(Candidate(url="https://www.lu.ch" + href, title=label, origin="source", uid=fid,
                                     source_typed_answer=True))
        return out


ADAPTER = Lucerne()
