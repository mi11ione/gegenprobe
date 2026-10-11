"""Project-wide robots.txt audit: every URL Gegenprobe fetched, or records as fetched, judged under RFC 9309.

    python -m gegenprobe.compliance.audit [--offline | --refresh]   -> results/compliance/robots_audit_all.json

Why: until 11 Oct 2026 (commit 099f416) gegenprobe.net judged robots.txt with urllib.robotparser, which applies the FIRST
matching rule; RFC 9309 applies the LONGEST. Hosts that list `Allow: /` before a narrower `Disallow` (www4.ti.ch) were
fetched on paths their robots.txt disallows (docs/incidents.md). This audit re-judges every recorded request.

Sources (each a "module"; committed files unless marked WORK or spike):
  gold_p1 .. p6          the gold-set samplers (eval/gold/sample.py, eval/gold2/sample.py:fetch_one and every sampler that
                         reuses it): *_docs / *_affairs / *_meetings (accepted documents: URL + sha256) and the fetch logs
                         (every attempt; doc-level logs are joined to OPD's URL by doc id through the docs metadata scan,
                         affair-level logs to the question/answer pair `eval.gold3.sample.pairs` chose), WORK drafts
  convert_demo           data/convert/demo_docs.json (make run step 4)
  repair_be / _che / _demo  results/repair (BE sample, verify40, fetch rows, WORK/repair/verify_all; CHE fedlex PDFs and
                         WORK/che_backlog.jsonl; the demo slice) + one example of each API request type
  adapters               WORK/adapters/url_cache.jsonl (every document the adapters downloaded) + API request types
  census_source_formats  results/census/source_formats_ti.json (one HTML page + headers-only requests)
  opd_exports            files.openparldata.ch/exports (census scan, hash check, opd_docs, VS scan, nightly)
  monitor_nightly        the nightly job's canton requests (Bern OGD tables, the BE rows it re-checks)
  spike_recovery         spikes/recovery (8 Oct, before this repository; its PDFs feed repair/ocr.py and verify40)
  ci_make_run            `make run` in CI (cold cache): the documents eval/rederive.py and eval/replay_all.py re-fetched,
                         reconstructed from results/ci/docker_make_run_*.json (their order and budget are deterministic)
  ci_jobs (summary)      workflows that fetch gold documents on GitHub runners, per invocation (run counts are in the
                         GitHub Actions history, not in this repository)

Request kinds: download (GET, body kept, sha256 recorded) | get_discarded (GET, body read and rejected: not a PDF, sha
mismatch) | page_read (an HTML page read and parsed) | headers_only (GET opened, status and headers read, body not read) |
failed (request sent, HTTP error or network error) | refused (never sent: robots.txt refusal at the time) | endpoint (one
example of an API/index request type) | unknown_url (an attempt whose URL was not logged and cannot be reconstructed).

robots.txt: read ONCE per host (User-Agent of gegenprobe.net), kept in data/compliance/robots/<host>.txt with the status
and date in _status.json; later runs re-use the copies (--refresh re-reads them, --offline never touches the network;
hosts the adapters' audit read on 11 Oct 2026 are taken from it). 2xx = rules; 4xx = no restrictions (RFC 9309
2.3.1.3); 5xx/network = host unreachable (not re-checkable today). Each URL also gets the stdlib first-match verdict net
used until 11 Oct 2026.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import glob
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

from .. import net, robots9309
from ..paths import DATA, DOCS_META, RESULTS, ROOT, WORK

OUT = RESULTS / "compliance" / "robots_audit_all.json"
ROBOTS_DIR = DATA / "compliance" / "robots"
SPIKE = Path(os.environ.get("GP_SPIKE_RECOVERY", Path.home() / "Desktop/hackapertus/spikes/recovery"))
FIX_COMMIT, FIX_TIME = "099f416", "2026-10-11T00:48:05+02:00"
MAKE_RUN_JOB = "2775988"  # commit that added the CI make-run job (9 Oct 2026, 20:04)
KINDS = ("download", "get_discarded", "page_read", "headers_only", "failed", "refused", "endpoint", "unknown_url")
SENT = ("download", "get_discarded", "page_read", "headers_only", "failed", "endpoint")  # a request reached the host
URL_RX = re.compile(r"https?://[^\s\"')]+")

REFERENCE_NOTES = {
    "https://www4.ti.ch": ("the rules that decide every Ticino verdict (User-agent: *, Allow: /, Disallow: "
                           "/poteri/gc/ricerca-messaggi-e-atti/ricerca/, Disallow: /user_librerie/php/GC/allegato.php) are "
                           "identical in the copy read on 10 Oct 2026 during the adapter run (excerpt in "
                           "tests/test_robots9309.py); no archived copy from 9 Oct 2026 was consulted"),
    "*": "every other host: today's robots.txt is the reference; no Wayback Machine copy was used",
}
# one example per API / index request type (not cached as documents); adapters' list from repair/adapters/robots_audit.py
ENDPOINTS = {
    "opd_exports": ["https://files.openparldata.ch/exports/index.json",
                    "https://files.openparldata.ch/exports/docs/docs_TI.ndjson.gz",
                    "https://files.openparldata.ch/exports/affairs.ndjson.gz"],
    "repair_be": ["https://ogd.parl.apps.be.ch/data/dokument.csv", "https://ogd.parl.apps.be.ch/data/geschaeft.csv",
                  "https://www.rrgr-service.apps.be.ch/api/gr/instances/585199c5-e188-44cb-b514-f143ada83635/render"
                  "?gnumber=2024.RRGR.91&lang=de"],
    "repair_che": ["https://fedlex.data.admin.ch/sparqlendpoint",
                   "https://ws.parlament.ch/odata.svc/Business?$filter=BusinessShortNumber%20eq%20%2705.3152%27"],
    "monitor_nightly": ["https://ogd.parl.apps.be.ch/data/dokument.csv", "https://ogd.parl.apps.be.ch/data/geschaeft.csv",
                        "https://files.openparldata.ch/exports/index.json"],
}
# workflows that fetch gold documents from their recorded URLs on GitHub runners: (workflow, job, parallel jobs, sets)
CI_JOBS = [
    ("arms-8b.yml", "fit", 1, ["gold_dev"]), ("arms-8b.yml", "shard", 6, ["gold_heldout"]),
    ("arms-8b-par.yml", "warm", 6, ["gold_dev"]), ("arms-8b-par.yml", "fit", 1, ["gold_dev"]),
    ("arms-8b-par.yml", "shard", 6, ["gold_heldout"]), ("arms-8b-fill.yml", "fill", 1, ["gold_heldout"]),
    ("arms-8b-p2.yml", "shard", 6, ["gold_p2"]), ("arms-8b-p6.yml", "fit", 1, ["gold_dev", "p6_test"]),
    ("arms-8b-p6.yml", "shard", 6, ["gold_dev", "p6_test"]),
    ("nightly-real.yml / nightly-real-docker.yml", "night 1", 1, ["be_rows"]),
]


# ---------------------------------------------------------------- helpers
def _jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def _rel(p: Path) -> str:
    p = Path(p)
    for base, tag in ((ROOT, ""), (WORK, "WORK/"), (SPIKE, "spikes/recovery/")):
        try:
            return tag + str(p.resolve().relative_to(base.resolve()))
        except ValueError:
            continue
    return str(p)


_DATES: dict[str, str | None] = {}


def file_date(p: Path) -> str | None:
    """Committed file: date it was first committed (git); otherwise its modification time (local date)."""
    key = str(p)
    if key not in _DATES:
        d = None
        try:
            rel = Path(p).resolve().relative_to(ROOT.resolve())
            out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%ad", "--date=short", "--", str(rel)],
                                 cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.split()
            d = out[-1] if out else None
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
        if d is None and Path(p).exists():
            d = dt.datetime.fromtimestamp(Path(p).stat().st_mtime).date().isoformat()
        _DATES[key] = d
    return _DATES[key]


def pdf_date(sha: str | None) -> str | None:
    """When WORK/pdf/<sha>.pdf was written (fetch_pdf writes a document once: the first download)."""
    if not sha:
        return None
    p = WORK / "pdf" / f"{sha}.pdf"
    return dt.datetime.fromtimestamp(p.stat().st_mtime).date().isoformat() if p.exists() else None


def classify_error(msg: str | None) -> tuple[str, str | None]:
    """(request kind, URL named in the message) for a sampler's error string."""
    m = msg or ""
    u = URL_RX.search(m)
    url = u.group(0).rstrip(".,;") if u else None
    if m.startswith("Disallowed") or "robots_disallowed" in m or "robots.txt" in m:
        return "refused", url
    if any(x in m.lower() for x in ("not_a_pdf", "not a pdf", "sha_mismatch", "too_large", "sha256 changed")):
        return "get_discarded", url
    if m.startswith("text too short"):
        return "download", url
    return "failed", url


