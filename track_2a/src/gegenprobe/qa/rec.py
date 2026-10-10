"""Rules: the executive's recommendation to parliament (accept / reject / partial / convert / none / not_applicable).

Candidates are printed sentences of the answer document that contain a proposal verb ("beantragt", "beantragen wir",
"Antrag", "propose", "invite", "propone", "invita", ...) together with an outcome word; each candidate maps to a value by
lexicon. Rules decide when all candidates agree; otherwise the sentences are the closed set for the Apertus pointer (which
sentence states the executive's recommendation, or none); the value then comes from the chosen sentence's lexicon.
Interpellations and questions: not_applicable by type (the type word printed in the question's head is the evidence).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import Doc

PROPOSE = re.compile(
    r"beantrag\w*|Antrag|empfiehlt|empfehlen|ersuchen\s+Sie|bitten\s+Sie|propos\w*|Proposition|invite\w*|propone\w*|"
    r"proposta|invita\w*|chiede\s+(al|di)|Il\s+Consiglio\s+di\s+Stato\s+(vi\s+)?(invita|propone)|Le\s+Conseil.{0,30}vous\s+(propose|invite)",
    re.I,
)
VAL = [
    ("convert", re.compile(r"in\s+der\s+Form\s+(eines|des)\s+Postulat\w*|als\s+Postulat|in\s+ein(en)?\s+Postulat|"
                           r"Umwandlung\s+in|in\s+Form\s+eines\s+Postulat|"
                           r"sous\s+(la\s+)?forme\s+(de|d.un)\s+postulat|transform\w*\s+en\s+postulat|"
                           r"trasformar\w*\s+in\s+postulato|come\s+postulato", re.I)),
    ("partial", re.compile(r"teilweise\s+(erheblich|zu\s+überweisen|anzunehmen|gutzuheissen)|teilweise\s+Erheblicherkl|"
                           r"partiellement|en\s+partie|parzialmente|in\s+parte\s+(accol|approv)", re.I)),
    ("reject", re.compile(r"abzulehnen|Ablehnung|nicht\s+(erheblich|zu\s+überweisen|zu\s+entsprechen|anzunehmen)|"
                          r"Nichtüberweisung|abzuweisen|zurückzuweisen|rejet\w*|refus\w*|ne\s+pas\s+(prendre|accepter|entrer)|"
                          r"respinge\w*|respint\w*|non\s+accogl\w*|non\s+entrare", re.I)),
    ("accept", re.compile(r"anzunehmen|Annahme|erheblich\s+zu\s+erkl|Erheblicherkl|zu\s+überweisen|Überweisung|"
                          r"entgegenzunehmen|gutzuheissen|zuzustimmen|accept\w*|adopt\w*|prendre\s+en\s+consid|"
                          r"renvo\w*\s+au\s+Conseil|accogl\w*|accolt\w*|approvar\w*", re.I)),
    ("none", re.compile(r"abzuschreiben|Abschreibung|als\s+erledigt|classer|classement|prendre\s+acte|"
                        r"stralciar\w*|evas\w*", re.I)),
]
EXEC = (r"(?:Regierungsrat|Bundesrat|Stadtrat|Gemeinderat|Conseil d.[ÉE]tat|Conseil-ex[ée]cutif|Gouvernement|Municipalit[ée]|"
        r"Conseil communal|Conseil administratif|Consiglio di Stato|Municipio|Regierung)")
TYPE_QI = re.compile(r"\b(interpellation|interpellanza|anfrage|frage|question|interrogazione|fragestunde)\b", re.I)


@dataclass
class Cand:
    g0: int
    g1: int
    text: str
    values: list[str]


def sentences(a: Doc) -> list[tuple[int, int]]:
    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?:])\s+(?=[A-ZÄÖÜÉÈÀ«\"„])|\n\s*\n", a.text):
        out.append((start, m.start()))
        start = m.end()
    out.append((start, len(a.text)))
    return [(a.trim(s, e)) for s, e in out if e - s > 5]


def value_of(s: str) -> list[str]:
    vals = [lab for lab, rx in VAL if rx.search(s)]
    # "nicht erheblich" contains "erheblich"; "Ablehnung ... Annahme als Postulat": keep convert/partial over others
    if "convert" in vals:
        return ["convert"]
    if "partial" in vals:
        return ["partial"]
    if "reject" in vals and "accept" in vals:
        acc = re.sub(r"nicht\s+(erheblich\s+zu\s+erkl\w*|zu\s+überweisen|anzunehmen)|non\s+accogl\w*|ne\s+pas\s+accepter", "",
                     s, flags=re.I)
        if not VAL[3][1].search(acc):
            return ["reject"]
        return ["partial"]
    return vals[:1]


def candidates(a: Doc) -> list[Cand]:
    out = []
    for s, e in sentences(a):
        t = a.text[s:e]
        if len(t) > 600 or not PROPOSE.search(t):
            continue
        v = value_of(t)
        if v:
            out.append(Cand(s, e, t, v))
    # "<executive> lehnt ... ab" (the executive rejects) is a proposal too
    for s0, s1 in sentences(a):
        t = a.text[s0:s1]
        rej = EXEC + r"[^.]{0,40}\blehnt\b[^.]{0,160}\bab\b|\blehnt\s+(der|die|das)\s+" + EXEC + r"[^.]{0,160}\bab\b"
        if len(t) <= 600 and re.search(rej, t) \
                and not any(c.g0 == s0 for c in out):
            out.append(Cand(s0, s1, t, ["reject"]))
    out.sort(key=lambda c: c.g0)
    # header field "Antrag Regierungsrat: <date> / Ablehnung" (LU) or "Antrag Regierungsrat: Ablehnung" (BE)
    m = re.search(r"Antrag\s+Regierungsrat\s*:[\s\S]{0,300}?(?:/\s*|\n)(Ablehnung|Erheblicherkl\w*(\s+als\s+Postulat)?|"
                  r"teilweise\s+\w+|Annahme(\s+als\s+Postulat)?)\b", a.text[:4000])
    if m:
        out.insert(0, Cand(m.start(1), m.end(1), m.group(1), value_of(m.group(1))))
    return out


def decide_rules(cands: list[Cand]) -> tuple[str | None, Cand | None, str]:
    """(value, evidence candidate, rule). value None = rules cannot decide (residue)."""
    if not cands:
        return "none", None, "no_recommendation_sentence"
    vals = {c.values[0] for c in cands}
    if len(vals) == 1:
        v = vals.pop()
        return v, cands[-1], f"lexicon_{v}"
    # the last sentence that proposes something decides when it is in the closing part
    return None, None, "conflicting_candidates"


def is_qi(q: Doc | None, affair_type: str | None) -> tuple[bool, tuple[int, int] | None]:
    """Interpellation / question by the type word in the head of the question document (span), else the OPD type."""
    if q is not None:
        m = TYPE_QI.search(q.text[:1500])
        mm = re.search(r"\b(motion|postulat\w*|mozione|anzug|résolution|risoluzione)\b", q.text[:1500], re.I)
        if m and (not mm or m.start() < mm.start()):
            return True, (m.start(), m.end())
        if mm:
            return False, (mm.start(), mm.end())
    if affair_type in ("Interpellation", "Question", "Question time"):
        return True, None
    return False, None
