"""Upper bound on the requests GitHub Actions runs made to disallowed www4.ti.ch paths before the RFC 9309 fix
(docs/incidents.md, 2026-10-09 to 2026-10-11).

Two inputs, both committed:
  data/compliance/ci_runs_before_fix.json   every run of every workflow created before the fix was pushed, with its jobs
                                            and steps (name, conclusion, start, end) as GitHub's API reports them
                                            (`snapshot`, needs the gh CLI; read-only API calls, no document is fetched)
  the documents each fetching step reads    data/gold/{dev,heldout}_docs.jsonl, data/gold2/p2_docs.jsonl,
                                            data/p6/p6_docs.jsonl, data/convert/demo_docs.json, each URL judged under
                                            RFC 9309 against the stored www4.ti.ch robots.txt (data/compliance/robots/)

A step that fetches is recognised by its command (step name); per executed step (any conclusion but `skipped`) it can
have downloaded at most the disallowed www4.ti.ch documents of the sets it reads, each once (one PDF cache per job), and
at most `tries` attempts per document (net.open_url retries on 429/5xx/timeouts: 5 in `make run`'s pdftext.fetch_pdf, 2
in the 8B workflows' fetch steps). Steps that fetch no document (model downloads, scorer self-checks on committed token
ids, the BE-only nightly) count 0. Concurrency: the largest number of fetching steps whose [start, end] intervals overlap;
net.py keeps >= 1.2 s between requests to one host within a process, not across processes.

    python -m gegenprobe.compliance.ci_repeats            recompute results/compliance/ci_repeats.json (offline)
    python -m gegenprobe.compliance.ci_repeats snapshot   refresh the run snapshot from the GitHub API (gh CLI)
"""
from __future__ import annotations

import collections
import json
import subprocess
import sys
from pathlib import Path

from .. import robots9309
from ..paths import DATA, RESULTS

REPO = "mi11ione/gegenprobe"
FIX_COMMIT = "099f416"
FIX_PUSHED = "2026-10-10T22:48:08Z"  # GitHub activity API: push 6a3ba3c..099f416 (commit time 22:48:05Z)
WORKFLOWS = ("ci.yml", "arms-8b.yml", "arms-8b-par.yml", "arms-8b-fill.yml", "arms-8b-p6.yml", "arms-8b-p2.yml",
             "gguf-8b.yml", "nightly-real.yml", "nightly-real-docker.yml")
SNAPSHOT = DATA / "compliance" / "ci_runs_before_fix.json"
OUT = RESULTS / "compliance" / "ci_repeats.json"
ROBOTS = DATA / "compliance" / "robots" / "www4.ti.ch.txt"
UA = "hackapertus-research/0.1"
SETS = {"gold_dev": DATA / "gold" / "dev_docs.jsonl", "gold_heldout": DATA / "gold" / "heldout_docs.jsonl",
        "gold_p2": DATA / "gold2" / "p2_docs.jsonl", "p6_test": DATA / "p6" / "p6_docs.jsonl",
        "convert_demo": DATA / "convert" / "demo_docs.json"}
# (workflow, substring of the step name) -> (fetch kind, sets read, attempts per document)
STEPS = [
    ("ci.yml", "make run", ("make run (re-derivation + converter demo)", ("gold_heldout", "gold_p2", "convert_demo"), 5)),
    ("ci.yml", "Run set -o pipefail", ("make run (re-derivation + converter demo)", ("gold_heldout", "gold_p2",
                                                                                      "convert_demo"), 5)),
    ("*", "eval.run_arms fetch --split dev", ("run_arms fetch dev", ("gold_dev",), 2)),
    ("*", "eval.run_arms fetch --split heldout", ("run_arms fetch heldout", ("gold_heldout",), 2)),
    ("*", "eval.p6.run_8b fetch", ("p6 fetch (dev + P6)", ("gold_dev", "p6_test"), 2)),
    ("*", "eval.run_arms_p2 fetch", ("p2 fetch", ("gold_p2",), 2)),
    ("gguf-8b.yml", "arms", ("gguf arms (run_arms, fetches held-out)", ("gold_heldout",), 2)),
]
NO_FETCH = {
    "gguf-8b.yml": "steps selfcheck / diag / impl score committed token-id fixtures (tests/fixtures/gguf_*.json) and fetch "
                   "only the model file and llama.cpp sources; the `arms` step, the only one that reads documents, was "
                   "skipped in all runs before the fix",
    "arms-8b-p2.yml": "its 6 shard jobs fetch the 62 P2 documents, none of which is on www4.ti.ch",
    "nightly-real.yml": "one network night: OPD exports, Bern's OGD tables and BE documents; no www4.ti.ch URL",
    "nightly-real-docker.yml": "no run before the fix",
}