def rec(module: str, url: str | None, request: str, source: Path | str, **kw) -> dict:
    src = _rel(source) if isinstance(source, Path) else source
    date = kw.pop("date", None)
    if date is None:
        date = (pdf_date(kw.get("sha256")) if request == "download" else None) or (
            file_date(source) if isinstance(source, Path) else None)
    return dict(module=module, url=net.quote_url(url) if url else None, request=request, source=src, date=date,
                **{k: v for k, v in kw.items() if v is not None})


# ---------------------------------------------------------------- OPD metadata joins (offline)
def docs_meta(ids: set) -> dict[int, dict]:
    """doc id -> {url, b, a} from the docs metadata scan (GP_DOCS_META/part*/docs_meta.jsonl.gz)."""
    out: dict[int, dict] = {}
    if not ids:
        return out
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt", encoding="utf-8"):
            i = int(line[7:line.index(",")]) if line.startswith('{"id": ') else json.loads(line)["id"]
            if i in ids and i not in out:
                d = json.loads(line)
                out[i] = dict(url=d.get("url"), b=d.get("b"), a=d.get("a"))
    return out


def affair_pairs(bodies: set[str]) -> dict[tuple[str, int], dict]:
    """(body, affair) -> {question, answer} as the P3/P3b/P5 samplers paired them (eval.gold3.sample.pairs, offline)."""
    if not bodies:
        return {}
    try:
        from eval.gold3 import sample as s3
    except Exception as e:  # eval/ not importable (installed package without the checkout)
        print(f"[audit] affair pairs unavailable: {e}", file=sys.stderr)
        return {}
    saved = s3.BODIES
    s3.BODIES = set(bodies)
    try:
        pl = s3.pairs()
    finally:
        s3.BODIES = saved
    return {(b, c["affair"]): c for b, cs in pl.items() for c in cs}


