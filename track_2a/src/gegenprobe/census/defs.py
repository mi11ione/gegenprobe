"""Frozen census definitions (ported verbatim from spikes/recovery/scripts/{scan_exports,funnel}.py, 8 Oct 2026).

Changing any pattern here changes the census numbers; tests/test_census_defs.py pins their behaviour on hand-made fixtures.
"""

from __future__ import annotations

import re

# Affair types in scope for the answer census (OPD harmonised English type names).
SCOPE_TYPES = ("Interpellation", "Motion", "Postulate", "Question", "Question time")

# ---- document text status (scan time; applied to the `text` field of the docs export) ----------------------------------
PLACEHOLDERS = [
    ("fedlex_js", re.compile(r"JavaScript", re.I)),
    (
        "not_available",
        re.compile(
            r"n'existe qu'en|nur auf (Deutsch|Französisch)|esiste solo in|not available|nicht verfügbar|"
            r"non disponible",
            re.I,
        ),
    ),
]
# answer markers searched in the first 25,000 normalised characters of a document's text
TEXT_FLAGS = {
    "ans_head": re.compile(
        r"Antwort des (Regierungsrat|Bundesrat|Stadtrat|Gemeinderat|Kleinen Rat|Staatsrat)|Antwort Regierungsrat|"
        r"Der Regierungsrat beantwortet|Stellungnahme des (Regierungsrat|Bundesrat|Stadtrat|Gemeinderat)|"
        r"R[ée]ponse du (Conseil|Gouvernement|Conseil-ex[ée]cutif|Conseil d.[ÉE]tat)|Le Conseil d.[ÉE]tat r[ée]pond|"
        r"Risposta del (Consiglio|Municipio)|Il Consiglio di Stato risponde|Beantwortung der (Interpellation|Anfrage|Frage)",
        re.I,
    ),
    "rrb": re.compile(
        r"RRB[- ]?Nr\.?:?\s*\d|Regierungsratsbeschluss|Auszug aus dem Protokoll des Regierungsrates|"
        r"Protokoll des Regierungsrates|Extrait du proc[eè]s-verbal du Conseil|ACE\s*n|Arr[eê]t[ée] du Conseil-ex[ée]cutif",
        re.I,
    ),
    "be_rrb_filled": re.compile(r"RRB-Nr\.?:\s*\d{4}[-/]\d+\s+vom\s+\d", re.I),
}


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def text_status(t: str | None) -> str:
    """null | blank | failed | ph_fedlex_js | ph_not_available | ok"""
    if t is None:
        return "null"
    s = t.strip()
    if not s:
        return "blank"
    if s.startswith("[extraction_failed"):
        return "failed"
    if len(s) < 4000:
        for k, rx in PLACEHOLDERS:
            if rx.search(s):
                return "ph_" + k
    return "ok"


# ---- answer events / documents / texts (funnel time) ---------------------------------------------------------------------
ANS_EV = re.compile(
    r"antwort|beantw|stellungnahme (des |der )?(regierungsrat|bundesrat|stadtrat|gemeinderat)|stellungnahme zum vorstoss|"
    r"der (bundesrat|regierungsrat|stadtrat|gemeinderat) (beantragt|ist bereit)|r[ée]ponse|r[ée]pond|rispost|risponde|"
    r"rapport du conseil d.[ée]tat|stadtrat, (antwort|weisung|entgegennahme|ablehnung)|antrag (regierungsrat|gemeinderat)",
    re.I,
)
NOT_EV = re.compile(r"keine antwort|zur stellungnahme|zur beantwortung|überweisung|überwiesen", re.I)
ORAL = re.compile(
    r"mündlich|oral|fragestunde|heure des questions|question time|antwortet auf diese|r[ée]pond à cette|"
    r"R[ée]ponse de M(me)?\. ",
    re.I,
)
ANS_EV_HARMONIZED_IDS = (6, 76)  # 'Beantwortet' / 'Beantwortung'
ANS_DOC = re.compile(
    r"antwort|RRB|r[ée]ponse|rispost|stellungnahme|beantwortung|regierungsratsbeschluss|beschluss des regierungsrates|"
    r"bericht und antrag|rapport du conseil|rapporto del consiglio|weisung|^SRB|stadtratsbeschluss|gemeinderatsbeschluss|"
    r"protokollauszug|auszug aus dem protokoll|extrait du proc|schreiben des (RR|regierungsrat)|ratschlag|"
    r"regierungsrat beantragt|_ANT\b",
    re.I,
)
ANS_TXT_TYPE = re.compile(r"antwort|r[ée]ponse|rispost|stellungnahme|avis du conseil", re.I)
MIN_DOC_CHARS = 200
MIN_TEXT_CHARS = 50

# VS oral-answer stub ("cf. réponse orale du Conseil d'Etat / s. mündliche Antwort des Staatsrats"): an `_ANT` document whose
# OPD text is 87 characters (OCR-verified 3/3 in spikes/recovery/ocr_probe.json); 80-95 admits the observed 82-char variant.
# Shorter `_ANT` texts (5-48 chars) are page furniture of failed extractions, not stubs, and stay `image_only`.
VS_ORAL_STUB_LEN = (80, 95)

# BE canton document uid inside OPD doc URLs (…/<32 hex>-332/… or …-332.pdf)
BE_UID = re.compile(r"/([0-9a-f]{32})-\d+(?:/|\.pdf)")
BE_ANSWER_NAME = re.compile(r"RRB|antwort|r[ée]ponse|ACE", re.I)
BE_OGD_ANSWER_TYPES = ("RRB", "Vorstossantwort", "RRB gescannt")


def event_title(e: dict) -> str:
    return " ".join(filter(None, [e.get("title_de"), e.get("title_fr"), e.get("title_it")]))


def classify_event(title: str, harmonized_id) -> str | None:
    """'written' | 'oral' | None (not an answer event)."""
    if (harmonized_id in ANS_EV_HARMONIZED_IDS or ANS_EV.search(title)) and not NOT_EV.search(title):
        return "oral" if ORAL.search(title) else "written"
    return None


def is_answer_doc(name: str | None, cat: str | None, flags) -> bool:
    label = f"{name or ''} | {cat or ''}"
    return bool(ANS_DOC.search(label)) or "ans_head" in flags or "be_rrb_filled" in flags


def year_of(number: str | None, begin_date: str | None) -> tuple[int | None, str]:
    m = re.match(r"((?:19|20)\d\d)\b", number or "")
    if m:
        return int(m.group(1)), "number"
    return (int(begin_date[:4]), "begin") if begin_date else (None, "none")
