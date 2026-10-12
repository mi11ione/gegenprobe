"""The files the app offers for download (site/downloads/): byte-identical copies of committed files, grouped as the About
view lists them, plus the adapter lists per parliament (census/corrected.write_lists) and their manifest.

results/repair/MANIFEST.json records, for every repair list it tracks, whether site/downloads/ holds a byte-identical copy
(`site_copies_identical`); the set of repair lists shipped here is therefore kept as it was.
"""
from __future__ import annotations

from pathlib import Path

from ..paths import ROOT

REPO_URL = "https://github.com/mi11ione/gegenprobe"
REPO_BLOB = REPO_URL + "/blob/main/track_2a/"
DIR = "downloads"

# (group, source under track_2a/, what it is)
DOWNLOADS = (
    ("Bern lists", "results/repair/repair_BE_relink.tsv",
     "relink: answers already in OPD under an agenda item, to attach to their affair by the canton's document id"),
    ("Bern lists", "results/repair/repair_BE_fetch.tsv", "fetch: answers OPD does not hold, with the canton's PDF URL"),
    ("Bern lists", "results/repair/repair_BE_review.tsv", "review: rows whose per-row check failed, for a person"),
    ("Bern lists", "results/repair/repair_BE_begin_date.tsv",
     "begin_date: affairs whose begin date is a load timestamp, with the submission event that replaces it"),
    ("Apply plan (dry run)", "results/repair/apply_be/apply_BE_plan.sql.txt",
     "guarded UPDATE statements, one per row, each conditioned on the row's before-state; never executed by us"),
    ("Apply plan (dry run)", "results/repair/apply_be/apply_BE_relink_plan.csv", "relink plan: before and after per row"),
    ("Apply plan (dry run)", "results/repair/apply_be/apply_BE_begin_date_plan.csv",
     "begin_date plan: before and after per row"),
    ("Apply plan (dry run)", "results/repair/apply_be/apply_BE_plan.json",
     "plan summary: rows by status, the export identifier rule and the hash/URL side effect"),
    ("JSON Schemas (v0.1)", "results/schema/affair.schema.json", "Affair: one parliamentary affair with its documents"),
    ("JSON Schemas (v0.1)", "results/schema/doc_extraction.schema.json", "DocExtraction: what the converter writes per document"),
    ("Workbench schema (v0.1)", "schema/gegenprobe_schema.py",
     "schema v0.1 as one Python file for OPD's workbench: pydantic only, no imports from gegenprobe, no I/O; its JSON "
     "Schemas are tested equal to the two above"),
    ("Workbench schema (v0.2)", "schema/gegenprobe_schema_v0_2.py",
     "schema v0.2: v0.1 plus P8's roles (author roles, the instrument's function, the text's language apart from the "
     "tag, submission-date roles, the recommendation's stage); pydantic only, imports the v0.1 file next to it"),
    ("Workbench schema (v0.2)", "results/schema/v0_2/p8_validation.json",
     "the 66 P8 gold affairs converted to v0.2 records, all valid, and the v0.1 samples upgraded losslessly (counts)"),
    ("Federal (Fedlex) list", "results/repair/repair_CHE.tsv.gz",
     "placeholder_replace: federal answers whose OPD document is a placeholder; a work queue (source_url resolved and "
     "verified on a minority of rows; the rest by repair.che backlog)"),
    ("OPD vocabulary errors", "results/census/vocab_bugs.tsv",
     "harmonised labels that are wrong as published, with the affairs carrying them and the census snapshot they were "
     "counted on"),
    ("Rows Apertus moved up (P7)", "results/repair/adapters/p7/promoted_by_apertus.tsv",
     "review-queue rows Apertus moved up, in the adapter-list columns (tier promoted_by_apertus, counted=false): a pre-sorted "
     "batch for a reviewer"),
    ("Rows Apertus moved up (P7)", "results/repair/adapters/p7/promoted.tsv",
     "the same rows as the registered P7 output (P7's own columns)"),
    ("Spot-check kit", "results/opd_spotcheck/spotcheck.csv",
     "30 gold labels (answer dates, P7 rows Apertus moved up, P8 submitter and type) with link, page, span and quote, for anyone "
     "to verify in about an hour; scored by python -m eval.spotcheck score"),
)

# the research dataset, the per-parliament table and the report (not repair lists: MANIFEST.json does not track them)
DATASET = (
    ("Dataset", "results/census/interventions.tsv.gz",
     "one row per intervention with a recorded government answer: link status, dates, date trust, OPD and source URLs"),
    ("Dataset", "results/census/interventions_README.md", "the dataset's and the parliaments table's column dictionary"),
    ("Dataset", "results/evidence/parliaments.csv", "one row per parliament: where the answers are, per period"),
    ("Report", "444_Report.pdf", "the technical report (PDF)"),
)


# served at the site root, not under downloads/: repair/adapters/registry.py (LOCK-listed) reads the parliaments' labels
# from site/parliaments.csv
AT_ROOT = ("parliaments.csv",)


def href(name: str) -> str:
    return name if name in AT_ROOT else f"{DIR}/{name}"


def files() -> list[tuple[str, str, str]]:
    return list(DOWNLOADS) + list(DATASET)


def copy(dest: Path) -> list[Path]:
    """Copy every listed file into dest/downloads/ and write the adapter lists there (census/corrected.write_lists);
    drop any other file. Returns the files written."""
    from ..census.corrected import MANIFEST, write_lists

    d = dest / DIR
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for _, rel, _ in files():
        src = ROOT / rel
        to = dest / src.name if src.name in AT_ROOT else d / src.name
        to.write_bytes(src.read_bytes())
        out.append(to)
    man = write_lists(d)
    out += [d / f["file"] for f in man["files"]] + [d / MANIFEST]
    for f in d.iterdir():
        if f.is_file() and f not in out:
            f.unlink()
    return out


def listing(dest: Path) -> list[dict]:
    """The About view's download list: group, file, size, rows (TSV/CSV), what it is; then the adapter lists."""
    import json

    from ..census.corrected import MANIFEST

    out = []
    for group, rel, what in files():
        p = ROOT / rel
        rows = None
        if p.suffix in (".tsv", ".csv"):
            with open(p, encoding="utf-8") as f:
                rows = sum(1 for line in f if line.strip()) - 1
        out.append(dict(g=group, f=p.name, h=href(p.name), b=p.stat().st_size, r=rows, w=what))
    m = json.loads((dest / DIR / MANIFEST).read_text(encoding="utf-8"))
    for f in sorted(m["files"], key=lambda f: f["body"]):
        out.append(dict(g="Adapter lists", f=f["file"], h=href(f["file"]), b=(dest / DIR / f["file"]).stat().st_size, r=f["rows"],
                        w=f"{f['label']}: adapter list (verified and review rows)", body=f["body"]))
    out.append(dict(g="Adapter lists", f=MANIFEST, h=href(MANIFEST), b=(dest / DIR / MANIFEST).stat().st_size, r=None,
                    w="per parliament: file, rows by action and tier, counted rows; which list wins on overlap"))
    return out
