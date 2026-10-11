"""Schema v0.2's roles read from the documents by fixed rules: authors with their printed role, the language of the text,
the instrument the member's text names (and its function), and the printed submission dates. No model, no network.

    roles.extract(question_pages, answer_pages, body=..., opd_names=...) -> dict (actors, instrument, dates, languages)

Every value points into the text it was read from (document role, page, char_start, char_end) and is pinned by the
sha256 of the printed text at that span; the caller turns the document role into the record's doc_id. Rule ids name the
printed cue (`authors:label:eingereicht_von`, `instrument:heading`, `date:label:depose_le`, ...).

Author roles follow the P8 annotation guide (eval/p8/GUIDE_P8.md §2) as the documents print them:
  * a labelled author block ("Eingereicht von", "Déposé(e) par", "Urheber/-in", "Initiant-e(-s)", "Auteur(s)") or a
    "von / de / di" line under the instrument's heading, or a name line right under a numbered heading: one name ->
    sole_author, several -> joint_author (no name is set apart);
  * a form that sets one name apart ("primo firmatario X", "Erstunterzeichner/in X", "X et consorts", "X und
    Mitunterzeichnende", "X e cofirmatari", or the name a Graubünden heading carries before its signature list) ->
    first_signatory, and the further printed signatures -> co_signatory;
  * a labelled co-signatory list ("Mitunterzeichnende", "Cosignataires", "Cofirmatari", "Weitere Unterschriften") ->
    co_signatory (a printed count such as "Cosignataires : 12" names nobody and adds no actor);
  * "unterstützt von / appuyé par / sostenuto da" -> supporter;
  * a parliamentary group ("SP-Fraktion", "groupe PLR", "gruppo Lega-UDC", "frazione UDC") as author -> kind
    parliamentary_group with role sole_author, and a person printed for it ("im Namen der", "au nom du groupe", "per il
    gruppo", "(Sprecher/in)" of a group) -> spokesperson.
  * When the member's text prints no author, the answer's heading is read ("Réponse ... à l'interpellation de M. X et
    consorts", "Antwort auf die Interpellation von X").
Language of the text: a stop-word profile per paragraph (LANG_METHOD); a language is listed when it holds at least
LANG_MIN_SHARE of the classified characters. It is the language of the text, never the source's tag.
Instrument: the instrument word printed as a heading (or in the heading line) of the member's text, mapped to
InstrumentNamed and, by a per-body table (FUNCTION_BY_BODY, default FUNCTION_DEFAULT), to its function; a printed name
that no table maps gives function `other`.
Dates: a labelled submission date ("Eingereicht am", "Déposée le", "Date de dépôt", "Réception au SGC", "presentata il",
"Eingang") -> lodged / received; a place-and-date line of the member's text ("Chur, 17. Juni 2026") -> signed; "déposée
lors de la séance du / eingereicht an der Sitzung vom" -> announced; "Transmission au CE / überwiesen am" -> later_step.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata

from ..repair.common import parse_dates

RULES_VERSION = "roles-1"
LANG_METHOD = "stopword-profile-v1 (de/fr/it/rm/en; paragraphs >= 120 chars; share >= 0.15)"
LANG_MIN_SHARE = 0.15

# ------------------------------------------------------------------------------------------------------------ names
_UP = "A-ZÀ-ÖØ-ÞČŠŽ"
_TOK = rf"[{_UP}][\w'’.\-]*"
_PART = r"(?:von|van|de|di|da|del|della|dal|im|zur|zum|le|la|du|des|dos|d['’]|De|Di|Da|Van|Von|Del|Della|Dal|Le|La)"
TITLES = re.compile(r"^(?:(?:M\.|MM\.|Mme|Mmes|Mlle|Mr\.|Herr|Frau|Dr\.|Prof\.|lic\.|iur\.|phil\.|med\.|KR|GR|LR|"
                    r"Landrat|Landrätin|Kantonsrat|Kantonsrätin|Grossrat|Grossrätin|Gemeinderat|Gemeinderätin|"
                    r"Stadtrat|Stadträtin|Einwohnerrat|Einwohnerrätin|député|députée|conseiller|conseillère|"
                    r"consigliere|consigliera|on\.|avv\.|ing\.|dott\.|signor|signora|Monsieur|Madame)\s+)+", re.I)
NOT_NAME = {
    "nein", "ja", "non", "oui", "no", "sì", "si", "keine", "aucun", "aucune", "nessuno", "der", "die", "das", "und",
    "regierungsrat", "regierung", "stadtrat", "gemeinderat", "kantonsrat", "grosser", "rat", "landrat", "conseil",
    "municipalité", "municipalite", "municipio", "governo", "consiglio", "grand", "staatsrat", "parlament", "commission",
    "kommission", "commissione", "betreffend", "concernant", "concernente", "concernent", "titel", "titre", "titolo",
    "vom", "du", "del", "datum", "date", "data", "seite", "page", "pagina", "interpellation", "motion", "postulat",
    "anfrage", "question", "mozione", "interrogazione", "interpellanza", "postulato", "dringlich", "urgent", "verteiler",
    "begründung", "développement", "dépôt", "sprecher/in", "fraktionsvorstoss", "kommissionsvorstoss", "richtlinienmotion",
    "weitere", "unterschriften", "cosignataires", "freundliche", "grüsse", "gruss", "merci", "vielen", "dank", "mit",
    "les", "le", "la", "il", "lo", "et", "e", "ou", "oder", "sowie", "anhang", "annexe", "allegato", "ordnungsantrag",
    "schweiz", "suisse", "svizzera", "kanton", "canton", "cantone", "stadt", "ville", "città", "gemeinde", "commune",
    "comune", "chancellerie", "staatskanzlei", "präsidium", "président", "presidente", "frau", "herr", "madame",
    "monsieur", "mesdames", "messieurs", "sehr", "geehrte", "geehrter", "damen", "herren", "signore", "signori",
    "grossrat", "grossrätin", "kantonsrätin", "landrätin", "gemeinderätin", "stadträtin", "einwohnerrat",
    "einwohnerrätin", "député", "députée", "députés", "conseiller", "conseillère", "conseillers", "consigliere",
    "consigliera", "deputato", "deputata", "gez.", "sig.", "signé", "firmato", "unterschrift", "signature",
    "anzug", "auftrag", "incarico", "incumbensa", "interpellaziun", "dumonda", "initiative", "iniziativa", "mandat",
    "résolution", "resolution", "risoluzione", "namens", "sprecher", "sprecherin", "ansprechperson",
}
GROUP_RX = re.compile(r"(?i)fraktion|\b(?:groupe|groupes|gruppo|gruppi|frazione|fracziun|gruppa|partei|parti|partito)\b")
COMMITTEE_RX = re.compile(r"(?i)\b(?:kommission|commission|commissione|cumissiun|ausschuss)\b")


def norm_name(s: str) -> tuple[str, ...]:
    """Tokens of a name for matching: parentheticals and titles dropped, accents folded, lower case, sorted."""
    s = re.sub(r"\([^)]*\)", " ", s)
    s = TITLES.sub("", s.strip())
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    toks = [t for t in re.split(r"[\s,]+", s) if t and t not in {"und", "et", "e", "&"}]
    return tuple(sorted(toks))


def same_person(a: str, b: str) -> bool:
    """Two printed names of one person: equal token sets, or one is a subset of the other (a surname-only print)."""
    x, y = set(norm_name(a)), set(norm_name(b))
    if not x or not y:
        return False
    if x == y:
        return True
    small, big = (x, y) if len(x) <= len(y) else (y, x)
    # hyphenated double names: "Menghini-Inauen" vs "Menghini"
    big_parts = big | {p for t in big for p in t.split("-")}
    return small <= big_parts


def _looks_like_name(piece: str) -> bool:
    p = TITLES.sub("", piece.strip())
    p = re.sub(r"\s*\([^)]*\)\s*", " ", p).strip(" .:")
    if not p or len(p) > 60 or re.search(r"\d", p):
        return False
    if GROUP_RX.search(p) or COMMITTEE_RX.search(p):
        return 1 <= len(p.split()) <= 8
    toks = p.split()
    if not 1 <= len(toks) <= 5:
        return False
    core = [t for t in toks if not re.fullmatch(_PART, t)]
    if not core or not any((len(t) >= 2 and not t.isupper()) or len(t) >= 4 for t in core):
        return False
    for t in toks:
        if re.fullmatch(_PART, t):
            continue
        if not re.fullmatch(_TOK, t) or t.lower().strip(".") in NOT_NAME:
            return False
        if t.isupper() and len(t) > 1 and not re.fullmatch(r"[A-ZÀ-Þ][A-ZÀ-Þ'\-]+", t):
            return False
    return True


def _kind(name: str) -> str:
    if GROUP_RX.search(name):
        return "parliamentary_group"
    if COMMITTEE_RX.search(name):
        return "committee"
    return "person"


_PARTY_TAIL = re.compile(r"\s+(?:SP|SVP|FDP|CVP|GLP|EVP|BDP|AL|CSP|EDU|PLR|PS|UDC|PDC|PVL|PES|Verts|Grüne|GRÜNE|Mitte|GPS|"
                         r"MCG|PLD|PPD|Lega|PCS|JUSO|EàG|PST|POP|Ensemble)\b.*$", re.S)


def _clean_span(page: str, s: int, e: int) -> tuple[int, int]:
    """Trim a name span: whitespace, punctuation, a leading title and a trailing parenthetical (party, place, role)."""
    while s < e and page[s] in " \t\n,;:.–-•*":
        s += 1
    while e > s and page[e - 1] in " \t\n,;:.–-•*":
        e -= 1
    m = TITLES.match(page[s:e])
    if m:
        s += m.end()
    while True:  # an instrument word or a function before the name: "Anzug Roland Engeler-Ohnemus"
        m = re.match(r"(\S+)\s+(?=\S)", page[s:e])
        if m and m.group(1).lower().strip(".:,") in NOT_NAME and not re.fullmatch(_PART, m.group(1)):
            s += m.end()
            continue
        break
    m = None if GROUP_RX.search(page[s:e]) else _PARTY_TAIL.search(page[s:e])
    if m and m.start() > 0 and _looks_like_name(page[s:s + m.start()]):
        e = s + m.start()
    m = re.search(r"(\s*\([^)]*\))+\s*$", page[s:e])
    if m and m.start() > 0:
        e = s + m.start()
    while e > s and page[e - 1] in " \t\n,;:.":
        e -= 1
    return s, e


_SPLIT_NL = re.compile(r"\s*(?:,|;|\n|\s+und\s+|\s+et\s+|\s+e\s+|\s+ed\s+|\s+and\s+|\s+sowie\s+|\s*&\s*|\s+/\s+)\s*")
_SPLIT_COMMA = re.compile(r"\s*(?:,|;|\s+und\s+|\s+et\s+|\s+e\s+|\s+ed\s+|\s+and\s+|\s+sowie\s+|\s*&\s*)\s*")
_CONJ = re.compile(r"^\s*(?:und|et|e|ed|and|sowie|&)\s+")


def split_names(page: str, s: int, e: int, stop_on_non_name: bool = True, skip: frozenset = frozenset()) -> list[tuple[int, int]]:
    """Name spans in page[s:e]. A list with commas outside parentheses is split on commas and und / et / e (a line
    break inside it is a space: "Esther\nSchaufelberger"); otherwise on line breaks too. Parentheticals stay with their
    name and are trimmed from the span."""
    lead = len(page[s:e]) - len(page[s:e].lstrip())
    para = re.search(r"\n[ \t]*\n", page[s + lead:e])
    if para:  # a block of names ends at the first blank line after it starts
        e = s + lead + para.start()
    seg = page[s:e]
    # protect separators inside parentheses: "(Seewil, SVP)"
    prot = re.sub(r"\([^)\n]*\)", lambda m: m.group(0).replace(",", "\x00").replace("\n", "\x01"), seg)
    rx = _SPLIT_COMMA if re.search(r"[,;]", prot) else _SPLIT_NL
    out, pos = [], 0
    for m in list(rx.finditer(prot)) + [None]:
        a, b = pos, (m.start() if m else len(prot))
        pos = m.end() if m else len(prot)
        piece = seg[a:b]
        cm = _CONJ.match(piece)
        if cm:
            a, piece = a + cm.end(), piece[cm.end():]
        if not piece.strip():
            continue
        if piece.strip().lower().strip(":") in skip:
            continue
        if _looks_like_name(piece):
            cs, ce = _clean_span(page, s + a, s + b)
            if ce > cs:
                out.append((cs, ce))
        elif stop_on_non_name:
            break
    return out


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _val(doc: str, pno: int, page: str, s: int, e: int, rule: str, value: str | None = None) -> dict:
    q = page[s:e]
    return dict(value=value if value is not None else re.sub(r"\s+", " ", q), doc=doc, page=pno, char_start=s,
                char_end=e, quote_sha256=_sha(q), rule=rule, exact=value is None and "\n" not in q and "  " not in q)


# ------------------------------------------------------------------------------------------------------------ authors
AUTHOR_LABELS = [
    ("eingereicht_von", r"Eingereicht\s+von\s*:?"),
    ("urheber", r"Urheber(?:in|innen|/-in|\(in\))?\s*:"),
    ("depose_par", r"D[ée]pos[ée]e?s?\s+par\s*:?"),
    ("auteur", r"Auteur(?:e|\(e\))?(?:s|\(s\))?\s*:"),
    ("initiant", r"[Il]nitiant(?:[-·.]?e)?(?:\(?-?s\)?)?\s*:"),
    ("presentata_da", r"(?:Presentat[ao]|Inoltrat[ao])\s+da\s*:?"),
    ("unterzeichnet_von", r"Unterzeichnet\s+von\s*:?"),
    ("signataire", r"Signataires?\s*:"),
    ("autor", r"Autor(?:/in|in|\(in\))?\s*:"),
]
FIRST_LABELS = [
    ("erstunterzeichner", r"Erstunterzeichne(?:r|rin|r/in|nde)\s*:?"),
    ("premier_signataire", r"Premi(?:er|ère)\s+signataire\s*:?"),
    ("primo_firmatario", r"Prim[oa]\s+firmatari[oa]\s*:?"),
]
CO_LABELS = [
    ("mitunterzeichnende", r"Mitunterzeichne(?:nde|r|rinnen|r/innen|r\*innen)\s*:"),
    ("cosignataires", r"Cosignataires?\s*:"),
    ("cofirmatari", r"Cofirmatari\s*:"),
    ("weitere_unterschriften", r"Weitere\s+Unterschriften\s*:"),
    ("mitunterzeichnet_von", r"Mitunterzeichnet\s+von\s*:"),
]
SUPPORT_LABELS = [
    ("unterstuetzt_von", r"[Uu]nterst[üu]tzt\s+von\s*:?"),
    ("appuye_par", r"(?:appuy|soutenu)[ée]?e?s?\s+par\s*:?"),
    ("sostenuto_da", r"sostenut[oa]\s+da\s*:?"),
]
ALL_LABELS = re.compile("|".join(rx for _, rx in AUTHOR_LABELS + FIRST_LABELS + CO_LABELS + SUPPORT_LABELS)
                        + r"|Dringlichkeit|Urgence|Urgenza|RRB-Nr|N° d.ACE|Direktion\s*:|Direction\s*:|Klassifizierung|"
                        r"Classification|Betreff|Objet|Oggetto|Titel\s*:|Titre\s*:|Datum\s*:|Date\s*:|Eingereicht am|"
                        r"D[ée]pos[ée]e? le|Vorstossart|Type d.intervention|Fraktionsvorstoss|Motion de groupe")
TABLE_SKIP = frozenset({"nein", "ja", "non", "oui", "no", "sì", "si", "☐", "☒", "x"})
_PERSON_PAREN = re.compile(rf"^[ \t]*((?:{_TOK}|{_PART})(?:[ \t]+(?:{_TOK}|{_PART})){{0,4}})[ \t]*\(([^)\n]{{2,60}})\)"
                           r"(?:[ \t]*\((Sprecher/in|Sprecherin|Sprecher|porte-parole)\))?[ \t]*$", re.M)

INSTRUMENT_WORDS = (r"(?:Dringliche\s+|Kleine\s+|Schriftliche\s+|Einfache\s+)?(?:Anfrage|Interpellation|Motion|Postulat|"
                    r"Frage|Auftrag|Anzug)|Projet\s+de\s+motion|Question(?:\s+[ée]crite)?|Interpellation|Motion|Postulat|"
                    r"Mandat|R[ée]solution|Initiative(?:\s+parlementaire)?|Interrogazione|Interpellanza|Mozione|"
                    r"Postulato|Incarico|Iniziativa(?:\s+parlamentare)?|Incumbensa|Dumonda|Interpellaziun|Postulat")
_ONE_NAME = rf"(?:{_TOK}|{_PART})(?:[ \t]+(?:{_TOK}|{_PART})){{0,4}}"
_GROUP_PHRASE = (r"(?:(?:la\s+|le\s+|il\s+|der\s+|die\s+)?(?:frazione|gruppo|groupe|fracziun|gruppa|Fraktion)[ \t]+"
                 r"[\w\-/.]+(?:[ \t]*/[ \t]*[\w\-.]+)?|[\w\-]+-Fraktion)")
_PAREN = r"(?:[ \t]*\([^)\n]{1,40}\))?"
_HONOR = r"(?:(?:M\.|Mme|MM\.|Mmes|Herrn?|Frau|on\.|dott\.|avv\.)[ \t]+)?"
# GR / FR / TI headings: "Anfrage Said Bucher betreffend ...", "Incarico di frazione UDC concernente ... (primo firmatario
# Sgier)", "Interpellation de M. Jean Exemple et consorts", "Anfrage Rudolf Vonlanthen" (alone on its line)
HEAD_INLINE = re.compile(
    rf"(?m)^[ \t]*(?:{INSTRUMENT_WORDS})[ \t]+(?:(?:von|de|di|da|del|dal|dalla|della|du|des|der)[ \t]+)?{_HONOR}"
    rf"(?P<names>{_GROUP_PHRASE}|(?:{_ONE_NAME}{_PAREN})(?:[ \t]*(?:,|und|et|e|&)[ \t]*{_HONOR}{_ONE_NAME}{_PAREN}){{0,6}})"
    r"(?P<tail>[ \t]+(?:et\s+consorts|und\s+Mitunterzeichnende|e\s+cofirmatari|und\s+Konsorten))?"
    r"(?:[ \t\n]+(?:betreffend|concernente|concernent|concernant|sur|sulla|sul|sui|sullo|zum|zur|zu|über|pour|per|«|\"|“|„|"
    r":|–|-)|[ \t]*\n)")
FIRST_PAREN = re.compile(rf"\((?:primo|prima)\s+firmatari[oa]\s+(?P<n>{_ONE_NAME})\)|"
                         rf"\((?:Erstunterzeichne(?:r|rin|r/in|nde))\s*:?\s*(?P<n2>{_ONE_NAME})\)|"
                         rf"\((?:premier|première)\s+signataire\s*:?\s*(?P<n3>{_ONE_NAME})\)")
CONSORTS = re.compile(rf"(?P<n>{_ONE_NAME})[ \t]*(?:\([^)\n]*\))?[ \t]+(?:&|et|und|e)[ \t]+(?:consorts|Mitunterzeichnende|"
                      r"cofirmatari|Konsorten)\b|(?P<m>" + _ONE_NAME + r")[ \t]+et[ \t]+\d+[ \t]+cosignataires")
NAMENS_HEAD = re.compile(r"(?m)^[ \t]*(?P<names>[^\n]{3,160}?)[ \t]+(?:namens|im\s+Namen|au\s+nom|a\s+nome)[ \t]+"
                         r"(?:der|du|des|del|della|dei|de\s+la)?[ \t]*(?P<g>[\w\-/]*Fraktion|groupe\s+[\w\-/]+|"
                         r"gruppo\s+[\w\-/]+)")
VON_LINE = re.compile(r"(?m)^[ \t]*(?:von|Von|VON|de|De|di|Di|da|Da)[ \t]+(?=(?:(?:M\.|Mme|Dr\.|Herrn?|Frau)\s+)?[A-ZÀ-Þ])")
SPOKES = re.compile(r"(?i)(?:im\s+Namen\s+der|namens\s+der|au\s+nom\s+du|au\s+nom\s+des|pour\s+le|per\s+il|a\s+nome\s+del|"
                    r"f[üu]r\s+die)[ \t]+(?P<g>(?:[\w\-]+[ \t-]*)?(?:Fraktion|groupe|gruppo|Kommission|commission|"
                    r"commissione)(?:[ \t]+[\w\-./]+){0,3})")
# the answer's heading names the intervention's author: "Réponse ... à l'interpellation de M. X et consorts", "Antwort
# auf die Interpellation von X", "risposta all'interrogazione di X"
ANSWER_HEAD = re.compile(
    rf"(?:à\s+l['’]|au\s+|à\s+la\s+|auf\s+die\s+|zur\s+|zum\s+|all['’]|alla\s+|al\s+|der\s+|des\s+)"
    rf"(?:interpellation|postulat|motion|question(?:\s+[ée]crite)?|Interpellation|Motion|Postulat|(?:Kleine\s+)?Anfrage|"
    rf"interpellanza|mozione|interrogazione)\s+(?:de|von|di|du|des)\s+{_HONOR}(?P<n>{_ONE_NAME})"
    r"(?P<tail>[ \t\n]+(?:et\s+consorts|und\s+Mitunterzeichnende|e\s+cofirmatari|und\s+Konsorten|et\s+\d+\s+cosignataires))?")
_MONTHS_EXTRA = {"schaner": 1, "favrer": 2, "mars": 3, "avrigl": 4, "matg": 5, "zercladur": 6, "fanadur": 7, "avust": 8,
                 "settember": 9, "october": 10, "november": 11, "december": 12}
_COMPACT = re.compile(r"\b(\d{1,2})\.?\s*(?:da\s+)?([a-zéûèäöüàç]{3,10})\s*(\d{4})\b", re.I)
_SHORT = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b")


def find_dates(text: str) -> list[tuple[str, int, int]]:
    """parse_dates (the project's parser) plus forms it does not read: '12janvier2024', Romansh '13 da zercladur 2025',
    two-digit years '24.01.22'; sorted by position, overlapping finds dropped."""
    from ..repair.common import MONTHS

    out = list(parse_dates(text))
    for m in _COMPACT.finditer(text):
        mo = MONTHS.get(m.group(2).lower()) or _MONTHS_EXTRA.get(m.group(2).lower())
        if mo:
            try:
                out.append((dt.date(int(m.group(3)), mo, int(m.group(1))).isoformat(), m.start(), m.end()))
            except ValueError:
                pass
    for m in _SHORT.finditer(text):
        d, mo, y = (int(x) for x in m.groups())
        try:
            out.append((dt.date(2000 + y if y < 70 else 1900 + y, mo, d).isoformat(), m.start(), m.end()))
        except ValueError:
            pass
    out.sort(key=lambda x: (x[1], -(x[2] - x[1])))
    kept: list[tuple[str, int, int]] = []
    for x in out:
        if kept and x[1] < kept[-1][2]:
            continue
        kept.append(x)
    return kept


def _date_line(line: str) -> tuple[str, int, int] | None:
    """A place-and-date line ('Chur, 17. Juni 2026', 'Vernier, le 23 janvier 2022', 'Cuira, ils 13 da zercladur 2025')
    or a bare date line ('28 août 2023'): (iso, start, end) of the date in the line."""
    ds = find_dates(line)
    if not ds:
        return None
    iso, s, e = ds[-1]
    if line[e:].strip(" .\t"):
        return None
    head = line[:s].strip()
    if not head:
        return iso, s, e
    head = re.sub(r"(?:,|\s)+(?:le|den|il|ils|am|li|, le)?\s*$", "", head).strip(" ,")
    if re.fullmatch(r"[A-ZÀ-Þ][\w'’.\-]*(?:[ \t/\-]+(?:[A-ZÀ-Þ(][\w'’.\-()]*|und|et|e|di|de|sur|am|im|bei))*", head) \
            and len(head) <= 45:
        return iso, s, e
    return None


_FUNCTION_LINE = re.compile(r"(?i)^\s*(?:conseill|municipa|kantonsr|grossr|landr|gemeinder|stadtr|einwohnerr|d[ée]put|"
                            r"deputat|consiglier|membre|mitglied|pr[äa]sident|secr[ée]taire|sekret|relat|l['’]auteur|"
                            r"die\s+unterzeichnenden|les\s+signataires|i\s+firmatari)")
_SCRIBBLE = re.compile(r"^[^A-Za-zÀ-ÿ]*$|[/?*<>~;=|_\\]{1,}.*[/?*<>~;=|_\\]|^.{0,3}$")


def _closing_block(pages: list[str], doc: str) -> tuple[list[dict], dict | None, dict | None]:
    """Signatures at the end of the member's text: the names under the last place-and-date (or bare date) line (GR:
    'Chur, 17. Juni 2026' then a comma list; Lausanne: names on lines of their own), else the names right above it
    (Vernier: names, a function line, 'Vernier, le ...'), else a last paragraph of names. Returns (names, the date line
    as a `signed` date, a group printed as 'Pour le groupe X' / 'Für die X-Fraktion' above the names)."""
    for pno in range(len(pages), max(0, len(pages) - 2), -1):
        page = pages[pno - 1]
        if len(page.strip()) < 20:
            continue
        lines = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"[^\n]*", page)]
        lines = [x for i, x in enumerate(lines) if not (i and lines[i - 1][1] == x[0] and x[0] == x[1])]
        tail_from = max(0, len(page) - 2500, 600 if pno == 1 else 0)
        idx = None
        for i, (s, _e, t) in enumerate(lines):
            if s >= tail_from and t.strip() and _date_line(t):
                idx = i
        date = None
        names: list[dict] = []
        group = None
        if idx is not None:
            s0, _, t0 = lines[idx]
            iso, ds, de = _date_line(t0)
            date = dict(_val(doc, pno, page, s0 + ds, s0 + de, "date:place_date_line", value=iso), role="signed")
            # after: names (skip blank and scribble lines; stop at a line of prose)
            for s, e, t in lines[idx + 1:]:
                if not t.strip() or _SCRIBBLE.search(t.strip()) or _FUNCTION_LINE.match(t):
                    continue
                sp = split_names(page, s, e, stop_on_non_name=False)
                if sp and all(_looks_like_name(page[a:b]) for a, b in sp) and \
                        sum(b - a for a, b in sp) >= 0.6 * len(t.strip()):
                    names += [_val(doc, pno, page, a, b, "authors:signatures") for a, b in sp]
                    continue
                break
            if not names:
                # before: up to 2 function / blank lines, then a block of name lines
                j = idx - 1
                skipped = 0
                while j >= 0 and (not lines[j][2].strip() or _FUNCTION_LINE.match(lines[j][2])) and skipped < 4:
                    j -= 1
                    skipped += 1
                block_end = lines[j][1] if j >= 0 else 0
                k = j
                while k >= 0 and lines[k][2].strip() and idx - k <= 8:
                    t = lines[k][2]
                    if SPOKES.match(t.strip()):
                        break
                    if not (_looks_like_name(t) or re.search(r"[,;]|\s(?:und|et|e)\s", t) and
                            split_names(page, lines[k][0], lines[k][1], stop_on_non_name=False)):
                        if not (len(t.split()) <= 2 and _looks_like_name(t.split(",")[0])):
                            break
                    k -= 1
                block_start = lines[k + 1][0] if k + 1 <= j else block_end
                if block_start < block_end:
                    sp = split_names(page, block_start, block_end, stop_on_non_name=True)
                    names = [_val(doc, pno, page, a, b, "authors:signatures") for a, b in sp]
                    gm = SPOKES.match(lines[k][2].strip()) if k >= 0 else None
                    if gm:
                        off = lines[k][0] + len(lines[k][2]) - len(lines[k][2].lstrip())
                        gs, ge = _clean_span(page, off + gm.start("g"), off + gm.end("g"))
                        group = _val(doc, pno, page, gs, ge, "authors:on_behalf_of")
        groups = [group] if group else []
        if not names and idx is None and pno == len(pages):
            names, groups = _trailing_names(page, pno, doc)
        if names or date:
            return names, date, groups
    return [], None, []


_FOOTER = re.compile(r"(?i)^\s*(?:seite|page|pagina)?\s*\d+\s*(?:/|von|de|di|sur)?\s*\d*\s*$")


def _trailing_names(page: str, pno: int, doc: str) -> tuple[list[dict], list[dict]]:
    """No date line: the last lines of the text that are only names (Vernier "A, B, C et D"; Basel "Heidi Mück"), with
    group lines among them ("namens der SP/JUSO-Fraktion", "Per il Gruppo PLR"); the line above must end a sentence."""
    lines = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"[^\n]+", page)]
    while lines and (_FOOTER.match(lines[-1][2]) or len(lines[-1][2].strip()) < 2):
        lines.pop()
    block = []
    while lines and len(block) < 8:
        s, e, t = lines[-1]
        if SPOKES.match(t.strip()):
            block.append(("group", s, e, t))
        elif split_names(page, s, e, stop_on_non_name=False) and all(
                _looks_like_name(x) for x in re.split(r"\s*(?:,|;|\s+und\s+|\s+et\s+|\s+e\s+)\s*", t.strip()) if x):
            block.append(("names", s, e, t))
        else:
            break
        lines.pop()
    if not block or (lines and not re.search(r"[.?!:;»“\"]\s*$", lines[-1][2])):
        return [], []
    block.reverse()
    names, groups, run = [], [], []
    for kind, s, e, t in block + [("end", 0, 0, "")]:
        if kind == "names":
            run.append((s, e))
            continue
        if run:  # consecutive name lines are one list: "Esther\nSchaufelberger et Barbara Lanzilao"
            names += [_val(doc, pno, page, a, b, "authors:signatures")
                      for a, b in split_names(page, run[0][0], run[-1][1], False)]
            run = []
        if kind == "group":
            gm = SPOKES.match(t.strip())
            off = s + len(t) - len(t.lstrip())
            gs, ge = _clean_span(page, off + gm.start("g"), off + gm.end("g"))
            groups.append(_val(doc, pno, page, gs, ge, "authors:on_behalf_of"))
    return names, groups


def _norm_group(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" ,.;:")


def _actor(role: str, kind: str, v: dict, on_behalf_of: str | None = None) -> dict:
    a = dict(role=role, kind=kind, name=v)
    if on_behalf_of:
        a["on_behalf_of"] = on_behalf_of
    return a


def _head_region(page: str, n: int = 2500) -> int:
    return min(len(page), n)


def _label_blocks(pages: list[str], doc: str, labels, max_chars: int = 500):
    """(label id, [name values]) for each labelled block: the names after the label up to the next label."""
    out = []
    for pno, page in enumerate(pages, 1):
        for lid, rx in labels:
            for m in re.finditer(rx, page):
                nxt = ALL_LABELS.search(page, m.end())
                end = min(nxt.start() if nxt else len(page), m.end() + max_chars)
                para = re.search(r"\n[ \t]*\n[ \t]*\S", page[m.end():end])
                if para and page[m.end():m.end() + para.start()].strip():
                    end = m.end() + para.start()
                spans = split_names(page, m.end(), end, stop_on_non_name=True, skip=TABLE_SKIP)
                if spans:
                    out.append((lid, [_val(doc, pno, page, s, e, f"authors:label:{lid}") for s, e in spans]))
    return out


def _table_authors(pages: list[str], doc: str) -> list[dict]:
    """Bern-type form: 'Eingereicht von:' / 'Déposée par :' in a label column; the values ('Name (Place, Party)') follow
    the labels as separate lines up to 'Dringlichkeit' / 'Urgence'."""
    page = pages[0]
    m = re.search(r"Eingereicht\s+von\s*:|D[ée]pos[ée]e?s?\s+par\s*:", page)
    if not m:
        return []
    stop = re.search(r"Dringlichkeit\s+verlangt|Urgence\s+demand[ée]e|RRB-Nr|N° d.ACE", page[m.end():])
    end = m.end() + (stop.start() if stop else 600)
    out = []
    for pm in _PERSON_PAREN.finditer(page, m.end(), end):
        out.append(_val(doc, 1, page, pm.start(1), pm.end(1), "authors:table:eingereicht_von"))
    return out


def _dedupe(vals: list[dict]) -> list[dict]:
    seen, out = [], []
    for v in vals:
        if any(same_person(v["value"], w) for w in seen):
            continue
        seen.append(v["value"])
        out.append(v)
    return out


def _has(actors: list[dict], v: dict) -> bool:
    return any(same_person(v["value"], x["name"]["value"]) for x in actors)


def _answer_head(a: list[str]) -> tuple[dict, bool] | None:
    """The author the answer's heading names, and whether it is set apart ('et consorts')."""
    if not a:
        return None
    page = a[0]
    m = ANSWER_HEAD.search(page[:3000])
    if m:
        s, e = _clean_span(page, m.start("n"), m.end("n"))
        if e > s and _looks_like_name(page[s:e]):
            return _val("answer", 1, page, s, e, "authors:answer_heading"), bool(m.group("tail"))
    m = CONSORTS.search(page[:3000])
    if m:
        g = "n" if m.group("n") else "m"
        s, e = _clean_span(page, m.start(g), m.end(g))
        if e > s and _looks_like_name(page[s:e]):
            return _val("answer", 1, page, s, e, "authors:answer_et_consorts"), True
    return None


