"""Rules: the submitter and the co-signatories as printed (question document first, then the answer document's title).

Sources, in order: a title line "<Type> [Nr. n] [von] <Name> [und <Name>] betreffend|über|concernant|…"; an author cue
("Signataire :", "Nom et prénom de l'auteur :", "eingereicht von", "Erstunterzeichner/in", "presentata da", …); the
signature block after the last question (lines that are only names); the answer's title ("à l'interpellation <Name> et
consorts", "presentata il … da <Name> e cofirmatari", "Anfrage von <Name> und <Name> betreffend"). Each name is a span.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import Doc, boilerplate_lines

UP = r"[A-ZÄÖÜÉÈÀÂÊÎÔÛÇŠČ]"
LO = r"[a-zäöüéèàâêîôûçëïßšćčñ'’]"
TOK = rf"(?:{UP}{LO}+(?:-{UP}{LO}+)*|{UP}{{2,}}(?:-{UP}{{2,}})*)"
PART = r"(?:von|van|de|di|da|del|dal|della|des|du|le|la|De|Di|Da|Del|Dal)"
INIT = rf"{UP}\."
NAME = rf"(?:(?:Dr\.|Prof\.)[ \t]+)?(?:{TOK}|{INIT})(?:[ \t]+(?:{INIT}[ \t]+)?(?:{PART}[ \t]+)?{TOK}){{1,3}}"
# inside a signature list a name may wrap to the next line
NAME_NL = re.compile(rf"(?:(?:Dr\.|Prof\.)\s+)?(?:{TOK}|{INIT})(?:[ \t]*\n?[ \t]+(?:{INIT}\s+)?(?:{PART}\s+)?{TOK}|"
                     rf"[ \t]*\n[ \t]*(?:{PART}\s+)?{TOK}){{1,3}}")
BE_LINE = re.compile(rf"^[ \t]*(?P<name>(?:{PART}[ \t]+)?{TOK}(?:[ \t]+{TOK})?)[ \t]+\([^)\n]{{2,60}}\)"
                     rf"(?P<lead>[ \t]*\((?:Sprecher/in|Sprecherin|Sprecher|porte-parole|portavoce)\))?[ \t]*$", re.M)
NAME_RX = re.compile(NAME)
TYPES = (r"(?:Dringliche\s+|Schriftliche\s+|Kleine\s+)?(?:Interpellation|Anfrage|Motion|Postulat|Anzug|Frage)|"
         r"Interpellanza|Mozione|Interrogazione|Postulato|Question\s+écrite(?:\s+urgente)?|Résolution")
JOIN = r"(?:\s*,\s*|\s+und\s+|\s+et\s+|\s+e\s+|\s+sowie\s+)"
END = (r"(?=\s*(?:\(|,?\s*betreffend|\s+über\b|\s+concernant|\s+sur\b|\s*:|\s*–|\s+-\s|\s*«|\s*\"|\s*„|,?\s+e\s+cofirmatari|"
       r"\s+und\s+Mit|\s+und\s+Konsort|\s+et\s+consorts|\s+namens|\s+vom\b|\s+du\b|\s+del\b|\s*$))")
TITLE = re.compile(rf"(?i:{TYPES})\s+(?:Nr\.\s*\d+\s+)?(?:von|de|di|del|della|da)?\s*(?P<names>{NAME}(?:\s*\([^)]{{0,60}}\))?"
                   rf"(?:{JOIN}{NAME}(?:\s*\([^)]{{0,60}}\))?)*){END}", re.M)
VON = re.compile(rf"^\s*(?:von|de|di)\s+(?P<names>{NAME}(?:\s*\([^)]{{0,60}}\))?(?:{JOIN}{NAME}(?:\s*\([^)]{{0,60}}\))?)*)",
                 re.M)
CUES = [
    re.compile(rf"(?:Signataires?|Auteure?s?|Interpellante?|Motionärin|Motionär|Postulantin|Postulant|Urheberin|Urheber|"
               rf"Erstunterzeichnerin|Erstunterzeichner|Erstunterzeichnende|eingereicht\s+von|d[ée]pos[ée]e?\s+par|"
               rf"presentat[ao]\s+(?:il\s+[^\n]{{0,30}}?)?da|prim[ao]\s+firmatari[ao]|Nom\s+et\s+pr[ée]nom\s+de\s+l.auteur)"
               rf"\s*:?\s*\n?\s*(?P<names>{NAME})"),
]
ANSWER_TITLE = [
    re.compile(rf"à\s+l.(?:interpellation|question\s+[ée]crite(?:\s+urgente)?|motion|postulat)\s+(?:de\s+)?(?P<names>{NAME}"
               rf"(?:{JOIN}{NAME})*)"),
    re.compile(rf"presentat[ao]\s+(?:il\s+\d{{1,2}}\.?\s*\w+\s+\d{{4}}\s+)?da\s+(?P<names>{NAME}(?:{JOIN}{NAME})*)"),
]
CO_CUE = re.compile(r"Mitunterzeichn\w*|Nom\(?s\)?\s+et\s+pr[ée]nom\(?s\)?\s+du\s+\(?des\)?\s+consort|cofirmatari\s*:|"
                    r"Cosignataires?\s*:", re.I)
NOT_NAME = re.compile(r"^(Regierungsrat|Stadtrat|Gemeinderat|Grosser|Grand|Conseil|Consiglio|Kanton|Canton|Stadt|Ville|Città|"
                      r"Municipio|Kantonsrat|Landrat|Basel|Zürich|Bern|Luzern|Genève|Vaud|Ticino|Bellinzona|Lugano|Gruppo|"
                      r"Fraktion|Groupe|Partito|Partei|Sehr|Signora|Signor|Madame|Monsieur|Herr|Frau|Interpellation|Motion|"
                      r"Postulat|Anfrage|Schriftliche|Kleine|Question|Interpellanza|Mozione|Interrogazione|Seite|Page|"
                      r"Pagina|Datum|Date|Data|Begründung|Antwort|Réponse|Risposta|Der|Die|Das|Le|La|Il|Les|Wir|Nous|Per|"
                      r"Im|In|Am|Zu|Mit|Und|Et|Ein|Eine)\b")


@dataclass
class Person:
    role: str  # submitter | co_signatory
    name: str
    g0: int
    g1: int
    doc: str  # question | answer
    rule: str


def _split_names(doc: Doc, g0: int, s: str) -> list[tuple[str, int, int]]:
    out = []
    for m in NAME_RX.finditer(s):
        name = m.group(0)
        if NOT_NAME.match(name):
            continue
        # a parenthesis right before means party/place, not a name
        out.append((name, g0 + m.start(), g0 + m.end()))
    return out


def _name_line(t: str) -> bool:
    if not t.strip() or not NAME_RX.search(t) and not re.match(rf"\s*{TOK}\s*,?\s*$", t):
        return False
    rest = NAME_RX.sub("", t)
    rest = re.sub(r"\([^)]*\)|\b(und|e|et|sowie)\b|[,;.“”\"»«/\-–]", "", rest)
    letters = len(re.sub(r"\W", "", rest))
    if letters < 4:
        return True
    segs = [x.strip() for x in re.split(r",|;", t) if x.strip()]
    return len(segs) >= 3 and all(re.match(rf"(?:{PART}\s+)?(?:{UP}|{INIT})", x) and len(x.split()) <= 4 and "?" not in x
                                  and not x.endswith(".") or x.endswith(" P.") for x in segs)


SEP = re.compile(r",|;|\s(?:und|e|et|sowie)\s")


def _signature_block(doc: Doc, after: int, skip: set[int]) -> list[tuple[str, int, int]]:
    """Names printed as a signature list after the last question: lines that hold only names (one per line, or comma /
    und / e / et lists whose names may wrap to the next line), or a first signature line '<Name>, <comment>'."""
    lines = [(i, ln) for i, ln in enumerate(doc.lines) if ln.g0 >= after and i not in skip]
    block = []
    for _, ln in lines:
        t = ln.text
        if _name_line(t):
            block.append(ln)
        elif not block:
            m = re.match(rf"\s*({NAME})\s*,\s*[a-zäöüéèà]", t)
            if m and not NOT_NAME.match(m.group(1)):
                return [(m.group(1), ln.g0 + m.start(1), ln.g0 + m.end(1))]
        elif t.strip() and not re.fullmatch(r"[\d\W]*", t.strip()):
            break
    if not block:
        return []
    out = []
    if any("," in ln.text for ln in block):
        g0, g1 = block[0].g0, block[-1].g1
        pos = g0
        cuts = [m for m in SEP.finditer(doc.text, g0, g1)] + [None]
        for m in cuts:
            e = m.start() if m else g1
            a, b = doc.trim(pos, e)
            seg = doc.text[a:b]
            if seg and re.match(rf"(?:{PART}\s+)?(?:{TOK}|{INIT})", seg) and len(seg) < 60 and not NOT_NAME.match(seg) \
                    and ("\n\n" not in seg or len(seg) < 40):
                out.append((re.sub(r"\s+", " ", seg), a, b))
            pos = m.end() if m else g1
    else:
        for ln in block:
            for m in NAME_RX.finditer(ln.text):
                if not NOT_NAME.match(m.group(0)):
                    out.append((m.group(0), ln.g0 + m.start(), ln.g0 + m.end()))
    return out


def find(q: Doc | None, a: Doc | None, q_end: int | None = None) -> tuple[list[Person], str]:
    """Submitter + co-signatories. q_end: end of the last question item (the signature block follows it)."""
    people: list[Person] = []
    rule = "none"
    if q is not None:
        head = q.text[:2500]
        names: list[tuple[str, int, int]] = []
        be = list(BE_LINE.finditer(q.text[:4000]))
        if be and any(m.group("lead") for m in be):
            lead = [m for m in be if m.group("lead")]
            order = lead + [m for m in be if not m.group("lead")]
            names = [(m.group("name"), m.start("name"), m.end("name")) for m in order]
            rule = "member_list_with_speaker"
        m = TITLE.search(head) if not names else None
        if m:
            names = _split_names(q, m.start("names"), m.group("names"))
            rule = "title_line"
        if not names:
            m = VON.search(head)
            if m:
                names = _split_names(q, m.start("names"), m.group("names"))
                rule = "von_line"
        if not names:
            for rx in CUES:
                m = rx.search(q.text)
                if m:
                    names = [(m.group("names"), m.start("names"), m.end("names"))]
                    rule = "author_cue"
                    break
        sig = _signature_block(q, q_end if q_end is not None else int(len(q.text) * 0.5), boilerplate_lines(q))
        if not names and sig:
            names, rule = sig, "signature_block"
        elif names and sig and rule != "member_list_with_speaker":
            # the title names the first author(s); further signatures are co-signatories
            keys = {w.lower() for n in names for w in n[0].split() if len(w) > 2}
            if any(w.lower() in keys for x in sig for w in x[0].split()):
                names = names + [x for x in sig if not any(w.lower() in keys for w in x[0].split() if len(w) > 2)]
        cm = CO_CUE.search(q.text)
        if cm:
            seg = q.text[cm.end():cm.end() + 400]
            for nm, s, e in _split_names(q, cm.end(), seg.split("\n\n")[0][:300]):
                names.append((nm, s, e))
        seen = set()
        for nm, s, e in names:
            k = nm.lower()
            if k in seen:
                continue
            seen.add(k)
            people.append(Person("submitter" if not people else "co_signatory", nm, s, e, "question", rule))
    if not people and a is not None:
        head = a.text[:3000]
        for rx in [TITLE] + ANSWER_TITLE:
            m = rx.search(head)
            if m:
                ns = _split_names(a, m.start("names"), m.group("names"))
                for i, (nm, s, e) in enumerate(ns):
                    people.append(Person("submitter" if i == 0 else "co_signatory", nm, s, e, "answer", "answer_title"))
                if ns:
                    rule = "answer_title"
                    break
    return people, rule


def name_candidates(q: Doc) -> list[tuple[str, int, int]]:
    """Every printed person-name-like string of the question document (closed set for the pointer)."""
    out, seen = [], set()
    for m in NAME_RX.finditer(q.text):
        nm = m.group(0)
        if NOT_NAME.match(nm) or nm.lower() in seen or len(nm) > 60:
            continue
        seen.add(nm.lower())
        out.append((nm, m.start(), m.end()))
    return out
