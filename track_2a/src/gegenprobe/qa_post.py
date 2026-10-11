"""Unlocked post-processing layer over the frozen Q/A extractor (src/gegenprobe/qa, LOCK6). Used only by
`python -m gegenprobe.qa_cli`; the P5 evaluation (eval/gold6) calls the frozen extractor directly, so nothing here changes
a registered result. Rules only, no model.

  prepare(pages)   length-preserving text fix before the frozen extractor runs: an answer heading printed after a
                   section number on one line ("3.1 Zu Frage 1:", as OPD's stored text and some PDFs have it) gets a line
                   break instead of the space, so the frozen heading rules see "Zu Frage 1:" at a line start. Offsets do
                   not move (one character replaced by one); every quote is cut from the original text.
  apply(...)       after the frozen extractor, in this order:
    questions end  the question list ends at the reasoning heading ("Begründung", "Begründung:", "Motivation",
                   "Motivazione", "Exposé des motifs", "Développement") or a co-signature table heading
                   ("Mitunterzeichnerinnen und Mitunterzeichner", "Name / Vorname", "Unterschriften"), plus the settings
                   file's `questions_end` patterns: a question that runs into it is cut before it, a numbered item after
                   it is not a question. A trailing item of a question list that is an OCR-garbled table row (no "?",
                   short, non-name characters: "7. BreniicT M^rho") is dropped too.
    demand         a motion's / postulate's demand whose points are dash bullets is ONE item (docs/qa.md): the request
                   paragraph through its last bullet, answered by the whole reply. Numbered demands (1. 2., a) b))
                   stay separate items.
    reasoning      starts after the reprinted member's text: a reprint heading ("Vorstosstext", "Auftragstext", "Wortlaut
                   des Vorstosses", "Texte de l'interpellation", ...) followed by the executive's heading ("Stellungnahme
                   des Regierungsrates", "Réponse du Conseil d'Etat", ...), or a leading block of lines that repeat the
                   question document.
    closing        the reasoning and the answers end before the closing block: a signature (name line + "Staatsschreiber",
                   "Chancelier", "Il Cancelliere", ...), a distribution list ("Verteiler", "Mitteilung an", "Copie à",
                   "Vorberatende Kommission", ...), "Im Namen des Regierungsrates", "Le Conseil d'Etat", "Per il
                   Consiglio di Stato", or the "Antrag des Regierungsrates" section. Generic, not per parliament; a
                   settings file may add `closing` patterns.
    people         a labelled signature list ("Unterschriften:", "Signataires :", "Firmatari:") is parsed: labels,
                   counts "(9)" and numbering "1." are not part of a name, names wrapped over a line are joined, and a
                   numbered list ("1. Beat Künzli, 2. ...") names the submitter first. Every name is a span.
    answer title   the submitter and co-signatories come from the answer's title line ("Einfache Anfrage von A, B und
                   C vom ...", "Interpellation de ...", "Interrogazione di ...") instead of a signature block when the
                   signature block is OCR-garbled (non-name characters such as ^ < / | or a digit inside a word on the
                   signature lines), or always with `prefer_answer_title: true` in the settings file.
    recommendation the frozen rules found no recommendation sentence (not_in_document) or conflicting ones: your
                   --anchors recommendation phrases for the body, then convert's frozen recommendation rules, then a
                   recommendation printed under an "Antrag des Regierungsrates" / "Proposition du Conseil d'Etat" /
                   "Proposta del Consiglio di Stato" heading. A frozen "accept" read off "Nichterheblicherklärung" becomes
                   reject. A not_in_document null that stands on a body outside the rule coverage is no_rules_for_body
                   (with --body) or flagged for review (without --body). On a body outside the rule coverage your
                   --anchors recommendation phrase beats the frozen lexicon (as in convert, where anchors fill before
                   the Q/A lexicon), and a value that convert's frozen rules contradict is flagged.
    coverage       --body outside data/convert/rules_coverage.json: every rule value is flagged needs_review (as in
                   convert), unless its rule is listed in the settings file's confirm_rules for the body.
"""
from __future__ import annotations

import re

from .convert import body_settings, overlay
from .qa import extract as X
from .qa import people as P
from .qa.answers import _shingles
from .qa.questions import CUE
from .qa.text import Doc, boilerplate_lines

# ---------------------------------------------------------------------------------------------- prepare
_AFTER_NUM = (r"(?:Zu|Ad|Zur)\s+(?:den\s+|der\s+)?(?:Fragen?|Punkte?n?|Ziffern?)\s+\d|Fragen?\s+\d|Antwort\s+(?:zu|auf)\s+"
              r"Frage|R[ée]ponses?\s+(?:à\s+la\s+|aux\s+)?questions?\s+\d|Questions?\s+\d|Risposta\s+(?:alla\s+|alle\s+)?"
              r"domand|Domand[ae]\s+(?:n\.\s*)?\d")
SECTION_HEADING = re.compile(rf"(?m)^([ \t]*\d{{1,2}}(?:\.\d{{1,2}})*\.?)[ \t](?=[ \t]*(?:{_AFTER_NUM}))", re.I)


def prepare(pages: list[str]) -> tuple[list[str], int]:
    """-> (pages with section-number-prefixed answer headings split onto their own line, number of headings split)."""
    out, n = [], 0
    for p in pages:
        q, k = SECTION_HEADING.subn(lambda m: m.group(1) + "\n", p)
        assert len(q) == len(p)
        out.append(q)
        n += k
    return out, n


# ---------------------------------------------------------------------------------------------- patterns
NUMP = r"(?:\d{1,2}(?:\.\d{1,2})*\.?\s*)?"
EXEC_N = (r"(?:Regierungsrat\w*|Stadtrat\w*|Gemeinderat\w*|Regierung|Bundesrat\w*|Landrat\w*|Kleinen\s+Rat\w*|"
          r"Exekutive|Gemeindevorstand\w*)")
