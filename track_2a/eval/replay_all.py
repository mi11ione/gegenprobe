"""`make run` replay of all pre-registrations (P1-P8), from committed files only, plus re-derivation of Apertus decisions.

Step `replay` (FAIL on any difference; no network, no model):
  P1  results/eval/{dev,heldout}__*.json   per-document predictions re-scored with eval/score.py and eval.arms.score_rec
                                            against the COMMITTED label files (data/gold/{dev,heldout}_labels.jsonl), not
                                            against the gold copied into the results file
  P2  results/eval2/p2__*.json             same scorer, labels data/gold2/p2_labels.jsonl
  P3  results/eval3/p3__*.json             eval.gold3.score3.score_all against data/gold3/p3_labels.jsonl
  P4  results/eval4/p4_heldout__*.json     eval.gold4.run_p4.score against data/gold4/p4_heldout_labels.jsonl
  hypotheses  eval.hypotheses, eval.gold2.hypotheses2, eval.gold3.hypotheses3, eval.gold4.hypotheses4 re-run into a
              temporary results tree; each output must be JSON-equal to the committed one
  locks       LOCK, LOCK2, LOCK3, LOCK4: every frozen file still has its registered sha256
  P3b         results/eval5/p3b__*.json re-scored (eval.gold3.score3.score_all, labels data/gold5/p3b_labels.jsonl),
              eval.gold5.hypotheses5 re-run into a scratch tree (JSON-equal to the committed file), LOCK5 verified
              (added 10 Oct 2026, round 4)
  8B          eval.gguf_8b_analysis re-run offline into a scratch tree from the committed 8B rows, θ file and CI timings;
              both outputs (gguf_8b_analysis.json, hypotheses__gguf_….json) must be JSON-equal to the committed ones
  P5          eval.gold6.hypotheses6 (split p5) re-run into a scratch tree from results/eval6/p5__*.json and
              data/gold6/p5_labels.jsonl; output must be byte-identical to the committed file; LOCK6 verified. The p5dev
              file is not replayed: it was written before LOCK6 by an earlier version of the script (no H3 fields)
  P6          eval.p6.hypotheses7 re-run into a scratch file from results/p6/p6__*.json and data/p6/p6_labels.jsonl; output
              must be byte-identical to the committed file; LOCK7 verified (P5/P6 added 11 Oct 2026, round 6)
  P7          eval.p7.replay8: the frozen eval.p7.hypotheses8 and eval.p7.tune.table re-run in a subprocess on a scratch
              WORK laid out from the committed copies in data/p7/ (test key + arm decisions, whose sha256 the frozen
              code checks against results/p7/test_sample.json; dev key + features; gold; the adapters' date-rule outcomes
              per (parliament, affair, gold date)); both outputs byte-identical to the committed files; LOCK8 verified on
              the repository files and the dev key copy (WORK inputs where present). Added 11 Oct 2026, round 8
  P8          eval.p8.score and eval.p8.hypotheses9 re-run from the committed merged gold (data/p8/p8_gold.jsonl) into a
              scratch tree; p8_tables.json and p8_hypotheses.json byte-identical to the committed files; LOCK9 verified on
              the repository files, the WORK keys through their committed copies (data/p7/*_key.jsonl,
              results/repair/adapters/audit3/key.jsonl) and the adapter-audit globs where WORK has them
  P7 post hoc eval/p7/offline.py: posthoc8, posthoc_r8 and cluster_r9 (not registered) re-run on the committed copies in
              data/p7/ (rule_any_outcomes.jsonl replaces the extracted texts); outputs byte-identical. Added round 10

Step `rederive_apertus` (PASS / WARN / SKIP; FAIL only if a decision recomputed from a cache HIT disagrees):
  For the P1 held-out and P2 documents whose PDF can be fetched and sha256-verified within the time budget, extract
  the text, rebuild the exact frozen prompts (convert/pointer.py, convert/cascade.py) and
  recompute the pointer and cascade decisions from the committed hash-keyed model cache (data/model_cache), cache-only:
  no request leaves the machine. A cache MISS means the prompt differs from the one the model saw, which happens when
  the local poppler/tesseract build extracts the text differently; misses are counted with both extractor versions.
  Budget: GP_REDERIVE_APERTUS_BUDGET seconds (default 180) PER SET, so P2 is always attempted. Until round 3 the budget
  was shared (120 s) and P1 used all of it: the CI make-run of fec4029 reached 0 of the 62 P2 documents.

    python -m eval.replay_all [replay|rederive_apertus]
"""
from __future__ import annotations

