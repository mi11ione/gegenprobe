"""Spot-check kit (round 10): 30 gold labels that anyone, OpenParlData included, can verify against the documents in about
an hour, and the scorer for the filled file. The gold of every test comes reproducibly from blind multi-annotator agents
with a cross-vendor check; the kit is sized for one sitting.

    PYTHONPATH=src:. python -m eval.spotcheck score results/opd_spotcheck/spotcheck.csv    agreement, Wilson 95% interval
    PYTHONPATH=src:. python -m eval.spotcheck summary   results/opd_spotcheck/summary.json from the committed kit (rows
                                                        per set; the claims check reads it)
    PYTHONPATH=src:. python -m eval.spotcheck build     DEV ONLY: rewrite the kit (needs WORK: the census docs scan for
                                                        OPD's copy URLs, the extracted texts for character spans)

Selection (seed 20261050, `random.Random(SEED + stratum index)`; no model, no network; every label already committed):
  dates   10 answer-date labels: 4 P1 held-out + 4 P2 documents whose gold has an answer date, each drawn from a
          different (parliament) where possible, + 1 P1 and 1 P2 document whose gold says "no qualifying answer date"
          (documents OPD types as answers, so the null is a real claim)            data/gold/heldout_*, data/gold2/p2_*
  p7      10 of the 120 judged Apertus promotions (P7 stratum `p7`, spread over parliaments, at most 3 from Frauenfeld):
          is the document the executive's answer to this affair, and is the gold answer date right; quote = the
          promoted row's printed line (span_line) and span = its date in the adapter's text, or, where that line does
          not print the gold date, annotator A1's date quote and no span        data/p7/test_*, promoted.tsv
  p8      5 submitter labels (stratified over the gold categories: sole author, joint author, group, co-signer) and 5
          type labels (stratified over the instrument function, the deviating categories first)    data/p8/

Columns: item_id, set, parliament, affair_number, document_url (OPD's own copy on files.openparldata.ch where OPD holds the
document: files.openparldata.ch/doc/<body_key>/<sha256(body_key + "affair" + url)>, OPD's identifier rule; else the
parliament's URL), source_url (the parliament's URL), page (1-based), char_span (start-end in our pdftotext text of that
page; P7: in the adapter's text of the document), quoted_text (at most 200 characters, only quotes the committed gold
already carries; P8 type rows carry none, their quotes are committed as sha256 only), what_to_check, our_label,
reviewer_agrees (yes / no; empty = not reviewed), note.
"""

from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import json
import random
import sys
from pathlib import Path

from gegenprobe.paths import DATA, RESULTS, ROOT, WORK
from gegenprobe.repair.common import parse_dates
from gegenprobe.stats import wilson

SEED = 20261050
KIT = RESULTS / "opd_spotcheck" / "spotcheck.csv"
SUMMARY = RESULTS / "opd_spotcheck" / "summary.json"
COLS = ["item_id", "set", "parliament", "affair_number", "document_url", "source_url", "page", "char_span", "quoted_text",
        "what_to_check", "our_label", "reviewer_agrees", "note"]
YES, NO = {"yes", "y", "1", "true", "ja", "oui", "agree"}, {"no", "n", "0", "false", "nein", "non", "disagree"}
MAXQ = 200


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ------------------------------------------------------------------------------------------------ score
def score(path: Path) -> dict:
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    per = collections.defaultdict(collections.Counter)
    bad = []
    for r in rows:
        v = (r.get("reviewer_agrees") or "").strip().lower()
        s = r.get("set") or "?"
        per[s]["items"] += 1
        if not v:
            continue
        if v in YES:
            per[s]["agree"] += 1
        elif v in NO:
            per[s]["disagree"] += 1
        else:
            bad.append(f"{r.get('item_id')}: reviewer_agrees {v!r} is neither yes nor no")
    tot = collections.Counter()
    for c in per.values():
        tot.update(c)

    def block(c: collections.Counter) -> dict:
        n = c["agree"] + c["disagree"]
        lo, hi = wilson(c["agree"], n) if n else (None, None)
        return dict(items=c["items"], reviewed=n, agree=c["agree"], disagree=c["disagree"],
                    agreement=round(c["agree"] / n, 4) if n else None,
                    wilson95_pct=[round(100 * lo, 1), round(100 * hi, 1)] if n else None)
    return dict(file=str(path), overall=block(tot), by_set={s: block(c) for s, c in sorted(per.items())}, invalid=bad)


