"""POST HOC (11 Oct 2026; proposed in review; not pre-registered): a generic DE/FR/IT keyword rule for P2's answer date,
written by a reviewer without reading the gold quotes, ported here verbatim and not tuned by the team. No registered
decision depends on this file. No model call; no network: the 62 P2 texts come from the project's text cache
(pdftext.extract on the committed sha256; every cached PDF is re-hashed against data/gold2/p2_docs.jsonl first, and a
missing one is fetched only through the project's fetch path, pdftext.fetch_pdf -> net.get: robots fail closed, <= 1
request per second per host).

    PYTHONPATH=src:. .venv/bin/python -m eval.gold2.posthoc_keyword   -> results/eval/p2_posthoc_keyword.json

The rule (the reviewer's text, unchanged; constants GOV, ANS, CUE, MON and the two date patterns below):
  only on documents OPD types as answers (as the registered-baseline comparison 'latest date on answer-typed
  documents' does); the text must name a government (GOV) and an answer cue (ANS); then the first date within 80
  characters after a session / minutes cue (CUE: "Sitzung vom", "séance du", "seduta del", "Protokoll ... vom", ...);
  else the latest date printed; else null.
Scored like every P2 arm: eval.score.outcome (strict) through eval.baselines._score, and paired with the Apertus pointer
(results/eval2/p2__publicai_swiss-ai_apertus-v1.5-8b.json) by eval.posthoc_r3._pair: exact McNemar (two-sided) on
documents right in exactly one arm, on all 62, on the 29 with a gold date and on the 33 without; and per parliament.
The page texts are joined with form feeds, as pdftotext prints them (the reviewer's input).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys

from eval import baselines as BL
from eval import posthoc_r3 as R3
from gegenprobe import pdftext
from gegenprobe.paths import DATA, PDF_CACHE, RESULTS

LABEL = ("POST HOC (11 Oct 2026; proposed in review; not pre-registered): a reviewer's generic keyword rule, ported "
         "verbatim, not tuned by the team; no registered decision depends on this file")
OUT = RESULTS / "eval" / "p2_posthoc_keyword.json"
BUILD = "publicai_swiss-ai_apertus-v1.5-8b"

# ---------------------------------------------------------------- the reviewer's rule, verbatim
MON = {'januar': 1, 'jänner': 1, 'februar': 2, 'märz': 3, 'maerz': 3, 'april': 4, 'mai': 5, 'juni': 6, 'juli': 7,
       'august': 8, 'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12,
       'janvier': 1, 'février': 2, 'fevrier': 2, 'mars': 3, 'avril': 4, 'juin': 6, 'juillet': 7, 'août': 8, 'aout': 8,
       'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12, 'decembre': 12,
       'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4, 'maggio': 5, 'giugno': 6, 'luglio': 7, 'agosto': 8,
       'settembre': 9, 'ottobre': 10, 'dicembre': 12}
rx1 = re.compile(r'\b(\d{1,2})\.?\s*(?:er|°|º)?\s+([A-Za-zÀ-ÿ]+)\s+((?:19|20)\d\d)\b')
rx2 = re.compile(r'\b(\d{1,2})\.(\d{1,2})\.((?:19|20)\d\d)\b')
GOV = r'(Regierungsrat|Gemeinderat|Stadtrat|Landammann|Conseil d.[ÉE]tat|Municipalit[ée]|Conseil communal|Consiglio di Stato|Municipio)'  # noqa: E501
ANS = r'(beantwort|Antwort|Stellungnahme|beschliesst|Beschluss|réponse|répond|détermination|risposta|risponde|risoluzione|preavviso)'  # noqa: E501
CUE = re.compile(r'(Sitzung vom|Beschluss vom|Auszug aus dem Protokoll|Protokoll.{0,40}?vom|séance du|en séance|Ainsi adopté|Adopté|seduta del|in seduta|risoluzione)', re.I)  # noqa: E501


def dates(t):
    out = []
    for m in rx1.finditer(t):
        mo = MON.get(m.group(2).lower())
        if mo:
            out.append((m.start(), f"{m.group(3)}-{mo:02d}-{int(m.group(1)):02d}"))
    for m in rx2.finditer(t):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.append((m.start(), f"{y}-{mo:02d}-{d:02d}"))
    return sorted(out)


def pred(t):
    if not t or len(t.strip()) < 50:
        return None
    if not (re.search(GOV, t) and re.search(ANS, t, re.I)):
        return None
    ds = dates(t)
    if not ds:
        return None
    for m in CUE.finditer(t):
        after = [d for p, d in ds if p >= m.end() and p - m.end() < 80]
        if after:
            return after[0]
    return max(d for _, d in ds)
# ---------------------------------------------------------------- end of the reviewer's rule


def keyword_date(text: str, dtype: str) -> str | None:
    """The rule on one document: answer-typed documents only (the reviewer's gate)."""
    return pred(text) if dtype == "answer" else None


def doc_text(d: dict) -> tuple[str | None, str]:
    """(text, how): the committed sha256 checked on the cached PDF; fetched via the project path only when missing."""
    p = PDF_CACHE / f"{d['sha256']}.pdf"
    how = "cache"
    if not p.exists():
        from gegenprobe.compliance import fetchguard
        fetchguard.ensure()  # RFC 9309 robots (fail closed) and the fetch guard before any request
        try:
            pdftext.fetch_pdf(d["url"], expect_sha256=d["sha256"])
            how = "fetched"
        except Exception as e:  # robots disallow, HTTP error, hash mismatch: the document counts as null (no text)
            return None, f"unavailable ({type(e).__name__})"
    if hashlib.sha256(p.read_bytes()).hexdigest() != d["sha256"]:
        return None, "sha256 mismatch"
    return "\x0c".join(pdftext.extract(d["sha256"])["pages"]), how


def rows_with_keyword(texts: dict[int, str | None]) -> list[dict]:
    res = json.loads((RESULTS / "eval2" / f"p2__{BUILD}.json").read_text())
    meta = {d["doc_id"]: d for d in map(json.loads, open(DATA / "gold2" / "p2_docs.jsonl"))}
    rows = []
    for r in res["per_doc"]:
        m = meta[r["doc_id"]]
        kw = keyword_date(texts.get(r["doc_id"]) or "", m["dtype"])
        dd = r.get("doc_dates") or []
        latest = max(dd) if dd else None
        rows.append(dict(doc_id=r["doc_id"], body=m["body"], cell=r["cell"], dtype=m["dtype"], gold=r["gold"],
                         lenient=r.get("lenient") or [], doc_dates=dd,
                         pred=dict(pointer=r["pointer"].get("value"), keyword=kw,
                                   latest_date_on_answer_docs_only=latest if m["dtype"] == "answer" else None)))
    return rows


def _arm(rows: list[dict], arm: str) -> dict:
    return BL._score([dict(gold=r["gold"], lenient=r["lenient"], doc_dates=r["doc_dates"], pred=r["pred"][arm])
                      for r in rows])


def main() -> dict:
    docs = [json.loads(x) for x in open(DATA / "gold2" / "p2_docs.jsonl")]
    texts, how = {}, {}
    for d in docs:
        texts[d["doc_id"]], how[d["doc_id"]] = doc_text(d)
    rows = rows_with_keyword(texts)
    out = dict(label=LABEL, proposed_by="proposed in review (an external-style review of the submission); rule text "
               "unchanged, run by the team", n=len(rows),
               inputs=dict(sha256_verified=sum(v in ("cache", "fetched") for v in how.values()),
                           fetched=sum(v == "fetched" for v in how.values()),
                           unavailable=sorted(k for k, v in how.items() if v not in ("cache", "fetched"))),
               arms={a: _arm(rows, a) for a in ("pointer", "keyword", "latest_date_on_answer_docs_only")},
               paired=dict(pointer_vs_keyword=R3._pair(rows, "pointer", "keyword"),
                           keyword_vs_latest_date_on_answer_docs_only=R3._pair(rows, "keyword",
                                                                               "latest_date_on_answer_docs_only")))
    # the reviewer's own run lacked two documents (unreachable then); the same rule with those two as null
    rev_missing = [int(x) for x in REVIEWER_UNREACHABLE]
    rows_rev = rows_with_keyword({k: (None if k in rev_missing else v) for k, v in texts.items()})
    out["reviewer_input"] = dict(note="the same rule with the two documents the reviewer could not fetch counted as "
                                 "null (the reviewer's reported run)", unreachable=rev_missing,
                                 keyword=_arm(rows_rev, "keyword"),
                                 pointer_vs_keyword=R3._pair(rows_rev, "pointer", "keyword")["all"])
    kp = out["arms"]
    out["summary"] = dict(pointer_exact=[kp["pointer"]["exact"], len(rows)],
                          keyword_exact=[kp["keyword"]["exact"], len(rows)],
                          pointer_answer_dates_found=kp["pointer"]["value_recall"],
                          keyword_answer_dates_found=kp["keyword"]["value_recall"],
                          p_pointer_vs_keyword=out["paired"]["pointer_vs_keyword"]["all"]["p_str"])
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


# the two P2 documents the reviewer's re-fetch did not reach (counted as null in the reviewer's 47/62)
REVIEWER_UNREACHABLE = (64053, 869638)


if __name__ == "__main__":
    r = main()
    print(json.dumps(dict(summary=r["summary"], inputs=r["inputs"], arms=r["arms"],
                          paired={k: v["all"] for k, v in r["paired"].items()},
                          reviewer_input={k: v for k, v in r["reviewer_input"].items() if k != "note"}), indent=1))
    sys.exit(0)
