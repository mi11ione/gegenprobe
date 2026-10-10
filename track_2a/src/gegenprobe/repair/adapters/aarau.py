"""Aarau (city), OPD body 4001: the Einwohnerrat's yearly "Anfragen" pages list each written question next to the
Stadtrat's answer.

  https://www.aarau.ch/politik-verwaltung/politik/einwohnerrat/anfragen-<YYYY>.html/<page id>   (2018-2025)
  https://www.aarau.ch/politik-verwaltung/politik/einwohnerrat.html/233                          (current year)
Each row links the question ("Anfrage", /public/upload/assets/<id>/<YYYY-NNN Anfrage ...>.pdf, the file OPD stores) and
the answer ("Antwort Stadtrat", /public/upload/assets/<id>/<YYYY-NNN Beantwortung ...>.pdf). The adapter keys on the
asset id of the question OPD holds and takes the answer link with the same YYYY-NNN prefix on the same page. robots.txt
disallows only /route/; the host answers 429 to quick bursts, which net.py backs off from. The answer prints "Aarau,
<date>" (= OPD's answer event) and "Beantwortung einer Anfrage". Answers OPD already holds on the affair are taken from
OPD first (in-OPD route). 2014-2017 answers are printed in the council minutes only; not covered.
"""
from __future__ import annotations

import html
import re
import urllib.parse

from . import robots
from .base import Candidate
from .inopd import HEADING as INOPD_HEADING
from .inopd import InOPD

BASE = "https://www.aarau.ch/politik-verwaltung/politik/"
PAGES = ["einwohnerrat/anfragen-2018.html/749", "einwohnerrat/anfragen-2019.html/892",
         "einwohnerrat/anfragen-2020.html/1292", "einwohnerrat/anfragen-2021.html/1588",
         "einwohnerrat/anfragen-2022.html/1955", "einwohnerrat/anfragen-2023.html/2295",
         "einwohnerrat/anfragen-2024.html/2598", "einwohnerrat/anfragen-2025.html/2922", "einwohnerrat.html/233"]
ASSET = re.compile(r'href="((?:https://www\.aarau\.ch)?/public/upload/assets/(\d+)/([^"?]+\.pdf)[^"]*)"', re.I)
PREFIX = re.compile(r"^(\d{4})-(\d+)\b")
ANSWER_FILE = re.compile(r"Beantwortung|Antwort", re.I)
HEADING = re.compile(INOPD_HEADING.pattern + r"|Beantwortung (?:einer|der) Anfrage", re.I)


class Aarau(InOPD):
    route = ("in-OPD first; else the yearly Anfragen page: the 'Antwort Stadtrat' link next to the question asset OPD "
             "holds")
    action = "fetch"

    def __init__(self):
        super().__init__("4001", label="Aarau (city)", heading=HEADING)
        self.hosts = ("www.aarau.ch", "files.openparldata.ch")
        self._index: dict[str, list[tuple[str, str, str]]] | None = None

    def index(self) -> dict[str, list[tuple[str, str, str]]]:
        """question asset id -> [(answer url, answer file name, page)] across the yearly pages (fetched once)."""
        if self._index is None:
            self._index = {}
            for page in PAGES:
                h = robots.get(BASE + page, timeout=60, tries=4).decode("utf-8", "replace")
                links = [(urllib.parse.urljoin("https://www.aarau.ch", html.unescape(u)), aid,
                          urllib.parse.unquote(name)) for u, aid, name in ASSET.findall(h)]
                for i, (_u, aid, name) in enumerate(links):
                    m = PREFIX.match(name)
                    if not m or ANSWER_FILE.search(name):
                        continue
                    ans = [(u2, n2, page) for u2, a2, n2 in links[i + 1:i + 6]
                           if n2.startswith(m.group(0)) and ANSWER_FILE.search(n2)]
                    have = self._index.setdefault(aid, [])
                    if ans and ans[0][0] not in {h[0] for h in have}:  # the current-year page repeats rows
                        have.append(ans[0])
        return self._index

    def candidates(self, x: dict, opd: list[dict]) -> list[Candidate]:
        out = super().candidates(x, opd)
        if any(c.origin == "opd_text" for c in out):
            return out
        for d in opd:
            m = re.search(r"/public/upload/assets/(\d+)/", d.get("url") or "")
            if not m:
                continue
            for u, name, page in self.index().get(m.group(1), []):
                out.append(Candidate(url=u, title=name, origin="source", source_typed_answer=True,
                                     uid=re.search(r"/assets/(\d+)/", u).group(1), meta=dict(page=BASE + page)))
        return out


ADAPTER = Aarau()
