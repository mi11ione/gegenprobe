"""Finding for OPD: question and answer documents of one affair linked in different languages (post hoc, no model, no
network).

Why: P5's rules paired 0 of 11 Valais answers (docs/qa.md). The cause is not unmarked answers: in all 4 Valais P5 affairs
OPD links the member's question as the French file (`INT_…_DEP_Final_FR.pdf`) and the government's answer as the German
file (`INT_…_ANT_DE.pdf` / `_ANT_D1.pdf`). The frozen pairing rule (qa/answers.py `_chain`) accepts a bare number chain
("1.", "2." …) only where the answer reprints question n (4-word shingle overlap >= 0.25 with the member's text), and
falls back to finding the reprinted questions; across languages both checks find nothing. This module counts how often
that pairing occurs across OPD's exports and re-scores the Valais pairing by question number (post hoc).

Definitions
  affair in scope   OPD harmonised type Interpellation, Motion, Postulate, Question or Question time (census/defs.py
                    SCOPE_TYPES), from data/census/affairs.tsv.gz
  question document the frozen P3 pairing (eval/gold3/sample.py `pair_type`, LOCK3): OPD document name / category /
                    harmonised category classed "intervention"
  answer document   the same function classed "answer"
  signal A (OPD tag)  the `language` field of OPD's docs export (data/census/docs.tsv.gz `lang`; "de;fr" = both)
  signal B (file name) the language suffix of the document's URL file name (`_DE.pdf`, `_FR.pdf`, `_IT.pdf`, `_D1.pdf`,
                    `_F1.pdf`, `-de.pdf`, `-fr.pdf`, `-it.pdf`); needs the local docs metadata scan (GP_DOCS_META)
  signal C (text)   stop-word counts on the PDF text (the repair/ocr.py guess_lang word lists; >= 3 hits and twice the
                    runner-up), for the 209 gold-set affairs whose PDF text is cached locally (WORK/text)
  cross-language    an affair with >= 1 tagged question document and >= 1 tagged answer document where no language of a
                    question document is a language of an answer document (so no same-language pair exists in OPD)
  first-pair cross  the lowest-id question and lowest-id answer document (the P3/P5 sampling convention) differ

    python -m gegenprobe.findings.cross_language        -> results/findings/cross_language_links.json
"""
from __future__ import annotations

import collections
import csv
import glob
import gzip
import json
import re
import sys
from pathlib import Path

from ..census.defs import SCOPE_TYPES
from ..paths import DATA, DOCS_META, RESULTS, TEXT_CACHE

OUT = RESULTS / "findings" / "cross_language_links.json"
LANGS = ("de", "fr", "it", "rm")
URL_LANG = re.compile(r"(?:[_-](?P<a>de|fr|it)|_(?P<b>[dfi])\d)\.pdf$", re.I)
STOP = {  # repair/ocr.py STOP, unchanged
    "de": {"und", "der", "die", "das", "nicht", "ist", "mit", "für"},
    "fr": {"les", "des", "est", "pour", "dans", "que", "une", "par"},
    "it": {"della", "che", "per", "una", "sono", "delle", "nel", "con"},
}
GOLD_SETS = {  # gold sets with one question and one answer document per affair (ids, sha256; never text)
    "P3": DATA / "gold3" / "p3_affairs.jsonl",
    "P3b": DATA / "gold5" / "p3b_affairs.jsonl",
    "P5dev": DATA / "gold6" / "p5dev_affairs.jsonl",
    "P5": DATA / "gold6" / "p5_affairs.jsonl",
    "P8": DATA / "p8" / "p8_affairs.jsonl",
}


def _pair_type():
    from eval.gold3.sample import pair_type  # frozen (LOCK3); imports only regexes and the doc-type guess

    return pair_type


def _tsv(p: Path):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        yield from csv.DictReader(f, delimiter="\t")


def body_names() -> dict[str, str]:
    return {r["key"]: r["name"] for r in _tsv(DATA / "census" / "bodies.tsv.gz")}


