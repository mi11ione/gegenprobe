"""`make run` inside Docker: replay every headline from committed inputs, run a small live slice, print a scoreboard.

Steps (each returns {"status": PASS|FAIL|SKIP, ...}); the process exits 1 if any step FAILs. SKIP is only allowed for
steps that need the network or a model endpoint and cannot reach them; the replay steps never skip.

  1 model     live backend: LLM_BASE_URL (vLLM-style) or GP_GGUF=1 (pinned GGUF on CPU); otherwise replay only
  2 census    recompute funnel, link status and feasibility matrix from data/census and assert equality with results/
  3 repair    BE canton-uid join on the vendored slice + triple check on a few PDFs fetched by sha256
  4 convert   sample documents through the cascade (metadata -> rules -> Apertus pointer); span / typed-null /
              footer-distractor / self-deletion checks; live scores compared with the committed cache within tolerance
  5 eval      re-score the cached four-arm results on the frozen gold set; print the scoreboard
  5b rederive re-derive the rules arm on the held-out set from the source PDFs (sha256-verified); WARN, never FAIL
  6 claims    every number in README / report recomputed from results files
"""
from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import time
import traceback
from pathlib import Path

OUT = Path(os.environ.get("GP_OUT", "/app/out" if Path("/app/out").exists() else "out"))

STEPS = [
    ("census", "gegenprobe.census.replay"),
    ("repair", "gegenprobe.repair.demo"),
    ("convert", "gegenprobe.convert.demo"),
    ("eval", "eval.replay"),
    ("rederive", "eval.rederive"),  # rules arm re-derived from the source PDFs (non-fatal: PASS / WARN / SKIP)
    ("claims", "gegenprobe.claims_step"),
]


def online(host: str = "files.openparldata.ch", port: int = 443, timeout: float = 5) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def model_step() -> dict:
    from gegenprobe import llm
    if os.environ.get("GP_GGUF") == "1":
        try:
            p = llm.fetch_gguf("apertus-v1.5-8b-text-q4_k_m")
            return dict(status="PASS", backend="gguf", path=str(p))
        except Exception as e:
            return dict(status="SKIP", backend="gguf", reason=f"GGUF unavailable ({type(e).__name__}: {e}); replay only")
    if os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_NAME"):
        return dict(status="PASS", backend="openai", model=os.environ["LLM_NAME"])
    return dict(status="SKIP", backend=None,
                reason="no LLM_BASE_URL/LLM_NAME and GP_GGUF!=1: model outputs replayed from data/model_cache")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report = dict(started=time.strftime("%Y-%m-%dT%H:%M:%S%z"), online=online(), steps={})
    print(f"Gegenprobe make run | network {'up' if report['online'] else 'DOWN (live slices skipped)'}", flush=True)
    r = model_step()
    report["steps"]["model"] = r
    print(f"[model]   {r['status']}  {r.get('backend') or ''} {r.get('reason', '')}", flush=True)
    ctx = dict(online=report["online"], backend=r.get("backend") if r["status"] == "PASS" else None, out=OUT)
    for name, mod in STEPS:
        s = time.time()
        try:
            res = importlib.import_module(mod).main(ctx)
        except Exception as e:
            res = dict(status="FAIL", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
        res["secs"] = round(time.time() - s, 1)
        report["steps"][name] = res
        line = res.get("summary") or res.get("error") or res.get("reason") or ""
        print(f"[{name:<7}] {res['status']}  ({res['secs']} s)  {line}", flush=True)
    # evidence viewer: rendered from the committed site/data.json; never fails the run
    try:
        from .viewer.__main__ import SITE, render
        site = render(json.loads((SITE / "data.json").read_text(encoding="utf-8")), OUT / "site")
        report["site"] = str(site)
    except Exception as e:  # noqa: BLE001 - optional artefact
        report["site"] = f"not rendered ({type(e).__name__}: {e})"
    report["secs"] = round(time.time() - t0, 1)
    fails = [k for k, v in report["steps"].items() if v["status"] == "FAIL"]
    report["result"] = "FAIL" if fails else "PASS"
    (OUT / "run_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    print(f"\nRESULT {report['result']} in {report['secs']} s" + (f"  failing: {', '.join(fails)}" if fails else ""))
    print(f"Full report: {OUT / 'run_report.json'}")
    if str(report.get("site", "")).endswith("index.html"):
        print("Evidence viewer: open out/site/index.html")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