import collections
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from gegenprobe.paths import DATA, RESULTS
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
SERVED = "publicai:swiss-ai/apertus-v1.5-8b"


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def _norm(x):
    """JSON round trip so tuples, int/float keys etc. compare as stored."""
    return json.loads(json.dumps(x, sort_keys=True))


def _diff(a, b, path="", out=None, limit=8):
    """First few differing paths between two JSON values (for the report)."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'committed' if k in a else 'recomputed'}")
            else:
                _diff(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}: committed {str(a)[:60]} != recomputed {str(b)[:60]}")
    return out


# ------------------------------------------------------------------------------------------------ P1 / P2 re-scoring
def _arm_rows(per_doc: list[dict], labels: dict[int, dict]) -> tuple[dict, dict, list[str]]:
    """Rebuild the scorer rows exactly as eval.arms.run does, with gold taken from the committed label file."""
    rows: dict[str, list] = collections.defaultdict(list)
    rec_rows: dict[str, list] = collections.defaultdict(list)
    problems = []
    for r in per_doc:
        lab = labels.get(r["doc_id"])
        if lab is None:
            problems.append(f"doc {r['doc_id']}: no committed label")
            continue
        if r.get("gold") != lab["answer_date"]:
            problems.append(f"doc {r['doc_id']}: gold in results {r.get('gold')} != label file {lab['answer_date']}")
        base = dict(cell=r["cell"], gold=lab["answer_date"], lenient=lab.get("answer_date_lenient") or [],
                    doc_dates=r.get("doc_dates") or [])
        if "rules" in r:
            ru = r["rules"]
            rows["rules"].append(dict(base, pred=ru.get("value") if ru.get("status") == "value" else None, route="rule"))
        if "pointer" in r:
            rows["pointer"].append(dict(base, pred=r["pointer"].get("value"), route="apertus"))
        if "cascade" in r:
            rows["cascade"].append(dict(base, pred=r["cascade"].get("value"), route=r["cascade"].get("route")))
        for arm in ("plain", "null"):
            g = r.get(f"naive_{arm}")
            if g is not None:
                pred = None if (g.get("date") or "").startswith("unparseable") else g.get("date")
                rows[f"naive_{arm}"].append(dict(base, pred=pred, route="apertus", receipt_ok=g.get("receipt_ok")))
        if "rec_rules" in r:
            gold_rec = lab.get("recommendation")
            rr = r["rec_rules"]
            r_val = rr.get("value") if rr.get("status") == "value" else None
            rec_rows["rec_rules"].append(dict(cell=r["cell"], gold=gold_rec, pred=r_val))
            if "rec_pointer" in r:
                pv = r["rec_pointer"].get("value")
                rec_rows["rec_pointer"].append(dict(cell=r["cell"], gold=gold_rec, pred=pv))
                c_val = r_val if rr.get("status") == "value" else (None if rr.get("status") == "null" else pv)
                rec_rows["rec_cascade"].append(dict(cell=r["cell"], gold=gold_rec, pred=c_val,
                                                    route="rule" if rr.get("status") != "abstain" else "apertus"))
    return rows, rec_rows, problems


def rescore_arms(res: dict, label_file: Path) -> list[str]:
    from eval.arms import score_rec
    from eval.score import summarise
    labels = {lab["doc_id"]: lab for lab in _jsonl(label_file)}
    rows, rec_rows, bad = _arm_rows(res["per_doc"], labels)
    for arm, stored in res["arms"].items():
        if arm not in rows:
            bad.append(f"arm {arm}: no per-doc predictions")
            continue
        got = dict(strict=summarise(rows[arm], True), lenient=summarise(rows[arm], False))
        bad += [f"{arm}{d}" for d in _diff(_norm(stored), _norm(got))]
    for arm, stored in (res.get("recommendation") or {}).items():
        bad += [f"{arm}{d}" for d in _diff(_norm(stored), _norm(score_rec(rec_rows[arm])))]
    return bad


def replay_p1_p2() -> list[dict]:
    out = []
    for split, files, labels in (
        ("P1 dev", sorted((RESULTS / "eval").glob("dev__*.json")), DATA / "gold" / "dev_labels.jsonl"),
        ("P1 held-out", sorted((RESULTS / "eval").glob("heldout__*.json")), DATA / "gold" / "heldout_labels.jsonl"),
        ("P2 unseen parliaments", sorted((RESULTS / "eval2").glob("p2__*.json")), DATA / "gold2" / "p2_labels.jsonl"),
    ):
        for f in files:
            res = json.loads(f.read_text())
            if split == "P1 dev":  # dev labels are keyed by (source, doc_id); spike items carry their own label rows
                labs = {}
                for lab in _jsonl(labels):
                    labs.setdefault(lab["doc_id"], lab)
                tmp = Path(tempfile.mkdtemp()) / "dev_labels.jsonl"
                tmp.write_text("".join(json.dumps(v) + "\n" for v in labs.values()))
                bad = rescore_arms(res, tmp)
            else:
                bad = rescore_arms(res, labels)
            out.append(dict(test=f"{split}: {f.name}", ok=not bad, detail=bad[:8], n=len(res["per_doc"])))
    return out


# ------------------------------------------------------------------------------------------------ P3 / P4 re-scoring
def replay_p3() -> list[dict]:
    from eval.gold3.score3 import score_all
    out = []
    labels = {g["affair_id"]: g for g in _jsonl(DATA / "gold3" / "p3_labels.jsonl")}
    entries = {e["affair_id"]: e for e in _jsonl(DATA / "gold3" / "p3_affairs.jsonl")}
    for f in sorted((RESULTS / "eval3").glob("p3__*.json")):
        res = json.loads(f.read_text())
        got = score_all(res["per_affair"], labels, entries)
        bad = _diff(_norm(res["scores"]), _norm(got))
        out.append(dict(test=f"P3 whole affairs: {f.name}", ok=not bad, detail=bad, n=len(res["per_affair"])))
    return out


def replay_p4() -> list[dict]:
    from eval.gold4 import run_p4
    out = []
    for f in sorted((RESULTS / "eval4").glob("p4_heldout__*__score.json")):
        build = f.name[len("p4_heldout__"):-len("__score.json")]
        tmp = Path(tempfile.mkdtemp())
        shutil.copyfile(RESULTS / "eval4" / f"p4_heldout__{build}.json", tmp / f"p4_heldout__{build}.json")
        old, run_p4.OUT = run_p4.OUT, tmp
        try:
            got = run_p4.score("heldout", build)
        finally:
            run_p4.OUT = old
        bad = _diff(_norm(json.loads(f.read_text())), _norm(got))
        out.append(dict(test=f"P4 virtual affairs: {f.name}", ok=not bad, detail=bad, n=got.get("n_gold_items")))
    return out


# ------------------------------------------------------------------------------------------------ hypotheses + locks
HYPOTHESES = [
    ("P1 H1-H4", "eval.hypotheses", "eval", "hypotheses__{b}.json"),
    ("P2 H1-H4", "eval.gold2.hypotheses2", "eval2", "hypotheses2__{b}.json"),
    ("P3 H1-H4", "eval.gold3.hypotheses3", "eval3", "hypotheses3__{b}.json"),
    ("P4 H1-H4", "eval.gold4.hypotheses4", "eval4", "hypotheses4__{b}.json"),
]


def replay_hypotheses(build: str = BUILD) -> list[dict]:
    import importlib
    out = []
    tmp = Path(tempfile.mkdtemp())
    for sub in ("eval", "eval2", "eval3", "eval4"):
        if (RESULTS / sub).exists():
            shutil.copytree(RESULTS / sub, tmp / sub)
    for name, mod, sub, pat in HYPOTHESES:
        committed = RESULTS / sub / pat.format(b=build)
        if not committed.exists():
            out.append(dict(test=f"{name} ({mod})", ok=False, detail=[f"{committed.name} not committed"]))
            continue
        m = importlib.import_module(mod)
        old = m.RESULTS
        m.RESULTS = tmp
        try:
            m.main(build)
        finally:
            m.RESULTS = old
        got = json.loads((tmp / sub / pat.format(b=build)).read_text())
        bad = _diff(_norm(json.loads(committed.read_text())), _norm(got))
        out.append(dict(test=f"{name} ({mod})", ok=not bad, detail=bad))
    return out


def replay_p3b(build: str = BUILD) -> list[dict]:
    """P3b: re-score from the committed labels, re-run the registered hypotheses/verdict script into a scratch tree."""
    from eval.gold3.score3 import score_all
    from eval.gold5 import hypotheses5
    out = []
    labels = {g["affair_id"]: g for g in _jsonl(DATA / "gold5" / "p3b_labels.jsonl")}
    entries = {e["affair_id"]: e for e in _jsonl(DATA / "gold5" / "p3b_affairs.jsonl")}
    for f in sorted((RESULTS / "eval5").glob("p3b__*.json")):
        res = json.loads(f.read_text())
        if "scores" not in res:  # the rules-only file carries no scores (scored only for the model build)
            continue
        bad = _diff(_norm(res["scores"]), _norm(score_all(res["per_affair"], labels, entries)))
        out.append(dict(test=f"P3b fresh affairs: {f.name}", ok=not bad, detail=bad, n=len(res["per_affair"])))
    committed = RESULTS / "eval5" / f"hypotheses_p3b__{build}.json"
    tmp = Path(tempfile.mkdtemp())
    shutil.copyfile(RESULTS / "eval5" / f"p3b__{build}.json", tmp / f"p3b__{build}.json")
    saved = hypotheses5.OUT5, hypotheses5.STAGE
    hypotheses5.OUT5, hypotheses5.STAGE = tmp, tmp / "stage_h"
    try:
        hypotheses5.main(build)
    finally:
        hypotheses5.OUT5, hypotheses5.STAGE = saved
    bad = _diff(_norm(json.loads(committed.read_text())), _norm(json.loads((tmp / committed.name).read_text())))
    out.append(dict(test="P3b H1-H4 + replication verdict (eval.gold5.hypotheses5)", ok=not bad, detail=bad))
    return out


def replay_8b() -> list[dict]:
    """The 8B analysis (exploratory P1 arms on the real 8B) re-run offline from committed files into a scratch tree."""
    from eval import gguf_8b_analysis as g8
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(RESULTS / "eval", tmp / "eval")
    saved = g8.RESULTS, g8.TIMES
    g8.RESULTS, g8.TIMES = tmp, tmp / "eval" / g8.TIMES.name
    try:
        g8.main()
    finally:
        g8.RESULTS, g8.TIMES = saved
    out = []
    for name in ("gguf_8b_analysis.json", f"hypotheses__{g8.B8}.json"):
        bad = _diff(_norm(json.loads((RESULTS / "eval" / name).read_text())),
                    _norm(json.loads((tmp / "eval" / name).read_text())))
        out.append(dict(test=f"8B analysis: {name} (eval.gguf_8b_analysis)", ok=not bad, detail=bad))
    return out


def _bytes_check(name: str, committed: Path, got: Path) -> dict:
    a, b = committed.read_bytes(), got.read_bytes()
    if a == b:
        return dict(test=name, ok=True, detail=[])
    bad = _diff(_norm(json.loads(a)), _norm(json.loads(b))) or ["JSON-equal but not byte-identical"]
    return dict(test=name, ok=False, detail=bad)


def replay_p5(build: str = BUILD) -> list[dict]:
    """P5: the registered hypotheses script re-run from the committed results and labels into a scratch tree."""
    from eval.gold6 import hypotheses6
    out = []
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(RESULTS / "eval6", tmp / "eval6")
    for split in ("p5",):
        committed = RESULTS / "eval6" / f"hypotheses6__{split}__{build}.json"
        if not committed.exists():
            out.append(dict(test=f"P5 {split} (eval.gold6.hypotheses6)", ok=False, detail=[f"{committed.name} not committed"]))
            continue
        (tmp / "eval6" / committed.name).unlink()
        old = hypotheses6.RESULTS
        hypotheses6.RESULTS = tmp
        try:
            hypotheses6.main(split, build)
        finally:
            hypotheses6.RESULTS = old
        name = f"P5 H1-H5 + verdict ({split}, eval.gold6.hypotheses6, byte-identical)"
        out.append(_bytes_check(name, committed, tmp / "eval6" / committed.name))
    return out


def replay_p6(build: str = BUILD) -> list[dict]:
    """P6: the registered hypotheses script re-run from the committed results and labels into a scratch file."""
    from eval.p6 import hypotheses7
    committed = RESULTS / "p6" / f"hypotheses7__{build}.json"
    if not committed.exists():
        return [dict(test="P6 (eval.p6.hypotheses7)", ok=False, detail=[f"{committed.name} not committed"])]
    got = Path(tempfile.mkdtemp()) / committed.name
    hypotheses7.main(build, res_path=RESULTS / "p6" / f"p6__{build}.json", labels_path=DATA / "p6" / "p6_labels.jsonl",
                     out_path=got)
    return [_bytes_check("P6 H1-H3 + secondaries (eval.p6.hypotheses7, byte-identical)", committed, got)]


def replay_p7() -> list[dict]:
    """P7: LOCK8, the committed WORK copies' hashes, hypotheses8 and the dev table, byte-identical (eval/p7/replay8.py)."""
    from eval.p7 import replay8
    return replay8.replay()


