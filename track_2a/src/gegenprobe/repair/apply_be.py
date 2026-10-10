"""Apply plan for the two Bern lists: before-state from an OPD docs export, after-state, and guarded SQL-like statements.

Dry run only. This module never connects to OPD and never changes anything there: it reads the committed lists and an OPD
export and writes (with --out) or prints (default) a plan a data engineer applies in OPD's own tooling.

    python -m gegenprobe.repair.apply_be --docs-export docs_BE.ndjson.gz             print the plan summary (writes nothing)
    python -m gegenprobe.repair.apply_be --fetch                                     stream today's docs_BE export (one
                                                                                     polite request, ~470 MB, nothing stored;
                                                                                     GP_EXPORTS_DIR reads it from disk)
    python -m gegenprobe.repair.apply_be --docs-export ... --out DIR                  write the plan files into DIR
      [--relink results/repair/repair_BE_relink.tsv] [--begin-date results/repair/repair_BE_begin_date.tsv]
      [--affairs-export affairs.ndjson.gz]   current begin_date per affair (default: the list's 6 Oct value)
      [--hash recompute|keep]                document identifier after re-parenting (default recompute, see below)

Files written with --out:
  apply_BE_relink_plan.csv      one row per relink: before (parent_type, affair_id, agenda_id, meeting_id, hash,
                                url_oparl), after (parent_type affair, affair_id, hash, url_oparl), status
  apply_BE_begin_date_plan.csv  one row per begin_date row: before (current begin_date), after, evidence event, status
  apply_BE_plan.sql.txt         guarded UPDATE statements as text, for status `apply` rows only (never executed here)
  apply_BE_plan.json            counts, the identifier check, the inputs

OPD's document `hash` is an identifier, not a content checksum: sha256 hex of body_key + parent_type + url, no separator
(OPD, correspondence 10 Oct 2026; results/census/hash_check.json), and the file name under files.openparldata.ch/doc/<body>/.
The relink documents are stored with parent_type `agenda` (and no agenda, affair or meeting id), so re-parenting them to
their affair changes the input of the rule: after = sha256(body_key + "affair" + url). `--hash recompute` (default) writes
that value, consistent with what OPD's loader computes for an affair document, which also changes the document's public
file URL (url_oparl); `--hash keep` leaves the identifier alone (stable URL, but the hash no longer follows the rule).
Which one OPD wants is OPD's decision; both values are in the CSV. A row whose current hash does not follow the rule is
not given a recomputed hash (status `hash_rule_mismatch`, ask OPD).

Statuses (relink): apply | already_attached (the document already hangs on the listed affair) | attached_elsewhere (another
parent since the list was made: do not move it) | not_in_export (document id missing from the export) |
hash_rule_mismatch. (begin_date): apply | review (the list says review; no statement) | changed_since_list (the current
begin_date differs from the list's before-value: someone changed it; re-check) | already_set (current = proposed) |
affair_not_in_export.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import io
import json
import re
import sys
from pathlib import Path

from .. import net
from .common import OUT

EXPORT_URL = "https://files.openparldata.ch/exports/docs/docs_BE.ndjson.gz"
DOC_URL = "https://files.openparldata.ch/doc/{body}/{hash}"
RELINK = OUT / "repair_BE_relink.tsv"
BEGIN = OUT / "repair_BE_begin_date.tsv"
HEX64 = re.compile(r"[0-9a-f]{64}")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
KEEP = ("id", "body_key", "parent_type", "url", "hash", "url_oparl", "affair_id", "agenda_id", "meeting_id", "news_id")

RELINK_COLS = ["opd_doc_id", "affair_id", "affair_number", "status", "before_parent_type", "before_affair_id",
               "before_agenda_id", "before_meeting_id", "before_hash", "before_url_oparl", "hash_rule_holds",
               "after_parent_type", "after_affair_id", "after_hash", "after_url_oparl", "identifier_changes", "url",
               "source_doc_uid", "verified", "note"]
BEGIN_COLS = ["affair_id", "affair_number", "status", "before_begin_date", "before_source", "after_begin_date",
              "evidence_event_id", "evidence_event_date", "evidence_event_title", "opd_group", "list_action", "note"]


def opd_hash(body_key: str, parent_type: str, url: str) -> str:
    """OPD's document identifier: sha256 hex of body_key + parent_type + url (no separator)."""
    return hashlib.sha256(f"{body_key}{parent_type}{url}".encode()).hexdigest()


