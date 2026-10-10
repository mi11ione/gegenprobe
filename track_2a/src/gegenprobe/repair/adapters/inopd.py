"""The answer is already in OPD, on the affair, but nothing marks it as the answer (generic adapter, any parliament).

Many councils file the executive's answer under the intervention's title or a file name ("Vorstoss - V2017.154",
"2019_0375", "Nordumfahrung", "Ligne Delle-Belfort. Alain Bohlinger (PLR)"), and the answer opens with a formula the
census lexicon (census/defs.py, frozen) does not list: "Der Stadtrat beantwortet die Einfache Anfrage wie folgt",
"Auf Antrag ... beantwortet der Stadtrat die Interpellation wie folgt", "Réponse du Gouvernement à la question écrite",
"Il Municipio risponde". This adapter reads OPD's own text of every document on the affair (opd_docs snapshot) and
proposes `tag_answer` when one of them passes the three checks; a document OPD holds without usable text whose name or
URL says it is the answer is fetched (from the parliament when robots.txt allows the path, else from OPD's own copy on
files.openparldata.ch) and extracted: `extract_tag`.

The answer formulas below are answer-specific: phrases that occur in questions ("prié de répondre", "um schriftliche
Beantwortung", "Souhait d'une réponse écrite") and in council minutes ("prend acte de la réponse") are excluded.
"""
from __future__ import annotations

import re
import urllib.parse

from ... import net
from . import robots
from .base import Adapter, Candidate, flatten

EXEC_DE = r"(?:Stadtrat|Gemeinderat|Regierungsrat|Regierung|Kleine Rat|Stadtregierung|Gemeindevorstand|Stadtpräsident)"
EXEC_FR = (r"(?:Conseil communal|Conseil d.[ÉEée]tat|Municipalit[ée]|Conseil municipal|Gouvernement|Conseil administratif|"
           r"Conseil-ex[ée]cutif)")
EXEC_IT = r"(?:Municipio|Consiglio di Stato)"
HEADING = re.compile(
    rf"beantwortet (?:der|die|den) {EXEC_DE}[^.:]{{0,90}}?wie folgt|"
    rf"(?:Der|Die) {EXEC_DE} beantwortet [^.:]{{0,90}}?wie folgt|"
    r"wird wie folgt beantwortet|beantwortet[^.:]{0,40}(?:Anfrage|Interpellation|Fragen|Motion|Postulat)[^.:]{0,40}wie folgt|"
    rf"Antwort de[rs] {EXEC_DE}e?s?\b|Stellungnahme de[rs] {EXEC_DE}e?s?\b|"
    # a title "Beantwortung der Interpellation ...", not a citation ("in der Beantwortung der Anfrage 2016.7")
    r"(?<!der )(?<!seiner )(?<!ihrer )(?<!die )(?<!zur )(?<!um )(?<!aus der )"
    r"Beantwortung der (?:Einfachen |Kleinen |dringlichen |schriftlichen )?(?:Anfrage|Interpellation)\b(?! wird| ist| sei)|"
    rf"(?<!acte de la )(?<!acte de )R[ÉEée]PONSE (?:DU |DE LA |DE L.)?{EXEC_FR}[^.]{{0,30}}(?:À|A|AU|AUX)\b|"
    rf"(?<!acte de la )(?<!acte de )R[ée]ponse (?:du |de la |de l.)?{EXEC_FR} (?:à|a|au|aux)\b|"
    rf"Vortrag des {EXEC_DE}e?s? an den (?:Stadtrat|Gemeinderat|Einwohnerrat)|Der Stadtrat an den Gemeinderat|"
    rf"(?:Le|La) {EXEC_FR} r[ée]pond (?:comme suit|aux questions|ainsi)|"
    r"R[ÉE]PONSE (?:À|A) L.(?:QUESTION|INTERPELLATION)|AU NOM DU GOUVERNEMENT DE LA R[ÉE]PUBLIQUE|"
    r"RAPPORT (?:INTERM[ÉEée]DIAIRE )?DU CONSEIL D.[ÉEée]TAT AU GRAND CONSEIL|"
    r"R[ée]ponse [ée]crite du Conseil d.[ÉEée]tat|R[ée]ponse (?:à|a) la question [ée]crite|"
    r"(?:DER|Der) (?:STADTRAT|Stadtrat|GEMEINDERAT|Gemeinderat) AN DEN "
    r"(?:EINWOHNERRAT|GEMEINDERAT|STADTRAT|Einwohnerrat|Gemeinderat)|"
    rf"Antrag des {EXEC_DE}e?s?:|Begr[üu]ndung (?:zum Postulat|zur Motion)|"
    rf"{EXEC_DE} beantwortet die (?:Kleine |Einfache )?(?:Anfrage|Interpellation) im Namen|"
    r"(?:Anfrage|Frage|Fragen|Interpellation)[^.:]{0,60}? wie folgt (?:zu )?beantworten|Im Namen des Staatsrate?s|"
    r"r[ée]pondre comme (?:il )?suit|y r[ée]pondre comme suit|En accord avec le Conseil d.[ÉE]tat, nous|"
    rf"Risposta (?:del|dal) {EXEC_IT}|Il {EXEC_IT} risponde|risposta all.interrogazione|"
    r"(?:in|con la presente diamo) risposta alla (?:Sua|vostra|sua) interrogazione|"
    r"ci riferiamo alla (?:vostra|sua|Sua|Vostra) interrogazione|si risponde come|"
    r"con riferimento all.interrogazione (?:citata|in oggetto)|"
    rf"{EXEC_DE} des Kantons \w+ an den (?:Grossen Rat|Kantonsrat|Landrat)|"
    r"rispondiamo (?:alla|alle) (?:sua|Sua|vostra|vostre|Vostra) (?:interrogazion|domand)",
    re.I,
)
# the legislature's own minutes quote or acknowledge the answer ("prend acte de la réponse", "Teilprotokoll"); they are
# never proposed as the answer itself
MINUTES_NAME = re.compile(r"^(?:Protokoll|Teilprotokoll|Beschlussprotokoll|Wortprotokoll|PV|Proc[eè]s-verbal|Verbale)\b|"
                          r"Protokolleintrag|Sitzungsprotokoll|_PV_|KR_Teilprotokoll|D[ée]lib[ée]r[ée]", re.I)