# ---------------------------------------------------------------- collectors
def doc_rows(module: str, path: Path) -> list[dict]:
    """Accepted documents of a gold file: rows with url+sha256, also nested (affair docs, meeting agenda/minutes)."""
    out = []
    for r in _jsonl(path):
        docs = r.get("docs") or [r.get(k) for k in ("agenda", "minutes") if isinstance(r.get(k), dict)] or [r]
        for d in docs:
            if d.get("url"):
                out.append(rec(module, d["url"], "download" if d.get("sha256") else "unknown_url", path,
                               doc_id=d.get("doc_id"), sha256=d.get("sha256")))
    return out


def doc_log(module: str, path: Path, meta: dict[int, dict]) -> list[dict]:
    out = []
    for r in _jsonl(path):
        i = r.get("doc_id")
        if i is None:  # shortfall summary rows
            continue
        err = r.get("error")
        kind, url = classify_error(err) if err else ("download", None)
        url = url or (meta.get(i) or {}).get("url")
        out.append(rec(module, url, kind if url else "unknown_url", path, doc_id=i, sha256=r.get("sha256"), error=err))
    return out


def affair_log(module: str, path: Path, pairs: dict, known: dict[int, dict]) -> list[dict]:
    """Affair-level logs (P3, P3b, P5, P5 dev): question fetched first, the answer only if the question was accepted."""
    out = []
    for r in _jsonl(path):
        a = r.get("affair_id")
        if a is None:
            continue
        pair = known.get(a) or pairs.get((str(r.get("body")), a)) or {}
        steps = [("question", r.get("q_error"))]
        if not r.get("q_error"):
            steps.append(("answer", r.get("a_error")))
        for role, err in steps:
            d = pair.get(role) or {}
            kind, url = classify_error(err) if err else ("download", None)
            url = url or d.get("url")
            out.append(rec(module, url, kind if url else "unknown_url", path, doc_id=d.get("doc_id") or d.get("id"),
                           affair_id=a, role=role, sha256=d.get("sha256"), error=err))
    return out


def known_affairs(*paths: Path) -> dict[int, dict]:
    out = {}
    for p in paths:
        for r in _jsonl(p):
            out[r["affair_id"]] = {d["role"]: d for d in r.get("docs", [])}
    return out


