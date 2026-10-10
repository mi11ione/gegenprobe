"""Document-type filters: a document can print the affair, an answer formula and a matching date and still not be the
government's answer. Each filter recognises one such document type from its own wording (deterministic, no model) and
moves the row down, never up: to `review` or `failed`, with a typed reason. The classes come from the blind audit of the
first adapter run (docs/adapters.md, "Audit"); every filter is tested on short synthetic excerpts (tests/test_adapter_filters.py).

  wrong_affair         the document's header prints an affair number of the parliament's own shape that is not the
                       target's, and the target's number is printed nowhere in the document (Solothurn: an RRB on
                       A 0110/2024 filed under A 0113/2024); a header typo is possible, so                     -> review
  extension_request    the subject line asks for (or grants) more time to answer: Fristverlängerung,
                       Fristerstreckung, prolongation du délai, proroga del termine; and the header does not
                       announce the answer or the closing report itself                                         -> failed
  parliament_report    a report of a parliamentary body (commission, Ratsbüro), not of the executive: "Rapporto della
                       commissione", "Bericht der ...kommission", "Bericht des Ratsbüros", "Rapport de la
                       commission"; and the header carries no executive answer formula                          -> failed
  minutes_reference    the legislature's minutes, which only refer to the written answer ("Die Antwort des
                       Stadtrates liegt schriftlich vor", "auf die separaten Akten verwiesen") and print no answer
                       formula of their own                                                                    -> failed
  member_text_only     the member's own text: it opens or closes as the question ("ANFRAGE von ...", "presentano
                       la seguente interrogazione", "Nell'attesa di una risposta", "Nous remercions le Gouvernement
                       de ses réponses") and no executive answer formula is printed outside a citation          -> failed
  resolution_reply     the executive's reply to a resolution the council adopted after the answer to the
                       interpellation (Lausanne): an executive document, but not the answer itself             -> review
"""
from __future__ import annotations

import dataclasses
import re

HEAD = 700   # characters of the flattened text that hold the subject line / letterhead
TAIL = 900   # characters at the end that hold the closing formula and the signatures


@dataclasses.dataclass
class Hit:
    reason: str
    outcome: str  # review | failed
    quote: str


def _q(ft: str, m: re.Match, pad: int = 50) -> str:
    return re.sub(r"\s+", " ", ft[max(0, m.start() - pad):m.end() + pad]).strip()[:200]


# ---------------------------------------------------------------- the executive's own answer formulas
EXEC_DE = (r"(?:Regierungsrate?s?|Stadtrate?s?|Gemeinderate?s?|Regierung|Kleinen Rate?s?|Stadtregierung|"
           r"Gemeindevorstande?s?|Staatsrate?s?)")
EXEC_FR = (r"(?:Conseil communal|Conseil d.[ÉEée]tat|Municipalit[ée]|Conseil municipal|Gouvernement|"
           r"Conseil administratif|Conseil-ex[ée]cutif)")
EXEC_IT = r"(?:Municipio|Consiglio di Stato)"
# phrases that only the executive's answer prints (never a citation of it): used to decide that a document "also
# contains the answer"
ANSWER_FORMULA = re.compile(
    r"wird wie folgt beantwortet|beantwortet[^.:]{0,120}?wie folgt|"
    rf"(?:Der|Die|Das) {EXEC_DE} (?:beantwortet|antwortet|nimmt (?:wie folgt )?Stellung)|"
    rf"Auszug aus dem Protokoll de[rs] {EXEC_DE}|Regierungsratsbeschluss vom|"
    rf"Vortrag des {EXEC_DE} an den|(?:Der|Die) (?:Stadtrat|Gemeinderat|Regierungsrat) an den "
    r"(?:Einwohnerrat|Gemeinderat|Stadtrat|Grossen Rat|Kantonsrat|Landrat)|"
    rf"Antrag des {EXEC_DE}:|erteilt (?:mündlich )?die Antwort|"
    rf"(?:Le|La) {EXEC_FR} r[ée]pond|r[ée]pondre comme (?:il )?suit|"
    rf"R[ée]ponse (?:du |de la |de l.)?{EXEC_FR} (?:à|a|au|aux)\b|R[ée]ponse [ée]crite du Conseil d.[ÉEée]tat|"
    rf"Il {EXEC_IT} risponde|Risposta (?:del|dal) {EXEC_IT}|{EXEC_IT} (?:risponde|comunica) quanto segue|"
    r"(?:in|con la presente diamo) risposta alla (?:Sua|sua|vostra|Vostra) interrogazione|"
    r"rispondiamo (?:alla|alle) (?:sua|Sua|vostra|vostre|Vostra) (?:interrogazion|domand)|si risponde come",
    re.I,
)
# the words before a formula that make it a citation ("nella risposta all'interrogazione 661", "suite à la réponse à
# l'interpellation", "um rasche Beantwortung der Anfrage")
CITATION_BEFORE = re.compile(
    r"(?:nella|dalla|alla|della|sua|vedi|come da|anticipato|dans (?:sa|la|leur)|suite [àa]|traitement de|selon|"
    r"in (?:der|seiner|ihrer)|mit der|zufrieden|befriedigt|um (?:eine )?(?:rasche |baldige |schriftliche )?|"
    r"bitten?|danken?|vgl\.?|cf\.?|laut|gemäss|gem\.)\W*(?:\S+\s+){0,3}\S*$",
    re.I,
)