def replay_p7_posthoc() -> list[dict]:
    """P7 post hoc (not registered): posthoc8, posthoc_r8 and cluster_r9 re-run on the committed copies in data/p7/
    (eval/p7/offline.py), each output byte-identical to results/p7/."""
    from eval.p7 import offline
    return offline.check()


# committed copies of LOCK9's single-file WORK inputs (identical bytes; a clean checkout has no WORK)
LOCK9_COPIES = {"WORK/p7dev/key.jsonl": DATA / "p7" / "dev_key.jsonl", "WORK/p7test/key.jsonl": DATA / "p7" / "test_key.jsonl",
                "WORK/adapters/audit3/key.jsonl": RESULTS / "repair" / "adapters" / "audit3" / "key.jsonl"}


def lock9() -> dict:
    """LOCK9 on what a checkout has: every frozen repository file; the WORK keys through their committed copies; the
    adapter-audit globs where WORK has them."""
    import hashlib
    from eval.prereg9 import lock9 as L9
    lk = json.loads(L9.LOCK9.read_text())
    bad = [f for f, h in lk["p8_files"].items() if not (L9.ROOT / f).exists() or L9.digest(f) != h]
    checked = 0
    for k, h in lk["work_inputs"].items():
        if k in LOCK9_COPIES:
            checked += 1
            if hashlib.sha256(LOCK9_COPIES[k].read_bytes()).hexdigest() != h:
                bad.append(f"{LOCK9_COPIES[k].relative_to(L9.ROOT)} != LOCK9 work_inputs {k}")
    from gegenprobe.paths import WORK
    globs = [k for k in lk["work_inputs"] if k not in LOCK9_COPIES]
    present = []
    for k in globs:  # "WORK/<dir>/*.jsonl", hashed as eval.p8.common.work_inputs does
        files = sorted((WORK / k[len("WORK/"):-len("/*.jsonl")]).glob("*.jsonl"))
        if not files:
            continue
        present.append(k)
        h = hashlib.sha256()
        for f in files:
            h.update(f.name.encode() + b"\0" + f.read_bytes())
        if h.hexdigest() != lk["work_inputs"][k]:
            bad.append(k)
    return dict(test=f"LOCK9 (P8): {len(lk['p8_files'])} files, {checked} WORK keys via committed copies, "
                     f"{len(present)}/{len(globs)} audit globs present", ok=not bad, detail=bad[:8])


