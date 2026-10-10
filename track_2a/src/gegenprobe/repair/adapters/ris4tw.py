"""St. Gallen (SG) and Solothurn (SO) cantons: the parliaments' Ratsinformationssystem (4teamwork RIS) has a JSON API.

  https://<host>/api/businesses/<id>/published_documents
lists a business's published documents with their type ("Antwort", "Stellungnahme", "Wortlaut", ...), title ("Antwort
der Regierung vom 12. August 2025") and file path (/media/documents/published/[signed/]<uuid>.pdf). <id> is OPD's
affair external_id (also the last segment of OPD's url_external, https://<host>/geschaefte/<id>). robots.txt on both
hosts is the single-page app's HTML (no rules): no restrictions. The date check uses the date in the document title
("vom <date>"), then the dates printed in the PDF.
"""
from __future__ import annotations

import json
import re

from . import robots
from ..common import parse_dates
from .base import Adapter, Candidate, Failure

HOSTS = {"SG": "https://www.ratsinfo.sg.ch", "SO": "https://ratsinfo.so.ch"}
LABELS = {"SG": "St. Gallen (canton)", "SO": "Solothurn (canton)"}
ANSWER_TYPE = re.compile(r"Antwort|Stellungnahme|Beantwortung|Bericht|Regierungsratsbeschluss|RRB", re.I)
NOT_ANSWER = re.compile(r"Wortlaut|Vorstoss|Protokoll|Abstimmung|Kantonsratsbeschluss|Erheblich|Traktand", re.I)
HEADING = re.compile(
    r"Antwort der Regierung|Die Regierung antwortet|Die Regierung beantwortet|Stellungnahme des Regierungsrate?s|"
    r"Stellungnahme der Regierung|Antwort des Regierungsrate?s|Der Regierungsrat (beantwortet|nimmt)|"
    r"Regierungsratsbeschluss vom|Antrag des Regierungsrate?s|Bericht der Regierung|Beschluss(es)?entwurf",
    re.I,
)
EXT = re.compile(r"/geschaefte/(\d+)")


class RIS4tw(Adapter):
    route = "RIS JSON API /api/businesses/<external_id>/published_documents -> document type 'Antwort'/'Stellungnahme'"
    action = "fetch"
    heading = HEADING

    def __init__(self, body: str):
        self.body = body
        self.label = LABELS[body]
        self.base = HOSTS[body]
        self.hosts = (self.base.split("//")[1],)

    def number_patterns(self, number: str) -> list[str]:
        n = re.escape(number or "")
        return [n.replace(r"\ ", r"\s*")]

    def candidates(self, x: dict, opd: list[dict]) -> list[Candidate]:
        ext = x.get("external_id")
        if not (ext and str(ext).isdigit()):
            m = EXT.search(x.get("url_external") or "")
            ext = m.group(1) if m else None
        if not ext:
            raise Failure("no_source_key", "no external id")
        docs = json.loads(robots.get(f"{self.base}/api/businesses/{ext}/published_documents", timeout=60, tries=3))
        out = []
        for d in docs:
            typ, title = d.get("document_type_name") or "", d.get("title") or ""
            if NOT_ANSWER.search(typ) and not ANSWER_TYPE.search(title):
                continue
            if not (ANSWER_TYPE.search(typ) or ANSWER_TYPE.search(title)):
                continue
            f = d.get("signed_file") or d.get("file")
            if not f:
                continue
            ds = parse_dates(title)
            out.append(Candidate(url=self.base + f, title=f"{typ}: {title}", origin="source", uid=str(d.get("id")),
                                 source_typed_answer=bool(re.search(r"Antwort|Stellungnahme", typ + title, re.I)),
                                 meta=dict(doc_type=typ, published=d.get("published_date"),
                                           doc_date=ds[-1][0] if ds else None)))
        out.sort(key=lambda c: (not c.source_typed_answer, c.title))
        return out


def adapter(body: str) -> RIS4tw:
    return RIS4tw(body)