def answer_printed(ft: str, heading: re.Pattern | None = None) -> re.Match | None:
    """The first executive answer formula (or the adapter's heading) printed outside a citation, else None."""
    for rx in (ANSWER_FORMULA, heading):
        if rx is None:
            continue
        for m in rx.finditer(ft):
            if not CITATION_BEFORE.search(ft[max(0, m.start() - 60):m.start()]):
                return m
    return None


# ---------------------------------------------------------------- wrong affair
def _num_key(s: str) -> str:
    """'A 0110/2024' -> 'A0110/2024'; '276a/2021' -> '276/2021' (a Vorlage letter belongs to the same affair);
    '2019/0375' -> '2019/375'."""
    s = re.sub(r"\s+", "", s).upper()
    s = re.sub(r"^(\d+)[A-Z](/)", r"\1\2", s)
    return re.sub(r"(?<=[/.])0+(?=\d)", "", s)


def wrong_affair(ft: str, x: dict, shape: re.Pattern | None, patterns: list[str] | None = None) -> Hit | None:
    """The header prints affair numbers of the parliament's shape, none of them is the target's (equal after
    normalisation), and the target's number (in the adapter's own spellings `patterns`) is printed nowhere in the
    document: the identity rests on the title or the source's metadata alone. Joint answers print the target too and
    pass. The header number can be a typo (Zürich canton, 1999: "KR-Nr. 468/1998" on the answer to 486/1998), so the
    row goes to review, not failed; a row whose identity check failed is failed anyway (Solothurn A 0113/2024)."""
    if shape is None or not x.get("number"):
        return None
    found = list(shape.finditer(ft[:HEAD]))
    if not found:
        return None
    want = _num_key(x["number"])
    if any(_num_key(m.group(1) if m.groups() else m.group(0)) == want for m in found):
        return None
    if any(re.search(r"(?<![\w/.])" + p + r"(?![\w/]|\.\d)", ft) for p in patterns or ()):
        return None
    return Hit("wrong_affair", "review", _q(ft, found[0]))


# ---------------------------------------------------------------- deadline extension
EXTENSION = re.compile(
    r"Fristverl[äa]ngerung|Fristerstreckung|Fristenerstreckung|Verl[äa]ngerung der (?:Behandlungs|Erfüllungs)?frist|"
    r"Erstreckung der (?:Behandlungs|Erfüllungs)?frist|prolongation (?:du|de|des) d[ée]lais?|"
    r"(?:report|prolongation) de l.[ée]ch[ée]ance|proroga (?:del|dei) termin[ei]|prolungamento (?:del|dei) termin[ei]",
    re.I,
)
# the subject announces the answer or the closing report together with the extension
EXTENSION_WITH_ANSWER = re.compile(
    r"Prüfungsbericht|Schlussbericht|Abschreibung|(?<!für die )(?<!zur )(?<!die )Beantwortung|Antwort de[rs]|"
    rf"Stellungnahme de[rs]|Bericht de[rs] {EXEC_DE}|(?<!d[ée]lai de )(?<!d[ée]lai de la )r[ée]ponse|rapport final|"
    r"(?<!termine di )(?<!termine per la )risposta|rapporto finale",
    re.I,
)