def authors(q: list[str], a: list[str] | None = None) -> tuple[list[dict], dict | None]:
    """Actors (role, kind, name value with doc role 'question' / 'answer') as the documents print them, and the
    signed date of the member's text's closing block (or None)."""
    a = a or []
    actors: list[dict] = []
    if not q:
        return actors, None
    # 1. a Bern-type form table
    tab = _dedupe(_table_authors(q, "question"))
    if tab:
        role = "sole_author" if len(tab) == 1 else "joint_author"
        return [_actor(role, "person", v) for v in tab], None
    # 2. labelled blocks
    blocks = _label_blocks(q, "question", AUTHOR_LABELS + FIRST_LABELS)
    co = _label_blocks(q, "question", CO_LABELS)
    sup = _label_blocks(q, "question", SUPPORT_LABELS)
    first_ids = {lid for lid, _ in FIRST_LABELS}
    if blocks:
        lid, vals = blocks[0]
        vals = _dedupe(vals)
        if lid in first_ids:
            actors.append(_actor("first_signatory", _kind(vals[0]["value"]), vals[0]))
            actors += [_actor("co_signatory", _kind(v["value"]), v) for v in vals[1:]]
        else:
            role = "sole_author" if len(vals) == 1 else "joint_author"
            actors += [_actor(role, _kind(v["value"]), v) for v in vals]
    # 3. heading forms on page 1 of the member's text
    if not actors:
        actors = _heading_authors(q)
    # 4. the closing signatures
    sig, signed, sig_groups = _closing_block(q, "question")
    sig = _dedupe(sig)
    if sig:
        persons = [x for x in actors if x["kind"] == "person"]
        groups = [x for x in actors if x["kind"] != "person"]
        firsts = [x for x in persons if x["role"] == "first_signatory"]
        lead = firsts[0] if firsts else (persons[0] if len(persons) == 1 else None)
        if lead and same_person(lead["name"]["value"], sig[0]["value"]) and len(sig) > 1:
            lead["role"] = "first_signatory"  # the heading's name opens the signature list: GR
            actors += [_actor("co_signatory", "person", v) for v in sig[1:] if not _has(actors, v)]
        elif groups and not persons:
            actors.append(_actor("first_signatory" if len(sig) > 1 else "spokesperson", "person", sig[0]))
            actors += [_actor("co_signatory", "person", v) for v in sig[1:] if not _has(actors, v)]
        elif firsts:
            actors += [_actor("co_signatory", "person", v) for v in sig if not _has(actors, v)]
        elif not actors:
            sig_groups = sig_groups + [v for v in sig if _kind(v["value"]) != "person"]
            sig = [v for v in sig if _kind(v["value"]) == "person"]
            if sig_groups:
                gs = _dedupe(sig_groups)
                actors = [_actor("sole_author" if len(gs) == 1 else ("first_signatory" if i == 0 else "co_signatory"),
                                 "parliamentary_group", g) for i, g in enumerate(gs)]
                actors += [_actor("spokesperson", "person", v) for v in sig]
            else:
                role = "sole_author" if len(sig) == 1 else "joint_author"
                actors = [_actor(role, _kind(v["value"]), v) for v in sig]
    # 5. labelled co-signatories and supporters
    for _, vals in co:
        actors += [_actor("co_signatory", _kind(v["value"]), v) for v in vals if not _has(actors, v)]
    for _, vals in sup:
        actors += [_actor("supporter", _kind(v["value"]), v) for v in vals if not _has(actors, v)]
    # 6. the answer's heading: sets the first signatory apart ('et consorts'), or names the author the member's text
    #    does not print
    ah = _answer_head(a)
    if ah:
        v, apart = ah
        persons = [x for x in actors if x["kind"] == "person"]
        if not actors:
            actors = [_actor("first_signatory" if apart else "sole_author", _kind(v["value"]), v)]
        elif apart and persons and same_person(persons[0]["name"]["value"], v["value"]) and \
                all(x["role"] in ("joint_author", "sole_author") for x in persons):
            persons[0]["role"] = "first_signatory"
            for x in persons[1:]:
                x["role"] = "co_signatory"
    for x in actors:
        if x["role"] == "spokesperson" and not x.get("on_behalf_of"):
            g = next((y for y in actors if y["kind"] != "person"), None)
            if g:
                x["on_behalf_of"] = g["name"]["value"]
    return actors, signed