MINUTES_TEXT = re.compile(r"^\W*(?:EXTRAIT DU PROC[ÈE]S-VERBAL DU CONSEIL (?:COMMUNAL|G[ÉE]N[ÉE]RAL)|Teilprotokoll|"
                          r"Protokolleintrag|Wortprotokoll|Beschlussprotokoll|Protokoll der \d+\. Sitzung)", re.I)
ANSWER_NAME = re.compile(r"r[ée]ponse|reponse|risposta|antwort|beantwortung|stellungnahme|RepEcr|_ANT\b|_REP\b", re.I)
GENERIC_HEADER_DATE = re.compile(
    r"(?:Beantwortung|Sitzung vom|Beschluss vom|Antwort de[rs] \w+ vom|transmise aux membres du Grand Conseil le|"
    r"distribu[ée]e en session le|r[ée]pondu en s[ée]ance du Conseil g[ée]n[ée]ral le|, (?:den|le|il)|Delémont, le|"
    r"Locarno,|Lugano,|Bellinzona,)\s+(\d{1,2}(?:er|°)?\.?\s*(?:\d{1,2}\.\s*|[A-Za-zéèûäöü]+\s+)\d{4})", re.I)


class InOPD(Adapter):
    route = ("OPD's own documents on the affair: an answer formula in OPD's text (tag_answer); an answer-named file "
             "without text is fetched and extracted (extract_tag)")
    action = "extract_tag"
    heading = HEADING
    header_date = GENERIC_HEADER_DATE
    header_window = 1500

    def __init__(self, body: str, label: str = "", heading: re.Pattern | None = None, window: tuple[int, int] = (0, 0),
                 number_rx=None, answer_name: re.Pattern | None = None, use_oparl_copy: bool = True,
                 all_docs: bool = False, number_shape: re.Pattern | None = None):
        self.body, self.label = body, label or body
        if heading is not None:
            self.heading = heading
        self.date_window = window
        self._number_rx = number_rx
        self.answer_name = answer_name or ANSWER_NAME
        self.use_oparl_copy = use_oparl_copy
        self.all_docs = all_docs  # every document on the affair is a candidate (the body files the answer as "the" doc)
        self.hosts = ("files.openparldata.ch",)
        self.number_shape = number_shape

    def number_patterns(self, number: str) -> list[str]:
        if self._number_rx:
            return self._number_rx(number)
        n = (number or "").strip()
        out = [re.escape(n).replace(r"\ ", r"\s*")]
        m = re.match(r"^(\d{4})[./-]0*(\d+)$", n)
        if m:
            out.append(rf"{m.group(1)}\s*[./-]\s*0*{m.group(2)}")
        return out

    def file_url(self, d: dict) -> str | None:
        """The parliament's URL when robots.txt allows it, else OPD's own copy (files.openparldata.ch/doc/...)."""
        u = d.get("url")
        if u:
            try:
                if robots.allowed(net.quote_url(u)):
                    return u
            except Exception:  # robots unreadable for the host: fall back to OPD's copy
                pass
        return d.get("url_oparl") if self.use_oparl_copy else None

    def candidates(self, x: dict, opd: list[dict]) -> list[Candidate]:
        out = []
        opd = [d for d in opd if not MINUTES_NAME.search(d.get("name") or "")
               and not MINUTES_TEXT.search((d.get("text") or "")[:300])]
        texty = [d for d in opd if len((d.get("text") or "").strip()) >= 200]
        hits = [d for d in texty if self.heading.search(flatten(d["text"]))]
        named = [d for d in texty if d not in hits and (self.all_docs or self.answer_name.search(
            (d.get("url") or "") + " " + (d.get("name") or "")))]
        for d in hits + named:
            out.append(Candidate(url=d.get("url"), title=d.get("name") or "", origin="opd_text", opd_doc_id=d["id"],
                                 text=d["text"], source_typed_answer=bool(self.answer_name.search(
                                     (d.get("url") or "") + " " + (d.get("name") or "")))))
        for d in opd:
            if len((d.get("text") or "").strip()) >= 200:
                continue
            if not (self.all_docs or self.answer_name.search(
                    urllib.parse.unquote(d.get("url") or "") + " " + (d.get("name") or ""))):
                continue
            u = self.file_url(d)
            if u:
                out.append(Candidate(url=u, title=d.get("name") or "", origin="opd_file", opd_doc_id=d["id"],
                                     source_typed_answer=not self.all_docs,
                                     meta=dict(parliament_url=d.get("url"))))
        if self.all_docs:  # OPD's text may be garbled (broken font maps): re-extract the file as a last resort
            for d in texty:
                if not self.heading.search(flatten(d["text"])):
                    u = self.file_url(d)
                    if u:
                        out.append(Candidate(url=u, title=d.get("name") or "", origin="opd_file", opd_doc_id=d["id"],
                                             meta=dict(parliament_url=d.get("url"), reextract=True)))
        return out