def extension_request(ft: str, title: str) -> Hit | None:
    """The extension is in the subject line (the head, or the candidate's title), the subject does not also announce the
    answer or the closing report (looked for up to the extension word, not in the narrative after it: "die Frist zur
    Vorlage eines Prüfungsberichts" is history), and the text prints no answer formula."""
    head = ft[:HEAD]
    m = EXTENSION.search(head)
    subject = head[:m.end() + 30] if m else ""
    src = head
    if not m:
        m, src = EXTENSION.search(title or ""), title or ""
        subject = title or ""
    if not m:
        return None
    if EXTENSION_WITH_ANSWER.search(subject) or ANSWER_IN_MINUTES.search(ft):
        return None
    return Hit("extension_request", "failed", _q(src, m))


# ---------------------------------------------------------------- reports of parliamentary bodies
PARLIAMENT_REPORT = re.compile(
    r"RAPPORTO (?:DI (?:MAGGIORANZA|MINORANZA) )?(?:DELLA|DELLE) COMMISSION[EI]|Rapporto commissionale|"
    r"RapportoMozione|Rapporto(?:Maggioranza|Minoranza)|"
    r"Bericht des Ratsb[üu]ros|Bericht der (?:[\w\-]+ ){0,3}[\w\-]*[Kk]ommission\b|Kommissionsbericht|"
    r"Bericht und Antrag der (?:[\w\-]+ ){0,3}[\w\-]*[Kk]ommission\b|"
    r"Rapport (?:de (?:majorit[ée]|minorit[ée]) )?de la [Cc]ommission\b|Rapport du Bureau du (?:Grand )?Conseil",
    re.I,
)
EXEC_IN_HEAD = re.compile(
    rf"Il {EXEC_IT} risponde|Risposta del {EXEC_IT}|MESSAGGIO MUNICIPALE|Osservazioni? del {EXEC_IT}|"
    rf"Antwort de[rs] {EXEC_DE}|Stellungnahme de[rs] {EXEC_DE}|Bericht de[rs] {EXEC_DE}|Vortrag de[rs] {EXEC_DE}|"
    rf"Auszug aus dem Protokoll de[rs] {EXEC_DE}|R[ée]ponse (?:du |de la |de l.)?{EXEC_FR}|"
    rf"Rapport (?:du |de la )?{EXEC_FR}",
    re.I,
)


REPORT_HEAD = 300  # the report's own title opens the document (after a letterhead); later it is a citation


def parliament_report(ft: str, title: str) -> Hit | None:
    head = ft[:HEAD]
    m, src = PARLIAMENT_REPORT.search(ft[:REPORT_HEAD]), head
    if not m:
        m, src = PARLIAMENT_REPORT.search(title or ""), title or ""
    if not m or EXEC_IN_HEAD.search(head):
        return None
    return Hit("parliament_report", "failed", _q(src, m))


# ---------------------------------------------------------------- legislature minutes that point to the answer
MINUTES = re.compile(
    r"Protokoll der \d+\.\s*Sitzung|AUSZUG AUS DEM PROTOKOLL\s+SITZUNG VOM|Substantielles Protokoll|"
    r"Beschlussprotokoll|Wortprotokoll|Proc[eè]s-verbal de la s[ée]ance|Verbale della seduta|"
    r"Eine Diskussion wird nicht verlangt|Schlusswort",
    re.I,
)
REFERS_TO_ANSWER = re.compile(
    r"Antwort de[rs] \w+ liegt (?:schriftlich )?vor|schriftliche Antwort (?:liegt|ist)[^.]{0,40} vor|"
    r"auf die separaten Akten verwiesen|die schriftliche Antwort auf die zu Grunde liegende|"
    rf"la r[ée]ponse (?:[ée]crite )?(?:du |de la |de l.)?{EXEC_FR} (?:a [ée]t[ée] (?:distribu|transmise)|est parvenue)|"
    r"risposta scritta (?:del \w+ )?(?:è stata|[èe] gi[àa]) (?:distribuita|trasmessa)",
    re.I,
)
ANSWER_IN_MINUTES = re.compile(r"wird wie folgt beantwortet|beantwortet[^.:]{0,120}?wie folgt|"
                               r"erteilt (?:mündlich )?die Antwort|r[ée]pond (?:comme suit|ainsi)|risponde come segue",
                               re.I)


def minutes_reference(ft: str, title: str) -> Hit | None:
    if not (MINUTES.search(ft[:1500]) or re.search(r"_PROT|Protokoll|Proc[eè]s-verbal|Verbale", title or "", re.I)):
        return None
    m = REFERS_TO_ANSWER.search(ft)
    if not m or ANSWER_IN_MINUTES.search(ft):
        return None
    return Hit("minutes_reference", "failed", _q(ft, m))