def _tsv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _lines(src: str | None, fetch: bool):
    if fetch:
        yield from net.stream_ndjson_gz(EXPORT_URL)
        return
    p = Path(src)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as f:
        yield from f


def read_docs(lines, ids: set[int], stats: dict | None = None) -> dict[int, dict]:
    """The export rows of the listed document ids (first row per id; every other row and the text are dropped).
    stats (optional) receives, over every row of the export, how many follow OPD's identifier rule, per parent_type."""
    out: dict[int, dict] = {}
    rule = collections.Counter()
    for line in lines:
        if not line.strip():
            continue
        d = json.loads(line)
        try:
            i = int(d["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if stats is not None and d.get("url") is not None and d.get("hash"):
            pt = d.get("parent_type")
            rule[(str(pt), opd_hash(d.get("body_key") or "", pt, d["url"]) == d["hash"])] += 1
        if i in ids and i not in out:
            out[i] = {k: d.get(k) for k in KEEP}
    if stats is not None:
        stats.update(rows=sum(rule.values()), follow_rule=sum(v for (_, ok), v in rule.items() if ok),
                     by_parent_type={pt: dict(rows=sum(v for (p, _), v in rule.items() if p == pt),
                                              follow_rule=rule[(pt, True)]) for pt in sorted({p for p, _ in rule})})
    return out


def read_begin_dates(path: str, ids: set[int]) -> dict[int, str]:
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            a = json.loads(line)
            if a.get("id") in ids:
                out[a["id"]] = (a.get("begin_date") or "")[:10]
    return out


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def relink_plan(rows: list[dict], docs: dict[int, dict], hash_mode: str = "recompute") -> list[dict]:
    plan = []
    for r in rows:
        did, aid = int(r["opd_doc_id"]), int(r["affair_id"])
        d = docs.get(did)
        p = dict(opd_doc_id=did, affair_id=aid, affair_number=r.get("affair_number", ""), url="",
                 source_doc_uid=r.get("source_doc_uid", ""), verified=r.get("verified", ""), note="")
        if d is None:
            plan.append(dict(p, status="not_in_export", note="document id not in this export"))
            continue
        body, pt, url, h = d.get("body_key") or "BE", d.get("parent_type"), d.get("url") or "", d.get("hash") or ""
        holds = bool(HEX64.fullmatch(h)) and opd_hash(body, pt, url) == h
        p.update(before_parent_type=pt, before_affair_id=d.get("affair_id"), before_agenda_id=d.get("agenda_id"),
                 before_meeting_id=d.get("meeting_id"), before_hash=h, before_url_oparl=d.get("url_oparl"),
                 hash_rule_holds=holds, url=url)
        cur_aff = _int(d.get("affair_id"))
        if cur_aff == aid:
            p.update(status="already_attached", after_parent_type=pt, after_affair_id=aid, after_hash=h,
                     after_url_oparl=d.get("url_oparl"), identifier_changes=False, note="nothing to do")
        elif cur_aff is not None or d.get("agenda_id") is not None or d.get("meeting_id") is not None:
            p.update(status="attached_elsewhere", note="the document has a parent now; the list's relink does not apply")
        elif hash_mode == "recompute" and not holds:
            p.update(status="hash_rule_mismatch", after_parent_type="affair", after_affair_id=aid,
                     note="current hash does not follow sha256(body_key + parent_type + url); new identifier not derivable")
        else:
            new = opd_hash(body, "affair", url) if hash_mode == "recompute" else h
            same_pattern = d.get("url_oparl") == DOC_URL.format(body=body, hash=h)
            p.update(status="apply", after_parent_type="affair", after_affair_id=aid, after_hash=new,
                     after_url_oparl=DOC_URL.format(body=body, hash=new) if same_pattern else d.get("url_oparl"),
                     identifier_changes=new != h)
        plan.append(p)
    return plan


def begin_plan(rows: list[dict], current: dict[int, str] | None) -> list[dict]:
    plan = []
    for r in rows:
        aid = int(r["affair_id"])
        listed = r.get("current_begin_date", "")
        before, src = (current.get(aid), "affairs export") if current is not None else (listed, "list (6 Oct snapshot)")
        p = dict(affair_id=aid, affair_number=r.get("affair_number", ""), before_begin_date=before or "", before_source=src,
                 after_begin_date=r.get("proposed_begin_date", ""), evidence_event_id=r.get("evidence_event_id", ""),
                 evidence_event_date=r.get("evidence_event_date", ""), evidence_event_title=r.get("evidence_event_title", ""),
                 opd_group=r.get("opd_group", ""), list_action=r.get("action", ""), note=r.get("note", ""))
        if current is not None and aid not in current:
            p["status"] = "affair_not_in_export"
        elif r.get("action") != "set_begin_date":
            p["status"] = "review"
        elif before == p["after_begin_date"]:
            p["status"] = "already_set"
        elif before != listed:
            p["status"] = "changed_since_list"
        else:
            p["status"] = "apply"
        plan.append(p)
    return plan


def _q(v) -> str:
    return "NULL" if v is None else str(int(v))


def statements(relink: list[dict], begin: list[dict]) -> list[str]:
    """Guarded UPDATEs as text: each changes a row only if it is still in its before-state. Table and column names are the
    export's (docs, affairs); map them to OPD's schema. Values are validated (ints, 64-hex, ISO dates) before they are
    written, so a malformed input row cannot inject text."""
    out = ["-- Gegenprobe apply plan for Bern (DRY RUN TEXT: generated by python -m gegenprobe.repair.apply_be, never executed",
           "-- by it). Table/column names follow the OPD export fields; adapt to OPD's schema. Run inside one transaction;",
           "-- each statement is guarded by the row's before-state and should report 1 row changed.",
           "-- Relinks: apply as a protected override until OPD's staging fix ships, or the next scrape undoes them.",
           "BEGIN;"]
    for p in relink:
        if p["status"] != "apply":
            continue
        assert HEX64.fullmatch(p["before_hash"]) and HEX64.fullmatch(p["after_hash"])
        set_hash = f", hash = '{p['after_hash']}'" if p["identifier_changes"] else ""
        out.append(f"UPDATE docs SET parent_type = 'affair', affair_id = {_q(p['affair_id'])}{set_hash} "
                   f"WHERE id = {_q(p['opd_doc_id'])} AND body_key = 'BE' AND parent_type = 'agenda' AND affair_id IS NULL "
                   f"AND agenda_id IS NULL AND meeting_id IS NULL AND hash = '{p['before_hash']}';  "
                   f"-- {p['affair_number'][:40].replace(chr(10), ' ')}")
    for p in begin:
        if p["status"] != "apply":
            continue
        assert ISO.fullmatch(p["after_begin_date"]) and ISO.fullmatch(p["before_begin_date"])
        ev = f"event {_q(p['evidence_event_id'])}" if p["evidence_event_id"] else "no event id"
        out.append(f"UPDATE affairs SET begin_date = '{p['after_begin_date']}' WHERE id = {_q(p['affair_id'])} "
                   f"AND body_key = 'BE' AND begin_date::date = '{p['before_begin_date']}';  -- Eingereicht, {ev}")
    out.append("COMMIT;")
    return out


def _rel(p) -> str:
    from ..paths import ROOT

    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def _write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else str(r.get(k)).lower() if isinstance(r.get(k), bool) else r.get(k))
                        for k in cols})


