"""BE begin_date correction list (second deliverable for OPD, in the layout of repair_BE).

OPD confirmed (correspondence, 10 Oct 2026) that BE `begin_date` 2024-10-28 is a load timestamp, not a date of the affair,
for older affairs (mostly 2010-2013) plus about 170 BE affairs from later loads, and that the true date is the affair's
'Eingereicht' (submitted) event. This module finds both groups from the vendored census tables (affairs + events):

  load_2024_10_28      begin_date 2024-10-28 and the affair's own 'Eingereicht' event says otherwise
  begin_matches_no_event  begin_date equals none of the affair's own event dates (other load timestamps; several are Sundays)
  no_events            the affair has no events at all, so begin_date cannot be checked (flagged, no proposal)

`group` is how a row was found; `opd_group` is the grouping OPD described and the README counts: `load_2024_10_28` (557)
and `later_load` (170 = begin_matches_no_event + no_events; none of them carries the 2024-10-28 timestamp). `action` is
what to do: `set_begin_date` (554) or `review` (173).

Proposal: begin_date := the 'Eingereicht' event date when the affair has one (action `set_begin_date`); otherwise the row is
`review` with the earliest own event date as a hint. Nothing is proposed without evidence from OPD's own events.
A proposal two or more years after the year in the affair number (e.g. 2007.RRGR.2254 -> 2011) is plausible for a
re-submitted or long-running affair but is sent to `review` rather than applied blindly.
Evidence is given as columns OPD can join on: the event id (from the raw events export, when present on this machine; the
vendored census table has no event ids), its date and its title, plus the export snapshot the row was computed from.

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

COLUMNS = ["body", "affair_id", "affair_number", "action", "group", "opd_group", "current_begin_date", "proposed_begin_date",
           "evidence_event_id", "evidence_event_date", "evidence_event_title", "snapshot", "note"]
REVIEW_YEARS = 2  # proposals this many years after the number's year go to review


def _event_ids(affair_ids: set) -> dict:
    """(affair_id, date, title) -> event id from the raw OPD events export, if it is on this machine."""
    from ..paths import OPD_RAW
    p = OPD_RAW / "events.ndjson.gz"
    if not p.exists():
        return {}
    import gzip
    out = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if str(e.get("affair_id")) in affair_ids and e.get("date"):
                t = " ".join(filter(None, [e.get("title_de"), e.get("title_fr"), e.get("title_it")]))
                out.setdefault((str(e["affair_id"]), e["date"][:10], t), e["id"])
                out.setdefault((str(e["affair_id"]), e["date"][:10], None), e["id"])
    return out


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
    from .common import snapshot
    snap = snapshot()
    eids = _event_ids(set(aff))
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
        notes = []
        if sub[aid]:
            prop, action = min(sub[aid]), "set_begin_date"
            ev_date, ev_title = prop, "Eingereicht"
            ny = a["number"][:4]
            if ny.isdigit() and int(prop[:4]) - int(ny) >= REVIEW_YEARS:
                action = "review"
                notes.append(f"proposed date is {int(prop[:4]) - int(ny)} years after the number's year; check before applying")
        elif ev[aid]:
            first = min(ev[aid])
            prop, action, ev_date, ev_title = "", "review", first[0], first[1]
            notes.append("no Eingereicht event; earliest own event given as a hint")
        else:
            prop, action, ev_date, ev_title = "", "review", "", ""
            notes.append("no events in OPD")
        wd = datetime.date.fromisoformat(b).strftime("%a") if b else ""
        if wd in ("Sat", "Sun"):
            notes.append(f"current begin_date is a {wd}")
        eid = (eids.get((aid, ev_date, ev_title)) or eids.get((aid, ev_date, None))) if ev_date else None
        opd_group = "load_2024_10_28" if group == "load_2024_10_28" else "later_load"
        out.append(dict(body="BE", affair_id=i(aid), affair_number=a["number"], action=action, group=group,
                        opd_group=opd_group, current_begin_date=b, proposed_begin_date=prop, evidence_event_id=eid or "",
                        evidence_event_date=ev_date, evidence_event_title=ev_title, snapshot=snap, note="; ".join(notes)))
    years = collections.Counter(r["affair_number"][:4] for r in out if r["group"] == "load_2024_10_28")
    summary = dict(
        n_be_affairs=len(aff),
        flagged=len(out),
        by_group=dict(collections.Counter(r["group"] for r in out)),
        by_action=dict(collections.Counter(r["action"] for r in out)),
        later_loads=sum(r["group"] != "load_2024_10_28" for r in out),
        by_opd_group=dict(collections.Counter(r["opd_group"] for r in out)),
        load_2024_10_28_number_years=dict(sorted(years.items())),
        on_weekend=sum("current begin_date is a" in r["note"] for r in out),
        review_years_after_number=sum("years after the number" in r["note"] for r in out),
        with_event_id=sum(bool(r["evidence_event_id"]) for r in out),
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