# ---------------------------------------------------------------- the member's text only
QUESTION_OPEN = re.compile(
    # the member's own header in capitals ("KR-Nr. 163/1999 ANFRAGE von ..."); an answer's subject line spells it in
    # lower case ("Beantwortung der Interpellation von ...")
    r"(?-i:\bA\s?N\s?F\s?R\s?A\s?G\s?E\s+von\b|\b(?:INTERPELLATION|MOTION|POSTULAT|DRINGLICHE ANFRAGE)\s+von\b)|"
    r"(?:presentano|presentiamo|presento|inoltrano|inoltriamo) (?:la seguente|il seguente|questa|la presente) "
    r"(?:interrogazione|interpellanza|mozione|atto)|"
    r"Initiative\s*:\s*(?:interpellation|question|postulat|motion)|"
    r"^.{0,60}?(?:Dringliche )?Anfrage an den (?:Stadtrat|Gemeinderat|Regierungsrat)\b|^\W*Anfrage\s+Absender|"
    r"(?:nous demandons|je demande|demandons) (?:au|à la) (?:Gouvernement|Conseil d.[ÉEée]tat|Conseil communal|"
    r"Municipalit[ée]) de (?:bien vouloir )?r[ée]pondre",
    re.I,
)
QUESTION_CLOSE = re.compile(
    r"(?:Nell.)?attesa (?:di una|della|delle) (?:vostra |sua |Sua )?rispost[ae]|"
    r"(?:Nous remercions|Je remercie|Merci (?:au|à la)) (?:d.avance )?(?:le |la )?(?:Gouvernement|Conseil d.[ÉEée]tat|"
    r"Municipalit[ée]|Conseil communal)[^.]{0,40}r[ée]ponses?|"
    r"(?:danke|danken) (?:ich|wir)?[^.]{0,40}für die (?:rasche |baldige |schriftliche )?Beantwortung|"
    r"(?:bitte|bitten) (?:ich|wir)?[^.]{0,40}um (?:eine |die )?(?:rasche |baldige |schriftliche )?Beantwortung|"
    r"(?:Ich|Wir) (?:frage|fragen|ersuche|ersuchen) (?:den|die) (?:Regierungsrat|Stadtrat|Gemeinderat|Regierung)\b|"
    r"F[üu]r die (?:[\w./\-]+[ \-])?Fraktion\b",
    re.I,
)


def member_text_only(ft: str, heading: re.Pattern | None) -> Hit | None:
    m = QUESTION_OPEN.search(ft[:HEAD]) or QUESTION_CLOSE.search(ft[-TAIL:])
    if not m:
        return None
    if answer_printed(ft, heading):
        return None
    src = ft if m.re is QUESTION_OPEN else ft[-TAIL:]
    return Hit("member_text_only", "failed", _q(src, m))


# ---------------------------------------------------------------- reply to a council resolution
RESOLUTION = re.compile(
    r"R[ée]solutions? (?:de |du |des )[^«»]{0,250}?adopt[ée]e?s? par le Conseil[^«»]{0,80}?suite [àa] la r[ée]ponse|"
    r"r[ée]ponse (?:[àa] la|aux) r[ée]solutions?",
    re.I,
)


def resolution_reply(ft: str, title: str) -> Hit | None:
    m, src = RESOLUTION.search(ft[:HEAD]), ft
    if not m:
        m, src = RESOLUTION.search(title or ""), title or ""
    if not m and re.search(r"(?:^|[_\s])(?:cc_)?r[ée]solutions?(?:[_\s]|$)", title or "", re.I) \
            and not ANSWER_FORMULA.search(ft[:HEAD]):
        m, src = re.search(r"r[ée]solutions?", title, re.I), title
    if not m:
        return None
    return Hit("resolution_reply", "review", _q(src, m))


# ---------------------------------------------------------------- all filters, in order
REASONS = ("wrong_affair", "extension_request", "parliament_report", "minutes_reference", "member_text_only",
           "resolution_reply")


def screen(ft: str, title: str, x: dict, heading: re.Pattern | None = None, shape: re.Pattern | None = None,
           patterns: list[str] | None = None) -> Hit | None:
    """The first filter that recognises the document (flattened text `ft`, candidate title) as not the answer, else
    None."""
    return (wrong_affair(ft, x, shape, patterns) or extension_request(ft, title) or parliament_report(ft, title)
            or minutes_reference(ft, title) or member_text_only(ft, heading) or resolution_reply(ft, title))