def replay_p8() -> list[dict]:
    """P8: the frozen scorer (eval.p8.score) and decision script (eval.p8.hypotheses9) re-run from the committed merged
    gold (data/p8/p8_gold.jsonl) into a scratch tree; both outputs byte-identical to results/p8/; LOCK9 verified."""
    from eval.p8 import hypotheses9, score
    tmp = Path(tempfile.mkdtemp())
    score.main(out=tmp / "p8_tables.json")
    hypotheses9.main(tables_path=tmp / "p8_tables.json", out_path=tmp / "p8_hypotheses.json")
    return [lock9(),
            _bytes_check("P8 tables (eval.p8.score, byte-identical)", RESULTS / "p8" / "p8_tables.json",
                         tmp / "p8_tables.json"),
            _bytes_check("P8 H1-H7 verdicts (eval.p8.hypotheses9, byte-identical)", RESULTS / "p8" / "p8_hypotheses.json",
                         tmp / "p8_hypotheses.json")]


def replay_locks() -> list[dict]:
    import importlib
    out = []
    for name, mod in (("LOCK (P1)", "eval.prereg.lock"), ("LOCK2 (P2)", "eval.prereg2.lock2"),
                      ("LOCK3 (P3)", "eval.prereg3.lock3"), ("LOCK4 (P4)", "eval.prereg4.lock4"),
                      ("LOCK5 (P3b)", "eval.prereg5.lock5"), ("LOCK6 (P5)", "eval.prereg6.lock6"),
                      ("LOCK7 (P6)", "eval.prereg7.lock7")):
        changed = importlib.import_module(mod).check()
        out.append(dict(test=name, ok=not changed, detail=[f"changed: {c}" for c in changed]))
    return out