# ------------------------------------------------------------------------------------------------ build (dev only)
def _labels() -> dict[str, str]:
    out = {}
    with open(ROOT / "site" / "parliaments.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["key"]] = r["label"]
    return out


def _docs_meta(ids: set[int]) -> dict[int, dict]:
    """id -> {b, a, url} from the census scan of OPD's docs exports (WORK/docs_meta), for OPD's copy URL."""
    out = {}
    for f in sorted((WORK / "docs_meta").glob("part*/docs_meta.jsonl.gz")):
        for line in gzip.open(f, "rt", encoding="utf-8"):
            d = json.loads(line)
            if d["id"] in ids and d["id"] not in out:
                out[d["id"]] = dict(b=d["b"], a=d.get("a"), url=d.get("url"))
    return out


def _opd_copy(meta: dict | None) -> str:
    if not meta or meta.get("a") is None or not meta.get("url"):
        return ""
    h = hashlib.sha256(f"{meta['b']}affair{meta['url']}".encode()).hexdigest()
    return f"https://files.openparldata.ch/doc/{meta['b']}/{h}"


def _affair_numbers(ids: set[int]) -> dict[int, str]:
    out = {}
    with gzip.open(RESULTS / "census" / "interventions.tsv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if int(r["affair_id"]) in ids:
                out[int(r["affair_id"])] = r["number"]
    rest = ids - set(out)
    p = WORK / "opd" / "affairs.ndjson.gz"
    if rest and p.exists():
        for line in gzip.open(p, "rt", encoding="utf-8"):
            d = json.loads(line)
            if d["id"] in rest:
                out[d["id"]] = d.get("number") or ""
    return out


def _span(sha: str, extractor: str, page: int | None, quote: str) -> str:
    """start-end of the quote in our extracted text of that page (whitespace-tolerant), else ''."""
    p = WORK / "text" / f"{sha}.{extractor}.json"
    if not page or not quote or not p.exists():
        return ""
    pages = json.loads(p.read_text())["pages"]
    if not 1 <= page <= len(pages):
        return ""
    t = pages[page - 1]
    i = t.find(quote)
    if i >= 0:
        return f"{i}-{i + len(quote)}"
    import re
    m = re.search(r"\s+".join(re.escape(w) for w in quote.split()), t)
    return f"{m.start()}-{m.end()}" if m else ""


def _q(s: str | None) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= MAXQ else s[: MAXQ - 1] + "…"


def _pick(items: list, k: int, rng: random.Random, key=None) -> list:
    """k items, spread over `key` (round robin over the shuffled groups), deterministic for the seed."""
    items = sorted(items, key=lambda x: json.dumps(x, sort_keys=True, default=str))
    rng.shuffle(items)
    if key is None:
        return items[:k]
    groups = collections.OrderedDict()
    for x in items:
        groups.setdefault(key(x), []).append(x)
    out = []
    while len(out) < k and any(groups.values()):
        for g in list(groups):
            if groups[g] and len(out) < k:
                out.append(groups[g].pop(0))
    return out


def _date_rows(split: str, docs_f: Path, labels_f: Path, n_dated: int, n_null: int, seed: int) -> list[dict]:
    docs = {d["doc_id"]: d for d in _jsonl(docs_f)}
    labs = [lab for lab in _jsonl(labels_f) if lab["doc_id"] in docs]
    rng = random.Random(seed)
    dated = _pick([lab for lab in labs if lab.get("answer_date") and lab.get("answer_date_quote")], n_dated, rng,
                  key=lambda lab: docs[lab["doc_id"]]["body"])
    null = _pick([lab for lab in labs if not lab.get("answer_date") and docs[lab["doc_id"]].get("dtype") == "answer"],
                 n_null, rng)
    out = []
    for lab in dated + null:
        d = docs[lab["doc_id"]]
        if lab.get("answer_date"):
            label = f"answer date {lab['answer_date']} ({lab.get('role') or 'role not given'})"
            check = "Is this the date of the government's answer (decision or letter date) printed at this place?"
        else:
            label = "no qualifying answer date printed in this document"
            check = "Does the document print no date of the government's answer to this affair?"
        out.append(dict(set="dates", split=split, body=d["body"], affair_id=d["affair_id"], doc_id=d["doc_id"],
                        source_url=d["url"], page=lab.get("answer_date_page") or "",
                        char_span=_span(d["sha256"], d["extractor"], lab.get("answer_date_page"),
                                        lab.get("answer_date_quote") or ""),
                        quoted_text=_q(lab.get("answer_date_quote")), what_to_check=check, our_label=label,
                        note=f"{split} gold, document {d['doc_id']}"))
    return out


def _p7_rows(k: int, seed: int) -> list[dict]:
    key = {r["id"]: r for r in _jsonl(DATA / "p7" / "test_key.jsonl")}
    gold = {r["id"]: r for r in _jsonl(DATA / "p7" / "test_annotations" / "gold.jsonl")}
    a1 = {r["id"]: r for r in _jsonl(DATA / "p7" / "test_annotations" / "A1.jsonl")}  # fallback quote
    prom = {(r["body"], int(r["affair_id"])): r
            for r in csv.DictReader(open(RESULTS / "repair" / "adapters" / "p7" / "promoted.tsv", encoding="utf-8"),
                                    delimiter="\t")}
    pool = [pid for pid, k_ in key.items() if k_["stratum"] == "p7" and (k_["body"], k_["affair_id"]) in prom
            and gold[pid]["is_answer"] == "yes" and gold[pid]["dates"]]
    rng = random.Random(seed)
    picked, n_frauenfeld = [], 0
    for pid in _pick(pool, len(pool), rng, key=lambda p: key[p]["body"]):
        if key[pid]["body"] == "4566":
            if n_frauenfeld >= 3:
                continue
            n_frauenfeld += 1
        picked.append(pid)
        if len(picked) == k:
            break
    out = []
    for pid in picked:
        kk, g = key[pid], gold[pid]
        pr = prom[(kk["body"], kk["affair_id"])]
        lst = {int(r["affair_id"]): r for r in csv.DictReader(
            open(RESULTS / "repair" / "adapters" / f"adapters_{kk['body']}.tsv", encoding="utf-8"), delimiter="\t")}
        row = lst.get(kk["affair_id"], {})
        span = f"{pr['span_char_start']}-{pr['span_char_end']}" if pr.get("span_char_start") else ""
        quote = pr.get("span_line") or ""
        if not any(d in g["dates"] for d, _, _ in parse_dates(quote)):  # Apertus's line does not print the gold date
            quote, span = a1.get(pid, {}).get("date_quote") or "", ""
        out.append(dict(set="p7", split="P7", body=kk["body"], affair_id=kk["affair_id"],
                        doc_id=int(pr["opd_doc_id"]) if (pr.get("opd_doc_id") or "").isdigit() else None,
                        source_url=row.get("source_url", ""), page="", char_span=span,
                        quoted_text=_q(quote),
                        what_to_check="Is this document the executive's written answer to this affair, and is the "
                                      "answer date right?",
                        our_label=f"executive's answer: yes; answer date {', '.join(g['dates'])}",
                        note=f"P7 packet {pid}; Apertus promoted it with answer date {pr['answer_date']}"))
    return out


def _p8_rows(k_sub: int, k_type: int, seed: int) -> list[dict]:
    gold = {g["id"]: g for g in _jsonl(DATA / "p8" / "p8_gold.jsonl")}
    affs = {a["affair_id"]: a for a in _jsonl(DATA / "p8" / "p8_affairs.jsonl")}
    ann = {r["id"]: r for r in _jsonl(DATA / "p8" / "annotations" / "A1.jsonl")}
    cat_words = dict(author_person="OPD's submitter {} is the sole author or designated first signatory",
                     joint_person="OPD's submitter {} is one of several joint authors, none designated first",
                     group="the author of record is a parliamentary group; OPD's submitter {} signs for it",
                     cosigner_person="OPD's submitter {} is a co-signer, not an author of record")
    fun_words = dict(mandate="mandates the executive to act", examine_report="asks the executive to examine and report",
                     questions="asks questions", direct_decision="proposes a decision the council takes itself")
    rng = random.Random(seed)

    def doc(g, role):
        return next((d for d in affs[g["affair_id"]]["docs"] if d["role"] == role), None)

    sub = []
    for gid, g in gold.items():
        f = g["fields"]["submitter"]
        name = (f.get("secondary") or {}).get("opd_name")
        if not f["applicable"] or f["category"] not in cat_words or not name:
            continue
        person = next((p for p in ann.get(gid, {}).get("people", []) if p.get("name") and
                       p["name"].split()[-1].lower() in name.lower()), None)
        if person is None or not person.get("span"):
            continue
        sub.append((gid, g, f, name, person))
    out = []
    for gid, g, f, name, person in _pick(sub, k_sub, rng, key=lambda x: x[2]["category"]):
        d = doc(g, person["span"]["doc"])
        out.append(dict(set="p8", split="P8 submitter", body=g["body"], affair_id=g["affair_id"],
                        doc_id=d["doc_id"] if d else None, source_url=d["url"] if d else "", page=person["span"]["page"],
                        char_span=f"{person['span']['char_start']}-{person['span']['char_end']}", quoted_text=_q(name),
                        what_to_check="Do the documents print OPD's submitter in this role?",
                        our_label=cat_words[f["category"]].format(name),
                        note=f"P8 {gid}, field submitter, gold {f['source']}"))
    typ = []
    for gid, g in gold.items():
        f = g["fields"]["type"]
        fn = ann.get(gid, {}).get("function") or {}
        if not f["applicable"] or f["category"] not in fun_words or not fn.get("span"):
            continue
        typ.append((gid, g, f, fn))
    rng2 = random.Random(seed + 1)
    for gid, g, f, fn in _pick(typ, k_type, rng2, key=lambda x: x[2]["category"]):
        d = doc(g, fn["span"]["doc"])
        out.append(dict(set="p8", split="P8 type", body=g["body"], affair_id=g["affair_id"],
                        doc_id=d["doc_id"] if d else None, source_url=d["url"] if d else "", page=fn["span"]["page"],
                        char_span=f"{fn['span']['char_start']}-{fn['span']['char_end']}", quoted_text="",
                        what_to_check="Does the text ask for what our_label says (act, examine and report, answer "
                                      "questions, or a decision the council takes itself)?",
                        our_label=f"OPD type {g['affair_type']}; the text {fun_words[f['category']]}",
                        note=f"P8 {gid}, field type, gold {f['source']}; quote committed as sha256 only"))
    return out


def build() -> dict:
    rows = (_date_rows("P1", DATA / "gold" / "heldout_docs.jsonl", DATA / "gold" / "heldout_labels.jsonl", 4, 1, SEED)
            + _date_rows("P2", DATA / "gold2" / "p2_docs.jsonl", DATA / "gold2" / "p2_labels.jsonl", 4, 1, SEED + 1)
            + _p7_rows(10, SEED + 2) + _p8_rows(5, 5, SEED + 3))
    meta = _docs_meta({r["doc_id"] for r in rows if r.get("doc_id")})
    nums = _affair_numbers({r["affair_id"] for r in rows})
    names = _labels()
    KIT.parent.mkdir(parents=True, exist_ok=True)
    with open(KIT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, lineterminator="\n")
        w.writeheader()
        for i, r in enumerate(rows, 1):
            opd = _opd_copy(meta.get(r.get("doc_id")))
            w.writerow(dict(item_id=f"S{i:02d}", set=r["set"], parliament=names.get(r["body"], r["body"]),
                            affair_number=nums.get(r["affair_id"], ""), document_url=opd or r["source_url"],
                            source_url=r["source_url"], page=r["page"], char_span=r["char_span"],
                            quoted_text=r["quoted_text"], what_to_check=r["what_to_check"], our_label=r["our_label"],
                            reviewer_agrees="", note=f"{r['note']}; OPD affair {r['affair_id']}"))
    by = collections.Counter(r["set"] for r in rows)
    return dict(file=str(KIT.relative_to(ROOT)), rows=len(rows), by_set=dict(by),
                opd_copy=sum(bool(_opd_copy(meta.get(r.get("doc_id")))) for r in rows))


def summary() -> dict:
    """Rows of the committed kit, per set -> results/opd_spotcheck/summary.json (no WORK, no network)."""
    rows = list(csv.DictReader(open(KIT, encoding="utf-8")))
    out = dict(file=str(KIT.relative_to(ROOT)), rows=len(rows),
               by_set=dict(sorted(collections.Counter(r["set"] for r in rows).items())))
    SUMMARY.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["build"]:
        print(json.dumps(build(), indent=1))
        print(json.dumps(summary(), indent=1))
        return 0
    if argv[:1] == ["summary"]:
        print(json.dumps(summary(), indent=1))
        return 0
    if argv[:1] == ["score"]:
        r = score(Path(argv[1]) if len(argv) > 1 else KIT)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 1 if r["invalid"] else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
