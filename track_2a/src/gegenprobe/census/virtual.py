"""The 'virtual affairs' frontier: bodies whose documents hang on meetings rather than affairs.

OPD (correspondence, 10 Oct 2026): many communes publish only per-meeting documents (minutes) and no affairs; deriving
affairs from meeting documents ('virtual affairs', numbered 'V' + start date) is part of the challenge. Per body, from the
vendored census tables: documents attached to an affair, to a meeting only, to an agenda item only, or to nothing.
Frontier = bodies with no affairs, or whose meeting-only documents outnumber affair documents (and >= 50 documents).
Separate from matrix.csv (which the replay asserts unchanged).

    python -m gegenprobe.census.virtual
"""
from __future__ import annotations

import collections
import json

from ..paths import RESULTS
from .tables import rows


def compute() -> dict:
    per = collections.defaultdict(collections.Counter)
    for d in rows("docs"):
        k = "affair" if d["affair"] else "meeting_only" if d["meeting"] == "1" else "agenda_only" if d["agenda"] == "1" \
            else "parentless"
        per[d["body"]][k] += 1
    for d in rows("docs_other"):
        c = int(d["count"])
        k = "affair" if d["affair"] else "meeting_only" if d["meeting"] == "1" else "agenda_only" if d["agenda"] == "1" \
            else "parentless"
        per[d["body"]][k] += c
    n_aff = collections.Counter(a["body"] for a in rows("affairs"))
    names = {b["key"]: b.get("name") for b in rows("bodies")}
    frontier = []
    for b, c in per.items():
        n = sum(c.values())
        if n >= 50 and (n_aff[b] == 0 or c["meeting_only"] > c["affair"]):
            frontier.append(dict(body=b, name=names.get(b), docs=n, affairs=n_aff[b], **{k: c[k] for k in
                                 ("affair", "meeting_only", "agenda_only", "parentless")}))
    frontier.sort(key=lambda x: -x["meeting_only"])
    return dict(
        definition="bodies with >= 50 documents and either no affairs or more meeting-only than affair documents",
        n_bodies=len(frontier),
        n_bodies_no_affairs=sum(x["affairs"] == 0 for x in frontier),
        meeting_only_docs=sum(x["meeting_only"] for x in frontier),
        docs=sum(x["docs"] for x in frontier),
        bodies=frontier,
        source="data/census/docs*.tsv.gz, affairs.tsv.gz, bodies.tsv.gz (snapshot 6 Oct 2026)",
    )


def main() -> dict:
    r = compute()
    (RESULTS / "census" / "virtual_affairs.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    return r


if __name__ == "__main__":
    r = main()
    print({k: v for k, v in r.items() if k != "bodies"})
    for x in r["bodies"][:15]:
        print(x)
