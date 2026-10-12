"""What OPD's metadata already holds, put into the converter's v0.2 records (post hoc, no model, no document text).

    python -m gegenprobe.schema.v0_2_meta vendor   read OPD's exports (GP_OPD_RAW: affairs, events, bodies; the snapshot of
                                                   the census) once and write the compact slice data/schema/v0_2_meta_slice.json
                                                   (the affair rows and events of the converter's records and of P11's NI
                                                   affairs, and the bodies' executive names); network: none
    (the overlay runs inside `python -m gegenprobe.schema.v0_2_parts`, i.e. `make schema-v02`, from the committed slice)

The records of gegenprobe.schema.v0_2_all (frozen under LOCKFED/LOCKP11, not edited) leave fields open that OPD's own
metadata fills. `with_metadata` fills them in the carrier layer, each value with route/basis `metadata` and `source`
naming the OPD record, and never replaces a value:
  * type.harmonised `unknown` -> the type OPD harmonises (its `type_harmonized_id`, mapped by data/schema/affair_types.json
    `opd_harmonised_ids`). The converter maps OPD's English labels, and OPD's labels "Question" and "Government affairs" are
    not in its table ("written question", "government business"), so 33 written questions and the federal ones read
    `unknown`. type.opd_harmonised_id is set with it.
  * decision: a typed null (not_extracted / not_in_corpus) -> OPD's last decision event (data/schema/opd_event_titles.json,
    the converter's own EVENT_MAP); for the federal Curia Vista events, which carry no harmonised title, the last event whose
    title starts with a decision word (CURIA_DECISIONS); else, for an interpellation or a question (affair_post's
    NO_DECISION_TYPES), the typed null `not_applicable` as the converter writes it.
  * procedural_state: a typed null -> OPD's last state event (EVENT_MAP), or the federal `Erledigt` event (closed).
  * qa[].answering_body (`not_extracted` in all 120 records): the body's executive as OPD's bodies export names it
    (`executive_name`, else `executive_name_<language>`), else the actor OPD's events give the executive's own step (the
    Federal Council's statement, Vernier's `Conseil administratif`), else the committed table data/schema/body_executives.json
    (one row: the Confederation, whose executive OPD's bodies export does not name). Not filled where OPD's own answer event
    names another actor (a committee): there the typed null stays, with that evidence.
  * P5 only (its assembly carries no OPD event): the submission date and OPD's answer event in `dates`, and OPD's answer
    event as qa[0].answer_date (the converter's metadata fallback, role unsplit), as the P3/P3b product records carry them.
Every change is listed in `extraction.notes` (one sentence) and returned; `strip_metadata` undoes the overlay exactly
(tests/test_schema_v0_2_meta.py).
"""
from __future__ import annotations

import copy
import gzip
import json
import re
import sys

from ..paths import DATA, OPD_RAW

SLICE = DATA / "schema" / "v0_2_meta_slice.json"
TABLE = DATA / "schema" / "body_executives.json"
OVERLAY = "gegenprobe.schema.v0_2_meta.with_metadata"
NOTE_HEAD = f"OPD metadata filled by {OVERLAY}"
EVENT_KEYS = ("id", "date", "title_de", "title_fr", "title_it", "title_harmonized_id", "actor_de", "actor_fr", "actor_it",
              "position")
AFFAIR_KEYS = ("id", "body_key", "number", "type_harmonized_en", "type_harmonized_id", "type_name_de", "type_name_fr",
               "type_name_it", "begin_date")
BODY_KEYS = ("id", "body_key", "name", "lang", "executive_name", "executive_name_de", "executive_name_fr",
             "executive_name_it", "executive_wikidata_id")
# federal (Curia Vista) event titles OPD carries without a harmonised id: title prefix -> decision outcome
CURIA_DECISIONS = (("Annahme", "adopted"), ("Ablehnung", "rejected"), ("Abgeschrieben", "written_off"),
                   ("Zurückgezogen", "withdrawn"))
CURIA_CLOSED = "Erledigt"
NOT_EXECUTIVE_ACTOR = re.compile(r"^(Kommission|Parlament|Grosser Rat|Kantonsrat|Landrat|Nationalrat|Ständerat)\b", re.I)
EXECUTIVE_ACTOR = re.compile(r"Bundesrat|Conseil administratif|Conseil municipal|Municipalit|Municipio|Stadtrat|"
                             r"Gemeinderat|Regierungsrat|Conseil d.[ÉE]tat|Consiglio di Stato", re.I)
ANSWER_HIDS = (6, 76)


