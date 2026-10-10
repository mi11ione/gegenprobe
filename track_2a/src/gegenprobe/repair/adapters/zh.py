"""Canton of Zürich, OPD body ZH: the Kantonsrat's CMI content web service (CDWS) lists each affair's steps and documents.

  https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Index/GESCHAEFT/searchdetails?q=krnr any "<KR-Nr.>"&l=de-CH
returns the affair (KRNr = OPD's affair number, e.g. 52/2004) with its steps (Ablaufschritt: "Eingereicht", "Antwort
Regierungsrat", "Stellungnahme Regierungsrat", ...) and per step the documents (eDocument ID, title such as "Antwort RR
52/2004 ..."). The answer PDF is
  https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Files/<eDocument ID>/<version with a pdf rendition>/pdf
the same URL form OPD stores for the question. robots.txt of the host answers 404 (no restrictions, RFC 9309).
The answer is the government's minutes extract: "Auszug aus dem Protokoll des Regierungsrates des Kantons Zürich /
Sitzung vom 7. April 2004 / 522. Anfrage (<title>) ... wird wie folgt beantwortet"; the date check uses the
"Sitzung vom" date. When OPD already holds the same file (same eDocument ID in a document URL), the row is a relink.
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

from . import robots
from .base import Adapter, Candidate, Failure

API = "https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Index/GESCHAEFT/searchdetails?q={q}&l=de-CH&s=1&m=5"
FILE = "https://parlzhcdws.cmicloud.ch/parlzh5/cdws/Files/{eid}/{ver}/pdf"
NS = {"g": "http://www.cmiag.ch/cdws/Geschaeft", "r": "http://www.cmiag.ch/cdws/searchDetailResponse"}
STEP = re.compile(r"Antwort|Stellungnahme|Bericht|Antrag des Regierungsrates|Beantwortung", re.I)
DOC = re.compile(r"^(Antwort|Stellungnahme|Bericht|Vorlage|RRB|Beschluss des Regierungsrates|Auszug)", re.I)
HEADING = re.compile(
    r"wird wie folgt beantwortet|beantwortet[\w ,]{0,60}wie folgt|Antwort des Regierungsrate?s|"
    r"Stellungnahme des Regierungsrate?s|Antrag des Regierungsrates|Bericht des Regierungsrates|"
    r"Auf Antrag de[rs] [\w\- ]{0,60}beschliesst der Regierungsrat",
    re.I,
)
HEADER_DATE = re.compile(r"(?:Sitzung vom|Antrag des Regierungsrates vom|Regierungsratsbeschluss vom)\s+"
                         r"(\d{1,2}\.\s*\w+\s+\d{4})", re.I)
EID = re.compile(r"/Files/([0-9a-f]{32})-\d+/", re.I)


class Zurich(Adapter):
    body = "ZH"
    label = "Zürich (canton)"
    route = "Kantonsrat CDWS search by KR-Nr. -> step 'Antwort Regierungsrat' document -> Files/<id>/1/pdf"
    action = "fetch"
    hosts = ("parlzhcdws.cmicloud.ch",)
    heading = HEADING
    header_date = HEADER_DATE
    _opd_eids: dict[str, dict] | None = None

    def opd_eids(self) -> dict[str, dict]:
        if self._opd_eids is None:
            from . import opd_docs
            self._opd_eids = {}
            for d in opd_docs.url_index("ZH"):
                m = EID.search(d.get("url") or "")
                if m:
                    self._opd_eids.setdefault(m.group(1), d)
        return self._opd_eids

    def candidates(self, x: dict, opd: list[dict]) -> list[Candidate]:
        q = urllib.parse.quote(f'krnr any "{x["number"]}"')
        xml = robots.get(API.format(q=q), timeout=90, tries=3)
        root = ET.fromstring(xml)
        out = []
        found = False
        for g in root.iter("{%s}Geschaeft" % NS["g"]):
            if (g.findtext("g:KRNr", default="", namespaces=NS) or "").strip() != x["number"]:
                continue
            found = True
            for step in g.iter("{%s}Ablaufschritt" % NS["g"]):
                typ = step.findtext("g:AblaufschrittTyp", default="", namespaces=NS) or ""
                sdate = step.findtext("g:Sitzungsdatum/g:Text", default="", namespaces=NS)
                for doc in step.iter("{%s}Dokument" % NS["g"]):
                    title = doc.findtext("g:Titel", default="", namespaces=NS) or ""
                    ed = doc.find("g:eDocument", NS)
                    if ed is None or not ed.get("ID"):
                        continue
                    if not (STEP.search(typ) or DOC.search(title)):
                        continue
                    eid = ed.get("ID")
                    vers = [v.get("Nr") for v in ed.findall("g:Version", NS)
                            if any((r.get("Extension") or "").lower() == "pdf" for r in v.findall("g:Rendition", NS))]
                    if not vers:
                        continue
                    full = ed.findtext("g:Fulltext", default=None, namespaces=NS)
                    c = Candidate(url=FILE.format(eid=eid, ver=vers[-1]), title=title, origin="source", uid=eid,
                                  source_typed_answer=bool(re.search(r"Antwort|Stellungnahme", typ + " " + title, re.I)),
                                  meta=dict(step=typ, step_date=sdate, api_fulltext_chars=len(full or "")))
                    held = self.opd_eids().get(eid.split("-")[0])
                    if held:
                        held = dict(held, same_affair=held.get("affair_id") == x["id"])
                        c.meta["opd_holds"] = dict(id=held["id"], affair_id=held["affair_id"], chars=held["chars"],
                                                   agenda_id=held["agenda_id"], meeting_id=held["meeting_id"],
                                                   same_affair=held["same_affair"])
                    out.append(c)
        if not found:
            raise Failure("not_found", f"KR-Nr. {x['number']} not in CDWS")
        out.sort(key=lambda c: (not c.source_typed_answer, c.title))
        return out


ADAPTER = Zurich()
