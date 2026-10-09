"""Document-type classifier over OPD doc metadata (name, category, harmonised category, URL) — no text is read.

  intervention  the member's intervention text (question/motion/postulate/interpellation as submitted)
  answer        the executive's written answer / decision on an intervention (RRB, Schreiben des RR, Risposta, Réponse ...)
  report        Botschaft / Ratschlag / Rapport / Messaggio, or a parliamentary minutes page

Only used to stratify the gold sample; the gold label (answer present? date?) is set by the annotator, not by this guess.
"""

import re

INTERVENTION = re.compile(
    r"vorstosstext|^Vorstoss-(de|fr)$|^Text (Interpellation|Schriftliche Anfrage|Anzug|Motion)|Eingabe Vorstoss|"
    r"^Anfrage_|^Postulat_|^Motion_|^Interpellation_|^Vorstoss - |_EIN_|^(Interrogazione|Interpellanza|Mozione)_\d+|"
    r"^\d{4}_\d{4} (Postulat|Motion|Interpellation|Schriftliche Anfrage|Dringliche)|^(QUE|Q|M|P|IUE) \d+$|^Proposition de motion|"
    r"^Interpellation (urgente )?(écrite )?\d|^Question écrite|^Postulat\b|^Motion\b|submitted_text",
    re.I,
)
ANSWER = re.compile(
    r"vorstossantwort|^RRB\b|^RRB[-:]|^Antwort_RR_|Schreiben des RR|"
    r"Beantwortung - (Antwort|Stellungnahme)|^(QUE|Q|M|P|IUE) \d+-A$|"
    r"^Rapport du Conseil d.Etat (M|P|Q|QUE|IUE)|Risposta del CdS|_ANT\b|^Antwort Stadtrat|"
    r"^RispostaInterrogazione|^OsservazioneMunicipio|"
    r"risposta|R[ée]ponse du (Conseil|Gouvernement|Municipal|Conseil municipal|Conseil communal)|response_text|r[ée]?ponse",
    re.I,
)
REPORT = re.compile(
    r"Wortlautdokument|^Vortrag|KR_Teilprotokoll|Ratschlag des RR|Kantonsratsprotokoll|Botschaft|^Rapport (PL|M|P|RD) |^Rapporto|"
    r"^Messaggio|^Rapport du Conseil d.Etat (PL|RD)|Protokollauszug|^Protokoll|proc[eè]s-verbal|^Verbale|protocol",
    re.I,
)


INTERVENTION_TYPES = {"Interpellation", "Motion", "Postulate", "Question", "Question time"}


def doc_type(d: dict) -> str | None:
    s = " ".join(str(x) for x in (d.get("name"), d.get("cat"), d.get("ch")) if x)
    if ANSWER.search(s):
        return "answer"
    if INTERVENTION.search(s):
        return "intervention"
    if REPORT.search(s):
        return "report"
    # TI files every text as "Versione PDF"; on an intervention-type affair that is the intervention text
    if d.get("b") == "TI" and (d.get("name") or "").startswith("Versione PDF") and d.get("a_type") in INTERVENTION_TYPES:
        return "intervention"
    return None
