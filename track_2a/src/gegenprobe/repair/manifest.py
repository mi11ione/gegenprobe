"""results/repair/MANIFEST.json: every repair list in results/repair, what produced it, and which list wins where two lists
name the same affair. No network, no model; reads the committed lists only.

    python -m gegenprobe.repair.manifest           write results/repair/MANIFEST.json (exit 1 if two files share a name)
    python -m gegenprobe.repair.manifest --table   the precedence table of docs/repair.md

Lists:
  route lists     results/repair/repair_<BODY>.tsv(.gz)   python -m gegenprobe.repair.run (relink, fetch, agenda_join,
                  retype_oral, ocr candidates, placeholder_replace); for a body with more than one action also one subset
                  file per action, repair_<BODY>_<action>.tsv (the same rows, split)
  Bern lists      repair_BE_begin_date.tsv (repair.be_begin_date) and apply_be/ (repair.apply_be: the guarded SQL plan
                  built from repair_BE_relink.tsv and repair_BE_begin_date.tsv)
  adapter lists   results/repair/adapters/adapters_<BODY>.tsv  python -m gegenprobe.repair.adapters.run --write (tier,
                  counted, opd_doc_id, target_category, text_sha256; repair/adapters/lists.py). adapters_X.tsv is a
                  header-only test artefact (TEST_ARTEFACTS), not a parliament's list
  P7 tier         results/repair/adapters/p7/promoted.tsv (registered P7 output) and promoted_by_apertus.tsv (the same
                  rows in adapter-list columns, repair/adapters/promoted_list.py); counted=false
"""
from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

from ..paths import RESULTS, ROOT

REPAIR = RESULTS / "repair"
OUT = REPAIR / "MANIFEST.json"
ADAPTERS = REPAIR / "adapters"
ROUTE_ACTIONS = ("relink", "agenda_join", "fetch", "retype_oral", "ocr", "placeholder_replace", "review",
                 "set_begin_date")

PRECEDENCE = [
    dict(lists="adapter list vs route list, action=ocr (same affair)",
         wins="adapter list",
         why="the route's ocr rows are candidates (OPD holds the answer file without usable text; no text read, "
             "verified empty). The adapters ran on every one of those affairs, read or OCR'd the text and checked it: "
             "their row (tier says whether it counts) replaces the candidate. A candidate whose affair has no adapter "
             "row (the adapter failed: no usable text, identity or heading not found) stays the only row for it."),
    dict(lists="adapter list vs route list, action=agenda_join or retype_oral (same affair)",
         wins="no overlap",
         why="agenda joins are census link status agenda, retype_oral is Valais' oral-answer pointer; the adapters only "
             "take absent and image_only affairs. Checked on every run (overlaps below)."),
    dict(lists="route list repair_<BODY>.tsv vs repair_<BODY>_<action>.tsv",
         wins="either (same rows)",
         why="the per-action files are the combined file split by action; apply one or the other, not both."),
    dict(lists="repair_BE_relink.tsv / repair_BE_begin_date.tsv vs apply_be/apply_BE_plan.*",
         wins="apply_be plan for execution",
         why="the plan is built from the two lists and guards every UPDATE with the before-state (repair.apply_be)."),
    dict(lists="results/ vs site/downloads/",
         wins="identical",
         why="site/downloads holds byte-identical copies of the lists it offers (sha256 below)."),
]


def _open(p: Path):
    return gzip.open(p, "rt", encoding="utf-8", newline="") if p.suffix == ".gz" else open(p, encoding="utf-8", newline="")


def _rows(p: Path) -> list[dict]:
    with _open(p) as f:
        return list(csv.DictReader(f, delimiter="\t" if ".tsv" in p.name else ","))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# results/repair/adapters/adapters_X.tsv: header only, written by a test (tests/test_adapter_filters.py) earlier
# redirected it to a scratch tree. Kept because LOCK8 hashes every adapters_*.tsv; it is not a parliament's list.
TEST_ARTEFACTS = {"adapters_X.tsv"}
P7_DIR = ADAPTERS / "p7"


def _kind(p: Path) -> tuple[str, str]:
    n = p.name
    if p.parent == ADAPTERS and n in TEST_ARTEFACTS:
        return ("test artefact (header only, no rows; not a parliament's list: body X is the test fixture's; kept because "
                "LOCK8 hashes every adapters_*.tsv)", "pytest tests/test_adapter_filters.py (earlier version)")
    if p.parent == P7_DIR:
        if n == "promoted.tsv":
            return ("P7 promoted tier (registered output; P7 columns; tier promoted_by_apertus, counted=false)",
                    "python -m gegenprobe.repair.adapters.adjudicate apply")
        return ("P7 promoted tier in adapter-list columns (same 214 rows; tier promoted_by_apertus, counted=false, "
                "action review, proposed_action set)", "python -m gegenprobe.repair.adapters.promoted_list")
    if p.parent == ADAPTERS:
        return "adapter list", "python -m gegenprobe.repair.adapters.run --write"
    if p.parent.name == "apply_be":
        return "Bern apply plan", "python -m gegenprobe.repair.apply_be"
    if n.startswith("repair_BE_begin_date"):
        return "Bern begin_date list", "python -m gegenprobe.repair.be_begin_date"
    body_action = n.split(".")[0][len("repair_"):]
    if any(body_action.endswith("_" + a) for a in ROUTE_ACTIONS):
        return "route list (one action, subset of the combined file)", "python -m gegenprobe.repair.run"
    return "route list (combined)", "python -m gegenprobe.repair.run"