def gold_sets() -> list[dict]:
    g = DATA
    out: list[dict] = []
    for m, f in (("gold_p1", g / "gold/dev_docs.jsonl"), ("gold_p1", g / "gold/heldout_docs.jsonl"),
                 ("gold_p1", WORK / "dev_docs_v1.jsonl"), ("gold_p1", WORK / "heldout_docs_draw1.jsonl"),
                 ("gold_p2", g / "gold2/p2_docs.jsonl"), ("gold_p2", WORK / "p2_docs_v1.jsonl"),
                 ("gold_p3", g / "gold3/p3_affairs.jsonl"),
                 ("gold_p4", g / "gold4/p4_meetings.jsonl"), ("gold_p4", g / "gold4/p4_heldout_meetings.jsonl"),
                 ("gold_p4", g / "gold4/p4_transfer_meetings.jsonl"),
                 ("gold_p3b", g / "gold5/p3b_affairs.jsonl"), ("gold_p5", g / "gold6/p5_affairs.jsonl"),
                 ("gold_p5dev", g / "gold6/p5dev_affairs.jsonl"),
                 ("p6", g / "p6/p6_docs.jsonl"), ("p6", g / "p6/dev2_docs.jsonl")):
        out += doc_rows(m, f)
    dlogs = [("gold_p1", g / "gold/dev_fetch_log.jsonl"), ("gold_p1", g / "gold/heldout_fetch_log.jsonl"),
             ("gold_p2", g / "gold2/p2_fetch_log.jsonl"), ("gold_p2", WORK / "p2_fetch_log_v1.jsonl"),
             ("p6", g / "p6/p6_fetch_log.jsonl"), ("p6", g / "p6/dev2_fetch_log.jsonl")]
    ids = {r["doc_id"] for _, f in dlogs for r in _jsonl(f) if r.get("doc_id") is not None}
    meta = docs_meta(ids)
    for m, f in dlogs:
        out += doc_log(m, f, meta)
    alogs = [("gold_p3", g / "gold3/p3_fetch_log.jsonl", g / "gold3/p3_affairs.jsonl"),
             ("gold_p3b", g / "gold5/p3b_fetch_log.jsonl", g / "gold5/p3b_affairs.jsonl"),
             ("gold_p5", g / "gold6/p5_fetch_log.jsonl", g / "gold6/p5_affairs.jsonl"),
             ("gold_p5dev", g / "gold6/p5dev_fetch_log.jsonl", g / "gold6/p5dev_affairs.jsonl")]
    known = known_affairs(*(a for _, _, a in alogs))
    bodies = {str(r.get("body")) for _, f, _ in alogs for r in _jsonl(f) if r.get("affair_id") not in known}
    pairs = {k: {"question": dict(v["question"], doc_id=v["question"]["id"]),
                 "answer": dict(v["answer"], doc_id=v["answer"]["id"])} for k, v in affair_pairs(bodies).items()}
    for m, f, _ in alogs:
        out += affair_log(m, f, pairs, known)
    return out


def repair() -> list[dict]:
    out = []
    p = RESULTS / "repair" / "be_relink_sample.json"
    if p.exists():
        out += [rec("repair_be", r["opd_url"], "download", p, doc_id=r.get("opd_doc_id"), sha256=r.get("pdf_sha256"))
                for r in json.loads(p.read_text())["rows"]]
    p = RESULTS / "repair" / "repair_BE_fetch.json"
    if p.exists():
        for r in json.loads(p.read_text())["rows"]:
            sha = (re.search(r"pdf_sha256=([0-9a-f]{64})", r.get("check_detail") or "") or [None, None])[1]
            out.append(rec("repair_be", r["source_url"], "download" if sha else "failed", p, sha256=sha))
    for f in sorted((WORK / "repair" / "verify_all").glob("*.json")):
        r = json.loads(f.read_text())
        if r.get("url"):
            out.append(rec("repair_be", r["url"], "download" if r.get("pdf_sha256") else "failed", f,
                           sha256=r.get("pdf_sha256"), error=r.get("error")))
    p = RESULTS / "repair" / "che_reproduce.json"
    if p.exists():
        out += [rec("repair_che", r["recovered_url"], "download", p, doc_id=r.get("doc_id"))
                for r in json.loads(p.read_text())["rows"] if r.get("recovered_url")]
    for r in _jsonl(WORK / "che_backlog.jsonl"):
        if r.get("recovered_url"):
            out.append(rec("repair_che", r["recovered_url"], "download" if r.get("pdf_sha256") else "failed",
                           WORK / "che_backlog.jsonl", doc_id=r.get("doc_id"), sha256=r.get("pdf_sha256")))
    p = DATA / "repair" / "demo" / "slice.json"
    if p.exists():
        out += [rec("repair_demo", d["url"], "download", p, doc_id=d.get("id"), sha256=d.get("sha256"))
                for d in json.loads(p.read_text()).get("parentless_docs", []) if d.get("url")]
    return out


