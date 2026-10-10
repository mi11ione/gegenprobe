"""Run a source adapter over every target affair of its parliament; resumable; writes the repair rows and the summary.

    python -m gegenprobe.repair.adapters.run BODY [BODY ...] [--limit N] [--cause absent|image_only] [--no-retry]
    python -m gegenprobe.repair.adapters.run --write [BODY ...]     rebuild outputs from the checkpoints (no network)
    python -m gegenprobe.repair.adapters.run --list                 the registered adapters

Checkpoint: one JSON line per affair in WORK/adapters/state/<BODY>.jsonl, appended as soon as the affair is done; a re-run
skips finished affairs and retries those that failed for a transient reason (timeout, network, HTTP 429/5xx).
Outputs (results/repair/adapters/):
  <BODY>.json             per-body summary + every affair's outcome (verified / review / failed with reason)
  repair_<BODY>.tsv       repair rows (verified and review), the columns of repair/common.py
  repair_<BODY>_review.tsv  the rows a person checks
  summary.json            per body: candidates, verified, review, failed by reason; coverage against the 16,749
Audit: WORK/adapters/audit/<BODY>.jsonl, a stratified sample of 30 (verified / review / failed) with excerpt paths.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import random
import re
import sys
import time

from ... import hardening
from ...paths import RESULTS
from .. import common
from . import base, opd_docs, registry, targets

OUT = RESULTS / "repair" / "adapters"
STATE = base.ADIR / "state"
AUDIT = base.ADIR / "audit"
DOC_BUDGET_S = 300
ORDER = {"verified": 0, "review": 1, "failed": 2}
REASON_ORDER = ["date_mismatch", "no_answer_event", "heading_fail", "identity_fail", "empty_text", "not_a_pdf", "too_large"]


def _rank(rec: dict) -> tuple:
    r = rec.get("reason") or ""
    return ORDER[rec["outcome"]], REASON_ORDER.index(r) if r in REASON_ORDER else 99


def process(ad: base.Adapter, x: dict, opd: list[dict]) -> dict:
    rec = dict(affair_id=x["id"], affair_number=x["number"], body=x["body"], cause=x["cause"], type=x["type"],
               year=x["year"], outcome="failed", reason=None, tried=[], at=dt.datetime.now().isoformat(timespec="seconds"))
    t0 = time.time()
    try:
        cands = ad.candidates(x, opd)
    except Exception as e:  # typed: robots, http, network, not_found ...
        rec.update(reason=base.failure_reason(e), detail=str(e)[:200])
        return rec
    if not cands:
        rec["reason"] = "no_candidate"
        return rec
    best = None
    for c in cands:
        one = dict(url=c.url, title=c.title[:160], origin=c.origin, opd_doc_id=c.opd_doc_id, uid=c.uid,
                   source_typed_answer=c.source_typed_answer, cmeta=c.meta)
        try:
            with hardening.time_budget(DOC_BUDGET_S):
                text, meta = ad.text(c)
            chk = ad.check(x, c, text)
            one.update(meta=meta, checks=chk, outcome=chk["outcome"], reason=chk["reason"])
            one["_text"] = text
        except Exception as e:
            one.update(outcome="failed", reason=base.failure_reason(e), detail=str(e)[:200])
        rec["tried"].append(one)
        if best is None or _rank(one) < _rank(best):
            best = one
        if one["outcome"] == "verified":
            break
    text = best.pop("_text", None)
    for t in rec["tried"]:
        t.pop("_text", None)
    rec.update(outcome=best["outcome"], reason=best.get("reason"), best={k: v for k, v in best.items()})
    if best["outcome"] != "failed" or text:
        origin = best["origin"]
        held = (best.get("cmeta") or {}).get("opd_holds")
        if held and held.get("same_affair"):  # the source's answer file is already on this affair in OPD
            origin = "opd_text" if (held.get("chars") or 0) >= 200 else "opd_file"
        rec["action"] = ("tag_answer" if origin == "opd_text" else "extract_tag" if origin == "opd_file"
                         else "relink" if held else ad.action)
        if held:
            best["opd_doc_id"] = held["id"]
        if text:
            p = base.save_excerpt(ad.body, x["id"], text, dict(affair_id=x["id"], number=x["number"], url=best["url"],
                                                                title=best["title"], origin=origin))
            rec["excerpt"] = str(p)
    rec["seconds"] = round(time.time() - t0, 1)
    return rec


def recheck(body: str) -> collections.Counter:
    """Re-run the checks of every affair's best candidate on its saved excerpt (no network): after a change to an
    adapter's formulas or date rule every row is judged by the same, current code. Rows whose outcome changes are
    appended to the checkpoint; a row that no longer verifies is picked up by --redo (other candidates)."""
    ad = registry.get(body)
    xs = {x["id"]: x for x in targets.load(body)}
    c: collections.Counter = collections.Counter()
    with open(STATE / f"{body}.jsonl", "a", encoding="utf-8") as f:
        for r in load_state(body).values():
            b, p = r.get("best") or {}, r.get("excerpt")
            if not (b.get("checks") and p and base.Path(p).exists()):
                continue
            text = base.Path(p).read_text(encoding="utf-8").split("\n\n", 1)[1]
            cand = base.Candidate(url=b.get("url"), title=b.get("title") or "", origin=b.get("origin") or "source",
                                  opd_doc_id=b.get("opd_doc_id"), uid=b.get("uid"),
                                  source_typed_answer=bool(b.get("source_typed_answer")), meta=b.get("cmeta") or {})
            chk = ad.check(xs[r["affair_id"]], cand, text)
            if chk["outcome"] != r["outcome"] or chk["reason"] != r.get("reason") or chk != b["checks"]:
                c[(r["outcome"], chk["outcome"])] += 1
                b.update(checks=chk, outcome=chk["outcome"], reason=chk["reason"])
                r.update(outcome=chk["outcome"], reason=chk["reason"], best=b, rechecked=True)
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return c


def load_state(body: str) -> dict[int, dict]:
    p = STATE / f"{body}.jsonl"
    out: dict[int, dict] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["affair_id"]] = r
    return out


def seed_url_cache(body: str) -> None:
    """Documents fetched by earlier runs (url + sha256 in the checkpoint) are re-read from WORK, not re-requested."""
    have = base._load_url_cache()
    for r in load_state(body).values():
        for t in r.get("tried", []):
            m = t.get("meta") or {}
            if t.get("url") and m.get("sha256") and m.get("kind") and t["url"] not in have:
                base.url_cache_put(t["url"], {k: m[k] for k in ("sha256", "extractor", "bytes", "kind") if k in m})


def run_body(body: str, limit: int | None = None, cause: str | None = None, retry: bool = True,
             redo: bool = False) -> dict:
    ad = registry.get(body)
    xs = targets.load(body, cause)
    opd = opd_docs.load(body)
    STATE.mkdir(parents=True, exist_ok=True)
    done = load_state(body)
    if redo:
        seed_url_cache(body)
    todo = [x for x in xs if x["id"] not in done or (retry and done[x["id"]].get("reason") in base.TRANSIENT)
            or (redo and done[x["id"]]["outcome"] != "verified")]
    if limit:
        todo = todo[:limit]
    print(f"[{body}] {len(xs)} targets, {len(done)} done, {len(todo)} to process", flush=True)
    with open(STATE / f"{body}.jsonl", "a", encoding="utf-8") as f:
        for n, x in enumerate(todo, 1):
            rec = process(ad, x, opd.get(x["id"], []))
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if n % 25 == 0 or n == len(todo):
                c = collections.Counter(r["outcome"] for r in load_state(body).values())
                print(f"[{body}] {n}/{len(todo)} {dict(c)}", flush=True)
    return write(body)


# ---------------------------------------------------------------- outputs
def snapshot(body: str) -> str:
    parts = [common.snapshot().split(";")[0]]
    m = opd_docs.meta(body)
    if m:
        parts.append(f"opd_docs_{body} {m['fetched']}")
    return "; ".join(p for p in parts if p)


def to_row(rec: dict, snap: str, ad: base.Adapter) -> dict:
    b = rec["best"]
    chk, meta = b.get("checks") or {}, b.get("meta") or {}
    act = rec["action"]
    verified = rec["outcome"] == "verified"
    detail = dict(route=ad.body.lower() + ":" + (b["origin"] or ""), identity_by=chk.get("identity_by"),
                  date_match=chk.get("date_match"), date_ok=chk.get("date_ok"), sha256=meta.get("sha256"),
                  extractor=meta.get("extractor"),
                  chars=meta.get("chars"), source_typed_answer=b.get("source_typed_answer") or None,
                  gap_cause=rec["cause"], reason=rec.get("reason"), quote=chk.get("heading_quote"))
    return dict(body=rec["body"], affair_id=rec["affair_id"], affair_number=rec["affair_number"],
                action=act if verified else "review", proposed_action=act, opd_doc_id=b.get("opd_doc_id"),
                source_doc_uid=b.get("uid"), source_doc_title=b.get("title"), source_url=b.get("url"), snapshot=snap,
                check_identity=chk.get("identity"), check_heading=chk.get("heading"), check_decision_nr=None,
                check_decision_date=chk.get("doc_date"), check_answer_event_dates=chk.get("answer_events"),
                check_date_eq_event=chk.get("date_eq_event"),
                check_detail="; ".join(f"{k}={common._cell(v)}" for k, v in detail.items() if v not in (None, "", [])),
                verified=verified, note=ad.route)


def _write_tsv(path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, common.COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: common._cell(r.get(k)) for k in common.COLS})


def body_summary(recs: list[dict]) -> dict:
    out = collections.Counter(r["outcome"] for r in recs)
    fails = collections.Counter(r["reason"] for r in recs if r["outcome"] == "failed")
    by_action = collections.Counter(r.get("action") for r in recs if r["outcome"] == "verified")
    by_cause = collections.defaultdict(collections.Counter)
    for r in recs:
        by_cause[r["cause"]][r["outcome"]] += 1
    review_reasons = collections.Counter(r["reason"] for r in recs if r["outcome"] == "review")
    ver = [r for r in recs if r["outcome"] == "verified"]
    date_class = collections.Counter(re.sub(r"\(.*", "", ((r.get("best") or {}).get("checks") or {}).get("date_match") or "")
                                     for r in ver)
    ident = collections.Counter(re.sub(r"\(.*", "", ((r.get("best") or {}).get("checks") or {}).get("identity_by") or "")
                                for r in ver)
    cands = sum(1 for r in recs if r.get("tried"))
    return dict(targets=len(recs), with_candidate=cands, verified=out["verified"], review=out["review"],
                failed=out["failed"], failed_by_reason=dict(fails.most_common()),
                review_by_reason=dict(review_reasons.most_common()), verified_by_action=dict(by_action),
                verified_by_date_match=dict(date_class.most_common()), verified_by_identity=dict(ident.most_common()),
                by_cause={k: dict(v) for k, v in by_cause.items()})


def write(body: str) -> dict:
    ad = registry.get(body)
    recs = sorted(load_state(body).values(), key=lambda r: r["affair_id"])
    snap = snapshot(body)
    rows = [to_row(r, snap, ad) for r in recs if r["outcome"] in ("verified", "review")]
    OUT.mkdir(parents=True, exist_ok=True)
    _write_tsv(OUT / f"repair_{body}.tsv", rows)
    _write_tsv(OUT / f"repair_{body}_review.tsv", [r for r in rows if r["action"] == "review"])
    s = body_summary(recs)
    s.update(body=body, label=ad.label, route=ad.route, hosts=list(ad.hosts), snapshot=snap)
    slim = [dict(affair_id=r["affair_id"], number=r["affair_number"], cause=r["cause"], outcome=r["outcome"],
                 reason=r.get("reason"), action=r.get("action"), url=(r.get("best") or {}).get("url"),
                 sha256=((r.get("best") or {}).get("meta") or {}).get("sha256"),
                 date_match=((r.get("best") or {}).get("checks") or {}).get("date_match"),
                 identity_by=((r.get("best") or {}).get("checks") or {}).get("identity_by"))
            for r in recs]
    base_json = dict(summary=s, affairs=slim)
    (OUT / f"{body}.json").write_text(json.dumps(base_json, ensure_ascii=False, indent=0, sort_keys=True))
    audit(body, recs)
    write_summary()
    return s


def audit(body: str, recs: list[dict], n: int = 30, seed: int = 20261011) -> None:
    """Stratified sample for blind auditors: up to 2/3 verified, the rest review and failed-with-text, seed fixed."""
    rng = random.Random(seed)
    strata = {k: [r for r in recs if r["outcome"] == k and r.get("excerpt")] for k in ("verified", "review", "failed")}
    want = {"verified": 20, "review": 6, "failed": 4}
    pick = []
    for k in ("verified", "review", "failed"):
        pool = strata[k]
        pick += rng.sample(pool, min(want[k], len(pool)))
    rest = [r for k in strata for r in strata[k] if r not in pick]
    pick += rng.sample(rest, min(n - len(pick), len(rest)))
    AUDIT.mkdir(parents=True, exist_ok=True)
    with open(AUDIT / f"{body}.jsonl", "w", encoding="utf-8") as f:
        for r in sorted(pick, key=lambda r: r["affair_id"]):
            b = r.get("best") or {}
            x = next((t for t in targets.load(body) if t["id"] == r["affair_id"]), {})
            f.write(json.dumps(dict(body=body, affair_id=r["affair_id"], affair_number=r["affair_number"],
                                    opd_title=x.get("title"), opd_type=x.get("type"),
                                    opd_answer_event_dates=x.get("answer_dates"), outcome=r["outcome"],
                                    reason=r.get("reason"), proposed_action=r.get("action"), source_url=b.get("url"),
                                    source_title=b.get("title"), excerpt_path=r.get("excerpt"),
                                    question="Is this document the government's written answer to this affair "
                                             "(same affair, an answer not the question, dated consistently)?"),
                               ensure_ascii=False) + "\n")


BASELINE = 3107  # results/report/figure_numbers.json: repairable_deterministic before the adapters
GAP = 16749
NEEDS_ADAPTERS = 10800


def write_summary() -> dict:
    per = {}
    for p in sorted(OUT.glob("*.json")):
        if p.name == "summary.json":
            continue
        per[p.stem] = json.loads(p.read_text())["summary"]
    ver_absent = sum(s["by_cause"].get("absent", {}).get("verified", 0) for s in per.values())
    ver_img = sum(s["by_cause"].get("image_only", {}).get("verified", 0) for s in per.values())
    rev_absent = sum(s["by_cause"].get("absent", {}).get("review", 0) for s in per.values())
    rev_img = sum(s["by_cause"].get("image_only", {}).get("review", 0) for s in per.values())
    by_action, by_date = collections.Counter(), collections.Counter()
    for s in per.values():
        by_action.update(s["verified_by_action"])
        by_date.update(s.get("verified_by_date_match", {}))
    out = dict(
        bodies=per,
        totals=dict(verified=ver_absent + ver_img, verified_absent=ver_absent, verified_image_only=ver_img,
                    review=rev_absent + rev_img, review_absent=rev_absent, review_image_only=rev_img,
                    verified_by_action=dict(by_action), verified_by_date_match=dict(by_date),
                    targets=sum(s["targets"] for s in per.values()),
                    failed_by_reason=dict(sum((collections.Counter(s["failed_by_reason"]) for s in per.values()),
                                              collections.Counter()).most_common())),
        coverage=dict(
            gap=GAP, baseline_repairable_deterministic=BASELINE,
            repairable_deterministic_with_adapters=BASELINE + ver_absent + ver_img,
            needs_adapters_before=NEEDS_ADAPTERS, needs_adapters_after=NEEDS_ADAPTERS - ver_absent,
            note="adapter rows count only when verified (identity + heading + a date consistent with OPD's events); "
                 "review rows are listed but not counted. image_only affairs were OCR candidates, not counted in the "
                 "baseline of 3,107; they count once a text copy verifies."),
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
    return out


def table() -> str:
    """The per-parliament results table of docs/adapters.md, from summary.json."""
    s = json.loads((OUT / "summary.json").read_text())
    rows = sorted(s["bodies"].values(), key=lambda b: -b["targets"])
    out = ["| parliament | targets (absent + image-only) | verified | of which tag/extract (in OPD) | review | failed: top "
           "reasons |", "|---|---|---|---|---|---|"]
    for b in rows:
        if not b["targets"]:
            continue
        va = b["verified_by_action"]
        inopd = va.get("tag_answer", 0) + va.get("extract_tag", 0)
        reasons = ", ".join(f"{k} {v:,}" for k, v in list(b["failed_by_reason"].items())[:3])
        out.append(f"| {b['label']} ({b['body']}) | {b['targets']:,} | {b['verified']:,} | {inopd:,} | {b['review']:,} | "
                   f"{reasons or '-'} |")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m gegenprobe.repair.adapters.run")
    ap.add_argument("bodies", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cause", choices=["absent", "image_only"])
    ap.add_argument("--no-retry", action="store_true")
    ap.add_argument("--redo", action="store_true", help="re-check every affair not verified (cached documents)")
    ap.add_argument("--write", action="store_true", help="rebuild outputs from checkpoints, no network")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--table", action="store_true", help="print the results table of docs/adapters.md")
    ap.add_argument("--recheck", action="store_true", help="re-run the checks on saved excerpts (no network)")
    a = ap.parse_args(argv)
    if a.table:
        print(table())
        return 0
    if a.list:
        for b, ad in registry.all().items():
            print(b, "|", ad.label, "|", ad.route)
        return 0
    for b in a.bodies or list(registry.all()):
        if a.recheck:
            print(b, "recheck", dict(recheck(b)), flush=True)
        s = write(b) if (a.write or a.recheck) else run_body(b, a.limit, a.cause, not a.no_retry, a.redo)
        print(json.dumps({k: s[k] for k in ("body", "targets", "verified", "review", "failed", "failed_by_reason")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
