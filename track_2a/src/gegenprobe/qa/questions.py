"""Rules: the member's enumerated questions (or requests) in the question document.

An item list is a chain of line-initial markers of one kind (1. / 1) / Frage 1 / a) / bullets) numbered 1, 2, 3, ...
The chain that is preceded by a question cue ("folgende Fragen", "questions suivantes", "seguenti domande", "Der
Regierungsrat wird beauftragt", ...) and whose items carry question marks wins. A chain that starts at 2 right after a
cue gets its item 1 from the text between the cue and marker 2 (pdftotext sometimes moves "1." elsewhere). Without a
marker chain: lines after a cue that each end with "?" are an unmarked list; exactly one question sentence is `single`;
several unmarked question sentences are `running_text` (no split guessed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .text import Doc, boilerplate_lines, fold

NUM = re.compile(r"^\s*(\d{1,2})\s*[.)](?=\s|$)(?!\s*(januar|februar|märz|april|mai|juni|juli|august|september|oktober|"
                 r"november|dezember|janvier|février|mars|avril|juin|juillet|août|septembre|octobre|novembre|décembre|"
                 r"gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|dicembre)\b)", re.I)
FRAGE = re.compile(r"^\s*(?:Frage|Question|Domanda|Quesito)\s+(\d{1,2})\b\s*[:.)]?", re.I)
LET = re.compile(r"^\s*([a-k])\s*[).](?=\s)")
BUL = re.compile(r"^\s*[-–—−•▪·*]\s*(?:\s(?=\S)|$)")
CUE = re.compile(
    r"folgende[rn]?\s+Fragen|nachstehende[rn]?\s+Fragen|um\s+(die\s+)?Beantwortung|Fragen\s*:|bitte[nt]?\s+(den|die|um)|"
    r"ersuche[nt]?\s+(den|die)|wird\s+(gebeten|beauftragt|ersucht|eingeladen|aufgefordert)|beauftrage[nt]?\s+(deshalb\s+|daher\s+)?(den|die)|"
    r"werden\s+(gebeten|beauftragt|ersucht|eingeladen)|"
    r"questions?\s+suivantes|les\s+questions\s+suivantes|mes\s+questions|(ma|notre)\s+question|nos\s+questions|questions\s*:|"
    r"(est|sont)\s+(invit[ée]s?|pri[ée]s?|charg[ée]s?)|prie\s+le|invitons|demandons|demande\s+au|"
    r"seguenti\s+domande|le\s+seguenti|domande\s*:|\bchied[eo]\b|\bchiediamo\b|invita(to|ti)?\s+(il|a)|"
    r"[èe]\s+(invitato|incaricato)|si\s+chiede",
    re.I,
)
STOP = re.compile(
    r"^\s*(Begründung|Begr[üu]ndung|Développement|Motivazione|Commentaire|Conclusions|Wir danken|Ich danke|Je remercie|"
    r"Nous remercions|Que le Conseil|Merci|Ringrazi|Vi ringrazi|Si ringrazia|Per\s+[A-Z]|Signature|Nom et prénom|"
    r"Mitunterzeichn|Unterschrift|Datum|Date|\d{1,2}\.\s*\d{1,2}\.\s*\d{2,4}|[A-ZÄÖÜ][\w-]+,\s*\d{1,2}\.)",
    re.I,
)


@dataclass
class Item:
    n: int
    g0: int
    g1: int
    marker: str


@dataclass
class QResult:
    style: str  # enumerated | single | running_text | none
    items: list[Item]
    rule: str
    cue: tuple[int, int] | None


def _markers(doc: Doc, skip: set[int]):
    out = []
    for i, ln in enumerate(doc.lines):
        if i in skip:
            continue
        t = ln.text
        for kind, rx in (("frage", FRAGE), ("num", NUM), ("let", LET), ("bul", BUL)):
            m = rx.match(t)
            if m:
                if kind == "let":
                    v = ord(m.group(1).lower()) - 96
                elif kind == "bul":
                    v = 0
                else:
                    v = int(m.group(1))
                out.append(dict(kind=kind, v=v, line=i, g=ln.g0 + (len(t) - len(t.lstrip())), gm=ln.g0 + m.end()))
                break
    return out


def _chains(marks: list[dict]) -> list[list[dict]]:
    chains = []
    for kind in ("frage", "num", "let"):
        ms = [m for m in marks if m["kind"] == kind]
        for i, m in enumerate(ms):
            if m["v"] not in (1, 2):
                continue
            ch = [m]
            for x in ms[i + 1:]:
                if x["v"] == ch[-1]["v"] + 1 and x["g"] - ch[-1]["g"] < 2500:
                    ch.append(x)
                elif x["v"] == m["v"] and x["g"] > m["g"]:
                    break
            if len(ch) >= 2 or (m["v"] == 2 and len(ch) >= 1):
                chains.append(ch)
    bul = [m for m in marks if m["kind"] == "bul"]
    run: list[dict] = []
    for m in bul:
        if run and m["line"] - run[-1]["line"] > 8:
            if len(run) >= 2:
                chains.append(run)
            run = []
        run.append(m)
    if len(run) >= 2:
        chains.append([dict(r, v=i + 1) for i, r in enumerate(run)])
    return chains


def _last_end(doc: Doc, g0: int, limit: int, skip: set[int]) -> int:
    """End of the last item: through the line where its sentence ends and the next line does not continue it."""
    li = doc.line_at(g0)
    lines = doc.lines
    widths = sorted(len(x.text) for x in lines if x.text.strip()) or [80]
    typical = widths[int(len(widths) * 0.8)]
    end = lines[li].g1
    j = li
    while j < len(lines) and lines[j].g0 < limit:
        if j in skip:
            j += 1
            continue
        t = lines[j].text.strip()
        if j > li and (not t and _next_stop(lines, j, skip)):
            break
        if j > li and t and (STOP.match(t) or NUM.match(t) or FRAGE.match(t) or _namey(t) or _names_line(t)):
            break
        if t:
            end = lines[j].g1
            if j == li and (NUM.fullmatch(t) or FRAGE.fullmatch(t) or LET.fullmatch(t + " ")):
                j += 1
                continue
            if re.search(r"[?.!]\s*[«»“”\"]?\s*$", t) and (len(lines[j].text) < 0.75 * typical or _next_stop(lines, j, skip)):
                break
        j += 1
    return min(end, limit)


def _next_upper(lines, j, skip) -> bool:
    k = j + 1
    while k < len(lines) and (k in skip or not lines[k].text.strip()):
        k += 1
    return k >= len(lines) or bool(re.match(r"\s*[\W\d]*[A-ZÄÖÜÉÈÀÂÊÎÔÛÇ]", lines[k].text))


def _next_stop(lines, j, skip) -> bool:
    k = j + 1
    while k < len(lines) and (k in skip or not lines[k].text.strip()):
        k += 1
    if k >= len(lines):
        return True
    t = lines[k].text.strip()
    return bool(STOP.match(t) or _namey(t) or k - j > 1)


NAME_TOK = r"(?:[A-ZÄÖÜÉÈÀÂÊÎÔÛÇ][a-zäöüéèàâêîôûçëïß'’]+(?:-[A-ZÄÖÜÉÈ][a-zäöüéèàâêîôûçëïß'’]+)?)"
NAMEY = re.compile(rf"^\s*(?:(?:Dr\.|Prof\.)\s+)?{NAME_TOK}(?:\s+(?:von|van|de|di|da|del|dal|la|le)?\s*{NAME_TOK}){{1,3}}"
                   r"\s*(\([^)]{1,40}\))?\s*$")


def _names_line(t: str) -> bool:
    from .people import _name_line

    return "," in t and _name_line(t)


def _namey(t: str) -> bool:
    return bool(NAMEY.match(t)) and "?" not in t


def _groups_after(doc: Doc, g: int, n: int, limit: int, skip: set[int]) -> list[tuple[int, int]]:
    """Up to n line groups after g, each ending at a short line that ends a sentence (or before a stop line)."""
    lines = doc.lines
    widths = sorted(len(x.text) for x in lines if x.text.strip()) or [80]
    typical = widths[int(len(widths) * 0.8)]
    out, cur0 = [], None
    j = doc.line_at(g)
    if lines[j].g0 < g:
        j += 1
    while j < len(lines) and lines[j].g0 < limit and len(out) < n:
        t = lines[j].text.strip()
        if j in skip or not t:
            j += 1
            continue
        if STOP.match(t) or _namey(t) or NUM.match(t) or FRAGE.match(t):
            break
        if cur0 is None:
            cur0 = lines[j].g0
        if (re.search(r"\?\s*[«»“”\"]?\s*$", t) and _next_upper(lines, j, skip)) or (
                re.search(r"[?.!]\s*[«»“”\"]?\s*$", t) and (len(lines[j].text) < 0.85 * typical or _next_stop(lines, j, skip))):
            out.append((cur0, lines[j].g1))
            cur0 = None
        j += 1
    if cur0 is not None and len(out) < n:
        out.append((cur0, lines[j - 1].g1))
    return out


def _bounds(doc: Doc, ch: list[dict], marks: list[dict], cue, skip: set[int]):
    text = doc.text
    starts = [m["g"] for m in ch]
    limit = min(len(text), starts[-1] + 4000)
    own = []
    for i, m in enumerate(ch):
        a = m["g"]
        b = starts[i + 1] if i + 1 < len(ch) else _last_end(doc, m["gm"], limit, skip)
        body = text[m["gm"]:b].strip()
        own.append([a, b, bool(body)])
    # runs of marker-only items: their texts follow the run as line groups, in order
    i = 0
    while i < len(own):
        if own[i][2]:
            i += 1
            continue
        j = i + 1
        # the cluster: following markers within 3 lines whose predecessor has no text of its own
        while j < len(own) and ch[j]["line"] - ch[j - 1]["line"] <= 3 and not own[j - 1][2]:
            j += 1
        run = list(range(i, j))
        after = ch[j - 1]["gm"]
        nxt = starts[j] if j < len(ch) else limit
        groups = _groups_after(doc, after, len(run), nxt, skip)
        if len(groups) == len(run):
            for k, r in enumerate(run):
                own[r] = [groups[k][0], groups[k][1], True]
        i = j
    bounds = [(a, b) for a, b, ok in own if ok]
    if ch[0]["v"] == 2:
        lead0 = doc.lines[doc.line_at(cue[1])].g1 + 1 if cue else None
        lead = (lead0, starts[0]) if lead0 is not None and text[lead0:starts[0]].strip() else None
        if lead is None:
            stray = [m for m in marks if m["kind"] == ch[0]["kind"] and m["v"] == 1 and m["g"] > starts[-1]]
            if stray:
                m = stray[0]
                lead = (m["g"], _last_end(doc, m["gm"], min(len(text), m["g"] + 3000), skip))
        if lead is None:
            return None
        bounds.insert(0, lead)
    return bounds if len(bounds) == len(ch) + (1 if ch[0]["v"] == 2 else 0) else None


def find(doc: Doc, request: bool = False) -> QResult:
    skip = boilerplate_lines(doc)
    text = doc.text
    cues = [(m.start(), m.end()) for m in CUE.finditer(text)]
    marks = _markers(doc, skip)
    best, best_score = None, 0.0
    for ch in _chains(marks):
        starts = [m["g"] for m in ch]
        cue = max((c for c in cues if c[1] <= starts[0] and starts[0] - c[1] < 700), default=None, key=lambda c: c[1])
        if ch[0]["v"] == 2 and cue is None:
            continue
        bounds = _bounds(doc, ch, marks, cue, skip)
        if not bounds:
            continue
        n_items = len(bounds)
        qmarks = sum("?" in text[a:b] for a, b in bounds)
        score = 2.0 * qmarks + (3.0 if cue else 0.0) + 0.1 * n_items
        if qmarks / n_items < 0.5 and not cue:
            continue
        if score > best_score:
            best_score = score
            best = (ch, bounds, cue)
    if best:
        ch, bounds, cue = best
        items = [Item(i + 1, *doc.trim(a, b), marker=ch[0]["kind"]) for i, (a, b) in enumerate(bounds)]
        if len(items) >= 2 and all(it.g1 > it.g0 for it in items):
            return QResult("enumerated", items, f"marker_chain_{ch[0]['kind']}", cue)
    # unmarked list: after a cue ending with ':' consecutive line groups each ending with '?'
    for c in cues:
        ln_i = doc.line_at(c[1])
        if not doc.lines[ln_i].text.rstrip().endswith(":"):
            continue
        groups, cur0 = [], None
        j = ln_i + 1
        while j < len(doc.lines):
            if j in skip:
                j += 1
                continue
            t = doc.lines[j].text.strip()
            if not t or (cur0 is None and (NUM.fullmatch(t) or BUL.fullmatch(t))):
                if cur0 is None:
                    j += 1
                    continue
                if groups and j + 1 < len(doc.lines) and doc.lines[j + 1].text.strip():
                    j += 1
                    continue
                break
            if cur0 is None:
                if _namey(t) or STOP.match(t):
                    break
                cur0 = doc.lines[j].g0
            if t.endswith("?") or re.search(r"\?\s*[«»“”\"]?\s*$", t):
                groups.append((cur0, doc.lines[j].g1))
                cur0 = None
            j += 1
        if len(groups) >= 2:
            items = [Item(i + 1, *doc.trim(a, b), marker="line") for i, (a, b) in enumerate(groups)]
            return QResult("enumerated", items, "unmarked_question_lines", c)
    if request:
        r = _request(doc, cues, skip)
        if r:
            return r
    # single / running text: question sentences after the last cue (or in the whole text)
    region0 = cues[-1][0] if cues else 0
    region0 = max([m.end() for m in re.finditer(r"[.!?:]\s|\n\s*\n", text[:region0])], default=0)
    sents = [m for m in re.finditer(r"[^.?!:]{8,}?\?", text[region0:])]
    if len(sents) == 1:
        a, b = doc.trim(region0 + sents[0].start(), region0 + sents[0].end())
        return QResult("single", [Item(1, a, b, marker="sentence")], "single_question_sentence", cues[-1] if cues else None)
    if len(sents) >= 2:
        return QResult("running_text", [], "several_unmarked_questions", cues[-1] if cues else None)
    return _request(doc, cues, skip) or QResult("none", [], "no_question_found", None)


REQ_CUE = re.compile(r"beauftragt|beauftrage|ersucht|eingeladen|aufgefordert|wird\s+gebeten|prüft|ist\s+zu|sind\s+zu|"
                     r"invit|charg|incaricat|invitato|prie|demande", re.I)
HEADER_END = re.compile(r"eröffnet\s+am[^\n]*|eingereicht\s+am[^\n]*|d[ée]pos[ée]e?\s+le[^\n]*|presentat[ao]\s+il[^\n]*", re.I)


def _request(doc: Doc, cues, skip) -> QResult | None:
    """A motion's / postulate's demand: the paragraph with the request cue, else the first body paragraph after the header
    (up to "Begründung")."""
    text = doc.text
    for c in cues:
        if re.search(r"beauftrag|ersuch|eingeladen|aufgefordert|invit|charg|incaricat|invitato", text[c[0]:c[1]], re.I):
            ln_i = doc.line_at(c[0])
            a = doc.lines[ln_i].g0
            b = _last_end(doc, c[1], min(len(text), c[1] + 2500), skip)
            a, b = doc.trim(a, b)
            if b > a:
                return QResult("single", [Item(1, a, b, marker="request")], "request_paragraph", c)
    m = HEADER_END.search(text[:1500])
    if m:
        from .text import paragraphs

        for p in paragraphs(doc, m.end(), min(len(text), m.end() + 3000), skip):
            if re.match(r"\s*(Begründung|Développement|Motivazione)", p.text, re.I):
                break
            if len(p.text) >= 60 and REQ_CUE.search(p.text) or len(p.text) >= 60:
                e = p.g1
                mm = re.search(r"[.:]\s*(\n|$)", p.text)
                if mm:
                    e = p.g0 + mm.end()
                a, b = doc.trim(p.g0, e)
                return QResult("single", [Item(1, a, b, marker="request")], "request_first_paragraph", None)
    return None


def item_tokens(doc: Doc, it: Item) -> list[str]:
    return re.findall(r"\w{3,}", fold(doc.text[it.g0:it.g1]))