REPRINT_H = re.compile(
    rf"^\s*{NUMP}(?:Vorstosstext|Auftragstext|Motionstext|Postulatstext|Interpellationstext|Anfragetext|Fragetext|"
    r"Wortlaut\s+(?:des|der)\s+(?:Vorstosses|Auftrags|Motion|Interpellation|Anfrage|Postulats|Frage)|"
    r"Text\s+(?:des|der)\s+(?:Vorstosses|Auftrags|Motion|Interpellation|Anfrage|Postulats)|Eingereichter\s+Text|"
    r"Begr[üu]ndung\s*\((?:Vorstosstext|Auftragstext)\)|"
    r"Texte\s+(?:de\s+l.|du\s+|de\s+la\s+)(?:interpellation|motion|postulat|question|r[ée]solution)|"
    r"Testo\s+dell?.?\s*(?:interpellanza|mozione|interrogazione|postulato))\b[^\n]{0,40}$", re.I | re.M)
REPLY_H = re.compile(
    rf"^\s*{NUMP}(?:(?:Stellungnahme|Antwort|Beantwortung|Erw[äa]gungen)\s+(?:des|der)\s+{EXEC_N}|"
    r"R[ée]ponse\s+(?:du|de\s+la)\s+(?:Conseil|Coll[èe]ge|Municipalit[ée]|Gouvernement)[^\n]{0,30}|"
    r"Risposta\s+del\s+(?:Consiglio|Municipio)[^\n]{0,30}|Presa\s+di\s+posizione\s+del\s+\w+[^\n]{0,30})\s*:?\s*$",
    re.I | re.M)
OFFICER = re.compile(
    r"^\s*(?:(?:Der|Die|Le|La|Il)\s+)?(?:Staatsschreiber(?:in)?|Landschreiber(?:in)?|Ratsschreiber(?:in)?|"
    r"Stadtschreiber(?:in)?|Gemeindeschreiber(?:in)?|Staatskanzler(?:in)?|Kanzler(?:in)?|Chancel(?:ier|i[eè]re)|"
    r"Cancellier[ea]|Segretari[oa](?:\s+(?:di\s+Stato|comunale|generale))?|Secr[ée]taire(?:\s+\w+){0,2}|"
    r"Pr[äa]sident(?:in)?|Pr[ée]sident(?:e)?|Presidente|Landammann|Stadtpr[äa]sident(?:in)?|"
    r"Regierungspr[äa]sident(?:in)?|Gemeindepr[äa]sident(?:in)?|Syndic(?:que)?|Sindac[oa]|Vizekanzler(?:in)?|"
    r"Vice-chancel(?:ier|i[eè]re))\s*[:,]?\s*$", re.I)
DISTRIBUTION = re.compile(
    r"^\s*(?:Verteiler|Verteilung|Geht\s+an|Kopie\s+an|Zustellung\s+an|Mitteilung(?:en)?\s+an|Vorberatende\s+Kommission|"
    r"Distribution|Copie\s+(?:à|aux?)|Communication\s+(?:à|aux?)|Exp[ée]dition|Intimazione|Comunicazione\s+a|"
    r"Trasmess[oa]\s+a|Distribuzione)\b", re.I)
FORMULA = re.compile(
    r"^\s*(?:Im\s+Namen\s+de[sr]\s+\w+|Namens\s+de[sr]\s+\w+|F[üu]r\s+den\s+(?:Regierungsrat|Stadtrat|Gemeinderat)|"
    r"(?:Le\s+Conseil\s+d.[ÉEée]tat|Il\s+Consiglio\s+di\s+Stato|Der\s+Regierungsrat)(?:\s+(?:du|de|del|della|des)\s+[^\n.]{0,50})?"
    r"\s*[:,]?\s*$|Pour\s+le\s+Conseil|AU\s+NOM\s+D|Au\s+nom\s+d|Per\s+il\s+(?:Consiglio|Municipio)|PER\s+IL\s+|"
    r"Mit\s+freundlichen\s+Gr[üu]ssen|Freundliche\s+Gr[üu]sse|Hochachtungsvoll|Veuillez\s+agr[ée]er|Distinti\s+saluti|"
    r"Con\s+ossequio)", re.I)
ANTRAG_H = re.compile(
    rf"^\s*{NUMP}(?:(?:Antrag|Antr[äa]ge)\s+(?:des|der)\s+{EXEC_N}|Antrag\s+{EXEC_N}|Antrag|"
    r"Proposition\s+du\s+(?:Conseil|Coll[èe]ge|Gouvernement)[^\n]{0,30}|Proposta\s+del\s+(?:Consiglio|Municipio)[^\n]{0,30})"
    r"\s*:?\s*$", re.I)
SECTION_NO = re.compile(r"^\s*\d{1,2}(?:\.\d{1,2})*\.?\s*$")
PLACE_DATE = re.compile(r"^\s*[A-ZÄÖÜ][\w .'-]{1,40},\s*(?:den\s+|le\s+|il\s+)?\d{1,2}\.?\s*\w+\.?\s*\d{4}\s*$")

# a recommendation under an "Antrag" heading: label lexicon (order matters; "Nichterheblicherklärung" contains
# "erheblicherklärung", "Erheblicherklärung und Abschreibung" contains both)
REC_LEX = [
    ("accept_and_write_off", re.compile(r"Erheblicherkl\w*\s+und\s+(?:gleichzeitige\s+)?Abschreibung|Annahme\s+und\s+"
                                        r"Abschreibung|accepter\s+et\s+classer|accolta\s+e\s+stralciata", re.I)),
    ("convert", re.compile(r"\bals\s+Postulat|in\s+(?:ein(?:en)?\s+)?Postulat|forme\s+(?:de|d.un)\s+postulat|"
                           r"come\s+postulato|in\s+postulato", re.I)),
    ("partial", re.compile(r"teilweise|partiel|en\s+partie|parzial|in\s+parte", re.I)),
    ("reject", re.compile(r"Nicht\s*erheblich|Nichterheblich|Nicht\s*[üu]berweisung|nicht\s+(?:zu\s+)?[üu]berweisen|"
                          r"Ablehnung|abzulehnen|Abweisung|Nichteintreten|\brejet|rejeter|refus|respin|non\s+accogl", re.I)),
    ("accept", re.compile(r"Erheblicherkl|[ÜU]berweisung|Annahme|anzunehmen|Zustimmung|acceptation|accepter|adoption|"
                          r"accogli|approvazione", re.I)),
    ("none", re.compile(r"Abschreibung|abzuschreiben|classement|classer|stralci|Kenntnisnahme|prendre\s+acte|"
                        r"presa\s+d.atto", re.I)),
]
NICHT_ERHEBLICH = re.compile(r"Nicht\s*erheblich|Nichterheblich", re.I)

