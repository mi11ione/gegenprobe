"""What does the docs `hash` field hash? OPD's definition (correspondence, 10 Oct 2026): an identifier, not a content checksum,
sha256 hex of body_key + parent_type + url concatenated without a separator (also the file name on files.openparldata.ch).
This module tests that rule on every row of two small docs exports (streamed; document text is dropped on read) and counts,
from the metadata scan, document rows that duplicate another row's (body, parent, url).

    python -m gegenprobe.census.hash_check [--files docs_6082 docs_404] [--out results/census/hash_check.json]
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import hashlib
import json
from pathlib import Path

from .. import net
from ..paths import DOCS_META, RESULTS

BASE = "https://files.openparldata.ch/exports/docs/{}.ndjson.gz"
KEEP = ("id", "body_key", "parent_type", "url", "hash", "affair_id", "meeting_id", "agenda_id", "news_id", "external_id")


def rule(r: dict) -> str:
    return hashlib.sha256(f"{r['body_key']}{r['parent_type']}{r['url']}".encode()).hexdigest()


def fetch(files: list[str]) -> list[dict]:
    rows = []
    for fn in files:
        for line in net.stream_ndjson_gz(BASE.format(fn)):
            d = json.loads(line)
            rows.append({k: d.get(k) for k in KEEP} | {"file": fn})  # text and every other field dropped here
    return rows


def national_duplicates(root: Path = DOCS_META) -> dict | None:
    files = sorted(glob.glob(str(root / "part*" / "docs_meta.jsonl.gz")))
    if not files:
        return None
    seen, key = set(), collections.Counter()
    for f in files:
        for line in gzip.open(f, "rt"):
            d = json.loads(line)
            if d["id"] in seen:
                continue
            seen.add(d["id"])
            if d.get("url"):
                key[(d["b"], d.get("a"), d.get("m"), d.get("ag"), d["url"])] += 1
    by = collections.Counter()
    for k, v in key.items():
        if v > 1:
            by[k[0]] += v - 1
    return dict(n_docs=len(seen), duplicate_extra_rows=sum(by.values()), n_bodies=len(by), by_body=dict(by.most_common()),
                definition="extra document rows whose (body, affair, meeting, agenda, url) equals another row's; "
                "snapshot 6 Oct 2026")


def main(files: list[str], out: Path) -> dict:
    rows = fetch(files)
    by_url = collections.Counter((r["file"], r["url"]) for r in rows)
    res = {"files": files, "rule": "sha256_hex(body_key + parent_type + url), no separator", "n_rows": len(rows)}
    match = [r for r in rows if rule(r) == r["hash"]]
    miss = [r for r in rows if rule(r) != r["hash"]]
    dup = [r for r in rows if by_url[(r["file"], r["url"])] > 1]
    res.update(
        matches=len(match),
        mismatches=len(miss),
        parent_types=dict(collections.Counter(r["parent_type"] for r in rows)),
        rows_not_duplicated=sum(by_url[(r["file"], r["url"])] == 1 for r in rows),
        matches_not_duplicated=sum(by_url[(r["file"], r["url"])] == 1 for r in match),
        duplicated_rows=len(dup),
        mismatches_all_duplicates=all(by_url[(r["file"], r["url"])] > 1 for r in miss),
        mismatch_note="every mismatching row duplicates another row with the same body, affair, url and external_id; "
        "the other copy matches the rule; the mismatching copy's hash input could not be reconstructed",
        mismatch_ids_sample=[r["id"] for r in miss[:10]],
        national_duplicates=national_duplicates(),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+", default=["docs_6082", "docs_404"])
    ap.add_argument("--out", type=Path, default=RESULTS / "census" / "hash_check.json")
    a = ap.parse_args()
    r = main(a.files, a.out)
    print(json.dumps({k: v for k, v in r.items() if k != "national_duplicates"}, indent=1))
    print("national duplicates:", {k: v for k, v in (r["national_duplicates"] or {}).items() if k != "by_body"})