def build(args) -> dict:
    rel_rows, begin_rows = _tsv(Path(args.relink)), _tsv(Path(args.begin_date))
    ids = {int(r["opd_doc_id"]) for r in rel_rows}
    stats: dict = {}
    docs = read_docs(_lines(args.docs_export, args.fetch), ids, stats)
    current = read_begin_dates(args.affairs_export, {int(r["affair_id"]) for r in begin_rows}) if args.affairs_export else None
    rp, bp = relink_plan(rel_rows, docs, args.hash), begin_plan(begin_rows, current)
    sql = statements(rp, bp)
    found = [p for p in rp if p["status"] != "not_in_export"]
    summary = dict(
        dry_run=True,
        inputs=dict(relink=_rel(args.relink), begin_date=_rel(args.begin_date),
                    docs_export=EXPORT_URL if args.fetch else Path(args.docs_export).name,
                    affairs_export=Path(args.affairs_export).name if args.affairs_export else None, hash_mode=args.hash),
        export_identifier_rule=dict(stats, rule="hash == sha256(body_key + parent_type + url)"),
        relink=dict(rows=len(rp), by_status=dict(collections.Counter(p["status"] for p in rp)),
                    before_parent_type=dict(collections.Counter(str(p.get("before_parent_type")) for p in found)),
                    hash_rule_holds=sum(bool(p.get("hash_rule_holds")) for p in found), checked=len(found),
                    identifier_changes=sum(bool(p.get("identifier_changes")) for p in rp if p["status"] == "apply")),
        begin_date=dict(rows=len(bp), by_status=dict(collections.Counter(p["status"] for p in bp))),
        statements=len(sql) - 6,
        identifier_note=("OPD's hash is sha256(body_key + parent_type + url); the relink documents carry parent_type "
                         "'agenda', so moving them to an affair changes the hash and the files.openparldata.ch/doc URL "
                         "unless OPD keeps the old identifier (--hash keep)"),
    )
    return dict(summary=summary, relink=rp, begin=bp, sql=sql)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gegenprobe.repair.apply_be",
                                 description="Bern apply plan (dry run; never touches OPD). See the module docstring.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--docs-export", help="OPD docs export for Bern (docs_BE.ndjson.gz, or an uncompressed .ndjson)")
    src.add_argument("--fetch", action="store_true", help="stream today's docs_BE export (one polite request)")
    ap.add_argument("--relink", default=str(RELINK))
    ap.add_argument("--begin-date", default=str(BEGIN))
    ap.add_argument("--affairs-export", help="affairs.ndjson.gz: re-read each affair's current begin_date")
    ap.add_argument("--hash", choices=["recompute", "keep"], default="recompute")
    ap.add_argument("--out", metavar="DIR", help="write the plan files here (default: print the summary only)")
    a = ap.parse_args(argv)
    r = build(a)
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        _write_csv(out / "apply_BE_relink_plan.csv", RELINK_COLS, r["relink"])
        _write_csv(out / "apply_BE_begin_date_plan.csv", BEGIN_COLS, r["begin"])
        (out / "apply_BE_plan.sql.txt").write_text("\n".join(r["sql"]) + "\n", encoding="utf-8")
        (out / "apply_BE_plan.json").write_text(json.dumps(r["summary"], indent=1) + "\n", encoding="utf-8")
        print(f"plan written to {out} (dry run: nothing was changed anywhere)", file=sys.stderr)
    else:
        buf = io.StringIO()
        for line in r["sql"][:8]:
            buf.write(line + "\n")
        print("dry run (no --out): summary and the first statements; nothing was written or changed", file=sys.stderr)
        print(buf.getvalue() + "...", file=sys.stderr)
    print(json.dumps(r["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
