"""The adapter repair lists OPD applies (round 6 list hygiene): one row per affair the adapters verified or sent to review,
with the tier that decides whether it counts, the OPD document it points at, the category to set and the hash of the text
that was checked.

    results/repair/adapters/adapters_<BODY>.tsv   (written by `python -m gegenprobe.repair.adapters.run --write`)

Columns: the repair columns of repair/common.py without the per-row `note` (the route is per parliament, in
results/repair/MANIFEST.json), then

  tier              exact_doc_date | exact_any_printed_date | date_window | identity_wording_only | review
                    (failed affairs are not listed; they stay in <BODY>.json)
  counted           true only for the three tiers with a date check (run.COUNTED); `verified` equals `counted`, and
                    `action` is the proposed action only when counted (otherwise `review`, proposed_action keeps it)
  review_reason     why a row is not counted: the check's reason and date class, `identity_wording_only`, or
                    `opd_doc_ambiguous` (the source file sits on the affair in OPD more than once)
  text_sha256       sha256 of the extracted text the checks read (UTF-8; the excerpt in WORK, never committed)
  target_category   the OPD category the applied row sets on the answer document: `response_text`, the value of OPD's
                    harmonised document vocabulary (docs exports, field category_harmonized) for a government answer
  target_category_note  the parliament's own answer label in OPD where one is in use (category_de/fr/it), else why
                    none can be given
  census_link_status, census_category   the registered census status of the affair and its place in the derived layer
                    (census/corrected.py)

The categories in use per parliament come from OPD's documents on the target affairs (WORK/adapters/opd_docs) and are
committed as results/repair/adapters/opd_categories.json (`python -m gegenprobe.repair.adapters.lists categories`).
"""
from __future__ import annotations

import collections
import functools
import gzip
import hashlib
import json
import re
import sys

from ...paths import RESULTS
from . import opd_docs

OUT = RESULTS / "repair" / "adapters"
PREFIX = "adapters_"
CATEGORIES = OUT / "opd_categories.json"
TARGET_CATEGORY = "response_text"
EXTRA_COLS = ["tier", "counted", "review_reason", "text_sha256", "target_category", "target_category_note",
              "census_link_status", "census_category"]
SETS_CATEGORY = ("tag_answer", "extract_tag", "fetch")
# a category label that names the government's answer (stricter than the census lexicon, which also lists minutes
# extracts and decisions)
ANSWER_LABEL = re.compile(r"antwort|r[ée]ponse|rispost|stellungnahme|beantwortung", re.I)
SOURCE_FILE = re.compile(r"/Files/([0-9a-f]{32})-\d+/", re.I)  # Zürich canton CDWS eDocument id (zh.EID)


def path(body: str):
    return OUT / f"{PREFIX}{body}.tsv"


# ---------------------------------------------------------------- OPD document of a row
@functools.lru_cache(maxsize=None)
def _by_source_file(body: str) -> dict[tuple[int, str], list[dict]]:
    out = collections.defaultdict(list)
    for d in opd_docs.url_index(body):
        m = SOURCE_FILE.search(d.get("url") or "")
        if m and d.get("affair_id"):
            out[(int(d["affair_id"]), m.group(1).lower())].append(d)
    return out


def opd_doc(body: str, rec: dict) -> tuple[int | None, list[int], int | None]:
    """(opd_doc_id, every OPD document id that carries the source file on this affair, the id whose URL is the version
    read). The in-OPD routes name their document; a source route (Zürich canton) that found its file already on the affair
    in OPD (cmeta.opd_holds) is joined back by the source file id in OPD's URL: one match is the document, more than one
    (the same file filed twice, or two versions) is ambiguous."""
    b = rec.get("best") or {}
    held = (b.get("cmeta") or {}).get("opd_holds")
    if not held or not held.get("same_affair"):
        return (int(b["opd_doc_id"]), [int(b["opd_doc_id"])], None) if b.get("opd_doc_id") else (None, [], None)
    m = SOURCE_FILE.search(b.get("url") or "")
    same = _by_source_file(body).get((int(rec["affair_id"]), m.group(1).lower()), []) if m else []
    ids = sorted({int(d["id"]) for d in same}) or [int(held["id"])]
    read = next((int(d["id"]) for d in same if d.get("url") == b.get("url")), None)
    return (ids[0] if len(ids) == 1 else None), ids, read