def _heading_authors(pages: list[str], doc: str = "question", max_pages: int = 1) -> list[dict]:
    out: list[dict] = []
    for pno, page in enumerate(pages[:max_pages], 1):
        head = page[:_head_region(page)]
        fp = FIRST_PAREN.search(head)
        m = HEAD_INLINE.search(head)
        if m:
            ns, ne = m.start("names"), m.end("names")
            if re.fullmatch(_GROUP_PHRASE, page[ns:ne]):
                gs, ge = _clean_span(page, ns, ne)
                gs += len(re.match(r"(?:la\s+|le\s+|il\s+|der\s+|die\s+)?", page[gs:ge]).group(0))
                out.append(_actor("sole_author", "parliamentary_group", _val(doc, pno, page, gs, ge, "authors:heading")))
            else:
                spans = split_names(page, ns, ne, stop_on_non_name=True)
                vals = _dedupe([_val(doc, pno, page, s, e, "authors:heading") for s, e in spans])
                if vals and _kind(vals[0]["value"]) == "person":  # "von Franz Meyer, CVP/EVP-Fraktion": affiliation
                    vals = [v for v in vals if _kind(v["value"]) == "person"]
                if vals:
                    if m.group("tail"):
                        out.append(_actor("first_signatory", _kind(vals[0]["value"]), vals[0]))
                    else:
                        role = "sole_author" if len(vals) == 1 else "joint_author"
                        out += [_actor(role, _kind(v["value"]), v) for v in vals]
        if fp:
            g = next(k for k in ("n", "n2", "n3") if fp.group(k))
            s, e = _clean_span(page, fp.start(g), fp.end(g))
            v = _val(doc, pno, page, s, e, "authors:heading:primo_firmatario")
            out = [x for x in out if not same_person(x["name"]["value"], v["value"])]
            out.append(_actor("first_signatory", "person", v))
        if out:
            return out
        cm = CONSORTS.search(head[:800])
        if cm:
            g = "n" if cm.group("n") else "m"
            s, e = _clean_span(page, cm.start(g), cm.end(g))
            if e > s and _looks_like_name(page[s:e]):
                return [_actor("first_signatory", _kind(page[s:e]), _val(doc, pno, page, s, e, "authors:et_consorts"))]
        # "A und B namens der Mitte-Fraktion vom 23. Mai 2023" (Luzern city)
        nm = NAMENS_HEAD.search(head[:1500])
        if nm:
            spans = split_names(page, nm.start("names"), nm.end("names"), stop_on_non_name=False)
            if spans and all(_looks_like_name(page[a:b]) for a, b in spans):
                gs, ge = _clean_span(page, nm.start("g"), nm.end("g"))
                g = _val(doc, pno, page, gs, ge, "authors:on_behalf_of")
                return [_actor("sole_author", "parliamentary_group", g)] + [
                    _actor("spokesperson", "person", _val(doc, pno, page, a, b, "authors:on_behalf_of"),
                           on_behalf_of=g["value"]) for a, b in spans]
        # "von X (Party) und Y (Party)" on its own line(s) near the heading
        heads = [lm.start() for lm in re.finditer(r"(?m)^[ \t]*\S[^\n]*$", head)
                 if (_NAMED_RX_I if lm.group(0).strip().isupper() else _NAMED_RX).match(lm.group(0).strip())]
        for vm in VON_LINE.finditer(head[:1200]):
            if vm.start() > 400 and not any(abs(vm.start() - h) <= 250 for h in heads):
                continue
            end = re.search(r"\n[ \t]*\n|\n[ \t]*(?:betreffend|Betreffend|concernant|concernente|Der|Die|Das|Le|La|Il)\b",
                            page[vm.end():])
            e_ = vm.end() + (end.start() if end else 300)
            spans = split_names(page, vm.end(), min(e_, vm.end() + 400), stop_on_non_name=True)
            if spans:
                vals = _dedupe([_val(doc, pno, page, s, e, "authors:von_line") for s, e in spans])
                role = "sole_author" if len(vals) == 1 else "joint_author"
                return [_actor(role, _kind(v["value"]), v) for v in vals]
        # FR: a name line right under a numbered heading ("Motion 2014-GC-210" / "Question 2022-CE-25")
        hm = re.search(r"(?m)^[ \t]*(?:Motion|Postulat|Question|Mandat|Anfrage|Auftrag|Initiative parlementaire|"
                       r"Parlamentarische Initiative|R[ée]solution|Resolution)[ \t]+\d{4}-(?:GC|CE)-\d+[ \t]*\n(?:[ \t]*\n)*",
                       head)
        if hm:
            line = re.match(r"[^\n]*", page[hm.end():]).group(0)
            spans = split_names(page, hm.end(), hm.end() + len(line), stop_on_non_name=False)
            if spans and all(_looks_like_name(page[s:e]) for s, e in spans):
                vals = _dedupe([_val(doc, pno, page, s, e, "authors:numbered_heading") for s, e in spans])
                role = "sole_author" if len(vals) == 1 else "joint_author"
                return [_actor(role, _kind(v["value"]), v) for v in vals]
        # Zürich city: "Name (Party)" lines of their own in the heading, before the instrument's name
        vals = []
        for pm in _PERSON_PAREN.finditer(page, 0, min(len(page), 800)):
            if len(pm.group(2)) <= 25 and _looks_like_name(pm.group(1)):
                vals.append(_val(doc, pno, page, pm.start(1), pm.end(1), "authors:heading_name_lines"))
        vals = _dedupe(vals)
        if vals:
            role = "sole_author" if len(vals) == 1 else "joint_author"
            return [_actor(role, "person", v) for v in vals]
    return out


