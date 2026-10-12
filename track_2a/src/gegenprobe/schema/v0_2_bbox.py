"""Page geometry for the converter records' located values (post hoc, R20): a bounding box in PDF points for every
character span, for a side-by-side PDF view that highlights a value without re-mapping it.

    python -m gegenprobe.schema.v0_2_bbox detect    for every located value (document, page, char_start, char_end) of the
                                                    converter's records (results/schema/v0_2/{p3,p3b,p5,fed}_records.jsonl)
                                                    run `pdftotext -bbox` on that page of the cached PDF, align its words
                                                    with the cached text the span indexes, character by character (the
                                                    same pdftotext, raw order) and write the union of the words the span covers ->
                                                    results/schema/v0_2/span_bboxes.jsonl
    python -m gegenprobe.schema.v0_2_bbox --check   exit 1 if a fresh run differs from the committed file (SKIP when the
                                                    PDFs are not cached)

The records stay as they are: schema v0.2 is strict (extra fields forbidden, schema/gegenprobe_schema_v0_2.py frozen),
so the box sits in this sidecar, keyed by the record (set, body, OPD id), the value's path and its span; a reader joins
on (path, doc, page, char_start, char_end). Coordinates: PDF points, origin top left, as pdftotext -bbox reports them
(`page_size` gives the page's width and height). `bbox` is [x0, y0, x1, y1]; `lines` the box per text line when the
span runs over several. Status per span:
  exact        every non-space character of the span was aligned to a character of a pdftotext -bbox word (the
               box is the union of those words)
  partial      some were (the box covers their words)
  unaligned    none was
  ocr_text     the span indexes an OCR text of a scanned page (no text layer; tesseract boxes are not computed here)
  no_pdf       the document is a text record (the federal cell's OPD texts export), not a PDF
  not_cached   the PDF or its text is not in the work cache
`text_ok` says whether the cached text at the span still hashes to the record's quote / quote_sha256.
No network, no model; validation_all.json's `span_bboxes` block counts the coverage from the committed file.
"""
from __future__ import annotations

import collections
import difflib
import hashlib
import html
import json
import re
import subprocess
import sys

from ..paths import PDF_CACHE
from . import v0_2_roles
from .p8_v0_2 import OUT

FILE = OUT / "span_bboxes.jsonl"
SETS = {"p3": "p3_records.jsonl", "p3b": "p3b_records.jsonl", "p5": "p5_records.jsonl", "fed": "fed_records.jsonl"}
WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">')
COORDS = "PDF points, origin top left (pdftotext -bbox)"


def _walk(o, path: str = ""):
    if isinstance(o, dict):
        if o.get("kind") == "value" and "route" in o:
            if o.get("page") is not None and o.get("char_start") is not None and o.get("char_end") is not None:
                yield path, o
            return
        for k, v in o.items():
            if k != "empty_reasons":
                yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{path}.{i}")


def spans(records: dict[str, list[dict]]) -> list[dict]:
    """Every located value of the records: set, record key, path, doc, page, span, its pin (quote / quote_sha256)."""
    out = []
    for k, recs in records.items():
        for r in recs:
            for path, v in _walk(r):
                out.append(dict(set=k, body=r["body"]["key"], opd_id=r["ref"]["opd_id"], path=path, doc=v["doc"],
                                page=v["page"], char_start=v["char_start"], char_end=v["char_end"],
                                quote=v.get("quote"), quote_sha256=v.get("quote_sha256")))
    return out


def load_records() -> dict[str, list[dict]]:
    return {k: [json.loads(x) for x in (OUT / n).read_text(encoding="utf-8").splitlines() if x.strip()]
            for k, n in SETS.items()}


def _doc_index() -> dict[str, dict]:
    """opd:<doc_id> -> the document row (sha256, image_only) of the P3, P3b and P5 affairs."""
    out = {}
    for _, path in v0_2_roles.SETS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                for d in json.loads(line)["docs"]:
                    out.setdefault(f"opd:{d['doc_id']}", d)
    return out


def page_words(pdf, page: int) -> tuple[list[tuple[float, float, float, float, str]], tuple[float, float]]:
    out = subprocess.run(["pdftotext", "-bbox", "-enc", "UTF-8", "-f", str(page), "-l", str(page), str(pdf), "-"],
                         capture_output=True, check=True, text=True, encoding="utf-8")
    m = PAGE.search(out.stdout)
    size = (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)
    words = [(float(a), float(b), float(c), float(d), html.unescape(w)) for a, b, c, d, w in WORD.findall(out.stdout)]
    return words, size


def align(text: str, words: list) -> dict[int, int]:
    """Character offset of the text -> index of the pdftotext -bbox word holding that character, over the non-space
    characters of both (the raw text joins a word hyphenated at a line end, "Wald-" + "gesetz" -> "Waldgesetz"; the
    words keep the hyphen), by the matching blocks of the two character sequences."""
    a_pos = [i for i, ch in enumerate(text) if not ch.isspace()]
    a = "".join(text[i] for i in a_pos)
    b_word, b = [], []
    for j, w in enumerate(words):
        for ch in w[4]:
            if not ch.isspace():
                b.append(ch)
                b_word.append(j)
    b = "".join(b)
    if a == b:
        return {a_pos[k]: b_word[k] for k in range(len(a))}
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    mp = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            mp[a_pos[blk.a + k]] = b_word[blk.b + k]
    return mp


def _r(x: float) -> float:
    return round(x, 2)


