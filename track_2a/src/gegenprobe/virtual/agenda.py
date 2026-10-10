"""Agenda ("Ordre du jour" / "Traktandenliste") -> numbered items with spans.

A meeting agenda is the one document every parliament publishes even when it publishes no affairs. Each numbered item is a
candidate virtual affair. Spans index into the page texts of the agenda document (pdftext.extract), like every other value.

Layout seen in pdftotext output (Bulle, Fribourg communes; also typical of DE "Traktanden"):
    Ordre du jour
    1. Approbation du procès-verbal de la séance du 12 décembre 2016
    2. Ratification du dépassement de crédit relatif aux travaux …
       … continuation line
    10. Divers
    AU NOM DU CONSEIL GENERAL
or with the number alone on its line and the title after a blank line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..validate.dates import find_dates

START = re.compile(r"(?im)^\s*(ordre du jour|traktanden(liste)?|ordine del giorno)\s*:?\s*$")
END = re.compile(r"(?im)^\s*(au nom du conseil|im namen des|per il consiglio|note\s*:|annexes?\s*:|beilagen\s*:)")
ITEM = re.compile(r"^\s*(\d{1,2})(?:\.(\d{1,2}))?\.?(?:\s+|$)(.*)$")
CONVENED = re.compile(r"(?is)(convoqu[ée]e? en s[ée]ance|einberufen|tagt am|convocato in seduta)(.{0,120})")


@dataclass
class Item:
    no: str                      # "5" or "5.2"
    title: str
    page: int
    char_start: int              # span of the title text (first line .. last continuation line)
    char_end: int
    lines: list[str] = field(default_factory=list)


@dataclass
class Agenda:
    meeting_date: dict | None    # {"value": ISO, "page", "char_start", "char_end", "quote"} or None
    items: list[Item]
    found_header: bool


def _meeting_date(pages: list[str]) -> dict | None:
    """The date the body is convened for: the first date after 'convoqué en séance' (else None, never the letter date)."""
    for pi, t in enumerate(pages, 1):
        m = CONVENED.search(t)
        if not m:
            continue
        win_start = m.start(2)
        for d in find_dates(t[win_start:win_start + 160]):
            s, e = win_start + d["start"], win_start + d["end"]
            # "les lundi 29 et 30 mai 2017": the sitting starts on the first day (the second is a reserve day)
            win = t[max(0, s - 40):s]
            pre = re.search(r"(\d{1,2})(?:er)?\s+et\s+(?:(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+)?$",
                            win, re.I)
            if pre:
                day = int(pre.group(1))
                iso = d["iso"][:8] + f"{day:02d}"
                s = s - (len(win) - pre.start())
                return dict(value=iso, page=pi, char_start=s, char_end=e, quote=t[s:e], rule="first_of_two_days")
            return dict(value=d["iso"], page=pi, char_start=s, char_end=e, quote=t[s:e], rule="convened_date")
    return None


HEADING = re.compile(r"(?i)(proc[eè]s.verbal de la s[ée]ance|protokoll der sitzung|verbale della seduta)")


def minutes_date(pages: list[str]) -> dict | None:
    """Date of the sitting as printed whole in the minutes' heading:
    'PROCES-VERBAL DE LA SEANCE DU CONSEIL GENERAL / DU 9 OCTOBRE 2017 – DE 19.30 H.' -> the first date within 250 chars."""
    t = pages[0] if pages else ""
    m = HEADING.search(t[:1500])
    if not m:
        return None
    ds = find_dates(t[m.end():m.end() + 250])
    if not ds:
        return None
    s, e = m.end() + ds[0]["start"], m.end() + ds[0]["end"]
    return dict(value=ds[0]["iso"], page=1, char_start=s, char_end=e, quote=t[s:e], rule="minutes_heading")


def parse(pages: list[str]) -> Agenda:
    items: list[Item] = []
    found = False
    for pi, text in enumerate(pages, 1):
        m = START.search(text)
        if m is None and not (found and items):
            continue
        found = True
        pos = m.end() if m else 0
        endm = END.search(text, pos)
        stop = endm.start() if endm else len(text)
        cur: Item | None = None
        offset = pos
        for line in text[pos:stop].split("\n"):
            ls = offset
            offset += len(line) + 1
            if not line.strip():
                continue
            im = ITEM.match(line)
            if im and (not items or _plausible_next(items[-1].no if items else None, im)):
                no = im.group(1) + (f".{im.group(2)}" if im.group(2) else "")
                rest = im.group(3).strip()
                cur = Item(no=no, title="", page=pi, char_start=-1, char_end=-1)
                items.append(cur)
                if rest:
                    s = ls + line.index(rest)
                    cur.title, cur.char_start, cur.char_end, cur.lines = rest, s, s + len(rest), [rest]
                continue
            if cur is not None:   # continuation line (or the title of a number-only line)
                s = ls + (len(line) - len(line.lstrip()))
                txt = line.strip()
                if cur.char_start < 0:
                    cur.char_start = s
                cur.char_end = s + len(txt)
                cur.title = (cur.title + " " + txt).strip()
                cur.lines.append(txt)
        if endm:
            break
    items = [i for i in items if i.title]
    return Agenda(meeting_date=_meeting_date(pages), items=items, found_header=found)


def _plausible_next(prev: str | None, im: re.Match) -> bool:
    """A numbered line is a new item only if its number continues the sequence (rejects '2017' or list numbers in titles)."""
    n = int(im.group(1))
    if prev is None:
        return n in (0, 1)
    p_main = int(prev.split(".")[0])
    if im.group(2):           # sub-item 5.1 under 5, or next sub-item
        return n == p_main or n == p_main + 1
    return n == p_main + 1 or n == p_main
