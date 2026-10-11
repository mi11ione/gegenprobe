"""Command line for the Q/A extractor (src/gegenprobe/qa): one affair = the member's question document + the executive's
answer document.

  python -m gegenprobe.qa_cli --question Q.pdf --answer A.pdf [--affair-type TYPE] [--lang de|fr|it] [--json]
  python -m gegenprobe.qa_cli --opd-text-question Q.txt --opd-text-answer A.json [...]

Each document is a PDF (local path or URL; a URL is fetched politely, robots.txt under RFC 9309, into the cache) or
OPD's stored text (`--opd-text-*`: plain text, or a docs-export JSON row with a `text` field). Either document may be
left out. Output: the numbered questions, the answer passage for each, the submitter and co-signatories, the
executive's recommendation and the reasoning span, each with page + character span and the rule that decided, or a
typed null. `--json` prints everything: the flat view, the validated schema v0.1 records (QAItem, Actor,
recommendation, reasoning) and what the rules left open.

Rules only: no model is called. (The Apertus closed-set pointer arm of P5 is run by eval/gold6/run6.py; its θ is fitted
to one served build.) Fields the rules leave open are listed under `left_open` / "left open" for a reviewer.

OPD's stored text has no page breaks (OPD extracts the whole PDF into one string), so it is read as ONE page: spans say
page 1, and character offsets are offsets into OPD's stored text as given. If the text does contain form feeds (\\f),
they are taken as page breaks. The output says which applies, per document.

Exit codes: 0 extracted; 2 bad input (unknown --affair-type, no document, a file that is not a PDF, a document that could
not be fetched or read: the typed failure kind is printed, as in `python -m gegenprobe convert`).
Docs: docs/qa.md ("Run it on your own affair").
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ONE_PAGE_NOTE = ("OPD stored text has no page breaks: read as one page; spans say page 1 and character offsets are "
                 "offsets into the stored text as given")
FF_NOTE = "OPD stored text: form feeds (\\f) taken as page breaks"


class InputError(Exception):
    def __init__(self, kind: str, reason: str, role: str):
        super().__init__(reason)
        self.kind, self.reason, self.role = kind, reason, role


def read_opd_text(path: str) -> tuple[list[str], str, str]:
    """-> (pages, doc_id, note). Plain text, or a docs-export JSON row ({"id": ..., "text": ...})."""
    from .convert import opdtext

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {path}")
    text = opdtext.load(path)
    doc_id = f"file:{p.name}"
    s = p.read_text(encoding="utf-8").lstrip()
    if s.startswith("{"):
        try:
            row = json.loads(s.splitlines()[0] if "\n" in s and not s.rstrip().endswith("}") else s)
            if row.get("id") is not None:
                doc_id = f"opd:{row['id']}"
        except (ValueError, AttributeError):
            pass
    if "\f" in text:
        pages = text.split("\f")
        if pages and not pages[-1].strip():
            pages = pages[:-1]
        return pages, doc_id, FF_NOTE
    return [text], doc_id, ONE_PAGE_NOTE


def read_pdf(source: str) -> tuple[list[str], str, dict]:
    """-> (pages, doc_id, info). Local path or URL; the same fetch, cache and text extraction as `convert`."""
    from . import pdftext
    from .convert import batch

    sha, path = batch.get_document(source)
    t = pdftext.extract(sha, path)
    return t["pages"], f"sha256:{sha[:16]}", dict(sha256=sha, extractor=t["extractor"], image_only=t["image_only"])


def load_role(role: str, pdf: str | None, opd_text: str | None) -> tuple[list[str] | None, dict]:
    if pdf and opd_text:
        raise InputError("usage", f"give either --{role} or --opd-text-{role}, not both", role)
    if not pdf and not opd_text:
        return None, dict(role=role, given=False)
    try:
        if opd_text:
            pages, doc_id, note = read_opd_text(opd_text)
            return pages, dict(role=role, given=True, source=opd_text, kind="opd_text", doc_id=doc_id, pages=len(pages),
                               chars=sum(map(len, pages)), extractor="opd-text", note=note)
        pages, doc_id, info = read_pdf(pdf)
        return pages, dict(role=role, given=True, source=pdf, kind="pdf", doc_id=doc_id, pages=len(pages), **info)
    except subprocess.CalledProcessError as e:
        raise InputError("text_failed", f"pdftotext/tesseract failed: {e}", role) from None
    except InputError:
        raise
    except Exception as e:  # same typed kinds as the convert CLI (robots_disallowed, not_a_pdf, file_not_found, ...)
        from .convert import output
        kind, reason = output.classify(e)
        if kind == "not_a_pdf" and pdf and not re.match(r"https?://", pdf):
            reason += f" (for OPD's stored text use --opd-text-{role})"
        raise InputError(kind, reason, role) from None


def left_open(out: dict) -> list[dict]:
    """What the rules did not decide (arm R residue), phrased for a reviewer."""
    r = out["residue"]
    v = out["view"]
    items = []
    if r.get("pair"):
        open_n = [a["n"] for a in v["answers"] if a["span"] is None]
        items.append(dict(field="answers", count=r["pair"], questions=open_n,
                          reason="no answer heading or reprinted question marks which passage answers these questions"))
    if r.get("submitter"):
        items.append(dict(field="submitter", count=1, reason="no rule found the submitter's printed name"))
    if r.get("recommendation"):
        items.append(dict(field="recommendation", count=1, reason="candidate recommendation sentences conflict"))
    return items


def run(q_pages, a_pages, lang: str, affair_type: str | None, docs: dict) -> dict:
    from .qa import extract as X

    out = X.extract(q_pages, a_pages, lang, None, q_id=docs["question"].get("doc_id", "question"),
                    a_id=docs["answer"].get("doc_id", "answer"), affair_type=affair_type)
    return dict(status="ok", tool=X.VERSION, mode="rules_only", language=lang, affair_type=affair_type,
                documents=docs, view=out["view"], records=out["records"], rules=out["rules"], left_open=left_open(out),
                model_calls=len(out["pointer"]))


# ---------------------------------------------------------------- human-readable report
def _snip(text: str, n: int = 90) -> str:
    s = " ".join(text.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _where(doc, span: dict | None) -> str:
    if not span:
        return "-"
    p0, c0 = doc.loc(span["g_start"])
    p1, c1 = doc.loc(span["g_end"])
    return f"p{p0}:{c0}-{c1}" if p0 == p1 else f"p{p0}:{c0} - p{p1}:{c1}"


def render(res: dict, q_pages, a_pages) -> str:
    from .qa.text import Doc

    docs = {"question": Doc("question", "q", q_pages) if q_pages else None,
            "answer": Doc("answer", "a", a_pages) if a_pages else None}
    v = res["view"]
    lines = []
    for role in ("question", "answer"):
        d = res["documents"][role]
        if not d["given"]:
            lines.append(f"{role}: (not given)")
            continue
        extra = f"; {d['note']}" if d.get("note") else ""
        lines.append(f"{role}: {d['source']} [{d['kind']}, {d['pages']} page(s), {d['doc_id']}{extra}]")
    lines.append(f"language {res['language']}; affair type {res['affair_type'] or '(not given)'}; rules only, "
                 f"{res['model_calls']} model calls")
    lines.append("")

    def txt(span):
        d = docs[span["doc"]]
        return d.text[span["g_start"]:span["g_end"]]

    lines.append(f"questions ({v['question_style']}): {len(v['questions'])}")
    for q, a in zip(v["questions"], v["answers"]):
        lines.append(f"  Q{q['n']}  {_where(docs['question'], q['span']):<18} {_snip(txt(q['span']))}")
        if a["span"]:
            joint = f" (joint with {', '.join(map(str, a['joint_with']))})" if a.get("joint_with") else ""
            lines.append(f"  A{q['n']}  {_where(docs['answer'], a['span']):<18} {_snip(txt(a['span']))}{joint}")
        else:
            lines.append(f"  A{q['n']}  -                  (null: no passage marked as the answer to this question)")
    lines.append(f"answer style: {v['answer_style']}")
    sub = v["submitter"]
    if sub:
        lines.append(f"submitter: {sub['name']}  [{sub['span']['doc']} {_where(docs[sub['span']['doc']], sub['span'])}, "
                     f"rule {sub.get('rule')}]")
    else:
        lines.append("submitter: (null)")
    if v["co_signatories"]:
        lines.append("co-signatories: " + ", ".join(c["name"] for c in v["co_signatories"]))
    rs = v.get("recommendation_span")
    ev = f"  [{rs['doc']} {_where(docs[rs['doc']], rs)}: {_snip(txt(rs), 70)}]" if rs else ""
    rec = v["recommendation"] if v["recommendation"] is not None else "(null: left open)"
    lines.append(f"recommendation: {rec}{ev}  rule {res['rules'].get('recommendation')}")
    r = v["reasoning"]
    lines.append(f"reasoning: {_where(docs['answer'], r)}  {_snip(txt(r), 70)}" if r else "reasoning: (null)")
    if res["left_open"]:
        lines.append("")
        lines.append("left open (review):")
        for x in res["left_open"]:
            qs = f" (questions {', '.join(map(str, x['questions']))})" if x.get("questions") else ""
            lines.append(f"  {x['field']}{qs}: {x['reason']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from .convert import affair_types

    ap = argparse.ArgumentParser(prog="python -m gegenprobe.qa_cli",
                                 description="Questions, answers, people, recommendation and reasoning of one affair "
                                 "(rules only, no model). See docs/qa.md.")
    ap.add_argument("--question", metavar="PDF", help="the member's question document: PDF path or URL")
    ap.add_argument("--answer", metavar="PDF", help="the executive's answer document: PDF path or URL")
    ap.add_argument("--opd-text-question", metavar="FILE", help="instead of --question: OPD's stored text (plain text or a "
                    "docs-export JSON row with 'text'); read as one page (OPD text has no page breaks)")
    ap.add_argument("--opd-text-answer", metavar="FILE", help="instead of --answer: OPD's stored text, as above")
    ap.add_argument("--affair-type", type=affair_types.arg_type, metavar="TYPE",
                    help="affair type (vocabulary key, DE/FR/IT/EN label or OPD's harmonised name). Interpellation / "
                    "Question / Question time make the recommendation not_applicable when the question document does "
                    "not name its type itself")
    ap.add_argument("--lang", choices=["de", "fr", "it"], help="language (guessed from the text if omitted)")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON (view, schema records, left open)")
    a = ap.parse_args(argv)
    if not (a.question or a.answer or a.opd_text_question or a.opd_text_answer):
        ap.print_usage(sys.stderr)
        print("give at least one document: --question/--opd-text-question and/or --answer/--opd-text-answer",
              file=sys.stderr)
        return 2
    try:
        q_pages, qd = load_role("question", a.question, a.opd_text_question)
        a_pages, ad = load_role("answer", a.answer, a.opd_text_answer)
    except InputError as e:
        if a.json:
            print(json.dumps(dict(status=e.kind, reason=e.reason, role=e.role), ensure_ascii=False))
        print(f"{e.role}: {e.kind}: {e.reason}", file=sys.stderr)
        return 2
    if not any(p.strip() for p in (q_pages or []) + (a_pages or [])):
        print("the documents contain no text (an image-only scan without OCR, or an empty OPD text)", file=sys.stderr)
        return 2
    if a.lang:
        lang = a.lang
    else:
        from .convert.batch import guess_lang
        lang = guess_lang("\n".join((q_pages or []) + (a_pages or [])))
    res = run(q_pages, a_pages, lang, a.affair_type, dict(question=qd, answer=ad))
    if a.json:
        json.dump(res, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(render(res, q_pages, a_pages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
