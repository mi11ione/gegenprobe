"""EXPLORATORY (PREREG8, added after LOCK8; not pre-registered): the real Apertus v1.5 8B (GGUF Q4_K_M, llama.cpp on a CPU
runner, the fast scorer `gegenprobe.gguf_fast` that cleared the D2 gate) as P7's closed-set verifier of the adapters' review
queue. Question: does the sovereign path (open 8B weights on one 4-vCPU machine, no gateway) reproduce the registered
P7 promotion precision (70B weights via Public AI)?

Same frozen system as P7 (src/gegenprobe/repair/adapters/adjudicate.py, data/p7/p7_config.json): is_answer prompt `a2`,
date choice `b1`, the adapters' own date rule, the same model view, the same eligibility. The free-generation arm is not
run (runner minutes; H3 is not part of this arm). Only the two thresholds are build-specific, as in P6's 8B arm:
θ_A and θ_B are fitted for this build on P7 DEV (80 rows, blind labels data/p7/dev_annotations/gold.jsonl) by the rule
eval/p7/tune.py fixed before the dev labels (θ_A = the smallest GRID value at which no promoted dev row is gold no,
unclear or disputed; θ_B on THETA_B: the most correct promotions at its θ_A, ties the smaller θ_B; `tune.configs`, run
unchanged). Then the test frame (478 rows) is scored once and joined with the committed blind P7 test gold
(data/p7/test_annotations/gold.jsonl) by the registered estimators of eval/p7/hypotheses8.py (H.load, H.est, the
stratified bootstrap, Wilson). Nothing here changes a LOCK8 file or a registered result.

Documents: the extracted texts are never committed. The committed recipe data/p7/gguf8b/rows.jsonl (written once from
the real WORK by `export`, no text) says for each of the 558 rows (80 dev + 478 frame) where its text came from:
  opd_text   OPD's own text of document `opd_doc_id`, re-read from OPD's docs export (files.openparldata.ch, streamed
             once per parliament by gegenprobe.repair.adapters.opd_docs.snapshot)
  opd_file / source   the file at `url`, fetched and extracted by the row's own adapter (Adapter.text: gegenprobe.net,
             RFC 9309 robots.txt, polite pacing, the OPD-copy routing of compliance/mirror.py; pdftotext, tesseract
             deu+fra+ita for scans); the file must be byte-identical (`doc_sha256`); if the original fails or changed,
             OPD's copy (`url_oparl`) is tried under the same byte check. A changed or vanished document is reported,
             never replaced.
Each rebuilt text is compared with the committed `text_sha256`: `text_identical` is recorded per row (the runner's
poppler/tesseract differ from the builds the 70B arm read, as in D3 of eval/prereg/DEVIATIONS.md). Gold-side date checks
(correct_dated, attainable) use the committed outcomes on the original texts (data/p7/date_rule_outcomes.jsonl), as the
registered replay does; the 8B's own date choice is checked on the runner's text.

    export                        DEV ONLY (real WORK, no network): write data/p7/gguf8b/rows.jsonl, each recipe verified
                                  against the local caches (text sha256 reproduced)
    fetch --split S --shard i/n   rebuild the texts of shard i of split S (dev | test) into WORK/adapters/excerpts/
    features --split S --shard i/n   8B answers (is_answer a2, date b1) per row -> results/p7/gguf8b/shards/
    fit                           θ_A, θ_B on the dev shards -> data/p7/gguf8b/theta.json, results/p7/gguf8b/dev_table.json
    merge                         test shards + θ -> results/p7/gguf8b/decisions.jsonl, then `hypotheses`
    hypotheses                    -> results/p7/gguf8b/hypotheses.json (offline: committed P7 key, decisions, gold)

CI: .github/workflows/arms-8b-p7.yml (dev shards -> fit -> six test shards -> merge).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from gegenprobe.compliance import fetchguard
from gegenprobe.paths import DATA, RESULTS, ROOT

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

LABEL = ("EXPLORATORY (PREREG8, added after LOCK8; not pre-registered): real Apertus v1.5 8B (GGUF Q4_K_M, llama.cpp CPU) as "
         "P7's closed-set verifier; frozen prompts a2/b1 and date rule; θ_A/θ_B fitted for this build on P7 dev by the "
         "rule of eval/p7/tune.py; scored against the committed P7 test gold with the estimators of eval/p7/hypotheses8.py")
BUILD = "gguf:apertus-v1.5-8b-text-q4_k_m"
IS_ANSWER, DATE = "a2", "b1"  # the frozen P7 prompts (data/p7/p7_config.json)
N_CTX = 8192  # the longest P7 prompt on the original texts is 4,872 tokens (b1; a2: 4,580; n_prompt of the committed
#                gateway cache, same tokenizer); room for OCR variation; a longer one is refused, never truncated
DIR = DATA / "p7" / "gguf8b"
ROWS = DIR / "rows.jsonl"
# overridable for the offline tests (tests/test_p7_8b.py), so that they never write into the committed places
THETA = Path(os.environ.get("GP_P7_8B_THETA") or DIR / "theta.json")
OUT = Path(os.environ.get("GP_P7_8B_OUT") or RESULTS / "p7" / "gguf8b")
SHARDS = OUT / "shards"
P7 = DATA / "p7"
TARGET_KEYS = ("number", "title", "type", "answer_dates", "gov_dates", "submit_dates")


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _as_read(text: str) -> str:
    """The text as adjudicate.excerpt_text returns it after base.save_excerpt (read back with universal newlines): the
    committed text_sha256 is of this form."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def load_rows(split: str | None = None) -> list[dict]:
    rows = _jsonl(ROWS)
    if not rows:
        raise SystemExit(f"{ROWS.relative_to(ROOT)} missing: run `export` on the machine that holds the P7 WORK")
    return [r for r in rows if split is None or r["split"] == split]