# ------------------------------------------------------------------------------------------------------------ language
STOP = {
    "de": "der die das und nicht ist wird werden mit für auf dem den des ein eine einer zu im auch sich von bei wie "
          "nach sind wurde dass oder aus durch über".split(),
    "fr": "le la les et des du un une est pour dans que qui sur pas au aux par ce cette sont être ont il elle nous "
          "leur avec".split(),
    "it": "il lo gli le e di del della che per con non una uno sono nel nella alla dei delle anche questo come "
          "più essere".split(),
    "rm": "ils las da dal dals cun ina in per betg èn è sco quai quest tar sin che vegn vegnir era dad ch tras "
          "suenter er nus".split(),
    "en": "the and of to in is that for on with as are be this by from it an or which".split(),
}
_WORD = re.compile(r"[a-zàâäçéèêëîïôöùûüœßìòóíáú]+", re.I)
_DISTINCT = {lg: set(ws) - set().union(*(set(o) for k, o in STOP.items() if k != lg)) for lg, ws in STOP.items()}


def _para_lang(text: str) -> str | None:
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 12:
        return None
    score = {lg: sum(1 for w in words if w in _DISTINCT[lg]) for lg in STOP}
    best = max(score, key=score.get)
    second = sorted(score.values())[-2]
    if score[best] < 3 or score[best] < 1.5 * second:
        return None
    return best


