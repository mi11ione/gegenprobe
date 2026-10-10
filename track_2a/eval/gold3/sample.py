"""P3 sample: whole affairs (question document + answer document) for multi-field extraction (eval/prereg3). Model-free.

An affair qualifies when OPD links at least one member text (the intervention as lodged) and one executive answer to it,
both with usable OPD text in a wide length band, and neither the affair nor its documents occur in P1 dev, P1 held-out or P2.
Bodies mix those the rules were written for (BE, ZH, BS, TI, Zürich city) and P2 bodies the rules never saw (NW, OW, VD,
Sion, Bellinzona). The document type is the P1 metadata guess (eval/gold/doctype.py), used only to pick the pair; the gold
labels come from the documents. PDFs are fetched politely; an affair whose pair cannot be fetched is replaced by the next one
of the same body in seeded order, and logged.

usage: python -m eval.gold3.sample [--fetch]
Out: data/gold3/p3_affairs.jsonl (affair + both documents: ids, url, sha256, pages, chars, extractor; never the text),
     data/gold3/p3_fetch_log.jsonl
"""

from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import random
import re

from eval.gold.doctype import doc_type
from eval.gold.sample import affair_types, lang_of
from eval.gold2.sample import fetch_one, seen
from gegenprobe.paths import DATA, DOCS_META

SEED = 20261012
GOLD3 = DATA / "gold3"
LEN_BAND = (1500, 30000)
SCOPE = {"Interpellation", "Motion", "Postulate", "Question"}
# (body, level, language, seen_by_rules, n affairs) — written into PREREG3_draft.md before drawing
QUOTAS = [
    ("BE", "canton", "de", True, 3),
    ("ZH", "canton", "de", True, 3),
    ("BS", "canton", "de", True, 3),
    ("TI", "canton", "it", True, 3),
    ("261", "commune", "de", True, 3),
    ("NW", "canton", "de", False, 3),
    ("OW", "canton", "de", False, 3),
    ("VD", "canton", "fr", False, 3),
    ("6643", "commune", "fr", False, 3),
    ("5002", "commune", "it", False, 3),
]
BODIES = {q[0] for q in QUOTAS}
# P3 pairing (wider than the P1 stratification guess, which misses how several parliaments name their files)
ANSWER3 = re.compile(
    r"Beantwortung|Antwort (des |der )?(Stadtrat|Regierungsrat|Gemeinderat)|^Antwort|Stellungnahme (zum|zur|des)|"
    r"Texte adopt[ée] par le Conseil d.[ÉE]tat|R[ée]ponse|Risposta|Osservazioni.*Municipio|^RRB\b",
    re.I,
)
QUESTION3 = re.compile(
    r"^(Dringliche |Kleine |Schriftliche )?(Interpellation|Postulat|Motion|Anfrage|Frage)\b|"
    r"^\d{4}_\d{4} (Schriftliche Anfrage|Postulat|Motion|Interpellation)|^Testo (interpellanza|mozione|interrogazione)|"
    r"^(Interpellanza|Mozione|Interrogazione|Postulato)\b|^(Interpellation|Question|Postulat|Motion|R[ée]solution)\b|"
    r"Texte d[ée]pos[ée]|^Objet$",
    re.I,
)


def pair_type(d: dict) -> str | None:
    t = doc_type(d)
    name = d.get("name") or ""
    if t == "answer" or ANSWER3.search(name):
        return "answer"
    if t == "intervention" or QUESTION3.search(name):
        return "intervention"
    return None


def p2_exclusions() -> tuple[set, set]:
    docs, affs = set(), set()
    for line in open(DATA / "gold2" / "p2_docs.jsonl"):
        x = json.loads(line)
        docs.add(x["doc_id"])
        if x.get("affair_id"):
            affs.add(x["affair_id"])
    return docs, affs


def pairs() -> dict[str, list[dict]]:
    """body -> [{affair, a_type, question: doc, answer: doc}] for qualifying affairs."""
    at = affair_types()
    by_aff = collections.defaultdict(lambda: {"intervention": [], "answer": []})
    ids = set()
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt"):
            d = json.loads(line)
            if d["id"] in ids or d["b"] not in BODIES or not d.get("url") or d.get("a") is None:
                continue
            ids.add(d["id"])
            if at.get(d["a"]) not in SCOPE or d["st"] != "ok" or not (LEN_BAND[0] <= d["n"] <= LEN_BAND[1]):
                continue
            d["a_type"] = at.get(d["a"])
            d["lg"] = lang_of(d)
            t = pair_type(d)
            if t in ("intervention", "answer"):
                by_aff[(d["b"], d["a"])][t].append(d)
    out = collections.defaultdict(list)
    for (b, a), v in by_aff.items():
        if v["intervention"] and v["answer"]:
            q = sorted(v["intervention"], key=lambda d: d["id"])[0]
            ans = sorted(v["answer"], key=lambda d: d["id"])[0]
            out[b].append(dict(affair=a, a_type=q["a_type"], question=q, answer=ans))
    return out


def draw(fetch: bool) -> list[dict]:
    s_docs, s_affs, _ = seen()
    p_docs, p_affs = p2_exclusions()
    s_docs |= p_docs
    s_affs |= p_affs
    pl = pairs()
    chosen, log = [], []
    for body, level, lang, seen_rules, n in QUOTAS:
        cands = [
            c
            for c in pl[body]
            if c["affair"] not in s_affs
            and c["question"]["id"] not in s_docs
            and c["answer"]["id"] not in s_docs
            and (c["question"]["lg"] in (lang, None))
        ]
        cands.sort(key=lambda c: c["affair"])
        random.Random(f"{SEED}:{body}").shuffle(cands)
        got = []
        for c in cands:
            if len(got) >= n:
                break
            rq = fetch_one(c["question"]) if fetch else {}
            ra = fetch_one(c["answer"]) if fetch and "error" not in rq else {}
            ok = "error" not in rq and "error" not in ra
            log.append(dict(affair_id=c["affair"], body=body, accepted=ok, q_error=rq.get("error"), a_error=ra.get("error")))
            if ok:
                got.append((c, rq, ra))
        if len(got) < n:
            log.append(dict(body=body, shortfall=n - len(got), pool=len(cands)))
        for c, rq, ra in got:
            docs = []
            for role, d, r in (("question", c["question"], rq), ("answer", c["answer"], ra)):
                docs.append(
                    dict(
                        role=role,
                        doc_id=d["id"],
                        name=d.get("name"),
                        url=d["url"],
                        opd_text_status=d["st"],
                        opd_chars=d["n"],
                        **{k: r.get(k) for k in ("sha256", "pages", "chars", "extractor", "image_only")},
                    )
                )
            chosen.append(
                dict(
                    split="p3",
                    affair_id=c["affair"],
                    body=body,
                    level=level,
                    lang=lang,
                    seen_by_rules=seen_rules,
                    affair_type=c["a_type"],
                    docs=docs,
                )
            )
    GOLD3.mkdir(parents=True, exist_ok=True)
    with open(GOLD3 / "p3_affairs.jsonl", "w") as f:
        for x in chosen:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(GOLD3 / "p3_fetch_log.jsonl", "w") as f:
        for x in log:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return chosen


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args()
    rows = draw(a.fetch)
    for k, v in sorted(collections.Counter((r["body"], r["affair_type"]) for r in rows).items()):
        print(k, v)
    print("total", len(rows))