def shard_rows(split: str, shard: str) -> list[dict]:
    """Contiguous blocks of the split's rows in (parliament, affair) order: each OPD docs export and each host is read
    by as few shards as possible."""
    i, n = map(int, shard.split("/"))
    rows = sorted(load_rows(split), key=lambda r: (r["body"], r["affair_id"]))
    return rows[i * len(rows) // n:(i + 1) * len(rows) // n]


def _tag(split: str, shard: str) -> str:
    return f"{split}__{shard.replace('/', '_of_')}"


# ------------------------------------------------------------------------------------------------ export (dev only)
def export() -> dict:
    """DEV ONLY: the recipe for every P7 dev and test-frame row, from the adapters' checkpoints, the OPD docs snapshots
    and the targets in the real WORK; each recipe is replayed against the local caches (no network) and must reproduce
    the committed text sha256."""
    from gegenprobe.repair.adapters import adjudicate as J
    from gegenprobe.repair.adapters import base, opd_docs, run, targets

    dev_key = {(k["body"], k["affair_id"]): k for k in _jsonl(P7 / "dev_key.jsonl")}
    test_key = {(k["body"], k["affair_id"]): k for k in _jsonl(P7 / "test_key.jsonl")}
    frame = {(d["body"], d["affair_id"]): d for d in _jsonl(P7 / "test_decisions.jsonl")}
    review = {(r["body"], r["affair_id"]): r for r in J.review_rows()}
    want = [("dev", k, dev_key[k]["stratum"]) for k in sorted(dev_key)] + \
           [("test", k, frame[k]["reason"]) for k in sorted(frame)]
    states, docs, tgs = {}, {}, {}
    out, bad = [], []
    for split, (body, aid), reason in want:
        if body not in states:
            states[body] = run.load_state(body)
            docs[body] = {d["id"]: d for ds in opd_docs.load(body).values() for d in ds}
            tgs[body] = {x["id"]: x for x in targets.load(body)}
        rec, rv, x = states[body][aid], review[(body, aid)], tgs[body][aid]
        b = rec["best"]
        origin = b.get("origin") or "source"
        held = docs[body].get(b.get("opd_doc_id")) or {}
        r = dict(split=split, body=body, affair_id=aid, reason=reason, text_sha256=rv["text_sha256"],
                 id=(dev_key.get((body, aid)) or test_key.get((body, aid)) or {}).get("id"),
                 origin=origin, opd_doc_id=b.get("opd_doc_id"), url=b.get("url"),
                 doc_sha256=(b.get("meta") or {}).get("sha256"), extractor=(b.get("meta") or {}).get("extractor"),
                 url_oparl=held.get("url_oparl") if origin != "source" else None,
                 target={k: x.get(k) for k in TARGET_KEYS})
        key_sha = (dev_key.get((body, aid)) or test_key.get((body, aid)) or {}).get("text_sha256")
        assert key_sha in (None, r["text_sha256"]), (body, aid)
        if origin == "opd_text":
            t = (held.get("text") or "")
        else:
            hit = base.url_cache_get(r["url"]) if r["url"] else None
            t = hit[0] if hit else ""
        r["recipe_verified_local"] = _sha(_as_read(t)) == r["text_sha256"]
        if not r["recipe_verified_local"]:
            bad.append((body, aid, origin))
        out.append(r)
    _write_jsonl(ROWS, out)
    res = dict(rows=len(out), dev=sum(r["split"] == "dev" for r in out), test=sum(r["split"] == "test" for r in out),
               origins=dict(collections.Counter(r["origin"] for r in out)), recipe_not_reproduced=bad,
               sha256=hashlib.sha256(ROWS.read_bytes()).hexdigest())
    print(json.dumps(res, indent=1))
    return res


# ------------------------------------------------------------------------------------------------ fetch (network)
def _offline_guard() -> None:
    """GP_P7_8B_OFFLINE=1 (tests): any network request raises before a byte leaves."""
    from gegenprobe import net

    def refuse(*a, **kw):
        raise RuntimeError("network disabled (GP_P7_8B_OFFLINE=1)")
    net.open_url = refuse


def fetch(split: str, shard: str) -> dict:
    """Rebuild the texts of one shard into WORK/adapters/excerpts/ (the place adjudicate.excerpt_text reads)."""
    from gegenprobe.repair.adapters import adjudicate as J
    from gegenprobe.repair.adapters import base, opd_docs, registry

    offline =os.environ.get("GP_P7_8B_OFFLINE") == "1"
    if offline:
        _offline_guard()
    rows = shard_rows(split, shard)
    status: dict[str, dict] = {}
    by_body = collections.defaultdict(set)
    for r in rows:
        if r["origin"] == "opd_text":
            by_body[r["body"]].add(r["affair_id"])
    opd: dict[str, dict[int, dict]] = {}
    for body, aids in sorted(by_body.items()):
        try:
            have = opd_docs.load(body)
            if not all(a in have for a in aids):
                if offline:
                    raise RuntimeError("OPD docs snapshot not in WORK")
                print("OPD docs export", body, flush=True)
                opd_docs.snapshot(body, aids)
                have = opd_docs.load(body)
            opd[body] = {d["id"]: d for ds in have.values() for d in ds}
        except Exception as e:  # reported per row below
            print("OPD-EXPORT-FAIL", body, type(e).__name__, str(e)[:160], flush=True)
            opd[body] = {}
    for r in rows:
        key = f"{r['body']}/{r['affair_id']}"
        st = dict(origin=r["origin"])
        text = None
        try:
            if r["origin"] == "opd_text":
                d = opd[r["body"]].get(r["opd_doc_id"])
                if d is None:
                    raise LookupError(f"OPD document {r['opd_doc_id']} not in the docs export")
                text, st["via"] = d.get("text") or "", "opd_docs_export"
            else:
                ad = registry.get(r["body"])
                tries = [u for u in (r["url"], r.get("url_oparl")) if u]
                errs = []
                for u in dict.fromkeys(tries):
                    try:
                        if offline and base.url_cache_get(u) is None:
                            raise RuntimeError("not in the local caches")
                        t, m = ad.text(base.Candidate(url=u, origin=r["origin"], opd_doc_id=r["opd_doc_id"]))
                        if r.get("doc_sha256") and m.get("sha256") and m["sha256"] != r["doc_sha256"]:
                            raise ValueError("document changed at source (sha256)")
                        text = t
                        st.update(via="original" if u == r["url"] else "opd_copy", extractor=m.get("extractor"),
                                  doc_identical=m.get("sha256") == r.get("doc_sha256") if r.get("doc_sha256") else None)
                        break
                    except Exception as e:
                        errs.append(f"{base.failure_reason(e)}: {str(e)[:120]}")
                if text is None:
                    raise LookupError("; ".join(errs) or "no URL")
        except Exception as e:
            st.update(ok=False, error=f"{type(e).__name__}: {str(e)[:240]}")
            status[key] = st
            print("FETCH-FAIL", key, st["error"][:160], flush=True)
            continue
        base.save_excerpt(r["body"], r["affair_id"], text, dict(affair_id=r["affair_id"], number=r["target"]["number"],
                                                                url=r["url"], origin=r["origin"], rebuilt="p7-8b"))
        back = J.excerpt_text(r["body"], r["affair_id"])  # what the 8B will read
        assert back == _as_read(text), key
        st.update(ok=True, text_sha256_ci=_sha(back), text_identical=_sha(back) == r["text_sha256"], chars=len(back))
        status[key] = st
    SHARDS.mkdir(parents=True, exist_ok=True)
    rep = dict(label=LABEL, split=split, shard=shard, rows=len(rows), fetched=sum(s["ok"] for s in status.values()),
               text_identical=sum(bool(s.get("text_identical")) for s in status.values()),
               failed={k: s["error"] for k, s in status.items() if not s["ok"]}, status=status)
    (SHARDS / f"fetch__{_tag(split, shard)}.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    print(f"fetch {split} {shard}: {rep['fetched']}/{len(rows)} texts, {rep['text_identical']} byte-identical to the "
          f"committed sha256; failed: {sorted(rep['failed'])}", flush=True)
    return rep


# ------------------------------------------------------------------------------------------------ model
class TooLong(Exception):
    pass


def backend():
    """The fast GGUF scorer with a context long enough for P7's views; a prompt that would not fit is refused before
    any evaluation (the row is reported `too_long`, never truncated)."""
    from gegenprobe.gguf_fast import GGUFFast
    from gegenprobe.llm import ModelCache

    class P7GGUF(GGUFFast):
        def score(self, user_text, prefix, conts):
            k = ModelCache.key(self.build, "score", dict(user=user_text, prefix=prefix, conts=conts, n_ctx=4096))
            if self.cache.get(k) is None and not self.offline:
                self._load()
                n = len(self._tok(self.render(user_text) + prefix)) + max(len(self._tok(c)) for c in conts) + 8
                if n > self.n_ctx:
                    raise TooLong(f"{n} tokens > n_ctx {self.n_ctx}")
            return super().score(user_text, prefix, conts)

    return P7GGUF(n_ctx=N_CTX)


def _strip(f: dict) -> dict:
    """No document text in any written file: drop each printed date's quoted line (as data/p7/dev_features.jsonl)."""
    for b in f.get("b", {}).values():
        for s in (b.get("spans") or {}).values():
            if s:
                s.pop("line", None)
    return f


def features(split: str, shard: str, be=None, deadline_s: float | None = None) -> dict:
    """8B answers for one shard (resumable: rows already in the shard file are kept). Test shards run only after the fit
    (θ is recorded by hash; the decisions themselves are taken in `merge`)."""
    from gegenprobe.repair.adapters import adjudicate as J

    t0 = time.time()
    deadline_s = deadline_s if deadline_s is not None else float(os.environ.get("GP_P7_8B_DEADLINE_S", "inf"))
    theta_sha = None
    if split == "test":
        if not THETA.exists():
            raise SystemExit("θ not fitted: run `fit` on the dev shards first")
        theta_sha = hashlib.sha256(THETA.read_bytes()).hexdigest()
    rows = shard_rows(split, shard)
    rep = json.loads((SHARDS / f"fetch__{_tag(split, shard)}.json").read_text())["status"]
    dst = SHARDS / f"{_tag(split, shard)}.jsonl"
    done = {(f["body"], f["affair_id"]) for f in _jsonl(dst)}
    be = be or backend()
    not_scored, n_new = {}, 0
    with open(dst, "a", encoding="utf-8") as fh:
        for r in rows:
            key = f"{r['body']}/{r['affair_id']}"
            st = rep.get(key) or dict(ok=False, error="not fetched")
            if (r["body"], r["affair_id"]) in done:
                continue
            if not st["ok"]:
                not_scored[key] = "fetch: " + st["error"][:160]
                continue
            if time.time() - t0 > deadline_s:
                not_scored[key] = "deadline"
                continue
            text = J.excerpt_text(r["body"], r["affair_id"])
            row = dict(body=r["body"], affair_id=r["affair_id"], reason=r["reason"], text_sha256=_sha(text))
            t1 = time.time()
            try:
                f = J.features(be, row, r["target"], (IS_ANSWER,), (DATE,), free=False)
            except TooLong as e:
                not_scored[key] = f"too_long: {e}"
                continue
            except Exception as e:  # one row's failure (e.g. the scorer's tokenisation check) never stops the shard
                not_scored[key] = f"error: {type(e).__name__}: {str(e)[:160]}"
                print("ROW-FAIL", key, not_scored[key], flush=True)
                continue
            f.update(id=r["id"], split=split, text_identical=_sha(text) == r["text_sha256"], seconds=round(time.time() - t1, 1))
            fh.write(json.dumps(_strip(f), ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            n_new += 1
            print(key, f"m_yes={f['a'][IS_ANSWER]['m_yes']:.2f}", f"m_none={f['b'][DATE]['m_none']:.2f}",
                  f"{f['seconds']}s", flush=True)
    scored = len(_jsonl(dst))
    summ = dict(label=LABEL, build=getattr(be, "build", "?"), split=split, shard=shard, assigned=len(rows), scored=scored,
                scored_now=n_new, not_scored=not_scored, theta_sha256=theta_sha, wall_s=round(time.time() - t0, 1),
                s_per_row=round((time.time() - t0) / n_new, 1) if n_new else None, n_ctx=N_CTX)
    (SHARDS / f"{_tag(split, shard)}.json").write_text(json.dumps(summ, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summ.items() if k != "not_scored"}), "not scored:", sorted(not_scored), flush=True)
    return summ


def _merged(split: str) -> list[dict]:
    feats = {}
    for p in sorted(SHARDS.glob(f"{split}__*.jsonl")):
        for f in _jsonl(p):
            feats[(f["body"], f["affair_id"])] = f
    return [feats[k] for k in sorted(feats)]


# ------------------------------------------------------------------------------------------------ θ fit (offline)
def _subprocess(cmd: list[str], work: Path | None = None) -> None:
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]), PYTHONDONTWRITEBYTECODE="1")
    if work is not None:
        env["GP_WORK"] = str(work)
    p = subprocess.run([sys.executable, "-m", "eval.p7.run_8b", *cmd], env=env, cwd=ROOT, timeout=7200)
    if p.returncode:
        raise SystemExit(f"{cmd[0]} failed (exit {p.returncode})")