def replay() -> dict:
    t0 = time.time()
    tests = (replay_p1_p2() + replay_p3() + replay_p4() + replay_hypotheses() + replay_p3b() + replay_8b() + replay_p5()
             + replay_p6() + replay_locks() + replay_p7() + replay_p8() + replay_p7_posthoc())
    fails = [t for t in tests if not t["ok"]]
    return dict(tests=tests, n=len(tests), failing=len(fails), secs=round(time.time() - t0, 1))


def main(ctx: dict | None = None) -> dict:
    r = replay()
    for t in r["tests"]:
        print(f"    {'PASS' if t['ok'] else 'FAIL'}  {t['test']}" + ("" if t["ok"] else f"  {t['detail'][:3]}"), flush=True)
    s = (f"{r['n'] - r['failing']}/{r['n']} replay tests pass "
         "(P1-P4 and P3b re-scored from committed labels, 9 hypotheses scripts incl. P5-P8, the P7 dev table, "
         "the P8 tables, the P7 post-hoc files, the 8B analysis, 9 locks)")
    return dict(status="FAIL" if r["failing"] else "PASS", summary=s, tests=r["tests"])


# ------------------------------------------------------------------------------------------------ Apertus re-derivation
def _offline_backend():
    from gegenprobe import llm
    be = llm.OpenAICompat(base_url="", api_key="", model="swiss-ai/apertus-v1.5-8b", build=SERVED, cache_readonly=True)
    be.offline = True  # cache only: a miss raises CacheMiss, nothing is sent anywhere
    return be


