"""Reconcile the two Bern numbers: answers *linkable within OPD* (placement: attached + agenda + parentless-by-uid = 3,394)
vs the *relink list prepared for OPD* (2,459 relink + 49 fetch, gap affairs only). Explains every parentless answer that is not a
relink row. Needs the exports (.work) like repair.be; writes results/repair/be_reconcile.json.

    python -m gegenprobe.repair.reconcile_be
"""
from __future__ import annotations

import collections
import json

from ..census import defs, tables
from .be import NAME, gap_ids, load_ogd
from .common import OUT, canton_uid, iter_docs_meta, iter_ndjson

SCOPE = {"Interpellation", "Motion", "Postulate", "Question", "Question time"}


def main() -> dict:
    answers, geschaeft = load_ogd()
    sa = {u: [d["dokument_uid"] for d in ds] for u, ds in answers.items()}
    aff = {a["external_id"]: a for a in iter_ndjson("affairs") if a["body_key"] == "BE"}
    ag = {g["id"]: g["item_affair_id"] for g in iter_ndjson("agendas") if g["body_key"] == "BE" and g.get("item_affair_id")}
    on_aff, on_ag, orphan = set(), set(), set()
    for d in iter_docs_meta({"BE"}):
        if not NAME.search(d.get("name") or ""):
            continue
        if d["a"]:
            on_aff.add(d["a"])
        elif d["ag"] in ag:
            on_ag.add(ag[d["ag"]])
        elif not d["m"]:
            u = canton_uid(d.get("url"))
            if u:
                orphan.add(u)
    rows = json.loads((OUT / "repair_BE.json").read_text())["rows"]
    route = lambda r: r.get("proposed_action") or r["action"]  # noqa: E731  (review rows keep their route here)
    relink = {int(r["affair_id"]) for r in rows if route(r) == "relink"}
    fetch = {int(r["affair_id"]) for r in rows if route(r) == "fetch"}
    gap = set(gap_ids())
    written = collections.defaultdict(bool)
    for e in tables.rows("events"):
        if defs.classify_event(e["title"], tables.i(e["hid"])) == "written":
            written[tables.i(e["affair"])] = True
    placed = collections.Counter()
    why = collections.Counter()
    for uid, g in geschaeft.items():
        if g["geschaeft_typ_deutsch"] not in ("Interpellation", "Motion", "Postulat", "Finanzmotion") or uid not in sa:
            continue
        a = aff.get(uid)
        oid = a["id"] if a else None
        if oid and oid in on_aff:
            p = "attached"
        elif oid and oid in on_ag:
            p = "via_agenda"
        elif any(u in orphan for u in sa[uid]):
            p = "parentless"
        else:
            p = "absent"
        placed[p] += 1
        if p != "parentless":
            continue
        if oid is None:
            why["no OPD affair for the canton affair"] += 1
        elif oid in relink:
            why["in the relink list: relink"] += 1
        elif oid in fetch:
            why["in the relink list: fetch"] += 1
        elif a.get("type_harmonized_en") not in SCOPE:
            why["affair type outside the census scope"] += 1
        elif not written[oid]:
            why["no written-answer event in OPD (not counted as missing)"] += 1
        elif oid not in gap:
            why["answer text already present in OPD (other document or texts)"] += 1
        else:
            why["in the gap but not relinked (other canton document preferred)"] += 1
    linkable = placed["attached"] + placed["via_agenda"] + placed["parentless"]
    out = dict(placement=dict(placed), linkable_within_opd=linkable,
               source_answered=sum(placed.values()), parentless_breakdown=dict(why),
               relink_list=dict(relink=len(relink), fetch=len(fetch)),
               parentless_not_in_list=placed["parentless"] - len(relink),
               note="placement counts every canton-answered BE intervention; the relink list covers only affairs in "
                    "the funnel gap (written-answer event in OPD, no answer text, not repaired by OPD's agenda join)")
    (OUT / "be_reconcile.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))
