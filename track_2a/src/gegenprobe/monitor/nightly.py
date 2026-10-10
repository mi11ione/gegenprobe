"""Nightly monitor + repair job.

One night =
  1. GET files.openparldata.ch/exports/index.json (one request) and compare each export's `created`/`size` with the state
     file (WORK/nightly/state.json). Unchanged exports are not touched.
  2. Single-file exports the census needs (affairs, events, agendas, bodies) are re-downloaded only when changed.
  3. Split docs_<body>/texts_<body> exports are re-scanned (metadata only, census.scan) only for bodies whose file size
     changed; every other body keeps last night's metadata. This is the incremental step: OPD regenerates all files nightly,
     but only bodies with new or edited documents change size.
  4. BE canton OGD tables (2 GETs, ~23 MB).
  5. census.extract -> census.funnel.compute on the nightly snapshot -> per-body answer-linking rates.
  6. repair.be list on the nightly snapshot -> new relink/fetch rows since the previous night.
  6b. every NEW relink/fetch row is triple-checked before it is emitted (affair number printed, answer heading, RRB date ==
     OPD answer event); a row that fails becomes action `review` (network mode only; offline rows stay unchecked).
  7. alerts.json (every alert carries the body key and name):
       linking_rate_drop     rate drops by more than DROP_PP points night over night (bodies with >= MIN_AFFAIRS)
       document_count_drop   a body's OPD document count falls by more than DOC_DROP
       new_body / body_gone  a body appears in or disappears from the rated set
       be_ogd_schema_change  the canton tables lost a column or an answer document type the join relies on
       be_ogd_answers_collapsed  the canton's answer-document count fell to zero or by more than half
       exports_stale         index.json older than GP_STALE_DAYS (default 2) days: OPD's export job may have stopped
       rate_trend_drop       a body's rate fell by more than TREND_PP points over the last TREND_NIGHTS nights (a slow
                             decline that never trips the night-over-night threshold)
  8. delivery (monitor.notify): alerts go to an outbox (WORK/nightly/outbox.json) first, then to the configured webhook /
     SMTP; the outbox is cleared only after a successful send, so an outage never loses an alert (it is re-sent with the
     next night's alerts). State is written after the send attempt. Exit code GP_ALERT_EXIT (default 3) when alerts fired,
     1 on error or when sending failed.
Outputs (GP_MONITOR_OUT, default results/monitor): rates.json, alerts.json, run.json; repair_BE_new.tsv (tonight's new rows)
and repair_BE_ledger.tsv (every row ever proposed: first_seen, last_seen, status pending | review | resolved | dropped).

Local exports: with GP_EXPORTS_DIR set (a mirror of files.openparldata.ch/exports, e.g. OPD's own export directory), every
exports URL is read from disk (net.local_exports); single exports are read in place and only changed docs/texts files are
re-scanned. The canton's two OGD tables are still fetched from the canton.

Linking rate (per body) = affairs with a written-answer event whose answer text is reachable in OPD (attached document,
`texts` row, or agenda item) / affairs with a written-answer event. Same definitions as the census.

usage:
  python -m gegenprobe.monitor.nightly run        full night (network)
  python -m gegenprobe.monitor.nightly offline    steps 5-7 on the current caches (no network); measures compute time
  python -m gegenprobe.monitor.nightly index      step 1 only: what changed since the cached snapshot (one request)
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .. import hardening, net
from ..paths import DOCS_META, OPD_RAW, RESULTS, ROOT, WORK

INDEX = "https://files.openparldata.ch/exports/index.json"
NIGHT = WORK / "nightly"
STATE = NIGHT / "state.json"
OUTBOX = NIGHT / "outbox.json"
OUT = Path(os.environ.get("GP_MONITOR_OUT", RESULTS / "monitor"))
SINGLE = ("affairs", "events", "agendas", "bodies")
DROP_PP = 2.0  # alert threshold: linking-rate drop in percentage points, night over night
MIN_AFFAIRS = 50  # only bodies with at least this many written-answer affairs are rated
DOC_DROP = 0.10  # alert when a body's OPD document count falls by more than 10 % (a scraper losing documents)
TREND_PP = 5.0  # alert when a body's rate fell by more than this over TREND_NIGHTS nights
TREND_NIGHTS = 7
STALE_DAYS = float(os.environ.get("GP_STALE_DAYS", "2"))
DOC_BUDGET_S = float(os.environ.get("GP_DOC_BUDGET_S", "600"))  # per-row ceiling for the triple check (fetch + extract)
LEDGER_COLS = ["key", "affair_id", "affair_number", "action", "opd_doc_id", "source_doc_uid", "source_url", "verified",
               "check_summary", "status", "first_seen", "last_seen"]


def _env(**kw) -> dict:
    e = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    e.update({k: str(v) for k, v in kw.items()})
    return e


def index_diff(old: dict, new: dict) -> dict:
    """Which exports changed between two index.json documents (by size, then created)."""

    def flat(idx):
        out = {}
        for e in idx["files"]:
            if e.get("type") == "single":
                out[e["entity"]] = (e["size"], e["created"])
            for f in e.get("files", []):
                out[f["filename"].removesuffix(".ndjson.gz")] = (f["size"], f["created"])
        return out

    a, b = flat(old), flat(new)
    changed = sorted(k for k in b if k in a and a[k][0] != b[k][0])
    return dict(
        changed=changed,
        new=sorted(set(b) - set(a)),
        gone=sorted(set(a) - set(b)),
        unchanged=len([k for k in b if k in a and a[k][0] == b[k][0]]),
        changed_bytes=sum(b[k][0] for k in changed),
        all_bytes=sum(v[0] for v in b.values()),
    )


def linking_rates(census_root: Path) -> tuple[dict, dict]:
    from ..census.funnel import compute

    res, aff = compute(census_root)
    c = collections.defaultdict(collections.Counter)
    for x in aff.values():
        if x["ev_w"]:
            c[x["b"]]["written"] += 1
            c[x["b"]]["linked"] += x["link"] in ("attached", "agenda")
    docs = {b: v.get("_n", 0) for b, v in res["docstat"].items()}
    rates = {
        b: dict(written=v["written"], linked=v["linked"], rate=round(100 * v["linked"] / v["written"], 2), docs=docs.get(b, 0))
        for b, v in sorted(c.items())
    } | {"_docs_only": {b: n for b, n in docs.items() if b not in c}}
    return rates, aff


def be_repair(census_root: Path, aff: dict) -> tuple[list[dict], dict]:
    """repair.be.join on the nightly snapshot: BE gap affairs x canton OGD answers x OPD parentless docs (census tables)."""
    from ..census.tables import rows
    from ..repair import be

    gap = {
        aid: dict(number=x["num"], external_id=x["ext"])
        for aid, x in aff.items()
        if x["b"] == "BE" and x["ev_w"] and not (x["dAt"] or x["tA"] or x["gAt"])
    }
    orph = {}
    for d in rows("docs", census_root):
        if d["body"] == "BE" and d["affair"] == "" and d["agenda"] == "" and d["meeting"] == "0" and d["be_uid"]:
            orph.setdefault(d["be_uid"], dict(id=int(d["id"])))
    answers, _ = be.load_ogd()
    rows_, c = be.join(answers, gap, orph)
    return rows_, dict(c)


def body_names(census_root: Path) -> dict[str, str]:
    from ..census.tables import rows

    try:
        return {r["key"]: r["name"] for r in rows("bodies", census_root)}
    except FileNotFoundError:
        return {}


def alerts(prev: dict, cur: dict, names: dict | None = None) -> list[dict]:
    names = names or {}
    out = []
    for b in sorted(set(prev) - set(cur)):
        if not b.startswith("_"):
            out.append(dict(body=b, kind="body_gone", prev_rate=prev[b]["rate"], prev_written=prev[b]["written"]))
    for b, r in cur.items():
        if b.startswith("_"):
            continue
        p = prev.get(b)
        if p is None:
            out.append(dict(body=b, kind="new_body", rate=r["rate"]))
            continue
        if r["written"] >= MIN_AFFAIRS and p["rate"] - r["rate"] > DROP_PP:
            out.append(
                dict(body=b, kind="linking_rate_drop", prev=p["rate"], cur=r["rate"], drop_pp=round(p["rate"] - r["rate"], 2))
            )
        if p.get("docs") and r["docs"] < (1 - DOC_DROP) * p["docs"]:
            out.append(dict(body=b, kind="document_count_drop", prev=p["docs"], cur=r["docs"]))
    for a in out:
        a["name"] = names.get(a["body"], "")
    return out


def trend_alerts(history: list[dict], cur: dict, names: dict | None = None) -> list[dict]:
    """Rate drop over TREND_NIGHTS nights (history: oldest first, each {ts, rates: {body: rate}})."""
    names = names or {}
    if len(history) < TREND_NIGHTS:
        return []
    old = history[-TREND_NIGHTS]["rates"]
    out = []
    for b, r in cur.items():
        if b.startswith("_") or r["written"] < MIN_AFFAIRS or b not in old:
            continue
        if old[b] - r["rate"] > TREND_PP:
            out.append(dict(body=b, name=names.get(b, ""), kind="rate_trend_drop", nights=TREND_NIGHTS, prev=old[b],
                            cur=r["rate"], drop_pp=round(old[b] - r["rate"], 2)))
    return out


def stale_alert(idx: dict | None, now: float | None = None) -> list[dict]:
    if not idx or not idx.get("generated_at"):
        return []
    gen = dt.datetime.fromisoformat(idx["generated_at"].replace("Z", "+00:00"))
    age = ((now or time.time()) - gen.timestamp()) / 86400
    if age > STALE_DAYS:
        return [dict(body="_exports", name="OpenParlData exports", kind="exports_stale", generated_at=idx["generated_at"],
                     age_days=round(age, 1))]
    return []


def ogd_alerts(prev: dict | None, cur: dict) -> list[dict]:
    out = []
    if cur["missing_columns"] or cur["missing_answer_types"]:
        out.append(dict(body="BE", name="Bern (canton OGD)", kind="be_ogd_schema_change",
                        missing_columns=cur["missing_columns"], missing_answer_types=cur["missing_answer_types"]))
    p = (prev or {}).get("answer_documents")
    if cur["answer_documents"] == 0 or (p and cur["answer_documents"] < 0.5 * p):
        out.append(dict(body="BE", name="Bern (canton OGD)", kind="be_ogd_answers_collapsed", prev=p,
                        cur=cur["answer_documents"]))
    return out


def verify_new(rows_: list[dict]) -> None:
    """Triple-check new relink/fetch rows before they are emitted (network mode). The canton's OGD PDF of the same document
    uid is checked (the census tables keep no document URLs)."""
    from .. import pdftext
    from ..repair import be

    _, geschaeft = be.load_ogd()
    vnr = {g["geschaeft_nr"]: g.get("geschaeft_vorstoss_nummer") for g in geschaeft.values()}
    ev = be.answer_events({r["affair_id"] for r in rows_}) if rows_ else {}
    for r in rows_:
        r["proposed_action"] = r.get("proposed_action") or r["action"]
        try:
            with hardening.time_budget(DOC_BUDGET_S):
                sha, path = pdftext.fetch_pdf(r["source_url"])
                text = "\n".join(pdftext.extract(sha, path, ocr=True)["pages"])
            c = be.verify_text(text, r["affair_number"], vnr.get(r["affair_number"]), ev.get(r["affair_id"], []))
            r["checks"] = dict(identity=c["identity"], heading=c["heading"], decision_nr=c["rrb_nr"],
                               decision_date=c["rrb_date"], answer_event_dates=c["opd_answer_events"],
                               date_eq_event=c["date_eq_event"], pdf_sha256=sha)
            r["verified"] = c["triple"]
        except Exception as e:  # typed: fetch_error rows are retried on the next night (transient), others stay in review
            kind = getattr(e, "kind", None) or type(e).__name__
            r["checks"], r["verified"] = dict(fetch_error=f"{kind}: {str(e)[:120]}"), False
        if not r["verified"]:
            r["action"] = "review"


PERMANENT = ("not_a_pdf", "sha_mismatch", "too_large", "HTTPError: HTTP Error 404", "HTTPError: HTTP Error 410")


def transient(check_summary: str) -> bool:
    """A failed check worth repeating the next night: a fetch error that is not a property of the document itself."""
    if not check_summary.startswith("fetch_error: "):
        return False
    return not check_summary.removeprefix("fetch_error: ").startswith(PERMANENT)


def _row_key(r: dict) -> str:
    return f"{r['affair_id']}:{r.get('proposed_action') or r['action']}:{r['source_doc_uid']}"


def _summary(checks) -> str:
    if not isinstance(checks, dict):
        return ""
    if "fetch_error" in checks:
        return "fetch_error: " + checks["fetch_error"]
    keys = ("identity", "heading", "date_eq_event")
    return " ".join(f"{k}={checks.get(k)}" for k in keys if k in checks)


def read_ledger(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["key"]: r for r in csv.DictReader(f, delimiter="\t")}


OPEN = ("pending", "review", "unchecked")


def _status(verified) -> str:
    v = str(verified)
    return "pending" if v == "True" else "review" if v == "False" else "unchecked"  # unchecked: offline night, no PDF read


def update_ledger(ledger: dict[str, dict], rows_: list[dict], aff: dict, today: str) -> dict[str, dict]:
    """Every row ever proposed. In tonight's list: pending (verified) / review (check failed) / unchecked (offline night).
    Gone from the list: resolved (the affair's answer is reachable in OPD now) / dropped (still unanswered)."""
    cur = {}
    for r in rows_:
        k = _row_key(r)
        old = ledger.get(k, {})
        cur[k] = dict(
            key=k, affair_id=r["affair_id"], affair_number=r.get("affair_number", ""),
            action=r.get("proposed_action") or r["action"], opd_doc_id=r.get("opd_doc_id") or "",
            source_doc_uid=r.get("source_doc_uid", ""), source_url=r.get("source_url", ""),
            verified=r["verified"] if "verified" in r else old.get("verified", ""),
            check_summary=_summary(r.get("checks")) or old.get("check_summary", ""),
            status=_status(r.get("verified", old.get("verified", ""))),
            first_seen=old.get("first_seen", today), last_seen=today,
        )
    for k, old in ledger.items():
        if k in cur:
            continue
        a = aff.get(int(old["affair_id"])) if str(old["affair_id"]).isdigit() else None
        reachable = bool(a and (a.get("dAt") or a.get("tA") or a.get("gAt")))
        cur[k] = dict(old, status="resolved" if reachable else ("dropped" if old["status"] in OPEN else old["status"]))
    return cur


def write_ledger(path: Path, ledger: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, LEDGER_COLS, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for k in sorted(ledger, key=lambda k: (str(ledger[k]["affair_id"]), k)):
            w.writerow(ledger[k])
    tmp.replace(path)


def _peak_rss_mb() -> float:
    """Largest resident set of this process or any finished child (the census extraction), for sizing MemoryMax."""
    import resource

    unit = 1 if sys.platform == "darwin" else 1024  # ru_maxrss: bytes on macOS, KiB on Linux
    rss = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return round(rss * unit / 2**20, 1)


def deliver(outbox: Path, to_send: list[dict], run: dict) -> None:
    """Persist the alerts in the outbox, send them, and clear the outbox only when the send succeeded; a failed send
    leaves them for the next night (alerts are never lost by committing state first)."""
    from .notify import send

    outbox.write_text(json.dumps(to_send, indent=1))
    try:
        run["notified"] = send(to_send, run)
        outbox.unlink()
        run["notify_error"] = None
    except Exception as e:  # the outbox stays; tomorrow's night re-sends it
        run["notified"] = []
        run["notify_error"] = f"{type(e).__name__}: {str(e)[:200]}"


def _download(entity: str, url: str, dest: Path) -> int:
    with net.open_url(url, timeout=900) as r:
        tmp = dest.with_suffix(".part")
        n = 0
        with open(tmp, "wb") as f:
            while b := r.read(1 << 20):
                f.write(b)
                n += len(b)
    tmp.replace(dest)
    return n


def night(offline: bool) -> dict:
    t = {}
    t0 = time.time()
    NIGHT.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    local = os.environ.get("GP_EXPORTS_DIR")
    if offline:
        opd, meta = OPD_RAW, DOCS_META
    else:
        opd = Path(local) if local else NIGHT / "opd"
        meta = Path(os.environ["GP_DOCS_META"]) if os.environ.get("GP_DOCS_META") else NIGHT / "docs_meta"
    transfer, idx = 0, None
    if not offline:
        opd.mkdir(parents=True, exist_ok=True)
        meta.mkdir(parents=True, exist_ok=True)
        idx = json.loads(net.get(INDEX))
        prev_idx = state.get("index")
        diff = index_diff(prev_idx, idx) if prev_idx else None
        if not local:  # single exports are read in place from GP_EXPORTS_DIR
            for e in idx["files"]:
                if e["entity"] in SINGLE and (not prev_idx or e["entity"] in diff["changed"]
                                              or not (opd / e["filename"]).exists()):
                    transfer += _download(e["entity"], e["url"], opd / e["filename"])
        changed_bodies = set()
        for e in idx["files"]:
            if e["entity"] in ("docs", "texts"):
                for f in e["files"]:
                    key = f["filename"].removesuffix(".ndjson.gz")
                    if not prev_idx or key in diff["changed"] or key in diff["new"]:
                        changed_bodies.add(f["filename"].split("_", 1)[1].split(".")[0])
        for bk in sorted(changed_bodies):  # one part directory per body, replaced atomically
            part = meta / f"part_{bk}"
            subprocess.run(
                [sys.executable, "-m", "gegenprobe.census.scan", str(part.with_suffix(".tmp")), bk], check=True, env=_env()
            )
            if part.exists():
                subprocess.run(["rm", "-rf", str(part)], check=True)
            part.with_suffix(".tmp").rename(part)
        from ..repair import be

        be.fetch_ogd()
        state["index"] = idx
        t["download_s"] = round(time.time() - t0, 1)
        t["rescanned_bodies"] = sorted(changed_bodies)
    t1 = time.time()
    census_out = NIGHT / "census"
    subprocess.run(
        [sys.executable, "-m", "gegenprobe.census.extract", "--out", str(census_out)],
        check=True,
        env=_env(GP_OPD_RAW=opd, GP_DOCS_META=meta),
        stdout=subprocess.DEVNULL,
    )
    t["extract_s"] = round(time.time() - t1, 1)
    t2 = time.time()
    rates, aff = linking_rates(census_out)
    t["rates_s"] = round(time.time() - t2, 1)
    t3 = time.time()
    rep, rep_counts = be_repair(census_out, aff)
    t["repair_be_s"] = round(time.time() - t3, 1)
    ledger_path = OUT / "repair_BE_ledger.tsv"
    ledger = read_ledger(ledger_path)
    prev_keys = set(state.get("be_repair_keys", []))
    keys = [_row_key(r) for r in rep]
    new = [r for r, k in zip(rep, keys) if k not in prev_keys]
    # rows whose check failed for a transient fetch reason (network, timeout, 5xx, unreadable robots.txt) are checked again
    retry = [r for r, k in zip(rep, keys) if k in prev_keys and transient(ledger.get(k, {}).get("check_summary", ""))]
    if not offline:
        verify_new(new + retry)
    names = body_names(census_out)
    prev_rates = state.get("rates", {})
    al = alerts(prev_rates, rates, names) if prev_rates else []
    history = state.get("history", [])
    al += trend_alerts(history, rates, names)
    if not offline:
        al += stale_alert(idx)
    from ..repair import be as _be

    health = _be.ogd_health()
    al += ogd_alerts(state.get("be_ogd"), health)
    t["total_s"] = round(time.time() - t0, 1)
    today = dt.date.today().isoformat()
    ledger = update_ledger(ledger, rep, aff, today)
    OUT.mkdir(parents=True, exist_ok=True)
    from ..repair.common import write_rows

    write_rows("BE_new", new, out=OUT)
    write_ledger(ledger_path, ledger)
    (OUT / "rates.json").write_text(json.dumps(rates, indent=1, sort_keys=True))
    # delivery: outbox first, send, clear only on success
    pending = json.loads(OUTBOX.read_text()) if OUTBOX.exists() else []
    to_send = pending + [dict(a, night=today) for a in al]
    (OUT / "alerts.json").write_text(json.dumps(dict(
        threshold_pp=DROP_PP, min_affairs=MIN_AFFAIRS, doc_drop=DOC_DROP, trend_pp=TREND_PP, trend_nights=TREND_NIGHTS,
        stale_days=STALE_DAYS, alerts=al, undelivered_from_previous_nights=pending), indent=1))
    run = dict(
        mode="offline" if offline else ("local-exports" if local else "network"),
        transfer_bytes=transfer,
        timings=t,
        bodies_rated=sum(1 for b in rates if not b.startswith("_")),
        alerts=len(al),
        alert_kinds=sorted({a["kind"] for a in al}),
        be_ogd=health,
        be_repair=rep_counts,
        be_repair_new_since_last_night=len(new),
        be_repair_retried=len(retry),
        ledger=dict(collections.Counter(r["status"] for r in ledger.values())),
        robots_unreadable=net.robots_report(),
        peak_rss_mb=_peak_rss_mb(),
        ts=round(time.time()),
    )
    deliver(OUTBOX, to_send, run)
    # state after the send attempt
    state["be_repair_keys"] = keys
    state["be_ogd"] = health
    state["rates"] = rates
    state["history"] = (history + [dict(ts=round(time.time()), rates={b: r["rate"] for b, r in rates.items()
                                                                       if not b.startswith("_")})])[-(TREND_NIGHTS + 1):]
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE)
    (OUT / "run.json").write_text(json.dumps(run, indent=1))
    run["_alerts"] = to_send
    return run


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "offline"
    if cmd == "index":
        new = json.loads(net.get(INDEX))
        old = json.loads((OPD_RAW / "index.json").read_text())
        d = index_diff(old, new)
        d.update(old_generated=old["generated_at"], new_generated=new["generated_at"])
        sizes = {f["filename"].removesuffix(".ndjson.gz"): f["size"] for e in new["files"] for f in e.get("files", [])}
        dt_ = [k for k in sizes if k.startswith(("docs_", "texts_"))]
        ch = [k for k in d["changed"] + d["new"] if k.startswith(("docs_", "texts_"))]
        single = {e["entity"]: e["size"] for e in new["files"] if e["entity"] in SINGLE}
        d["census_inputs"] = dict(
            docs_texts_files=len(dt_),
            docs_texts_changed=len(ch),
            docs_texts_bytes=sum(sizes[k] for k in dt_),
            docs_texts_changed_bytes=sum(sizes[k] for k in ch),
            single_exports_bytes=sum(single.values()),
        )
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "index_diff.json").write_text(json.dumps(d, indent=1))
        print({k: (v if not isinstance(v, list) else len(v)) for k, v in d.items()})
        return 0
    if cmd in ("run", "offline"):
        from .notify import exit_code

        run = night(offline=cmd == "offline")
        al = run.pop("_alerts")
        print(run)
        if run.get("notify_error"):
            print(f"alert delivery failed ({run['notify_error']}); kept in {OUTBOX} for the next night", file=sys.stderr)
            return 1
        return exit_code(al)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