def language_of_text(pages: list[str]) -> list[str]:
    """Languages the text is written in, by paragraph stop-word profile; [] when no paragraph can be classified."""
    chars: dict[str, int] = {}
    for page in pages:
        for para in re.split(r"\n[ \t]*\n", page):
            if len(para.strip()) < 120:
                continue
            lg = _para_lang(para)
            if lg:
                chars[lg] = chars.get(lg, 0) + len(para)
    tot = sum(chars.values())
    if not tot:
        return []
    order = sorted(chars, key=lambda k: -chars[k])
    return [lg for lg in order if chars[lg] / tot >= LANG_MIN_SHARE]


# ------------------------------------------------------------------------------------------------------------ instrument
NAMED = [
    ("motion", r"Projet\s+de\s+motion|Motion|Mozione|Moziun"),
    ("postulate", r"Postulat|Postulato"),
    ("interpellation", r"Dringliche\s+Interpellation|Interpellation|Interpellanza|Interpellaziun"),
    ("question", r"(?:Dringliche\s+|Kleine\s+|Schriftliche\s+|Einfache\s+)?Anfrage|Question(?:\s+[ée]crite)?|"
                 r"Interrogazione|Dumonda|Fragestunde"),
    ("resolution", r"R[ée]solution|Risoluzione"),
    ("initiative", r"Parlamentarische\s+Initiative|Initiative\s+parlementaire|Iniziativa\s+parlamentare|"
                   r"Einzelinitiative|Standesinitiative"),
    ("other", r"Auftrag|Incarico|Incumbensa|Anzug|Mandat|Antrag|Volksauftrag|Requête|Petition|Pétition"),
]
_NAMED_RX = re.compile("|".join(f"(?P<{k}{i}>{rx})" for i, (k, rx) in enumerate(NAMED)))
_NAMED_RX_I = re.compile(_NAMED_RX.pattern, re.I)  # a heading printed in capitals: "PROJET DE MOTION", "QUESTION ÉCRITE"
FUNCTION_DEFAULT = {"motion": "mandate", "postulate": "examine_report", "interpellation": "questions",
                    "question": "questions", "initiative": "direct_decision", "resolution": "other"}