def _lang(d: dict) -> str:
    from eval import arms
    # exactly eval.arms.load_split + _lang (frozen; see DEVIATIONS D1 for the OCR cell)
    return arms._lang(dict(lang=d.get("lang") or {"it": "it", "fr": "fr"}.get(d["cell"][:2], "de"), cell=d["cell"]))


def rederive_apertus(budget_s: float | None = None) -> dict:
    from gegenprobe import llm, pdftext
    from gegenprobe.convert import cascade, pointer, rules
    # per set (P1, P2): a shared budget let P1 starve P2 (0/62 attempted in CI before round 3)
    budget_s = float(os.environ.get("GP_REDERIVE_APERTUS_BUDGET", "180")) if budget_s is None else budget_s
    t0 = time.time()
    be = _offline_backend()
    sets = []
    for name, docs_f, res_f in (
        ("P1 held-out", DATA / "gold" / "heldout_docs.jsonl", RESULTS / "eval" / f"heldout__{BUILD}.json"),
        ("P2 unseen", DATA / "gold2" / "p2_docs.jsonl", RESULTS / "eval2" / f"p2__{BUILD}.json"),
    ):
        if res_f.exists():
            res = json.loads(res_f.read_text())
            sets.append((name, _jsonl(docs_f), {r["doc_id"]: r for r in res["per_doc"]}, res["theta"]))
    out = dict(sets={}, poppler=pdftext.poppler_version(), tesseract=pdftext.tesseract_version())
    has_ocr = shutil.which("tesseract") is not None
    for name, docs, committed, theta in sets:
        t_set, stop = time.time(), False
        s = collections.Counter()
        s["n"] = len(docs)
        miss_examples, mismatches = [], []
        docs = sorted(docs, key=lambda d: (d.get("image_only", False), d["doc_id"]))
        for d in docs:
            if stop or time.time() - t_set > budget_s:
                stop = True
                s["not_reached_budget"] += 1
                continue
            if d.get("image_only") and not has_ocr:
                s["skipped_no_ocr"] += 1
                continue
            try:
                sha, path = pdftext.fetch_pdf(d["url"], expect_sha256=d["sha256"])
                t = pdftext.extract(sha, path)
            except Exception:  # unreachable, robots.txt, changed source
                s["unreachable"] += 1
                continue
            pages, lg, c = t["pages"], _lang(d), committed[d["doc_id"]]
            try:
                p = pointer.answer_date(be, pages, lg, theta, anchors=rules.anchors(pages))
                cas = cascade.answer_date(dict(pages=pages, lang=lg, image_only=t["image_only"]), be, theta, use_metadata=False)
            except llm.CacheMiss:
                s["cache_miss"] += 1
                s["cache_miss_other_extractor"] += t["extractor"] != d.get("extractor")
                if len(miss_examples) < 5:
                    miss_examples.append(dict(doc_id=d["doc_id"], extractor_now=t["extractor"],
                                              extractor_committed=d.get("extractor")))
                continue
            s["rederived"] += 1
            want_p, want_c = c["pointer"], c["cascade"]
            m_now, m_was = p.margin, want_p.get("margin")
            same_m = (m_now == m_was) or (m_now is not None and m_was is not None and abs(m_now - m_was) < 1e-9)
            same_p = p.value == want_p.get("value") and same_m
            same_c = cas.get("value") == want_c.get("value") and cas.get("route") == want_c.get("route")
            if same_p and same_c:
                s["match"] += 1
            else:
                mismatches.append(dict(doc_id=d["doc_id"], pointer_committed=[want_p.get("value"), want_p.get("margin")],
                                       pointer_now=[p.value, p.margin], cascade_committed=want_c.get("value"),
                                       cascade_now=cas.get("value")))
        out["sets"][name] = dict(s, mismatches=mismatches[:20], cache_miss_examples=miss_examples,
                                 secs=round(time.time() - t_set, 1), budget_s=budget_s)
    out["secs"] = round(time.time() - t0, 1)
    return out