def _gh(path: str) -> dict | list:
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True, timeout=120).stdout
    return json.loads(out)


def snapshot(jobs_dir: Path | None = None) -> dict:
    """Runs created before FIX_PUSHED, with jobs and steps (jobs_dir: previously saved <run_id>.json job listings)."""
    runs = []
    for w in WORKFLOWS:
        page = 1
        while True:
            d = _gh(f"repos/{REPO}/actions/workflows/{w}/runs?per_page=100&page={page}")
            rs = d.get("workflow_runs", [])
            for r in rs:
                if r["created_at"] < FIX_PUSHED:
                    runs.append(dict(workflow=w, id=r["id"], created_at=r["created_at"], head_sha=r["head_sha"],
                                     conclusion=r["conclusion"]))
            if len(rs) < 100:
                break
            page += 1
    for r in runs:
        f = jobs_dir / f"{r['id']}.json" if jobs_dir else None
        api = f"repos/{REPO}/actions/runs/{r['id']}/jobs?per_page=100&filter=all"
        jl = json.loads(f.read_text()) if f and f.exists() else _gh(api)
        r["jobs"] = [dict(name=j["name"], conclusion=j["conclusion"], started_at=j.get("started_at"),
                          completed_at=j.get("completed_at"),
                          steps=[dict(name=s["name"][:160], conclusion=s["conclusion"], started_at=s.get("started_at"),
                                      completed_at=s.get("completed_at")) for s in j.get("steps", [])])
                     for j in jl["jobs"] if r["workflow"] != "ci.yml" or j["name"] == "make-run"]
    runs.sort(key=lambda r: (r["workflow"], r["created_at"]))
    return dict(repo=REPO, fix_commit=FIX_COMMIT, fix_pushed=FIX_PUSHED,
                note="GitHub Actions runs created before the RFC 9309 fix was pushed (ci.yml: the make-run job only, the "
                     "one that fetches documents); read-only API data (`gh api .../actions/runs/<id>/jobs`)",
                runs=runs)


def set_counts() -> dict[str, int]:
    """Distinct www4.ti.ch URLs on paths the stored robots.txt disallows (RFC 9309), per document set."""
    text = ROBOTS.read_text(encoding="utf-8")
    out = {}
    for k, p in SETS.items():
        if p.suffix == ".json":
            docs = json.loads(p.read_text())["docs"]
        else:
            docs = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        urls = {d["url"] for d in docs if "://www4.ti.ch/" in (d.get("url") or "")}
        out[k] = sum(1 for u in urls if not robots9309.allowed_by(text, UA, u))
    return out


def _classify(workflow: str, step: str):
    for w, pat, spec in STEPS:
        if (w == "*" or w == workflow) and (pat in step if pat != "arms" else step == "arms"):
            return spec
    return None