def linked_docs() -> dict[tuple[str, str], dict[str, list[dict]]]:
    """(body, affair) -> {"question": [doc], "answer": [doc]} from the committed census tables."""
    scope = {r["id"]: r["type_h"] for r in _tsv(DATA / "census" / "affairs.tsv.gz") if r["type_h"] in SCOPE_TYPES}
    pt = _pair_type()
    out: dict = collections.defaultdict(lambda: {"question": [], "answer": []})
    for r in _tsv(DATA / "census" / "docs.tsv.gz"):
        if r["affair"] not in scope:
            continue
        d = dict(id=int(r["id"]), b=r["body"], a=int(r["affair"]), name=r["name"], cat=r["cat"] or None,
                 ch=r["cat_h"] or None, a_type=scope[r["affair"]],
                 tag=tuple(x for x in r["lang"].split(";") if x) or None)
        t = pt(d)
        if t:
            out[(r["body"], r["affair"])]["question" if t == "intervention" else "answer"].append(d)
    return out


def _langs(docs: list[dict], key: str) -> set[str]:
    return {lg for d in docs for lg in (d.get(key) or ())}


def classify(v: dict[str, list[dict]], key: str) -> str | None:
    """'same' | 'cross' | None (not evaluable on this signal); see module docstring."""
    ql, al = _langs(v["question"], key), _langs(v["answer"], key)
    if not ql or not al:
        return None
    return "same" if ql & al else "cross"


def first_pair_cross(v: dict[str, list[dict]], key: str) -> bool | None:
    q = min(v["question"], key=lambda d: d["id"])
    a = min(v["answer"], key=lambda d: d["id"])
    if not q.get(key) or not a.get(key):
        return None
    return not set(q[key]) & set(a[key])


def url_lang(url: str | None) -> str | None:
    m = URL_LANG.search((url or "").rsplit("/", 1)[-1])
    if not m:
        return None
    x = (m.group("a") or m.group("b")).lower()
    return {"d": "de", "f": "fr", "i": "it"}.get(x, x)


def add_url_signal(pairs: dict) -> bool:
    """Attach signal B (`url` key) from the local docs metadata scan; False when the scan is not present."""
    files = sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz")))
    if not files:
        return False
    want = {d["id"]: d for v in pairs.values() for role in v.values() for d in role}
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if '"url"' not in line:
                    continue
                d = json.loads(line)
                x = want.get(d["id"])
                if x is not None and "url_file" not in x:
                    x["url_file"] = (d.get("url") or "").rsplit("/", 1)[-1]
                    lg = url_lang(d.get("url"))
                    x["url"] = (lg,) if lg else None
    return True


def text_lang(text: str) -> str:
    w = collections.Counter(re.findall(r"[a-zàâäéèêëîïôöùûüç]+", text.lower()))
    score = sorted(((sum(w[s] for s in v), k) for k, v in STOP.items()), reverse=True)
    (best, lg), (second, _) = score[0], score[1]
    return lg if best >= 3 and best >= 2 * second else "unknown"


def cached_text(sha: str) -> str | None:
    """Text of a cached extraction (pdftotext first, then OCR); None if not cached. Reads the cache file only."""
    for p in sorted(TEXT_CACHE.glob(f"{sha}.pdftotext-*.json")) + sorted(TEXT_CACHE.glob(f"{sha}.tesseract-*.json")):
        pages = json.loads(p.read_text(encoding="utf-8")).get("pages") or []
        t = "\n".join(pages)
        if len(t.strip()) >= 200:
            return t
    return None


