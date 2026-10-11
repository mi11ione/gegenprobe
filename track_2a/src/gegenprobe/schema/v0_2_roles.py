"""Schema v0.2's roles for the converter's own records: gegenprobe.convert.roles run over the P3, P3b and P5 documents.

    python -m gegenprobe.schema.v0_2_roles            write results/schema/v0_2/converter_roles_records.jsonl (needs the
                                                      cached extractions in WORK/text; no network, no model)
    python -m gegenprobe.schema.v0_2_roles --check    re-extract and compare with the committed file (exit 1 on a
                                                      difference; exit 0 with a note when the texts are not cached)

The committed file holds, per affair, what the rules read: actors with their printed role, the instrument's name and
function, the printed submission dates and the language of each document's text. Every value carries its document
role, page and character span and the sha256 of the printed text at the span; no document text is written (a name or a
date is the value itself). gegenprobe.schema.v0_2_all reads this file to put the roles into the v0.2 records, so `make
run` needs no document text for the records.
"""
from __future__ import annotations

import json
import sys

from ..convert import roles as R
from ..paths import ROOT, TEXT_CACHE

OUT_FILE = ROOT / "results" / "schema" / "v0_2" / "converter_roles_records.jsonl"
SETS = (("p3", ROOT / "data" / "gold3" / "p3_affairs.jsonl"), ("p3b", ROOT / "data" / "gold5" / "p3b_affairs.jsonl"),
        ("p5", ROOT / "data" / "gold6" / "p5_affairs.jsonl"))


def pages_of(sha: str, image_only: bool = False) -> tuple[list[str], str] | None:
    """(pages, extractor) of the cached extraction: OCR for an image-only document when an OCR text exists."""
    ps = sorted(TEXT_CACHE.glob(f"{sha}.*.json"))
    if not ps:
        return None
    ocr = [p for p in ps if ".tesseract-" in p.name]
    pick = ocr[0] if (image_only and ocr) else next((p for p in ps if ".pdftotext-" in p.name), ps[0])
    d = json.loads(pick.read_text(encoding="utf-8"))
    return d["pages"], d.get("extractor") or pick.name.split(".", 1)[1].rsplit(".", 1)[0]


def _strip(v: dict) -> dict:
    return {k: x for k, x in v.items() if k != "exact"} | {"exact": bool(v.get("exact"))}


def extract_row(set_name: str, row: dict) -> dict | None:
    docs = {d["role"]: d for d in row["docs"]}
    got = {r: pages_of(d["sha256"], bool(d.get("image_only"))) for r, d in docs.items()}
    if any(v is None for v in got.values()):
        return None
    q, a = (got.get("question") or ([], ""))[0], (got.get("answer") or ([], ""))[0]
    x = R.extract(q, a, row["body"])
    return dict(
        set=set_name, affair_id=row["affair_id"], body=row["body"], rules_version=R.RULES_VERSION,
        extractors={r: v[1] for r, v in got.items()},
        actors=[dict(role=p["role"], kind=p["kind"], name=_strip(p["name"]),
                     **({"on_behalf_of": p["on_behalf_of"]} if p.get("on_behalf_of") else {})) for p in x["actors"]],
        instrument=(dict(named=_strip(x["instrument"]["named"]), function=_strip(x["instrument"]["function"]))
                    if x["instrument"] else None),
        dates=[_strip(d) for d in x["dates"]],
        language_of_text={r: v for r, v in x["language_of_text"].items() if v is not None},
        language_method=R.LANG_METHOD,
    )


def render() -> tuple[str | None, list[str]]:
    """(the file's text, affairs whose texts are not cached); text None when any is missing."""
    rows, missing = [], []
    for set_name, path in SETS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            r = extract_row(set_name, row)
            if r is None:
                missing.append(f"{set_name}:{row['affair_id']}")
            else:
                rows.append(r)
    if missing:
        return None, missing
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), []


def load() -> dict[tuple[str, int], dict]:
    """The committed roles, keyed by (set, affair_id)."""
    out = {}
    for line in OUT_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[(r["set"], r["affair_id"])] = r
    return out


def check() -> dict:
    """Re-extract and compare (`make run` / tests): PASS, FAIL, or SKIP when the texts are not cached."""
    text, missing = render()
    if text is None:
        return dict(status="SKIP", summary=f"roles not re-extracted: {len(missing)} affairs' texts not cached")
    same = OUT_FILE.exists() and OUT_FILE.read_text(encoding="utf-8") == text
    n = text.count("\n")
    return dict(status="PASS" if same else "FAIL",
                summary=f"roles re-extracted from the cached texts for {n} affairs: "
                        + ("identical to the committed file" if same else "DIFFER from the committed file"))


def main(argv: list[str]) -> int:
    if "--check" in argv:
        r = check()
        print(f"converter roles: {r['status']}: {r['summary']}")
        return 1 if r["status"] == "FAIL" else 0
    text, missing = render()
    if text is None:
        print(f"texts not cached for {len(missing)} affairs (e.g. {missing[:3]}); fetch them through gegenprobe.pdftext",
              file=sys.stderr)
        return 1
    OUT_FILE.write_text(text, encoding="utf-8")
    print(OUT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
