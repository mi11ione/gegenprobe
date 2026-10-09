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
  7. alerts.json: a body whose linking rate drops by more than DROP_PP percentage points night over night (bodies with at
     least MIN_AFFAIRS written-answer affairs), a body whose document count falls by more than DOC_DROP, a new body.
Outputs: results/monitor/{rates.json, alerts.json, run.json}; repair rows in results/monitor/repair_BE_new.tsv.

Linking rate (per body) = affairs with a written-answer event whose answer text is reachable in OPD (attached document,
`texts` row, or agenda item) / affairs with a written-answer event. Same definitions as the census.

usage:
  python -m gegenprobe.monitor.nightly run        full night (network)
  python -m gegenprobe.monitor.nightly offline    steps 5-7 on the current caches (no network); measures compute time
  python -m gegenprobe.monitor.nightly index      step 1 only: what changed since the cached snapshot (one request)
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .. import net
from ..paths import DOCS_META, OPD_RAW, RESULTS, ROOT, WORK

INDEX = "https://files.openparldata.ch/exports/index.json"
NIGHT = WORK / "nightly"
STATE = NIGHT / "state.json"
OUT = RESULTS / "monitor"
SINGLE = ("affairs", "events", "agendas", "bodies")
DROP_PP = 2.0  # alert threshold: linking-rate drop in percentage points, night over night
MIN_AFFAIRS = 50  # only bodies with at least this many written-answer affairs are rated
DOC_DROP = 0.10  # alert when a body's OPD document count falls by more than 10 % (a scraper losing documents)


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


def alerts(prev: dict, cur: dict) -> list[dict]:
    out = []
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
    return out


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
    opd, meta = (OPD_RAW, DOCS_META) if offline else (NIGHT / "opd", NIGHT / "docs_meta")
    transfer = 0
    if not offline:
        opd.mkdir(parents=True, exist_ok=True)
        meta.mkdir(parents=True, exist_ok=True)
        idx = json.loads(net.get(INDEX))
        prev_idx = state.get("index")
        diff = index_diff(prev_idx, idx) if prev_idx else None
        for e in idx["files"]:
            if e["entity"] in SINGLE and (not prev_idx or e["entity"] in diff["changed"] or not (opd / e["filename"]).exists()):
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
    prev_keys = set(state.get("be_repair_keys", []))
    keys = [f"{r['affair_id']}:{r['action']}:{r['source_doc_uid']}" for r in rep]
    new = [r for r, k in zip(rep, keys) if k not in prev_keys]
    state["be_repair_keys"] = keys
    prev_rates = state.get("rates", {})
    al = alerts(prev_rates, rates) if prev_rates else []
    state["rates"] = rates
    STATE.write_text(json.dumps(state))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rates.json").write_text(json.dumps(rates, indent=1, sort_keys=True))
    (OUT / "alerts.json").write_text(
        json.dumps(dict(threshold_pp=DROP_PP, min_affairs=MIN_AFFAIRS, doc_drop=DOC_DROP, alerts=al), indent=1)
    )
    t["total_s"] = round(time.time() - t0, 1)
    from ..repair.common import write_rows

    write_rows("BE_new", new, out=OUT)
    run = dict(
        mode="offline" if offline else "network",
        transfer_bytes=transfer,
        timings=t,
        bodies_rated=sum(1 for b in rates if not b.startswith("_")),
        alerts=len(al),
        be_repair=rep_counts,
        be_repair_new_since_last_night=len(new),
        ts=round(time.time()),
    )
    (OUT / "run.json").write_text(json.dumps(run, indent=1))
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
        print(night(offline=cmd == "offline"))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