def gold_text_check(pairs: dict) -> dict | None:
    """Signal C on the gold-set affairs: text language of question and answer vs OPD's tag."""
    rows, seen = [], set()
    for name, p in GOLD_SETS.items():
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if r["affair_id"] in seen:
                continue
            docs = {d["role"]: d for d in r["docs"]}
            if "question" not in docs or "answer" not in docs:
                continue
            seen.add(r["affair_id"])
            tq, ta = cached_text(docs["question"]["sha256"]), cached_text(docs["answer"]["sha256"])
            tags = {}
            v = pairs.get((r["body"], str(r["affair_id"])))
            for role in ("question", "answer"):
                did = int(docs[role]["doc_id"])
                hit = next((d for d in (v or {}).get(role, []) if d["id"] == did), None)
                tags[role] = "+".join(hit["tag"]) if hit and hit.get("tag") else None
            rows.append(dict(set=name, body=r["body"], affair_id=r["affair_id"],
                             q_doc=int(docs["question"]["doc_id"]), a_doc=int(docs["answer"]["doc_id"]),
                             q_text=text_lang(tq) if tq else None, a_text=text_lang(ta) if ta else None,
                             q_tag=tags["question"], a_tag=tags["answer"]))
    have = [r for r in rows if r["q_text"] and r["a_text"]]
    if not have:
        return None
    known = [r for r in have if "unknown" not in (r["q_text"], r["a_text"])]
    cross = [r for r in known if r["q_text"] != r["a_text"]]
    tagged = [(r, role) for r in have for role in ("q", "a") if r[f"{role}_tag"] and r[f"{role}_text"] != "unknown"]
    tag_wrong = [dict(set=r["set"], body=r["body"], affair_id=r["affair_id"], doc=r[f"{role}_doc"],
                      role={"q": "question", "a": "answer"}[role], opd_tag=r[f"{role}_tag"], text=r[f"{role}_text"])
                 for r, role in tagged if r[f"{role}_text"] not in r[f"{role}_tag"].split("+")]
    return dict(
        affairs=len(rows), with_both_texts=len(have), both_languages_detected=len(known),
        cross_language_by_text=len(cross),
        cross_language_by_body=dict(collections.Counter(r["body"] for r in cross)),
        cross_language_rows=[{k: r[k] for k in ("set", "body", "affair_id", "q_doc", "a_doc", "q_text", "a_text",
                                                "q_tag", "a_tag")} for r in cross],
        opd_tag_vs_text=dict(documents_with_tag_and_text=len(tagged), tag_differs_from_text=len(tag_wrong),
                             rows=tag_wrong),
    )


# ---------------------------------------------------------------- Valais pairing by question number (post hoc)

def _number_pairs(a, k: int, reply: tuple[int, int]) -> list[tuple[int, int, int]]:
    """Language-independent pairing: bare numbered paragraphs "1." … "k." in document order inside the reply, all k
    present; answer n runs from its number to the next number (or the reply end). A reprinted question right after the
    number (text up to the first '?' that ends a line, within 600 characters, no blank line) is skipped."""
    from ..qa import answers
    from ..qa.text import boilerplate_lines, strip_edges

    skip = boilerplate_lines(a)
    hs = [h for h in answers._headings(a, reply[0], reply[1], skip) if h["kind"] == "num"]
    chain, want = [], 1
    for h in hs:
        if h["nums"][0] == want:
            chain.append(h)
            want += 1
    if len(chain) != k:
        return []
    out = []
    for i, h in enumerate(chain):
        end = chain[i + 1]["g"] if i + 1 < len(chain) else reply[1]
        body = h["gm"]
        seg = a.text[body:min(end, body + 600)]
        m = re.search(r"\?[ \t]*\n", seg)
        if m and "\n\n" not in seg[:m.start()]:
            body += m.end()
        s, e = strip_edges(a, body, end, skip)
        out.append((i + 1, s, e))
    return out


