"""Frozen rules baseline (route "rule"): deterministic DE/FR/IT anchor lexicons, no model.

Developed only on the dev pool (data/gold/dev_ids.json: spike items, recovery audit docs, Bilanz docs, dev split of the gold
sampler). Frozen by sha256 in eval/prereg before any held-out label exists.

Field `answer_date` — the date of the executive's answer to (or decision on) the affair, with a role:
  decision  the executive decided/adopted it: RRB-Nr. … vom, Datum RR-Sitzung, Regierungsratsbeschluss vom, Auszug aus dem
            Protokoll … Sitzung vom, N° ACE … du, Ainsi adopté en séance … le, RG n. … del, ris. mun. …
  dispatch  the date printed on the answer letter: "<Ort>, <Datum>" / "Date de dépôt" / "zugestellt am" in a document that
            carries an answer heading of the executive
Rules emit one of
  value    with span, role, rule id (and the decision number when the anchor carries one)
  null     with a typed reason, only on explicit evidence: an empty answer template (BE "RRB-Nr.: … vom" with no date),
           an oral-answer stub (VS "réponse orale"), or an image-only page without OCR
  abstain  no anchor → residue for the pointer (arm "rules only" scores abstain as null)
Footer/edit/print dates and submission dates are never answer dates (FOOTER, SUBMISSION).

Field `recommendation` — the executive's motion on a motion/postulate: accept | reject | convert (to postulate), lexical only.
"""

from __future__ import annotations

import re

from .lattice import DATE_RE, dates

DATE = "(?P<date>(?i:" + re.sub(r"\?P<\w+>", "", DATE_RE.pattern) + "))"  # month names case-insensitive everywhere
HEAD_CHARS = 2500


def _ws(rx: re.Pattern) -> re.Pattern:
    """pdftotext wraps lines anywhere: let every literal space in an anchor (outside character classes) match any
    whitespace run, newlines included."""
    out, in_cls, esc = [], False, False
    for ch in rx.pattern:
        if esc:
            out.append(ch)
            esc = False
        elif ch == "\\":
            out.append(ch)
            esc = True
        elif ch == "[" and not in_cls:
            in_cls = True
            out.append(ch)
        elif ch == "]" and in_cls:
            in_cls = False
            out.append(ch)
        elif ch == " " and not in_cls:
            out.append(r"\s+")
        else:
            out.append(ch)
    return re.compile("".join(out), rx.flags)


