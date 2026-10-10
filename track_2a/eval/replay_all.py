"""`make run` replay of all four pre-registrations, from committed files only, plus re-derivation of Apertus decisions.

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


def replay_locks() -> list[dict]:
    import importlib
    out = []
    for name, mod in (("LOCK (P1)", "eval.prereg.lock"), ("LOCK2 (P2)", "eval.prereg2.lock2"),
                      ("LOCK3 (P3)", "eval.prereg3.lock3"), ("LOCK4 (P4)", "eval.prereg4.lock4")):
        changed = importlib.import_module(mod).check()
        out.append(dict(test=name, ok=not changed, detail=[f"changed: {c}" for c in changed]))
    return out


def replay() -> dict:
    t0 = time.time()
    tests = replay_p1_p2() + replay_p3() + replay_p4() + replay_hypotheses() + replay_locks()
    fails = [t for t in tests if not t["ok"]]
    return dict(tests=tests, n=len(tests), failing=len(fails), secs=round(time.time() - t0, 1))


def main(ctx: dict | None = None) -> dict:
    r = replay()
    for t in r["tests"]:
        print(f"    {'PASS' if t['ok'] else 'FAIL'}  {t['test']}" + ("" if t["ok"] else f"  {t['detail'][:3]}"), flush=True)
    s = (f"{r['n'] - r['failing']}/{r['n']} replay tests pass "
         "(P1-P4 re-scored from committed labels, 4 hypotheses scripts, 4 locks)")
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