# instruments outside the shared names, per body (the parliament's own instrument word -> function)
FUNCTION_BY_BODY = {
    "GR": {"Auftrag": "mandate", "Incarico": "mandate", "Incumbensa": "mandate"},
    "SO": {"Auftrag": "mandate"},
    "BS": {"Anzug": "examine_report"},
    "FR": {"Mandat": "mandate"},
    "BE": {"Finanzmotion": "mandate"},
}


def _named_key(m: re.Match) -> str:
    return re.sub(r"\d+$", "", next(k for k, v in m.groupdict().items() if v))


def instrument(q: list[str], body: str) -> dict | None:
    """The instrument word the member's text prints as its heading (a line of its own, or the start of the heading
    line), within the first 2,500 characters of page 1 (page 2 if page 1 is a cover)."""
    for pno, page in enumerate(q[:2], 1):
        head = page[:_head_region(page)]
        best = None
        for lm in re.finditer(r"(?m)^[ \t]*(.+?)[ \t]*$", head):
            line = lm.group(1)
            upper = line.isupper()
            m = (_NAMED_RX_I if upper else _NAMED_RX).match(line)
            if not m:
                continue
            rest = line[m.end():]
            alone = not rest.strip() or re.match(r"[ \t]*(?:(?i:nr\.|no\b|n°)|\d|von|de|di|da|betreffend|concernant|"
                                                  r"concernente|concernent|au sens|[-–:]|[A-ZÀ-Þ\"«„“])", rest)
            if not alone or (m.end() < len(line) and line[m.end()].isalpha()):
                continue
            best = (lm.start(1) + m.start(), lm.start(1) + m.end(), m)
            break
        if best:
            s, e, m = best
            word = page[s:e]
            key = _named_key(m)
            fn_body = FUNCTION_BY_BODY.get(body, {})
            w1 = re.sub(r"\s+", " ", word).split(" ")[-1]
            w1 = next((k for k in fn_body if k.lower() == w1.lower()), w1)
            fn = fn_body.get(w1) or FUNCTION_DEFAULT.get(key) or "other"
            rule_fn = f"instrument_function:{body}:{w1}" if w1 in fn_body else (
                f"instrument_function:default:{key}" if key in FUNCTION_DEFAULT else "instrument_function:unmapped")
            return dict(named=dict(_val("question", pno, page, s, e, "instrument:heading", value=key), word=word),
                        function=dict(_val("question", pno, page, s, e, rule_fn, value=fn)))
    return None