ANSWER_HEADING = re.compile(
    r"^\s*(?:Antwort (?:des|der) (?:Regierungsrat|Bundesrat|Stadtrat|Gemeinderat|Kleinen Rat|Staatsrat|Regierung)|"
    r"Antwort Regierungsrat|"
    r"Beantwortung (?:der|des) (?:Interpellation|Schriftlichen Anfrage|Anfrage|Frage|Motion|Postulat|Kleinen Anfrage)|"
    r"Stellungnahme (?:des|der) (?:Regierungsrat|Bundesrat|Stadtrat|Gemeinderat|Regierung)|STELLUNGNAHME ZU|"
    r"Intervention parlementaire\. Réponse|Parlamentarischer Vorstoss\.? Antwort|"
    r"R[ée]ponse (?:du|de la) (?:Conseil|Gouvernement|Conseil-ex[ée]cutif|Conseil d.[ÉE]tat|Municipalit[ée]|"
    r"Conseil administratif|"
    r"Conseil municipal|Conseil communal)|R[ÉE]PONSE (?:AU|À L.|A L.)\s*(?:POSTULAT|INTERPELLATION|MOTION|QUESTION)|"
    r"R[ée]ponse (?:au|à l.|a l.)\s*(?:postulat|interpellation|motion|question|r[ée]solution)|"
    r"Risposta (?:del|al|alla|all.)\s*(?:Consiglio di Stato|Municipio|interrogazione|interpellanza|mozione|\d)|RISPOSTA\b|"
    r"Il Consiglio di Stato\s*$)",
    re.I | re.M,
)
ANSWER_HEADING = _ws(ANSWER_HEADING)
# BE headers: answer template fields and their empty variant
BE_RRB_INLINE = re.compile(r"RRB[- ]?Nr\.?\s*:?\s*(?P<num>\d{1,4}/\d{4})\s+vom\s+" + DATE, re.I)
BE_RRB_SPLIT = re.compile(r"RRB[- ]?Nr\.?\s*:[^\n]*\n(?:[^\n]*\n){0,6}?\s*(?P<num>\d{1,4}/\d{4})\s*(?:\n\s*)?vom\s+" + DATE, re.I)
BE_RRB_NEW = re.compile(r"RRB[- ]?Nr\.?\s*:\s*\n\s*(?P<num>\d{1,4}/\d{4})\s*\n\s*Datum RR-Sitzung\s*:\s*\n\s*" + DATE, re.I)
BE_ACE = re.compile(
    r"(?:N°\s*d.?ACE|N°\s*ACE|ACE\s*n[°o]?)\s*:?[^\n]*\n(?:[^\n]*\n){0,6}?\s*(?P<num>\d{1,4}/\d{4})\s*(?:\n\s*)?du\s+" + DATE,
    re.I,
)
BE_ACE_INLINE = re.compile(r"(?:N°\s*d.?ACE|N°\s*ACE|ACE\s*n[°o]?)\s*:?\s*(?P<num>\d{1,4}/\d{4})\s+du\s+" + DATE, re.I)
BE_EMPTY = re.compile(r"(?:RRB[- ]?Nr\.?\s*:|N°\s*d.?ACE\s*:)[\s\S]{0,160}?\n\s*(?:vom|du)\s*\n", re.I)
DECISION = [
    ("be_rrb_inline", BE_RRB_INLINE),
    ("be_rrb_new", BE_RRB_NEW),
    ("be_rrb_split", BE_RRB_SPLIT),
    ("be_ace_inline", BE_ACE_INLINE),
    ("be_ace_split", BE_ACE),
    (
        "rrb_vom",
        re.compile(
            r"(?:Regierungsratsbeschluss|Stadtratsbeschluss|Gemeinderatsbeschluss|Beschluss des (?:Regierungsrates|"
            r"Stadtrates|Gemeinderates))\s*(?:Nr\.?\s*(?P<num>[\d/.-]+)\s*)?vom\s+" + DATE,
            re.I,
        ),
    ),
    (
        "protokoll_sitzung",
        re.compile(
            r"Protokoll\s+des\s+(?:Regierungsrat|Stadtrat|Gemeinderat)\w*(?:\s+(?:des Kantons|von)\s+[\w-]+)?"
            r"[\s\S]{0,160}?(?:Sitzung\s+)?vom\s+" + DATE,
            re.I,
        ),
    ),
    # "Conseil communal"/"Conseil municipal" are the legislature in Lausanne/Ville de Genève but the executive in VS communes:
    # ambiguous, so they are not decision anchors
    (
        "proces_verbal_exec",
        re.compile(
            r"proc[eè]s-verbal du (?:Conseil-ex[ée]cutif|Conseil d.[ÉE]tat|Gouvernement|"
            r"Conseil administratif)[\s\S]{0,160}?(?:s[ée]ance du|du|le)\s+" + DATE,
            re.I,
        ),
    ),
    (
        "datum_rr_sitzung",
        re.compile(
            r"Datum RR-Sitzung\s*:?[^\n]*\n(?:[^\n]*\n){0,6}?\s*"
            + DATE
            + r"\s*$|Datum RR-Sitzung\s*:?\s*"
            + DATE.replace("?P<date>", "?P<date2>"),
            re.I | re.M,
        ),
    ),
    ("lu_antrag", re.compile(r"Antrag Regierungsrat\s*:[\s\S]{0,300}?" + DATE + r"\s*/\s*(?P<rec>[^\n]{3,60})", re.I)),
    (
        "fr_adopte_seance",
        re.compile(
            r"(?:Ainsi )?adopt[ée]e? en s[ée]ance (?:de (?:la )?Municipalit[ée]|du Conseil[^\n,]{0,40})"
            r"[^\n]{0,40}?le\s+" + DATE,
            re.I,
        ),
    ),
    (
        "fr_seance_exec",
        re.compile(
            r"(?:Conseil d.[ÉE]tat|Conseil-ex[ée]cutif|Gouvernement|Municipalit[ée]|"
            r"Conseil administratif)[^\n]{0,60}?(?:en|dans|lors de) sa s[ée]ance du\s+" + DATE,
            re.I,
        ),
    ),
    ("it_rg", re.compile(r"\bRG\s*n\.?\s*(?P<num>\d+)\s*del\s+" + DATE, re.I)),
    # the abbreviated header label only ("ris. mun.: 01/02/2012"); prose like "con risoluzione governativa n. 87 del ..." cites
    # an earlier decision and is not this document's answer date
    (
        "it_ris_label",
        re.compile(r"\bris\.\s*(?:mun|gov)\.\s*:\s*(?:n(?:o|r)?\.?\s*(?P<num>[\d./]+)\s*)?(?:del\s+)?" + DATE, re.I),
    ),
    ("it_risposta_del", re.compile(r"^\s*Risposta del\s+" + DATE + r"\s+all.interpellanza", re.I | re.M)),
]
DECISION = [(rid, _ws(rx)) for rid, rx in DECISION]
DISPATCH = [
    ("date_de_depot", re.compile(r"Date de d[ée]p[ôo]t\s*:\s*" + DATE, re.I)),
    ("zugestellt", re.compile(r"zugestellt am\s+" + DATE, re.I)),
    ("place_date", re.compile(r"^\s*[A-ZÄÖÜ][\w'’.\- ]{1,40}?,\s*(?:(?:den|le|il|lì|li)\s+)?" + DATE + r"(?:/\w+)?\s*$", re.M)),
    (
        "ti_header_date",
        re.compile(r"Bellinzona\b[\s\S]{0,40}?" + DATE),
    ),  # TI letterhead "Numero … Bellinzona … 3 luglio 2024" (also OCR)
]
DATE_LINE = re.compile(
    r"^[^\w\n]{0,3}" + DATE + r"\.?\s*$", re.M
)  # a line holding only a date (Ville de Genève, Mendrisio headers)
# executive signature block: "Berne, le 4 avril 2012 / Au nom du Conseil-exécutif", "Im Namen des Regierungsrates"
SIGNATURE = re.compile(
    r"^\s*[A-ZÄÖÜ][\w'’.\- ]{1,40}?,\s*(?:(?:den|le|il|lì|li)\s+)?" + DATE + r"\.?\s*\n(?:[^\n]*\n){0,3}?\s*"
    r"(?:Au nom du|Im Namen des|Per il|Pour le|Für den)\s+(?:Conseil-ex[ée]cutif|Conseil d.[ÉE]tat|Gouvernement|"
    r"Regierungsrat|Stadtrat|Gemeinderat|Consiglio di Stato|Municipio|Conseil administratif|Municipalit[ée])",
    re.M,
)
LE_DATE_LINE = re.compile(r"^\s*[Ll]e\s+" + DATE + r"\.?\s*$", re.M)  # "Le 21 mars 2007." above a signature
TAIL_CHARS = 2500  # signature place-date at the end of an answer ("Sion, le 12 juillet 2023", "Delémont, le ...")
FOOTER = re.compile(
    r"Letzte Bearbeitung|Derni[èe]re modification|Version\s*:|Dok\.?-Nr|No de document|Druckdatum|gedruckt|imprim[ée]|"
    r"Document g[ée]n[ée]r[ée]|Stand\s*:|Ausdruck|erstellt am|Dateiname|Seite \d+\s*(?:von|/)|Page \d+\s*(?:sur|/)",
    re.I,
)
SUBMISSION = re.compile(r"Eingereicht am|eingereicht|d[ée]pos[ée]e? le|presentat[ao] il|Déposée le|reichte", re.I)
ORAL = re.compile(r"r[ée]ponse orale|m[üu]ndliche Antwort|risposta orale", re.I)


