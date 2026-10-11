"""EXPLORATORY 8B arm on P7 (eval/p7/run_8b.py), offline: no model, no network.

  * the committed recipe covers the 80 dev and 478 test-frame rows, carries no document text, and every recipe reproduced
    the committed text sha256 when it was written
  * fed the registered 70B decisions in place of the 8B's, the analysis reproduces results/p7/p7_hypotheses.json exactly
  * the whole CI path (fetch -> features -> fit -> merge -> hypotheses) runs with a fake backend; with the real WORK
    present, the fetch step rebuilds every text from the local caches byte-identically (network refused)
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from eval.p7 import run_8b as R

ROOT = Path(__file__).resolve().parents[1]
REAL_WORK = Path(os.environ.get("GP_WORK", ROOT / ".work"))


def test_committed_recipe_covers_p7_and_carries_no_text():
    rows = R.load_rows()
    assert len(rows) == 558 and sum(r["split"] == "dev" for r in rows) == 80
    assert all(r["recipe_verified_local"] for r in rows)
    dev = {(k["body"], k["affair_id"]) for k in R._jsonl(R.P7 / "dev_key.jsonl")}
    frame = {(d["body"], d["affair_id"]) for d in R._jsonl(R.P7 / "test_decisions.jsonl")}
    assert {(r["body"], r["affair_id"]) for r in rows if r["split"] == "dev"} == dev
    assert {(r["body"], r["affair_id"]) for r in rows if r["split"] == "test"} == frame
    for r in rows:
        assert "text" not in r and set(r["target"]) == set(R.TARGET_KEYS)
        assert r["origin"] in ("opd_text", "opd_file", "source") and (r["origin"] == "opd_text" or r["url"])
    blocks = [R.shard_rows("test", f"{i}/6") for i in range(6)]
    assert sum(map(len, blocks)) == 478 and len({(r["body"], r["affair_id"]) for b in blocks for r in b}) == 478


def test_analysis_reproduces_the_registered_p7_figures(tmp_path):
    dec = [dict(body=d["body"], affair_id=d["affair_id"], reason=d["reason"], scored=True, p7_8b=d["p7"], why_8b=d["p7_why"],
                date_8b=d["p7_date"], gate_rule_any_8b=False, text_identical=True)
           for d in R._jsonl(R.P7 / "test_decisions.jsonl")]
    R._write_jsonl(tmp_path / "dec.jsonl", dec)
    theta = tmp_path / "theta.json"
    theta.write_text(json.dumps(dict(theta_a=8.0, theta_b=10.0, is_answer="a2", date="b1", dev={})))
    env = dict(os.environ, GP_P7_8B_THETA=str(theta), GP_P7_8B_OUT=str(tmp_path / "out"))
    code = ("import sys; from pathlib import Path; from eval.p7 import run_8b as R; "
            "R.hypotheses(Path(sys.argv[1]), Path(sys.argv[2]))")
    subprocess.run([sys.executable, "-c", code, str(tmp_path / "dec.jsonl"), str(tmp_path / "h.json")], env=env, cwd=ROOT,
                   check=True)
    res = json.loads((tmp_path / "h.json").read_text())
    reg = json.loads((ROOT / "results" / "p7" / "p7_hypotheses.json").read_text())
    assert res["checks"] == dict(registered_70b_arm_reproduced=True, registered_h4_reproduced=True)
    for m in ("precision", "precision_dated", "recall_all", "recall_attainable"):
        assert res["arms"]["p7_8b"][m] == reg["arms"]["p7"][m]
    assert res["H4_8b"]["difference_precision_dated_8b_minus_trivial"] == reg["H4"]["difference_precision_dated_p7_minus_trivial"]
    h = res["H1_8b_on_p7_sample"]
    assert (h["promoted_8b"], h["correct"], h["wilson95"]) == (reg["H1"]["n"], reg["H1"]["correct"], reg["H1"]["wilson95"])
    assert res["arms"]["rule_any_view"]["promoted_in_frame"] == 217  # the committed no-model ablation (posthoc_r8)


# ------------------------------------------------------------------------------------------------ the CI path
DRIVER = r'''
import hashlib, json, os, sys
from pathlib import Path
from eval.p7 import run_8b as R
from gegenprobe.repair.adapters import adjudicate as J, base

mode, n_test = sys.argv[1], int(sys.argv[2])
GOLD = {}  # synthetic mode: affair number -> gold is_answer (dev and test annotations), so that the fit finds a θ
if mode == "synthetic":
    for split, key, gold in (("dev", "dev_key.jsonl", "dev_annotations/gold.jsonl"),
                             ("test", "test_key.jsonl", "test_annotations/gold.jsonl")):
        g = {x["id"]: x["is_answer"] for x in R._jsonl(R.P7 / gold)}
        num = {(r["body"], r["affair_id"]): r["target"]["number"] for r in R.load_rows(split)}
        for k in R._jsonl(R.P7 / key):
            GOLD[num[(k["body"], k["affair_id"])]] = g[k["id"]]

class Fake:
    """Deterministic stand-in for the GGUF scorer. Synthetic mode: m_yes 12 on gold-yes rows, 2 on the others, the
    first printed date chosen; otherwise m_yes in [0, 19] and the preferred letter from the prompt hash."""
    build = "fake:p7-8b-test"
    def score(self, user, prefix, conts):
        h = int(hashlib.sha256(user.encode()).hexdigest()[:12], 16)
        number = user.split("- number: ", 1)[1].split("\n", 1)[0]
        if prefix == J.ANSWER_PREFIX:
            m = (12.0 if GOLD[number] == "yes" else 2.0) if number in GOLD else float(h % 20)
            return [-0.01, -0.01 - m]
        pick = 0 if GOLD else h % max(1, len(conts) - 1)
        return [-0.05 if i == pick else -6.0 - i for i in range(len(conts))]

if mode == "synthetic":  # no WORK: write texts that print the OPD dates, as a fetch would have
    for split in ("dev", "test"):
        shards = ["0/1"] if split == "dev" else [f"0/{n_test}"]
        for sh in shards:
            status = {}
            for r in R.shard_rows(split, sh):
                t = r["target"]
                ds = (t["answer_dates"] or t["submit_dates"] or ["2020-01-01"])
                body = (f"Antwort des Regierungsrates auf die Interpellation {t['number']} {t['title']}\n"
                        + "".join(f"Sitzung vom {d[8:10]}.{d[5:7]}.{d[:4]}\n" for d in ds) + "x " * 150)
                base.save_excerpt(r["body"], r["affair_id"], body, dict(affair_id=r["affair_id"], rebuilt="test"))
                status[f"{r['body']}/{r['affair_id']}"] = dict(ok=True, text_identical=False)
            R.SHARDS.mkdir(parents=True, exist_ok=True)
            (R.SHARDS / f"fetch__{R._tag(split, sh)}.json").write_text(json.dumps(dict(status=status)))
    dev_shards, test_shards = ["0/1"], [f"0/{n_test}"]
else:  # real local caches, network refused
    dev_shards = [f"{i}/4" for i in range(4)]
    test_shards = [f"{i}/6" for i in range(6)]
    reps = [R.fetch("dev", s) for s in dev_shards] + [R.fetch("test", s) for s in test_shards]
    print("FETCH", json.dumps(dict(fetched=sum(r["fetched"] for r in reps), identical=sum(r["text_identical"] for r in reps),
                                   failed=[k for r in reps for k in r["failed"]])))
for s in dev_shards:
    R.features("dev", s, be=Fake())
R.fit()
for s in test_shards:
    R.features("test", s, be=Fake())
R.merge()
'''


def _run(tmp_path, mode, work, n_test="40"):
    env = dict(os.environ, GP_WORK=str(work), GP_P7_8B_THETA=str(tmp_path / "theta.json"),
               GP_P7_8B_OUT=str(tmp_path / "out"), GP_P7_8B_OFFLINE="1",
               PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    p = subprocess.run([sys.executable, "-c", DRIVER, mode, n_test], env=env, cwd=ROOT, capture_output=True, text=True,
                       timeout=3600)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    return p.stdout


def _check_outputs(tmp_path, n_test_scored):
    theta = json.loads((tmp_path / "theta.json").read_text())
    assert theta["label"].startswith("EXPLORATORY") and theta["is_answer"] == "a2" and theta["dev_scored"] == 80
    dec = R._jsonl(tmp_path / "out" / "decisions.jsonl")
    assert len(dec) == 478 and sum(d["scored"] for d in dec) == n_test_scored
    assert all(not d["p7_8b"] for d in dec if not d["scored"])
    h = json.loads((tmp_path / "out" / "hypotheses.json").read_text())
    assert h["checks"] == dict(registered_70b_arm_reproduced=True, registered_h4_reproduced=True)
    assert h["coverage"]["scored"] == n_test_scored and h["label"].startswith("EXPLORATORY")
    for f in R._jsonl(tmp_path / "out" / "features_test.jsonl") + R._jsonl(tmp_path / "out" / "features_dev.jsonl"):
        assert all("line" not in (s or {}) for s in f["b"]["b1"]["spans"].values())  # no document text written
    return theta, h


def test_ci_path_with_a_fake_backend_on_synthetic_texts(tmp_path):
    out = _run(tmp_path, "synthetic", tmp_path / "work", n_test="1")
    theta, h = _check_outputs(tmp_path, 478)
    assert "8B promotes" in out
    # the fake answers yes on exactly the gold-yes rows and the synthetic texts print OPD's dates: the tune rule finds a
    # θ_A, and every promotion is correct
    assert theta["theta_a"] is not None and theta["dev"]["promoted"] > 0 and theta["dev"]["precision"] == 1.0
    s = h["H1_8b_on_p7_sample"]
    assert s["promoted_8b"] > 0 and s["correct"] == s["promoted_8b"] and h["H1_8b_frame"]["promoted_in_frame"] > 0


@pytest.mark.skipif(not (REAL_WORK / "adapters" / "url_cache.jsonl").exists(), reason="needs the real P7 WORK caches")
def test_fetch_rebuilds_every_p7_text_from_the_local_caches(tmp_path):
    """The CI fetch path on the 558 rows, network refused: every text comes back byte-identical (OPD docs snapshots,
    url cache, PDFs and extracted-text caches linked read-only into a scratch WORK; excerpts are written there)."""
    work = tmp_path / "work"
    (work / "adapters").mkdir(parents=True)
    for rel in ("adapters/opd_docs", "adapters/raw", "pdf", "text"):
        if (REAL_WORK / rel).exists():
            (work / rel).symlink_to(REAL_WORK / rel)
    (work / "adapters" / "url_cache.jsonl").write_bytes((REAL_WORK / "adapters" / "url_cache.jsonl").read_bytes())
    out = _run(tmp_path, "local", work)
    fetch = json.loads(next(x for x in out.splitlines() if x.startswith("FETCH "))[6:])
    assert fetch == dict(fetched=558, identical=558, failed=[])
    _check_outputs(tmp_path, 478)
    for r in R.load_rows():  # the excerpts the 8B read are the committed texts
        t = (work / "adapters" / "excerpts" / r["body"] / f"{r['affair_id']}.txt").read_text(encoding="utf-8")
        assert hashlib.sha256(t.split("\n\n", 1)[1].encode()).hexdigest() == r["text_sha256"]