LABEL = re.compile(r"(?:Unterschriften|Unterschrift|Unterzeichnende|Unterzeichner(?:in|innen)?|Erstunterzeichner(?:in)?|"
                   r"Mitunterzeichnende|Mitunterzeichner(?:innen)?|Signatures?|Signataires?|Cosignataires?|Firme|"
                   r"Firmatari[oe]?|Cofirmatari)\s*:", re.I)
_NT = rf"(?:{P.TOK}|{P.INIT})"
NAME_FULL = re.compile(rf"(?:(?:Dr\.|Prof\.)\s+)?(?:{P.PART}\s+)?{_NT}(?:\s+(?:{P.PART}\s+)?{_NT}){{1,4}}")
LEAD_JUNK = re.compile(rf"^(?:\s*{LABEL.pattern}\s*|\s*\d{{1,2}}\.\s+)+", re.I)
TAIL_JUNK = re.compile(r"(?:\s*\(\s*\d{1,3}\s*\)|\s*[;,]|(?<!\b[A-ZÄÖÜ])\.)+\s*$")  # an initial keeps its dot


# the member's question list ends here (after the first question)
QEND = re.compile(r"^\s*(?:[IVX\d]{1,3}\.?\s+)?(?:Begr[üu]ndung|Begruendung|Motivation|Motivazioni?|Expos[ée]\s+des\s+"
                  r"motifs|D[ée]veloppement)\s*(?::.*)?$", re.I)
SIGTABLE = re.compile(r"^\s*(?:Mitunterzeichn\w*|Name\s*/\s*Vorname|Vorname\s*/\s*Name|Nom\s*/\s*pr[ée]nom|"
                      r"Cognome\s*/?\s*nome|Unterschriften?\s*:?\s*$|Unterschriften\s*:|Signatures?\s*:?\s*$|"
                      r"Firm[ae]\s*:?\s*$|Firmatari\w*\s*:?\s*$)", re.I)
# OCR damage on a signature line or table row: characters no printed name contains, or a digit inside a word
GARBLED = re.compile(r"[\^<>\\|~{}\[\]@#%*=_€£§]|[^\W\d_]\d|\d[^\W\d_]|\d-[^\W\d_]|/[^\s\d]")


# ---------------------------------------------------------------------------------------------- helpers
def _lines_in(d: Doc, g0: int, g1: int):
    for i, ln in enumerate(d.lines):
        if ln.g1 > g0 and ln.g0 < g1:
            yield i, ln


def _next_text_line(d: Doc, i: int, skip: set[int]) -> int | None:
    j = i + 1
    while j < len(d.lines) and (j in skip or not d.lines[j].text.strip()):
        j += 1
    return j if j < len(d.lines) else None


def _prev_text_line(d: Doc, i: int, skip: set[int], floor: int = 0) -> int | None:
    j = i - 1
    while j >= floor and (j in skip or not d.lines[j].text.strip()):
        j -= 1
    return j if j >= floor else None


def _trim_tail(d: Doc, g0: int, g1: int, skip: set[int]) -> int:
    """Drop trailing blank lines, running headers/footers and bare section numbers ("4.") before g1."""
    g0, g1 = d.trim(g0, g1)
    while g1 > g0:
        i = d.line_at(g1 - 1)
        ln = d.lines[i]
        if ln.g0 <= g0:
            break
        if i in skip or SECTION_NO.match(ln.text) or not ln.text.strip():
            g1 = d.trim(g0, ln.g0)[1]
            continue
        break
    return g1


def _name_like(t: str) -> bool:
    t = t.strip()
    return bool(t) and len(t) <= 45 and not t.endswith(".") and bool(NAME_FULL.fullmatch(t)) and not P.NOT_NAME.match(t)


def _span(d: Doc, g0: int, g1: int) -> dict:
    return dict(doc=d.role, g_start=g0, g_end=g1)


# ---------------------------------------------------------------------------------------------- steps
def _garbled_row(t: str) -> bool:
    t = t.strip()
    letters = sum(c.isalpha() for c in t)
    vis = sum(not c.isspace() for c in t)
    return bool(t) and (bool(re.search(r"[\^<>\\|~{}\[\]@#%*=_€£§]", t)) or vis > 0 and letters / vis < 0.7)


def _questions_end(view, rules, q: Doc | None, extra_rx, log) -> list[int]:
    """-> the numbers of the items dropped. Cuts the question list at its end (QEND / SIGTABLE / settings questions_end)
    and drops trailing OCR-garbled table rows."""
    qs = view["questions"]
    if q is None or not qs:
        return []
    skip = boilerplate_lines(q)
    first_line_end = q.lines[q.line_at(qs[0]["span"]["g_start"])].g1
    last_end = max(x["span"]["g_end"] for x in qs)
    end, why = None, None
    for i, ln in enumerate(q.lines):
        if ln.g0 < first_line_end or i in skip:
            continue
        if ln.g0 >= last_end:
            break
        t = ln.text
        if len(t) < 200 and QEND.match(t):
            why = f"reasoning heading '{t.strip()[:40]}'"
        elif len(t) < 120 and SIGTABLE.match(t):
            why = f"signature table heading '{t.strip()[:40]}'"
        elif any(rx.search(t) for rx in extra_rx):
            why = f"questions_end (settings file) at '{t.strip()[:40]}'"
        else:
            continue
        end = ln.g0
        break
    if end is not None and any(x["span"]["g_start"] >= end and "?" in q.text[x["span"]["g_start"]:x["span"]["g_end"]]
                               for x in qs):
        # a question follows the heading (a layout with a reason under each question): not the end of the list
        log.append(dict(field="questions", step="questions end", result=f"{why} is followed by further questions: "
                                                                        "not the end of the list"))
        end, why = None, None
    kept, cut = [], 0
    for x in qs:
        sp = x["span"]
        if end is not None and sp["g_start"] >= end:
            continue
        if end is not None and sp["g_end"] > end:
            e = _trim_tail(q, sp["g_start"], end, skip)
            if e <= sp["g_start"]:
                continue
            x = dict(x, span=_span(q, sp["g_start"], e))
            cut += 1
        kept.append(x)
    dropped_end = [x["n"] for x in qs if x not in kept and not any(k["n"] == x["n"] for k in kept)]
    # trailing rows of a numbered signature table read as list items ("7. BreniicT M^rho")
    garbled = []
    asks = sum("?" in q.text[x["span"]["g_start"]:x["span"]["g_end"]] for x in kept)
    while len(kept) > 1 and asks * 2 >= len(kept):
        sp = kept[-1]["span"]
        body = re.sub(r"^\s*\d{1,2}\s*[.)]", "", q.text[sp["g_start"]:sp["g_end"]])
        if "?" in body or len(body.strip()) >= 60 or not _garbled_row(body):
            break
        garbled.append(kept.pop()["n"])
    dropped = dropped_end + garbled[::-1]
    if not dropped and not cut:
        log.append(dict(field="questions", step="questions end", result="the question list does not run past its end"
                        + (f" ({why})" if why else "")))
        return []
    keep_n = {x["n"] for x in kept}
    view["questions"] = kept
    view["answers"] = [dict(a, joint_with=[j for j in a.get("joint_with", []) if j in keep_n]) for a in view["answers"]
                       if a["n"] in keep_n]
    rules["questions"] = f"{rules['questions']}+post_questions_end"
    parts = []
    if end is not None and (cut or dropped_end):
        parts.append(f"list ends before the {why}" + (f": {cut} question(s) cut" if cut else "")
                     + (f", item(s) {', '.join(map(str, dropped_end))} after it dropped" if dropped_end else ""))
    if garbled:
        parts.append(f"item(s) {', '.join(map(str, garbled[::-1]))} dropped: OCR-garbled table row(s), not questions")
    log.append(dict(field="questions", step="questions end", result="; ".join(parts)))
    return dropped


