"""P4 sample: meetings of the Bulle Conseil général (OPD body 2125) for which OPD holds both the agenda ("Ordre du jour")
and the minutes ("Procès-verbal") of the SAME sitting. Bulle is on the virtual-affairs frontier (results/census/
virtual_affairs.json): all 641 of its OPD documents hang on meetings, none on an affair.

Selection (fixed before drawing): candidates = meetings with an agenda doc and a PV whose name carries the meeting's own
date; seeded draw of N_MEETINGS with SEED. The PV of a sitting is often filed under the NEXT meeting, so PVs are matched by
the date printed in their name, across all Bulle meetings.

    python -m eval.gold4.sample [--fetch]   -> data/gold4/p4_meetings.jsonl (+ PDFs/texts in .work)
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import random
import re

from gegenprobe import pdftext
from gegenprobe.paths import DATA, DOCS_META

BODY = "2125"
SEED = 20261012
N_MEETINGS = 6
MONTHS = {m: i + 1 for i, m in enumerate(["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                                          "septembre", "octobre", "novembre", "décembre"])}
PV_RX = re.compile(r"(?:proc[eè]s.verbal de la s[ée]ance (?:constitutive )?du|PV_CG_)\s*"
                   r"(\d{1,2})(?:er)?[ ._](\w+|\d{1,2})[ ._](\d{4})", re.I)


def pv_date(name: str) -> str | None:
    m = PV_RX.search(name or "")
    if not m:
        return None
    d, mo, y = m.groups()
    mo = MONTHS.get(mo.lower()) if not mo.isdigit() else int(mo)
    return f"{int(y):04d}-{mo:02d}-{int(d):02d}" if mo else None


def candidates() -> list[dict]:
    rows = [json.loads(line) for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz")))
            for line in gzip.open(f, "rt")]
    rows = [r for r in rows if str(r.get("b")) == BODY and r.get("st") == "ok"]
    by_meeting = collections.defaultdict(list)
    pv_by_date = {}
    for r in rows:
        by_meeting[r["m"]].append(r)
        d = pv_date(r.get("name") or "")
        if d:  # prefer the approved version of the minutes when both exist
            if d not in pv_by_date or "approuv" in (r.get("name") or "").lower():
                pv_by_date[d] = r
    out = []
    for m, rs in by_meeting.items():
        oj = [r for r in rs if re.search(r"ordre du jour", r.get("name") or "", re.I)]
        date = oj[0]["date"][:10] if oj else None
        if oj and date in pv_by_date:
            out.append(dict(meeting_id=m, date=date, agenda=oj[0], minutes=pv_by_date[date], n_docs=len(rs)))
    return sorted(out, key=lambda x: x["date"])


def main(fetch: bool) -> None:
    cand = candidates()
    pick = sorted(random.Random(SEED).sample(cand, N_MEETINGS), key=lambda x: x["date"])
    out = []
    for c in pick:
        rec = dict(body=BODY, meeting_id=c["meeting_id"], date=c["date"], n_docs=c["n_docs"])
        for role in ("agenda", "minutes"):
            r = c[role]
            rec[role] = dict(doc_id=r["id"], name=r.get("name"), url=r.get("url"), opd_chars=r.get("n"))
            if fetch:
                sha, path = pdftext.fetch_pdf(r["url"])
                t = pdftext.extract(sha, path)
                rec[role].update(sha256=sha, pages=len(t["pages"]), chars=sum(map(len, t["pages"])),
                                 extractor=t["extractor"], image_only=t["image_only"])
        out.append(rec)
        print(rec["date"], rec["agenda"]["doc_id"], rec["minutes"]["doc_id"], flush=True)
    (DATA / "gold4").mkdir(parents=True, exist_ok=True)
    with open(DATA / "gold4" / "p4_meetings.jsonl", "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(cand)} candidate meetings, {len(out)} drawn (seed {SEED})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    main(ap.parse_args().fetch)