def _patch_offline() -> None:
    """Committed date-rule outcomes for the gold dates (eval/p7/offline.py), and OPD targets for tune's attainable set."""
    from eval.p7 import offline
    from eval.p7 import tune

    offline._patch()

    class _Targets(dict):
        def __missing__(self, k):
            return {}
    tune._targets = lambda body: _Targets()


def fit() -> dict:
    feats = _merged("dev")
    if not feats:
        raise SystemExit(f"no dev shard files in {SHARDS}")
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / "features_dev.jsonl"
    _write_jsonl(src, feats)
    _subprocess(["_fit", str(src)])
    res = json.loads(THETA.read_text())
    print(json.dumps({k: res[k] for k in ("theta_a", "theta_b", "dev")}, indent=1))
    return res


def _fit_inner(src: Path) -> None:
    from eval.p7 import tune

    _patch_offline()
    feats = _jsonl(src)
    for f in feats:  # the free arm is not run on the 8B; tune.arms_of reads it, so it is marked absent
        f.setdefault("free", dict(answer="not_run", date=None, rule=[None, False]))
    tmp = Path(tempfile.mkdtemp(prefix="p7_8b_fit"))
    (tmp / "ann").mkdir()
    shutil.copyfile(P7 / "dev_annotations" / "gold.jsonl", tmp / "ann" / "gold.jsonl")
    gold = tune.load_ann(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    cf = tune.configs(feats, gold)  # every θ_B of tune.THETA_B, θ_A by tune's pre-fixed rule (tune.rule_theta)
    best = sorted(cf, key=lambda c: (-c["correct"], c["is_answer"] != "a1", c["theta_b"]))[0]  # tune.table's choice
    ok = best["theta_a"] is not None
    dev_ids = {r["id"] for r in load_rows("dev")}
    res = dict(label=LABEL, build=BUILD, is_answer=IS_ANSWER, date=DATE,
               theta_a=best["theta_a"], theta_b=best["theta_b"] if ok else None,
               rule="eval/p7/tune.py unchanged: per θ_B in tune.THETA_B, θ_A = the smallest tune.GRID value with no promoted "
                    "dev row gold no/unclear/disputed (tune.rule_theta); chosen: most correct promotions at its θ_A, ties "
                    "the smaller θ_B (the is_answer prompt is fixed at the frozen a2)",
               no_theta_note=None if ok else "no grid value satisfies the rule for any θ_B: the 8B promotes nothing",
               dev=dict((k, best[k]) for k in ("promoted", "correct", "precision", "wilson", "recall_all",
                                               "recall_attainable", "date_hit")),
               dev_scored=len(feats), dev_not_scored=sorted(dev_ids - {f["id"] for f in feats}),
               dev_text_identical=sum(bool(f.get("text_identical")) for f in feats),
               reference_70b=dict((k, json.loads((P7 / "p7_config.json").read_text())[k]) for k in ("theta_a", "theta_b")),
               features_sha256=hashlib.sha256(src.read_bytes()).hexdigest())
    DIR.mkdir(parents=True, exist_ok=True)
    THETA.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    (OUT / "dev_table.json").write_text(json.dumps(dict(label=LABEL, configs=cf, chosen=res), indent=1, sort_keys=True) + "\n")


# ------------------------------------------------------------------------------------------------ merge + analysis
def cfg_8b(theta: dict):
    from gegenprobe.repair.adapters import adjudicate as J
    return J.Config(theta_a=theta["theta_a"], theta_b=theta["theta_b"], is_answer=IS_ANSWER, date=DATE, name="p7-8b")


def decisions(feats: list[dict], theta: dict) -> list[dict]:
    """One line per test-frame row (no text): scored or why not, the 8B decision, and the gate + any-date variant."""
    from gegenprobe.repair.adapters import adjudicate as J

    by = {(f["body"], f["affair_id"]): f for f in feats}
    status = {}
    for p in sorted(SHARDS.glob("fetch__test__*.json")):
        status.update(json.loads(p.read_text())["status"])
    not_scored = {}
    for p in sorted(SHARDS.glob("test__*.json")):
        not_scored.update(json.loads(p.read_text())["not_scored"])
    cfg = cfg_8b(theta) if theta["theta_a"] is not None else None
    out = []
    for r in sorted(load_rows("test"), key=lambda r: (r["body"], r["affair_id"])):
        f = by.get((r["body"], r["affair_id"]))
        key = f"{r['body']}/{r['affair_id']}"
        d = dict(body=r["body"], affair_id=r["affair_id"], reason=r["reason"], scored=f is not None)
        if f is None:
            d.update(p7_8b=False, why_8b="not_scored", not_scored=not_scored.get(key) or (status.get(key) or {}).get("error")
                     or "not run", gate_rule_any_8b=False)
        else:
            a, b = f["a"][IS_ANSWER], f["b"][DATE]
            dec = J.decide(f, cfg) if cfg else dict(promote=False, why="no_theta", date=None, date_class=None)
            any_pass = any(ok for _c, ok in b["rule_all"].values())
            d.update(p7_8b=bool(dec["promote"]), why_8b=dec["why"], date_8b=dec["date"], class_8b=dec["date_class"],
                     m_yes_8b=round(a["m_yes"], 4), m_none_8b=round(b["m_none"], 4), n_dates_8b=f["n_dates"],
                     gate_rule_any_8b=bool(cfg) and a["m_yes"] > cfg.theta_a and any_pass,
                     text_identical=bool(f.get("text_identical")))
        out.append(d)
    return out


def merge() -> dict:
    feats = _merged("test")
    if not feats:
        raise SystemExit(f"no test shard files in {SHARDS}")
    theta = json.loads(THETA.read_text())
    _write_jsonl(OUT / "features_test.jsonl", feats)
    dec = decisions(feats, theta)
    _write_jsonl(OUT / "decisions.jsonl", dec)
    print(f"{sum(d['scored'] for d in dec)}/{len(dec)} frame rows scored; 8B promotes {sum(d['p7_8b'] for d in dec)}")
    return hypotheses()


def hypotheses(dec_path: Path | None = None, out: Path | None = None) -> dict:
    """Run the analysis on a scratch WORK laid out from the committed P7 copies (eval/p7/replay8.LAYOUT), so that
    eval/p7/hypotheses8.load() reads, hash-checks and weights exactly the rows of the registered analysis."""
    from eval.p7 import replay8

    dec_path = dec_path or OUT / "decisions.jsonl"
    out = out or OUT / "hypotheses.json"
    tmp = Path(tempfile.mkdtemp(prefix="p7_8b_hyp"))
    try:
        for s, d in replay8.LAYOUT.items():
            (tmp / "work" / d).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(P7 / s, tmp / "work" / d)
        _subprocess(["_hyp", str(dec_path), str(out), str(THETA)], work=tmp / "work")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    res = json.loads(out.read_text())
    print(json.dumps(dict(H1_8b_on_p7_sample=res["H1_8b_on_p7_sample"], H4_8b=res["H4_8b"]["supported_analogue"],
                          checks=res["checks"]), indent=1))
    return res


def _r(x, nd=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, nd)


def _hyp_inner(dec_path: Path, out: Path, theta_path: Path) -> None:
    from eval.p7 import hypotheses8 as H
    from gegenprobe.stats import wilson

    _patch_offline()
    rows, smp = H.load()  # registered rows: committed key + decisions (hash-checked), gold, weights, correct(_dated)
    dec = {(d["body"], d["affair_id"]): d for d in _jsonl(dec_path)}
    ra = {(o["body"], o["affair_id"]): o for o in _jsonl(P7 / "rule_any_outcomes.jsonl") if o["scope"] == "frame"}
    if len(dec) != smp["frame"]:
        raise SystemExit(f"{len(dec)} decisions for a frame of {smp['frame']}")
    for r in rows:
        d = dec[(r["body"], r["affair_id"])]
        r.update(p7_8b=d["p7_8b"], gate_rule_any_8b=d["gate_rule_any_8b"], scored_8b=d["scored"], date_8b=d.get("date_8b"),
                 rule_any_view=ra[(r["body"], r["affair_id"])]["rule_any_view"])
    theta = json.loads(theta_path.read_text())
    frame_counts = dict(p7=smp["arms_on_frame"]["p7"], trivial=smp["arms_on_frame"]["trivial"],
                        p7_8b=sum(d["p7_8b"] for d in dec.values()),
                        gate_rule_any_8b=sum(d["gate_rule_any_8b"] for d in dec.values()),
                        rule_any_view=sum(ra[k]["rule_any_view"] for k in dec))
    names = dict(p7="registered P7 (70B weights via Public AI; committed decisions)",
                 p7_8b="the same frozen system on the local 8B GGUF with its own θ_A/θ_B",
                 trivial="no model: some printed date equals an OPD answer event",
                 rule_any_view="no model (ablation, eval/p7/posthoc_r8.py): some printed date of the view passes the date rule",
                 gate_rule_any_8b="8B is_answer gate (m_yes > θ_A) + some printed date of the view passes the date rule")
    arms = {}
    for arm in names:
        arms[arm] = dict(
            what=names[arm], promoted_in_frame=frame_counts[arm],
            promoted_annotated=sum(1 for r in rows if r[arm]),
            precision=H.est(rows, lambda rs, a=arm: H._ratio(rs, a, "correct")),
            precision_dated=H.est(rows, lambda rs, a=arm: H._ratio(rs, a, "correct_dated")),
            recall_all=H.est(rows, lambda rs, a=arm: H._recall(rs, a, "correct")),
            recall_attainable=H.est(rows, lambda rs, a=arm: H._recall(rs, a, "correct_dated")),
            correct_rows_in_frame=H.est(rows, lambda rs, a=arm: H._total(rs, a, "correct")),
            correct_dated_rows_in_frame=H.est(rows, lambda rs, a=arm: H._total(rs, a, "correct_dated")))
    # H1 analogue on the 120 sampled P7 rows (the registered p7 stratum): which of them the 8B also promotes, and how
    # many of those are correct (a conditional precision: rows both builds promote)
    p7s = [r for r in rows if r["stratum"] == "p7"]
    pr = [r for r in p7s if r["p7_8b"]]
    k, n = sum(r["correct"] for r in pr), len(pr)
    lb, ub = wilson(k, n) if n else (0.0, 1.0)
    h1s = dict(sampled_p7_rows=len(p7s), scored_8b=sum(r["scored_8b"] for r in p7s), promoted_8b=n, correct=k,
               precision=_r(k / n) if n else None, wilson95=[_r(lb), _r(ub)],
               precision_dated=_r(sum(r["correct_dated"] for r in pr) / n) if n else None,
               date_hit=sum(1 for r in pr if r["date_8b"] in r["gold_dates"]),
               same_date_as_70b=sum(1 for r in pr if r["date_8b"] == r["p7_date"]),
               errors=[dict(id=r["id"], gold=r["gold"], reason=r["reason"]) for r in pr if not r["correct"]],
               meets_h1_bar=n >= H.H1_MIN_N and lb >= H.H1_LB, bar=f"Wilson 95% lower bound >= {H.H1_LB} with >= "
               f"{H.H1_MIN_N} promoted rows judged (PREREG8 H1, applied here as a yardstick, not a test)",
               registered_70b=dict(n=len(p7s), correct=sum(r["correct"] for r in p7s)))
    # the 8B's own promotions over the frame: weighted precision (the registered design weights N_s/n_s, stratified
    # bootstrap); rows outside the annotated packets are represented by their stratum's weight
    pw = arms["p7_8b"]["precision"]
    h1f = dict(promoted_in_frame=frame_counts["p7_8b"], promoted_annotated=arms["p7_8b"]["promoted_annotated"],
               by_stratum=dict(collections.Counter(r["stratum"] for r in rows if r["p7_8b"])),
               precision=pw, precision_dated=arms["p7_8b"]["precision_dated"],
               lower_bound_at_least_0_90=pw["ci95"][0] is not None and pw["ci95"][0] >= H.H1_LB)
    diff = H.est(rows, lambda rs: H._ratio(rs, "p7_8b", "correct_dated") - H._ratio(rs, "trivial", "correct_dated"))
    h4 = dict(difference_precision_dated_8b_minus_trivial=diff,
              supported_analogue=diff["ci95"][0] is not None and diff["ci95"][0] > 0,
              statement="PREREG8 H4 with the 8B in place of p7: the stratified bootstrap 95% interval excludes 0 above")
    vs70 = H.est(rows, lambda rs: H._ratio(rs, "p7_8b", "correct_dated") - H._ratio(rs, "p7", "correct_dated"))
    p7_70 = {(x["body"], x["affair_id"]): x["p7"] for x in _jsonl(P7 / "test_decisions.jsonl")}
    agree = collections.Counter((p7_70[k], d["p7_8b"]) for k, d in dec.items() if d["scored"])
    # consistency: the scaffold recomputes the registered 70B figures exactly
    reg = json.loads((RESULTS / "p7" / "p7_hypotheses.json").read_text())
    same = all(arms["p7"][m] == reg["arms"]["p7"][m] for m in ("precision", "precision_dated", "recall_all", "recall_attainable"))
    h4_70 = H.est(rows, lambda rs: H._ratio(rs, "p7", "correct_dated") - H._ratio(rs, "trivial", "correct_dated"))
    same_h4 = h4_70 == reg["H4"]["difference_precision_dated_p7_minus_trivial"]
    res = dict(
        label=LABEL, build=BUILD, theta=dict((k, theta.get(k)) for k in ("theta_a", "theta_b", "is_answer", "date", "dev")),
        H1_8b_on_p7_sample=h1s, H1_8b_frame=h1f, H4_8b=h4, precision_dated_8b_minus_70b=vs70, arms=arms,
        agreement_on_scored_frame_rows={f"70b_{'yes' if a else 'no'}__8b_{'yes' if b else 'no'}": v
                                        for (a, b), v in sorted(agree.items())},
        coverage=dict(frame=len(dec), scored=sum(d["scored"] for d in dec.values()),
                      text_identical=sum(bool(d.get("text_identical")) for d in dec.values()),
                      annotated=len(rows), annotated_scored=sum(r["scored_8b"] for r in rows),
                      not_scored={f"{b}/{a}": d.get("not_scored") for (b, a), d in sorted(dec.items()) if not d["scored"]},
                      note="a row the 8B could not score (document unreachable or changed, prompt too long, deadline) "
                           "counts as not promoted"),
        checks=dict(registered_70b_arm_reproduced=same, registered_h4_reproduced=same_h4),
        method="eval/p7/hypotheses8.py unchanged (load, est, _ratio, _recall, _total, boot: B = 10,000, seed 20261014) on "
               "the committed key, decisions and gold (hash-checked against results/p7/test_sample.json); gold date checks "
               "from data/p7/date_rule_outcomes.jsonl; the ablation from data/p7/rule_any_outcomes.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------------------------------ cli
def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_fit"]:
        _fit_inner(Path(argv[1]))
        return 0
    if argv[:1] == ["_hyp"]:
        _hyp_inner(Path(argv[1]), Path(argv[2]), Path(argv[3]))
        return 0
    ap = argparse.ArgumentParser(description="EXPLORATORY: the local Apertus 8B on P7")
    ap.add_argument("cmd", choices=["export", "fetch", "features", "fit", "merge", "hypotheses"])
    ap.add_argument("--split", choices=["dev", "test"], default="test")
    ap.add_argument("--shard", default="0/1")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        export()
    elif a.cmd == "fetch":
        fetch(a.split, a.shard)
    elif a.cmd == "features":
        features(a.split, a.shard)
    elif a.cmd == "fit":
        fit()
    elif a.cmd == "merge":
        merge()
    else:
        hypotheses()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
