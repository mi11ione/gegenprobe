"""Rules on the executive's answer document: where the reply starts and ends (the reasoning span), and which passage
answers which numbered question.

Reply start: the last reply cue ("wird wie folgt beantwortet", "Réponse du Conseil d'Etat", "risponde come segue", ...)
that is not the document title, else the end of the reprinted member's text, else the first body paragraph.
Reply end: the first closing formula after the start ("Im Namen des Regierungsrates", "AU NOM DU CONSEIL D'ETAT", "Per il
Consiglio di Stato", "Mitteilung an", signatures, ...), or a closing recommendation sentence.
Per-question anchors (in order of preference): answer headings ("Zu Frage 2", "Zu den Fragen 1 und 3", "Ad 2", "Réponse
à la question 2", "Domanda 2"), the member's question n reprinted in the reply, numbered paragraphs "2." matching the
question count. A repeated question after its heading is not part of the answer. A heading whose answer is empty (several
questions repeated, then one reply) is joint with the following one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .questions import Item
from .text import Doc, boilerplate_lines, fold, strip_edges

REPLY_CUE = re.compile(
    r"wie\s+folgt\s+(zu\s+)?beantwort|beantwort\w*\s+.{0,80}?wie\s+folgt|berichten\s+.{0,60}?wie\s+folgt|nimmt\s+.{0,60}?wie\s+folgt\s+Stellung|"
    r"(Antwort|Stellungnahme)\s+des\s+(Regierungsrates|Stadtrates|Gemeinderates|Regierungsrats|Stadtrats|Gemeinderats)\b|"
    r"^\s*(Antwort|Beantwortung|Stellungnahme)\s*:?\s*$|"
    r"r[ée]ponse\s+du\s+(conseil|coll[èe]ge|municipalit)|r[ée]pond\s+(comme\s+suit|de\s+la\s+mani[èe]re\s+suivante|ainsi)|"
    r"^\s*R[ÉE]PONSES?\s*:?\s*$|^\s*R[ée]ponses?\s+aux\s+questions|"
    r"risposta\s+del\s+(consiglio|municipio)|risponde\s+(come\s+segue|quanto\s+segue)|^\s*Risposte?\s*:?\s*$|"
    r"ai\s+quesiti\s+(posti|formulati)|alle\s+domande\s+(poste|formulate)|rispondiamo\s+come\s+segue|"
    r"si\s+risponde\s+(come\s+segue|quanto\s+segue|alle)",
    re.I | re.M,
)
CLOSE = re.compile(
    r"^\s*(Im\s+Namen\s+des|Namens\s+des|Mit\s+freundlichen\s+Gr[üu]ssen|Freundliche\s+Gr[üu]sse|Hochachtungsvoll|"
    r"II\.\s*Mitteilung|Mitteilung\s+an|Für\s+richtigen\s+Auszug|Vor\s+dem\s+Regierungsrat|Der\s+Staatsschreiber|"
    r"Die\s+Staatsschreiberin|Der\s+Stadtschreiber|Die\s+Stadtschreiberin|Der\s+Präsident|Die\s+Präsidentin|"
    r"AU\s+NOM\s+D|Au\s+nom\s+d|Ainsi\s+d[ée]lib[ée]r|Ainsi\s+adopt|Le\s+pr[ée]sident|La\s+pr[ée]sidente|"
    r"Le\s+chancelier|La\s+chanceli[èe]re|Le\s+secr[ée]taire|Veuillez\s+agr[ée]er|"
    r"PER\s+IL\s+(CONSIGLIO|MUNICIPIO)|Per\s+il\s+(Consiglio|Municipio)|Distinti\s+saluti|Con\s+ossequio|"
    r"Vogliate\s+gradire|Il\s+Presidente|La\s+Presidente|Il\s+Cancelliere|Il\s+Segretario)",
    re.I | re.M,
)
CLOSE_SENT = re.compile(
    r"Au\s+b[ée]n[ée]fice\s+de\s+ces\s+explications|vous\s+invite\s+à\s+prendre\s+acte|"
    r"Wir\s+bitten\s+Sie,?\s+von\s+(dieser|der)\s+(Antwort|Beantwortung)\s+Kenntnis|"
    r"Mit\s+diesen\s+Ausführungen\s+betrachten\s+wir|"
    r"Restiamo\s+a\s+disposizione|Vogliate\s+gradire",
    re.I,
)
# answer headings: (regex, kind); group "n" = first number, group "more" = further numbers
H_NUMS = r"(?P<n>\d{1,2})(?P<more>(?:\s*(?:,|und|bis|sowie|et|à|e|ed|-|–|/)\s*\d{1,2})*)"
HEADINGS = [
    (re.compile(rf"^\s*(?:Zu|Ad|Zur|Betreffend)\s+(?:den\s+|der\s+)?(?:Fragen?|Punkte?n?|Ziffern?)"
                rf"\s+{H_NUMS}\b", re.I), "zu_frage"),
    (re.compile(rf"^\s*(?:Antwort\s+(?:zu|auf)\s+)?Fragen?\s+{H_NUMS}\b", re.I), "frage"),
    (re.compile(rf"^\s*(?:R[ée]ponses?\s+(?:à\s+la\s+|aux\s+)?)?questions?\s+{H_NUMS}\b", re.I), "question"),
    (re.compile(rf"^\s*(?:Risposta\s+(?:alla\s+|alle\s+)?)?(?:domand[ae]|quesit[oi])\s+(?:n\.\s*)?{H_NUMS}\b", re.I), "domanda"),
    (re.compile(rf"^\s*(?:En\s+r[ée]ponse\s+(?:à\s+la|aux)|Concernant\s+la|Concernant\s+les|[AÀ]\s+la|S.agissant\s+de\s+la|"
                rf"Quant\s+à\s+la|Pour\s+(?:ce\s+qui\s+est\s+de\s+)?la|Relativement\s+à\s+la)"
                rf"\s+questions?\s+(?:n°\s*)?{H_NUMS}\b", re.I),
     "inline"),
    (re.compile(rf"^\s*(?:In\s+merito\s+alla|Per\s+quanto\s+riguarda\s+la|Riguardo\s+alla|Alla|Quanto\s+alla|Con\s+riferimento\s+alla)"
                rf"\s+domand[ae]\s+(?:n\.\s*)?{H_NUMS}\b", re.I), "inline"),
    (re.compile(rf"^\s*(?:Bezüglich|Betreffend|Hinsichtlich|In\s+Bezug\s+auf)\s+(?:die\s+)?Fragen?"
                rf"\s+{H_NUMS}\b", re.I), "inline"),
    (re.compile(rf"^\s*(?:ad|zu|Ad)\s+{H_NUMS}\s*[).:]", re.I), "ad"),
    (re.compile(rf"^\s*(?:Zu|Ad)\s+{H_NUMS}\s*$", re.I), "ad"),
    (re.compile(r"^\s*(?P<n>\d{1,2})\s*[.)](?=\s|$)(?P<more>)"), "num"),
    (re.compile(r"^\s*\d{1,2}\.(?P<n>\d{1,2})\.?(?=\s|$)(?P<more>)"), "subnum"),
]


@dataclass
class APassage:
    n: int
    g0: int
    g1: int
    rule: str
    joint_with: list[int] = field(default_factory=list)


@dataclass
class AResult:
    reply: tuple[int, int] | None  # reasoning span (global offsets)
    reply_rule: str
    passages: list[APassage]
    style: str  # per_question | mixed | global | no_answer
    anchor_rule: str | None


def _nums(m) -> list[int]:
    out = [int(m.group("n"))]
    more = m.group("more") or ""
    rng = re.search(r"(?:bis|à|-|–)\s*(\d{1,2})", more)
    if rng and int(rng.group(1)) > out[0] and len(re.findall(r"\d{1,2}", more)) == 1:
        return list(range(out[0], int(rng.group(1)) + 1))
    out += [int(x) for x in re.findall(r"\d{1,2}", more)]
    return sorted(set(out))


def _shingles(s: str, k: int = 4) -> set:
    w = re.findall(r"\w{2,}", fold(s))
    return {" ".join(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def reprint_block(a: Doc, q: Doc | None, skip: set[int]) -> tuple[int, int] | None:
    """The reprint of the member's text near the start of the answer: the first block of question-matching lines (gaps of
    at most 2 lines), at least 300 characters and 30% of the question document."""
    if q is None:
        return None
    qs = _shingles(q.text)
    if not qs:
        return None
    match = []
    for i, ln in enumerate(a.lines):
        sh = _shingles(ln.text)
        if len(sh) >= 3 and i not in skip:
            match.append((i, len(sh & qs) / len(sh) >= 0.6))
    first = next((k for k, (_, ok) in enumerate(match) if ok), None)
    if first is None:
        return None
    last, gap = first, 0
    for k in range(first + 1, len(match)):
        if match[k][1]:
            last, gap = k, 0
        else:
            gap += 1
            if gap > 2:
                break
    g0, g1 = a.lines[match[first][0]].g0, a.lines[match[last][0]].g1
    if g1 - g0 < max(300, 0.3 * len(q.text.strip())):
        return None
    # trailing short lines of the reprint (signature, closing quote)
    j = match[last][0] + 1
    while j < len(a.lines) and j - match[last][0] <= 3:
        t = a.lines[j].text.strip()
        if t and len(t) < 45 and not REPLY_CUE.search(t) and not any(rx.match(t) for rx, _ in HEADINGS):
            g1 = a.lines[j].g1
        elif t:
            break
        j += 1
    return g0, g1


def _is_title_cue(text: str, m) -> bool:
    return bool(re.match(r"[\s\S]{0,40}?(à\s+l|à\s+la|auf\s+die|zur|zum|all['’]|alla|sur\s+l|concernant)",
                         text[m.end():m.end() + 60], re.I)) and m.start() < 0.15 * len(text)


def reply_span(a: Doc, q: Doc | None, k: int = 0) -> tuple[tuple[int, int] | None, str]:
    skip = boilerplate_lines(a)
    text = a.text
    if len(text.strip()) < 200:
        return None, "no_text"
    rp = reprint_block(a, q, skip)
    cues = [m for m in REPLY_CUE.finditer(text) if not _is_title_cue(text, m)]
    start, rule = None, None
    if rp is not None:
        after = [m for m in cues if m.start() >= rp[0]]
        if after:
            start, rule = a.lines[a.line_at(after[0].end())].g1 + 1, "reply_cue_after_reprint"
        else:
            start, rule = rp[1] + 1, "after_reprint"
    elif cues:
        start, rule = a.lines[a.line_at(cues[0].end())].g1 + 1, "reply_cue"
    else:
        widths = sorted(len(x.text) for x in a.lines if x.text.strip()) or [80]
        typical = widths[int(len(widths) * 0.8)]
        run = 0
        for i, ln in enumerate(a.lines):
            if i in skip:
                continue
            run = run + 1 if len(ln.text.strip()) > 0.6 * typical else 0
            if run == 3:
                start, rule = a.lines[i - 2].g0, "first_body_paragraph"
                break
    if start is None or start >= len(text):
        return None, "no_reply_found"
    end = len(text)
    m = CLOSE.search(text, start)
    if m:
        end = m.start()
    m2 = CLOSE_SENT.search(text, start, end)
    if m2:
        end = m2.start()
    # a recommendation / write-off proposal in the closing part ends the reasoning
    from . import rec as _rec
    tail0 = start + int(0.6 * (end - start))
    for s0, s1 in _rec.sentences(a):
        if tail0 <= s0 < end and _rec.PROPOSE.search(text[s0:s1]) and _rec.value_of(text[s0:s1]) and s1 - s0 < 600:
            end = s0
            break
    mh = re.search(r"(?m)^\s*(Antrag|Proposition|Proposta|Conclusions?|Schlussfolgerung)\s*:?\s*$", text[tail0:end])
    if mh:
        end = tail0 + mh.start()
    g0, g1 = strip_edges(a, start, end, skip)
    if g1 - g0 < 20:
        return None, "empty_reply"
    return (g0, g1), rule


def _headings(a: Doc, g0: int, g1: int, skip: set[int]):
    out = []
    for i, ln in enumerate(a.lines):
        if ln.g0 < g0 - 1 or ln.g0 >= g1 or i in skip:
            continue
        for rx, kind in HEADINGS:
            m = rx.match(ln.text)
            if m:
                out.append(dict(kind=kind, nums=_nums(m), g=ln.g0, gm=ln.g0 + m.end(), line=i))
                break
    return out


def _chain(hs: list[dict], k: int, a: Doc | None = None, qtexts: dict | None = None) -> list[dict]:
    """Headings of one kind in document order, each question number taken once (first occurrence), numbers within 1..k.
    A bare number chain ("2.") counts only where most of its headings are followed by the reprint of question n."""
    best = []
    for kind in ("zu_frage", "frage", "question", "domanda", "inline", "ad", "num", "subnum"):
        taken, cand = set(), []
        pool = [h for h in hs if h["kind"] == kind and max(h["nums"]) <= k]
        if kind in ("num", "subnum") and a is not None and qtexts:
            # per number, prefer the occurrence followed by the reprint of question n
            def ok(h):
                qs = _shingles(qtexts.get(h["nums"][0]) or "")
                sh = _shingles(a.text[h["gm"]:h["gm"] + 300])
                return bool(qs and sh and len(sh & qs) / len(sh) >= 0.25)
            good = {h["nums"][0] for h in pool if ok(h)}
            pool = [h for h in pool if h["nums"][0] not in good or ok(h)]
        for h in pool:
            if set(h["nums"]) & taken:
                continue
            taken |= set(h["nums"])
            cand.append(h)
        cover = len(taken)
        if kind in ("num", "subnum"):
            if cover < max(2, k - 1) or a is None or not qtexts:
                continue
            if [h["nums"][0] for h in cand] != sorted(h["nums"][0] for h in cand):
                continue
            ok = 0
            for h in cand:
                qs = _shingles(qtexts.get(h["nums"][0]) or "")
                sh = _shingles(a.text[h["gm"]:h["gm"] + 300])
                ok += bool(qs and sh and len(sh & qs) / len(sh) >= 0.25)
            if ok < 0.5 * len(cand):
                continue
        if cover > sum(len(h["nums"]) for h in best):
            best = cand
    return best


def _skip_repeated(a: Doc, g: int, end: int, qtext: str | None) -> int:
    """After a heading at g: skip the reprinted question text (token alignment with the member's question; small
    differences allowed), plus a leading ':' or '?'."""
    if not qtext:
        return g
    qt = re.findall(r"\w+", fold(qtext))
    qt = [t for t in qt if not t.isdigit()] or qt
    if len(qt) < 3:
        return g
    toks = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\w+", fold(a.text[g:end])) if not m.group(0).isdigit()]
    i = j = 0
    last = None
    misses = 0
    # leading heading residue (numbers, 'frage', ':') is ignored
    while i < len(toks) and (toks[i][2] in ("frage", "fragen", "question", "domanda", "zu", "ad")):
        i += 1
    while i < len(toks) and j < len(qt):
        if toks[i][2] == qt[j]:
            last = toks[i][1]
            i += 1
            j += 1
            misses = 0
        else:
            # try to resync within a small window
            hit = None
            for di in range(0, 3):
                for dj in range(0, 3):
                    if (di or dj) and i + di < len(toks) and j + dj < len(qt) and toks[i + di][2] == qt[j + dj]:
                        hit = (di, dj)
                        break
                if hit:
                    break
            if not hit:
                break
            i += hit[0]
            j += hit[1]
            misses += 1
            if misses > 3:
                break
    if last is None or j < 0.6 * len(qt):
        return g
    pos = g + last
    m = re.match(r"[\s\d?:.!»“”\"()]*", a.text[pos:end])
    return pos + (m.end() if m else 0)


def _find_reprinted(a: Doc, g0: int, g1: int, qtext: str) -> int | None:
    """Start offset of the line in [g0, g1) where the member's question text is reprinted (first 4-gram match run)."""
    qs = _shingles(qtext)
    if len(qs) < 2:
        return None
    best = None
    for ln in a.lines:
        if ln.g0 < g0 or ln.g0 >= g1:
            continue
        sh = _shingles(ln.text)
        if len(sh) >= 2 and len(sh & qs) / len(sh) >= 0.6:
            best = ln.g0
            break
    return best


