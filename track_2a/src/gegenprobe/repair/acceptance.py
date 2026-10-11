"""Acceptance test for OPD's staging fix: how many of the BE relink documents are attached to their affair in a given
OPD snapshot.

OPD confirmed (correspondence, 10 Oct 2026) that a Bern answer arriving through two sources with the same document id is
kept under the first parent seen, and that a fix is pending. Until it ships, a relink applied to the database can be undone
by the next scrape, so the list is best applied as a protected override, or used as this acceptance test: after the fix,
every relink document should be attached to the affair the list names.

    python -m gegenprobe.repair.acceptance <docs_BE.ndjson.gz>   score a local snapshot (e.g. OPD's own export file)
    python -m gegenprobe.repair.acceptance --fetch               stream today's docs_BE export (470 MB, one polite request,
                                                                 nothing stored; GP_EXPORTS_DIR reads it from disk)
    python -m gegenprobe.repair.acceptance                       the census scan of the 6 Oct 2026 snapshot (dev machines)
Writes results/repair/acceptance_<live|file>_<YYYY-MM-DD>.json (acceptance_snapshot-2026-10-06.json for the default).
    --out DIR   write the result file into DIR instead (e.g. /var/lib/gegenprobe/results on a host whose checkout is
                read-only, as under the venv unit); checked for writability before anything is streamed. The relink list
                itself is always read from the checkout (results/repair/repair_BE.tsv).
Exit code 0 only when every relink document is attached to the affair the list names (the fix has shipped); 1 otherwise,
so CI or the nightly can gate on it; 2 when --out is not a writable directory.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import gzip
import io
import json
import os
import sys
from pathlib import Path

from .. import net
from gegenprobe.compliance import fetchguard
from .common import OUT, iter_docs_meta

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

EXPORT_URL = "https://files.openparldata.ch/exports/docs/docs_BE.ndjson.gz"


def relink_rows() -> dict[int, int]:
    """opd_doc_id -> affair_id for every relink row (including rows sent to review by the per-row check)."""
    out = {}
    for r in csv.DictReader(open(OUT / "repair_BE.tsv", encoding="utf-8"), delimiter="\t"):
        if (r.get("proposed_action") or r["action"]) == "relink":
            out[int(r["opd_doc_id"])] = int(r["affair_id"])
    return out


def _iter_export(lines):
    for line in lines:
        d = json.loads(line)
        yield dict(id=d["id"], a=d.get("affair_id"), ag=d.get("agenda_id"), m=d.get("meeting_id"))


def score(docs, want: dict[int, int]) -> dict:
    c = collections.Counter()
    seen = set()
    wrong = []
    for d in docs:
        if d["id"] not in want or d["id"] in seen:
            continue
        seen.add(d["id"])
        if d["a"] == want[d["id"]]:
            c["attached_to_listed_affair"] += 1
        elif d["a"]:
            c["attached_elsewhere"] += 1
            if len(wrong) < 20:
                wrong.append(dict(opd_doc_id=d["id"], listed_affair=want[d["id"]], attached_to=d["a"]))
        elif d["ag"] or d["m"]:
            c["under_agenda_or_meeting"] += 1
        else:
            c["still_parentless"] += 1
    c["doc_not_in_snapshot"] = len(want) - len(seen)
    return dict(n=len(want), **c, attached_elsewhere_examples=wrong,
                passed=c["attached_to_listed_affair"] == len(want))


def _out_dir(argv: list[str]) -> tuple[list[str], Path | None, str | None]:
    """Remove `--out DIR` / `--out=DIR` from argv; (rest, dir or None, error or None)."""
    rest, out = [], None
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = next(it, None)
            if out is None:
                return rest, None, "--out needs a directory"
        elif a.startswith("--out="):
            out = a.split("=", 1)[1]
        else:
            rest.append(a)
    if out is None:
        return rest, None, None
    d = Path(out)
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f".acceptance-write-test-{os.getpid()}"
        probe.write_text("")
        probe.unlink()
    except OSError as e:
        return rest, None, f"--out {d} is not a writable directory ({type(e).__name__}: {e})"
    return rest, d, None


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    argv, out_dir, err = _out_dir(argv)
    if err:
        print(err, file=sys.stderr)
        return 2
    want = relink_rows()
    if argv and argv[0] == "--fetch":
        r = net.open_url(EXPORT_URL, timeout=600)
        res = score(_iter_export(io.TextIOWrapper(gzip.GzipFile(fileobj=r), encoding="utf-8")), want)
        r.close()
        label = "live"
    elif argv and Path(argv[0]).is_file():
        with gzip.open(argv[0], "rt", encoding="utf-8") as f:
            res = score(_iter_export(f), want)
        label = Path(argv[0]).stem.split(".")[0]
    else:  # the census scan of the 6 Oct 2026 snapshot (default; dev machine)
        res = score(iter_docs_meta({"BE"}), want)
        label = "snapshot-2026-10-06"
    res["snapshot"] = label
    if label.startswith("snapshot-"):  # the pinned census snapshot: one stable file
        name = f"acceptance_{label}.json"
    else:  # live / local export: one dated file per check, never overwritten by the next day's run
        res["checked_on"] = dt.date.today().isoformat()
        name = f"acceptance_{label}_{res['checked_on']}.json"
    (out_dir or OUT).mkdir(parents=True, exist_ok=True)
    (out_dir or OUT).joinpath(name).write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "attached_elsewhere_examples"}, indent=1))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