# ------------------------------------------------------------------------------------------------------------ dates
DATE_LABELS = [
    ("lodged", "eingereicht_am", r"Eingereicht\s+am\s*:?"),
    ("lodged", "datum_einreichung", r"(?:Datum\s+der\s+Einreichung|Einreichungsdatum|Einreichedatum)\s*:?"),
    ("lodged", "depose_le", r"D[ée]pos[ée]e?s?\s+le\s*:?"),
    ("lodged", "date_depot", r"Date\s+de\s+d[ée]p[ôo]t\s*:?"),
    ("lodged", "presentata_il", r"(?:[Pp]resentat[ao]|[Ii]noltrat[ao]|[Dd]eposta?)\s+il\s*:?"),
    ("lodged", "data_presentazione", r"Data\s+(?:di\s+)?presentazione\s*:?"),
    ("received", "reception", r"R[ée]ception\s+(?:au\s+SGC|au\s+secr[ée]tariat)?\s*:?|Re[çc]ue?\s+le\s*:?"),
    ("received", "eingang", r"Eingang\s*:|Eingegangen\s+am\s*:?|Posteingang\s*:?"),
    ("announced", "session", r"eingereicht\s+an\s+der\s+Sitzung\s+vom|d[ée]pos[ée]e?\s+lors\s+de\s+la\s+s[ée]ance\s+du|"
                             r"presentat[ao]\s+nella\s+seduta\s+del"),
    ("later_step", "transmission", r"Transmission\s+au\s+CE\s*:?|[Üü]berwiesen\s+am\s*:?|Begründet\s+am\s*:?|"
                                   r"D[ée]velopp[ée]e?\s+le\s*:?"),
]