def _back_over_heading(a: Doc, g: int, skip: set[int]) -> int:
    """If the lines right before g are an answer heading or a bare marker, the anchor starts there."""
    j = a.line_at(g)
    k = j - 1
    while k >= 0 and (k in skip or not a.lines[k].text.strip()) and j - k <= 4:
        k -= 1
    if k >= 0 and j - k <= 4:
        t = a.lines[k].text
        if any(rx.match(t) for rx, _ in HEADINGS) and len(t.strip()) < 40:
            return a.lines[k].g0
    return g


def pair(a: Doc, q: Doc | None, items: list[Item], reply: tuple[int, int] | None,
         reprint_lo: int | None = None) -> tuple[list[APassage], str | None]:
    """Rule anchors for each question item inside the reply. Returns (passages, rule) — only questions with an anchor."""
    if not reply or not items:
        return [], None
    g0, g1 = reply
    skip = boilerplate_lines(a)
    k = len(items)
    qtexts = {it.n: q.text[it.g0:it.g1] if q else None for it in items}
    anchors: list[dict] = []
    rule = None
    hs = _headings(a, g0, g1, skip)
    ch = _chain(hs, k, a, qtexts)
    if sum(len(h["nums"]) for h in ch) < k:
        lo = reprint_lo if reprint_lo is not None else 0
        hs2 = _headings(a, lo, g1, skip)
        ch2 = _chain(hs2, k, a, qtexts)
        if sum(len(h["nums"]) for h in ch2) > sum(len(h["nums"]) for h in ch):
            ch = ch2
    if ch and sum(len(h["nums"]) for h in ch) >= (1 if k == 1 else 2):
        # an inline heading ("Concernant la question 6, ...") is part of the answer sentence
        anchors = [dict(nums=h["nums"], g=h["g"], body=h["g"] if h["kind"] == "inline" else h["gm"]) for h in ch]
        rule = f"heading_{ch[0]['kind']}"
    else:
        # reprinted questions in order
        pos, found = g0, []
        for it in items:
            s = _find_reprinted(a, pos, g1, qtexts[it.n] or "")
            if s is not None:
                found.append(dict(nums=[it.n], g=s, body=s))
                pos = s + 1
        if len(found) >= max(2, k - 1):
            anchors, rule = found, "reprinted_question"
    if not anchors:
        return [], None
    out: list[APassage] = []
    for an in anchors:
        an["g"] = _back_over_heading(a, an["g"], skip)
    for i, an in enumerate(anchors):
        nxt = anchors[i + 1]["g"] if i + 1 < len(anchors) else g1
        body = an["body"]
        # skip the repeated question text of every number in this heading
        for n in an["nums"]:
            body = max(body, _skip_repeated(a, body, nxt, qtexts.get(n)))
        s, e = strip_edges(a, body, nxt, skip)
        out.append(APassage(an["nums"][0], s, e, rule, joint_with=an["nums"][1:]))
        for n in an["nums"][1:]:
            out.append(APassage(n, s, e, rule, joint_with=[x for x in an["nums"] if x != n]))
    # empty passages (question repeated, answer given jointly later): joint with the next non-empty one
    out.sort(key=lambda p: (p.g0, p.n))
    for i, p in enumerate(out):
        if p.g1 - p.g0 < 3:
            nxt = next((x for x in out[i + 1:] if x.g1 - x.g0 >= 3), None)
            if nxt:
                p.g0, p.g1 = nxt.g0, nxt.g1
                p.rule += "+joint_empty"
    groups: dict[tuple[int, int], list[APassage]] = {}
    for p in out:
        if p.g1 - p.g0 >= 3:
            groups.setdefault((p.g0, p.g1), []).append(p)
    for ps in groups.values():
        ns = sorted({p.n for p in ps})
        for p in ps:
            p.joint_with = [x for x in ns if x != p.n]
    seen, res = set(), []
    for p in sorted(out, key=lambda p: p.n):
        if p.n not in seen and p.g1 - p.g0 >= 3 and 1 <= p.n <= k:
            seen.add(p.n)
            res.append(p)
    return res, rule