def adapters() -> list[dict]:
    out = []
    p = WORK / "adapters" / "url_cache.jsonl"
    for r in _jsonl(p):
        out.append(rec("adapters", r["url"], "download", p, sha256=(r.get("meta") or {}).get("sha256")))
    # the three Ticino files of the 10 Oct incident: downloaded by the adapters, then deleted from the cache (incidents.md)
    out += [rec("adapters", f"https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid={i}", "download",
                "docs/incidents.md (adapter cache entries deleted 10 Oct 2026)", date="2026-10-10")
            for i in (115005, 119023, 137701)]
    try:
        from ..repair.adapters.robots_audit import ENDPOINTS as AE
    except Exception:
        AE = []
    out += [rec("adapters", u, "endpoint", "src/gegenprobe/repair/adapters (API request types)") for u in AE]
    return out


def census_source_formats() -> list[dict]:
    p = RESULTS / "census" / "source_formats_ti.json"
    out = []
    if not p.exists():
        return out
    d = json.loads(p.read_text())
    for w in (d.get("withdrawn") or {}).get("requests", []):  # requests whose result was withdrawn on 11 Oct 2026
        out.append(rec("census_source_formats", w["url"], w["request"], p, date=w.get("date")))
    for a in d.get("attos", []):
        if a.get("page"):
            out.append(rec("census_source_formats", a["page"], "page_read", p, date=d.get("checked")))
        for f in a.get("source_answer_files", []):
            out.append(rec("census_source_formats", f["url"], "headers_only", p, date=d.get("checked")))
    return out


def convert_demo() -> list[dict]:
    p = DATA / "convert" / "demo_docs.json"
    return [rec("convert_demo", d["url"], "download", p, doc_id=d.get("doc_id"), sha256=d.get("sha256"))
            for d in (json.loads(p.read_text())["docs"] if p.exists() else []) if d.get("url")]


def endpoints() -> list[dict]:
    return [rec(m, u, "endpoint", "request types (code)") for m, us in ENDPOINTS.items() for u in us]


def monitor_nightly() -> list[dict]:
    """Night 1 of the real nightly run re-checks every BE relink/fetch row: the canton's OGD PDF of each row."""
    p = RESULTS / "repair" / "repair_BE.tsv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return [rec("monitor_nightly", r["source_url"], "download", p, date="2026-10-10") for r in rows if r.get("source_url")]


def spike_recovery() -> list[dict]:
    out = []
    if not SPIKE.exists():
        return out
    p = SPIKE / "reextract.json"
    if p.exists():
        for r in json.loads(p.read_text()):
            have = (SPIKE / "data" / "reextract" / f"{r['doc_id']}.pdf").exists()
            out.append(rec("spike_recovery", r["url"], "download" if have else "failed", p, doc_id=r["doc_id"],
                           note=r.get("result")))
    for name, col in (("be_recovered_urls.tsv", "source_pdf_url"), ("che_recovered_urls.tsv", "recovered_url")):
        p = SPIKE / name
        if p.exists():
            with open(p, encoding="utf-8") as f:
                out += [rec("spike_recovery", r[col], "download", p, doc_id=r.get("opd_doc_id")) for r in
                        csv.DictReader(f, delimiter="\t") if r.get(col)]
    ad = SPIKE / "data" / "audit_docs"
    files: dict[int, Path] = {}
    if ad.exists():
        for f in sorted(ad.iterdir()):
            if f.stem.isdigit():
                files.setdefault(int(f.stem), f)
    purged = RESULTS / "compliance" / "purged.json"  # copies deleted by gegenprobe.compliance.mirror purge still count
    gone = {}
    if purged.exists():
        for r in json.loads(purged.read_text()).get("deleted", []):
            if any("audit_docs" in f for f in r.get("files", [])):
                gone.update({int(i): r["url"] for i in r.get("doc_ids") or []})
    meta = docs_meta(set(files) | set(gone))
    for i in sorted(set(files) | set(gone)):
        url = gone.get(i) or (meta.get(i) or {}).get("url")
        date = (dt.datetime.fromtimestamp(files[i].stat().st_mtime).date().isoformat() if i in files else "2026-10-08")
        out.append(rec("spike_recovery", url, "download" if url else "unknown_url", ad, doc_id=i, date=date))
    return out


