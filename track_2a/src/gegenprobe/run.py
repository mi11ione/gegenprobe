"""`make run` inside Docker: replay every headline from committed inputs, run a small live slice, print a scoreboard.

Steps (each returns {"status": PASS|FAIL|SKIP, ...}); the process exits 1 if any step FAILs. SKIP is only allowed for
steps that need the network or a model endpoint and cannot reach them; the replay steps never skip.

  1 model     live backend: LLM_BASE_URL (vLLM-style) or GP_GGUF=1 (pinned GGUF on CPU); otherwise replay only
  2 census    recompute funnel, link status and feasibility matrix from data/census and assert equality with results/
  3 repair    BE canton-uid join on the vendored slice + triple check on a few PDFs fetched by sha256
  4 convert   sample documents through the cascade (metadata -> rules -> Apertus pointer); span / typed-null /
              footer-distractor / self-deletion checks; live scores compared with the committed cache within tolerance
  5 eval      re-score the cached P1 arm results on the frozen gold set; print the scoreboard
  6 replay    all nine pre-registered tests from committed files (P1-P8, P3b): P1-P4 and P3b re-scored from the
              committed label files, the nine hypotheses scripts re-run and compared with their committed outputs (P5-P8
              byte-identical), the P7 dev table, the P8 tables, the P7 post-hoc files (eval/p7/offline.py) and the 8B
              analysis re-run offline and compared, the nine LOCK files verified (FAIL on any difference)
  6b schema_v02  schema v0.2 re-derived from committed files and compared with results/schema/v0_2/ (FAIL on any
              difference or invalid record): the converter's own P3, P3b and P5 records carried to v0.2 (105 affairs) with
              v0.2's roles from the committed role-rule readings (re-extracted from the texts and compared when they are
              cached), the P8 gold (66 affairs) and the v0.1 samples upgraded losslessly
  7 rederive  the P1 rules arm re-derived from the source PDFs (sha256-verified); WARN, never FAIL
  8 rederive_apertus  P1 + P2 pointer and cascade decisions recomputed from the committed model cache, cache-only
              (no request leaves the machine); FAIL only if a cache hit gives a different decision
  9 claims    every claimed number recomputed from its results file and found where it is printed (token-bounded; short
              values need context); every anchor found at its position (claims_anchor.json); in the strict zones
              (README, technical report, form notes, each end to end; claims_strict.json) every number token must
              be bound to its claim by an anchor or be a listed non-claim
The last lines: the P1 (and P2) Apertus replay coverage, e.g. "Apertus replay: P1 132/154 decisions re-derived from the
model cache, 132 match (22 cache misses)", then "RESULT PASS in 537 s"; when a step skipped, the RESULT line names it:
"RESULT PASS (offline: 3 steps skipped: convert, rederive, rederive_apertus) in 868 s".
Re-derivation budgets (seconds): GP_REDERIVE_BUDGET (rules, default 240) + GP_REDERIVE_APERTUS_BUDGET (default 180, per set:
P1 and P2 each get it, so P2 is always attempted; worst case 240 + 2 x 180 s).
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
    ("census", "gegenprobe.census.replay", "main"),
    ("repair", "gegenprobe.repair.demo", "main"),
    ("convert", "gegenprobe.convert.demo", "main"),
    ("eval", "eval.replay", "main"),
    ("replay", "eval.replay_all", "main"),  # P1-P8, 8B analysis + hypotheses + nine locks, committed files (FAIL on any diff)
    ("schema_v02", "gegenprobe.schema.v0_2_all", "step"),  # v0.2: 105 converter records + 66 P8 gold affairs (FAIL on a diff)
    ("rederive", "eval.rederive", "main"),  # rules arm re-derived from the source PDFs (non-fatal: PASS / WARN / SKIP)
    ("rederive_apertus", "eval.replay_all", "main_rederive"),  # pointer/cascade from the model cache (cache-only)
    ("claims", "gegenprobe.claims_step", "main"),
]
P1_DOCS = 154  # P1 held-out documents (data/gold/heldout_docs.jsonl)
os.environ.setdefault("GP_REDERIVE_BUDGET", "240")
os.environ.setdefault("GP_REDERIVE_APERTUS_BUDGET", "180")  # per set (P1, P2)


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


def skipped_steps(report: dict) -> list[str]:
    """Steps of STEPS that reported SKIP (the model step is not one of them: replaying the model cache is the default)."""
    return [k for k, _, _ in STEPS if (report["steps"].get(k) or {}).get("status") == "SKIP"]


def replay_coverage(report: dict) -> dict:
    """P1 / P2 Apertus decisions re-derived from the committed model cache (step rederive_apertus), per set."""
    st = report["steps"].get("rederive_apertus") or {}
    return dict(status=st.get("status"), sets=st.get("coverage") or {})


def coverage_line(report: dict) -> str:
    """One line: how many P1 Apertus decisions this run re-derived from the model cache, and why the rest were not."""
    cov = replay_coverage(report)
    p1 = next((v for k, v in cov["sets"].items() if k.startswith("P1")), None)
    if p1 is None:
        why = "offline" if report.get("online") is False else f"step rederive_apertus {cov['status'] or 'not run'}"
        return (f"Apertus replay: P1 0/{P1_DOCS} decisions re-derived from the model cache ({why}); the stored decisions "
                "were re-scored by step eval")
    rest = [f"{p1.get(k, 0)} {lab}" for k, lab in (("cache_miss", "cache misses"), ("unreachable", "unreachable"),
                                                    ("not_reached_budget", "over budget")) if p1.get(k)]
    line = (f"Apertus replay: P1 {p1.get('rederived', 0)}/{p1['n']} decisions re-derived from the model cache, "
            f"{p1.get('match', 0)} match" + (f" ({', '.join(rest)})" if rest else ""))
    p2 = next((v for k, v in cov["sets"].items() if k.startswith("P2")), None)
    if p2 is not None:
        line += f"; P2 {p2.get('rederived', 0)}/{p2['n']}, {p2.get('match', 0)} match"
    return line


def result_line(report: dict) -> str:
    """`RESULT PASS in 537 s`, or with skipped steps `RESULT PASS (offline: 3 steps skipped: convert, rederive,
    rederive_apertus) in 868 s`: a PASS never hides that a live check did not run."""
    fails = [k for k, v in report["steps"].items() if v["status"] == "FAIL"]
    skipped = skipped_steps(report)
    note = ""
    if skipped:
        n = len(skipped)
        note = (f" ({'offline: ' if report.get('online') is False else ''}{n} step{'s' if n != 1 else ''} skipped: "
                f"{', '.join(skipped)})")
    return (f"RESULT {'FAIL' if fails else 'PASS'}{note} in {report['secs']} s"
            + (f"  failing: {', '.join(fails)}" if fails else ""))


def main() -> int:
    from gegenprobe import ocrguard
    ocrguard.ensure()  # OCR fails loudly: a scan without OCR is a typed ocr_failed, never a cached page of empty text
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    report = dict(started=time.strftime("%Y-%m-%dT%H:%M:%S%z"), online=online(), steps={})
    print(f"Gegenprobe make run | network {'up' if report['online'] else 'DOWN (live slices skipped)'}", flush=True)
    r = model_step()
    report["steps"]["model"] = r
    print(f"[model]   {r['status']}  {r.get('backend') or ''} {r.get('reason', '')}", flush=True)
    ctx = dict(online=report["online"], backend=r.get("backend") if r["status"] == "PASS" else None, out=OUT)
    for name, mod, fn in STEPS:
        s = time.time()
        try:
            res = getattr(importlib.import_module(mod), fn)(ctx)
        except Exception as e:
            res = dict(status="FAIL", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
        res["secs"] = round(time.time() - s, 1)
        report["steps"][name] = res
        line = res.get("summary") or res.get("error") or res.get("reason") or ""
        print(f"[{name:<8}] {res['status']}  ({res['secs']} s)  {line}", flush=True)
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
    report["skipped"] = skipped_steps(report)
    report["apertus_replay"] = replay_coverage(report)
    (OUT / "run_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    print("\n" + coverage_line(report))
    print(result_line(report))
    print(f"Full report: {OUT / 'run_report.json'}")
    if str(report.get("site", "")).endswith("index.html"):
        print("Evidence viewer: open out/site/index.html")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