def _garbled_signature(q: Doc, view) -> str | None:
    """The first OCR-garbled line in the signature block the frozen rule read the names from (the name lines and the
    lines just above them), or None."""
    xs = [x for x in [view.get("submitter")] + list(view.get("co_signatories") or [])
          if x and x["span"]["doc"] == "question"]
    if not xs:
        return None
    i0 = q.line_at(min(x["span"]["g_start"] for x in xs))
    i1 = q.line_at(max(x["span"]["g_end"] for x in xs))
    for i in range(max(0, i0 - 6), min(len(q.lines), i1 + 3)):
        t = q.lines[i].text.strip()
        if t and len(t) < 80 and GARBLED.search(t):
            return t[:40]
    return None


def answer_title_names(a: Doc) -> list[tuple[str, int, int]]:
    """Names in the answer's title line, by the frozen rules' title patterns (people.TITLE, people.ANSWER_TITLE)."""
    head = a.text[:3000]
    for rx in [P.TITLE] + P.ANSWER_TITLE:
        m = rx.search(head)
        if m:
            ns = P._split_names(a, m.start("names"), m.group("names"))
            if ns:
                return ns
    return []


def _answer_title(view, rules, q: Doc | None, a: Doc | None, prefer: bool, log) -> None:
    if a is None or rules.get("people") == "answer_title":
        return
    why = None
    if prefer:
        why = "prefer_answer_title in the settings file"
    elif rules.get("people") == "signature_block" and q is not None:
        bad = _garbled_signature(q, view)
        if bad:
            why = f"the signature block is OCR-garbled ('{bad}')"
    if not why:
        return
    ns = answer_title_names(a)
    if not ns:
        log.append(dict(field="people", step="answer title", result=f"{why}, but the answer prints no title line with "
                                                                    "names; names unchanged"))
        return
    old = (view.get("submitter") or {}).get("name")
    keys = {w.lower() for n, _, _ in ns for w in n.split() if len(w) > 2}
    # a title with the submitter only ("Interpellation de A et consorts") keeps the clean co-signatories read before
    kept = [] if len(ns) > 1 else [c for c in view.get("co_signatories") or [] if not GARBLED.search(c["name"]) and
                                   not keys & {w.lower() for w in c["name"].split() if len(w) > 2}]
    view["submitter"] = dict(name=ns[0][0], span=_span(a, ns[0][1], ns[0][2]), rule="answer_title")
    view["co_signatories"] = [dict(name=n, span=_span(a, s, e), rule="answer_title") for n, s, e in ns[1:]] + kept
    prev = rules.get("people")
    rules["people"] = "answer_title"
    log.append(dict(field="people", step="answer title", result=f"{why}: {len(ns)} name(s) from the answer's title line "
                                                                f"(submitter {ns[0][0]}; was {old or 'null'}, rule {prev})"
                                                                + (f"; {len(kept)} co-signator(ies) kept" if kept else "")))


def _demand(view, rules, q: Doc | None, qi: bool, affair_type, log) -> bool:
    if q is None or qi or not str(rules.get("questions") or "").startswith("marker_chain_bul") or len(view["questions"]) < 2:
        return False
    motion = affair_type in ("Motion", "Postulate") or bool(
        re.search(r"\b(motion|postulat\w*|mozione|postulato|anzug|auftrag|r[ée]solution|risoluzione)\b", q.text[:1500], re.I))
    if not motion:
        return False
    first = view["questions"][0]["span"]["g_start"]
    last = view["questions"][-1]["span"]["g_end"]
    cues = [m for m in CUE.finditer(q.text, max(0, first - 700), first)]
    g0 = q.lines[q.line_at(cues[-1].start())].g0 if cues else first
    g0, g1 = q.trim(g0, last)
    n = len(view["questions"])
    view["questions"] = [dict(n=1, span=_span(q, g0, g1))]
    view["answers"] = [dict(n=1, span=None, joint_with=[])]
    view["question_style"] = "single"
    rules["questions"] = f"{rules['questions']}+post_one_demand"
    rules["pairing"] = "post_single_demand_whole_reply"
    log.append(dict(field="questions", step="demand", result=f"{n} dash bullets inside the motion's demand -> one item "
                                                             f"(q {g0}-{g1}); the answer is the whole reply"))
    return True


