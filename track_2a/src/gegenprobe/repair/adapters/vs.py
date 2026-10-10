"""Canton of Valais, OPD body VS: the Grand Conseil's front-end JSON API (parlement.vs.ch; robots.txt is empty).

  https://parlement.vs.ch/api/fe/v1/entity?id=<OPD external_id>     the affair (ParlProcess) and its documents
  https://parlement.vs.ch/api/fe/v1/document?id=<document id>&locale=fr|de   a document's attachment (PDF) URL per
                                                                    language (written-question answers exist in one
                                                                    language; the other is a "not translated" stub)
The answer document is the member labelled `..._ANT` (Antwort / réponse) or `..._REP`; the PDF prints "ANTWORT AUF DIE
MOTION" / "RÉPONSE À LA MOTION ..." and closes "Sitten, den <date>" / "Sion, le <date>". OPD's answer event for VS
is the answer's date for written questions and the treating session for motions, so the date rule is: equal, or the
answer precedes OPD's event by at most 120 days. Identity: the number or title printed, or the source's own label of
the document carries OPD's affair number (`source_label`). `_ANT` documents that only point to an oral answer
("cf. réponse orale", "Pas de réponse pour les Interpellations") are typed `oral_pointer`, never proposed.
"""

from __future__ import annotations

import json
import re

from . import robots
from ..common import parse_dates
from .base import Adapter, Candidate, Failure, fetch_text

API = "https://parlement.vs.ch/api/fe/v1"
ANSWER_LABEL = re.compile(r"_(ANT|REP)\b|_(ANT|REP)_", re.I)
HEADING = re.compile(
    r"ANTWORT AUF (?:DIE|DAS|DEN)|Antwort des Staatsrate?s|R[ÉE]PONSE (?:À|A|AU|AUX) (?:LA |L.)?"
    r"(?:MOTION|POSTULAT|INTERPELLATION|QUESTION|R[ÉE]SOLUTION)|R[ée]ponse du Conseil d.[ÉE]tat|"
    r"Le Conseil d.[ÉE]tat r[ée]pond|Der Staatsrat (?:beantwortet|antwortet)|"
    r"(?:Anfrage|Frage|Fragen|Interpellation)[^.:]{0,60}? wie folgt (?:zu )?beantworten|Im Namen des Staatsrate?s|"
    r"r[ée]pondre comme (?:il )?suit|y r[ée]pondre comme suit|En accord avec le Conseil d.[ÉE]tat, nous|"
    r"En accord avec le Conseil d.[ÉE]tat, nous vous (?:remettons|transmettons)|notre (?:d[ée]termination|r[ée]ponse) "
    r"(?:suite|à votre|relative)|Im Einvernehmen mit dem Staatsrat|(?:unsere|die) (?:Stellungnahme|Antwort) (?:zu|auf) "
    r"Ihre(?:r)? (?:schriftlichen )?Frage",
    re.I,
)
STUB = re.compile(r"ne sont pas traduites|werden nicht [üu]bersetzt", re.I)
ORAL = re.compile(
    r"r[ée]ponse orale|m[üu]ndliche Antwort|Pas de r[ée]ponse pour les Interpellations|"
    r"pas de r[ée]ponse car",
    re.I,
)


class Valais(Adapter):
    body = "VS"
    label = "Valais (canton)"
    route = "parlement.vs.ch /api/fe/v1/entity?id=<external_id> -> member '_ANT'/'_REP' -> /api/fe/v1/document -> PDF"
    action = "fetch"
    hosts = ("parlement.vs.ch",)
    heading = HEADING
    # OPD's answer event: for written questions the answer's own date (equal); for motions the session that treated
    # the motion, which the Conseil d'Etat's written answer precedes (first full run: event - answer date 0..217 days,
    # median ~55; 145 of 172 within 120 days)
    date_window = (0, 120)
    header_date = re.compile(r"\bDat(?:e|um)\b[\s\S]{0,120}?(\d{1,2}\.?\s*(?:\d{1,2}\.\s*|[A-Za-zéèûäöüÉÈ]+\s+)\d{4})")
    header_window = 1500

    def doc_date(self, text: str, c: Candidate) -> str | None:
        """The closing "Sitten, den / Sion, le <date>" first (answers to motions: their header table carries the
        motion's own date), then the letter's "Date <date>" (answers to written questions)."""
        ms = list(self.tail_date.finditer(text))
        m = ms[-1] if ms else None
        if m:
            ds = parse_dates(m.group(1))
            if ds:
                return ds[0][0]
        return super().doc_date(text, c)
    tail_date = re.compile(r"(?:Sitten|Sion), (?:den |le )?(\d{1,2}(?:er)?\.?\s*(?:\d{1,2}\.\s*|[A-Za-zéèûäöü]+\s+)\d{4})")

    def number_patterns(self, number: str) -> list[str]:
        n = re.escape(number or "")
        return [n, n.replace("_", r"[_ ]")]

    def text(self, c: Candidate):
        t, m = fetch_text(c.url, self.body, ocr=self.ocr)
        if len(t) < 1500 and ORAL.search(t):
            raise Failure("oral_pointer", "the answer document points to an oral answer")
        if len(t) < 1500 and STUB.search(t):
            raise Failure("translation_stub", "language placeholder (answers to written questions are not translated)")
        if len(t.strip()) < 200:
            raise Failure("empty_text", f"{len(t.strip())} chars after extraction ({m['extractor']})")
        m["chars"] = len(t)
        return t, m

    def candidates(self, x: dict, opd: list[dict]) -> list[Candidate]:
        ext = x.get("external_id")
        if not ext:
            raise Failure("no_source_key", "no external id")
        ent = json.loads(robots.get(f"{API}/entity?id={ext}", timeout=60, tries=3))
        out = []
        for m in ent.get("members") or []:
            lab = m.get("label") or ""
            if m.get("_type_class") != "Document" or not ANSWER_LABEL.search(lab):
                continue
            for loc in ("fr", "de"):
                doc = json.loads(robots.get(f"{API}/document?id={m['id']}&locale={loc}", timeout=60, tries=3))
                for v in doc.get("attachment_versions") or []:
                    if (
                        (v.get("attachment_type") or "").endswith("pdf")
                        and v.get("attachment_path")
                        and v["attachment_path"] not in {c.url for c in out}
                    ):
                        same = (doc.get("parl_process_number") or "").strip() == (x["number"] or "").strip()
                        out.append(
                            Candidate(
                                url=v["attachment_path"],
                                title=lab,
                                origin="source",
                                uid=str(m["id"]),
                                source_typed_answer=True,
                                meta=dict(
                                    api_date=doc.get("date"),
                                    api_number=doc.get("parl_process_number"),
                                    api_number_eq=same,
                                    source_identity="source_label" if same and (x["number"] or "#") in lab else None,
                                    locale=loc,
                                ),
                            )
                        )
        return out


ADAPTER = Valais()
