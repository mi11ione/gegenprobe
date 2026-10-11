"""Command line for the Q/A extractor (src/gegenprobe/qa): one affair = the member's question document + the executive's
answer document.

  python -m gegenprobe.qa_cli --question Q.pdf --answer A.pdf [--affair-type TYPE] [--lang de|fr|it] [--json]
                              [--body KEY] [--anchors FILE] [--explain]
  python -m gegenprobe.qa_cli --opd-text-question Q.txt --opd-text-answer A.json [...]

Each document is a PDF (local path or URL; a URL is fetched politely, robots.txt under RFC 9309, into the cache) or
OPD's stored text (`--opd-text-*`: plain text, or a docs-export JSON row with a `text` field). Either document may be
left out. Output: the numbered questions, the answer passage for each, the submitter and co-signatories, the
executive's recommendation and the reasoning span, each with page + character span and the rule that decided, or a
typed null. `--json` prints everything: the flat view, the validated schema v0.1 records (QAItem, Actor,
recommendation, reasoning) and what the rules left open.

The frozen extractor (src/gegenprobe/qa, LOCK6) decides first; an unlocked post-processing layer (gegenprobe/qa_post.py)
then corrects what the frozen rules get wrong on unfamiliar layouts: a motion's dash-bullet demand as one item, the
reasoning without the reprinted member's text and without the closing block (signature, distribution list), signature
lists ("Unterschriften: 1. Name, 2. Name ... (9)"), a recommendation printed under an "Antrag des Regierungsrates"
heading, headings like "3.1 Zu Frage 1:". `--body` checks rule coverage as `convert` does (outside it: values flagged
needs_review, an open recommendation becomes no_rules_for_body); `--anchors FILE` is the same per-parliament file as
`convert --anchors` (recommendation phrases, confirm_rules, affair_types, closing, reprint_headings); `--explain` lists
the rules and post steps per field.

Rules only: no model is called. (The Apertus closed-set pointer arm of P5 is run by eval/gold6/run6.py; its θ is fitted
to one served build.) Fields the rules leave open are listed under `left_open` / "left open" for a reviewer.

OPD's stored text has no page breaks (OPD extracts the whole PDF into one string), so it is read as ONE page: spans say
page 1, and character offsets are offsets into OPD's stored text as given. If the text does contain form feeds (\\f),
they are taken as page breaks. The output says which applies, per document.

Exit codes: 0 extracted; 2 bad input (unknown --affair-type, no document, a file that is not a PDF, a document that could
not be fetched or read: the typed failure kind is printed, as in `python -m gegenprobe convert`; a malformed --anchors
file).
Docs: docs/qa.md ("Run it on your own affair").
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

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
    """What the rules did not decide (arm R residue), phrased for a reviewer, plus an open recommendation the post layer
    could not settle (no_rules_for_body, or not_in_document without --body)."""
    r = out["residue"]
    v = out["view"]
    items = []
    rec = (out.get("records") or {}).get("recommendation") or {}
    if r.get("pair"):
        open_n = [a["n"] for a in v["answers"] if a["span"] is None]
        items.append(dict(field="answers", count=r["pair"], questions=open_n,
                          reason="no answer heading or reprinted question marks which passage answers these questions"))
    if r.get("submitter"):
        items.append(dict(field="submitter", count=1, reason="no rule found the submitter's printed name"))
    if r.get("recommendation"):
        items.append(dict(field="recommendation", count=1, reason="candidate recommendation sentences conflict"))
    elif rec.get("kind") == "null" and rec.get("null_reason") == "no_rules_for_body":
        items.append(dict(field="recommendation", count=1, reason=rec.get("evidence")))
    elif rec.get("kind") == "null" and rec.get("null_reason") == "not_in_document" and \
            any(x["field"] == "recommendation" for x in out.get("review") or []):
        items.append(dict(field="recommendation", count=1, reason="no recommendation sentence found by the rules on a "
                          "layout whose coverage was not checked (no --body): confirm the null"))
    return items


def run(q_pages, a_pages, lang: str, affair_type: str | None, docs: dict, body: str | None = None,
        settings: dict | None = None) -> dict:
    from . import qa_post
    from .qa import extract as X

    q_id, a_id = docs["question"].get("doc_id", "question"), docs["answer"].get("doc_id", "answer")
    qp, nq = qa_post.prepare(q_pages) if q_pages else (q_pages, 0)
    ap, na = qa_post.prepare(a_pages) if a_pages else (a_pages, 0)
    out = X.extract(qp, ap, lang, None, q_id=q_id, a_id=a_id, affair_type=affair_type)
    post = qa_post.apply(out, q_pages, a_pages, affair_type=affair_type, body=body, settings=settings, q_id=q_id,
                         a_id=a_id, prepared=nq + na)
    res = dict(status="ok", tool=X.VERSION, post_layer=POST_VERSION, mode="rules_only", language=lang,
               affair_type=affair_type, body=body, documents=docs, view=post["view"], records=post["records"],
               rules=post["rules"], left_open=left_open(post), model_calls=len(out["pointer"]),
               rules_coverage=post["rules_coverage"], needs_review=bool(post["review"]), review_reasons=post["review"],
               frozen=dict(view=out["view"], rules=out["rules"]))
    res["explain"] = explain(res, out, post, settings)
    return res


POST_VERSION = "gegenprobe-qa-post-0.1"


def explain(res: dict, out: dict, post: dict, settings: dict | None) -> dict:
    """Per field: the frozen rule that decided, then every post step tried and what it did."""
    from .convert import overlay

    fields = dict(questions=("questions",), answers=("pairing",), reasoning=("reply",), people=("people",),
                  recommendation=("recommendation",))
    ex = dict(cache=overlay.cache_info(), rules_coverage=post["rules_coverage"],
              settings_file=(settings or {}).get("file"), fields={})
    for f, keys in fields.items():
        steps = [dict(step="frozen rule (LOCK6)", result=str(out["rules"].get(keys[0])))]
        steps += [dict(step=x["step"], result=x["result"]) for x in post["post"] if x["field"] == f or
                  (f == "answers" and x["field"] == "answers")]
        if post["rules"].get(keys[0]) != out["rules"].get(keys[0]):
            steps.append(dict(step="decided by", result=str(post["rules"].get(keys[0]))))
        ex["fields"][f] = steps
    cov = [x for x in post["post"] if x["field"] == "coverage"]
    if cov:
        ex["fields"]["coverage"] = [dict(step=x["step"], result=x["result"]) for x in cov]
    return ex


def render_explain(ex: dict) -> str:
    c = ex["cache"]
    lines = [f"cache: {c['work']}  ({c['note']})"]
    cov = ex["rules_coverage"]
    lines.append(f"rules coverage: body={cov['body']} -> {cov['status']}: {cov['note']}")
    if ex.get("settings_file"):
        lines.append(f"settings/anchors file: {ex['settings_file']}")
    for f, steps in ex["fields"].items():
        lines.append(f"{f}:")
        for s in steps:
            lines.append(f"  {s['step']:<32} {s['result']}")
    return "\n".join(lines)


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
    rr = res["records"]["recommendation"]
    if rr.get("kind") == "null" and v["recommendation"] != "not_applicable":
        rec = f"null ({rr.get('null_reason')}: {rr.get('evidence')})"
    else:
        rec = v["recommendation"]
    lines.append(f"recommendation: {rec}{ev}  rule {res['rules'].get('recommendation')}")
    r = v["reasoning"]
    lines.append(f"reasoning: {_where(docs['answer'], r)}  {_snip(txt(r), 70)}" if r else "reasoning: (null)")
    if res["left_open"]:
        lines.append("")
        lines.append("left open (review):")
        for x in res["left_open"]:
            qs = f" (questions {', '.join(map(str, x['questions']))})" if x.get("questions") else ""
            lines.append(f"  {x['field']}{qs}: {x['reason']}")
    if res.get("review_reasons"):
        lines.append("")
        lines.append("needs review:")
        for x in res["review_reasons"]:
            lines.append(f"  {x['field']}: {x['reason']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from .convert import affair_types, body_settings, overlay

    ap = argparse.ArgumentParser(prog="python -m gegenprobe.qa_cli",
                                 description="Questions, answers, people, recommendation and reasoning of one affair "
                                 "(rules only, no model). See docs/qa.md.")
    ap.add_argument("--question", metavar="PDF", help="the member's question document: PDF path or URL")
    ap.add_argument("--answer", metavar="PDF", help="the executive's answer document: PDF path or URL")
    ap.add_argument("--opd-text-question", metavar="FILE", help="instead of --question: OPD's stored text (plain text or a "
                    "docs-export JSON row with 'text'); read as one page (OPD text has no page breaks)")
    ap.add_argument("--opd-text-answer", metavar="FILE", help="instead of --answer: OPD's stored text, as above")
    ap.add_argument("--affair-type", metavar="TYPE",
                    help="affair type (vocabulary key, DE/FR/IT/EN label, OPD's harmonised name, or an OPD type name such "
                    "as Auftrag; a settings file's affair_types for --body). Interpellation / Question / Question time "
                    "make the recommendation not_applicable when the question document does not name its type itself")
    ap.add_argument("--body", help="OPD body key (e.g. SO, BE, 261): checks rule coverage as convert does; outside it every "
                    "rule value is flagged needs_review and an open recommendation is no_rules_for_body")
    ap.add_argument("--anchors", metavar="JSON", help="the per-parliament settings file shared with `convert --anchors`: "
                    "recommendation phrases, confirm_rules, affair_types, closing, reprint_headings (docs/qa.md)")
    ap.add_argument("--explain", action="store_true", help="list, per field, the frozen rule and every post step tried "
                    "(stderr; --json adds an 'explain' key)")
    ap.add_argument("--lang", choices=["de", "fr", "it"], help="language (guessed from the text if omitted)")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON (view, schema records, left open)")
    a = ap.parse_args(argv)
    settings = None
    if a.anchors:
        try:
            settings = body_settings.load(a.anchors)
        except overlay.AnchorError as e:
            print(str(e), file=sys.stderr)
            return 2
    try:
        a.affair_type = affair_types.normalize(a.affair_type, body_settings.type_aliases(settings, a.body))
    except affair_types.UnknownAffairType as e:
        ap.error(f"argument --affair-type: {e}")
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
    res = run(q_pages, a_pages, lang, a.affair_type, dict(question=qd, answer=ad), body=a.body, settings=settings)
    ex = res.pop("explain")
    if a.explain:
        res["explain"] = ex
    if a.json:
        json.dump(res, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(render(res, q_pages, a_pages))
    warn = overlay.coverage_warning(res["rules_coverage"])
    if warn:
        print(warn.replace("Rows are marked needs_review and open fields get null_reason no_rules_for_body",
                           "Values are flagged needs_review and an open recommendation is no_rules_for_body"),
              file=sys.stderr)
    elif not a.body:
        print("note: no --body given, so rule coverage (data/convert/rules_coverage.json) was not checked", file=sys.stderr)
    if a.explain:
        print(render_explain(ex), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
