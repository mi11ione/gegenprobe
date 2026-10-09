"""In-corpus repair, all bodies: answer documents that OPD files under an agenda item (affair_id null) whose agenda row
points to the affair (`agendas.item_affair_id`). No network: a join OPD can run on its own tables.

Only affairs the funnel counts as a gap are listed (written-answer event, no answer text attached), so every row closes a
gap. Definitions are census.funnel's (same tables in data/census/, same answer-document rule).

usage: python -m gegenprobe.repair.agenda    -> results/repair/repair_<BODY>.{tsv,json} rows with action agenda_join
"""

from __future__ import annotations

import collections
import sys

from ..census import defs
from ..census.funnel import compute, flags_of
from ..census.tables import i, rows
from .common import OUT, dump


def build() -> tuple[dict[str, list[dict]], dict]:
    _, aff = compute()
    want = {aid for aid, x in aff.items() if x["ev_w"] and not (x["dAt"] or x["tA"]) and x["gAt"]}
    ag2aff = {int(g["id"]): int(g["affair"]) for g in rows("agendas")}
    by_body: dict[str, list[dict]] = collections.defaultdict(list)
    seen = set()
    for d in rows("docs"):
        a, ag = i(d["affair"]), i(d["agenda"])
        if a is not None or ag not in ag2aff:
            continue
        aid = ag2aff[ag]
        if aid not in want or aid in seen:
            continue
        if not (
            defs.is_answer_doc(d["name"], d["cat"], flags_of(int(d["flags"])))
            and d["status"] == "ok"
            and int(d["n"]) >= defs.MIN_DOC_CHARS
        ):
            continue
        seen.add(aid)
        x = aff[aid]
        by_body[x["b"]].append(
            dict(
                body=x["b"],
                affair_id=aid,
                affair_number=x["num"],
                action="agenda_join",
                opd_doc_id=int(d["id"]),
                source_doc_uid=None,
                source_doc_title=d["name"],
                source_url=None,
                checks=dict(agenda_id=ag, text_status=d["status"], text_chars=int(d["n"])),
                verified=None,
                note="answer document filed under an agenda item that points to this affair (agendas.item_affair_id)",
            )
        )
    stats = dict(affairs=len(seen), by_body={b: len(v) for b, v in sorted(by_body.items())})
    return by_body, stats


def main(argv: list[str]) -> int:
    by_body, stats = build()
    dump(OUT / "agenda_join.json", dict(stats, rows=[r for v in by_body.values() for r in v]))
    print(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
