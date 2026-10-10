"""BE begin_date correction list (second deliverable for OPD, in the layout of repair_BE).

OPD confirmed (correspondence, 10 Oct 2026) that BE `begin_date` 2024-10-28 is a load timestamp, not a date of the affair,
for older affairs (mostly 2010-2013) plus about 170 BE affairs from later loads, and that the true date is the affair's
'Eingereicht' (submitted) event. This module finds both groups from the vendored census tables (affairs + events):

  load_2024_10_28      begin_date 2024-10-28 and the affair's own 'Eingereicht' event says otherwise
  begin_matches_no_event  begin_date equals none of the affair's own event dates (other load timestamps; several are Sundays)
  no_events            the affair has no events at all, so begin_date cannot be checked (flagged, no proposal)

Proposal: begin_date := the 'Eingereicht' event date when the affair has one (action `set_begin_date`); otherwise the row is
`review` with the earliest own event date as a hint. Nothing is proposed without evidence from OPD's own events.

    python -m gegenprobe.repair.be_begin_date [--out results/repair]
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
from pathlib import Path

from ..census.tables import i, rows
from ..paths import RESULTS

COLUMNS = ["body", "affair_id", "affair_number", "action", "group", "current_begin_date", "proposed_begin_date",
           "evidence", "note"]


def build() -> dict:
    aff = {r["id"]: r for r in rows("affairs") if r["body"] == "BE"}
    sub = collections.defaultdict(list)
    ev = collections.defaultdict(list)
    for e in rows("events"):
        if e["affair"] in aff and e["date"]:
            d = e["date"][:10]
            ev[e["affair"]].append((d, e["title"]))
            if e["hid"] == "1" or e["title"] == "Eingereicht":
                sub[e["affair"]].append(d)
    out = []
    for aid, a in sorted(aff.items(), key=lambda kv: kv[1]["number"]):
        b = (a["begin"] or "")[:10]
        own = {d for d, _ in ev[aid]}
        if b == "2024-10-28" and sub[aid] and b not in sub[aid]:
            group = "load_2024_10_28"
        elif not ev[aid]:
            group = "no_events"
        elif b and b not in own:
            group = "begin_matches_no_event"
        else:
            continue
        if sub[aid]:
            prop, action = min(sub[aid]), "set_begin_date"
            evidence = f"Eingereicht event {min(sub[aid])}"
        elif ev[aid]:
            first = min(ev[aid])
            prop, action, evidence = "", "review", f"no Eingereicht event; earliest own event {first[0]} ({first[1]})"
        else:
            prop, action, evidence = "", "review", "no events in OPD"
        wd = datetime.date.fromisoformat(b).strftime("%a") if b else ""
        out.append(dict(body="BE", affair_id=i(aid), affair_number=a["number"], action=action, group=group,
                        current_begin_date=b, proposed_begin_date=prop, evidence=evidence,
                        note=f"current begin_date is a {wd}" if wd in ("Sat", "Sun") else ""))
    years = collections.Counter(r["affair_number"][:4] for r in out if r["group"] == "load_2024_10_28")
    summary = dict(
        n_be_affairs=len(aff),
        flagged=len(out),
        by_group=dict(collections.Counter(r["group"] for r in out)),
        by_action=dict(collections.Counter(r["action"] for r in out)),
        later_loads=sum(r["group"] != "load_2024_10_28" for r in out),
        load_2024_10_28_number_years=dict(sorted(years.items())),
        on_weekend=sum(bool(r["note"]) for r in out),
        source="data/census/affairs.tsv.gz + events.tsv.gz (snapshot 6 Oct 2026)",
    )
    return dict(body="BE", columns=COLUMNS, n=len(out), summary=summary, rows=out)


def main(out: Path = RESULTS / "repair") -> dict:
    r = build()
    out.mkdir(parents=True, exist_ok=True)
    (out / "repair_BE_begin_date.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    with open(out / "repair_BE_begin_date.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLUMNS) + "\n")
        for row in r["rows"]:
            f.write("\t".join(str(row[c]) for c in COLUMNS) + "\n")
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=RESULTS / "repair")
    print(json.dumps(main(ap.parse_args().out)["summary"], indent=1))