def _reasoning_start(view, rules, q: Doc | None, a: Doc, skip, extra_rx, log) -> None:
    r = view["reasoning"]
    if not r:
        return
    r0, r1 = r["g_start"], r["g_end"]
    win0, win1 = max(0, r0 - 400), r0 + int(0.6 * (r1 - r0))
    rep = [(i, ln) for i, ln in _lines_in(a, win0, win1) if i not in skip and len(ln.text) < 120 and (
        REPRINT_H.match(ln.text) or any(rx.search(ln.text) for rx in extra_rx))]
    new, why = None, None
    if rep:
        i0, ln0 = rep[0]
        for i, ln in _lines_in(a, ln0.g1, r1):
            if i not in skip and len(ln.text) < 120 and REPLY_H.match(ln.text):
                j = _next_text_line(a, i, skip)
                if j is not None:
                    new, why = a.lines[j].g0, f"reprint heading '{ln0.text.strip()}' then reply heading '{ln.text.strip()}'"
                break
        if new is None and q is not None:
            new = _after_reprint_block(q, a, a.line_at(ln0.g1) + 1, r1, skip)
            why = f"reprint heading '{ln0.text.strip()}', then the lines that repeat the question document" if new else None
    elif q is not None:
        # no reprint heading: only a reprint of the member's WHOLE text (quoted, or set off) at the start counts; a single
        # question repeated before its answer stays part of the reply (P5 labels, post-hoc check in QA_wording.md)
        new = _after_reprint_block(q, a, a.line_at(r0), r1, skip, min_lines=3,
                                   min_chars=max(300, int(0.5 * len(q.text.strip()))))
        why = "the reply opened with a reprint of the member's whole text" if new else None
    if new is not None and r0 < new < r1 - 20:
        view["reasoning"] = _span(a, *a.trim(new, r1))
        rules["reply"] = f"{rules['reply']}+post_after_reprint"
        log.append(dict(field="reasoning", step="reprint", result=f"start moved {r0} -> {new}: {why}"))
    else:
        log.append(dict(field="reasoning", step="reprint", result="no reprinted member's text at the start of the reply"))


def _after_reprint_block(q: Doc, a: Doc, i_start: int, limit: int, skip, min_lines: int = 1, min_chars: int = 0):
    qs = _shingles(q.text)
    if not qs:
        return None
    last, n, gap, first_g = None, 0, 0, None
    for i in range(i_start, len(a.lines)):
        ln = a.lines[i]
        if ln.g0 >= limit:
            break
        if i in skip or not ln.text.strip():
            continue
        sh = _shingles(ln.text)
        if len(sh) >= 2 and len(sh & qs) / len(sh) >= 0.5:
            last, n, gap = i, n + 1, 0
            first_g = ln.g0 if first_g is None else first_g
        elif len(sh) < 2 and last is not None:  # short lines inside the reprint (headings, "Begründung", numbers)
            continue
        else:
            gap += 1
            if last is None and gap > 1 or gap > 2:
                break
    if last is None or n < min_lines or a.lines[last].g1 - first_g < min_chars:
        return None
    j = _next_text_line(a, last, skip)
    # a heading right after the reprint ("Begründung", "Stellungnahme ...") is not part of the reply
    while j is not None and (REPLY_H.match(a.lines[j].text) or REPRINT_H.match(a.lines[j].text) or
                             SECTION_NO.match(a.lines[j].text) or re.match(r"^\s*Begr[üu]ndung\b.{0,60}$", a.lines[j].text)):
        j = _next_text_line(a, j, skip)
    return a.lines[j].g0 if j is not None else None


def _closing(view, rules, a: Doc, skip, extra_rx, log) -> int | None:
    r = view["reasoning"]
    if not r:
        return None
    r0, r1 = r["g_start"], r["g_end"]
    starts = [x["span"]["g_start"] for x in view["answers"] if x["span"] and x["span"]["doc"] == "answer"]
    floor = max([r0 + int(0.4 * (r1 - r0))] + [s + 1 for s in starts if s < r1])
    end_all = len(a.text)
    cut, why = None, None
    for i, ln in _lines_in(a, floor, end_all):
        if i in skip:
            continue
        t = ln.text
        kind = None
        if len(t) < 100 and OFFICER.match(t):
            kind = "signature"
        elif DISTRIBUTION.match(t):
            kind = "distribution list"
        elif len(t) < 100 and FORMULA.match(t):
            kind = "closing formula"
        elif len(t) < 100 and ANTRAG_H.match(t):
            kind = "recommendation section"
        elif any(rx.search(t) for rx in extra_rx):
            kind = "closing (settings file)"
        if not kind:
            continue
        g = ln.g0
        j = _prev_text_line(a, i, skip, floor=a.line_at(r0))
        steps = 0
        while j is not None and steps < 3 and (_name_like(a.lines[j].text) or PLACE_DATE.match(a.lines[j].text) or
                                              SECTION_NO.match(a.lines[j].text)):
            g = a.lines[j].g0  # the signature's name line, a place-date line, the section number above the heading
            j = _prev_text_line(a, j, skip, floor=a.line_at(r0))
            steps += 1
        cut, why = g, f"{kind} at '{t.strip()[:50]}'"
        break
    if cut is None or cut >= r1 and not any(x["span"] and x["span"]["g_end"] > cut for x in view["answers"]):
        log.append(dict(field="reasoning", step="closing", result="no closing block inside the reply" if cut is None else
                        f"closing block after the reply ({why})"))
        return None
    if cut < r1:
        e = _trim_tail(a, r0, cut, skip)
        if e - r0 > 20:
            view["reasoning"] = _span(a, r0, e)
            rules["reply"] = f"{rules['reply']}+post_closing"
    n = 0
    for x in view["answers"]:
        sp = x["span"]
        if sp and sp["doc"] == "answer" and sp["g_start"] < cut < sp["g_end"]:
            e = _trim_tail(a, sp["g_start"], cut, skip)
            if e > sp["g_start"]:
                x["span"] = _span(a, sp["g_start"], e)
                x["post"] = "closing"
                n += 1
    log.append(dict(field="reasoning", step="closing", result=f"reply ends before the {why}; {n} answer(s) trimmed"))
    return cut


def _norm_words(t: str) -> str:
    from .qa.text import fold
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)  # a word hyphenated over a line break
    t = re.sub(r"(\w)- (\w)", r"\1\2", t)           # ... as OPD's stored text sometimes joins it ("Behör- den")
    return " ".join(re.findall(r"\w+", fold(t)))