def _git_date(commit: str) -> str | None:
    try:
        return subprocess.run(["git", "show", "-s", "--format=%ad", "--date=short", commit], cwd=ROOT,
                              capture_output=True, text=True, timeout=30).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def ci_make_run() -> list[dict]:
    """Documents `make run` re-fetched in CI (cold cache): eval/rederive.py and eval/replay_all.py walk the held-out set
    sorted by (image_only, doc_id) until their budget ends, P2 likewise; step 4 fetches the 12 converter demo documents
    (data/convert/demo_docs.json). Reconstructed per recorded run."""
    out = []
    p1 = sorted(_jsonl(DATA / "gold" / "heldout_docs.jsonl"), key=lambda d: (d.get("image_only", False), d["doc_id"]))
    p2 = sorted(_jsonl(DATA / "gold2" / "p2_docs.jsonl"), key=lambda d: (d.get("image_only", False), d["doc_id"]))
    for f in sorted((RESULTS / "ci").glob("docker_make_run_*.json")):
        r = json.loads(f.read_text())
        date = _git_date(r.get("commit", "")) or file_date(f)
        rr, ra = r.get("rederive_rules") or {}, r.get("rederive_apertus") or {}
        n1 = max(len(p1) - rr.get("not_reached_budget", len(p1)), len(p1) - (ra.get("P1") or {}).get("over_budget", len(p1))
                 if ra.get("P1") else 0)
        n2 = len(p2) - (ra.get("P2") or {}).get("over_budget", len(p2)) if ra.get("P2") else 0
        demo = json.loads((DATA / "convert" / "demo_docs.json").read_text())["docs"] if r.get("convert", True) else []
        for d in p1[:n1] + p2[:n2] + demo:
            out.append(rec("ci_make_run", d["url"], "download", f, date=date, doc_id=d["doc_id"], sha256=d["sha256"],
                           run=r.get("run_id")))
    return out


def collect() -> list[dict]:
    rows = []
    for fn in (gold_sets, convert_demo, repair, adapters, census_source_formats, endpoints, monitor_nightly,
               spike_recovery, ci_make_run):
        got = fn()
        print(f"[audit] {fn.__name__}: {len(got)} records", file=sys.stderr, flush=True)
        rows += got
    return rows


# ---------------------------------------------------------------- robots.txt
def fetch_robots(base: str) -> tuple[str, str | None]:
    req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": net.UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return f"HTTP {r.status}", r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500 and e.code != 429:
            return f"HTTP {e.code} (no restrictions)", None
        return f"HTTP {e.code} (unreachable)", None
    except Exception as e:
        return f"unreachable ({type(e).__name__})", None


