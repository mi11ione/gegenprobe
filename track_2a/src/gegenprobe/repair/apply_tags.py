"""Apply plan for the adapter lists' tag rows: before-state from OPD's docs exports, guarded SQL-like statements.

Dry run only, like repair.apply_be: this module never connects to OPD's database and never changes anything there. It
reads the committed adapter lists and OPD docs exports and writes (with --out) or prints (default) a plan that a data
engineer applies in OPD's own tooling.

Rows: every adapter-list row (results/repair/adapters/adapters_<BODY>.tsv) with counted=true and action
  tag_answer   OPD holds the answer document with its text; set its category_harmonized to response_text
  extract_tag  OPD holds the answer document without text (image-only scan); set the category now, extract the text with
               OPD's own OCR (the list's text_sha256 is the hash of OUR tesseract output: no guard for OPD's text)

    python -m gegenprobe.repair.apply_tags --exports-dir DIR [--out DIR]   docs exports on disk: DIR/docs_<BODY>.ndjson.gz or
                                                                          DIR/docs/docs_<BODY>.ndjson.gz (OPD's layout)
    python -m gegenprobe.repair.apply_tags --fetch [--out DIR]             stream each body's docs export (one polite request
                                                                          per body; GP_EXPORTS_DIR reads them from disk)
    python -m gegenprobe.repair.apply_tags --cache [--out DIR]             development: WORK/adapters/opd_docs (the adapters'
                                                                          own snapshot of the target affairs' documents)
      [--bodies 261,NE] [--lists DIR] [--actions tag_answer,extract_tag]

Files written with --out:
  apply_tags_plan.csv       one row per listed document: the before-state read from the export (affair_id,
                            category_harmonized, text length and sha256, url), the list's values, status, the guard used
  apply_tags_plan.sql.txt   guarded UPDATE statements as text, for status `apply` rows only (never executed here)
  apply_tags_plan.json      counts per body, action and status; the inputs

Guards (every statement changes a row only if it is still in the state the list was checked against):
  tag_answer   id, body_key, affair_id, category_harmonized IS NULL, sha256(text) = the list's text_sha256 (rows the
               adapter checked on OPD's own text, extractor=opd_export). Rows checked on our own extraction of the same
               file (e.g. ZH, pdftotext of the PDF OPD links; the list's hash is of that text): url = the list's
               source_url and sha256(text) = OPD's text as read from this export
  extract_tag  id, body_key, affair_id, category_harmonized IS NULL, the document still has no text, url unchanged

Statuses: apply | already_tagged (category_harmonized is response_text already) | category_set (another category is set:
not overwritten; ask the scraper owner) | affair_changed (the document hangs on another affair now) | text_changed
(tag_answer: OPD's text no longer has the hash the list was checked on) | text_now_present (extract_tag: OPD has text for
the document now; re-run the adapter on it) | not_in_export.

Protected override: several scrapers set category_harmonized themselves (e.g. NE recording_video, TI protocol;
docs/adapters.md). A value set by hand can be overwritten by the next scrape unless OPD protects it. Apply these
statements as a protected override, as for the Bern relinks.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

from .. import net
from ..paths import RESULTS, WORK
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

LISTS = RESULTS / "repair" / "adapters"
EXPORT_URL = "https://files.openparldata.ch/exports/docs/docs_{body}.ndjson.gz"
CACHE = WORK / "adapters" / "opd_docs"
TARGET = "response_text"
ACTIONS = ("tag_answer", "extract_tag")
HEX64 = re.compile(r"[0-9a-f]{64}")
BODY = re.compile(r"[A-Za-z0-9]{1,16}")
KEEP = ("id", "body_key", "affair_id", "category_harmonized", "url")
PLAN_COLS = ["body", "affair_id", "affair_number", "opd_doc_id", "list_action", "status", "guard",
             "before_affair_id", "before_category_harmonized", "before_text_chars", "before_text_sha256",
             "list_text_sha256", "text_hash_matches", "before_url", "after_category_harmonized", "source_url", "note"]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def list_rows(lists: Path = LISTS, bodies: set[str] | None = None, actions=ACTIONS) -> list[dict]:
    """counted=true rows of the given actions from every adapter list (header-only lists contribute nothing)."""
    out = []
    for p in sorted(lists.glob("adapters_*.tsv")):
        body = p.stem[len("adapters_"):]
        if bodies and body not in bodies:
            continue
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if r.get("counted") == "true" and r.get("action") in actions:
                    out.append(r)
    return out


def read_docs(lines, ids: set[int], body: str) -> dict[int, dict]:
    """Export rows of the listed document ids: the fields the guard needs, plus the text's length and sha256 (the text
    itself is dropped)."""
    out: dict[int, dict] = {}
    for line in lines:
        if not line.strip():
            continue
        d = json.loads(line)
        try:
            i = int(d["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if i in ids and i not in out:
            text = d.get("text") or ""
            row = {k: d.get(k) for k in KEEP}
            row["body_key"] = row.get("body_key") or body
            row.update(text_chars=len(text), text_sha256=_sha(text) if text else "")
            out[i] = row
    return out


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def opd_text_checked(r: dict) -> bool:
    """The adapter checked OPD's own stored text (extractor=opd_export): the list's text_sha256 is the hash of that text."""
    return "extractor=opd_export" in (r.get("check_detail") or "")


def plan_rows(rows: list[dict], docs: dict[tuple[str, int], dict]) -> list[dict]:
    plan = []
    for r in rows:
        body, did, aid, act = r["body"], int(r["opd_doc_id"]), int(r["affair_id"]), r["action"]
        h = r.get("text_sha256") or ""
        p = dict(body=body, affair_id=aid, affair_number=r.get("affair_number", ""), opd_doc_id=did, list_action=act,
                 list_text_sha256=h, after_category_harmonized=TARGET, source_url=r.get("source_url", ""), note="")
        d = docs.get((body, did))
        if d is None:
            plan.append(dict(p, status="not_in_export", note="document id not in this export"))
            continue
        cat = d.get("category_harmonized")
        p.update(before_affair_id=d.get("affair_id"), before_category_harmonized=cat, before_text_chars=d["text_chars"],
                 before_text_sha256=d["text_sha256"], before_url=d.get("url") or "",
                 text_hash_matches=bool(d["text_sha256"]) and d["text_sha256"] == h)
        if _int(d.get("affair_id")) != aid:
            p.update(status="affair_changed", note="the document hangs on another affair (or none) now")
        elif cat == TARGET:
            p.update(status="already_tagged", note="nothing to do")
        elif cat not in (None, ""):
            p.update(status="category_set", note=f"category_harmonized is '{cat}': not overwritten (scraper-set or "
                                                  "hand-set); ask the scraper owner")
        elif act == "tag_answer" and not p["text_hash_matches"] and not opd_text_checked(r):
            # checked on our own extraction of the same file (e.g. ZH: pdftotext of the PDF OPD links): the list's hash
            # is of that text, so the guard is the file (url) plus OPD's text as read now
            if (r.get("source_url") or "") == p["before_url"] and d["text_sha256"]:
                p.update(status="apply", guard="url_and_export_text_sha256",
                         note="checked on our extraction of the same file (list text_sha256 is of that text); guard: url + "
                              "OPD's text as in this export")
            else:
                p.update(status="text_changed", note="checked on our own extraction of a different file; re-run the "
                                                     "adapter")
        elif act == "tag_answer" and not p["text_hash_matches"]:
            p.update(status="text_changed", note="OPD's text differs from the text the list was checked on; re-run the "
                                                 "adapter")
        elif act == "extract_tag" and d["text_chars"]:
            p.update(status="text_now_present", note="OPD has text for this document now; re-run the adapter on it")
        else:
            p.update(status="apply", guard="text_sha256" if act == "tag_answer" else "no_text_same_url")
        plan.append(p)
    return plan


def _q_int(v) -> str:
    return str(int(v))


def _q_str(v: str) -> str:
    """A SQL string literal for a URL: no control characters, single quotes doubled."""
    s = str(v)
    if any(ord(c) < 32 for c in s):
        raise ValueError(f"control character in {s[:60]!r}")
    return "'" + s.replace("'", "''") + "'"


def statements(plan: list[dict]) -> list[str]:
    """Guarded UPDATEs as text. Table and column names are the export's (docs); sha256(text) is written in PostgreSQL
    syntax. Values are validated (ints, 64-hex, body keys) before they are written."""
    out = ["-- Gegenprobe apply plan for the adapter lists' tag rows (DRY RUN TEXT: generated by",
           "-- python -m gegenprobe.repair.apply_tags, never executed by it). Table/column names follow the OPD export",
           "-- fields; adapt to OPD's schema. Run inside one transaction; each statement should report 1 row changed.",
           "-- PROTECTED OVERRIDE: scrapers set category_harmonized themselves; without protection the next scrape can",
           "-- overwrite a value set here (docs/adapters.md).",
           "BEGIN;"]
    for p in plan:
        if p["status"] != "apply":
            continue
        assert BODY.fullmatch(p["body"]), p["body"]
        head = (f"UPDATE docs SET category_harmonized = '{TARGET}' WHERE id = {_q_int(p['opd_doc_id'])} "
                f"AND body_key = '{p['body']}' AND affair_id = {_q_int(p['affair_id'])} AND category_harmonized IS NULL")
        sha = "encode(sha256(convert_to(text, 'UTF8')), 'hex')"
        if p["guard"] == "text_sha256":
            assert HEX64.fullmatch(p["list_text_sha256"])
            guard = f" AND {sha} = '{p['list_text_sha256']}'"
        elif p["guard"] == "url_and_export_text_sha256":
            assert HEX64.fullmatch(p["before_text_sha256"])
            guard = f" AND url = {_q_str(p['before_url'])} AND {sha} = '{p['before_text_sha256']}'"
        else:
            guard = f" AND (text IS NULL OR text = '') AND url = {_q_str(p['before_url'])}"
        num = str(p["affair_number"])[:40].replace("\n", " ")
        out.append(f"{head}{guard};  -- {p['list_action']} {num}")
    out.append("COMMIT;")
    return out


def _export_lines(body: str, args):
    if args.fetch:
        yield from net.stream_ndjson_gz(EXPORT_URL.format(body=body))
        return
    if args.cache:
        cands = [CACHE / f"{body}.jsonl.gz"]
    else:
        d = Path(args.exports_dir)
        cands = [d / f"docs_{body}.ndjson.gz", d / "docs" / f"docs_{body}.ndjson.gz", d / f"docs_{body}.ndjson"]
    p = next((c for c in cands if c.exists()), None)
    if p is None:
        return  # not_in_export for every row of this body
    with (gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")) as f:
        yield from f


def build(args) -> dict:
    bodies = set(args.bodies.split(",")) if args.bodies else None
    rows = list_rows(Path(args.lists), bodies, tuple(args.actions.split(",")))
    by_body = collections.defaultdict(set)
    for r in rows:
        by_body[r["body"]].add(int(r["opd_doc_id"]))
    docs: dict[tuple[str, int], dict] = {}
    for body in sorted(by_body):
        for i, d in read_docs(_export_lines(body, args), by_body[body], body).items():
            docs[(body, i)] = d
    plan = plan_rows(rows, docs)
    sql = statements(plan)
    st = collections.Counter((p["body"], p["list_action"], p["status"]) for p in plan)
    summary = dict(
        dry_run=True,
        inputs=dict(lists=str(args.lists), source="fetch" if args.fetch else ("cache" if args.cache else args.exports_dir),
                    actions=args.actions),
        rows=len(plan),
        by_status=dict(collections.Counter(p["status"] for p in plan)),
        by_action_status={f"{a} / {s}": n for (a, s), n in sorted(collections.Counter(
            (p["list_action"], p["status"]) for p in plan).items())},
        by_body={b: {f"{a} / {s}": n for (bb, a, s), n in sorted(st.items()) if bb == b} for b in sorted(by_body)},
        tag_answer_text_hash_matches=sum(bool(p.get("text_hash_matches")) for p in plan if p["list_action"] == "tag_answer"),
        statements=len(sql) - 7,
        protected_override="scrapers set category_harmonized themselves; apply as a protected override (docs/adapters.md)",
    )
    return dict(summary=summary, plan=plan, sql=sql)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, PLAN_COLS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else str(r.get(k)).lower() if isinstance(r.get(k), bool) else r.get(k))
                        for k in PLAN_COLS})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gegenprobe.repair.apply_tags",
                                 description="Tag-row apply plan (dry run; never touches OPD). See the module docstring.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--exports-dir", help="directory with docs_<BODY>.ndjson.gz (or docs/docs_<BODY>.ndjson.gz)")
    src.add_argument("--fetch", action="store_true", help="stream each listed body's docs export (polite requests)")
    src.add_argument("--cache", action="store_true", help="development: WORK/adapters/opd_docs")
    ap.add_argument("--lists", default=str(LISTS))
    ap.add_argument("--bodies", help="comma-separated body keys (default: every body with tag rows)")
    ap.add_argument("--actions", default=",".join(ACTIONS))
    ap.add_argument("--out", metavar="DIR", help="write the plan files here (default: print the summary only)")
    a = ap.parse_args(argv)
    r = build(a)
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        _write_csv(out / "apply_tags_plan.csv", r["plan"])
        (out / "apply_tags_plan.sql.txt").write_text("\n".join(r["sql"]) + "\n", encoding="utf-8")
        (out / "apply_tags_plan.json").write_text(json.dumps(r["summary"], indent=1) + "\n", encoding="utf-8")
        print(f"plan written to {out} (dry run: nothing was changed anywhere)", file=sys.stderr)
    else:
        print("dry run (no --out): summary and the first statements; nothing was written or changed", file=sys.stderr)
        print("\n".join(r["sql"][:9]) + "\n...", file=sys.stderr)
    print(json.dumps(r["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