def _near_question(frag: str, qtexts: list[str]) -> bool:
    """The fragment repeats a whole question but for an OCR slip or two ('lindem' for 'lindern'): >= 40 characters and a
    similarity ratio >= 0.92 to the question's text."""
    import difflib

    return len(frag) >= 40 and any(difflib.SequenceMatcher(None, frag, t).ratio() >= 0.92 for t in qtexts if t)


def _repeated_tail(view, q: Doc | None, a: Doc, log) -> None:
    """An answer that still opens with the end of its question (the frozen alignment stopped at a hyphenated word,
    'Behör- den beeinflussen? Wie in Ziff. ...'): the fragment up to the first '?' is cut when the question document
    contains it word for word, or when it repeats a whole question but for an OCR slip (_near_question)."""
    if q is None:
        return
    qn = _norm_words(q.text)
    qtexts = [re.sub(r"^\d{1,2} ", "", _norm_words(q.text[x["span"]["g_start"]:x["span"]["g_end"]]))
              for x in view["questions"] if x["span"]["doc"] == "question"]
    n = 0
    for x in view["answers"]:
        sp = x["span"]
        if not sp or sp["doc"] != "answer":
            continue
        head = a.text[sp["g_start"]:min(sp["g_end"], sp["g_start"] + 160)]
        m = re.search(r"\?[»“”\"]?", head)
        if not m:
            continue
        frag = _norm_words(head[:m.start()])
        if len(frag) < 10 or frag not in qn and not _near_question(frag, qtexts):
            continue
        g0 = sp["g_start"] + m.end()
        g0, g1 = a.trim(g0, sp["g_end"])
        if g1 - g0 > 20:
            x["span"] = _span(a, g0, g1)
            x["post"] = (x.get("post") + "+" if x.get("post") else "") + "question_tail"
            n += 1
    if n:
        log.append(dict(field="answers", step="repeated question", result=f"{n} answer(s) opened with the end of their "
                                                                          "question: cut"))


def _signature_list(q: Doc) -> tuple[list[tuple[str, int, int, int | None]], tuple[int, int] | None]:
    """[(name, g0, g1, number or None)] of the first labelled signature list, and the label span."""
    for m in LABEL.finditer(q.text):
        out = []
        pos = m.end()
        stop = min(len(q.text), pos + 3000)
        cnt = re.search(r"\(\s*\d{1,3}\s*\)", q.text[pos:stop])
        blank = re.search(r"\n[ \t]*\n", q.text[pos:stop])
        end = stop
        if cnt:
            end = min(end, pos + cnt.end())
        if blank and (not cnt or blank.start() < cnt.start()):
            end = min(end, pos + blank.start())
        seg_start = pos
        for sm in list(re.finditer(r",|;|\s+(?:und|et|e)\s+", q.text[pos:end])) + [None]:
            s = seg_start
            e = pos + sm.start() if sm else end
            raw = q.text[s:e]
            lead = LEAD_JUNK.match(raw)
            num = None
            if lead:
                mn = re.search(r"(\d{1,2})\.\s*$", lead.group(0))
                num = int(mn.group(1)) if mn else None
                s += lead.end()
            tail = TAIL_JUNK.search(q.text[s:e])
            if tail:
                e = s + tail.start()
            s, e = q.trim(s, e)
            nm = " ".join(q.text[s:e].split())
            seg_start = pos + sm.end() if sm else end
            if not nm:
                continue
            if not _name_like(nm):
                break
            out.append((nm, s, e, num))
        if out:
            return out, (m.start(), m.end())
    return [], None


def _people(view, rules, q: Doc | None, log) -> None:
    if q is None:
        return
    sig, lab = _signature_list(q)
    changed = []
    sub = view.get("submitter")
    if sig:
        numbered = sorted([x for x in sig if x[3] is not None], key=lambda x: x[3])
        ordered = numbered + [x for x in sig if x[3] is None]
        frozen_rule = rules.get("people") or "none"
        sub_in_label = bool(sub and lab and sub["span"]["doc"] == "question" and sub["span"]["g_start"] < lab[1] + 3
                            and sub["span"]["g_end"] > lab[0])
        if numbered or frozen_rule in ("signature_block", "none") or sub_in_label or not sub:
            nm, s, e, _ = ordered[0]
            rule = "post_signature_list_numbered" if numbered else "post_signature_list"
            view["submitter"] = dict(name=nm, span=_span(q, s, e), rule=rule)
            view["co_signatories"] = [dict(name=x[0], span=_span(q, x[1], x[2]), rule=rule) for x in ordered[1:]]
            rules["people"] = rule
            changed.append(f"{len(ordered)} names from the signature list '{q.text[lab[0]:lab[1]]}'"
                           + (f", {len(numbered)} numbered (no. {numbered[0][3]} is the submitter)" if numbered else ""))
        else:
            keys = {w.lower() for w in sub["name"].split() if len(w) > 2}
            co = [x for x in ordered if not keys & {w.lower() for w in x[0].split() if len(w) > 2}]
            view["co_signatories"] = [dict(name=x[0], span=_span(q, x[1], x[2]), rule="post_signature_list") for x in co]
            changed.append(f"submitter kept from rule {frozen_rule}; co-signatories from the signature list")
    # every name: no label, count or numbering in it
    for x in [view.get("submitter")] + list(view.get("co_signatories") or []):
        if not x:
            continue
        d = q if x["span"]["doc"] == "question" else None
        if d is None:
            continue
        s, e = x["span"]["g_start"], x["span"]["g_end"]
        raw = d.text[s:e]
        lead = LEAD_JUNK.match(raw)
        if lead:
            s += lead.end()
        tail = TAIL_JUNK.search(d.text[s:e])
        if tail:
            e = s + tail.start()
        s, e = d.trim(s, e)
        if (s, e) != (x["span"]["g_start"], x["span"]["g_end"]) and e > s:
            changed.append(f"'{' '.join(raw.split())}' -> '{' '.join(d.text[s:e].split())}'")
            x["name"] = " ".join(d.text[s:e].split())
            x["span"] = _span(d, s, e)
    log.append(dict(field="people", step="signature list", result="; ".join(changed) if changed else
                    "no labelled signature list; names unchanged"))


def _lex(text: str) -> str | None:
    for lab, rx in REC_LEX:
        if rx.search(text):
            return lab
    return None