# ----------------------------------------------------------------------------------------------------------- vendor
def _rows(name: str):
    with gzip.open(OPD_RAW / f"{name}.ndjson.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def wanted() -> tuple[set[int], set[str]]:
    """The OPD affair ids and body keys of the converter's records (P3, P3b, P5, federal) and of P11's NI affairs."""
    from .p8_v0_2 import OUT

    ids, bodies = set(), set()
    for k in ("p3", "p3b", "p5", "fed"):
        for line in (OUT / f"{k}_records.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                ids.add(int(r["ref"]["opd_id"]))
                bodies.add(r["body"]["key"])
    for line in (DATA / "p11" / "p11_affairs.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["cell"] == "ni":
                ids.add(int(r["affair_id"]))
                bodies.add(r["body"])
    return ids, bodies


def vendor() -> dict:
    ids, bodies = wanted()
    aff = {a: dict(affair=None, events=[]) for a in ids}
    for a in _rows("affairs"):
        if a["id"] in aff:
            aff[a["id"]]["affair"] = {k: a.get(k) for k in AFFAIR_KEYS}
    for e in _rows("events"):
        if e.get("affair_id") in aff:
            aff[e["affair_id"]]["events"].append({k: e.get(k) for k in EVENT_KEYS})
    for v in aff.values():
        v["events"].sort(key=lambda e: (e["date"] or "", e["position"] or 0, e["id"]))
    bod = {b["body_key"]: {k: b.get(k) for k in BODY_KEYS} for b in _rows("bodies") if b.get("body_key") in bodies}
    out = dict(source=("OPD's nightly exports affairs, events, bodies (GP_OPD_RAW; the census snapshot, hashes in "
                       "eval/prereg/LOCK and results/census): the rows of the converter's v0.2 records and P11's NI "
                       "affairs; written by `python -m gegenprobe.schema.v0_2_meta vendor`"),
               affairs={str(a): aff[a] for a in sorted(aff)}, bodies=dict(sorted(bod.items())))
    SLICE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return dict(affairs=len(aff), with_row=sum(v["affair"] is not None for v in aff.values()),
                events=sum(len(v["events"]) for v in aff.values()), bodies=len(bod))


def load() -> dict:
    return json.loads(SLICE.read_text(encoding="utf-8"))


def table() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))["bodies"]


# ----------------------------------------------------------------------------------------------------------- overlay
def _meta(value, source: str, **kw) -> dict:
    return dict(kind="value", value=value, basis="metadata", route="metadata", source=source, **kw)


def _types_by_hid() -> dict[int, str]:
    t = json.loads((DATA / "schema" / "affair_types.json").read_text(encoding="utf-8"))
    out = {}
    for x in t:
        for h in x.get("opd_harmonised_ids") or []:
            out.setdefault(int(h), x["key"])
    return out


def _event_map() -> dict:
    return {e["opd_id"]: e["maps_to"] for e in json.loads((DATA / "schema" / "opd_event_titles.json")
                                                          .read_text(encoding="utf-8"))}


def _open(v: dict | None) -> bool:
    """A field OPD's metadata may fill: absent, or a typed null the converter did not establish from a document."""
    return not v or (v.get("kind") == "null" and v.get("null_reason") in ("not_extracted", "not_in_corpus"))


def _title(e: dict) -> str:
    return " ".join(filter(None, (e.get("title_de"), e.get("title_fr"), e.get("title_it"))))


def _actor(e: dict) -> tuple[str | None, str | None]:
    """(OPD's actor of the event, its field): actor_de, else actor_fr, else actor_it."""
    for k in ("actor_de", "actor_fr", "actor_it"):
        if e.get(k):
            return e[k], k
    return None, None


def answering_body(rec: dict, m: dict, bodies: dict, tab: dict) -> tuple[dict | None, str]:
    """(the answering body as a metadata value, or None; why). OPD's answer event naming a non-executive actor wins."""
    key = rec["body"]["key"]
    evs = (m or {}).get("events") or []
    ans = [e for e in evs if e.get("title_harmonized_id") in ANSWER_HIDS and _actor(e)[0]]
    other = [e for e in ans if NOT_EXECUTIVE_ACTOR.match(_actor(e)[0])]
    if other:
        e = other[-1]
        return None, (f"OPD's answer event opd:events/{e['id']} names {_actor(e)[0]!r} as its actor, not the executive: "
                      "the answering body is left open")
    b = bodies.get(key) or {}
    if b.get("executive_name"):
        return _meta(b["executive_name"], f"opd:bodies/{b['id']}#executive_name"), "opd_bodies"
    exe = [e for e in evs if _actor(e)[0] and EXECUTIVE_ACTOR.search(_actor(e)[0])
           and not NOT_EXECUTIVE_ACTOR.match(_actor(e)[0])]
    if exe:
        e = exe[-1]
        name, field = _actor(e)
        return _meta(name, f"opd:events/{e['id']}#{field}"), "opd_events"
    for lg in [b.get("lang", "") or "", *(rec["body"].get("languages") or [])]:
        lg = lg.lower()
        if lg and b.get(f"executive_name_{lg}"):
            return _meta(b[f"executive_name_{lg}"], f"opd:bodies/{b['id']}#executive_name_{lg}"), "opd_bodies"
    t = tab.get(key)
    if t:
        return _meta(t["name"], f"gegenprobe:data/schema/body_executives.json#{key}"), "table"
    return None, f"OPD's bodies export names no executive for body {key} and no OPD event names one"


def _decision(rec: dict, m: dict, emap: dict) -> tuple[dict | None, str | None]:
    evs = (m or {}).get("events") or []
    dc = [e for e in evs if "decision" in emap.get(e.get("title_harmonized_id"), {})]
    if dc:
        e = dc[-1]
        return _meta(emap[e["title_harmonized_id"]]["decision"], f"opd:events/{e['id']}"), "opd_event"
    if rec["body"]["key"] == "CHE":
        cd = [(e, out) for e in evs if not e.get("title_harmonized_id") for p, out in CURIA_DECISIONS
              if (e.get("title_de") or "").startswith(p)]
        if cd:
            e, out = cd[-1]
            return _meta(out, f"opd:events/{e['id']}"), "curia_title"
    return None, None


def _state(rec: dict, m: dict, emap: dict) -> dict | None:
    evs = (m or {}).get("events") or []
    st = [e for e in evs if "state" in emap.get(e.get("title_harmonized_id"), {})]
    if st:
        e = st[-1]
        return _meta(emap[e["title_harmonized_id"]]["state"], f"opd:events/{e['id']}")
    if rec["body"]["key"] == "CHE":
        cl = [e for e in evs if not e.get("title_harmonized_id") and (e.get("title_de") or "").startswith(CURIA_CLOSED)]
        if cl:
            return _meta("closed", f"opd:events/{cl[-1]['id']}")
    return None


def with_metadata(rec: dict, sl: dict, set_name: str, tab: dict | None = None) -> tuple[dict, list[dict]]:
    """The record with the open fields OPD's metadata fills (module docstring) and the list of changes."""
    from ..affair_post import NO_DECISION_TYPES
    from ..census import defs

    rec = copy.deepcopy(rec)
    tab = table() if tab is None else tab
    m = sl["affairs"].get(str(rec["ref"].get("opd_id")))
    a = (m or {}).get("affair") or {}
    emap = _event_map()
    changes: list[dict] = []
    t = rec["type"]
    if t.get("harmonised") == "unknown" and a.get("type_harmonized_id") is not None:
        k = _types_by_hid().get(int(a["type_harmonized_id"]))
        if k:
            t["harmonised"] = k
            t["opd_harmonised_id"] = int(a["type_harmonized_id"])
            changes.append(dict(field="type.harmonised", was="unknown", now=k,
                                source=f"opd:affairs/{a['id']}#type_harmonized_id={a['type_harmonized_id']}"))
    if _open(rec.get("procedural_state")):
        v = _state(rec, m, emap)
        if v is None and m and (rec.get("procedural_state") or {}).get("null_reason") == "not_extracted":
            v = dict(kind="null", null_reason="not_in_corpus", route="metadata",
                     evidence=f"OPD records no state event for this affair (opd:affairs/{rec['ref']['opd_id']})")
        if v:
            changes.append(dict(field="procedural_state", was=_desc(rec.get("procedural_state")), now=_desc(v),
                                source=v.get("source")))
            rec["procedural_state"] = v
    if _open(rec.get("decision")):
        v, how = _decision(rec, m, emap)
        if v is None and t.get("harmonised") in NO_DECISION_TYPES:
            v = dict(kind="null", null_reason="not_applicable", route="metadata",
                     evidence=f"affair type {t['harmonised']} ({t.get('source_label')}): parliament takes no decision on it")
        elif v is None and m and (rec.get("decision") or {}).get("null_reason") == "not_extracted":
            v = dict(kind="null", null_reason="not_in_corpus", route="metadata",
                     evidence=f"OPD records no decision event for this affair (opd:affairs/{rec['ref']['opd_id']})")
        if v is not None:
            changes.append(dict(field="decision", was=_desc(rec.get("decision")), now=_desc(v), source=v.get("source")))
            rec["decision"] = v
    if set_name == "p5" and m:
        _p5_dates(rec, m, defs, changes)
    bodies = sl["bodies"]
    for i, q in enumerate(rec.get("qa") or []):
        if not (q.get("answer_doc") or q.get("answer_text_ref")) or not _open(q.get("answering_body")):
            continue
        v, how = answering_body(rec, m, bodies, tab)
        if v is not None:
            changes.append(dict(field=f"qa.{i}.answering_body", was=_desc(q.get("answering_body")), now=v["value"],
                                source=v["source"], via=how))
            q["answering_body"] = v
        else:
            q["answering_body"] = dict(q.get("answering_body") or {}, evidence=how)
            changes.append(dict(field=f"qa.{i}.answering_body", was=_desc(q.get("answering_body")), now="unchanged",
                                reason=how))
    filled = [c for c in changes if c.get("now") != "unchanged"]
    if changes:
        ex = rec["extraction"]
        note = (f"{NOTE_HEAD}: " + (", ".join(f"{c['field']} ({c.get('source') or c['now']})" for c in filled) or "nothing")
                + " (route metadata, no value replaced)")
        ex["notes"] = f"{ex['notes']}; {note}" if ex.get("notes") else note
    return rec, changes


def _desc(v: dict | None) -> str:
    if not v:
        return "absent"
    return f"value {v['value']}" if v.get("kind") == "value" else f"null {v.get('null_reason')}"


def _p5_dates(rec: dict, m: dict, defs, changes: list[dict]) -> None:
    """P5's assembly carries no OPD event: the submission and the answer event as the P3/P3b records carry them."""
    from ..affair.extract import BE_LOAD_DATE, SUBMITTED_HIDS

    a, evs = m.get("affair") or {}, m.get("events") or []
    roles = {d["role"] for d in rec.get("dates") or [] if d["date"].get("route") == "metadata"}
    sub = sorted((e for e in evs if e.get("title_harmonized_id") in SUBMITTED_HIDS and e.get("date")),
                 key=lambda e: e["date"])
    new = []
    if "submitted" not in roles:
        if sub:
            new.append(dict(role="submitted", date=_meta(sub[0]["date"][:10], f"opd:events/{sub[0]['id']}")))
        elif a.get("begin_date") and not (a.get("body_key") == "BE" and a["begin_date"][:10] == BE_LOAD_DATE):
            new.append(dict(role="submitted", date=_meta(a["begin_date"][:10], f"opd:affairs/{a['id']}#begin_date")))
    ans = sorted((e for e in evs if e.get("date") and defs.classify_event(_title(e), e.get("title_harmonized_id"))
                  == "written"), key=lambda e: e["date"])
    if ans and "answered" not in roles:
        new.append(dict(role="answered", label="OPD answer event",
                        date=_meta(ans[0]["date"][:10], f"opd:events/{ans[0]['id']}")))
    if new:
        rec["dates"] = new + (rec.get("dates") or [])
        rec.get("empty_reasons", {}).pop("dates", None)
        for d in new:
            changes.append(dict(field=f"dates[{d['role']}]", was="absent", now=d["date"]["value"],
                                source=d["date"]["source"]))
    q = (rec.get("qa") or [None])[0]
    if q is not None and ans and _open(q.get("answer_date")):
        changes.append(dict(field="qa.0.answer_date", was=_desc(q.get("answer_date")), now=ans[0]["date"][:10],
                            source=f"opd:events/{ans[0]['id']}"))
        q["answer_date"] = _meta(ans[0]["date"][:10], f"opd:events/{ans[0]['id']}")


def strip_metadata(rec: dict, before: dict) -> dict:
    """Undo with_metadata given the record before it (the overlay keeps a record otherwise identical): for the test."""
    rec = copy.deepcopy(rec)
    for k in ("type", "procedural_state", "decision", "dates", "qa"):
        rec[k] = copy.deepcopy(before.get(k)) if k in before else rec.pop(k, None)
    if "dates" in (before.get("empty_reasons") or {}):
        rec["empty_reasons"]["dates"] = before["empty_reasons"]["dates"]
    # the answer-date roles (gegenprobe.schema.v0_2_dates) run after this overlay and read the dates it fills: their
    # sentence is the one of the record before it
    from .v0_2_dates import NOTE_HEAD as DATES_HEAD
    ex = rec["extraction"]
    ex["notes"] = "; ".join([x for x in (ex.get("notes") or "").split("; ")
                             if not x.startswith((NOTE_HEAD, DATES_HEAD))]
                            + [x for x in (before["extraction"].get("notes") or "").split("; ")
                               if x.startswith(DATES_HEAD)])
    return rec


def main(argv: list[str]) -> int:
    if argv[:1] == ["vendor"]:
        print(json.dumps(vendor(), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
