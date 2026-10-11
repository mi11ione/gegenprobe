"""Run a source adapter over every target affair of its parliament; resumable; writes the repair rows and the summary.

    python -m gegenprobe.repair.adapters.run BODY [BODY ...] [--limit N] [--cause absent|image_only] [--no-retry]
    python -m gegenprobe.repair.adapters.run --write [BODY ...]     rebuild outputs from the checkpoints (no network)
    python -m gegenprobe.repair.adapters.run --refilter [BODY ...]  re-judge saved excerpts with the current checks and
                                                                    filters; re-process the affairs a filter moved down
    python -m gegenprobe.repair.adapters.run --list                 the registered adapters

Checkpoint: one JSON line per affair in WORK/adapters/state/<BODY>.jsonl, appended as soon as the affair is done; a re-run
skips finished affairs and retries those that failed for a transient reason (timeout, network, HTTP 429/5xx).
Outputs (results/repair/adapters/):
  <BODY>.json             per-body summary + every affair's outcome (verified / review / failed with reason) and tier
  adapters_<BODY>.tsv     the list OPD applies: verified and review rows with tier, counted, opd_doc_id, target_category,
                          text_sha256 (lists.py); filter tier=review for the rows a person checks
  adapters_summary.json   per body: candidates, tiers, review, failed by reason; coverage against the 16,749
  tiers.json              per tier: rows by cause, action, date class and parliament
  filtered.tsv            every affair a document-type filter fired on (filters.py): filter, outcome, quote
Audit: WORK/adapters/audit/<BODY>.jsonl, a stratified sample of 30 (verified / review / failed) with excerpt paths,
drawn once and never overwritten (auditors' verdicts refer to it).
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
from . import base, lists, opd_docs, registry, targets

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
            best["opd_doc_id"] = rec["best"]["opd_doc_id"] = held["id"]
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


def refilter(body: str) -> dict:
    """After a change to the checks or filters: re-judge every saved excerpt (recheck, no network). An affair whose best
    document a filter moved down is processed again (process(): its other candidates, documents read from the WORK
    caches; adapters whose candidate list comes from the source's API ask it again), so an answer filed next to the
    filtered document can still verify. The re-processed record replaces the rechecked one only when it is better."""
    before = {k: r["outcome"] for k, r in load_state(body).items()}
    moved = recheck(body)
    after = load_state(body)
    redo = [r for k, r in after.items() if ((r.get("best") or {}).get("checks") or {}).get("filter")
            and ORDER[r["outcome"]] > ORDER[before[k]]]
    out = collections.Counter()
    if redo:
        ad = registry.get(body)
        xs = {x["id"]: x for x in targets.load(body)}
        opd = opd_docs.load(body)
        seed_url_cache(body)
        with open(STATE / f"{body}.jsonl", "a", encoding="utf-8") as f:
            for r in redo:
                rec = process(ad, xs[r["affair_id"]], opd.get(r["affair_id"], []))
                if ORDER[rec["outcome"]] < ORDER[r["outcome"]]:
                    rec["refiltered_from"] = dict(outcome=r["outcome"], reason=r.get("reason"),
                                                  url=(r.get("best") or {}).get("url"))
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out[f"{r['outcome']}->{rec['outcome']}"] += 1
                else:
                    out[f"{r['outcome']} kept"] += 1
                    if r.get("excerpt") and (r.get("best") or {}).get("url") != (rec.get("best") or {}).get("url"):
                        _restore_excerpt(body, r)
    return dict(rechecked={f"{a}->{b}": n for (a, b), n in moved.items()}, reprocessed=dict(out))


def _restore_excerpt(body: str, r: dict) -> None:
    """process() saved the text of its own best document; the kept record's excerpt is the filtered document's."""
    b = r.get("best") or {}
    text = None
    if b.get("origin") == "opd_text" and b.get("opd_doc_id"):
        text = next((d["text"] for d in opd_docs.load(body).get(r["affair_id"], []) if d["id"] == b["opd_doc_id"]), None)
    if text is None and b.get("url"):
        hit = base.url_cache_get(b["url"])
        text = hit[0] if hit else None
    if text is not None:
        base.save_excerpt(body, r["affair_id"], text, dict(affair_id=r["affair_id"], number=r["affair_number"],
                                                           url=b.get("url"), title=b.get("title"), origin=b.get("origin")))


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


def classify(body: str, rec: dict) -> dict:
    """The row tier of one affair (docs/adapters.md "Verification tiers"): failed, review, or the tier of a verified
    affair; a verified tag_answer / extract_tag row whose source file sits on the affair in OPD more than once
    (lists.opd_doc) goes to review (`opd_doc_ambiguous`). counted = the tier has a date check (COUNTED)."""
    b = rec.get("best") or {}
    chk = b.get("checks") or {}
    doc, ids, read = lists.opd_doc(body, rec) if rec["outcome"] != "failed" else (b.get("opd_doc_id"), [], None)
    out = dict(opd_doc_id=doc, opd_doc_ids=ids if len(ids) > 1 else None, review_reason=None)
    dm = chk.get("date_match")
    if rec["outcome"] == "failed":
        return dict(out, tier="failed", counted=False)
    if rec["outcome"] == "review":
        return dict(out, tier="review", counted=False,
                    review_reason=f"{rec.get('reason')}: {dm}" if dm and rec.get("reason") == "date_mismatch"
                    else rec.get("reason"))
    tier = tier_of(dm)
    if rec.get("action") in ("tag_answer", "extract_tag") and len(ids) > 1:
        why = (f"opd_doc_ambiguous: the source file is on this affair in OPD {len(ids)} times (ids "
               f"{' '.join(map(str, ids))}" + (f"; the version read is {read}" if read else "") + ")")
        return dict(out, tier="review", counted=False, review_reason=why, verified_tier=tier)
    if tier not in COUNTED:
        out["review_reason"] = f"{tier}: {dm}"
    return dict(out, tier=tier, counted=tier in COUNTED)


def to_row(rec: dict, snap: str, ad: base.Adapter, cl: dict | None = None) -> dict:
    cl = cl or classify(rec["body"], rec)
    b = rec["best"]
    chk, meta = b.get("checks") or {}, b.get("meta") or {}
    act = rec["action"]
    counted = cl["counted"]
    detail = dict(route=ad.body.lower() + ":" + (b["origin"] or ""), identity_by=chk.get("identity_by"),
                  date_match=chk.get("date_match"), date_ok=chk.get("date_ok"), sha256=meta.get("sha256"),
                  extractor=meta.get("extractor"),
                  chars=meta.get("chars"), source_typed_answer=b.get("source_typed_answer") or None,
                  gap_cause=rec["cause"], reason=rec.get("reason"), quote=chk.get("heading_quote"))
    link, place = lists.census_cols(rec["affair_id"], dict(outcome=rec["outcome"], action=act, cause=rec["cause"],
                                                           tier=cl["tier"], counted=counted))
    sets = act in lists.SETS_CATEGORY
    return dict(body=rec["body"], affair_id=rec["affair_id"], affair_number=rec["affair_number"],
                action=act if counted else "review", proposed_action=act, opd_doc_id=cl["opd_doc_id"],
                source_doc_uid=b.get("uid"), source_doc_title=b.get("title"), source_url=b.get("url"), snapshot=snap,
                check_identity=chk.get("identity"), check_heading=chk.get("heading"), check_decision_nr=None,
                check_decision_date=chk.get("doc_date"), check_answer_event_dates=chk.get("answer_events"),
                check_date_eq_event=chk.get("date_eq_event"),
                check_detail="; ".join(f"{k}={common._cell(v)}" for k, v in detail.items() if v not in (None, "", [])),
                verified=counted, tier=cl["tier"], counted=counted, review_reason=cl["review_reason"],
                text_sha256=lists.text_sha256(rec), target_category=lists.TARGET_CATEGORY if sets else None,
                target_category_note=lists.category_note(rec["body"]) if sets else None,
                census_link_status=link, census_category=place)


LIST_COLS = [c for c in common.COLS if c != "note"] + lists.EXTRA_COLS


def _write_tsv(path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, LIST_COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: common._cell(r.get(k)) for k in LIST_COLS})


def _reason_key(reason: str | None) -> str:
    """'date_mismatch: anywhere_conflict(-335d)' -> 'date_mismatch: anywhere_conflict'; 'opd_doc_ambiguous: ...' ->
    'opd_doc_ambiguous'."""
    head, _, rest = (reason or "").partition(": ")
    return f"{head}: {re.sub(r'[(].*', '', rest)}" if head == "date_mismatch" and rest else head


def body_summary(recs: list[dict], cls: dict[int, dict]) -> dict:
    out = collections.Counter(r["outcome"] for r in recs)
    fails = collections.Counter(r["reason"] for r in recs if r["outcome"] == "failed")
    by_action = collections.Counter(r.get("action") for r in recs if r["outcome"] == "verified")
    by_cause = collections.defaultdict(collections.Counter)
    for r in recs:
        by_cause[r["cause"]][r["outcome"]] += 1
    review_reasons = collections.Counter(_reason_key(cls[r["affair_id"]]["review_reason"])
                                         for r in recs if cls[r["affair_id"]]["tier"] == "review")
    ver = [r for r in recs if r["outcome"] == "verified"]
    date_class = collections.Counter(re.sub(r"\(.*", "", ((r.get("best") or {}).get("checks") or {}).get("date_match") or "")
                                     for r in ver)
    ident = collections.Counter(re.sub(r"\(.*", "", ((r.get("best") or {}).get("checks") or {}).get("identity_by") or "")
                                for r in ver)
    cands = sum(1 for r in recs if r.get("tried"))
    filt = collections.Counter(f"{((r.get('best') or {}).get('checks') or {}).get('filter')}:{r['outcome']}" for r in recs
                               if ((r.get("best") or {}).get("checks") or {}).get("filter"))
    row_tiers = collections.Counter(c["tier"] for c in cls.values())
    return dict(targets=len(recs), with_candidate=cands, verified=out["verified"], review=row_tiers["review"],
                counted=sum(row_tiers[t] for t in COUNTED), row_tiers={t: row_tiers[t] for t in ROW_TIERS},
                filtered=dict(sorted(filt.items())),
                failed=out["failed"], failed_by_reason=dict(fails.most_common()),
                review_by_reason=dict(review_reasons.most_common()), verified_by_action=dict(by_action),
                verified_by_date_match=dict(date_class.most_common()), verified_by_identity=dict(ident.most_common()),
                by_cause={k: dict(v) for k, v in by_cause.items()})


def write(body: str, summary: bool = True) -> dict:
    ad = registry.get(body)
    recs = sorted(load_state(body).values(), key=lambda r: r["affair_id"])
    snap = snapshot(body)
    cls = {r["affair_id"]: classify(body, r) for r in recs}
    rows = [to_row(r, snap, ad, cls[r["affair_id"]]) for r in recs if r["outcome"] in ("verified", "review")]
    OUT.mkdir(parents=True, exist_ok=True)
    for old in (OUT / f"repair_{body}.tsv", OUT / f"repair_{body}_review.tsv"):  # names before round 6
        old.unlink(missing_ok=True)
    _write_tsv(lists.path(body), rows)
    s = body_summary(recs, cls)
    s.update(body=body, label=ad.label, route=ad.route, hosts=list(ad.hosts), snapshot=snap)
    slim = []
    for r in recs:
        b = r.get("best") or {}
        chk = b.get("checks") or {}
        c = cls[r["affair_id"]]
        slim.append(dict(affair_id=r["affair_id"], number=r["affair_number"], cause=r["cause"], outcome=r["outcome"],
                         reason=r.get("reason"), action=r.get("action"), url=b.get("url"),
                         sha256=(b.get("meta") or {}).get("sha256"), date_match=chk.get("date_match"),
                         doc_date=chk.get("doc_date"), identity_by=chk.get("identity_by"), filter=chk.get("filter"),
                         filter_quote=chk.get("filter_quote"), tier=c["tier"], counted=c["counted"],
                         opd_doc_id=c["opd_doc_id"], review_reason=c["review_reason"]))
    base_json = dict(summary=s, affairs=slim)
    (OUT / f"{body}.json").write_text(json.dumps(base_json, ensure_ascii=False, indent=0, sort_keys=True))
    if not (AUDIT / f"{body}.jsonl").exists():  # drawn once: the auditors' verdicts refer to this sample
        audit(body, recs)
    if summary:
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


def fresh_audit(n: int = 300, seed: int = 20261111, out=None, exclude_dir=None) -> dict:
    """A fresh stratified random sample of counted verified rows (tiers exact_date and date_window) for blind auditors,
    excluding every affair of the first audit (WORK/adapters/audit): per parliament max(5, share of n proportional to
    its pool) where the pool allows, the rest by largest remainder. Each row has the first audit's fields; its excerpt
    is copied next to the sample (WORK/adapters/audit2/excerpts) so later runs cannot change what was judged."""
    import shutil
    out = out or base.ADIR / "audit2"
    exclude_dir = exclude_dir or AUDIT
    seen = set()
    for p in exclude_dir.glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                seen.add((r["body"], r["affair_id"]))
    pools = {}
    for p in sorted(OUT.glob("*.json")):
        if p.name in NOT_BODIES:
            continue
        b = p.stem
        st = load_state(b)
        ids = [a["affair_id"] for a in json.loads(p.read_text())["affairs"] if a["outcome"] == "verified"
               and tier_of(a.get("date_match")) in COUNTED and (b, a["affair_id"]) not in seen
               and st[a["affair_id"]].get("excerpt")]
        if ids:
            pools[b] = sorted(ids)
    total = sum(len(v) for v in pools.values())
    want = {b: min(5, len(v)) for b, v in pools.items()}
    rest = n - sum(want.values())
    share = {b: rest * len(v) / total for b, v in pools.items()}
    extra = {b: min(int(share[b]), len(pools[b]) - want[b]) for b in pools}
    left = rest - sum(extra.values())
    for b in sorted(pools, key=lambda b: (-(share[b] - int(share[b])), b)):
        if left <= 0:
            break
        if want[b] + extra[b] < len(pools[b]):
            extra[b] += 1
            left -= 1
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.jsonl"):
        f.unlink()
    counts = {}
    for b in sorted(pools):
        k = want[b] + extra[b]
        pick = sorted(rng.sample(pools[b], k))
        st = load_state(b)
        xs = {x["id"]: x for x in targets.load(b)}
        with open(out / f"{b}.jsonl", "w", encoding="utf-8") as f:
            for aid in pick:
                r = st[aid]
                bb = r.get("best") or {}
                x = xs.get(aid, {})
                ex = out / "excerpts" / b / f"{aid}.txt"
                ex.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(r["excerpt"], ex)
                f.write(json.dumps(dict(body=b, affair_id=aid, affair_number=r["affair_number"],
                                        opd_title=x.get("title"), opd_type=x.get("type"),
                                        opd_answer_event_dates=x.get("answer_dates"), outcome=r["outcome"],
                                        reason=r.get("reason"), proposed_action=r.get("action"),
                                        source_url=bb.get("url"), source_title=bb.get("title"), excerpt_path=str(ex),
                                        question="Is this document the government's written answer to this affair "
                                                 "(same affair, an answer not the question, dated consistently)?"),
                                   ensure_ascii=False) + "\n")
        counts[b] = k
    res = dict(n=sum(counts.values()), seed=seed, pool=total, excluded=len(seen), per_body=counts,
               pool_per_body={b: len(v) for b, v in pools.items()}, bodies=len(counts),
               note="fresh blind-audit sample of counted verified rows (exact date, date window), drawn after the "
                    "document-type filters; rows and excerpts in WORK/adapters/audit2 (never committed)")
    if out == base.ADIR / "audit2":
        (OUT / "audit2_sample.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True))
    return res


BASELINE = 3107  # results/report/figure_numbers.json: repairable_deterministic before the adapters
GAP = 16749
NEEDS_ADAPTERS = 10800
# the other files in OUT are one per body
SUMMARY = OUT / "adapters_summary.json"
# the other .json files in OUT are one per body
NOT_BODIES = ("adapters_summary.json", "tiers.json", "robots_audit.json", "audit_effect.json", "audit2_sample.json",
              "opd_categories.json", "canary.json", "summary.json")


# Verification tiers (docs/adapters.md "Verification tiers"): how strong the date check behind a verified row is. The first
# three count as verified repairs in the coverage figures; identity_wording_only is listed separately. An 'anywhere'
# match whose document date lies more than base.ANY_DATE_MAX_DAYS from every event is review (base.date_check).
TIERS = {
    "exact_doc_date": ("verified: the document's own date equals an OPD event date", ("eq", "eq_gov")),
    "exact_any_printed_date": ("verified: a date printed in the document equals an OPD answer event; the document's own "
                               f"date was not read, or lies within {base.ANY_DATE_MAX_DAYS} days of an event",
                               ("anywhere",)),
    "date_window": ("verified: the document's date within the parliament's documented window",
                    ("window", "latest_in_window")),
    "identity_wording_only": ("identity + wording only (no date check)", ("after_submission",)),
}
COUNTED = ("exact_doc_date", "exact_any_printed_date", "date_window")
ROW_TIERS = (*TIERS, "review", "failed")


def tier_of(date_match: str | None) -> str:
    cls = re.sub(r"\(.*", "", date_match or "")
    for k, (_, classes) in TIERS.items():
        if cls in classes:
            return k
    raise ValueError(f"verified row with date class {date_match!r} has no tier")


def body_tiers(body: str, affairs: list[dict]) -> dict:
    """Per row tier (verified tiers, review): rows by cause, action and date class; for the window tier the parliament's
    documented window (the adapter's date_window, event - document date in days) and the offsets observed."""
    out = {k: dict(n=0, absent=0, image_only=0, by_action=collections.Counter(), by_date_match=collections.Counter())
           for k in (*TIERS, "review")}
    offs = []
    for a in affairs:
        if a["tier"] not in out:
            continue
        t = out[a["tier"]]
        t["n"] += 1
        t[a["cause"]] += 1
        t["by_action"][a.get("action")] += 1
        t["by_date_match"][re.sub(r"\(.*", "", a.get("date_match") or "")] += 1
        m = re.search(r"\(\+?(-?\d+)d\)", a.get("date_match") or "")  # "window(+7d)", "window(+-61d)"
        if m and a["tier"] == "date_window":
            offs.append(int(m.group(1)))
    for t in out.values():
        t["by_action"], t["by_date_match"] = dict(t["by_action"]), dict(t["by_date_match"])
    if out["date_window"]["n"]:
        lo, hi = registry.get(body).date_window
        out["date_window"].update(window_days=[lo, hi], max_abs_days=max(abs(lo), abs(hi)),
                                  observed_days=[min(offs), max(offs)] if offs else None)
    return out


def write_summary() -> dict:
    per, tiers = {}, {}
    for p in sorted(OUT.glob("*.json")):
        if p.name in NOT_BODIES:
            continue
        d = json.loads(p.read_text())
        per[p.stem] = d["summary"]
        tiers[p.stem] = body_tiers(p.stem, d["affairs"])
        per[p.stem]["tiers"] = {k: v["n"] for k, v in tiers[p.stem].items() if k in TIERS}
        per[p.stem]["counted_by_action"] = dict(sum((collections.Counter(tiers[p.stem][k]["by_action"]) for k in COUNTED),
                                                    collections.Counter()))
    tot = {}
    for k in (*TIERS, "review"):
        rows = [t[k] for t in tiers.values()]
        tot[k] = dict(label=TIERS[k][0] if k in TIERS else "review: a person checks (not counted)",
                      date_classes=list(TIERS[k][1]) if k in TIERS else None, counted=k in COUNTED,
                      n=sum(r["n"] for r in rows), absent=sum(r["absent"] for r in rows),
                      image_only=sum(r["image_only"] for r in rows),
                      by_action=dict(sum((collections.Counter(r["by_action"]) for r in rows), collections.Counter())),
                      by_date_match=dict(sum((collections.Counter(r["by_date_match"]) for r in rows),
                                             collections.Counter())),
                      by_body={b: {kk: vv for kk, vv in t[k].items() if kk not in ("by_action", "by_date_match")}
                               for b, t in sorted(tiers.items()) if t[k]["n"]})
    ver_absent = sum(tot[k]["absent"] for k in COUNTED)
    ver_img = sum(tot[k]["image_only"] for k in COUNTED)
    rv = tot["review"]
    by_action, by_date = collections.Counter(), collections.Counter()
    for k in COUNTED:
        by_action.update(tot[k]["by_action"])
        by_date.update(tot[k]["by_date_match"])
    passed = sum(s["verified"] for s in per.values())
    filtered = collections.Counter()
    for s in per.values():
        filtered.update(s.get("filtered") or {})
    review_reasons = collections.Counter()
    for s in per.values():
        review_reasons.update(s.get("review_by_reason") or {})
    write_filtered()
    iw = tot["identity_wording_only"]
    counted_bodies = sorted(b for b, s in per.items() if s["counted"])
    out = dict(
        bodies=per,
        tiers={k: {kk: v[kk] for kk in ("label", "n", "absent", "image_only", "counted")} for k, v in tot.items()},
        totals=dict(verified=ver_absent + ver_img, verified_absent=ver_absent, verified_image_only=ver_img,
                    counted=ver_absent + ver_img, checks_passed_all_tiers=passed, identity_wording_only=iw["n"],
                    identity_wording_only_absent=iw["absent"], identity_wording_only_image_only=iw["image_only"],
                    review=rv["n"], review_absent=rv["absent"], review_image_only=rv["image_only"],
                    review_by_reason=dict(review_reasons.most_common()),
                    verified_by_action=dict(by_action), verified_by_date_match=dict(by_date),
                    identity_wording_only_by_date_match=iw["by_date_match"],
                    targets=sum(s["targets"] for s in per.values()),
                    adapters=len(per), adapters_with_counted=len(counted_bodies),
                    adapters_without_counted=len(per) - len(counted_bodies),
                    filtered=dict(sorted(filtered.items())),
                    failed_by_reason=dict(sum((collections.Counter(s["failed_by_reason"]) for s in per.values()),
                                              collections.Counter()).most_common())),
        coverage=dict(
            gap=GAP, baseline_repairable_deterministic=BASELINE,
            repairable_deterministic_with_adapters=BASELINE + ver_absent + ver_img,
            adapter_rows_counted=ver_absent + ver_img,
            needs_adapters_before=NEEDS_ADAPTERS, needs_adapters_after=NEEDS_ADAPTERS - ver_absent,
            identity_wording_only_listed_separately=iw["n"],
            note="adapter rows count only when verified with a date check: tiers exact_doc_date (the document's own "
                 "date equals an OPD event date), exact_any_printed_date (a printed date equals an OPD answer event "
                 "and the document's own date, if read, lies within 30 days of one) or date_window (within the "
                 "parliament's documented window); rows of tier identity_wording_only (Jura: OPD's answer events carry "
                 "no date) and review rows are listed but not counted. image_only affairs were OCR candidates, not "
                 "counted in the baseline of 3,107; they count once a text copy verifies."),
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").unlink(missing_ok=True)  # name before round 6 (results/repair/summary.json is the routes')
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
    (OUT / "tiers.json").write_text(json.dumps(dict(
        tiers=tot, counted=list(COUNTED),
        headline=dict(gap=GAP, baseline_repairable_deterministic=BASELINE,
                      repairable_deterministic_with_adapters=out["coverage"]["repairable_deterministic_with_adapters"],
                      adapter_rows_counted=ver_absent + ver_img,
                      needs_adapters_after=out["coverage"]["needs_adapters_after"],
                      listed_separately_identity_wording_only=iw["n"], review=rv["n"],
                      adapters=len(per), adapters_with_counted=len(counted_bodies))),
        ensure_ascii=False, indent=1, sort_keys=True))
    return out


def write_filtered() -> None:
    """filtered.tsv: every affair whose best document a document-type filter (filters.py) recognised, with the filter,
    the outcome it left and the quote that triggered it."""
    rows = []
    for p in sorted(OUT.glob("*.json")):
        if p.name in NOT_BODIES:
            continue
        for a in json.loads(p.read_text())["affairs"]:
            if a.get("filter"):
                rows.append((p.stem, a["affair_id"], a["number"], a["filter"], a["outcome"], a.get("reason") or "",
                             a.get("url") or "", re.sub(r"\s+", " ", a.get("filter_quote") or "")))
    with open(OUT / "filtered.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["body", "affair_id", "affair_number", "filter", "outcome", "reason", "source_url", "quote"])
        w.writerows(sorted(rows, key=lambda r: (r[0], r[1])))


def table() -> str:
    """The per-parliament results table of docs/adapters.md, from adapters_summary.json."""
    s = json.loads(SUMMARY.read_text())
    rows = sorted(s["bodies"].values(), key=lambda b: -b["targets"])
    out = ["| parliament | targets (absent + image-only) | exact document date | exact printed date | date window | "
           "of which tag/extract (in OPD) | identity + wording only (not counted) | review | failed: top reasons | "
           "moved down by document-type filters |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for b in rows:
        if not b["targets"]:
            continue
        t = b["tiers"]
        va = b["counted_by_action"]
        inopd = va.get("tag_answer", 0) + va.get("extract_tag", 0)
        reasons = ", ".join(f"{k} {v:,}" for k, v in sorted(b["failed_by_reason"].items(), key=lambda kv: (-kv[1], kv[0]))[:3])
        filt = collections.Counter()
        for k, v in (b.get("filtered") or {}).items():
            filt[k.split(":")[0]] += v
        moved = ", ".join(f"{k} {v:,}" for k, v in sorted(filt.items(), key=lambda kv: (-kv[1], kv[0])))
        out.append(f"| {b['label']} ({b['body']}) | {b['targets']:,} | {t['exact_doc_date']:,} | "
                   f"{t['exact_any_printed_date']:,} | {t['date_window']:,} | {inopd:,} | {t['identity_wording_only']:,} | "
                   f"{b['review']:,} | {reasons or '-'} | {moved or '-'} |")
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
    ap.add_argument("--fresh-audit", type=int, metavar="N",
                    help="draw a fresh audit sample of N counted verified rows into WORK/adapters/audit2")
    ap.add_argument("--recheck", action="store_true", help="re-run the checks on saved excerpts (no network)")
    ap.add_argument("--refilter", action="store_true",
                    help="recheck, then re-process the affairs a document-type filter moved down (cached documents)")
    a = ap.parse_args(argv)
    if a.table:
        print(table())
        return 0
    if a.fresh_audit:
        print(json.dumps(fresh_audit(a.fresh_audit), indent=1))
        return 0
    if a.list:
        for b, ad in registry.all().items():
            print(b, "|", ad.label, "|", ad.route)
        return 0
    for b in a.bodies or list(registry.all()):
        if a.recheck:
            print(b, "recheck", dict(recheck(b)), flush=True)
        if a.refilter:
            print(b, "refilter", json.dumps(refilter(b)), flush=True)
        s = (write(b, summary=False) if (a.write or a.recheck or a.refilter)
             else run_body(b, a.limit, a.cause, not a.no_retry, a.redo))
        print(json.dumps({k: s[k] for k in ("body", "targets", "counted", "review", "failed", "failed_by_reason")}))
    write_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