def _date_of(m: re.Match) -> str | None:
    c = dates([m.group("date") or m.groupdict().get("date2") or ""])
    return c[0]["value"] if c else None


def _dgroup(m: re.Match) -> str:
    return "date" if m.group("date") is not None else "date2"


def _span(page: int, text: str, m: re.Match) -> dict:
    s, e = m.span(_dgroup(m))
    ls = text.rfind("\n", 0, s) + 1
    le = text.find("\n", e)
    return dict(
        page=page, char_start=s, char_end=e, quote=re.sub(r"\s+", " ", text[max(ls, m.start()) : (le if le > 0 else e)])[:200]
    )


def anchors(pages: list[str]) -> list[tuple[int, int]]:
    """(page, char offset) of every answer heading or decision anchor — used to place pointer choices."""
    out = []
    for pi, t in enumerate(pages, start=1):
        for m in ANSWER_HEADING.finditer(t):
            out.append((pi, m.start()))
        for _, rx in DECISION:
            for m in rx.finditer(t):
                out.append((pi, m.start(_dgroup(m))))
    return out


def _line(text: str, pos: int) -> str:
    ls = text.rfind("\n", 0, pos) + 1
    le = text.find("\n", pos)
    return text[ls : le if le > 0 else len(text)]


def answer_date(pages: list[str], image_only: bool = False) -> dict:
    full = "\n".join(pages)
    if not full.strip():
        return dict(
            field="answer_date", status="null", null_reason="image_only" if image_only else "text_failed", rule="empty_text"
        )
    if len(full.strip()) < 400 and ORAL.search(full):
        return dict(field="answer_date", status="null", null_reason="oral", rule="oral_stub")
    # 1. decision anchors anywhere (header first: pages in order, first match wins within the rule priority)
    for rid, rx in DECISION:
        for pi, t in enumerate(pages, start=1):
            for m in rx.finditer(t):
                if FOOTER.search(_line(t, m.start(_dgroup(m)))):
                    continue
                v = _date_of(m)
                if v:
                    out = dict(
                        field="answer_date",
                        status="value",
                        value=v,
                        role="decision",
                        rule=rid,
                        span=_span(pi, t, m),
                        number=m.groupdict().get("num"),
                    )
                    if m.groupdict().get("rec"):
                        out["recommendation_text"] = m.group("rec").strip()
                    return out
    # 1b. a place-date line directly above an executive signature block (bills, reports and answers alike)
    for pi, t in enumerate(pages, start=1):
        for m in SIGNATURE.finditer(t):
            v = _date_of(m)
            if v:
                return dict(
                    field="answer_date", status="value", value=v, role="dispatch", rule="signature_block", span=_span(pi, t, m)
                )
    # 2. explicit empty answer template (BE): the answer does not exist in this document
    head = full[:HEAD_CHARS]
    if BE_EMPTY.search(head) and not ANSWER_HEADING.search(head):
        return dict(field="answer_date", status="null", null_reason="not_in_document", rule="be_empty_template")
    # 3. dispatch date on a document that carries an executive answer heading
    h = ANSWER_HEADING.search(head)
    if h:
        last = len(pages)
        tail_from = max(0, len(pages[-1]) - TAIL_CHARS)
        cands = [(rid, rx, "head", 1, 0, HEAD_CHARS) for rid, rx in DISPATCH]
        # a bare date line at most 200 chars above the heading (date printed right before "Réponse du Conseil administratif")
        cands.append(("date_line_above_heading", DATE_LINE, "head", 1, max(0, h.start() - 200), h.start()))
        cands += [
            ("place_date", DISPATCH[2][1], "tail", last, tail_from, len(pages[-1])),
            ("le_date_line", LE_DATE_LINE, "tail", last, tail_from, len(pages[-1])),
        ]
        for rid, rx, where, pi, lo, hi in cands:
            t = pages[pi - 1]
            for m in rx.finditer(t, lo, min(hi, len(t))):
                ln = _line(t, m.start("date"))
                if FOOTER.search(ln) or SUBMISSION.search(ln):
                    continue
                v = _date_of(m)
                if v:
                    return dict(
                        field="answer_date", status="value", value=v, role="dispatch", rule=f"{rid}_{where}", span=_span(pi, t, m)
                    )
        return dict(field="answer_date", status="abstain", rule="heading_without_date", heading=h.group(0).strip()[:80])
    return dict(field="answer_date", status="abstain", rule="no_anchor")