def robots_for(hosts: list[str], offline: bool, refresh: bool = False) -> dict[str, dict]:
    """Each host's robots.txt, read at most once: a host already in data/compliance/robots/_status.json is not re-read
    unless `refresh`; --offline never reads."""
    ROBOTS_DIR.mkdir(parents=True, exist_ok=True)
    sf = ROBOTS_DIR / "_status.json"
    status_all = json.loads(sf.read_text()) if sf.exists() else {}
    # hosts the adapters' audit already read (same User-Agent, 11 Oct 2026): re-use those copies, do not read again
    aa = RESULTS / "repair" / "adapters" / "robots_audit.json"
    if aa.exists() and not refresh:
        prev = json.loads(aa.read_text())
        for h, v in prev["hosts"].items():
            if h in hosts and h not in status_all:
                src = WORK / "adapters" / "robots_audit" / (urllib.parse.urlsplit(h).netloc + ".txt")
                if v["robots"].startswith("HTTP 2") and not src.exists():
                    continue
                if src.exists() and v["robots"].startswith("HTTP 2"):
                    (ROBOTS_DIR / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                status_all[h] = dict(status=v["robots"], read=prev["checked"], via="repair/adapters/robots_audit")
        sf.write_text(json.dumps(status_all, indent=1, sort_keys=True) + "\n")
    out = {}
    for h in hosts:
        f = ROBOTS_DIR / (urllib.parse.urlsplit(h).netloc + ".txt")
        if offline or (h in status_all and not refresh):
            st = status_all.get(h, {}).get("status", "not read")
            text = f.read_text(encoding="utf-8") if f.exists() and st.startswith("HTTP 2") else None
        else:
            st, text = fetch_robots(h)
            if text is not None:
                f.write_text(text, encoding="utf-8")
            elif f.exists():
                f.unlink()
            status_all[h] = dict(status=st, read=dt.date.today().isoformat())
            sf.write_text(json.dumps(status_all, indent=1, sort_keys=True) + "\n")
            print(f"[audit] {h}/robots.txt: {st}", file=sys.stderr, flush=True)
        out[h] = dict(status=st, text=text, read=status_all.get(h, {}).get("read"))
    return out


def judge(url: str, text: str | None, status: str) -> tuple[str, bool | None]:
    """(verdict, first_match_allowed): allowed | disallowed | no_restrictions | host_unreachable."""
    if text is None:
        return ("host_unreachable" if "unreachable" in status or status == "not read" else "no_restrictions"), None
    rules = robots9309.parse(text, net.UA)
    ok = robots9309.decide(rules, robots9309.url_path(url))
    rp = urllib.robotparser.RobotFileParser()
    robots9309._ORIG_PARSE(rp, text.splitlines())
    return ("allowed" if ok else "disallowed"), robots9309._ORIG_CAN_FETCH(rp, net.UA, url)


# ---------------------------------------------------------------- report
RANK = {k: i for i, k in enumerate(("download", "get_discarded", "page_read", "headers_only", "failed", "endpoint",
                                     "refused", "unknown_url"))}


def strongest(kinds) -> str:
    """The request kind that reached furthest (a URL both downloaded and later refused counts as downloaded)."""
    return min(kinds, key=RANK.__getitem__)


def summarize(rows: list[dict], robots: dict[str, dict]) -> dict:
    """Per host and per module: distinct URLs by their strongest request kind, the disallowed ones listed with dates,
    doc ids, sha256 and modules. `records` counts every logged event (a document in a docs file and in its fetch log is
    two records of one request; a CI run that re-downloads a document is one more request)."""
    verdicts: dict[str, tuple] = {}
    for r in rows:
        u = r["url"]
        host = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(u)) if u else "(url not logged)"
        r["host"] = host
        if u and host in robots:
            if u not in verdicts:
                verdicts[u] = judge(u, robots[host]["text"], robots[host]["status"])
            r["verdict"], r["first_match_allowed"] = verdicts[u]
        else:
            r["verdict"], r["first_match_allowed"] = "unknown", None

    def block(rs: list[dict], with_hosts: bool) -> dict:
        per_url: dict[str, dict] = {}
        for r in rs:
            if not r["url"]:
                continue
            x = per_url.setdefault(r["url"], dict(kinds=collections.Counter(), dates=set(), doc_ids=set(), sha256=set(),
                                                  modules=set(), verdict=r["verdict"], fm=r["first_match_allowed"],
                                                  host=r["host"]))
            x["kinds"][r["request"]] += 1
            x["modules"].add(r["module"])
            if r.get("date"):
                x["dates"].add(r["date"])
            if r.get("doc_id") is not None:
                x["doc_ids"].add(str(r["doc_id"]))
            if r.get("sha256"):
                x["sha256"].add(r["sha256"])
        by_kind = collections.Counter(strongest(x["kinds"]) for x in per_url.values())
        dis = {u: x for u, x in per_url.items() if x["verdict"] == "disallowed"}
        dis_kind = collections.Counter(strongest(x["kinds"]) for x in dis.values())
        unre = collections.Counter(strongest(x["kinds"]) for x in per_url.values() if x["verdict"] == "host_unreachable")
        sent = {u: x for u, x in dis.items() if strongest(x["kinds"]) in SENT}
        dates = sorted({d for r in rs for d in ([r["date"]] if r.get("date") else [])})
        out = dict(
            distinct_urls=len(per_url), distinct_urls_by_request=dict(sorted(by_kind.items())),
            records=dict(sorted(collections.Counter(r["request"] for r in rs).items())),
            disallowed_distinct_urls_by_request=dict(sorted(dis_kind.items())),
            disallowed_requests_sent=sum(sum(n for k, n in x["kinds"].items() if k in SENT) for x in sent.values()),
            disallowed_download_records=sum(x["kinds"].get("download", 0) for x in dis.values()),
            disallowed_allowed_by_first_match=sum(1 for x in sent.values() if x["fm"]),
            not_recheckable_distinct_urls_by_request=dict(sorted(unre.items())),
            dates=[dates[0], dates[-1]] if dates else None, sources=sorted({r["source"] for r in rs}),
            disallowed_urls=[dict(url=u, request=strongest(x["kinds"]), records=dict(x["kinds"]), dates=sorted(x["dates"]),
                                  doc_ids=sorted(x["doc_ids"]), sha256=sorted(x["sha256"]), modules=sorted(x["modules"]))
                             for u, x in sorted(sent.items())])
        if with_hosts:
            out["hosts_with_disallowed"] = sorted({x["host"] for x in sent.values()})
        return out

    by_host = collections.defaultdict(list)
    by_mod = collections.defaultdict(list)
    for r in rows:
        by_host[r["host"]].append(r)
        by_mod[r["module"]].append(r)
    hosts = {}
    for h, rs in sorted(by_host.items()):
        rb = robots.get(h, {})
        b = block(rs, False)
        if not b["disallowed_urls"]:
            b.pop("disallowed_urls")
        hosts[h] = dict(robots=rb.get("status"), robots_read=rb.get("read"),
                        robots_sha256=hashlib.sha256(rb["text"].encode()).hexdigest() if rb.get("text") is not None else None,
                        modules=sorted({r["module"] for r in rs}), **b)
    modules = {m: block(rs, True) for m, rs in sorted(by_mod.items())}
    project = block([r for r in rows if r["module"] != "spike_recovery"], True)
    project.pop("disallowed_urls")
    totals = dict(project=project, verdicts=dict(sorted(collections.Counter(
        v[0] for v in verdicts.values()).items())), hosts=len(by_host))
    return dict(totals=totals, hosts=hosts, modules=modules)