def _antrag_heading(a: Doc, skip) -> tuple[str, int, int, str] | None:
    """The last 'Antrag des Regierungsrates' / 'Proposition du Conseil d'Etat' heading line followed by a short
    recommendation phrase -> (label, g0, g1, heading)."""
    found = None
    for i, ln in enumerate(a.lines):
        if i in skip or len(ln.text) > 90 or not ANTRAG_H.match(ln.text):
            continue
        j = _next_text_line(a, i, skip)
        if j is None:
            continue
        g0 = a.lines[j].g0
        seg = a.text[g0:min(len(a.text), g0 + 400)]
        m = re.search(r"[.:;](?=\s|$)|\n[ \t]*\n", seg)
        g1 = g0 + (m.start() if m else len(seg))
        g0, g1 = a.trim(g0, g1)
        lab = _lex(a.text[g0:g1])
        if lab and g1 - g0 >= 4:
            found = (lab, g0, g1, ln.text.strip())
    return found


def _recommendation(view, rules, records, a: Doc | None, a_pages, affair_type, body, settings, cov, log, review) -> dict:
    """-> {route, rule, null} (null: a TypedNull dict to put in the records instead of the rebuilt one, or None)."""
    v = view["recommendation"]
    res = dict(route="rule", rule=rules.get("recommendation"), null=None)
    if a is None or v == "not_applicable":
        return res
    sp = view.get("recommendation_span")
    if v == "accept" and sp and NICHT_ERHEBLICH.search(a.text[sp["g_start"]:sp["g_end"] + 30]):
        view["recommendation"] = "reject"
        res["rule"] = rules["recommendation"] = f"{rules['recommendation']}+post_nichterheblich"
        log.append(dict(field="recommendation", step="Nichterheblich", result="'Nichterheblicherklärung' read as accept by "
                                                                               "the frozen lexicon -> reject"))
        return res
    open_null = v == "none" and sp is None
    conflict = v is None
    specs = overlay.anchors_for(settings, body).get("recommendation") if settings else None
    if not (open_null or conflict):
        if specs and cov["status"] in ("not_covered", "user_anchors"):
            # outside the rule coverage your measured phrase beats the frozen lexicon (as in convert)
            h, tr = overlay.apply_rec_anchors(a_pages, specs, (settings or {}).get("file"))
            for t in tr:
                log.append(dict(field="recommendation", step=t["step"], result=t["result"]))
            if h:
                g0 = a.starts[h["page"] - 1] + h["char_start"]
                view["recommendation"] = h["value"]
                view["recommendation_span"] = _span(a, g0, a.starts[h["page"] - 1] + h["char_end"])
                res.update(route="user_anchor", rule=h["rule"])
                log.append(dict(field="recommendation", step="anchor over lexicon", result=(
                    f"body {cov['body']} is outside the rule coverage: your anchor {h['rule']} -> {h['value']} replaces "
                    f"the frozen {rules.get('recommendation')} -> {v}")))
                rules["recommendation"] = h["rule"]
                if h.get("needs_review"):
                    review.append(dict(field="recommendation", reason=h.get("review_reason")))
                if h["value"] != v:
                    review.append(dict(field="recommendation", reason=f"your anchor says {h['value']}, the frozen "
                                                                      f"lexicon says {v}: read the document"))
        return res
    hit = None
    if specs:
        h, tr = overlay.apply_rec_anchors(a_pages, specs, (settings or {}).get("file"))
        for t in tr:
            log.append(dict(field="recommendation", step=t["step"], result=t["result"]))
        if h:
            g0 = a.starts[h["page"] - 1] + h["char_start"]
            hit = (h["value"], g0, a.starts[h["page"] - 1] + h["char_end"], "user_anchor", h["rule"])
            if h.get("needs_review"):
                review.append(dict(field="recommendation", reason=h.get("review_reason")))
    elif settings is not None:
        log.append(dict(field="recommendation", step="user anchors", result=f"none for body {body}"))
    if hit is None and open_null:
        from .convert import rules as CR
        r = CR.recommendation(a_pages, affair_type)
        if r.get("status") == "value":
            s = r["span"]
            g0 = a.starts[s["page"] - 1] + s["char_start"]
            hit = (r["value"], g0, a.starts[s["page"] - 1] + s["char_end"], "rule", f"convert_{r['rule']}")
        log.append(dict(field="recommendation", step="convert's frozen rules",
                        result=f"{r['rule']} -> {r['value']}" if r.get("status") == "value" else "no match"))
    if hit is None:
        ah = _antrag_heading(a, boilerplate_lines(a))
        if ah:
            hit = (ah[0], ah[1], ah[2], "rule", "post_antrag_heading")
        log.append(dict(field="recommendation", step="'Antrag' heading",
                        result=f"'{ah[3]}' -> {ah[0]} ({a.text[ah[1]:ah[2]][:60]!r})" if ah else
                        "no recommendation phrase under an 'Antrag des Regierungsrates' / 'Proposition' heading"))
    if hit:
        lab, g0, g1, route, rule = hit
        view["recommendation"] = lab
        view["recommendation_span"] = _span(a, g0, g1)
        res.update(route=route, rule=rule)
        rules["recommendation"] = rule
        sent = a.text[g0:min(len(a.text), g1 + 120)]
        for rx, why in overlay.REVIEW_Q:
            if rx.search(sent):
                review.append(dict(field="recommendation", reason=f"the {lab} phrase is qualified: {why}"))
                break
        if conflict:
            review.append(dict(field="recommendation", reason="the frozen rules found conflicting recommendation "
                                                              f"sentences; {rule} chose {lab}: check it"))
        return res
    if open_null and cov["status"] not in ("covered",) and not body_settings.is_confirmed(settings, body,
                                                                                             rules.get("recommendation")):
        if cov["status"] == "unknown":
            review.append(dict(field="recommendation", reason="no recommendation sentence found, and no --body given: "
                                                              "whether the rules know this layout was not checked"))
        else:
            res["null"] = dict(kind="null", null_reason="no_rules_for_body", route="rule",
                               evidence=f"no recommendation sentence found; body {cov['body']} is not in "
                                        "rules_coverage.json", doc=a.doc_id)
            review.append(dict(field="recommendation", reason=f"no frozen rules for body {cov['body']} and none of them "
                                                              "fired: read the document or add --anchors"))
    return res


