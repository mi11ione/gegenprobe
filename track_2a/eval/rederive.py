"""`make run` step: re-derive the frozen RULES arm on the held-out set from the source PDFs, not from stored predictions.

For each held-out document: fetch the PDF from its source URL and verify it against the committed sha256
(pdftext.fetch_pdf), extract the text (pdftotext; tesseract deu+fra+ita for image-only scans if tesseract is installed),
run the frozen rules (convert/rules.py, LOCK-hashed), and compare status and value with the committed rules row
(results/eval/heldout__none.json). Documents whose host is unreachable or forbidden by robots.txt are skipped and
counted; a time budget (GP_REDERIVE_BUDGET seconds, default 360) stops the step with a partial count.

OCR (round 13): before the first scan, gegenprobe.ocrguard.status() checks tesseract AND its deu/fra/ita language data
(and compares each model's sha256 with the measured tessdata_fast set); without them the scans are skipped and counted
with the reason, never re-derived from empty text. A scan whose OCR fails at run time is listed as `ocr_failed`.

Status: PASS = every re-derived document matches and no scan was skipped or failed OCR; WARN = some differ (listed with
both extractor versions; a different poppler/tesseract build can change the text) or scans were skipped / failed OCR;
SKIP = offline or nothing re-derived. Never FAIL: the replay steps already
gate the frozen numbers, this step shows they come out of the source PDFs.

    python -m eval.rederive [out.json]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from gegenprobe import ocrguard, pdftext
from gegenprobe.convert import rules
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)
ocrguard.ensure()  # OCR fails loudly: missing language data / tesseract errors are `ocr_failed`, never cached empty pages


def _jsonl(p):
    return [json.loads(x) for x in open(p, encoding="utf-8")]


def run(budget_s: float | None = None) -> dict:
    budget_s = float(os.environ.get("GP_REDERIVE_BUDGET", "360")) if budget_s is None else budget_s
    t0 = time.time()
    docs = _jsonl(DATA / "gold" / "heldout_docs.jsonl")
    committed = {r["doc_id"]: r["rules"] for r in json.loads((RESULTS / "eval" / "heldout__none.json").read_text())["per_doc"]}
    ocr = ocrguard.status()  # tesseract AND its deu/fra/ita data, checked up front (not just the binary)
    has_ocr = ocr["ok"]
    docs = sorted(docs, key=lambda d: (d.get("image_only", False), d["doc_id"]))  # text-layer documents first, scans last
    res = dict(n=len(docs), rederived=0, match=0, mismatches=[], unreachable=[], skipped_no_ocr=0, not_reached_budget=0,
               ocr_failed=[], tesseract=pdftext.tesseract_version(), poppler=pdftext.poppler_version(),
               ocr=dict(ok=ocr["ok"], reason=ocr["reason"], dir=ocr["dir"], pinned=ocr["pinned"],
                        unpinned=ocr["unpinned"], tessdata_commit=ocrguard.TESSDATA_COMMIT))
    for i, d in enumerate(docs):
        if time.time() - t0 > budget_s:
            res["not_reached_budget"] = len(docs) - i
            break
        if d.get("image_only") and not has_ocr:
            res["skipped_no_ocr"] += 1
            continue
        try:
            sha, path = pdftext.fetch_pdf(d["url"], expect_sha256=d["sha256"])
            t = pdftext.extract(sha, path)
        except pdftext.FetchError as e:
            if e.kind == ocrguard.KIND:  # a scan whose OCR did not run: counted and named, never scored as a null
                res["ocr_failed"].append(dict(doc_id=d["doc_id"], reason=e.detail[:200]))
                continue
            res["unreachable"].append(dict(doc_id=d["doc_id"], error=f"{type(e).__name__}: {str(e)[:100]}"))
            continue
        except Exception as e:  # unreachable host, robots.txt, changed source (sha mismatch), not a PDF
            res["unreachable"].append(dict(doc_id=d["doc_id"], error=f"{type(e).__name__}: {str(e)[:100]}"))
            continue
        r = rules.answer_date(t["pages"], t["image_only"])
        got = dict(status=r["status"], value=r.get("value") if r["status"] == "value" else None)
        want = committed[d["doc_id"]]
        want = dict(status=want["status"], value=want.get("value"))
        res["rederived"] += 1
        if got == want:
            res["match"] += 1
        else:
            res["mismatches"].append(dict(doc_id=d["doc_id"], committed=want, rederived=got, extractor_now=t["extractor"],
                                          extractor_committed=d.get("extractor")))
    res["secs"] = round(time.time() - t0, 1)
    return res


def _models(o: dict) -> str:
    if not o["ok"]:
        return "not available"
    if o["pinned"]:
        return f"= the measured tessdata_fast@{o['tessdata_commit'][:7]} (sha256 match)"
    return "differ from the measured tessdata_fast (sha256): " + "+".join(o["unpinned"])


def main(ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    if ctx.get("online") is False:
        return dict(status="SKIP", reason="network down: held-out PDFs not fetched; eval replayed the stored predictions")
    r = run()
    out = Path(ctx.get("out") or "out")
    out.mkdir(parents=True, exist_ok=True)
    (out / "rederive.json").write_text(json.dumps(r, indent=1))
    s = (f"rules arm re-derived from source PDFs (sha256-verified) for {r['rederived']}/{r['n']} held-out documents: "
         f"{r['match']} match the committed predictions, {len(r['mismatches'])} differ; {len(r['unreachable'])} unreachable, "
         f"{r['not_reached_budget']} not reached in the time budget, {r['skipped_no_ocr']} scans skipped (OCR not ready"
         f"{': ' + r['ocr']['reason'] if r['skipped_no_ocr'] and r['ocr']['reason'] else ''}), "
         f"{len(r['ocr_failed'])} scans ocr_failed; OCR models {_models(r['ocr'])}")
    loud = r["skipped_no_ocr"] or r["ocr_failed"]
    status = "SKIP" if r["rederived"] == 0 else ("PASS" if not (r["mismatches"] or loud) else "WARN")
    return dict(status=status, summary=s, **{k: r[k] for k in ("rederived", "match", "n", "secs", "ocr")},
                mismatches=r["mismatches"][:20], ocr_failed=r["ocr_failed"][:20], skipped_no_ocr=r["skipped_no_ocr"])


if __name__ == "__main__":
    r = run()
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else RESULTS / "eval" / "rederive_local.json"
    p.write_text(json.dumps(dict(r, note="local measurement; `make run` writes out/rederive.json"), indent=1))
    print({k: v for k, v in r.items() if k not in ("mismatches", "unreachable")}, "mismatches", len(r["mismatches"]),
          "unreachable", len(r["unreachable"]))
