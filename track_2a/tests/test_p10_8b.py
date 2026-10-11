"""EXPLORATORY 8B arm on P10 (eval/p10/run_8b.py), offline: no model, no network.

  * the committed recipe covers the 40 P10 test and the 36 development affairs, carries no document text, and its pinned
    inputs are intact; the shards partition the work units
  * fed the registered gateway pointer, the scaffold reproduces results/p10/p10_scores.json exactly (score.py unchanged)
  * the whole CI path (fetch -> features on several shards -> merge, refit on development included) runs with a fake
    backend, and the roles composed from the stored answers equal what `roles_pointer.read` returns on the same texts
    with the same backend, for the frozen and the refitted thresholds; with the real WORK present, the fetch step
    rebuilds every PDF and text from the local caches byte-identically (network refused)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from eval.p10 import run_8b as R

ROOT = Path(__file__).resolve().parents[1]
REAL_WORK = Path(os.environ.get("GP_WORK", ROOT / ".work"))
FILLER = "Synthetischer Fülltext ohne Bedeutung für den Offline-Test. "


def test_committed_recipe_and_pins():
    rows = R.load_rows()
    assert len(rows) == 76 and sum(r["split"] == "test" for r in rows) == 40 and sum(r["split"] == "dev" for r in rows) == 36
    assert all(r["recipe_verified_local"] for r in rows)
    gold = {g["affair_id"] for g in R._jsonl(R.C.GOLD)}
    assert {r["affair_id"] for r in rows if r["split"] == "test"} == gold
    assert {r["affair_id"] for r in rows if r["split"] == "dev"} == {d["affair_id"] for d in R._dev_gold()}
    for r in rows:
        assert "text" not in r and len(r["kinds"]) == r["n_cands"] and len(r["docs"]) == 2
        assert all(len(d["sha256"]) == 64 and len(d["text_sha256"]) == 64 for d in r["docs"])
    assert R.lockcheck() == []
    pins = json.loads(R.PINS.read_text())
    assert pins["registered_pointer_recomposed"] == "40/40"
    for split, n in (("test", 6), ("dev", 10)):
        us = [(u["affair_id"], u["idx"]) for i in range(n) for u in R.shard_units(split, f"{i}/{n}")]
        assert us == [(u["affair_id"], u["idx"]) for u in R.units(split)]  # contiguous, disjoint, complete


def test_scaffold_reproduces_the_registered_p10_scores():
    assert R.check_registered() == dict(registered_table_reproduced=True, registered_candidates_reproduced=True,
                                        registered_secondary_reproduced=True, registered_hypotheses_reproduced=True)


# ------------------------------------------------------------------------------------------------ the CI path
DRIVER = r'''
import hashlib, json, sys
from pathlib import Path
from eval.p10 import run_8b as R
from eval.p10 import arms as A
from gegenprobe import pdftext
from gegenprobe.paths import PDF_CACHE, TEXT_CACHE
from gegenprobe.convert import role_candidates as RC, roles_pointer as RP

mode, FILLER = sys.argv[1], sys.argv[2]

class Fake:
    """Deterministic stand-in for the GGUF scorer: P(true) from the prompt hash."""
    build, kind = "fake:p10-8b-test", "gguf"
    def score(self, user, prefix, conts):
        h = int(hashlib.sha256((user + prefix).encode()).hexdigest()[:12], 16)
        x = (h % 1000) / 1000 * 12 - 6
        return [-0.01, -0.01 - x] if x > 0 else [-0.01 + x, -0.01]

if mode == "synthetic":  # no WORK: a placeholder PDF per document and its synthetic pages in the text cache
    pdftext.poppler_version = lambda: "synthetic"
    PDF_CACHE.mkdir(parents=True, exist_ok=True); TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    N = {s: R.rosters(s) for s in ("test", "dev")}
    for r in R.load_rows():
        names = [f"{f} {l}" for f, l in (N[r["split"]].get(r["body"]) or [("Anna", "Muster"), ("Beat", "Beispiel")])[:3]]
        for d in r["docs"]:
            (PDF_CACHE / f"{d['sha256']}.pdf").write_bytes(b"%PDF-1.4 placeholder")
            if d["role"] == "question":
                pages = [f"Interpellation betreffend Synthese\n\nErstunterzeichner: {names[0]}\n"
                         f"Mitunterzeichnende: {', '.join(names[1:])}\n\n" + FILLER * 30, FILLER * 20 + f"\n{names[0]}\n"]
            else:
                pages = ["Antwort des Gemeinderates auf die Interpellation von " + names[0] + " und Mitunterzeichnende\n\n"
                         + FILLER * 25]
            (TEXT_CACHE / f"{d['sha256']}.pdftotext-synthetic.json").write_text(json.dumps(
                dict(sha256=d["sha256"], extractor="pdftotext-synthetic", pages=pages, image_only=False)))

dev_shards, test_shards = [f"{i}/3" for i in range(3)], [f"{i}/2" for i in range(2)]
reps = [R.fetch("dev", s) for s in dev_shards] + [R.fetch("test", s) for s in test_shards]
print("FETCH", json.dumps(dict(fetched=sum(r["fetched"] for r in reps), affairs=sum(r["affairs"] for r in reps),
                               identical=sum(r["text_identical"] for r in reps), failed=[k for r in reps for k in r["failed"]])))
for s in dev_shards:
    R.features("dev", s, be=Fake())
for s in test_shards:
    R.features("test", s, be=Fake())
out = R.merge(n_boot=200)

# the roles composed from the stored answers == roles_pointer.read on the same texts with the same backend
cfg = R.config()
got = {x["affair_id"]: x for x in R._jsonl(R.OUT / "p10_pointer_8b.jsonl")}
variants = {"frozen": cfg}
if out["refit"].get("available"):
    variants["refit_dev"] = dict(cfg, tau=out["refit"]["tau"], tau_first=out["refit"]["tau_first"])
same = 0
for r in R.load_rows("test"):
    q, a = R.affair_inputs(r)
    cands = RC.candidates(q, a, R.rosters("test").get(r["body"], []))["candidates"]
    for k, c in variants.items():
        res = RP.read(Fake(), q, a, cands, A.lang_of(r["stratum"], q), c)
        same += [tuple(x) for x in got[r["affair_id"]][f"pointer_8b_{k}"]] == A.pointer_pairs(res)
print("READ", json.dumps(dict(same=same, of=40 * len(variants), refit=out["refit"].get("available"))))
'''


def _run(tmp_path, mode, work):
    env = dict(os.environ, GP_WORK=str(work), GP_P10_8B_OUT=str(tmp_path / "out"), GP_P10_8B_OFFLINE="1",
               PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    p = subprocess.run([sys.executable, "-c", DRIVER, mode, FILLER], env=env, cwd=ROOT, capture_output=True, text=True,
                       timeout=3600)
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    line = {x.split(" ", 1)[0]: json.loads(x.split(" ", 1)[1]) for x in p.stdout.splitlines()
            if x.startswith(("FETCH ", "READ "))}
    return line["FETCH"], line["READ"]


def _check_outputs(tmp_path, text_identical: bool):
    out = tmp_path / "out"
    res = json.loads((out / "p10_8b_scores.json").read_text())
    reg = json.loads((ROOT / "results" / "p10" / "p10_scores.json").read_text())
    assert res["label"].startswith("EXPLORATORY") and res["refit"]["available"]
    assert res["checks"]["registered_table_reproduced"] and res["checks"]["registered_candidates_reproduced"]
    assert set(res["variants"]) == {"frozen", "refit_dev"}
    for v in res["variants"].values():
        assert v["coverage"]["pointer_run"] == 40 and set(v["holds"]) == {"H1", "H2", "H3a", "H3b"}
        assert v["primary"]["table"]["all"]["pointer_registered"] == reg["primary"]["table"]["all"]["pointer"]
    assert res["variants"]["frozen"]["thresholds"] == dict(tau=0.98, tau_first=0.3)
    assert res["checks"]["text_identical"] == (40 if text_identical else 0)
    for p in out.rglob("*"):  # no document text in any output (the synthetic filler, or any long line of a page)
        if p.is_file():
            assert FILLER.strip() not in p.read_text(encoding="utf-8")
    for f in R._jsonl(next(out.glob("shards/test__0_of_2.jsonl"))):
        assert set(f) == {"split", "id", "affair_id", "idx", "value", "kind", "answers", "prompt_ids", "n_prompt",
                          "seconds"}
    return res


def test_ci_path_with_a_fake_backend_on_synthetic_texts(tmp_path):
    fetch, read = _run(tmp_path, "synthetic", tmp_path / "work")
    assert fetch["failed"] == [] and fetch["fetched"] == fetch["affairs"] >= 76 and fetch["identical"] == 0
    assert read == dict(same=80, of=80, refit=True)
    _check_outputs(tmp_path, text_identical=False)


@pytest.mark.skipif(not all((REAL_WORK / d).exists() for d in ("pdf", "text")), reason="needs the real P10/P8 WORK caches")
def test_fetch_rebuilds_every_p10_text_from_the_local_caches(tmp_path):
    """The CI fetch path on the 76 affairs, network refused: every PDF from the local cache by its sha256, every text
    byte-identical to the committed text sha256, every candidate list identical to the committed one."""
    work = tmp_path / "work"
    work.mkdir()
    for rel in ("pdf", "text"):
        (work / rel).symlink_to(REAL_WORK / rel)
    fetch, read = _run(tmp_path, "local", work)
    assert fetch["failed"] == [] and fetch["fetched"] == fetch["affairs"] == fetch["identical"]
    assert read == dict(same=80, of=80, refit=True)
    res = _check_outputs(tmp_path, text_identical=True)
    assert res["checks"]["candidates_identical"] == 40
