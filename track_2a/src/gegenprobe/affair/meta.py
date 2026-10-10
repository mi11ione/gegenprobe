"""OPD metadata for whole-affair extraction: the affair row, its events (with OPD ids, for `source` provenance), its
contributors (public office holders' names and roles as OPD publishes them), and per-body name lists for the closed
candidate sets of the submitter pointer.

`vendor(affair_ids)` reads the raw exports in GP_OPD_RAW (.work/opd) once and writes a compact file that ships with the repo
(data/gold3/opd_meta_p3.jsonl + data/gold3/body_names_p3.json); `load()` reads it back. The persons export (which carries
contact fields) is never read: names come from the contributors export only.
"""

from __future__ import annotations

import collections
import gzip
import json
from pathlib import Path

from ..paths import DATA, OPD_RAW

META = DATA / "gold3" / "opd_meta_p3.jsonl"
NAMES = DATA / "gold3" / "body_names_p3.json"

AFFAIR_KEYS = (
    "id",
    "body_key",
    "number",
    "external_id",
    "title_de",
    "title_fr",
    "title_it",
    "type_name_de",
    "type_name_fr",
    "type_name_it",
    "type_harmonized_en",
    "type_harmonized_id",
    "state_name_de",
    "state_name_fr",
    "state_name_harmonized_id",
    "begin_date",
    "end_date",
)
EVENT_KEYS = ("id", "date", "title_de", "title_fr", "title_it", "title_harmonized_id", "actor_de", "position")
CONTRIB_KEYS = (
    "id",
    "person_id",
    "group_id",
    "type",
    "fullname",
    "firstname",
    "lastname",
    "role_de",
    "role_fr",
    "role_it",
    "role_harmonized",
    "party_harmonized_de",
    "position",
)


def _rows(name: str):
    with gzip.open(OPD_RAW / f"{name}.ndjson.gz", "rt") as f:
        for line in f:
            yield json.loads(line)


def vendor(affair_ids: set[int], bodies: set[str]) -> None:
    out = {a: dict(affair=None, events=[], contributors=[]) for a in affair_ids}
    for a in _rows("affairs"):
        if a["id"] in out:
            out[a["id"]]["affair"] = {k: a.get(k) for k in AFFAIR_KEYS}
    for e in _rows("events"):
        if e.get("affair_id") in out:
            out[e["affair_id"]]["events"].append({k: e.get(k) for k in EVENT_KEYS})
    names = collections.defaultdict(dict)
    for c in _rows("contributors"):
        if c.get("affair_id") in out:
            out[c["affair_id"]]["contributors"].append({k: c.get(k) for k in CONTRIB_KEYS})
        if c.get("body_key") in bodies and c.get("type") == "person" and c.get("lastname"):
            names[c["body_key"]][c.get("person_id") or c["fullname"]] = [c.get("firstname") or "", c["lastname"]]
    META.parent.mkdir(parents=True, exist_ok=True)
    with open(META, "w") as f:
        for a, v in sorted(out.items()):
            v["events"].sort(key=lambda e: (e["date"] or "", e["position"] or 0, e["id"]))
            v["contributors"].sort(key=lambda c: (c["position"] or 0, c["id"]))
            f.write(json.dumps(dict(affair_id=a, **v), ensure_ascii=False) + "\n")
    NAMES.write_text(
        json.dumps({b: sorted({tuple(v) for v in d.values()}) for b, d in sorted(names.items())}, ensure_ascii=False)
    )


def load(path: Path = META) -> dict[int, dict]:
    return {r["affair_id"]: r for r in map(json.loads, open(path))}


def body_names(path: Path = NAMES) -> dict[str, list[tuple[str, str]]]:
    return {b: [tuple(x) for x in v] for b, v in json.loads(path.read_text()).items()}