def ci_jobs(rows: list[dict]) -> list[dict]:
    """Per invocation of each workflow job that fetches gold documents from their recorded URLs on a GitHub runner (no PDF
    cache between jobs): how many requested URLs robots.txt disallows today. Before commit 099f416 these were fetched;
    since then src/sitecustomize.py makes net refuse them (and, with data/compliance/mirror_urls.json, read OPD's copy)."""
    dis = {r["url"] for r in rows if r.get("verdict") == "disallowed"}
    sets = {"gold_dev": DATA / "gold/dev_docs.jsonl", "gold_heldout": DATA / "gold/heldout_docs.jsonl",
            "gold_p2": DATA / "gold2/p2_docs.jsonl", "p6_test": DATA / "p6/p6_docs.jsonl"}
    n = {k: sum(1 for d in _jsonl(p) if net.quote_url(d["url"]) in dis) for k, p in sets.items()}
    be = RESULTS / "repair" / "repair_BE.tsv"
    if be.exists():
        with open(be, encoding="utf-8") as f:
            n["be_rows"] = sum(1 for r in csv.DictReader(f, delimiter="\t") if r.get("source_url")
                               and net.quote_url(r["source_url"]) in dis)
    jobs = [dict(workflow=w, job=j, parallel_jobs=k, sets=s,
                 disallowed_downloads_per_invocation=k * sum(n.get(x, 0) for x in s)) for w, j, k, s in CI_JOBS]
    mk = collections.Counter(r.get("run") for r in rows if r["module"] == "ci_make_run" and r.get("verdict") == "disallowed")
    try:
        commits = int(subprocess.run(["git", "rev-list", "--count", f"{MAKE_RUN_JOB}..{FIX_COMMIT}^"], cwd=ROOT,
                                     capture_output=True, text=True, timeout=30).stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        commits = None
    jobs.insert(0, dict(workflow="ci.yml", job="make-run (every push and pull request)", parallel_jobs=1,
                        sets=["gold_heldout (within budget)", "gold_p2 (within budget)", "convert demo"],
                        disallowed_downloads_recorded_runs={str(k): v for k, v in sorted(mk.items())},
                        commits_between_job_and_fix=commits,
                        note=f"job added in {MAKE_RUN_JOB}; each push runs it once (a push can carry several commits)"))
    return jobs


def main(argv: list[str]) -> int:
    offline = "--offline" in argv
    last = json.loads(OUT.read_text()) if OUT.exists() else {}
    rows = collect()
    hosts = sorted({"{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(r["url"])) for r in rows if r["url"]})
    robots = robots_for(hosts, offline, refresh="--refresh" in argv)
    s = summarize(rows, robots)
    out = dict(
        checked=max((v["read"] for v in robots.values() if v.get("read")), default=last.get("checked")),
        user_agent=net.UA, matcher="gegenprobe.robots9309 (RFC 9309 2.2.2: longest match, allow wins ties)",
        reference=("each host's robots.txt as read on the 'checked' date (copies: data/compliance/robots/); no archived "
                   "copy from 9-10 Oct 2026 was used except where noted under 'reference_notes'"),
        reference_notes=REFERENCE_NOTES,
        fix=dict(commit=FIX_COMMIT, time=FIX_TIME, what="RFC 9309 matcher for every entry point (src/sitecustomize.py)"),
        request_kinds=dict(
            download="GET, body kept (sha256 recorded)", get_discarded="GET, body read and rejected (not a PDF, sha mismatch)",
            page_read="GET of an HTML page, read and parsed", headers_only="GET opened, headers read, body not read",
            failed="request sent, HTTP or network error", refused="not sent: refused by robots.txt at the time",
            endpoint="one example of an API/index request type", unknown_url="attempt whose URL was not logged"),
        **s, ci_jobs=ci_jobs(rows))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=sorted) + "\n")
    t = out["totals"]["project"]
    print(json.dumps({k: t[k] for k in t if k not in ("sources",)}, indent=1))
    for h, v in out["hosts"].items():
        if v["disallowed_distinct_urls_by_request"]:
            print(h, v["robots"], v["disallowed_distinct_urls_by_request"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
