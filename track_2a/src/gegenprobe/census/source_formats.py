"""Which copies of an answer OPD holds, and whether one has text (offline; OPD's records only).

    python -m gegenprobe.census.source_formats [AFFAIR_ID ...]    -> results/census/source_formats_ti.json

History. Until 11 Oct 2026 this module read Ticino's atto page (www4.ti.ch/poteri/gc/ricerca-messaggi-e-atti/ricerca/…)
and opened each answer attachment (www4.ti.ch/user_librerie/php/GC/allegato.php) to read its file name. Both paths are
disallowed by www4.ti.ch's robots.txt under RFC 9309; the first-match parser net used then let the three requests of
10 Oct 2026 through (docs/incidents.md). Their result (the parliament's file names for interrogazione 100.19) is
withdrawn: OPD's records do not hold the Word attachment of that answer, so it cannot be re-sourced from OPD.

What it does now: for each affair, list the documents OPD records on it (data/census/docs.tsv.gz: id, name, text status,
length) and count OPD's copies of the answer and how many have text. No network. `attos` stays empty (no parliament page
is read), so the site prints no parliament-side spot check.
"""
from __future__ import annotations

import datetime as dt
import json
import sys

from ..paths import RESULTS
from .tables import rows

OUT = RESULTS / "census" / "source_formats_ti.json"
DEFAULT = (173406,)  # OPD affair of interrogazione 100.19 (Ticino)
ANSWER_PREFIX = "Risposta"
# the requests of 10 Oct 2026 whose result is withdrawn (kept so the robots.txt audit counts them)
WITHDRAWN_REQUESTS = [
    dict(url="https://www4.ti.ch/poteri/gc/ricerca-messaggi-e-atti/ricerca/risultati/dettaglio"
             "?user_gcparlamento_pi8%5Battid%5D=101174", request="page_read", date="2026-10-10"),
    dict(url="https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid=131008", request="headers_only", date="2026-10-10"),
    dict(url="https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid=131009", request="headers_only", date="2026-10-10"),
]


def opd_side(affair: int) -> dict:
    docs = [dict(doc_id=int(d["id"]), name=d["name"], opd_text_status=d["status"], chars=int(d["n"] or 0))
            for d in rows("docs") if d["affair"] == str(affair)]
    ans = [d for d in docs if d["name"].startswith(ANSWER_PREFIX)]
    return dict(affair=affair, opd_documents=docs, opd_answer_copies=len(ans),
                opd_answer_copies_with_text=sum(1 for d in ans if d["opd_text_status"] == "ok"))


def main(argv: list[str]) -> int:
    affairs = [int(a) for a in argv] or list(DEFAULT)
    out = dict(
        label="OPD's copies of an answer and their text status (OPD records only; no parliament page is read)",
        checked=dt.date.today().isoformat(),
        withdrawn=dict(
            date="2026-10-11",
            what="the 10 Oct 2026 spot check of Ticino's answer attachments (one atto page, two attachment headers)",
            why="www4.ti.ch robots.txt disallows /poteri/gc/ricerca-messaggi-e-atti/ricerca/ and "
                "/user_librerie/php/GC/allegato.php (RFC 9309 longest match); see docs/incidents.md and "
                "results/compliance/robots_audit_all.json",
            not_re_sourceable="OPD's records hold no Word copy of this answer; the parliament's file names are not used",
            requests=WITHDRAWN_REQUESTS),
        attos=[],
        opd=[opd_side(a) for a in affairs])
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
