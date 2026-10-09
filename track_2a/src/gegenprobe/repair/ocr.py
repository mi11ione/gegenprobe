"""Image-only answer documents (scans): recover the text with Tesseract (deu+fra+ita), then check that it is an answer.

The census found 2,366 gap affairs outside BE/CHE whose answer document is attached but has no text in OPD; a 30-document
spike probe called 29/30 of them image-only PDFs; re-fetching the same 30 (results/repair/ocr_probe.json) shows 15 image-only
scans, 13 VS `_ANT` oral-answer pointers that do have a text layer (see vs.py), 1 short BL text layer and 1 TG document OPD
never extracted. The scans are real written answers. This module OCRs them and types the result:
  text_recovered   ≥ 200 characters of OCR text
  heading          an answer heading or the executive's letterhead (Consiglio di Stato / Regierungsrat / Conseil d'État ...)
  date_parsed      at least one full date (DE/FR/IT formats) in the first page
  oral_stub        VS pointer to an oral answer

Language models: tessdata_fast @ 87416418657359cb625c412a48b6e1d6d41c29bd (deu, fra, ita, eng; sha256 in TESSDATA_SHA256).
Docker installs Debian's tesseract-ocr-{deu,fra,ita}; local runs use WORK/tessdata via TESSDATA_PREFIX.

usage:
  python -m gegenprobe.repair.ocr probe [max_pages]   the 30-document re-extraction sample, deu+fra+ita vs eng-only
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .. import pdftext
from ..paths import PDF_CACHE, WORK
from ..stats import wilson_pct
from .common import ANSWER_HEADING, OUT, dump, parse_dates
from .vs import STUB

TESSDATA_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
TESSDATA_SHA256 = {
    "deu": "19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d",
    "fra": "ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca",
    "ita": "b8f89e1e785118dac4d51ae042c029a64edb5c3ee42ef73027a6d412748d8827",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}
LETTERHEAD = re.compile(
    r"Consiglio di Stato|Repubblica e Cantone Ticino|Regierungsrat|Conseil d.[ÉE]tat|Conseil-ex[ée]cutif|"
    r"Stadtrat|Gemeinderat|Municipio|Conseil communal|Stellungnahme|Risposta|R[ée]ponse|Antwort",
    re.I,
)
SPIKE = Path.home() / "Desktop/hackapertus/spikes/recovery"
STOP = {
    "deu": {"und", "der", "die", "das", "nicht", "ist", "mit", "für"},
    "fra": {"les", "des", "est", "pour", "dans", "que", "une", "par"},
    "ita": {"della", "che", "per", "una", "sono", "delle", "nel", "con"},
}


def use_local_tessdata() -> None:
    td = WORK / "tessdata"
    if "TESSDATA_PREFIX" not in os.environ and (td / "deu.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(td)


def guess_lang(text: str) -> str:
    w = collections.Counter(re.findall(r"[a-zàâäéèêëîïôöùûüç]+", text.lower()))
    score = {k: sum(w[s] for s in v) for k, v in STOP.items()}
    best = max(score, key=score.get)
    return best if score[best] >= 3 else "unknown"


def classify(text: str, first_page: str) -> dict:
    t = re.sub(r"\s+", " ", text).strip()
    return dict(
        chars=len(t),
        text_recovered=len(t) >= 200,
        oral_stub=bool(STUB.search(t)) and len(t) < 300,
        heading=bool(ANSWER_HEADING.search(t) or LETTERHEAD.search(t)),
        answer_heading_strict=bool(ANSWER_HEADING.search(t)),
        date_parsed=bool(parse_dates(first_page)),
        first_date=(parse_dates(first_page) or [(None,)])[0][0],
        lang=guess_lang(t),
        accented=len(re.findall(r"[àâäéèêëîïôöùûüç]", t, re.I)),
    )


def ocr_doc(path: Path, langs: str, max_pages: int | None) -> tuple[dict, float, int]:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    dest = PDF_CACHE / f"{sha}.pdf"
    if not dest.exists():
        PDF_CACHE.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    timing_file = WORK / "ocr_timing.json"
    timing = json.loads(timing_file.read_text()) if timing_file.exists() else {}
    t0 = time.time()
    d = pdftext.extract(sha, dest, ocr=True, langs=langs, max_ocr_pages=max_pages)
    key = f"{sha}:{d['extractor']}"
    if key not in timing:  # first (uncached) extraction: record wall time; cached re-runs report the recorded value
        timing[key] = round(time.time() - t0, 2)
        timing_file.write_text(json.dumps(timing))
    return d, timing[key], len(d["pages"])


def probe(max_pages: int = 3) -> dict:
    use_local_tessdata()
    rows_in = json.loads((SPIKE / "reextract.json").read_text())
    rows = []
    for r in rows_in:
        p = SPIKE / "data/reextract" / f"{r['doc_id']}.pdf"
        if not p.exists():
            continue
        row = dict(doc_id=r["doc_id"], body=r["b"], affair_type=r["t"], year=r["y"], name=r["name"], opd_status=r["opd_status"])
        for langs in ("deu+fra+ita", "eng"):
            d, secs, npages = ocr_doc(p, langs, max_pages)
            text = "\n".join(d["pages"])
            c = classify(text, d["pages"][0] if d["pages"] else "")
            c.update(extractor=d["extractor"], secs=round(secs, 1), pages=npages, image_only=d["image_only"])
            row[langs] = c
        rows.append(row)
        m = row["deu+fra+ita"]
        print(
            row["body"],
            row["name"][:40],
            m["lang"],
            m["chars"],
            m["heading"],
            m["date_parsed"],
            m["oral_stub"],
            "| eng",
            row["eng"]["chars"],
            flush=True,
        )
    return summarise(rows)


def category(r: dict) -> str:
    m = r["deu+fra+ita"]
    if m["image_only"]:
        return "image_only"
    if m["oral_stub"]:
        return "text_layer_oral_stub"
    return "text_layer_full" if m["text_recovered"] else "text_layer_short"


def summarise(rows: list[dict]) -> dict:
    def agg(sel, key):
        ks = [r[key] for r in sel]
        n = len(ks)
        out = dict(n=n)
        for f in ("text_recovered", "heading", "answer_heading_strict", "date_parsed", "oral_stub"):
            out[f] = sum(bool(x[f]) for x in ks)
        out["mean_chars"] = round(sum(x["chars"] for x in ks) / max(1, n))
        out["accented_chars"] = sum(x["accented"] for x in ks)
        out["secs_per_page"] = round(sum(x["secs"] for x in ks) / max(1, sum(x["pages"] for x in ks)), 2)
        return out

    for r in rows:
        r["category"] = category(r)
    cats = collections.Counter(r["category"] for r in rows)
    img = [r for r in rows if r["category"] == "image_only"]
    ok = [
        r for r in img if r["deu+fra+ita"]["text_recovered"] and r["deu+fra+ita"]["heading"] and r["deu+fra+ita"]["date_parsed"]
    ]
    ok_eng = [r for r in img if r["eng"]["text_recovered"] and r["eng"]["heading"] and r["eng"]["date_parsed"]]
    by_body = collections.defaultdict(list)
    by_lang = collections.defaultdict(list)
    for r in img:
        by_body[r["body"]].append(r)
        by_lang[r["deu+fra+ita"]["lang"]].append(r)
    by_cat_body = collections.defaultdict(collections.Counter)
    for r in rows:
        by_cat_body[r["category"]][r["body"]] += 1
    return dict(
        n_docs=len(rows),
        categories=dict(cats),
        categories_by_body={k: dict(v) for k, v in by_cat_body.items()},
        image_only=len(img),
        image_only_ok=len(ok),
        ci_image_only_ok=wilson_pct(len(ok), len(img)),
        image_only_ok_eng=len(ok_eng),
        ci_image_only_ok_eng=wilson_pct(len(ok_eng), len(img)),
        rule="written answer recovered = OCR text >= 200 chars AND (answer heading or executive letterhead) "
        "AND a full date on page 1",
        image_multi=agg(img, "deu+fra+ita"),
        image_eng=agg(img, "eng"),
        by_body={b: dict(multi=agg(v, "deu+fra+ita"), eng=agg(v, "eng")) for b, v in sorted(by_body.items())},
        by_lang={lg: dict(multi=agg(v, "deu+fra+ita"), eng=agg(v, "eng")) for lg, v in sorted(by_lang.items())},
        tessdata=dict(repo="tesseract-ocr/tessdata_fast", commit=TESSDATA_COMMIT, sha256=TESSDATA_SHA256),
        rows=rows,
    )


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "probe"
    if cmd == "probe":
        r = probe(int(argv[1]) if len(argv) > 1 else 3)
        dump(OUT / "ocr_probe.json", r)
        print(json.dumps({k: v for k, v in r.items() if k not in ("rows", "tessdata")}, indent=0)[:3000])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