def text_sha256(rec: dict) -> str | None:
    p = rec.get("excerpt")
    if not p:
        return None
    try:
        raw = open(p, encoding="utf-8").read()
    except OSError:
        return None
    text = raw.split("\n\n", 1)[1] if "\n\n" in raw else raw
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- categories
def build_categories() -> dict:
    """Per parliament with adapter targets: the category labels on OPD's documents of the target affairs (category_de,
    _fr, _it) and the harmonised categories in use; the label that names the answer, if the parliament uses one."""
    out = {}
    for p in sorted(opd_docs.CACHE.glob("*.jsonl.gz")):
        if ".urls." in p.name:
            continue
        b = p.name.split(".")[0]
        labels, answer, harm, n = collections.Counter(), collections.Counter(), collections.Counter(), 0
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                n += 1
                for lang in ("de", "fr", "it"):
                    c = d.get(f"category_{lang}")
                    if c:
                        labels[c] += 1
                        if ANSWER_LABEL.search(c):
                            answer[(lang, c)] += 1
                if d.get("category_harmonized"):
                    harm[d["category_harmonized"]] += 1
        out[b] = dict(documents=n, labelled=sum(labels.values()), labels=dict(labels.most_common(8)),
                      answer_labels=[dict(lang=k[0], label=k[1], n=v) for k, v in answer.most_common()],
                      harmonized=dict(harm.most_common()))
    return dict(note="OPD's document categories on the adapter target affairs (WORK/adapters/opd_docs, docs exports of "
                     "10 Oct 2026). target_category of every list row is OPD's harmonised value `response_text`; "
                     "answer_labels are the parliament's own labels that name the answer (antwort, réponse, risposta, "
                     "Stellungnahme, Beantwortung)", target_category=TARGET_CATEGORY, bodies=out)


@functools.lru_cache(maxsize=1)
def categories() -> dict:
    return json.loads(CATEGORIES.read_text())["bodies"] if CATEGORIES.exists() else {}


def category_note(body: str, doc: dict | None = None) -> str:
    c = categories().get(body)
    if c is None:
        return "category vocabulary of this parliament not read (no OPD documents on its target affairs)"
    if c["answer_labels"]:
        lab = "; ".join(f"category_{a['lang']}={a['label']} ({a['n']} documents)" for a in c["answer_labels"][:2])
        return f"also the parliament's own answer label in OPD: {lab}"
    if not c["labelled"]:
        return (f"own label not determinable: none of OPD's {c['documents']:,} documents on this parliament's target "
                "affairs carries a category_de/fr/it; set category_harmonized only")
    top = ", ".join(list(c["labels"])[:3])
    return f"own label not determinable: this parliament's labels in OPD ({top}) name no answer; set category_harmonized only"


# ---------------------------------------------------------------- census columns
@functools.lru_cache(maxsize=1)
def _census():
    from ...census import corrected
    return corrected.interventions(), corrected.earlier_fetch()


def census_cols(aid: int, ad: dict) -> tuple[str, str]:
    from ...census import corrected
    iv, early = _census()
    x = iv.get(int(aid))
    if x is None or x["link"] == "attached":  # not a registered gap row (only in tests: synthetic affair ids)
        return (x or {}).get("link", ""), ""
    cat, sub = corrected.place(x["link"], ad, early.get(int(aid)))
    return x["link"], f"{cat}:{sub}" if sub else cat


def main(argv: list[str]) -> int:
    if argv[:1] == ["categories"]:
        res = build_categories()
        CATEGORIES.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{CATEGORIES}: {len(res['bodies'])} parliaments")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
