"""Adapter canaries: one known affair per external source, re-checked live, plus a guard on the committed counts.

A parliament that changes its site, API or file layout breaks its adapter silently: the next monthly re-run would simply
verify fewer rows. A canary is one affair per source whose answer the adapter verified (a counted row of the committed
list); re-checking it runs the adapter's whole path again (candidates from the source's API or index, the document fetched
fresh through the polite network layer, extraction, identity / heading / date checks). It alerts when

  adapter_canary_failed        a canary that was counted is no longer counted (the reason says where it broke: a typed
                               failure such as http_404, not_found, robots_disallowed, empty_text, or the check that failed)
  adapter_canary_text_changed  still counted, but the extracted text's sha256 differs from the committed one (the source
                               re-published the file, or the text differs under the same extractor; informational).
                               Not raised when the document's bytes are the baseline's (`baseline.file_sha256`) and only
                               the extractor differs from the baseline's (`baseline.extractor`, e.g. the Docker image's
                               poppler 22.12 against the host's 26.02): the result then says `text_differs_by_extractor`
  adapter_counted_drop         a parliament's counted rows in results/repair/adapters/adapters_summary.json fell since the
                               last canary run by more than max(DROP_MIN, DROP_SHARE of the previous count) (after a re-run)

    python -m gegenprobe.repair.adapters.canary select    choose the canaries from WORK (checkpoints, targets, OPD docs)
                                                           -> results/repair/adapters/canary.json (committed)
    python -m gegenprobe.repair.adapters.canary check     offline: every canary is a counted row of its committed list with
                                                           the committed text hash (CI; exit 1 if not)
    python -m gegenprobe.repair.adapters.canary run       network (RFC 9309 robots + OPD mirror, one request at a time per
                                                           host): re-check every canary; WORK/canary/<date>.json and
                                                           WORK/canary/state.json; exit GP_ALERT_EXIT (default 3) on alerts
    python -m gegenprobe.repair.adapters.canary baseline  network: re-check every canary and, where it verifies with the
                                                           committed text hash, record the document's bytes hash and the
                                                           extractor in canary.json `baseline` (no other field changes)
    python -m gegenprobe.repair.adapters.canary run --fixtures DIR   the same, reading each canary's document text from
                                                           DIR/<BODY>_<affair_id>.txt instead of the network (tests, drills)

The nightly job runs `run` as an optional step when GP_ADAPTER_CANARY=1 (monitor/nightly.py), and its alerts go through
the nightly's outbox and channels; docs/runbook.md "Adapters: operating plan".
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

from ...paths import RESULTS, WORK
from . import base, lists, registry

CANARY = RESULTS / "repair" / "adapters" / "canary.json"
STATE_DIR = WORK / "canary"
OPD_HOST = "files.openparldata.ch"
DROP_MIN = 5
DROP_SHARE = 0.02
AFFAIR_KEYS = ("id", "body", "number", "type", "year", "cause", "title", "answer_dates", "gov_dates", "submit_dates",
               "external_id", "url_external")


def _host(url: str | None) -> str:
    return urllib.parse.urlsplit(url or "").netloc


# ---------------------------------------------------------------- select (WORK -> committed canary.json)
def select() -> dict:
    """Per external source (a host an adapter reads documents from): the counted row with an exact document date and the
    smallest affair id among the source's parliaments. OPD's own copies (files.openparldata.ch) get one canary through an
    extract_tag row (OPD's file, read and checked). Each canary carries the OPD metadata the check needs, so a re-check
    needs no WORK cache."""
    from . import opd_docs, run, targets
    s = json.loads(run.SUMMARY.read_text())
    sources: dict[str, list[str]] = {}
    for b, v in s["bodies"].items():
        for h in v["hosts"]:
            sources.setdefault(h, []).append(b)
    out = []
    for host, bodies in sorted(sources.items()):
        best = None
        for b in sorted(bodies):
            st = run.load_state(b)
            for aid in sorted(st):
                r = st[aid]
                url = (r.get("best") or {}).get("url")
                c = run.classify(b, r)
                if not (c["counted"] and c["tier"] == "exact_doc_date" and _host(url) == host):
                    continue
                if r.get("action") != ("extract_tag" if host == OPD_HOST else "fetch"):
                    continue
                if best is None or (r["affair_id"] < best[1]["affair_id"]):
                    best = (b, r, c)
                break
        if best is None:
            continue
        b, r, c = best
        x = next(t for t in targets.load(b) if t["id"] == r["affair_id"])
        # OPD's documents on the affair, without their text (an adapter may key on them: Aarau finds the answer next
        # to the question file OPD holds; the in-OPD route reads OPD's own file copy)
        opd = [{k: d.get(k) for k in ("id", "affair_id", "name", "url", "url_oparl", "format")} | dict(text="")
               for d in opd_docs.load(b).get(r["affair_id"], [])]
        out.append(dict(source=host, body=b, affair_id=r["affair_id"], affair_number=r["affair_number"],
                        action=r.get("action"), tier=c["tier"], source_url=r["best"].get("url"),
                        candidate=dict(title=r["best"].get("title"), uid=r["best"].get("uid"),
                                       origin=r["best"].get("origin"), opd_doc_id=r["best"].get("opd_doc_id"),
                                       source_typed_answer=bool(r["best"].get("source_typed_answer")),
                                       meta=r["best"].get("cmeta") or {}),
                        text_sha256=lists.text_sha256(r), affair={k: x.get(k) for k in AFFAIR_KEYS}, opd_docs=opd))
    return dict(note="one known counted affair per external source the adapters read (repair/adapters/canary.py); "
                     "re-checked live by `canary run` (nightly with GP_ADAPTER_CANARY=1)",
                selected=dt.date.today().isoformat(), canaries=out,
                counted_by_body={b: v["counted"] for b, v in sorted(s["bodies"].items())})


def load() -> dict:
    return json.loads(CANARY.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- check (offline, committed files only)
def check(cfg: dict | None = None) -> list[str]:
    """Problems with the committed canaries: each must be a counted row of its committed list with the same text hash,
    and the committed counts must equal adapters_summary.json."""
    import csv
    from . import run
    cfg = cfg or load()
    bad = []
    for c in cfg["canaries"]:
        with open(lists.path(c["body"]), encoding="utf-8") as f:
            row = next((r for r in csv.DictReader(f, delimiter="\t") if int(r["affair_id"]) == c["affair_id"]), None)
        if row is None or row["counted"] != "true":
            bad.append(f"{c['source']}: {c['body']} {c['affair_number']} is not a counted row of {lists.path(c['body']).name}")
        elif row["text_sha256"] != c["text_sha256"]:
            bad.append(f"{c['source']}: {c['body']} {c['affair_number']} text_sha256 differs from the committed list")
    s = json.loads(run.SUMMARY.read_text())
    if {b: v["counted"] for b, v in s["bodies"].items()} != cfg["counted_by_body"]:
        bad.append("counted_by_body differs from adapters_summary.json (re-run `canary select` after a re-run)")
    return bad


# ---------------------------------------------------------------- run (live re-check)
@contextlib.contextmanager
def _fresh(c: dict, fixtures: Path | None, scratch: Path):
    """Live: bypass the URL cache so every document is requested again. Fixtures: serve DIR/<BODY>_<id>.txt instead.
    Either way the re-check's excerpt goes to `scratch`, never over the committed run's excerpt in WORK/adapters."""
    saved = base.url_cache_get, base.fetch_text, base.ADIR
    base.url_cache_get = lambda url: None
    base.ADIR = scratch
    seen.clear()
    real = base.fetch_text
    # adapters that imported fetch_text by name (vs.py) get the same wrapper; restored below
    users = [m for n, m in list(sys.modules.items()) if n.startswith("gegenprobe.repair.adapters.") and m is not base
             and getattr(m, "fetch_text", None) is real]

    def recording(url, body, ocr=True, max_ocr_pages=4):
        t, m = real(url, body, ocr=ocr, max_ocr_pages=max_ocr_pages)
        seen[url] = dict(file_sha256=m.get("sha256"), extractor=m.get("extractor"))
        return t, m
    base.fetch_text = recording
    for m in users:
        m.fetch_text = recording
    if fixtures is not None:
        def fake(url, body, ocr=True, max_ocr_pages=4):
            p = fixtures / f"{c['body']}_{c['affair_id']}.txt"
            if not p.exists():
                raise base.Failure("not_found", f"fixture {p.name} missing")
            t = p.read_text(encoding="utf-8")
            m = dict(sha256=hashlib.sha256(t.encode()).hexdigest(), extractor="fixture", kind="txt")
            seen[url] = dict(file_sha256=m["sha256"], extractor=m["extractor"])
            return t, m
        base.fetch_text = fake
        for m in users:
            m.fetch_text = fake
    try:
        yield
    finally:
        base.url_cache_get, base.fetch_text, base.ADIR = saved
        for m in users:
            m.fetch_text = real


seen: dict[str, dict] = {}  # url -> {file_sha256, extractor} of the documents fetched during one re-check


class _Committed:
    """Fixtures mode: the adapter with its candidate list replaced by the committed candidate (no API, no robots
    request); text and checks are the adapter's own."""

    def __init__(self, ad, c: dict):
        self._ad, self._c = ad, c

    def __getattr__(self, k):
        return getattr(self._ad, k)

    def candidates(self, x, opd):
        k = self._c["candidate"]
        return [base.Candidate(url=self._c["source_url"], title=k.get("title") or "", origin=k["origin"],
                               opd_doc_id=k.get("opd_doc_id"), uid=k.get("uid"),
                               source_typed_answer=k.get("source_typed_answer", False), meta=dict(k.get("meta") or {}))]


def recheck(c: dict, fixtures: Path | None = None, scratch: Path | None = None) -> dict:
    """Run the adapter for one canary affair (candidates, text, checks) and classify the result like the committed list."""
    from . import run
    ad = registry.get(c["body"])
    if fixtures is not None:
        ad = _Committed(ad, c)
    t0 = time.time()
    with _fresh(c, fixtures, scratch or (STATE_DIR / "work")):
        rec = run.process(ad, dict(c["affair"]), [dict(d) for d in c.get("opd_docs") or []])
        cl = run.classify(c["body"], rec) if rec.get("best") else dict(tier="failed", counted=False)
        if rec["outcome"] == "failed":
            cl = dict(tier="failed", counted=False)
        sha = lists.text_sha256(rec)
    url = (rec.get("best") or {}).get("url")
    doc = seen.get(url) or {}
    out = dict(source=c["source"], body=c["body"], affair_id=c["affair_id"], affair_number=c["affair_number"],
               outcome=rec["outcome"], reason=rec.get("reason"), detail=rec.get("detail"), tier=cl["tier"],
               counted=cl["counted"], text_sha256=sha, same_text=sha == c["text_sha256"] if sha else None,
               url=url, seconds=round(time.time() - t0, 1))
    if doc:
        out.update(file_sha256=doc.get("file_sha256"), extractor=doc.get("extractor"))
    out["text_differs_by_extractor"] = by_extractor(out, c.get("baseline"))
    return out


def by_extractor(r: dict, bl: dict | None) -> bool:
    """The text hash differs only because the extractor does: the document's bytes are the baseline's and the extractor
    is another one (e.g. the Docker image's poppler 22.12 against the host's 26.02 the committed hash was taken with)."""
    return bool(r.get("same_text") is False and bl and bl.get("file_sha256") and r.get("file_sha256")
                and r["file_sha256"] == bl["file_sha256"] and r.get("extractor") and r["extractor"] != bl.get("extractor"))


def alerts(results: list[dict], counts_prev: dict | None, counts_now: dict, names: dict | None = None) -> list[dict]:
    names = names or {}
    out = []
    for r in results:
        name = names.get(r["body"], r["body"])
        if not r["counted"]:
            out.append(dict(kind="adapter_canary_failed", body=r["body"], name=name, source=r["source"],
                            affair=r["affair_number"], outcome=r["outcome"], tier=r["tier"], reason=r["reason"],
                            message=f"{name}: the canary affair {r['affair_number']} on {r['source']} no longer verifies "
                                    f"({r['outcome']}: {r['reason'] or r['tier']}); the adapter's path may have broken"))
        elif r["same_text"] is False and not r.get("text_differs_by_extractor"):
            out.append(dict(kind="adapter_canary_text_changed", body=r["body"], name=name, source=r["source"],
                            affair=r["affair_number"],
                            message=f"{name}: the canary {r['affair_number']} still verifies but its text changed"))
    for b, prev in sorted((counts_prev or {}).items()):
        now = counts_now.get(b, 0)
        if prev - now > max(DROP_MIN, DROP_SHARE * prev):
            name = names.get(b, b)
            out.append(dict(kind="adapter_counted_drop", body=b, name=name, previous=prev, now=now,
                            message=f"{name}: counted adapter rows fell from {prev:,} to {now:,}"))
    return out


def run_all(fixtures: Path | None = None, cfg: dict | None = None, state_dir: Path | None = None) -> dict:
    from . import run
    cfg = cfg or load()
    state_dir = state_dir or STATE_DIR
    results = []
    for c in cfg["canaries"]:
        try:
            results.append(recheck(c, fixtures))
        except Exception as e:  # never let one canary stop the others
            results.append(dict(source=c["source"], body=c["body"], affair_id=c["affair_id"],
                                affair_number=c["affair_number"], outcome="failed", reason=base.failure_reason(e),
                                detail=str(e)[:200], tier="failed", counted=False, text_sha256=None, same_text=None))
    state_p = state_dir / "state.json"
    prev = json.loads(state_p.read_text())["counted_by_body"] if state_p.exists() else cfg["counted_by_body"]
    now = {b: v["counted"] for b, v in json.loads(run.SUMMARY.read_text())["bodies"].items()}
    names = {b: v["label"] for b, v in json.loads(run.SUMMARY.read_text())["bodies"].items()}
    al = alerts(results, prev, now, names)
    res = dict(ts=round(time.time()), date=dt.date.today().isoformat(), mode="fixtures" if fixtures else "network",
               canaries=len(results), verified=sum(r["counted"] for r in results),
               expected=len(cfg["canaries"]), results=results, alerts=al)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{res['date']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    state_p.write_text(json.dumps(dict(counted_by_body=now, last=res["date"], verified=res["verified"]), indent=1))
    return res


def baseline(cfg: dict) -> list[dict]:
    """Live re-check; where a canary verifies with the committed text hash, record in cfg its document's bytes hash and the
    extractor that produced that text (`baseline`), so a later night can tell a re-published file from an extractor
    difference. Nothing else changes (text_sha256 stays the committed list's)."""
    out = []
    for c in cfg["canaries"]:
        r = recheck(c)
        out.append(r)
        if r["counted"] and r["same_text"] and r.get("file_sha256"):
            c["baseline"] = dict(file_sha256=r["file_sha256"], extractor=r["extractor"], checked=dt.date.today().isoformat(),
                                 url=r["url"])
    return out


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "select":
        cfg = select()
        CANARY.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{CANARY}: {len(cfg['canaries'])} canaries: "
              + ", ".join(f"{c['source']} ({c['body']} {c['affair_number']})" for c in cfg["canaries"]))
        return 0
    if cmd == "check":
        bad = check()
        for b in bad:
            print("canary:", b)
        print(f"{len(load()['canaries'])} canaries, {len(bad)} problems")
        return 1 if bad else 0
    if cmd == "baseline":
        cfg = load()
        rs = baseline(cfg)
        CANARY.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        for r in rs:
            print(f"{r['source']:28} {r['body']:5} {r['affair_number']:14} same_text={r['same_text']} "
                  f"extractor={r.get('extractor')} file={str(r.get('file_sha256'))[:16]}")
        n = sum(bool(c.get("baseline")) for c in cfg["canaries"])
        print(f"{CANARY}: baseline recorded for {n}/{len(cfg['canaries'])} canaries")
        return 0 if n == len(cfg["canaries"]) else 1
    if cmd == "run":
        fx = Path(argv[argv.index("--fixtures") + 1]) if "--fixtures" in argv else None
        res = run_all(fx)
        for r in res["results"]:
            print(f"{r['source']:28} {r['body']:5} {r['affair_number']:14} {r['outcome']:8} {r['tier']:22} "
                  f"same_text={r['same_text']}"
                  + (f" (same file, extractor {r['extractor']}: no alert)" if r.get("text_differs_by_extractor") else ""))
        for a in res["alerts"]:
            print("ALERT", a["kind"], a["message"])
        print(f"{res['verified']}/{res['expected']} canaries verified, {len(res['alerts'])} alerts")
        return int(os.environ.get("GP_ALERT_EXIT", "3")) if res["alerts"] else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