# ------------------------------------------------------------------------------------------------ recommendation
EXEC = (
    r"(?:Regierungsrat|Bundesrat|Stadtrat|Gemeinderat|Conseil d.[ÉE]tat|Conseil-ex[ée]cutif|Gouvernement|Municipalit[ée]|"
    r"Conseil municipal|Conseil communal|Conseil administratif|Consiglio di Stato|Municipio)"
)
REC_PAT = {  # the executive must be the subject of the motion verb (a commission's recommendation is not the government's)
    "convert": [
        r"(?:als|in ein(?:en)?)\s+Postulat\s+(?:zu\s+)?(?:überweisen|umzuwandeln|erheblich)",
        r"Erheblicherkl[äa]rung als Postulat",
        r"Annahme als Postulat",
        r"sous (?:la )?forme de postulat",
        r"transform(?:er|ée?) en postulat",
        r"trasformar(?:e|la|lo) in postulato",
        r"come postulato",
    ],
    "reject": [
        EXEC + r"[^.]{0,80}?(?:beantragt|empfiehlt)[^.]{0,160}?(?:abzulehnen|nicht (?:erheblich zu erkl[äa]ren|zu überweisen))",
        r"Antrag Regierungsrat\s*:[\s\S]{0,300}?/\s*Ablehnung",
        r"Antrag\s*:\s*Ablehnung",
        EXEC + r"[^.]{0,80}?propose[^.]{0,120}?(?:de )?(?:rejeter|refuser|le rejet)",
        r"Proposition du Conseil-ex[ée]cutif\s*:?\s*Rejet",
        EXEC + r"[^.]{0,80}?invite[^.]{0,80}?à (?:rejeter|refuser)",
        EXEC + r"[^.]{0,80}?propone[^.]{0,120}?di (?:respingere|non accogliere)",
        EXEC + r"[^.]{0,80}?invita[^.]{0,80}?a respingere",
    ],
    "accept": [
        EXEC + r"[^.]{0,80}?(?:beantragt|empfiehlt)[^.]{0,160}?(?:anzunehmen|erheblich zu erkl[äa]ren|zu überweisen)",
        r"Antrag Regierungsrat\s*:[\s\S]{0,300}?/\s*(?:Erheblicherkl[äa]rung|Annahme)",
        r"Antrag\s*:\s*Annahme",
        EXEC + r"[^.]{0,80}?propose[^.]{0,120}?(?:d.)?(?:accepter|adopter|l.acceptation|l.adoption)",
        r"Proposition du Conseil-ex[ée]cutif\s*:?\s*(?:Adoption|Acceptation)",
        EXEC + r"[^.]{0,80}?invite[^.]{0,80}?à (?:accepter|adopter)",
        EXEC + r"[^.]{0,80}?propone[^.]{0,120}?di accogliere",
        EXEC + r"[^.]{0,80}?invita[^.]{0,80}?ad? accogliere",
    ],
}
REC = [(lab, _ws(re.compile("|".join(pats), re.I))) for lab, pats in REC_PAT.items()]  # priority: convert > reject > accept


def recommendation(pages: list[str], affair_type: str | None = None) -> dict:
    if affair_type in ("Interpellation", "Question", "Question time"):
        return dict(field="recommendation", status="null", null_reason="not_applicable", rule="affair_type")
    # label priority convert > reject > accept over the whole document (conversions contain "Annahme"; "nicht erheblich"
    # contains "erheblich"); the span is the first match of the winning label
    for lab, rx in REC:
        for pi, t in enumerate(pages, start=1):
            m = rx.search(t)
            if m:
                return dict(
                    field="recommendation",
                    status="value",
                    value=lab,
                    rule=f"rec_{lab}",
                    span=dict(page=pi, char_start=m.start(), char_end=m.end(), quote=re.sub(r"\s+", " ", m.group(0))[:200]),
                )
    return dict(field="recommendation", status="abstain", rule="no_anchor")