def valais_posthoc() -> dict | None:
    """Re-score P5's Valais Q/A pairing by question number (post hoc; registered metric: an answer is right when the
    predicted span has IoU >= 0.5 with the gold span, eval/gold6/score6.py)."""
    from eval.gold6.score6 import iou

    from ..qa import answers
    from ..qa.text import Doc

    labels = {json.loads(x)["affair_id"]: json.loads(x) for x in open(DATA / "gold6" / "p5_labels.jsonl", encoding="utf-8")}
    committed = {r["affair_id"]: r for r in json.loads((RESULTS / "eval6" / "p5__none.json").read_text())["per_affair"]}
    rows = []
    for line in open(DATA / "gold6" / "p5_affairs.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r["body"] != "VS":
            continue
        docs = {d["role"]: d for d in r["docs"]}
        pages = {}
        for role, d in docs.items():
            ps = [p for p in sorted(TEXT_CACHE.glob(f"{d['sha256']}.{d['extractor']}.json"))]
            if not ps:
                return None
            pages[role] = json.loads(ps[0].read_text(encoding="utf-8"))["pages"]
        q, a = Doc("question", "q", pages["question"]), Doc("answer", "a", pages["answer"])
        view = committed[r["affair_id"]]["R"]["view"]
        k = len(view["questions"])
        reply, _ = answers.reply_span(a, q)
        pred = {n: dict(doc="answer", g_start=s, g_end=e) for n, s, e in (_number_pairs(a, k, reply) if reply and k else [])}
        rules = {x["n"]: x["span"] for x in view["answers"]}
        gold = {x["n"]: x["span"] for x in labels[r["affair_id"]]["answers"]}
        g_nonnull = [n for n, s in gold.items() if s]

        def right(p, gold=gold, g_nonnull=g_nonnull):
            return sum(1 for n in g_nonnull if p.get(n) and iou(p[n], gold[n]) >= 0.5)

        rows.append(dict(
            affair_id=r["affair_id"], q_doc=docs["question"]["doc_id"], a_doc=docs["answer"]["doc_id"],
            q_text=text_lang(q.text), a_text=text_lang(a.text), questions_found=k,
            gold_answers=len(g_nonnull), answer_style_gold=labels[r["affair_id"]]["answer_style"],
            rules_right=right(rules), rules_predicted=sum(1 for s in rules.values() if s),
            by_number_right=right(pred), by_number_predicted=len(pred),
            by_number_iou=[round(iou(pred.get(n), gold[n]), 3) for n in g_nonnull]))
    g = sum(x["gold_answers"] for x in rows)
    return dict(
        status="post hoc, not registered (P5 registered result unchanged: rules-only Valais Q/A 0/11)",
        rule=("numbered paragraphs '1.' ... 'k.' inside the frozen reply span (qa/answers.py reply_span), all k "
              "questions found by the frozen question rules present in order, without the same-language reprint check; "
              "a reprinted question after the number is skipped up to its line-final '?'"),
        affairs=len(rows), gold_answers=g,
        rules_right=sum(x["rules_right"] for x in rows), rules_predicted=sum(x["rules_predicted"] for x in rows),
        by_number_right=sum(x["by_number_right"] for x in rows),
        by_number_predicted=sum(x["by_number_predicted"] for x in rows),
        rows=rows)


# ---------------------------------------------------------------- the finding

def tag_counts(pairs: dict, key: str = "tag") -> dict:
    """Per body: affairs with both roles, evaluable on the signal, cross-language, first-pair cross."""
    per = collections.defaultdict(collections.Counter)
    for (b, _a), v in pairs.items():
        if not v["question"] or not v["answer"]:
            continue
        c = per[b]
        c["affairs_with_q_and_a"] += 1
        k = classify(v, key)
        if k:
            c["evaluable"] += 1
            c[k] += 1
        fp = first_pair_cross(v, key)
        if fp is not None:
            c["first_pair_evaluable"] += 1
            c["first_pair_cross"] += int(fp)
    return {b: dict(c) for b, c in per.items()}


NAME_NUMBER = re.compile(r"(?<!\d)(\d{4}\.(?:\d{2}\.\d{3}|RRGR\.\d+))")


def affair_numbers() -> dict[str, tuple[str, str]]:
    return {r["id"]: (r["body"], r["number"]) for r in _tsv(DATA / "census" / "affairs.tsv.gz")}


def strict_cases(pairs: dict, key: str = "tag") -> list[dict]:
    """Every affair where OPD links no same-language question/answer pair: its documents (id, language, OPD name's
    affair number, URL file name) and other OPD affairs of the same body that carry the same number."""
    nums = affair_numbers()
    by_num = collections.defaultdict(list)
    for aid, (b, num) in nums.items():
        if num:
            by_num[(b, num)].append(int(aid))
    out = []
    for (b, a), v in sorted(pairs.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))):
        if not v["question"] or not v["answer"] or classify(v, key) != "cross":
            continue
        num = nums.get(a, (b, ""))[1]

        def doc(d, key=key):
            m = NAME_NUMBER.search(d["name"] or "")
            return dict(id=d["id"], lang="+".join(d.get(key) or ()), name_number=m.group(1) if m else None,
                        file=d.get("url_file"))
        out.append(dict(body=b, affair=int(a), number=num,
                        same_number_affairs=sorted(x for x in by_num.get((b, num), []) if x != int(a)),
                        question_docs=[doc(d) for d in v["question"]], answer_docs=[doc(d) for d in v["answer"]]))
    return out