def list_files() -> list[Path]:
    fs = sorted(REPAIR.glob("repair_*.tsv")) + sorted(REPAIR.glob("repair_*.tsv.gz"))
    fs += sorted((REPAIR / "apply_be").glob("*.csv")) + sorted(ADAPTERS.glob("adapters_*.tsv"))
    fs += [P7_DIR / n for n in ("promoted.tsv", "promoted_by_apertus.tsv") if (P7_DIR / n).exists()]
    return fs


def same_names() -> dict[str, list[str]]:
    """Basenames that occur more than once under results/repair (excluding the audit folders' verdict files)."""
    seen = collections.defaultdict(list)
    for p in REPAIR.rglob("*"):
        if p.is_file() and not any(part.startswith("audit") for part in p.relative_to(REPAIR).parts[:-1]):
            seen[p.name].append(str(p.relative_to(ROOT)))
    return {k: v for k, v in sorted(seen.items()) if len(v) > 1}


def overlaps() -> list[dict]:
    """Per body with an adapter list and a combined route list: the affairs both name, by (route action, adapter tier)."""
    out = []
    for a in sorted(ADAPTERS.glob("adapters_*.tsv")):
        if a.name in TEST_ARTEFACTS:
            continue
        body = a.stem[len("adapters_"):]
        r = REPAIR / f"repair_{body}.tsv"
        if not r.exists():
            continue
        ad = {x["affair_id"]: x for x in _rows(a)}
        route = _rows(r)
        pairs = collections.Counter()
        for x in route:
            y = ad.get(x["affair_id"])
            pairs[(x["action"], y["tier"] if y else "no adapter row")] += 1
        both = sum(v for (ra, t), v in pairs.items() if t != "no adapter row")
        doc_differs = sum(1 for x in route if x["affair_id"] in ad and x["opd_doc_id"] and ad[x["affair_id"]]["opd_doc_id"]
                          and x["opd_doc_id"] != ad[x["affair_id"]]["opd_doc_id"])
        out.append(dict(body=body, route_list=r.name, adapter_list=a.name, route_rows=len(route), adapter_rows=len(ad),
                        same_affair=both, opd_doc_id_differs=doc_differs,
                        by_route_action_and_adapter_tier={f"{ra} / {t}": v for (ra, t), v in sorted(pairs.items())},
                        winner="adapter list for the same_affair rows; the route list for its other rows"))
    return out


def site_copies(files: list[Path]) -> dict:
    d = ROOT / "site" / "downloads"
    out = {}
    for p in files:
        q = d / p.name
        if q.exists():
            out[p.name] = q.read_bytes() == p.read_bytes()
    return out


def build() -> dict:
    files = list_files()
    rows = []
    for p in files:
        kind, cmd = _kind(p)
        rs = _rows(p)
        act = collections.Counter(r.get("action") or "" for r in rs)
        e = dict(file=str(p.relative_to(ROOT)), kind=kind, command=cmd, rows=len(rs), by_action=dict(sorted(act.items())),
                 sha256=_sha(p))
        if kind == "adapter list" or kind.startswith(("test artefact", "P7 promoted")):
            e["by_tier"] = dict(sorted(collections.Counter(r["tier"] for r in rs).items()))
            e["counted"] = sum(r["counted"] == "true" for r in rs)
        rows.append(e)
    ov = overlaps()
    dup = same_names()
    return dict(
        note="Every repair list under results/repair, the command that writes it and which list wins where two lists "
             "name the same affair (precedence). Adapter lists: apply rows with counted=true (verified=true is the same); "
             "tier=review rows are for a person. No two files under results/repair share a name.",
        precedence=PRECEDENCE,
        files=rows,
        overlaps=ov,
        overlap_totals=dict(same_affair=sum(o["same_affair"] for o in ov),
                            opd_doc_id_differs=sum(o["opd_doc_id_differs"] for o in ov),
                            by_pair=dict(sum((collections.Counter(o["by_route_action_and_adapter_tier"]) for o in ov),
                                             collections.Counter()))),
        same_name=dup,
        site_copies_identical=site_copies(files),
    )


def table(m: dict) -> str:
    out = ["| lists | wins | why |", "|---|---|---|"]
    out += [f"| {p['lists']} | {p['wins']} | {p['why']} |" for p in m["precedence"]]
    out += ["", "| parliament | route list (rows) | adapter list (rows) | same affair | route action / adapter tier |",
            "|---|---|---|---|---|"]
    for o in m["overlaps"]:
        pairs = ", ".join(f"{k} {v:,}" for k, v in o["by_route_action_and_adapter_tier"].items())
        out.append(f"| {o['body']} | {o['route_list']} ({o['route_rows']:,}) | {o['adapter_list']} ({o['adapter_rows']:,}) "
                   f"| {o['same_affair']:,} | {pairs} |")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    m = build()
    if "--table" in argv:
        print(table(m))
        return 0
    OUT.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(m['files'])} lists, {m['overlap_totals']['same_affair']:,} affairs in two lists"
          f", same names: {len(m['same_name'])}")
    return 1 if m["same_name"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