# in the answer only the forms that name the intervention's own lodging ("à l'interpellation ... déposée le ..."), not
# the answer's own form fields ("Date de dépôt" of the answer document, Geneva)
ANSWER_DATE_LABELS = {"depose_le", "eingereicht_am", "presentata_il"}


def submission_dates(q: list[str], a: list[str] | None = None) -> list[dict]:
    """Labelled submission-procedure dates: the first date after the label (on its line or within the next 120
    characters of the form), on the first two pages of the member's text and the first page of the answer ('Réponse ...
    à l'interpellation ... déposée le 29 août 2023'); and a bare date line in the member's text's heading (the first 600
    characters: 'GR Nr. 2025/ 355 / 27. August 2025') -> lodged, a place-and-date line there -> signed."""
    out, seen = [], set()
    docs = [("question", pno, page) for pno, page in enumerate(q[:2], 1)] + [("answer", 1, a[0])] * bool(a)
    for doc, pno, page in docs:
        for role, lid, rx in DATE_LABELS:
            if doc == "answer" and lid not in ANSWER_DATE_LABELS:
                continue
            for m in re.finditer(rx, page):
                if doc == "answer" and m.start() > 3000:
                    break
                window = page[m.end():m.end() + 120]
                ds = find_dates(window)
                if not ds:
                    continue
                iso, s, e = ds[0][0], m.end() + ds[0][1], m.end() + ds[0][2]
                if (iso, role) in seen:
                    continue
                seen.add((iso, role))
                out.append(dict(_val(doc, pno, page, s, e, f"date:label:{lid}", value=iso), role=role,
                                label=re.sub(r"\s+", " ", m.group(0)).strip(" :")))
    if q:
        page = q[0]
        for lm in re.finditer(r"[^\n]+", page[:600]):
            dl = _date_line(lm.group(0))
            if dl and len(lm.group(0).strip()) <= 60:
                iso, ds, de = dl
                bare = not lm.group(0)[:ds].strip()
                role = "lodged" if bare else "signed"
                if (iso, role) in seen or (iso, "lodged") in seen:
                    break
                seen.add((iso, role))
                out.append(dict(_val("question", 1, page, lm.start() + ds, lm.start() + de,
                                     "date:heading_date_line" if bare else "date:heading_place_date", value=iso), role=role))
                break
    return out


# ------------------------------------------------------------------------------------------------------------ all
def extract(q: list[str], a: list[str] | None, body: str) -> dict:
    """All roles of one affair from its member's text `q` and the answer `a` (pages as extracted)."""
    actors, signed = authors(q, a)
    dates = submission_dates(q, a)
    if signed and not any(d["value"] == signed["value"] and d["role"] == "signed" for d in dates):
        dates.append(signed)
    return dict(rules_version=RULES_VERSION, actors=actors, instrument=instrument(q, body) if q else None, dates=dates,
                language_of_text=dict(question=language_of_text(q) if q else None,
                                      answer=language_of_text(a) if a else None))