def main_rederive(ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    if ctx.get("online") is False:
        return dict(status="SKIP", reason="network down: PDFs not fetched; Apertus decisions replayed from stored rows")
    r = rederive_apertus()
    out = Path(ctx.get("out") or "out")
    out.mkdir(parents=True, exist_ok=True)
    (out / "rederive_apertus.json").write_text(json.dumps(r, indent=1))
    parts, n_re, n_mis, n_miss = [], 0, 0, 0
    for name, s in r["sets"].items():
        n_re += s.get("rederived", 0)
        n_mis += len(s["mismatches"])
        n_miss += s.get("cache_miss", 0)
        parts.append(f"{name} {s.get('match', 0)}/{s.get('rederived', 0)} match of {s['n']} "
                     f"({s.get('cache_miss', 0)} cache miss, {s.get('unreachable', 0)} unreachable, "
                     f"{s.get('not_reached_budget', 0)} over budget)")
    summary = ("Apertus pointer + cascade decisions recomputed from the committed model cache (cache-only, frozen code): "
               + "; ".join(parts))
    status = "FAIL" if n_mis else ("SKIP" if n_re == 0 else ("WARN" if n_miss else "PASS"))
    return dict(status=status, summary=summary, rederived=n_re, mismatches=n_mis, cache_miss=n_miss, secs=r["secs"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "replay"
    res = main({}) if cmd == "replay" else main_rederive({"online": True, "out": ".work/out"})
    print(res["status"], res["summary"])
    sys.exit(1 if res["status"] == "FAIL" else 0)