def compute(snap: dict | None = None) -> dict:
    snap = snap or json.loads(SNAPSHOT.read_text())
    n = set_counts()
    wf = collections.OrderedDict((w, dict(runs_before_fix=0, executed_fetch_steps={}, skipped_fetch_steps=0,
                                          downloads_max=0, requests_max_with_retries=0)) for w in WORKFLOWS)
    intervals = []
    for r in snap["runs"]:
        w = wf[r["workflow"]]
        w["runs_before_fix"] += 1
        for j in r["jobs"]:
            for s in j["steps"]:
                spec = _classify(r["workflow"], s["name"])
                if spec is None:
                    continue
                kind, sets, tries = spec
                if s["conclusion"] in ("skipped", None) or not s.get("started_at"):
                    w["skipped_fetch_steps"] += 1
                    continue
                k = sum(n[x] for x in sets)
                w["executed_fetch_steps"][kind] = w["executed_fetch_steps"].get(kind, 0) + 1
                w["downloads_max"] += k
                w["requests_max_with_retries"] += k * tries
                if k:
                    intervals.append((s["started_at"], s["completed_at"] or s["started_at"], r["workflow"], r["id"],
                                      j["name"]))
    ev = sorted([(a, 1, x) for a, b, *x in intervals] + [(b, -1, x) for a, b, *x in intervals],
                key=lambda e: (e[0], e[1]))
    cur, peak, at, active = 0, 0, None, []
    for t, d, x in ev:
        if d == 1:
            active.append(x)
        else:
            active.remove(x)
        cur += d
        if cur > peak:
            peak, at = cur, dict(time=t, steps=[dict(workflow=a, run=b, job=c) for a, b, c in active])
    for w, v in wf.items():
        if v["runs_before_fix"] and v["downloads_max"] == 0 and w in NO_FETCH:
            v["why_zero"] = NO_FETCH[w]
        elif not v["runs_before_fix"]:
            v["why_zero"] = NO_FETCH.get(w, "no run before the fix")
    coarse = dict(ci=96 * 43, arms_8b=6 * 261, arms_8b_par=2 * 387, arms_8b_fill=40, arms_8b_p6=147)
    return dict(
        note=("Upper bound on requests to disallowed www4.ti.ch paths made by GitHub Actions runs before the RFC 9309 fix "
              f"(commit {FIX_COMMIT}, pushed {FIX_PUSHED}), from the committed run snapshot "
              f"({SNAPSHOT.relative_to(DATA.parent)}) and the documents each executed fetching step reads "
              "(python -m gegenprobe.compliance.ci_repeats)."),
        fix_commit=FIX_COMMIT, fix_pushed=FIX_PUSHED,
        disallowed_ti_urls_per_set=n,
        workflows=wf,
        upper_bound_downloads=sum(v["downloads_max"] for v in wf.values()),
        upper_bound_requests_with_retries=sum(v["requests_max_with_retries"] for v in wf.values()),
        upper_bound_total=sum(coarse.values()),
        upper_bound_total_note=("the earlier bound: every run of a workflow counted at the full per-invocation fetch of "
                                "its definition (ci 96 x 43, arms-8b 6 x 261, arms-8b-par 2 x 387, fill 40, p6 147). It "
                                "left out arms-8b-p2 and gguf-8b; both made no request to www4.ti.ch (workflows.*.why_zero), "
                                "so it is an upper bound on downloads too, looser than upper_bound_downloads"),
        max_concurrent_fetching_steps=peak, max_concurrency_at=at,
        pacing=("net.py waits >= 1.2 s between two requests to the same host within one process (all threads); separate "
                "processes on separate runners do not coordinate, so at the peak above at most "
                f"{peak} requests could reach www4.ti.ch within any 1.2 s"),
        not_in_bound="robots.txt reads (an allowed path) and requests made outside GitHub Actions "
                     "(results/compliance/robots_audit_all.json, totals.project)",
    )


def main(argv: list[str]) -> int:
    if argv[:1] == ["snapshot"]:
        jd = Path(argv[argv.index("--jobs-dir") + 1]) if "--jobs-dir" in argv else None
        snap = snapshot(jd)
        SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{SNAPSHOT}: {len(snap['runs'])} runs")
        return 0
    res = compute()
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("upper_bound_downloads", "upper_bound_requests_with_retries",
                                          "upper_bound_total", "max_concurrent_fetching_steps")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
