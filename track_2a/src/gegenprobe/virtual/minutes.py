"""Minutes ("Procès-verbal") -> one section per agenda item, and the decision sentence of each section.

Sections are found by matching each agenda title in the minutes text (normalised token sequence of its first significant
words), in agenda order. Minutes usually repeat the agenda as a list near the top; the section heading is then the
second occurrence. Decisions are read from the section's LAST decision sentence ("Au vote, le Conseil général accepte …",
"… prend acte de la réponse …", "… n'est pas transmis …"), which is the final vote after any procedural votes.
Spans index into the minutes' page texts.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

STOP = set("""madame monsieur mme m mm messieurs mesdames de du des la le les l d au aux a et en sur pour par un une
dem der die das den des und von vom zu zur zum fur im am an""".split())
DECISION_SENT = re.compile(
    r"(?is)([^.\n]{0,220}(?:\bau vote\b|le conseil g[ée]n[ée]ral (?:accepte|approuve|adopte|ratifie|refuse|rejette|d[ée]cide|"
    r"transmet|ne transmet pas|prend acte|renvoie)|prend acte|est transmise?|n.est pas transmise?|sont transmis|"
    r"der (?:grosse )?(?:gemeinde|stadt)rat (?:genehmigt|beschliesst|lehnt|nimmt)|wird (?:genehmigt|abgelehnt|überwiesen))"
    r"(?:[^.]|\.(?![ \t]*\n|\s+[A-ZÉÈÀ«])){0,320}?\.(?=[ \t]*\n|\s+[A-ZÉÈÀ«]|\s*$))")
OUTCOME_RULES = [  # order matters: negations first
    ("rejected", re.compile(r"(?i)\b(refuse|rejette|ne transmet pas|n.est pas transmis|n.accepte pas|n.approuve pas|"
                            r"lehnt .{0,40}ab|wird abgelehnt|nicht überwiesen)")),
    ("acknowledged", re.compile(r"(?i)\b(prend acte|nimmt .{0,40}kenntnis)")),
    ("referred", re.compile(r"(?i)\b(renvoi|renvoie|zurückgewiesen)")),
    ("withdrawn", re.compile(r"(?i)\b(retir[ée]|zurückgezogen)")),
    ("adopted", re.compile(r"(?i)\b(accepte|approuve|adopte|ratifie|transmet|est transmise?|sont transmis|d[ée]cide de|"
                           r"genehmigt|beschliesst|überwiesen)")),
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s)


def _tokens_with_offsets(text: str) -> list[tuple[str, int]]:
    """(normalised token, char offset in the ORIGINAL text) — normalisation keeps one char per char for latin text."""
    out = []
    for m in re.finditer(r"[^\W_]+", text):
        t = _norm(m.group(0)).strip()
        if t:
            out.append((t, m.start()))
    return out


GENERIC = set("""decision transmission reponse conseil communal general determination approbation adoption ratification
election membre membres groupe nom depose deposee concernant relative relatif relatives relatifs demandant question questions
proposition postulat postulats motion interpellation sur la le au aux mme mm madame monsieur messieurs divers rapport
antwort beantwortung gemeinderat stadtrat postulat motion interpellation anfrage wahl genehmigung""".split())


def _key(title: str, n: int = 4) -> list[str]:
    toks = [t for t in _norm(title).split() if t not in STOP]
    specific = [t for t in toks if t not in GENERIC and len(t) > 2]
    return (specific or toks)[:n]


@dataclass
class Section:
    no: str
    start: int | None      # offset in the joined minutes text
    end: int | None
    match: str             # "heading" | "heading_after_listing" | "not_found"


def _specific_stream(tokens: list[tuple[str, int]]) -> tuple[str, list[int]]:
    """Concatenate the specific tokens (not STOP, not GENERIC, len > 2) into one string, with a char -> original offset map,
    so that 'Marie-Christine' and 'MarieChristine' both read 'mariechristine'."""
    buf, where = [], []
    for t, off in tokens:
        if t in STOP or t in GENERIC or len(t) <= 2:
            continue
        buf.append(t)
        where.extend([off] * len(t))
    return "".join(buf), where


def _find_all(stream: tuple[str, list[int]], key: list[str]) -> list[int]:
    s, where = stream
    k = "".join(key)
    if len(k) < 6:
        return []
    out, i = [], s.find(k)
    while i >= 0:
        out.append(where[i])
        i = s.find(k, i + 1)
    return out


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def sections(text: str, items) -> list[Section]:
    stream = _specific_stream(_tokens_with_offsets(text))
    occ = []
    for it in items:
        hits = []
        for n in (4, 3, 2):
            hits = _find_all(stream, _key(it.title, n))
            if hits:
                break
        occ.append(hits)
    # agenda LISTINGS (minutes often repeat the agenda once or twice near the top): a window of 4,000 chars that holds
    # occurrences of at least half of the items (min 3) is a listing region; occurrences inside it are not headings
    allocc = sorted((h, k) for k, hits in enumerate(occ) for h in hits)
    need = max(3, (len(items) + 1) // 2)
    regions = []
    for i, (h, _) in enumerate(allocc):
        inwin = [(g, j) for g, j in allocc[i:] if g < h + 4000]
        if len({j for _, j in inwin}) >= need:
            regions.append((h, max(g for g, _ in inwin) + 200))
    merged = []
    for lo, hi in sorted(regions):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))

    def dense(pos: int, k: int) -> bool:
        return any(lo <= pos <= hi for lo, hi in merged)

    out, last = [], -1
    for k, (it, hits) in enumerate(zip(items, occ)):
        free = [h for h in hits if h > last and not dense(h, k)]
        if free:
            pick, how = _line_start(text, free[0]), "heading"
            last = free[0]
        elif [h for h in hits if h > last]:
            # every remaining occurrence sits in a listing region: the LAST one is taken as the heading when it ends that
            # region (e.g. item 1 whose short section starts right after the repeated agenda)
            tail = [h for h in hits if h > last][-1]
            region = next((r for r in merged if r[0] <= tail <= r[1]), None)
            if region and not any(tail < g <= region[1] for g, j in allocc if j != k):
                pick, how = _line_start(text, tail), "listing_tail"
                last = tail
            else:
                pick, how = None, "listing_only"
        else:
            pick, how = None, "not_found"
        out.append(Section(no=it.no, start=pick, end=None, match=how))
    starts = [x.start for x in out]
    for i, sec in enumerate(out):
        if sec.start is None:
            continue
        nxt = [x for x in starts[i + 1:] if x is not None]
        sec.end = nxt[0] if nxt else len(text)
    return out


def decision(text: str, sec: Section) -> dict | None:
    """Last decision sentence of a section -> {outcome, start, end, quote, rule} (offsets in the joined text) or None."""
    if sec.start is None:
        return None
    body = text[sec.start:sec.end]
    best = None
    for m in DECISION_SENT.finditer(body):
        sent = m.group(1)
        for outcome, rx in OUTCOME_RULES:
            if rx.search(sent):
                best = dict(outcome=outcome, start=sec.start + m.start(1), end=sec.start + m.end(1),
                            quote=re.sub(r"\s+", " ", sent.strip())[:380], rule=f"minutes_{outcome}")
                break
    return best