def box_of(s: int, e: int, text: str, mp: dict[int, int], words) -> dict:
    chars = [i for i in range(s, min(e, len(text))) if not text[i].isspace()]
    hit = sorted({mp[i] for i in chars if i in mp})
    if not chars or not hit:
        return dict(status="unaligned", n_words=0)
    ws = [words[j] for j in hit]
    lines: list[list[float]] = []
    for w in ws:
        if lines and abs(w[1] - lines[-1][1]) < 2 and abs(w[3] - lines[-1][3]) < 2:
            ln = lines[-1]
            ln[0], ln[2] = min(ln[0], w[0]), max(ln[2], w[2])
        else:
            lines.append([w[0], w[1], w[2], w[3]])
    out = dict(status="exact" if all(i in mp for i in chars) else "partial", n_words=len(hit),
               bbox=[_r(min(w[0] for w in ws)), _r(min(w[1] for w in ws)), _r(max(w[2] for w in ws)),
                     _r(max(w[3] for w in ws))])
    if len(lines) > 1:
        out["lines"] = [[_r(x) for x in ln] for ln in lines]
    return out


def _text_ok(text: str, sp: dict) -> bool | None:
    seg = text[sp["char_start"]:sp["char_end"]]
    if sp.get("quote_sha256"):
        return hashlib.sha256(seg.encode("utf-8")).hexdigest() == sp["quote_sha256"]
    if sp.get("quote"):
        q = sp["quote"]
        return seg == q or re.sub(r"\s+", " ", seg) == re.sub(r"\s+", " ", q) or seg.startswith(q[:200])
    return None


def detect() -> str:
    docs = _doc_index()
    pages_cache: dict[tuple[str, int], tuple] = {}
    text_cache: dict[str, tuple | None] = {}
    rows = []
    for sp in spans(load_records()):
        key = {k: sp[k] for k in ("set", "body", "opd_id", "path", "doc", "page", "char_start", "char_end")}
        d = docs.get(sp["doc"])
        if sp["doc"].startswith("opd-texts:") or d is None:
            rows.append(dict(key, status="no_pdf"))
            continue
        sha = d["sha256"]
        if sha not in text_cache:
            text_cache[sha] = v0_2_roles.pages_of(sha, bool(d.get("image_only")))
        got = text_cache[sha]
        pdf = PDF_CACHE / f"{sha}.pdf"
        if got is None or not pdf.exists():
            rows.append(dict(key, status="not_cached"))
            continue
        pages, ext = got
        text = pages[sp["page"] - 1] if sp["page"] <= len(pages) else ""
        ok = _text_ok(text, sp)
        if ext.startswith("tesseract"):
            rows.append(dict(key, status="ocr_text", text_ok=ok))
            continue
        pk = (sha, sp["page"])
        if pk not in pages_cache:
            words, size = page_words(pdf, sp["page"])
            pages_cache[pk] = (words, size, align(text, words))
        words, size, mp = pages_cache[pk]
        b = box_of(sp["char_start"], sp["char_end"], text, mp, words)
        rows.append(dict(key, **b, page_size=[_r(size[0]), _r(size[1])], coords=COORDS, text_ok=ok))
    rows.sort(key=lambda r: (r["set"], r["body"], r["opd_id"], r["path"]))
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)


def check_detections() -> dict:
    try:
        text = detect()
    except (OSError, subprocess.CalledProcessError) as e:
        return dict(status="SKIP", summary=f"span boxes not re-derived ({e})")
    if '"status": "not_cached"' in text:
        return dict(status="SKIP", summary="span boxes not re-derived: PDFs not cached")
    same = FILE.exists() and FILE.read_text(encoding="utf-8") == text
    return dict(status="PASS" if same else "FAIL",
                summary=f"span boxes re-derived for {text.count(chr(10))} located values: "
                        + ("identical to the committed file" if same else "DIFFER from the committed file"))


def block(records: dict[str, list[dict]]) -> dict:
    """validation_all.json's `span_bboxes`: coverage of the committed boxes over the located values of the records."""
    rows = {}
    if FILE.exists():
        for line in FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[(r["set"], r["opd_id"], r["path"], r["doc"], r["page"], r["char_start"], r["char_end"])] = r
    per, n_all = collections.defaultdict(collections.Counter), collections.Counter()
    for sp in spans(records):
        r = rows.get((sp["set"], sp["opd_id"], sp["path"], sp["doc"], sp["page"], sp["char_start"], sp["char_end"]))
        st = r["status"] if r else "missing"
        per[sp["set"]][st] += 1
        n_all[st] += 1
        if r and r.get("text_ok") is False:
            n_all["text_mismatch"] += 1
    total = sum(v for k, v in n_all.items() if k != "text_mismatch")
    with_box = n_all["exact"] + n_all["partial"]
    pdf_text = total - n_all["ocr_text"] - n_all["no_pdf"]
    sample = next((r for r in rows.values() if r["set"] == "p3" and r["opd_id"] == 39369
                   and r["path"] == "qa.0.answer_date"), None)
    return dict(
        label="POST HOC (R20): page bounding boxes for the located values (sidecar; the records are unchanged)",
        file="results/schema/v0_2/span_bboxes.jsonl (python -m gegenprobe.schema.v0_2_bbox detect)",
        coords=COORDS, n_spans=total, with_bbox=with_box, exact=n_all["exact"], partial=n_all["partial"],
        on_pdf_text_layer=pdf_text, with_bbox_of_pdf_text_layer=f"{with_box}/{pdf_text}",
        statuses=dict(sorted(n_all.items())), sets={k: dict(sorted(c.items())) for k, c in sorted(per.items())},
        sample=sample,
    )


def main(argv: list[str]) -> int:
    if argv[:1] == ["detect"]:
        FILE.write_text(detect(), encoding="utf-8")
        print(FILE)
        return 0
    if "--check" in argv:
        c = check_detections()
        print(c["summary"])
        return 1 if c["status"] == "FAIL" else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