def build() -> dict:
    pairs = linked_docs()
    names = body_names()
    tag = tag_counts(pairs, "tag")
    have_url = add_url_signal(pairs)
    url = tag_counts(pairs, "url") if have_url else None
    both = None
    if have_url:
        both = collections.defaultdict(collections.Counter)
        for (b, _a), v in pairs.items():
            if v["question"] and v["answer"]:
                kt, ku = classify(v, "tag"), classify(v, "url")
                if kt and ku:
                    both[b]["evaluable_both"] += 1
                    both[b][f"tag_{kt}__url_{ku}"] += 1
        both = {b: dict(c) for b, c in both.items()}
    bodies = []
    for b in sorted(tag, key=lambda b: (-tag[b].get("cross", 0), -tag[b]["affairs_with_q_and_a"], b)):
        t = tag[b]
        row = dict(body=b, name=names.get(b), affairs_with_q_and_a=t["affairs_with_q_and_a"],
                   opd_tag=dict(evaluable=t.get("evaluable", 0), cross=t.get("cross", 0),
                                first_pair_evaluable=t.get("first_pair_evaluable", 0),
                                first_pair_cross=t.get("first_pair_cross", 0)))
        if url is not None:
            u = url.get(b, {})
            row["file_name"] = dict(evaluable=u.get("evaluable", 0), cross=u.get("cross", 0))
            row["tag_and_file_name"] = (both or {}).get(b, {})
        if t.get("evaluable") or (url and url.get(b, {}).get("evaluable")):
            bodies.append(row)
    tot = collections.Counter()
    for b in tag.values():
        for k, v in b.items():
            tot[k] += v
    cross_bodies = [r["body"] for r in bodies if r["opd_tag"]["cross"]]
    out = dict(
        status="post hoc finding (not a registered result); no model, no network",
        definitions=DEFINITIONS,
        inputs=dict(committed=["data/census/affairs.tsv.gz", "data/census/docs.tsv.gz", "data/census/bodies.tsv.gz",
                               "eval/gold3/sample.py:pair_type (LOCK3)"],
                    local=["GP_DOCS_META/part*/docs_meta.jsonl.gz (file names)", "WORK/text (cached PDF text)"],
                    file_name_signal=have_url),
        totals=dict(affairs_with_q_and_a=tot["affairs_with_q_and_a"], opd_tag_evaluable=tot["evaluable"],
                    opd_tag_cross=tot["cross"], opd_tag_first_pair_evaluable=tot["first_pair_evaluable"],
                    opd_tag_first_pair_cross=tot["first_pair_cross"], bodies_evaluable=len(bodies),
                    bodies_with_cross=cross_bodies),
        bodies=bodies,
        no_same_language_pair=strict_cases(pairs, "tag"),
    )
    if url is not None:
        out["totals"].update(file_name_evaluable=sum(u.get("evaluable", 0) for u in url.values()),
                             file_name_cross=sum(u.get("cross", 0) for u in url.values()))
    gt = gold_text_check(pairs)
    if gt:
        out["gold_text_check"] = gt
    vp = valais_posthoc()
    if vp:
        out["valais_pairing_by_number"] = vp
    return out


DEFINITIONS = {
    "scope": "OPD harmonised type Interpellation, Motion, Postulate, Question or Question time (census/defs.py)",
    "question_document": "eval/gold3/sample.py pair_type == 'intervention' (frozen P3 pairing, OPD name/category)",
    "answer_document": "eval/gold3/sample.py pair_type == 'answer'",
    "opd_tag": "OPD docs export `language` (data/census/docs.tsv.gz lang; 'de;fr' counts as both)",
    "file_name": "language suffix of the URL file name: _DE/_FR/_IT.pdf, _D1/_F1/_I1.pdf, -de/-fr/-it.pdf",
    "text": "stop-word counts on cached PDF text (repair/ocr.py word lists; >= 3 hits and twice the runner-up)",
    "cross": "affair with >= 1 question and >= 1 answer document carrying the signal, and no language shared between "
             "the question documents and the answer documents (OPD offers no same-language pair)",
    "first_pair_cross": "the lowest-id question and lowest-id answer document (P3/P5 sampling convention) differ",
}


def main(argv: list[str] | None = None) -> int:
    out = Path((argv or sys.argv[1:] or [str(OUT)])[0])
    r = build()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(r["totals"], ensure_ascii=False))
    for b in r["bodies"][:10]:
        print(b["body"], b["name"], b["affairs_with_q_and_a"], b["opd_tag"], b.get("file_name"))
    if "valais_pairing_by_number" in r:
        v = r["valais_pairing_by_number"]
        print("valais", {k: v[k] for k in ("gold_answers", "rules_right", "by_number_right", "by_number_predicted")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
