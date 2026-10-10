"""Per-row verification of the whole BE list (every relink and fetch row), not a sample.

For each row the document OPD would re-attach (relink: the URL OPD stores for its parentless copy; fetch: the canton's
OGD PDF) is fetched politely, cached by sha256 in WORK, and checked three ways (be.verify_text):
  identity   the affair number (or the canton's Vorstoss number) is printed in the document
  heading    an answer heading is printed ("Antwort des Regierungsrates", "Réponse du Conseil-exécutif", ...)
  date       the printed RRB decision date equals one of OPD's answer-event dates for the affair
with BOTH RRB parsers: v1 (the parser frozen when the 40-row sample was pre-registered) and v2 (added afterwards, see
be.recheck_sample). A row is `verified` when the v2 triple holds; every other row becomes action `review`.

Resumable: one JSON per affair under WORK/repair/verify_all/; a row that failed for a transient reason (network, timeout,
HTTP 5xx, time budget) is fetched again on the next run. Per-row ceiling GP_DOC_BUDGET_S (default 600 s).
Writes results/repair/be_verify_all.json and a DONE marker.

    python -m gegenprobe.repair.verify_all [run|summary]
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time

from .. import hardening, pdftext
from ..paths import WORK
from ..stats import wilson_pct
from .be import answer_events, load_ogd, verify_text
from .common import OUT, iter_docs_meta

CACHE = WORK / "repair" / "verify_all"
LIST = OUT / "repair_BE.tsv"
RESULT = OUT / "be_verify_all.json"
DONE = CACHE / "DONE"
TRANSIENT = ("URLError", "TimeoutError", "timeout", "TimeBudgetExceeded", "HTTPError: HTTP Error 5", "ConnectionError",
             "RemoteDisconnected", "IncompleteRead", "network_error", "text_timeout")


def _rows() -> list[dict]:
    """Relink + fetch rows of the BE list as built by be.build_list (the combined repair_BE.tsv may already carry review
    rows, so the action we verify is the proposed one)."""
    out = []
    for r in csv.DictReader(open(LIST, encoding="utf-8"), delimiter="\t"):
        act = r.get("proposed_action") or r["action"]
        if act in ("relink", "fetch"):
            out.append(dict(r, proposed_action=act))
    return out


def run() -> dict:
    os.environ.setdefault("TESSDATA_PREFIX", str(WORK / "tessdata"))
    CACHE.mkdir(parents=True, exist_ok=True)
    if DONE.exists():
        DONE.unlink()
    rows = _rows()
    want = {int(r["opd_doc_id"]) for r in rows if r["opd_doc_id"]}
    url_of = {d["id"]: d.get("url") for d in iter_docs_meta({"BE"}) if d["id"] in want}
    _, geschaeft = load_ogd()
    vnr = {g["geschaeft_nr"]: g.get("geschaeft_vorstoss_nummer") for g in geschaeft.values()}
    ev = answer_events({int(r["affair_id"]) for r in rows})
    t0, done = time.time(), 0
    for r in rows:
        p = CACHE / f"{r['affair_id']}.json"
        if p.exists():
            prev = json.loads(p.read_text())
            if not str(prev.get("error", "")).startswith(TRANSIENT):
                continue
        aid = int(r["affair_id"])
        url = url_of.get(int(r["opd_doc_id"])) if r["proposed_action"] == "relink" else r["source_url"]
        rec = dict(affair_id=aid, affair_number=r["affair_number"], proposed_action=r["proposed_action"], url=url)
        try:
            with hardening.time_budget(float(os.environ.get("GP_DOC_BUDGET_S", "600"))):
                sha, path = pdftext.fetch_pdf(url)
                d = pdftext.extract(sha, path, ocr=True)
            text = "\n".join(d["pages"])
            rec.update(pdf_sha256=sha, extractor=d["extractor"])
            for v in (1, 2):
                rec[f"v{v}"] = verify_text(text, r["affair_number"], vnr.get(r["affair_number"]), ev.get(aid, []), parser=v)
        except Exception as e:  # network / robots / non-PDF: recorded, row goes to review
            rec["error"] = f"{getattr(e, 'kind', None) or type(e).__name__}: {str(e)[:160]}"
        p.write_text(json.dumps(rec, ensure_ascii=False))
        done += 1
        if done % 50 == 0:
            print(f"{done} new rows, {time.time() - t0:.0f} s", flush=True)
    res = summary()
    DONE.write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    print("DONE", json.dumps({k: v for k, v in res.items() if k != "rows"}), flush=True)
    return res


def _agg(recs: list[dict], v: int) -> dict:
    ok = [r for r in recs if f"v{v}" in r]
    n = len(recs)
    ident = sum(r[f"v{v}"]["identity"] for r in ok)
    head = sum(r[f"v{v}"]["heading"] for r in ok)
    with_ev = [r for r in ok if r[f"v{v}"]["opd_answer_events"]]
    date = sum(r[f"v{v}"]["date_eq_event"] is True for r in with_ev)
    tri = sum(r[f"v{v}"]["triple"] for r in ok)
    return dict(
        n=n,
        fetched=len(ok),
        identity=ident,
        ci_identity=wilson_pct(ident, n),
        heading=head,
        ci_heading=wilson_pct(head, n),
        with_answer_event=len(with_ev),
        date_eq_event=date,
        ci_date_eq_event=wilson_pct(date, len(with_ev)),
        triple=tri,
        ci_triple=wilson_pct(tri, n),
    )


def summary() -> dict:
    recs = [json.loads(p.read_text()) for p in sorted(CACHE.glob("*.json"))]
    by_act = {}
    for act in ("relink", "fetch"):
        sel = [r for r in recs if r["proposed_action"] == act]
        by_act[act] = dict(v1_registered=_agg(sel, 1), v2=_agg(sel, 2))
    errors = [dict(affair_number=r["affair_number"], error=r["error"]) for r in recs if "error" in r]
    res = dict(
        note="every relink/fetch row of the BE list, document fetched and checked; v1 = parser frozen for the "
        "pre-registered 40-row sample, v2 = parser added afterwards; verified := v2 triple",
        rows_checked=len(recs),
        by_action=by_act,
        fetch_errors=len(errors),
        errors=errors[:50],
        rows={
            str(r["affair_id"]): dict(
                sha=r.get("pdf_sha256"),
                identity=(r.get("v2") or {}).get("identity"),
                heading=(r.get("v2") or {}).get("heading"),
                rrb_nr=(r.get("v2") or {}).get("rrb_nr"),
                rrb_date=(r.get("v2") or {}).get("rrb_date"),
                rrb_date_v1=(r.get("v1") or {}).get("rrb_date"),
                answer_events=(r.get("v2") or {}).get("opd_answer_events"),
                date_eq_event=(r.get("v2") or {}).get("date_eq_event"),
                triple_v1=(r.get("v1") or {}).get("triple"),
                triple=(r.get("v2") or {}).get("triple"),
                error=r.get("error"),
            )
            for r in recs
        },
    )
    RESULT.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True))
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    r = run() if cmd == "run" else summary()
    print(json.dumps({k: v for k, v in r.items() if k not in ("rows", "errors")}, indent=1))