def _convert_check(view, a_pages, affair_type, cov, log, review) -> None:
    """Outside the rule coverage: convert's frozen recommendation rules run first in convert. When they read a different
    label from the same answer document than qa_cli reports, the two tools would disagree: flag it."""
    v = view["recommendation"]
    if a_pages is None or v in (None, "not_applicable") or cov["status"] not in ("not_covered", "user_anchors"):
        return
    from .convert import rules as CR
    r = CR.recommendation(a_pages, affair_type)
    if r.get("status") == "value" and r["value"] != v:
        review.append(dict(field="recommendation", reason=f"convert's frozen rule {r['rule']} reads {r['value']} "
                                                          f"(p{r['span']['page']}), qa_cli reports {v}: read the document"))
        log.append(dict(field="recommendation", step="convert check", result=f"convert's {r['rule']} -> {r['value']}: "
                                                                              "disagrees, flagged"))


# ---------------------------------------------------------------------------------------------- apply
def apply(out: dict, q_pages, a_pages, *, affair_type=None, body=None, settings=None, q_id="question",
          a_id="answer", prepared: int = 0) -> dict:
    """out: the frozen extract() result (run on prepare()d pages). q_pages / a_pages: the ORIGINAL pages (same lengths).
    Returns {view, records, rules, residue, post, review, rules_coverage}."""
    import copy

    view = copy.deepcopy(out["view"])
    rules = dict(out["rules"])
    residue = dict(out["residue"])
    q = Doc("question", q_id, q_pages) if q_pages else None
    a = Doc("answer", a_id, a_pages) if a_pages else None
    log: list[dict] = []
    review: list[dict] = []
    if prepared:
        log.append(dict(field="answers", step="section-number headings",
                        result=f"{prepared} heading(s) like '3.1 Zu Frage 1:' put on their own line (offsets unchanged)"))
    rec_rules = {it["n"]: it["answer"].get("rule") for it in out["records"]["qa_items"]}
    qi = view["recommendation"] == "not_applicable" and rules.get("recommendation") == "type_interpellation_or_question"
    if _questions_end(view, rules, q, body_settings.patterns(settings, "questions_end", body), log):
        open_n = sum(x["span"] is None for x in view["answers"])
        if open_n and residue.get("pair"):
            residue["pair"] = open_n
        else:
            residue.pop("pair", None)
    collapsed = _demand(view, rules, q, qi, affair_type, log)
    if collapsed:
        residue.pop("pair", None)
    if a is not None:
        skip = boilerplate_lines(a)
        _reasoning_start(view, rules, q, a, skip, body_settings.patterns(settings, "reprint_headings", body), log)
        _closing(view, rules, a, skip, body_settings.patterns(settings, "closing", body), log)
        _repeated_tail(view, q, a, log)
    # one item answered by the whole reply: the (corrected) reasoning span
    for x in view["answers"]:
        if view["reasoning"] and (collapsed or rec_rules.get(x["n"]) == "single_question_whole_reply"):
            x["span"] = dict(view["reasoning"])
            x["post"] = "single_demand_whole_reply" if collapsed else x.get("post")
    if view["questions"]:
        k = sum(x["span"] is not None for x in view["answers"])
        if view["reasoning"]:
            view["answer_style"] = "per_question" if k == len(view["answers"]) else ("mixed" if k else "global")
    _people(view, rules, q, log)
    _answer_title(view, rules, q, a, body_settings.flag(settings, "prefer_answer_title", body), log)
    cov = overlay.coverage(body, settings)
    rec = _recommendation(view, rules, out["records"], a, a_pages, affair_type, body, settings, cov, log, review)
    _convert_check(view, a_pages, affair_type, cov, log, review)
    if view["submitter"] is not None:
        residue.pop("submitter", None)
    if view["recommendation"] is not None:
        residue.pop("recommendation", None)
    # ---- coverage: every rule value on a body the rules were not written on needs review (as in convert)
    confirmed = []
    if cov["status"] in ("not_covered", "user_anchors"):
        fields = dict(questions=rules.get("questions"), answers=rules.get("pairing"), reasoning=rules.get("reply"),
                      people=rules.get("people"), recommendation=rules.get("recommendation"))
        for f, rule in fields.items():
            if not rule or rule in ("none", "no_question_found", "no_answer_document") or \
                    (f == "recommendation" and (view["recommendation"] == "not_applicable" or rec["null"])):
                continue
            if f == "recommendation" and rec["route"] == "user_anchor":
                continue
            if body_settings.is_confirmed(settings, body, rule):
                confirmed.append(f"{f}: {rule}")
                continue
            if not any(r["field"] == f for r in review):
                review.append(dict(field=f, reason=f"rule {rule} decided on body {cov['body']}, whose layouts "
                                                   "the rules were never written or measured on (list it under "
                                                   "confirm_rules in your --anchors file once you have checked it)"))
    if confirmed:
        log.append(dict(field="coverage", step="confirm_rules", result="confirmed for " + str(cov["body"]) + ": " +
                        ", ".join(confirmed)))
    # ---- records, rebuilt from the corrected view on the ORIGINAL text
    ans = {}
    for x in view["answers"]:
        if x["span"] is not None:
            base = "post_single_demand_whole_reply" if collapsed else (rec_rules.get(x["n"]) or "rule")
            post = f"+post_{x['post']}" if x.get("post") and not collapsed else ""
            ans[x["n"]] = dict(span=x["span"], joint_with=x.get("joint_with", []), route="rule", rule=base + post)
    prov = dict(reasoning=dict(rule=f"reply_{rules.get('reply')}"),
                recommendation=dict(route=rec["route"], rule=rec["rule"]))
    if view["recommendation"] == "not_applicable" and view.get("recommendation_span") is None:
        prov["recommendation"]["rule"] = rules.get("recommendation")
    records = X.build_records(view, q, a, ans, prov, None)
    if rec["null"]:
        from pydantic import TypeAdapter

        from .schema import schema_v0_1 as S
        records["recommendation"] = TypeAdapter(S.GovRecommendationF).validate_python(rec["null"]).model_dump(
            mode="json", exclude_none=True)
    for x in view["answers"]:
        x.pop("post", None)
    return dict(view=view, records=records, rules=rules, residue=residue, post=log, review=review, rules_coverage=cov)
