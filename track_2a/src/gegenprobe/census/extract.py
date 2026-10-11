"""Project the full OPD exports (≈6 GB streamed; metadata scan in GP_DOCS_META) onto the compact census tables that are
committed under data/census/ and replayed by `make run`.

The projection keeps raw-ish fields wherever the census applies a pattern (event titles, document names/categories, text
types), so the frozen regexes in census/defs.py are re-applied at replay time. Three things are reduced, because the raw
form would not fit the 100 MB data budget or would carry personal data:
  * document full text   -> text status, length, the three answer-marker flags (computed at scan time, census/scan.py)
  * contributors         -> per (affair, harmonised role, type) the number of distinct persons/groups (no names)
  * texts export         -> per row its type and the longest non-placeholder language version (the only predicate used)
Documents outside the answer census (not attached to an in-scope affair directly or via an agenda item, and not a BE
canton document) are aggregated to counts per (affair, body, text status, usable, language, category, meeting?, agenda?).

usage: python -m gegenprobe.census.extract [--out data/census]
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import devpaths
from ..paths import DATA, DOCS_META, OPD_RAW
from . import defs

OUT = DATA / "census"
# the canton tables: GP_BE_OGD (the nightly job passes WORK/be_ogd); development default: the recovery spike's copy
BE_OGD = Path(os.environ.get("GP_BE_OGD") or devpaths.spikes() / "recovery" / "data" / "be_ogd")
SEP = "\t"


def _clean(s) -> str:
    if s is None:
        return ""
    return re.sub(r"[\t\r\n]+", " ", str(s))


def _d(s) -> str:
    return (s or "")[:10]


class _W:
    """gzip TSV writer with header and deterministic output (mtime 0)."""

    def __init__(self, path: Path, cols: list[str]):
        self.path = path
        self.raw = open(path, "wb")
        self.gz = gzip.GzipFile(fileobj=self.raw, mode="wb", mtime=0, compresslevel=9)
        self.n = 0
        self.gz.write((SEP.join(cols) + "\n").encode())

    def row(self, *vals) -> None:
        self.gz.write((SEP.join(_clean(v) for v in vals) + "\n").encode())
        self.n += 1

    def close(self) -> int:
        self.gz.close()
        self.raw.close()
        return self.n


def _lines(p: Path):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        yield from f


def _file_info(p: Path) -> dict:
    st = p.stat()
    return dict(
        file=p.name, bytes=st.st_size, mtime=datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")
    )


def extract(out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    meta = dict(generated=datetime.now(timezone.utc).isoformat(timespec="seconds"), inputs={}, rows={})
    for name in ("affairs", "events", "agendas", "bodies", "contributors"):
        meta["inputs"][name] = _file_info(OPD_RAW / f"{name}.ndjson.gz")
    for idxname in ("index.json", "index_census_dl.json"):
        p = OPD_RAW / idxname
        if p.exists():
            idx = json.loads(p.read_text())
            meta["inputs"][idxname] = dict(
                generated_at=idx.get("generated_at"),
                created={e["entity"]: e.get("created") for e in idx["files"] if "created" in e},
            )

    # ---- bodies
    w = _W(out / "bodies.tsv.gz", ["key", "type", "name", "lang", "canton", "has_parliament"])
    for line in _lines(OPD_RAW / "bodies.ndjson.gz"):
        b = json.loads(line)
        w.row(
            b["body_key"],
            b.get("type"),
            b.get("name_de") or b.get("name"),
            b.get("lang"),
            b.get("canton_key"),
            b.get("has_parliament"),
        )
    meta["rows"]["bodies"] = w.close()

    # ---- affairs (all types; the matrix needs every type)
    be_ext = {}
    w = _W(out / "affairs.tsv.gz", ["id", "body", "type_h", "type_raw", "number", "begin", "end", "state_raw", "state_h", "ext"])
    scope_ids = set()
    for line in _lines(OPD_RAW / "affairs.ndjson.gz"):
        a = json.loads(line)
        traw = a.get("type_name_de") or a.get("type_name_fr") or a.get("type_name_it")
        sraw = a.get("state_name_de") or a.get("state_name_fr") or a.get("state_name_it")
        ext = a.get("external_id") if a["body_key"] == "BE" else ""
        if ext:
            be_ext[ext] = a["id"]
        w.row(
            a["id"],
            a["body_key"],
            a.get("type_harmonized_en"),
            traw,
            a.get("number"),
            _d(a.get("begin_date")),
            _d(a.get("end_date")),
            sraw,
            a.get("state_name_harmonized_id"),
            ext,
        )
        if a.get("type_harmonized_en") in defs.SCOPE_TYPES:
            scope_ids.add(a["id"])
    meta["rows"]["affairs"] = w.close()

    # ---- events (only those attached to an affair; title concatenated de/fr/it exactly as the funnel reads it)
    w = _W(out / "events.tsv.gz", ["affair", "date", "hid", "title", "actor"])
    n_noaff = 0
    for line in _lines(OPD_RAW / "events.ndjson.gz"):
        e = json.loads(line)
        if e.get("affair_id") is None:
            n_noaff += 1
            continue
        w.row(
            e["affair_id"],
            _d(e.get("date")),
            e.get("title_harmonized_id"),
            defs.event_title(e),
            e.get("actor_de") or e.get("actor_fr") or e.get("actor_it"),
        )
    meta["rows"]["events"] = w.close()
    meta["rows"]["events_without_affair"] = n_noaff

    # ---- documents (deduplicated by id, first occurrence in part order, as the spike funnel did)
    agenda_ids_needed = set()
    docs = []
    seen = set()
    for f in sorted(glob.glob(str(DOCS_META / "part*/docs_meta.jsonl.gz"))):
        for line in _lines(Path(f)):
            d = json.loads(line)
            if d["id"] in seen:
                continue
            seen.add(d["id"])
            docs.append(d)
            if d.get("a") is None and d.get("ag") is not None:
                agenda_ids_needed.add(d["ag"])

    w = _W(out / "agendas.tsv.gz", ["id", "affair"])
    ag2aff = {}
    for line in _lines(OPD_RAW / "agendas.ndjson.gz"):
        g = json.loads(line)
        if g["id"] in agenda_ids_needed and g.get("item_affair_id") is not None:
            ag2aff[g["id"]] = g["item_affair_id"]
            w.row(g["id"], g["item_affair_id"])
    meta["rows"]["agendas"] = w.close()

    # Documents of in-scope affairs (directly or via an agenda item) and BE documents carrying a canton uid keep their
    # name/category (the answer-document patterns are re-applied at replay). All other documents are aggregated to counts
    # per (affair, body, status, usable, language, harmonised category, meeting, agenda) -- every field the census reads.
    w = _W(
        out / "docs.tsv.gz",
        ["id", "body", "affair", "agenda", "meeting", "status", "n", "flags", "lang", "cat_h", "be_uid", "name", "cat"],
    )
    flag_bits = {k: 1 << i for i, k in enumerate(defs.TEXT_FLAGS)}
    other: dict[tuple, int] = {}
    for d in docs:
        aid = d.get("a") if d.get("a") is not None else ag2aff.get(d.get("ag"))
        uid = ""
        if d["b"] == "BE":
            m = defs.BE_UID.search(d.get("url") or "")
            uid = m.group(1) if m else ""
        if aid in scope_ids or uid:
            bits = sum(flag_bits[f] for f in d.get("fl", []))
            w.row(
                d["id"],
                d["b"],
                d.get("a") if d.get("a") is not None else "",
                d.get("ag") if d.get("ag") is not None else "",
                1 if d.get("m") else 0,
                d["st"],
                d["n"],
                bits,
                d.get("lang"),
                d.get("ch"),
                uid,
                d.get("name"),
                d.get("cat"),
            )
        else:
            k = (
                "" if d.get("a") is None else d["a"],
                d["b"],
                d["st"],
                int(d["n"] >= defs.MIN_DOC_CHARS),
                d.get("lang") or "",
                d.get("ch") or "",
                1 if d.get("m") else 0,
                0 if d.get("ag") is None else 1,
            )
            other[k] = other.get(k, 0) + 1
    meta["rows"]["docs"] = w.close()
    w = _W(out / "docs_other.tsv.gz", ["affair", "body", "status", "usable", "lang", "cat_h", "meeting", "agenda", "count"])
    for k, n in sorted(other.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        w.row(*k, n)
    meta["rows"]["docs_other"] = w.close()

    # ---- texts export (types + longest non-placeholder language version)
    w = _W(out / "texts.tsv.gz", ["id", "body", "affair", "type", "date", "maxlen"])
    seen = set()
    for f in sorted(glob.glob(str(DOCS_META / "part*/texts_meta.jsonl.gz"))):
        for line in _lines(Path(f)):
            t = json.loads(line)
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            ml = max([v for L, v in t["lens"].items() if L not in t["ph"]] or [0])
            w.row(t["id"], t["b"], t.get("a") if t.get("a") is not None else "", t.get("type"), _d(t.get("date")), ml)
    meta["rows"]["texts"] = w.close()

    # ---- contributors: counts of distinct persons/groups per (affair, harmonised role, type); names never kept
    agg: dict[tuple, set] = {}
    raw_roles: dict[tuple, int] = {}
    for line in _lines(OPD_RAW / "contributors.ndjson.gz"):
        c = json.loads(line)
        if c.get("affair_id") is None:
            continue
        k = (c["affair_id"], c.get("role_harmonized") or "", c.get("type") or "")
        who = c.get("person_id") if c.get("type") == "person" else c.get("group_id")
        agg.setdefault(k, set()).add(who if who is not None else f"x{c['id']}")
        rk = (c.get("body_key"), c.get("role_de") or c.get("role_fr") or c.get("role_it") or "", c.get("role_harmonized") or "")
        raw_roles[rk] = raw_roles.get(rk, 0) + 1
    w = _W(out / "contributors.tsv.gz", ["affair", "role_h", "type", "n"])
    for (a, r, t), s in sorted(agg.items()):
        w.row(a, r, t, len(s))
    meta["rows"]["contributors"] = w.close()
    w = _W(out / "contributor_roles.tsv.gz", ["body", "role_raw", "role_h", "rows"])
    for (b, rr, rh), n in sorted(raw_roles.items()):
        w.row(b, rr, rh, n)
    meta["rows"]["contributor_roles"] = w.close()

    # ---- BE canton OGD: answer documents and the affair table (public ids/titles only, no person fields)
    w = _W(out / "be_ogd_answers.tsv.gz", ["geschaeft_uid", "dokument_uid", "typ", "titel"])
    for d in csv.DictReader(open(BE_OGD / "dokument.csv", encoding="utf-8")):
        if d["dokument_typ_deutsch"] in defs.BE_OGD_ANSWER_TYPES:
            w.row(d["dokument_geschaeft_uid"], d["dokument_uid"], d["dokument_typ_deutsch"], d["dokument_titel"])
    meta["rows"]["be_ogd_answers"] = w.close()
    w = _W(out / "be_ogd_affairs.tsv.gz", ["geschaeft_uid", "nr", "typ"])
    for g in csv.DictReader(open(BE_OGD / "geschaeft.csv", encoding="utf-8")):
        w.row(g["geschaeft_uid"], g["geschaeft_nr"], g["geschaeft_typ_deutsch"])
    meta["rows"]["be_ogd_affairs"] = w.close()
    for name in ("dokument.csv", "geschaeft.csv"):
        meta["inputs"]["be_ogd_" + name] = _file_info(BE_OGD / name)
    meta["inputs"]["docs_meta"] = [
        _file_info(Path(f)) | dict(part=Path(f).parent.name) for f in sorted(glob.glob(str(DOCS_META / "part*/*_meta.jsonl.gz")))
    ]

    meta["sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob("*.tsv.gz"))}
    meta["secs"] = round(time.time() - t0, 1)
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    m = extract(ap.parse_args().out)
    print(json.dumps(m["rows"], indent=1), m["secs"], "s")
