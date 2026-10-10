"""Real Apertus v1.5 8B (GGUF Q4_K_M, llama.cpp on CPU) on the P1 held-out documents, against the 70B weights.

Exploratory arms pre-registered in eval/prereg/DEVIATIONS.md (D2, D3 and addenda). Reads the frozen per-document rows
(results/eval/heldout__<build>.json), the 8B θ file, the fit log and the CI timings; no model calls, no new scoring rule:
correctness is eval/score.py's `outcome`, the registered hypotheses are eval/hypotheses.py run unchanged on the 8B rows.

    python -m eval.gguf_8b_analysis fetch-ci   # network (gh): per-job /usr/bin/time blocks of the 8B CI runs
                                               #   -> results/eval/gguf_ci_times.json
    python -m eval.gguf_8b_analysis            # offline -> results/eval/gguf_8b_analysis.json
                                               #            results/eval/hypotheses__gguf_apertus-v1.5-8b-text-q4_k_m.json
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from eval import hypotheses
from eval.hypotheses import correct, mcnemar_exact
from eval.score import outcome, summarise
from gegenprobe.paths import DATA, RESULTS
from gegenprobe.stats import auroc, wilson

B8 = "gguf_apertus-v1.5-8b-text-q4_k_m"
B70 = "publicai_swiss-ai_apertus-v1.5-8b"  # the 70B weights, served by Public AI under the -8b name (report §3)
ARMS = ("rules", "pointer", "cascade")
REPO = "mi11ione/gegenprobe"
RUN_ARMS = 38032826730  # fit + 6 held-out shards
RUN_FILL = 38057496203  # fill-in of the 5 documents the shard bug skipped
RUN_PARALLEL = 38048369442  # independent parallel run (warm-up over 6 runners, then its own fit)
TIMES = RESULTS / "eval" / "gguf_ci_times.json"
TIME_KEYS = {
    "Command being timed": "command",
    "User time (seconds)": "user_s",
    "System time (seconds)": "system_s",
    "Percent of CPU this job got": "cpu_pct",
    "Elapsed (wall clock) time (h:mm:ss or m:ss)": "wall",
    "Maximum resident set size (kbytes)": "max_rss_kb",
}


def _hms(s: str) -> float:
    parts = [float(x) for x in s.split(":")]
    return sum(v * 60**i for i, v in enumerate(reversed(parts)))


def parse_time(log: str) -> dict:
    """The GNU /usr/bin/time -v block of one job log."""
    out = {}
    for line in log.splitlines():
        line = re.sub(r"^\S+Z\s", "", line).strip()  # strip the Actions timestamp
        k, _, v = line.partition(": ")
        if k in TIME_KEYS:
            out[TIME_KEYS[k]] = v.strip().strip('"')
    if "wall" in out:
        out["wall_s"] = _hms(out["wall"])
        out["user_s"], out["system_s"] = float(out["user_s"]), float(out["system_s"])
        out["max_rss_kb"] = int(out["max_rss_kb"])
    return out


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def fetch_ci() -> dict:
    jobs = []
    for run in (RUN_ARMS, RUN_FILL):
        for j in json.loads(_gh("api", f"repos/{REPO}/actions/runs/{run}/jobs", "--paginate"))["jobs"]:
            t = parse_time(_gh("api", f"repos/{REPO}/actions/jobs/{j['id']}/logs"))
            jobs.append(dict(run=run, job_id=j["id"], name=j["name"], runner=(j.get("labels") or [""])[0],
                             conclusion=j["conclusion"], **t))
    with tempfile.TemporaryDirectory() as tmp:  # the parallel run's fit artifact: θ only
        _gh("run", "download", str(RUN_PARALLEL), "-R", REPO, "-n", "fit", "-D", tmp)
        par = json.loads((Path(tmp) / "data" / "convert" / "theta" / f"{B8}.json").read_text())["answer_date"]
    out = dict(source=f"GitHub Actions job logs (GNU time -v) of runs {RUN_ARMS}, {RUN_FILL}; fit artifact of {RUN_PARALLEL}",
               runner_vcpus=4, runner_ram_gb=16, runner_note="ubuntu-24.04 public-repository runner (DEVIATIONS.md D3 addendum)",
               jobs=jobs, parallel_fit=dict(run=RUN_PARALLEL, theta=par["theta"], auroc=par["auroc"]))
    TIMES.write_text(json.dumps(out, indent=1))
    return out


def _rows(build: str) -> list[dict]:
    return json.loads((RESULTS / "eval" / f"heldout__{build}.json").read_text())["per_doc"]


def _arm_rows(rows: list[dict], arm: str) -> list[dict]:
    return [dict(cell=r["cell"], gold=r["gold"], lenient=r.get("lenient") or [], doc_dates=r["doc_dates"],
                 pred=r[arm].get("value"), route=r[arm].get("route")) for r in rows]


def _ci(k: int, n: int) -> list[float]:
    return [round(100 * x, 1) for x in wilson(k, n)]


def p_str(p: float) -> str:
    """As the documents print p: two significant digits, scientific below 0.001 (e.g. 3.6 × 10⁻⁵)."""
    if p >= 0.001:
        return f"{p:.2g}"
    m, e = f"{p:.1e}".split("e")
    return f"{m} × 10" + str(int(e)).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))


def _mcnemar(a: list[dict], b: list[dict], arm_a: str, arm_b: str) -> dict:
    bb = {r["doc_id"]: r for r in b}
    pairs = [(correct(r, arm_a), correct(bb[r["doc_id"]], arm_b)) for r in a]
    only_a, only_b = sum(x and not y for x, y in pairs), sum(y and not x for x, y in pairs)
    return dict(n=len(pairs), a_correct=sum(x for x, _ in pairs), b_correct=sum(y for _, y in pairs),
                a_only=only_a, b_only=only_b, p=mcnemar_exact(only_a, only_b), p_str=p_str(mcnemar_exact(only_a, only_b)))


def registered_hypotheses() -> dict:
    """eval/hypotheses.py, unchanged, on the 8B rows. The naive arms were not run on the 8B (D3), and H1's naive
    comparison line reads them, so each row gets an empty naive_plain placeholder in a temporary copy and the line is
    reported as not run."""
    rows = _rows(B8)
    res = json.loads((RESULTS / "eval" / f"heldout__{B8}.json").read_text())
    for r in rows:
        r.setdefault("naive_plain", {"date": None})
    res["per_doc"] = rows
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "eval").mkdir()
        (Path(tmp) / "eval" / f"heldout__{B8}.json").write_text(json.dumps(res))
        orig, hypotheses.RESULTS = hypotheses.RESULTS, Path(tmp)
        try:
            out = hypotheses.main(B8)
        finally:
            hypotheses.RESULTS = orig
    out["H1"]["naive_plain_values_on_null"] = "not run on the 8B (DEVIATIONS.md D3)"
    out["note"] = "eval/hypotheses.py unchanged; naive arm not run on the 8B (D3)"
    (RESULTS / "eval" / f"hypotheses__{B8}.json").write_text(json.dumps(out, indent=1))
    return out


def cost() -> dict:
    t = json.loads(TIMES.read_text())
    fit = next(j for j in t["jobs"] if j["name"] == "fit")
    held = [j for j in t["jobs"] if j["name"].startswith("shard") or j["name"] == "fill"]
    shards = sorted((RESULTS / "eval" / "shards").glob("heldout__gguf__*.json"))
    scored = [r for p in shards for r in json.loads(p.read_text())["per_doc"]]
    dev_n = len(json.loads((DATA / "convert" / "theta" / f"{B8}.json").read_text())["answer_date"]["fitted_on"])
    wall, user = sum(j["wall_s"] for j in held), sum(j["user_s"] + j["system_s"] for j in held)
    rows = _rows(B8)
    return dict(
        note="GNU time of the python step only (PDF fetch + text extraction + model load + rules + pointer on every "
             "document; the cascade reuses the pointer's scores). One document at a time per runner, llama.cpp using "
             "the runner's 4 vCPUs. No vCPU-hour price source exists in report/cost.py, so cost is given in CPU-seconds.",
        runner_vcpus=t["runner_vcpus"],
        heldout_jobs=len(held),
        heldout_doc_runs=len(scored),
        heldout_docs_unique=len({r["doc_id"] for r in scored}),
        heldout_wall_s_total=wall,
        heldout_cpu_s_total=user,
        heldout_wall_s_per_doc=wall / len(scored),
        heldout_cpu_s_per_doc=user / len(scored),
        heldout_docs_with_candidates=sum(bool(r["pointer"].get("n_cands")) for r in rows),
        fit_dev_docs=dev_n,
        fit_wall_s=fit["wall_s"],
        fit_wall_h=fit["wall_s"] / 3600,
        fit_cpu_s=fit["user_s"] + fit["system_s"],
        fit_wall_s_per_doc=fit["wall_s"] / dev_n,
        fit_cpu_s_per_doc=(fit["user_s"] + fit["system_s"]) / dev_n,
        max_rss_gb=max(j["max_rss_kb"] for j in [fit, *held]) / 1e6,
        cpu_pct_fit=fit["cpu_pct"],
    )


def main() -> dict:
    r8, r70 = _rows(B8), _rows(B70)
    th = json.loads((DATA / "convert" / "theta" / f"{B8}.json").read_text())["answer_date"]
    out: dict = dict(
        build=B8,
        model_file="Colby/apertus-v1.5-8b-text-Q4_K_M-GGUF (sha256 in results/eval/gguf_impl60.json)",
        compare_build=B70,
        n=len(r8),
        theta=th["theta"],
        theta_dev_auroc=th["auroc"],
        theta_dev_n=th["n_pos"] + th["n_neg"],
        theta_70b=json.loads((RESULTS / "eval" / f"heldout__{B70}.json").read_text())["theta"],
    )
    if TIMES.exists():
        t = json.loads(TIMES.read_text())
        out["theta_parallel_run"] = dict(run=t["parallel_fit"]["run"], theta=t["parallel_fit"]["theta"],
                                         identical=t["parallel_fit"]["theta"] == th["theta"])
    # determinism: documents scored twice (shard bug, then fill-in) must carry identical decisions and margins
    seen: dict = {}
    dup = []
    for p in sorted((RESULTS / "eval" / "shards").glob("heldout__gguf__*.json")):
        for r in json.loads(p.read_text())["per_doc"]:
            key = json.dumps({a: r[a] for a in ARMS}, sort_keys=True)
            if r["doc_id"] in seen:
                dup.append(dict(doc_id=r["doc_id"], identical=seen[r["doc_id"]] == key))
            seen[r["doc_id"]] = key
    out["scored_twice"] = dict(n=len(dup), identical=sum(d["identical"] for d in dup), doc_ids=[d["doc_id"] for d in dup])

    arms: dict = {}
    for arm in ARMS:
        rows = _arm_rows(r8, arm)
        s, le = summarise(rows, True), summarise(rows, False)
        vals = [r for r in r8 if r[arm].get("value")]
        printed = sum(r[arm]["value"] in r["doc_dates"] for r in vals)
        nulls = [r for r in r8 if r["gold"] is None]
        on_null = sum(r[arm].get("value") is not None for r in nulls)
        arms[arm] = dict(
            strict={c: dict(exact=v["exact"], n=v["n"], ci_pct=_ci(v["exact"], v["n"]), **{k: v[k] for k in
                    ("correct", "correct_null", "false_null", "misattributed", "fabricated")}) for c, v in s.items()},
            lenient={c: dict(exact=v["exact"], n=v["n"], ci_pct=_ci(v["exact"], v["n"])) for c, v in le.items()},
            values_returned=len(vals),
            values_printed_in_document=printed,
            fabricated=len(vals) - printed,
            dates_on_answerless=on_null,
            n_answerless=len(nulls),
            dates_on_answerless_ci_pct=_ci(on_null, len(nulls)),
            model_decided=sum(r[arm].get("route") == "apertus" for r in r8),
        )
        # the 70B, same rows, for the side-by-side
        s70 = summarise(_arm_rows(r70, arm), True)["ALL"]
        arms[arm]["exact_70b"] = [s70["exact"], s70["n"]]
        arms[arm]["exact_70b_ci_pct"] = _ci(s70["exact"], s70["n"])
        arms[arm]["dates_on_answerless_70b"] = sum(r[arm].get("value") is not None for r in r70 if r["gold"] is None)
    out["arms"] = arms
    by70 = {r["doc_id"]: r for r in r70}
    out["rules_identical_to_70b_run"] = [sum(r["rules"].get("value") == by70[r["doc_id"]]["rules"].get("value")
                                             for r in r8), len(r8)]
    # every value the 8B pointer/cascade returned, with outcome, for audit
    out["outcome_check"] = {arm: sum(outcome(r[arm].get("value"), r["gold"], set(r["doc_dates"]), r.get("lenient"), True)
                                     == "fabricated" for r in r8) for arm in ARMS}

    pos = [r["pointer"]["margin"] for r in r8 if r["gold"] is None and r["pointer"].get("n_cands")]
    neg = [r["pointer"]["margin"] for r in r8 if r["gold"] is not None and r["pointer"].get("n_cands")]
    pos70 = [r["pointer"]["margin"] for r in r70 if r["gold"] is None and r["pointer"].get("n_cands")]
    neg70 = [r["pointer"]["margin"] for r in r70 if r["gold"] is not None and r["pointer"].get("n_cands")]
    out["abstention_auroc"] = dict(auroc=auroc(pos, neg), n_null=len(pos), n_value=len(neg), auroc_70b=auroc(pos70, neg70))

    out["mcnemar"] = dict(
        pointer_8b_vs_70b=_mcnemar(r8, r70, "pointer", "pointer"),
        cascade_8b_vs_70b=_mcnemar(r8, r70, "cascade", "cascade"),
        cascade_8b_vs_rules=_mcnemar(r8, r8, "cascade", "rules"),
        pointer_8b_vs_rules=_mcnemar(r8, r8, "pointer", "rules"),
    )
    # recall on the 64 answered documents (dates found), per build
    out["dates_found"] = {arm: dict(b8=arms[arm]["strict"]["ALL"]["correct"],
                                    b70=summarise(_arm_rows(r70, arm), True)["ALL"]["correct"],
                                    n_gold_value=sum(r["gold"] is not None for r in r8)) for arm in ARMS}
    out["hypotheses_registered"] = h = registered_hypotheses()
    out["display"] = dict(  # strings as the documents print them
        h2_primary_p=p_str(h["H2"]["primary_fr_it_ocr"]["p"]),
        auroc=f"{out['abstention_auroc']['auroc']:.3f}",
        auroc_70b=f"{out['abstention_auroc']['auroc_70b']:.3f}",
        h4=f"{h['H4']['wrong']} of {h['H4']['apertus_decided_fr_it_values']}",
    )
    if TIMES.exists():
        out["cost"] = cost()
    p = RESULTS / "eval" / "gguf_8b_analysis.json"
    p.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(fetch_ci() if sys.argv[1:] == ["fetch-ci"] else main(), indent=1)[:6000])
